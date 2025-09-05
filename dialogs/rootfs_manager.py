from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QMessageBox, QFileDialog, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
import os, datetime, shutil, subprocess, struct, threading
from core.partition_scan import scan_rootfs_partitions, extract_partition_raw
from core.binwalk_utils import get_binwalk

class _BinwalkWorker(QThread):
    """Background worker to run binwalk and parse output so UI doesn't freeze.

    Adds cancellable support: terminate() sets a flag; we kill the subprocess.
    """
    finished_signal = Signal(bool, list, str)  # ok, entries, err

    def __init__(self, binwalk_path: str, fw_path: str, extra_args=None):
        super().__init__()
        self.binwalk_path = binwalk_path
        self.fw_path = fw_path
        self._proc = None
        self._cancel = threading.Event()
        self._extra_args = extra_args or []

    def cancel(self):
        self._cancel.set()
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.kill()
        except Exception:
            pass

    def run(self):  # executes in background thread
        try:
            cmd = [self.binwalk_path, '--term'] + self._extra_args + [self.fw_path]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            collected = []
            # Stream lines to allow faster cancel
            while True:
                if self._cancel.is_set():
                    raise RuntimeError('cancelled')
                line = self._proc.stdout.readline() if self._proc.stdout else ''
                if not line:
                    if self._proc.poll() is not None:
                        break
                    continue
                collected.append(line)
            out = ''.join(collected)
            if self._cancel.is_set():
                raise RuntimeError('cancelled')
            entries = _parse_binwalk_basic(out)
            self.finished_signal.emit(True, entries, '')
        except Exception as e:
            self.finished_signal.emit(False, [], str(e))


def _parse_binwalk_basic(out: str):
    """Parse minimal binwalk output -> list of {offset, desc, fs} for known FS types."""
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line or not line[0:1].isdigit():
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            off = int(parts[0])
        except ValueError:
            continue
        desc = parts[1]
        low = desc.lower()
        fstype = None
        if 'squashfs' in low:
            fstype = 'squashfs'
        elif 'cramfs' in low:
            fstype = 'cramfs'
        elif 'jffs2' in low:
            fstype = 'jffs2'
        elif 'yaffs' in low:
            fstype = 'yaffs2'
        if not fstype:
            continue
        entries.append({'offset': off, 'desc': desc, 'fs': fstype})
    return entries


