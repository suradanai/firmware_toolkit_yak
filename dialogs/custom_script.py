import os, tempfile, subprocess
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, QTextEdit, QHBoxLayout, QPushButton, QMessageBox)

class CustomScriptDialog(QDialog):
    def __init__(self, parent, rootfs_part):
        super().__init__(parent)
        self.setWindowTitle("Run Custom Script / Command")
        self.resize(900, 650)
        self.parent_win = parent
        self.rootfs_part = rootfs_part
        self._build_ui(); self._prepare_rootfs()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        desc = QLabel("เครื่องมือนี้จะ extract rootfs (ถ้ายัง) ไปยัง temp dir และให้รันคำสั่ง / สคริปต์เบื้องต้น")
        desc.setWordWrap(True); lay.addWidget(desc)
        mode_row = QHBoxLayout(); mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox(); self.mode_combo.addItems(["shell", "python", "grep"]); mode_row.addWidget(self.mode_combo); mode_row.addStretch(); lay.addLayout(mode_row)
        self.input_edit = QTextEdit(); self.input_edit.setPlaceholderText("เช่น\n# shell\nfind . -maxdepth 2 -type f | head\n\n# python\nfor p in list_files('.')[:10]:\n    print(p)\n\n# grep mode: ใส่ pattern หนึ่งบรรทัด เช่น root:x:")
        lay.addWidget(self.input_edit,1)
        btn_row = QHBoxLayout(); self.btn_run = QPushButton("Run"); self.btn_run.clicked.connect(self.run_action); self.btn_close = QPushButton("Close"); self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_run); btn_row.addWidget(self.btn_close); btn_row.addStretch(); lay.addLayout(btn_row)
        self.out_edit = QTextEdit(); self.out_edit.setReadOnly(True); lay.addWidget(self.out_edit,2)

    def log(self, msg):
        self.out_edit.append(msg); self.out_edit.ensureCursorVisible()
        if hasattr(self.parent_win,'log'): self.parent_win.log(f"[CustomScript] {msg}")

    def _prepare_rootfs(self):
        part_index = self.parent_win.rootfs_part_spin.value() - 1
        use_cache=False
        if getattr(self.parent_win,'edit_cache_dir',None) and getattr(self.parent_win,'edit_cache_part_index',None)==part_index:
            if os.path.isdir(self.parent_win.edit_cache_dir): self.work_dir = self.parent_win.edit_cache_dir; use_cache=True
        if use_cache: self.log("ใช้ rootfs cache เดิม"); return
        tmp_work = tempfile.mkdtemp(prefix="custom_script_"); self.parent_win.log(f"[TEMP] custom script workspace: {tmp_work}")
        rootfs_bin = os.path.join(tmp_work,"rootfs.bin")
        with open(self.parent_win.fw_path,'rb') as f:
            f.seek(self.rootfs_part['offset']); blob = f.read(self.rootfs_part['size'])
        with open(rootfs_bin,'wb') as f: f.write(blob)
        extract_dir = os.path.join(tmp_work,'extract'); os.makedirs(extract_dir, exist_ok=True)
        from app import extract_rootfs
        ok, err = extract_rootfs(self.rootfs_part['fs'], rootfs_bin, extract_dir, self.log)
        if not ok: self.log(f"❌ extract ไม่สำเร็จ: {err}"); self.work_dir=None
        else: self.work_dir = extract_dir; self.log(f"เตรียม rootfs สำหรับ script: {extract_dir}")
        self._temp_workspace = tmp_work

    def closeEvent(self, event):
        if hasattr(self,'_temp_workspace'):
            try: import shutil; shutil.rmtree(self._temp_workspace, ignore_errors=True)
            except: pass
        super().closeEvent(event)

    def _list_files(self, base):
        out=[]
        for root, dirs, files in os.walk(base):
            for f in files:
                rel=os.path.relpath(os.path.join(root,f), base); out.append(rel)
                if len(out)>=10000: return out
        return out

    def run_action(self):
        if not getattr(self,'work_dir',None): QMessageBox.warning(self,"Run","ยังไม่มี rootfs พร้อมใช้งาน"); return
        mode=self.mode_combo.currentText(); code=self.input_edit.toPlainText().strip()
        if not code: QMessageBox.information(self,"Run","ไม่มี input"); return
        self.out_edit.clear()
        if mode=='shell': self._run_shell(code)
        elif mode=='python': self._run_python(code)
        else: self._run_grep(code)

    def _run_shell(self, cmd):
        if len(cmd)>4000: self.log("คำสั่งยาวเกิน ตัดออก"); cmd=cmd[:4000]
        try:
            proc=subprocess.Popen(cmd, cwd=self.work_dir, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out,_=proc.communicate(timeout=30); self.log(out or "(no output)"); self.log(f"[exit={proc.returncode}]")
        except subprocess.TimeoutExpired: self.log("Timeout (30s)")
        except Exception as e: self.log(f"error: {e}")

    def _run_python(self, code):
        ns={'__builtins__': {k:getattr(__builtins__,k) for k in ['len','range','print','open','enumerate','min','max','sum','sorted','any','all'] if k in __builtins__},
            'WORK_DIR': self.work_dir,
            'list_files': lambda p='.' : self._list_files(os.path.join(self.work_dir,p)) if os.path.isdir(os.path.join(self.work_dir,p)) else [],
            'read_text': lambda p: open(os.path.join(self.work_dir,p),'r',encoding='utf-8',errors='ignore').read(2048),
        }
        out_lines=[]
        def _printer(*a,**kw): out_lines.append(' '.join(str(x) for x in a))
        ns['print']=_printer
        try:
            exec(code, ns, {})
            for line in out_lines: self.log(line)
            self.log("[python done]")
        except Exception as e: self.log(f"Exception: {e}")

    def _run_grep(self, pattern):
        pat=pattern.strip()
        if not pat: self.log("ไม่มี pattern"); return
        count=0
        try:
            for root, dirs, files in os.walk(self.work_dir):
                for f in files:
                    fp=os.path.join(root,f)
                    try:
                        with open(fp,'rb') as fh: data=fh.read(4096)
                        if pat.lower().encode('utf-8') in data.lower():
                            rel=os.path.relpath(fp,self.work_dir); self.log(rel); count+=1
                            if count>=200: self.log('[เก็บ 200 รายการแรก]'); return
                    except Exception: continue
            self.log(f"[พบ {count} matches]")
        except Exception as e: self.log(f"grep error: {e}")