class RootFSManagerDialog(QDialog):
    def __init__(self, parent, fw_path: str, log_func):
        super().__init__(parent)
        self.fw_path = fw_path
        self.log = log_func
        self.setWindowTitle("RootFS / Partition Manager")
        self.resize(880, 520)
        self.parts = []
        self._build_ui()
        self._scan()

    def _build_ui(self):
        """Build dialog UI (rescan, binwalk merge, auto merge toggle, editor, resplice)."""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Firmware: {os.path.basename(self.fw_path)}"))

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Index","FS","Offset","Size","TrueSize","Desc"])
        layout.addWidget(self.table, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_rescan = QPushButton("Rescan")
        self.btn_binwalk_merge = QPushButton("Binwalk Merge")
        self.btn_binwalk_quick = QPushButton("BW Quick")
        self.chk_auto_merge = QCheckBox("Auto Merge")
        self.chk_auto_merge.setToolTip("Run Binwalk Merge automatically the first time this dialog opens")
        self.chk_auto_merge.setChecked(True)
        self.btn_extract = QPushButton("Extract Selected")
        self.btn_open_editor = QPushButton("Open in RootFS Editor")
        self.btn_resplice = QPushButton("Re-splice Patched RootFS")
        self.btn_close = QPushButton("Close")
        for w in (self.btn_rescan, self.btn_binwalk_quick, self.btn_binwalk_merge, self.chk_auto_merge,
                  self.btn_extract, self.btn_open_editor, self.btn_resplice):
            btn_row.addWidget(w)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        # Signals (properly indented inside _build_ui)
        self.btn_rescan.clicked.connect(self._scan)
        self.btn_binwalk_quick.clicked.connect(lambda: self._binwalk_merge_clicked(signature_only=True))
        self.btn_binwalk_merge.clicked.connect(self._binwalk_merge_clicked)
        self.btn_export_json = QPushButton('Save JSON')
        btn_row.addWidget(self.btn_export_json)
        self.btn_export_json.clicked.connect(self._export_partitions_json)
        self.btn_export_json.setToolTip('Export partition table to JSON for reproducibility')
        self.btn_extract.clicked.connect(self._extract_selected)
        self.btn_open_editor.clicked.connect(self._open_selected_editor)
        self.btn_resplice.clicked.connect(self._resplice_selected)
        self.btn_close.clicked.connect(self.close)

        # Selection behavior
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)

    def _scan(self):
        self.log('[PART] scanning partitions ...')
        self.parts = scan_rootfs_partitions(self.fw_path, self.log)
        # sync to parent context if available
        try:
            if hasattr(self.parent(), 'fw_ctx'):
                self.parent().fw_ctx.partitions = list(self.parts)
        except Exception:
            pass
        self._refresh_table()
        self.log(f"[PART] found {len(self.parts)} entries")
        # Auto binwalk merge on first load (only once per dialog)
        if not hasattr(self, '_auto_merged'):
            self._auto_merged = True
            if self.chk_auto_merge.isChecked():
                try:
                    if get_binwalk():
                        self._start_binwalk_merge(async_run=True)
                except Exception:
                    pass

    def _selected_part(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return None
        r = sorted(rows)[0]
        if r < 0 or r >= len(self.parts):
            return None
        return self.parts[r]

    # ---- Binwalk Merge ----
    # ---- Async Binwalk Merge Handling ----
    def _binwalk_merge_clicked(self, signature_only: bool = False):
        """Handle Binwalk Merge / Quick button.

        signature_only=True => use faster signature scan (adds --signature) if supported.
        If a scan is already running, this acts as a cancel toggle.
        """
        if getattr(self, '_bw_running', False):
            self.log('[PART] cancelling binwalk ...')
            try:
                self._bw_worker.cancel()
            except Exception:
                pass
            return
        extra_args = []
        if signature_only:
            extra_args = ['--signature']  # safe even if unsupported; binwalk will ignore
        self._start_binwalk_merge(async_run=True, extra_args=extra_args, quick=signature_only)

    def _start_binwalk_merge(self, async_run=False, extra_args=None, quick: bool = False):
        if getattr(self, '_bw_running', False):
            return
        bw = get_binwalk()
        if not bw:
            QMessageBox.information(self, 'Binwalk', 'ไม่พบ binwalk ใน PATH (ติดตั้งด้วย apt หรือ pip)')
            return
        label = 'binwalk quick' if quick else 'binwalk'
        if async_run:
            self._bw_running = True
            self.btn_binwalk_merge.setText('Cancel Binwalk')
            self.log(f'[PART] {label} merge (async) ... args={extra_args or []}')
            self._bw_worker = _BinwalkWorker(bw, self.fw_path, extra_args=extra_args or [])
            self._bw_worker.finished_signal.connect(self._on_bw_done)
            self._bw_worker.start()
        else:
            self._run_binwalk_sync(bw)

    def _on_bw_done(self, ok: bool, entries: list, err: str):
        self._bw_running = False
        self.btn_binwalk_merge.setText('Binwalk Merge')
        self.btn_binwalk_merge.setEnabled(True)
        if not ok:
            if err and err != 'cancelled':
                QMessageBox.critical(self,'Binwalk',err)
            return
        if ok:
            self._consume_binwalk_entries(entries)

    def _run_binwalk_sync(self, bw_path: str):
        try:
            self.log('[PART] running binwalk (sync) ...')
            proc = subprocess.run([bw_path, '--term', self.fw_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
            out = proc.stdout or ''
        except Exception as e:
            QMessageBox.critical(self, 'Binwalk', f'รัน binwalk ล้มเหลว: {e}')
            return
        entries = _parse_binwalk_basic(out)
        if not entries:
            QMessageBox.information(self, 'Binwalk', 'ไม่พบไฟล์ระบบที่สามารถ merge ได้')
            return
        self._consume_binwalk_entries(entries)

    def _consume_binwalk_entries(self, entries):
        existing_offsets = {p['offset'] for p in self.parts}
        try:
            fw_size = os.path.getsize(self.fw_path)
        except Exception:
            fw_size = 0
        # Filter only new
        new_entries = [e for e in entries if e['offset'] not in existing_offsets]
        if not new_entries:
            QMessageBox.information(self,'Binwalk Merge','ไม่มีรายการใหม่ (อาจซ้ำอยู่แล้ว)')
            return
        # Reuse sizing logic from original
        candidate_offsets = sorted({e['offset'] for e in new_entries} | existing_offsets)
        added = 0
        next_index = (max((p.get('index',0) for p in self.parts), default=-1) + 1) if self.parts else 0
        for e in sorted(new_entries, key=lambda x:x['offset']):
            # find next higher offset
            nxt = None
            for o in candidate_offsets:
                if o > e['offset']:
                    nxt = o; break
            if nxt is None:
                nxt = fw_size
            gap_size = max(0, (nxt - e['offset'])) if fw_size else 0
            header_size = None
            try:
                with open(self.fw_path,'rb') as f:
                    f.seek(e['offset']); head = f.read(128)
                if e['fs']=='squashfs' and len(head) >= 0x30 and (head[:4] in (b'hsqs', b'sqsh')):
                    header_size = struct.unpack('<Q', head[0x28:0x30])[0] or None
                elif e['fs']=='cramfs' and len(head) >= 0x20 and head[:4] in (b'\x45\x3d\xcd\x28', b'\x28\xcd\x3d\x45'):
                    header_size = struct.unpack('<I', head[4:8])[0] or None
            except Exception:
                pass
            reported_size = header_size if header_size else gap_size
            if header_size and gap_size and header_size > gap_size:
                reported_size = gap_size  # clamp
            if fw_size and gap_size > fw_size:
                gap_size = fw_size - e['offset']
            if gap_size <= 0:
                continue
            part = {
                'index': next_index,
                'fs': e['fs'],
                'offset': e['offset'],
                'size': gap_size,
                'reported_size': reported_size,
                'header_size': header_size,
                'desc': e['desc'] + (' [BW][HDR]' if header_size else ' [BW]')
            }
            self.parts.append(part)
            existing_offsets.add(e['offset'])
            candidate_offsets.append(e['offset']); candidate_offsets.sort()
            next_index += 1; added += 1
            if header_size and header_size > gap_size and gap_size < 4096:
                self.log(f"[PART][WARN] header {header_size} > gap {gap_size} (<4K) at 0x{e['offset']:X}; clamped")
        if added:
            self._refresh_table()
            self.log(f'[PART] binwalk merge added {added} partitions')
            QMessageBox.information(self,'Binwalk Merge', f'เพิ่ม {added} รายการจาก binwalk')
        else:
            QMessageBox.information(self,'Binwalk Merge','ไม่มีรายการใหม่ (อาจหา size ไม่ได้)')

    # (removed duplicate legacy _binwalk_merge implementation)

    def _extract_selected(self):
        part = self._selected_part()
        if not part:
            QMessageBox.information(self,'Extract','Select a row first')
            return
        out_dir = QFileDialog.getExistingDirectory(self,'Select output directory')
        if not out_dir:
            return
        size = part['reported_size'] or part['size']
        out_file = os.path.join(out_dir, f"part_{part['index']}_{part['fs']}_0x{part['offset']:X}.bin")
        extract_partition_raw(self.fw_path, part['offset'], size, out_file)
        self.log(f"[PART] extracted -> {out_file}")
        QMessageBox.information(self,'Extract', f"Saved: {out_file}")

    def _open_selected_editor(self):
        from dialogs.rootfs_editor import RootFSEditDialog
        part = self._selected_part()
        if not part:
            QMessageBox.information(self,'RootFS','Select a row first')
            return
        if part['fs'] not in ('squashfs','cramfs','jffs2','yaffs2'):
            QMessageBox.warning(self,'RootFS','Not a supported rootfs type')
            return
        # extract raw first to temp & then call global extract_rootfs
        import tempfile, shutil
        from app import extract_rootfs
        tmpdir = tempfile.mkdtemp(prefix='part_extract_')
        raw_tmp = os.path.join(tmpdir, 'raw.bin')
        size = part['reported_size'] or part['size']
        extract_partition_raw(self.fw_path, part['offset'], size, raw_tmp)
        root_dir = os.path.join(tmpdir, 'fs')
        ok, err = extract_rootfs(part['fs'], raw_tmp, root_dir, self.log)
        if not ok:
            QMessageBox.critical(self,'Extract', f'Failed: {err}')
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        # Optional squashfs summary test
        if part['fs']=='squashfs':
            try:
                proc = subprocess.run(['unsquashfs','-s',raw_tmp],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
                if proc.returncode!=0:
                    self.log('[ROOTFS][WARN] unsquashfs -s failed (possible corruption)')
            except Exception:
                pass
        out_dir = QFileDialog.getExistingDirectory(self,'Select output directory for repack outputs')
        if not out_dir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        dlg = RootFSEditDialog(self, root_dir, {'fs':part['fs'],'offset':part['offset'],'size':size}, self.fw_path, out_dir)
        dlg.exec()
        # Clean temp (editor copies repacked firmware elsewhere)
        shutil.rmtree(tmpdir, ignore_errors=True)

    def _resplice_selected(self):
        part = self._selected_part()
        if not part:
            QMessageBox.information(self,'Re-splice','Select a row first')
            return
        # Ask for patched rootfs file to splice
        patched_path, _ = QFileDialog.getOpenFileName(self, 'Select patched rootfs file')
        if not patched_path:
            return
        new_size = os.path.getsize(patched_path)
        # Slot size should use carve span (part['size']); reported_size may be smaller (actual data)
        slot_size = part.get('size') or part.get('reported_size')
        if new_size > slot_size:
            QMessageBox.critical(self,'Re-splice', f'New rootfs ({new_size} bytes) larger than slot ({slot_size})')
            return
        # Backup firmware first
        try:
            from app import backup_file, compute_sha256, log_patch_action
            backup_file(self.fw_path, backup_dir='backup', note='before_resplice')
        except Exception as e:
            self.log(f'[RESP] backup warning: {e}')
        # Create output firmware path
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        out_fw = os.path.join(os.path.dirname(self.fw_path), f"resplice_{part['fs']}_0x{part['offset']:X}_{ts}.bin")
        try:
            with open(self.fw_path,'rb') as f: data = bytearray(f.read())
            with open(patched_path,'rb') as f: new_rootfs = f.read()
            start = part['offset']; end = start + slot_size
            data[start:start+len(new_rootfs)] = new_rootfs
            if len(new_rootfs) < slot_size:
                data[start+len(new_rootfs):end] = b'\x00' * (slot_size - len(new_rootfs))
            with open(out_fw,'wb') as f: f.write(data)
            from app import compute_sha256, log_patch_action
            sha = compute_sha256(out_fw)
            log_patch_action('resplice', out_fw, sha, f"rootfs {part['fs']} offset=0x{part['offset']:X}")
            # Quick header validation of first few bytes
            try:
                with open(out_fw,'rb') as vf:
                    head = vf.read(16)
                if part['fs']=='squashfs' and head[:4] not in (b'hsqs', b'sqsh'):
                    self.log('[RESP][WARN] squashfs magic missing after resplice')
                elif part['fs']=='cramfs' and head[:4] not in (b'\x45\x3d\xcd\x28', b'\x28\xcd\x3d\x45'):
                    self.log('[RESP][WARN] cramfs magic missing after resplice')
            except Exception as _hv_e:
                self.log(f'[RESP][WARN] header validation error: {_hv_e}')
            QMessageBox.information(self,'Re-splice', f'Success -> {out_fw}')
            self.log(f"[RESP] wrote {out_fw}")
        except Exception as e:
            QMessageBox.critical(self,'Re-splice', f'Failed: {e}')
            self.log(f'[RESP] error: {e}')

    def _refresh_table(self):
        self.table.setRowCount(len(self.parts))
        color_map = {
            'squashfs': '#c8e6c9',  # light green
            'cramfs':   '#ffe0b2',  # light orange
            'jffs2':    '#d1c4e9',  # light purple
            'yaffs2':   '#bbdefb',  # light blue
        }
        for r,p in enumerate(self.parts):
            gap_size = p.get('size',0)
            true_size = p.get('reported_size', gap_size)
            header_sz = p.get('header_size')
            self.table.setItem(r,0,QTableWidgetItem(str(p.get('index','?'))))
            fs_item = QTableWidgetItem(p.get('fs','?'))
            base_color = color_map.get(p.get('fs',''), None)
            if base_color:
                fs_item.setBackground(self._qcolor(base_color))
            self.table.setItem(r,1,fs_item)
            self.table.setItem(r,2,QTableWidgetItem(f"0x{p.get('offset',0):X}"))
            size_item = QTableWidgetItem(hex(gap_size))
            size_item.setToolTip('Slot / carve span size (gap to next known offset)')
            self.table.setItem(r,3,size_item)
            if header_sz and header_sz != gap_size:
                true_txt = f"{hex(true_size)}*"
            else:
                true_txt = hex(true_size)
            ts_item = QTableWidgetItem(true_txt)
            ts_item.setToolTip('True filesystem size (from header) * indicates differs from slot')
            self.table.setItem(r,4,ts_item)
            desc = p.get('desc','')[:160]
            desc_item = QTableWidgetItem(desc)
            if '[BW]' in desc:
                desc_item.setBackground(self._qcolor('#fff9c4'))  # pale yellow
            self.table.setItem(r,5,desc_item)
        self.table.resizeColumnsToContents()
    # (removed duplicated second rendering loop)

    def _qcolor(self, hex_code):  # helper to avoid repeated imports
        from PySide6.QtGui import QColor
        return QColor(hex_code)

    def _export_partitions_json(self):
        if not self.parts:
            QMessageBox.information(self,'Export','No partitions to export')
            return
        path, _ = QFileDialog.getSaveFileName(self,'Save JSON','partitions.json','JSON (*.json)')
        if not path:
            return
        import json
        data = []
        for p in self.parts:
            data.append({k: p.get(k) for k in ('index','fs','offset','size','reported_size','header_size','desc')})
        try:
            with open(path,'w',encoding='utf-8') as f:
                json.dump({'firmware': self.fw_path, 'parts': data}, f, indent=2)
            self.log(f'[PART] exported JSON -> {path}')
            QMessageBox.information(self,'Export',f'Saved: {path}')
        except Exception as e:
            QMessageBox.critical(self,'Export',f'Failed: {e}')

    def closeEvent(self, ev):
        try:
            if getattr(self, '_bw_running', False) and getattr(self, '_bw_worker', None):
                self._bw_worker.cancel()
        except Exception:
            pass
        super().closeEvent(ev)
