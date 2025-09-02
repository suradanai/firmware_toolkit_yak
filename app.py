import sys
import os
import subprocess, threading, hashlib, shutil, tempfile, datetime, struct, time, json, binascii, gzip
from tool_registry import (
    choose_tool, get_candidates,
    CAP_SQUASHFS_EXTRACT, CAP_SQUASHFS_PACK,
    CAP_CRAMFS_EXTRACT, CAP_CRAMFS_PACK,
    CAP_JFFS2_EXTRACT, CAP_JFFS2_PACK,
    CAP_YAFFS2_EXTRACT, CAP_YAFFS2_PACK,
    log_summary as tool_log_summary
)

# Qt imports (added / restored after patch issues)
try:
    from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QSplitter, QTextEdit, QTabWidget, QFileDialog,
    QMessageBox, QInputDialog, QCheckBox, QSpinBox, QComboBox, QLineEdit, QDialogButtonBox,
    QListWidget, QListWidgetItem, QStackedWidget, QSizePolicy, QProgressBar, QGroupBox
    )
    from PySide6.QtWidgets import QDialog
    from PySide6.QtGui import QAction
    from PySide6.QtCore import Qt, QThread, Signal
except Exception as _qt_e:
    print('[WARN] PySide6 import failed (GUI parts will not work):', _qt_e)
    # Provide minimal dummies to avoid NameErrors in headless operations
    QApplication = object; QMainWindow = object; QWidget = object
    QVBoxLayout = QHBoxLayout = QPushButton = QLabel = QTreeWidget = QTreeWidgetItem = object
    QSplitter = QTextEdit = QTabWidget = QFileDialog = QMessageBox = QInputDialog = QCheckBox = QSpinBox = object
    QAction = object; Qt = type('Qt', (), {'Horizontal': 1, 'UserRole': 32})
    class QThread: pass
    class Signal:  # dummy signal
        def __init__(self,*a,**k): pass
        def connect(self,*a,**k): pass

from dialogs import SelectivePatchDialog, RootFSEditDialog, CustomScriptDialog, SpecialFunctionsWindow, UBootEnvEditorDialog
from core.logging_utils import configure_logging
from passlib.hash import sha512_crypt
import core.multisquash as multisquash

# ---- Temporary i18n & worker stubs (rebuild after corruption) ----
def _(key: str) -> str:
    mapping = {
        'app_title': 'Firmware Toolkit',
        'btn_open_fw': 'Open Firmware',
        'btn_patch_boot': 'Boot Delay',
        'btn_patch_serial': 'Serial Shell',
        'btn_patch_network': 'Network'
    }
    return mapping.get(key, key)

class FMKRunner(QThread):
    log = Signal(str)
    error = Signal(str)
    finished = Signal(int)
    def __init__(self, cmd, cwd=None):
        super().__init__(); self.cmd = cmd; self.cwd = cwd
    def run(self):
        import subprocess, shlex
        try:
            self.log.emit('[FMKRunner] start: ' + ' '.join(shlex.quote(c) for c in self.cmd))
            p = subprocess.Popen(self.cmd, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if p.stdout:
                for line in iter(p.stdout.readline, ''):
                    if not line: break
                    self.log.emit(line.rstrip())
            p.wait()
            rc = p.returncode
            if rc != 0:
                self.error.emit(f'Command exited rc={rc}')
            self.finished.emit(rc)
        except Exception as e:
            self.error.emit(f'Runner exception: {e}')
            self.finished.emit(-1)

class ApplyPipelineWorker:
    def __init__(self, fw_path, suggestions, output_dir):
        self._cancel=False
    def start(self): pass
    def request_cancel(self): self._cancel=True

class MultiSquashWorker(QThread):
    log = Signal(str)
    error = Signal(str)
    finished_ok = Signal(str)
    def __init__(self, fw_path, out_dir, allow_destructive):
        super().__init__(); self.fw_path=fw_path; self.out_dir=out_dir; self.allow_destructive=allow_destructive
    def run(self):
        try:
            self.log.emit('[MSQ] Detecting squashfs parts...')
            parts = multisquash.detect_squashfs(self.fw_path)
            if not parts:
                self.error.emit('No squashfs parts found'); return
            # For now only operate on first part
            part0 = parts[0]
            self.log.emit(f'[MSQ] using part offset=0x{part0.offset:X} size={part0.size}')
            import tempfile, os
            tmpdir = tempfile.mkdtemp(prefix='msq_')
            try:
                part_file = os.path.join(tmpdir,'part0.bin')
                multisquash.extract_part(self.fw_path, part0, part_file)
                self.log.emit('[MSQ] extracted part slice')
                unsquash_dir = os.path.join(tmpdir,'unsquash'); os.makedirs(unsquash_dir, exist_ok=True)
                # Use 'auto' so extract_rootfs can detect cramfs/jffs2/yaffs2 instead of forcing squashfs
                ok, err = extract_rootfs('auto', part_file, unsquash_dir, self.log.emit)
                if not ok:
                    self.error.emit(f'extract failed: {err}'); return
                # optional shrink pipeline
                success, out_path, new_size = multisquash.shrink_pipeline(unsquash_dir, orig_limit=part0.size, allow_destructive=self.allow_destructive)
                self.log.emit(f'[MSQ] shrink success={success} size={new_size}')
                # Repack (simple mksquashfs) if shrink produced candidate within size
                if success and out_path:
                    with open(self.fw_path,'rb') as f: fw_data = bytearray(f.read())
                    with open(out_path,'rb') as f: new_part = f.read()
                    if len(new_part) <= part0.size:
                        fw_data[part0.offset:part0.offset+len(new_part)] = new_part
                        if len(new_part) < part0.size:
                            fw_data[part0.offset+len(new_part):part0.offset+part0.size] = b'\x00'*(part0.size-len(new_part))
                        out_fw = os.path.join(self.out_dir, os.path.basename(self.fw_path).replace('.bin','')+'_multisquash.bin')
                        with open(out_fw,'wb') as f: f.write(fw_data)
                        self.log.emit(f'[MSQ] wrote {out_fw}')
                        self.finished_ok.emit(out_fw); return
                    else:
                        self.log.emit('[MSQ] new part larger than original (abort write)')
                self.error.emit('shrink or repack failed')
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            self.error.emit(f'MultiSquash error: {e}')

class SuggestedPipelinePreviewDialog:
    def __init__(self, parent, suggestions): self.suggestions = suggestions
    def exec(self): return 0

def extract_rootfs(fs_type, rootfs_bin, unsquashfs_dir, log_func):
    """Extract rootfs (auto-detect squashfs/cramfs/jffs2/yaffs2). Returns (ok, err)."""
    try:
        fs_type = (fs_type or '').strip().lower()
        if not os.path.exists(rootfs_bin):
            return False, 'rootfs image missing'
        os.makedirs(unsquashfs_dir, exist_ok=True)
        with open(rootfs_bin,'rb') as f: head = f.read(512)
        def _has_magic(d, magic: bytes): return d.startswith(magic)
        squash_magics = (b'hsqs', b'sqsh')
        cramfs_magic_le = b'\x45\x3d\xcd\x28'; cramfs_magic_be = b'\x28\xcd\x3d\x45'
        detected=None
        if any(_has_magic(head,m) for m in squash_magics): detected='squashfs'
        elif _has_magic(head, cramfs_magic_le) or _has_magic(head, cramfs_magic_be): detected='cramfs'
        elif any(m in head[:256] for m in squash_magics): detected='squashfs'
        if fs_type in ('auto','','unknown'):
            if detected: fs_type = detected
            else:
                if head[:2]==b'\x85\x19' or head[0x100:0x102]==b'\x85\x19': fs_type='jffs2'
                elif b'yaffs' in head.lower(): fs_type='yaffs2'
        if fs_type in ('squash','sqsh'): fs_type='squashfs'
        log_func(f"[ROOTFS] detect={detected or 'none'} final={fs_type}")
        # --- SquashFS ---
        if fs_type=='squashfs':
            import tempfile, subprocess, shutil as _sh
            candidates = get_candidates(CAP_SQUASHFS_EXTRACT)
            if not candidates:
                single = shutil.which('unsquashfs')
                if not single: return False, 'unsquashfs tool not found'
                class _Stub:
                    pass
                s = _Stub()
                s.path = single
                candidates = [s]
            # heuristic reorder: system first then legacy lzma
            try:
                def _score(ti):
                    p=getattr(ti,'path',''); sc=0
                    if '/usr/' in p: sc-=50
                    if 'lzma' in os.path.basename(p).lower(): sc-=20
                    return sc
                candidates=sorted(candidates,key=_score)
            except Exception: pass
            tmpdir=tempfile.mkdtemp(prefix='unsq_')
            try:
                success=False
                for idx, ti in enumerate(candidates,1):
                    tool=ti.path; dest=os.path.join(tmpdir,'squashfs-root')
                    cmd=[tool,'-d',dest,rootfs_bin]
                    log_func(f"[UNSQUASHFS] try {idx}: {tool}")
                    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                    out=p.stdout or ''
                    if p.returncode!=0 and ('unsupported' in out.lower() or 'unknown compression' in out.lower()):
                        alt=[tool,'-no-progress','-d',dest,rootfs_bin]; log_func('[UNSQUASHFS] retry alt flags')
                        p2=subprocess.run(alt,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                        if p2.returncode==0: p=p2; out=p.stdout or ''
                    fatal=False
                    for line in (out.splitlines()[:400]):
                        if 'fatal' in line.lower(): fatal=True
                        if any(k in line.lower() for k in ('fatal','error')): log_func('[UNSQUASHFS] '+line)
                    if p.returncode==0 and not fatal:
                        success=True; break
                if not success:
                    # heuristic fallback to alternate fs type detection
                    if _has_magic(head, cramfs_magic_le) or _has_magic(head, cramfs_magic_be): fs_type='cramfs'
                    elif b'\x85\x19' in head[:4096]: fs_type='jffs2'
                    elif b'yaffs' in head.lower(): fs_type='yaffs2'
                    else: return False,'unsquashfs failed (all versions)'
                if fs_type=='squashfs':
                    root_dir=os.path.join(tmpdir,'squashfs-root')
                    if not os.path.isdir(root_dir): return False,'squashfs-root missing after extraction'
                    for name in os.listdir(root_dir):
                        src=os.path.join(root_dir,name); dst=os.path.join(unsquashfs_dir,name)
                        if os.path.exists(dst):
                            try:
                                if os.path.isdir(dst) and os.path.isdir(src): pass
                                else: os.remove(dst)
                            except Exception: pass
                        try: _sh.move(src,dst)
                        except Exception as e: log_func(f"[UNSQUASHFS] move warn: {e}")
                    return True,''
            finally:
                shutil.rmtree(tmpdir,ignore_errors=True)
        # --- CramFS ---
        if fs_type=='cramfs':
            cramfsck=shutil.which('cramfsck') or shutil.which('uncramfs')
            if not cramfsck: return False,'cramfs extraction tool (cramfsck/uncramfs) not found'
            import subprocess as _sub
            if os.path.basename(cramfsck)=='cramfsck': cmd=[cramfsck,'-x',unsquashfs_dir,rootfs_bin]
            else: cmd=[cramfsck,rootfs_bin,unsquashfs_dir]
            p=_sub.run(cmd,stdout=_sub.PIPE,stderr=_sub.STDOUT,text=True)
            log_func(f"[CRAMFS] rc={p.returncode}")
            if p.stdout:
                for line in p.stdout.splitlines()[:200]:
                    if 'error' in line.lower(): log_func('[CRAMFS] '+line)
            if p.returncode!=0: return False,'cramfs extraction failed'
            return True,''
        # --- JFFS2 ---
        if fs_type in ('jffs2','jffs'):
            tool=choose_tool(CAP_JFFS2_EXTRACT)
            exe=tool.path if tool else shutil.which('unjffs2')
            if not exe: return False,'unjffs2 tool not found'
            import tempfile as _tf, subprocess as _sub
            tmp=_tf.mkdtemp(prefix='jffs2_')
            try:
                cmd=[exe,rootfs_bin,tmp]; log_func('[JFFS2] '+' '.join(cmd))
                p=_sub.run(cmd,stdout=_sub.PIPE,stderr=_sub.STDOUT,text=True,timeout=300)
                if p.returncode!=0: log_func('[JFFS2] extract failed rc='+str(p.returncode)); return False,'unjffs2 failed'
                for n in os.listdir(tmp):
                    s=os.path.join(tmp,n); d=os.path.join(unsquashfs_dir,n)
                    if os.path.isdir(s): shutil.copytree(s,d,dirs_exist_ok=True)
                    else: shutil.copy2(s,d)
                return True,''
            finally:
                shutil.rmtree(tmp,ignore_errors=True)
        # --- YAFFS2 ---
        if fs_type in ('yaffs2','yaffs'):
            tool=choose_tool(CAP_YAFFS2_EXTRACT)
            exe=tool.path if tool else shutil.which('unyaffs2')
            if not exe: return False,'unyaffs2 tool not found'
            import tempfile as _tf, subprocess as _sub
            tmp=_tf.mkdtemp(prefix='yaffs2_')
            try:
                cmd=[exe,rootfs_bin,tmp]; log_func('[YAFFS2] '+' '.join(cmd))
                p=_sub.run(cmd,stdout=_sub.PIPE,stderr=_sub.STDOUT,text=True,timeout=300)
                if p.returncode!=0: log_func('[YAFFS2] extract failed rc='+str(p.returncode)); return False,'unyaffs2 failed'
                for n in os.listdir(tmp):
                    s=os.path.join(tmp,n); d=os.path.join(unsquashfs_dir,n)
                    if os.path.isdir(s): shutil.copytree(s,d,dirs_exist_ok=True)
                    else: shutil.copy2(s,d)
                return True,''
            finally:
                shutil.rmtree(tmp,ignore_errors=True)
        return False,f'unsupported fs type: {fs_type}'
    except Exception as e:
        return False,str(e)
# --- System library check (Linux: libxcb-cursor0 for Qt) ---
def check_system_libs():
    try:
        # ตัวอย่าง: เช็คว่ามีไฟล์ libxcb-cursor หรือไม่ (ไม่ต้องเข้มงวดมาก)
        # หากไม่มี ก็แค่บันทึก warning (ที่อื่นจะพยายาม fallback เอง)
        return True
    except Exception:
        return True  # ไม่ให้บล็อคการทำงานหลัก

def find_tool(name: str):
    """Locate external helper binary.
    Search order:
      1) tools_bin/ (repo vendor)
      2) tools_bin/bin/ (common layout)
      3) any extra dirs from FMK_TOOL_DIRS env (colon separated)
      4) PATH (shutil.which)
    Accept either exact match or executable starting with name (e.g. name+'.py').
    """
    candidates = []
    seen = set()
    def _add(path):
        if path and path not in seen and os.path.isdir(path):
            seen.add(path); candidates.append(path)
    try:
        here = os.path.dirname(__file__)
        tb = os.path.join(here,'tools_bin')
        _add(tb)
        _add(os.path.join(tb,'bin'))
        extra = os.environ.get('FMK_TOOL_DIRS','')
        for d in extra.split(':'):
            if d: _add(d)
    except Exception:
        pass
    for d in candidates:
        try:
            for fn in os.listdir(d):
                if fn == name or fn.startswith(name+'.') or fn.startswith(name+'-'):
                    fp = os.path.join(d, fn)
                    if os.path.isfile(fp) and os.access(fp, os.X_OK):
                        return fp
        except Exception:
            continue
    return shutil.which(name)

def log_vendor_tools(log_func):
    try:
        tools = ['unsquashfs','mksquashfs','binwalk','cramfsck','mkcramfs','mkfs.jffs2']
        for t in tools:
            p = find_tool(t)
            log_func(f"[TOOLS] {t}: {p or 'NOT FOUND'}")
    except Exception as e:
        try: log_func(f'[TOOLS] vendor tool scan error: {e}')
        except Exception: pass

def repack_rootfs(fs_type, unsquashfs_dir, rootfs_bin_out, log_func, force_comp=None):
    def _normalize_fs(t):
        return (t or '').strip().lower()
    fs_type = _normalize_fs(fs_type)
    if fs_type == "squashfs":
        ti = choose_tool(CAP_SQUASHFS_PACK)
        mksquashfs = ti.path if ti else find_tool("mksquashfs")
        if not mksquashfs:
            return False, "mksquashfs tool not found"

        # --- ตรวจสอบ compression เดิม ---
        comp = "gzip"  # default
        extra_opts = []
        try:
            # หาไฟล์ squashfs เดิมใกล้ๆ rootfs_bin_out
            orig_info = None
            parent_dir = os.path.dirname(rootfs_bin_out) or "."
            for fname in os.listdir(parent_dir):
                if fname.endswith(".bin") or fname.endswith(".img") or fname.endswith(".squashfs"):
                    orig_path = os.path.join(parent_dir, fname)
                    try:
                        out = subprocess.check_output([find_tool("unsquashfs") or "unsquashfs", "-s", orig_path], text=True, stderr=subprocess.DEVNULL)
                        orig_info = out
                        break
                    except Exception:
                        continue
            if orig_info:
                for line in orig_info.splitlines():
                    if "Compression:" in line:
                        comp = line.split(":",1)[1].strip().split()[0].lower()
                        break
            # override by caller
            if force_comp:
                comp = force_comp

            # เพิ่มออปชันบีบอัดสูงสุดตามชนิด
            if comp == "xz":
                extra_opts = ["-comp", "xz", "-b", "256K", "-Xdict-size", "100%"]
            elif comp == "lzma":
                extra_opts = ["-comp", "lzma", "-b", "256K"]
            elif comp == "gzip":
                extra_opts = ["-comp", "gzip", "-b", "256K"]
            elif comp == "zstd":
                extra_opts = ["-comp", "zstd", "-b", "256K"]
            else:
                extra_opts = ["-comp", comp]
        except Exception as e:
            log_func(f"[WARN] ตรวจสอบ compression เดิมไม่สำเร็จ: {e}")
            extra_opts = ["-comp", "gzip", "-b", "256K"]

        try:
            cmd = [mksquashfs, unsquashfs_dir, rootfs_bin_out, "-noappend"] + extra_opts
            log_func(f"[INFO] repack squashfs: {' '.join(cmd)}")
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=120)
            return True, ""
        except Exception as e:
            return False, f"mksquashfs error: {e}"

    elif fs_type == "cramfs":
        ti = choose_tool(CAP_CRAMFS_PACK)
        mkcramfs = ti.path if ti else shutil.which("mkcramfs")
        if not mkcramfs:
            return False, "mkcramfs tool not found"
        try:
            subprocess.check_output([mkcramfs, unsquashfs_dir, rootfs_bin_out], stderr=subprocess.STDOUT, timeout=90)
            return True, ""
        except Exception as e:
            return False, f"mkcramfs error: {e}"

    elif fs_type in ("jffs2", "jffs"):
        ti = choose_tool(CAP_JFFS2_PACK)
        mkfsjffs2 = ti.path if ti else shutil.which("mkfs.jffs2")
        if not mkfsjffs2:
            return False, "mkfs.jffs2 tool not found"
        try:
            # default options; could add -l / -e later (eraseblock size)
            subprocess.check_output([mkfsjffs2, "-d", unsquashfs_dir, "-o", rootfs_bin_out], stderr=subprocess.STDOUT, timeout=180)
            return True, ""
        except Exception as e:
            return False, f"mkfs.jffs2 error: {e}"

    elif fs_type in ("yaffs2", "yaffs"):
        ti = choose_tool(CAP_YAFFS2_PACK)
        mkyaffs2 = ti.path if ti else shutil.which("mkyaffs2")
        if not mkyaffs2:
            return False, "mkyaffs2 tool not found"
        try:
            subprocess.check_output([mkyaffs2, unsquashfs_dir, rootfs_bin_out], stderr=subprocess.STDOUT, timeout=180)
            return True, ""
        except Exception as e:
            return False, f"mkyaffs2 error: {e}"

    else:
        return False, f"ไม่รองรับการ pack {fs_type}"

def patch_boot_delay(fw_path, rootfs_part, new_delay, out_path, log_func):
    """Auto patch boot delay at known candidate offsets (currently 0x100)."""
    try:
        with open(fw_path,'rb') as f: data = bytearray(f.read())
        if len(data) <= 0x100:
            log_func('❌ ไฟล์เล็กเกินไป ไม่มี offset 0x100'); return False,'file too small'
        candidates = [0x100]
        for off in candidates:
            if off < len(data): data[off] = new_delay & 0xFF
        with open(out_path,'wb') as f: f.write(data)
        log_func(f'✅ ปรับ boot delay={new_delay}s {len(candidates)} จุด -> {out_path}')
        return True,''
    except Exception as e:
        log_func(f'❌ Patch boot delay ผิดพลาด: {e}')
        return False,str(e)

def read_boot_delay_byte(path: str):
    try:
        with open(path,'rb') as f:
            if f.seek(0,2) <= 0x100:
                return None
            f.seek(0x100)
            b=f.read(1)
            return b[0] if b else None
    except Exception:
        return None

# ---- U-Boot Environment Helpers ----
def scan_uboot_env(fw_path, max_search=0x200000, env_sizes=(0x1000,0x2000,0x4000,0x8000,0x10000), deep: bool=False):
    """Scan potential U-Boot env blocks.
    Improvements:
    - Broader search range (default 2MB)
    - Accept blocks without explicit bootdelay; use key/value density heuristic
    - Skip obviously binary/compressed segments (high entropy w/o '=' pairs)
    - Return list sorted by likelihood (has bootdelay first, then larger blocks)
    """
    import struct, binascii
    results=[]
    try:
        fsize=os.path.getsize(fw_path)
        if deep:
            limit=fsize  # deep scan full file
            if fsize>64*1024*1024:  # safety cap
                limit=64*1024*1024
        else:
            limit=min(fsize,max_search)
        with open(fw_path,'rb') as f:
            blob=f.read(limit)
        step=0x400 if not deep else 0x800
        for off in range(0, limit, step):
            for env_size in env_sizes:
                if off+env_size>len(blob):
                    continue
                block=blob[off:off+env_size]
                if len(block)<8:
                    continue
                crc_stored=struct.unpack('<I', block[:4])[0]
                data=block[4:]
                if b'=' not in data[:env_size-4]:
                    continue
                end_double=data.find(b'\x00\x00')
                if end_double==-1 or end_double<4:
                    continue
                env_region=data[:end_double+1]
                first_eq=env_region.find(b'=')
                if first_eq==-1 or first_eq>64:
                    continue
                calc=binascii.crc32(env_region)&0xffffffff
                valid=(calc==crc_stored)
                raw_vars=env_region.split(b'\x00')
                kv={}; text_pairs=0
                for raw in raw_vars:
                    if not raw or b'=' not in raw:
                        continue
                    k,v=raw.split(b'=',1)
                    if not k or len(k)>64:
                        continue
                    if any(c<32 or c>126 for c in k):
                        continue
                    try:
                        k_dec=k.decode(); v_dec=v.decode(errors='ignore')
                    except:
                        continue
                    kv[k_dec]=v_dec; text_pairs+=1
                if text_pairs<3:
                    continue
                score=0
                if 'bootdelay' in kv: score+=5
                if 'baudrate' in kv: score+=2
                if 'ethaddr' in kv or 'ipaddr' in kv: score+=2
                score+=min(len(kv),50)/10.0
                results.append({'offset':off,'size':env_size,'crc':f"{crc_stored:08x}",'crc_calc':f"{calc:08x}",'valid':valid,'vars':kv,'bootdelay':kv.get('bootdelay'),'score':score})
    except Exception:
        pass
    # If nothing found AND deep requested: fallback heuristic extraction
    if deep and not results:
        try:
            with open(fw_path,'rb') as f: blob=f.read(limit)
            import re, binascii, struct
            # search anchor keys
            for m in re.finditer(b'bootargs=|bootcmd=', blob):
                start=m.start()
                # scan backwards up to 512 bytes to possible CRC start
                back=min(512, start)
                window_start=start-back
                # attempt to parse key=value sequence forward
                kv_region=b''
                p=start
                max_len=0x10000
                pairs=[]; raw=blob
                while p < len(raw) and len(kv_region) < max_len:
                    end=raw.find(b'\x00', p)
                    if end==-1: break
                    seg=raw[p:end]
                    if seg==b'':  # first null -> end
                        break
                    kv_region+=seg+b'\x00'
                    if b'=' in seg:
                        k,v=seg.split(b'=',1)
                        if 1<=len(k)<=64:
                            try: pairs.append((k.decode(errors='ignore'), v.decode(errors='ignore')))
                            except: pass
                    p=end+1
                    # termination double null
                    if p < len(raw) and raw[p:p+1]==b'\x00':
                        break
                if len(pairs)>=3:
                    # assume CRC 4 bytes before first key if plausible
                    crc_pos=window_start
                    if crc_pos+4 < start:
                        candidate_crc=struct.unpack('<I', blob[crc_pos:crc_pos+4])[0]
                        calc=binascii.crc32(kv_region+b'\x00') & 0xffffffff
                        valid=(candidate_crc==calc)
                    else:
                        valid=False; candidate_crc=0; calc=binascii.crc32(kv_region+b'\x00') & 0xffffffff
                    kv=dict(pairs)
                    score=5 if 'bootdelay' in kv else 0
                    score+=min(len(kv),50)/10.0
                    results.append({'offset':crc_pos if crc_pos<start else start,'size':len(kv_region)+8,'crc':f"{candidate_crc:08x}",'crc_calc':f"{calc:08x}",'valid':valid,'vars':kv,'bootdelay':kv.get('bootdelay'),'score':score,'heuristic':True})
        except Exception:
            pass
    # deduplicate (same offset/size)
    dedup={}
    for r in results:
        key=(r['offset'], r['size'])
        if key not in dedup or (r.get('score',0) > dedup[key].get('score',0)):
            dedup[key]=r
    results=list(dedup.values())
    # sort: higher score first then smaller offset
    results.sort(key=lambda r:(-r.get('score',0), r['offset']))
    return results

# ---- Advanced U-Boot env scanner v2 (extended heuristics) ----
def scan_uboot_env_v2(
    fw_path: str,
    max_search: int = 0x400000,
    env_sizes = (0x800,0x1000,0x1800,0x2000,0x3000,0x4000,0x6000,0x8000,0x10000,0x20000,0x40000),
    deep: bool = False,
    step: int | None = None,
    keep_crc_mismatch: bool = True,
    compiled_scan: bool = True,
    verbose: bool = False,
    max_candidates: int = 2000,
):
    """Improved scan for U-Boot environment blocks.

    Features:
      - Smaller step (default 0x100 or 0x200) to catch misaligned blocks.
      - Both endian CRC trials (little + big) to detect big-endian images.
      - Wider env_sizes list.
      - Accept candidate with sufficiently many key=value (>=3) even if CRC mismatch (flag 'crc_ok'=False).
      - Detect redundant pair sequences (two blocks of same size back-to-back) and mark 'redundant_pair'.
      - Optional heuristic for compiled default env (string region containing bootdelay=..., bootcmd=... before double null) -> type='compiled'.
      - Score weighting: bootdelay/bootcmd presence, number of vars, CRC validity.
    Returns list of dict candidates sorted by score desc.
    """
    import struct, binascii
    candidates = []
    try:
        fsize = os.path.getsize(fw_path)
        limit = fsize if deep else min(fsize, max_search)
        with open(fw_path,'rb') as f: blob = f.read(limit)
    except Exception:
        return []
    if step is None:
        step = 0x100 if deep else 0x200
    anchors = (b'bootdelay=', b'bootcmd=', b'bootargs=')
    def score_vars(kv):
        s = 0
        if 'bootdelay' in kv: s += 5
        if 'bootcmd' in kv: s += 3
        if 'bootargs' in kv: s += 2
        s += min(len(kv),80)/12.0
        return s
    # Scan blocks
    for off in range(0, len(blob), step):
        if len(candidates) >= max_candidates: break
        for env_size in env_sizes:
            end = off + env_size
            if end > len(blob) or env_size < 16: continue
            block = blob[off:end]
            data = block[4:]
            # quick reject: must have '=' and terminating \x00\x00 within region (allow mismatch CRC)
            if b'=' not in data: continue
            term = data.find(b'\x00\x00')
            if term == -1 or term < 4: continue
            env_region = data[:term+1]
            # parse pairs
            raw_vars = env_region.split(b'\x00')
            kv={}; valid_pairs=0
            for raw in raw_vars:
                if not raw or b'=' not in raw: continue
                k,v = raw.split(b'=',1)
                if len(k)==0 or len(k)>64: continue
                try:
                    k_dec=k.decode(); v_dec=v.decode(errors='ignore')
                except Exception:
                    continue
                if any(ord(c)<32 or ord(c)>126 for c in k_dec):
                    continue
                kv[k_dec]=v_dec; valid_pairs+=1
            if valid_pairs < 3:  # too sparse
                continue
            # CRC checks
            crc_le = binascii.crc32(env_region) & 0xffffffff
            crc_be = crc_le  # compute once (data same) but we compare to stored bytes both endian
            stored_le = struct.unpack('<I', block[:4])[0]
            stored_be = struct.unpack('>I', block[:4])[0]
            crc_ok = (stored_le == crc_le) or (stored_be == crc_be)
            if not crc_ok and not keep_crc_mismatch:
                continue
            s = score_vars(kv)
            if crc_ok: s += 2
            cand = {
                'offset': off,
                'size': env_size,
                'vars': kv,
                'bootdelay': kv.get('bootdelay'),
                'score': s,
                'crc_ok': crc_ok,
                'stored_crc_le': f"{stored_le:08x}",
                'calc_crc': f"{crc_le:08x}",
                'endian_match': 'le' if stored_le==crc_le else ('be' if stored_be==crc_be else 'none'),
                'type':'block'
            }
            candidates.append(cand)
    # Redundant pair marking
    by_size = {}
    for c in candidates:
        by_size.setdefault(c['size'], []).append(c)
    for size, lst in by_size.items():
        lst.sort(key=lambda x:x['offset'])
        for a,b in zip(lst, lst[1:]):
            if b['offset'] == a['offset'] + size:
                a['redundant_pair'] = True; b['redundant_pair'] = True
    # Compiled env heuristic
    if compiled_scan:
        try:
            import re
            for m in re.finditer(b'bootdelay=\d+', blob):
                start = m.start()
                # extend forward collecting key=value\0 strings
                p = start
                limit_forward = min(len(blob), start + 0x8000)
                kv_bytes = b''; kv_parsed = {}
                while p < limit_forward:
                    end = blob.find(b'\x00', p)
                    if end == -1: break
                    seg = blob[p:end]
                    p = end + 1
                    if seg == b'':
                        break
                    if b'=' not in seg:
                        # if non key=value encountered early, abort
                        if len(kv_parsed) < 3: break
                        else: continue
                    k,v = seg.split(b'=',1)
                    try:
                        ks = k.decode(); vs = v.decode(errors='ignore')
                    except Exception:
                        continue
                    if any(ord(c)<32 or ord(c)>126 for c in ks):
                        break
                    kv_parsed[ks]=vs
                    kv_bytes += seg + b'\x00'
                    if len(kv_parsed) > 64: break
                if len(kv_parsed) >=3:
                    s = score_vars(kv_parsed) + 1  # compiled bonus
                    candidates.append({
                        'offset': start,
                        'size': len(kv_bytes),
                        'vars': kv_parsed,
                        'bootdelay': kv_parsed.get('bootdelay'),
                        'score': s,
                        'crc_ok': False,
                        'endian_match':'n/a',
                        'type':'compiled'
                    })
        except Exception:
            pass
    # Deduplicate by (offset,size,type)
    uniq = {}
    for c in candidates:
        key = (c['offset'], c['size'], c.get('type','block'))
        if key not in uniq or c['score'] > uniq[key]['score']:
            uniq[key] = c
    out = list(uniq.values())
    out.sort(key=lambda r: (-r.get('score',0), r['offset']))
    if verbose:
        for c in out[:15]:
            print(f"[V2] off=0x{c['offset']:X} size=0x{c['size']:X} type={c.get('type')} vars={len(c['vars'])} score={c['score']:.2f} crc_ok={c['crc_ok']} bootdelay={c.get('bootdelay')}")
    return out

def analyze_bootloader_env(env_blocks):
    """Produce human/AI style findings & suggestions from scanned U-Boot env blocks.
    Returns (findings, suggestions)
    """
    findings=[]; suggestions=[]
    if not env_blocks:
        return ["[BOOTENV] ไม่พบ environment"], ["ไม่สามารถวิเคราะห์ bootloader env (ไม่พบ)"]
    # choose best (score first) for detailed analysis
    best=env_blocks[0]
    vars_=best.get('vars',{})
    findings.append(f"[BOOTENV] ใช้บล็อค @0x{best['offset']:X} size=0x{best['size']:X} valid_crc={best['valid']} vars={len(vars_)}")
    key_groups={'boot':['bootcmd','bootargs','bootdelay','bootfile','autoload'], 'net':['ipaddr','serverip','gatewayip','netmask','ethaddr'], 'hw':['baudrate','mtdparts','console'], 'misc':['preboot','stdin','stdout','stderr','bootretry']}
    # Summaries
    for grp,keys in key_groups.items():
        present=[k for k in keys if k in vars_]
        if present:
            findings.append(f"[BOOTENV] {grp}: "+", ".join(f"{k}={vars_[k]}" for k in present))
    # Heuristic suggestions
    def add_sug(cond,msg):
        if cond and msg not in suggestions: suggestions.append(msg)
    # bootdelay
    try:
        bd=int(vars_.get('bootdelay','0'))
        add_sug(bd>3, f"ลด bootdelay {bd}->1 เพื่อบูตเร็วขึ้น")
    except: pass
    # bootcmd risk
    bc=vars_.get('bootcmd','')
    add_sug('tftp' in bc.lower(), 'พิจารณาลบ tftp จาก bootcmd หากไม่ใช้ network boot')
    add_sug('nand' in bc.lower() and 'ubi' in bc.lower(), 'ตรวจสอบความถูกต้องของคำสั่ง ubi ใน bootcmd')
    # bootargs
    ba=vars_.get('bootargs','')
    add_sug('console=' not in ba, 'เพิ่ม console=ttyS0,115200 ใน bootargs เพื่อ debug')
    add_sug('root=' not in ba, 'กำหนด root= ใน bootargs ให้ชัดเจน (เช่น root=/dev/mtdblockX ro)')
    add_sug('panic=' not in ba, 'เพิ่ม panic=3 ใน bootargs เพื่อรีบูตหลัง kernel panic')
    # network
    ip=vars_.get('ipaddr',''); serverip=vars_.get('serverip','')
    add_sug(ip in ('','0.0.0.0'), 'ตั้งค่า ipaddr ให้ถูกต้อง หรือเอาออกหากไม่ใช้ netboot')
    add_sug(serverip and ip==serverip, 'ipaddr กับ serverip เหมือนกัน ตรวจสอบความจำเป็น')
    eth=vars_.get('ethaddr','')
    import re
    mac_re=re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')
    add_sug(eth and not mac_re.match(eth), 'ethaddr รูปแบบไม่ถูกต้อง (ต้องเป็น MAC AA:BB:CC:DD:EE:FF)')
    # security
    preboot=vars_.get('preboot','')
    add_sug(preboot!='' and 'reset' in preboot.lower(), 'ตรวจสอบ preboot มีคำสั่ง reset อาจทำให้ loop')
    add_sug('bootretry' not in vars_, 'เพิ่ม bootretry=3 เพื่อวนบูตกรณีบูตล้มเหลว')
    # autoload
    autoload=vars_.get('autoload','')
    add_sug(autoload.lower()=='yes', 'ตั้ง autoload=no หากไม่ต้องการ dhcp/bootp อัตโนมัติ')
    # summary line
    if suggestions:
        findings.append('[BOOTENV] ข้อเสนอ:')
        findings.extend('  - '+s for s in suggestions)
    else:
        findings.append('[BOOTENV] ไม่พบข้อเสนอเพิ่มเติม')
    return findings, suggestions

def patch_uboot_env_bootdelay(src_fw, dst_fw, new_val, log_func=lambda m:None):
    envs=scan_uboot_env(src_fw)
    if not envs:  # fallback to v2
        log_func('[UBOOT] v1 scan no result, trying v2...')
        envs = scan_uboot_env_v2(src_fw, deep=True)
    if not envs:
        log_func('[UBOOT] ไม่พบ environment สำหรับแก้ไข')
        return False
    # choose env with bootdelay first
    target=None
    for e in envs:
        if e.get('bootdelay') is not None:
            target=e; break
    if not target:
        target=envs[0]
    off=target['offset']; size=target['size']
    with open(src_fw,'rb') as f: f.seek(off); block=f.read(size)
    if len(block)!=size:
        log_func('[UBOOT] อ่าน block ไม่ครบ')
        return False
    import struct, binascii
    stored_crc=struct.unpack('<I', block[:4])[0]
    data=block[4:]
    end_double=data.find(b'\x00\x00')
    if end_double==-1:
        log_func('[UBOOT] ไม่พบ \0\0')
        return False
    env_region=data[:end_double+1]
    pairs=[]
    for raw in env_region.split(b'\x00'):
        if not raw: continue
        if b'=' not in raw: continue
        k,v=raw.split(b'=',1)
        try: pairs.append((k.decode(), v.decode(errors='ignore')))
        except: pass
    updated=False
    for i,(k,v) in enumerate(pairs):
        if k=='bootdelay':
            if v!=str(new_val):
                pairs[i]=(k,str(new_val)); updated=True
            else:
                updated=True
            break
    else:
        pairs.append(('bootdelay', str(new_val))); updated=True
    if not updated:
        log_func('[UBOOT] ไม่มีการเปลี่ยนแปลง bootdelay')
        return True
    kv_bytes=b''.join(f"{k}={v}".encode()+b'\x00' for k,v in pairs)
    new_env_region=kv_bytes+b'\x00'
    if len(new_env_region)+1 > size-4:  # +1 second null
        log_func('[UBOOT] env ใหม่ยาวเกิน block')
        return False
    new_crc=binascii.crc32(new_env_region)&0xffffffff
    used=len(new_env_region)+1
    padding=b'\x00'*((size-4)-used)
    new_block=struct.pack('<I', new_crc)+new_env_region+b'\x00'+padding
    # copy whole file then patch
    with open(src_fw,'rb') as fsrc, open(dst_fw,'wb') as fdst: shutil.copyfileobj(fsrc,fdst)
    with open(dst_fw,'r+b') as f: f.seek(off); f.write(new_block)
    log_func(f"[UBOOT] bootdelay {target.get('bootdelay')} -> {new_val} @0x{off:X} size=0x{size:X} crc_old={stored_crc:08x} crc_new={new_crc:08x}")
    return True

def patch_uboot_env_bootdelay_all(src_fw, dst_fw, new_val, log_func=lambda m:None):
    """Patch bootdelay across all detected (normal + deep) U-Boot env blocks.
    Writes cumulative result to dst_fw.
    """
    import struct, binascii
    try:
        # start by copying original to dst
        with open(src_fw,'rb') as fsrc, open(dst_fw,'wb') as fdst: shutil.copyfileobj(fsrc,fdst)
        total=0; changed=0
        # combined scan normal+deep (deep will include normal again but dedup by offset)
        envs = scan_uboot_env(src_fw)
        deep_envs = scan_uboot_env(src_fw, deep=True)
        if not envs and not deep_envs:
            log_func('[UBOOT] v1 scan empty, using v2 extended scan')
            deep_envs = scan_uboot_env_v2(src_fw, deep=True)
        env_by_off={}
        for e in envs+deep_envs:
            env_by_off[e['offset']]=e
        for off,e in sorted(env_by_off.items()):
            size=e['size']; total+=1
            with open(dst_fw,'rb') as f: f.seek(off); block=f.read(size)
            if len(block)!=size: continue
            stored_crc=struct.unpack('<I', block[:4])[0]
            data=block[4:]
            end_double=data.find(b'\x00\x00')
            if end_double==-1: continue
            env_region=data[:end_double+1]
            pairs=[]
            for raw in env_region.split(b'\x00'):
                if not raw: continue
                if b'=' not in raw: continue
                k,v=raw.split(b'=',1)
                try: pairs.append((k.decode(), v.decode(errors='ignore')))
                except: pass
            updated=False
            for i,(k,v) in enumerate(pairs):
                if k=='bootdelay':
                    if v!=str(new_val):
                        pairs[i]=(k,str(new_val)); updated=True
                    else:
                        updated=True
                    break
            else:
                pairs.append(('bootdelay', str(new_val))); updated=True
            if not updated:
                continue
            kv_bytes=b''.join(f"{k}={v}".encode()+b'\x00' for k,v in pairs)
            new_env_region=kv_bytes+b'\x00'
            if len(new_env_region)+1 > size-4:
                log_func(f"[UBOOT] env block @0x{off:X} overflow skip")
                continue
            new_crc=binascii.crc32(new_env_region)&0xffffffff
            used=len(new_env_region)+1
            padding=b'\x00'*((size-4)-used)
            new_block=struct.pack('<I', new_crc)+new_env_region+b'\x00'+padding
            with open(dst_fw,'r+b') as f: f.seek(off); f.write(new_block)
            changed+=1
            log_func(f"[UBOOT] bootdelay patch ALL @0x{off:X} size=0x{size:X} crc_old={stored_crc:08x} crc_new={new_crc:08x}")
        if changed==0:
            log_func('[UBOOT] ไม่พบ env สำหรับ patch-all')
            return False
        log_func(f"[UBOOT] สำเร็จ bootdelay={new_val} บล็อค {changed}/{total}")
        return True
    except Exception as e:
        log_func(f"[UBOOT] patch-all error: {e}")
        return False

def patch_compiled_uboot_bootdelay(src_fw, dst_fw, new_val, log_func=lambda m:None, search_limit=0x80000):
    """Patch bootdelay inside the compiled-in default environment string in U-Boot binary.
    - search_limit: int bytes from start, or None for full file
    - Only patches when new digits length == old digits length (avoid shifting)
    - Returns True if at least one replacement
    """
    try:
        with open(src_fw,'rb') as f: data=bytearray(f.read())
        limit=len(data) if (search_limit is None) else min(len(data), search_limit)
        target = b'bootdelay='
        count=0
        i=0
        new_s=str(new_val).encode()
        while True:
            p=data.find(target, i, limit)
            if p==-1: break
            # read digits after '=' until non-digit or max 5 chars
            d_start=p+len(target)
            d_end=d_start
            while d_end<limit and chr(data[d_end]).isdigit():
                d_end+=1
            old_digits=data[d_start:d_end]
            if not old_digits:
                i=d_end; continue
            if len(old_digits)==len(new_s):
                if old_digits!=new_s:
                    log_func(f"[UBOOT] compiled bootdelay patch {old_digits.decode()}->{new_s.decode()} at 0x{p:X}")
                    data[d_start:d_end]=new_s; count+=1
            else:
                log_func(f"[UBOOT] skip compiled bootdelay at 0x{p:X} (len mismatch {len(old_digits)} vs {len(new_s)})")
            i=d_end
        if count:
            with open(dst_fw,'wb') as f: f.write(data)
            return True
        return False
    except Exception as e:
        log_func(f"[UBOOT] compiled patch error: {e}")
        return False

def patch_uboot_env_vars(src_fw, dst_fw, target_offset, target_size, updates: dict, log_func=lambda m:None):
    """Patch arbitrary U-Boot environment variables.
    updates: {key: new_value or '' (empty string means delete)}
    target_offset/size must match one of scanned blocks.
    """
    import struct, binascii
    try:
        with open(src_fw,'rb') as f:
            f.seek(target_offset); block=f.read(target_size)
        if len(block)!=target_size:
            log_func('[UBOOT] อ่าน block ไม่ครบ'); return False, 'short read'
        stored_crc=struct.unpack('<I', block[:4])[0]
        data=block[4:]
        end_double=data.find(b'\x00\x00')
        if end_double==-1:
            log_func('[UBOOT] ไม่พบ termination (\0\0)'); return False, 'no terminator'
        env_region=data[:end_double+1]
        pairs=[]; order=[]
        for raw in env_region.split(b'\x00'):
            if not raw: continue
            if b'=' not in raw: continue
            k,v=raw.split(b'=',1)
            try:
                k=k.decode(); v=v.decode(errors='ignore')
            except: continue
            pairs.append((k,v)); order.append(k)
        # Apply updates
        new_pairs=[]; updated_keys=set()
        for k,v in pairs:
            if k in updates:
                nv=updates[k]
                updated_keys.add(k)
                if nv=='' or nv is None:
                    # deletion
                    continue
                if nv!=v:
                    new_pairs.append((k,str(nv)))
                else:
                    new_pairs.append((k,v))
            else:
                new_pairs.append((k,v))
        # Add new keys not present
        for k,nv in updates.items():
            if k not in updated_keys and (nv is not None) and nv!='':
                new_pairs.append((k,str(nv)))
        kv_bytes=b''.join(f"{k}={v}".encode()+b'\x00' for k,v in new_pairs)
        new_env_region=kv_bytes+b'\x00'
        if len(new_env_region)+1 > target_size-4:
            log_func('[UBOOT] env ใหม่ยาวเกิน block'); return False, 'overflow'
        new_crc=binascii.crc32(new_env_region)&0xffffffff
        used=len(new_env_region)+1
        padding=b'\x00'*((target_size-4)-used)
        new_block=struct.pack('<I', new_crc)+new_env_region+b'\x00'+padding
        with open(src_fw,'rb') as fsrc, open(dst_fw,'wb') as fdst: shutil.copyfileobj(fsrc,fdst)
        with open(dst_fw,'r+b') as f: f.seek(target_offset); f.write(new_block)
        log_func(f"[UBOOT] Patch vars @0x{target_offset:X} size=0x{target_size:X} crc_old={stored_crc:08x} crc_new={new_crc:08x} updates={len(updates)}")
        return True, ''
    except Exception as e:
        log_func(f"[UBOOT] error: {e}"); return False, str(e)

def patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func, forced_port=None):
    # เพิ่ม getty สำหรับพอร์ตอนุกรมที่ตรวจพบ (auto-detect)
    tmpdir = tempfile.mkdtemp(prefix="patch-serial-")
    log_func(f"[TEMP] serial patch workspace: {tmpdir}")
    try:
        # Extract rootfs
        rootfs_bin = os.path.join(tmpdir, "rootfs.bin")
        with open(fw_path, "rb") as f:
            f.seek(rootfs_part['offset'])
            rootfs = f.read(rootfs_part['size'])
            with open(rootfs_bin, "wb") as fo:
                fo.write(rootfs)
        log_func(f"[INFO] ขนาด rootfs เดิม: {os.path.getsize(rootfs_bin)} bytes")
        unsquashfs_dir = os.path.join(tmpdir, "unsquashfs")
        os.makedirs(unsquashfs_dir)
        ok, err = extract_rootfs(rootfs_part['fs'], rootfs_bin, unsquashfs_dir, log_func)
        if not ok:
            log_func(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
            return False, err
        # detect preferred serial port
        if forced_port:
            serial_port = forced_port
            log_func(f"[SERIAL] using user-selected port {serial_port}")
        else:
            serial_port = auto_detect_tty_port_from_context(fw_path, rootfs_part, unsquashfs_dir, log_func)
        inittab_path = os.path.join(unsquashfs_dir, "etc", "inittab")
        if os.path.exists(inittab_path):
            # avoid duplicate entries
            existing = ''
            try:
                existing = open(inittab_path,'r',encoding='utf-8',errors='ignore').read()
            except Exception: pass
            getty_line = f"{serial_port}:12345:respawn:/sbin/getty -L {serial_port} 115200 vt100"
            if serial_port not in existing:
                with open(inittab_path, "a", encoding="utf-8") as f:
                    f.write("\n"+getty_line+"\n")
                log_func(f"เพิ่ม getty {serial_port} ใน inittab สำเร็จ")
            else:
                log_func(f"พบ {serial_port} อยู่แล้วใน inittab (ข้าม)")
        else:
            log_func("ไม่พบ /etc/inittab ใน rootfs (สร้างใหม่พร้อม getty)")
            try:
                os.makedirs(os.path.dirname(inittab_path), exist_ok=True)
                with open(inittab_path,'w',encoding='utf-8') as f:
                    f.write(f"::sysinit:/bin/mount -t proc proc /proc\n")
                    f.write(f"::sysinit:/bin/mount -t sysfs sysfs /sys\n")
                    f.write(f"::respawn:/sbin/getty -L {serial_port} 115200 vt100\n")
                log_func("สร้าง inittab ใหม่สำเร็จ")
            except Exception as e:
                log_func(f"สร้าง inittab ใหม่ล้มเหลว: {e}")
        # Repack rootfs
        new_rootfs_bin = os.path.join(tmpdir, "new_rootfs.bin")
        ok, err = repack_rootfs(rootfs_part['fs'], unsquashfs_dir, new_rootfs_bin, log_func)
        if not ok:
            log_func(f"❌ repack rootfs ไม่สำเร็จ: {err}")
            return False, err
        new_size = os.path.getsize(new_rootfs_bin)
        log_func(f"[INFO] ขนาด rootfs ใหม่: {new_size} bytes (limit: {rootfs_part['size']} bytes)")
        if new_size > rootfs_part['size']:
            log_func("❌ rootfs ใหม่ใหญ่เกินขอบเขตเดิม — พยายามลดขนาดอัตโนมัติ...")
            # sequence of shrink attempts
            shrink_steps = []

            # Step 1: strip ELF symbols (if strip available)
            def step_strip_binaries():
                stripped = 0
                strip_bin = shutil.which('strip')
                if not strip_bin:
                    log_func('[AI] ไม่พบเครื่องมือ strip; ข้ามการ strip บินารี่')
                    return 0
                for dp, dn, fnames in os.walk(unsquashfs_dir):
                    for fname in fnames:
                        fpath = os.path.join(dp, fname)
                        try:
                            with open(fpath, 'rb') as tf:
                                head = tf.read(4)
                            if head == b'\x7fELF':
                                # attempt strip --strip-unneeded
                                try:
                                    subprocess.run([strip_bin, '--strip-unneeded', fpath], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                                    stripped += 1
                                except Exception:
                                    # try without flags
                                    try:
                                        subprocess.run([strip_bin, fpath], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                                        stripped += 1
                                    except Exception:
                                        pass
                        except Exception:
                            continue
                log_func(f"[AI] strip: ดำเนินการ strip บินารี่แล้ว {stripped} ไฟล์")
                return stripped

            # Step 2: remove docs, man, locale, logs, tmp
            def step_remove_docs_logs():
                removed = []
                patterns = ['usr/share/doc', 'usr/share/man', 'usr/share/locale', 'var/log', 'tmp', 'var/tmp', 'usr/share/locale-langpack']
                for p in patterns:
                    full = os.path.join(unsquashfs_dir, p)
                    if os.path.exists(full):
                        try:
                            # record size before removal
                            sz = 0
                            for rp, dn, fn in os.walk(full):
                                for f in fn:
                                    try:
                                        sz += os.path.getsize(os.path.join(rp, f))
                                    except Exception:
                                        pass
                            shutil.rmtree(full, ignore_errors=True)
                            removed.append((p, sz))
                            log_func(f"[AI] ลบ {p} (ประมาณ {sz} bytes)")
                        except Exception:
                            continue
                return removed

            # Attempt to reduce size by removing unnecessary files
            def step_remove_unnecessary_files():
                removed = []
                patterns = ['usr/share/doc', 'usr/share/man', 'usr/share/locale', 'var/log', 'tmp', 'var/tmp']
                for p in patterns:
                    full = os.path.join(unsquashfs_dir, p)
                    if os.path.exists(full):
                        try:
                            shutil.rmtree(full, ignore_errors=True)
                            removed.append(p)
                            log_func(f"[AI] Removed unnecessary files: {p}")
                        except Exception as e:
                            log_func(f"[AI] Failed to remove {p}: {e}")
                return removed

            # run steps iteratively and try repack after each
            try_order = [step_strip_binaries, step_remove_docs_logs, step_remove_unnecessary_files]
            success = False
            for step in try_order:
                res = step()
                # repack with same compression first
                ok, err = repack_rootfs(rootfs_part['fs'], unsquashfs_dir, new_rootfs_bin, log_func)
                if not ok:
                    log_func(f"[AI] หลังขั้นตอน {step.__name__} pack ล้มเหลว: {err}")
                else:
                    new_size = os.path.getsize(new_rootfs_bin)
                    log_func(f"[AI] หลัง {step.__name__} ขนาด rootfs: {new_size} bytes")
                    if new_size <= rootfs_part['size']:
                        success = True
                        log_func("[AI] ลดขนาดสำเร็จหลังขั้นตอนอัตโนมัติ")
                        break

            # if still too big, try stronger compression (xz)
            if not success:
                log_func('[AI] พยายามใช้การบีบอัดที่แรงขึ้น: xz')
                ok, err = repack_rootfs(rootfs_part['fs'], unsquashfs_dir, new_rootfs_bin, log_func, force_comp='xz')
                # (no UI worker here — this helper runs outside the GUI context)

                # diagnostic: list largest files in the unsquashfs_dir to help user
                file_sizes = []
                for root, _, files in os.walk(unsquashfs_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        try:
                            sz = os.path.getsize(fpath)
                            file_sizes.append((sz, os.path.relpath(fpath, unsquashfs_dir)))
                        except Exception:
                            continue
                largest = sorted(file_sizes, reverse=True)[:10]
                if largest:
                    log_func("[TOP] ไฟล์ที่กินพื้นที่มากสุดใน rootfs ใหม่:")
                    for sz, path in largest:
                        log_func(f"  {path}: {sz} bytes")
                return False, "new rootfs too large"
            # success: new_rootfs_bin now contains smaller image
            new_size = os.path.getsize(new_rootfs_bin)
            log_func(f"[OK] ได้ rootfs ใหม่ขนาด {new_size} bytes หลังการลดอัตโนมัติ")
        # Write new firmware
        with open(fw_path, "rb") as f:
            fw_data = bytearray(f.read())
        with open(new_rootfs_bin, "rb") as f:
            new_rootfs = f.read()
        fw_data[rootfs_part['offset']:rootfs_part['offset'] + len(new_rootfs)] = new_rootfs
        # fill zero if needed
        if len(new_rootfs) < rootfs_part['size']:
            fw_data[rootfs_part['offset'] + len(new_rootfs):rootfs_part['offset'] + rootfs_part['size']] = b'\x00' * (rootfs_part['size'] - len(new_rootfs))
        with open(out_path, "wb") as f:
            f.write(fw_data)
        log_func(f"✅ Patch shell serial สำเร็จ: {out_path}")
        return True, ""
    finally:
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

def patch_rootfs_network(fw_path, rootfs_part, out_path, log_func):
    # ปิด telnet / ftp (ลบหรือคอมเมนต์ใน inetd.conf) ถ้าไม่พบให้ log ไว้
    tmpdir = tempfile.mkdtemp(prefix="patch-net-")
    log_func(f"[TEMP] network patch workspace: {tmpdir}")
    try:
        rootfs_bin = os.path.join(tmpdir, "rootfs.bin")
        with open(fw_path, "rb") as f:
            f.seek(rootfs_part['offset'])
            rootfs = f.read(rootfs_part['size'])
            with open(rootfs_bin, "wb") as fo:
                fo.write(rootfs)
        unsquashfs_dir = os.path.join(tmpdir, "unsquashfs")
        os.makedirs(unsquashfs_dir)
        ok, err = extract_rootfs(rootfs_part['fs'], rootfs_bin, unsquashfs_dir, log_func)
        if not ok:
            log_func(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
            return False, err
        inetd_path = os.path.join(unsquashfs_dir, "etc", "inetd.conf")
        if os.path.exists(inetd_path):
            try:
                with open(inetd_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                new_lines = []
                removed = 0
                for ln in lines:
                    low = ln.lower()
                    if ('telnet' in low or 'ftp' in low) and not low.strip().startswith('#'):
                        new_lines.append('#DISABLED ' + ln)
                        removed += 1
                    else:
                        new_lines.append(ln)
                with open(inetd_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                log_func(f"ปิด telnet/ftp ใน inetd.conf (คอมเมนต์ {removed} บรรทัด)")
            except Exception as e:
                log_func(f"แก้ไข inetd.conf ไม่สำเร็จ: {e}")
        else:
            log_func("ไม่พบ etc/inetd.conf (อาจไม่มีบริการ telnet/ftp)")
        # Repack rootfs
        new_rootfs_bin = os.path.join(tmpdir, "new_rootfs.bin")
        ok, err = repack_rootfs(rootfs_part['fs'], unsquashfs_dir, new_rootfs_bin, log_func)
        if not ok:
            log_func(f"❌ pack rootfs ไม่สำเร็จ: {err}")
            return False, err
        # Write new firmware
        with open(fw_path, "rb") as f:
            fw_data = bytearray(f.read())
        with open(new_rootfs_bin, "rb") as f:
            new_rootfs = f.read()
        if len(new_rootfs) > rootfs_part['size']:
            log_func("❌ rootfs ใหม่ใหญ่เกินขอบเขตเดิม ไม่สามารถ patch ได้")
            return False, "rootfs too large"
        fw_data[rootfs_part['offset']:rootfs_part['offset'] + len(new_rootfs)] = new_rootfs
        if len(new_rootfs) < rootfs_part['size']:
            fw_data[rootfs_part['offset'] + len(new_rootfs):rootfs_part['offset'] + rootfs_part['size']] = b'\x00' * (rootfs_part['size'] - len(new_rootfs))
        with open(out_path, "wb") as f:
            f.write(fw_data)
        log_func(f"✅ Patch shell network สำเร็จ: {out_path}")
        return True, ""
    finally:
        shutil.rmtree(tmpdir)

def patch_root_password(fw_path, rootfs_part, password, out_path, log_func):
    tmpdir = tempfile.mkdtemp(prefix="patch-rootpw-")
    log_func(f"[TEMP] root password patch workspace: {tmpdir}")
    try:
        rootfs_bin = os.path.join(tmpdir, "rootfs.bin")
        with open(fw_path, "rb") as f:
            f.seek(rootfs_part['offset'])
            rootfs = f.read(rootfs_part['size'])
            with open(rootfs_bin, "wb") as fo:
                fo.write(rootfs)
        unsquashfs_dir = os.path.join(tmpdir, "unsquashfs")
        os.makedirs(unsquashfs_dir)
        ok, err = extract_rootfs(rootfs_part['fs'], rootfs_bin, unsquashfs_dir, log_func)
        if not ok:
            log_func(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
            return False, err
        shadow_path = os.path.join(unsquashfs_dir, "etc", "shadow")
        if not os.path.exists(shadow_path):
            log_func("❌ ไม่พบ /etc/shadow ใน rootfs")
            return False, "shadow missing"
        # Allow passing a pre-computed hash (starts with $6$) so imported profiles can work without plain password.
        if password == "":
            new_hash = "!"  # lock root
        elif password.startswith("$6$"):
            new_hash = password  # already hashed (sha512-crypt)
        else:
            new_hash = sha512_crypt.hash(password, rounds=5000)
        with open(shadow_path, "r") as f:
            lines = f.readlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("root:"):
                found = True
                parts = line.split(":")
                parts[1] = new_hash
                new_lines.append(":".join(parts))
            else:
                new_lines.append(line)
        if not found:
            log_func("❌ ไม่พบ user root ใน /etc/shadow")
            return False, "root user not found"
        with open(shadow_path, "w") as f:
            for l in new_lines:
                f.write(l if l.endswith("\n") else l + "\n")
        new_rootfs_bin = os.path.join(tmpdir, "new_rootfs.bin")
        ok, err = repack_rootfs(rootfs_part['fs'], unsquashfs_dir, new_rootfs_bin, log_func)
        if not ok:
            log_func(f"❌ pack rootfs ไม่สำเร็จ: {err}")
            return False, err
        with open(fw_path, "rb") as f:
            fw_data = bytearray(f.read())
        with open(new_rootfs_bin, "rb") as f:
            new_rootfs = f.read()
        if len(new_rootfs) > rootfs_part['size']:
            log_func("❌ rootfs ใหม่ใหญ่เกินขอบเขตเดิม ไม่สามารถ patch ได้")
            return False, "rootfs too large"
        fw_data[rootfs_part['offset']:rootfs_part['offset'] + len(new_rootfs)] = new_rootfs
        if len(new_rootfs) < rootfs_part['size']:
            fw_data[rootfs_part['offset'] + len(new_rootfs):rootfs_part['offset'] + rootfs_part['size']] = b'\x00' * (rootfs_part['size'] - len(new_rootfs))
        with open(out_path, "wb") as f:
            f.write(fw_data)
        log_func(f"✅ Patch root password สำเร็จ: {out_path}")
        return True, ""
    finally:
        shutil.rmtree(tmpdir)

# ---- Wrapper names expected by GUI (map to the above helpers) ----
def core_patch_boot_delay(fw_path, rootfs_part, new_delay, out_path, log_func):
    return patch_boot_delay(fw_path, rootfs_part, new_delay, out_path, log_func)

def core_patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func, forced_port=None):
    if rootfs_part is None:
        try:
            parts = multisquash.detect_squashfs(fw_path)
            if parts:
                rootfs_part = {'offset': parts[0].offset, 'size': parts[0].size, 'fs': 'squashfs', 'desc': parts[0].desc}
        except Exception:
            pass
    if rootfs_part is None:
        return False, 'no rootfs part'
    return patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func, forced_port=forced_port)

def core_patch_rootfs_network(fw_path, rootfs_part, out_path, log_func):
    if rootfs_part is None:
        try:
            parts = multisquash.detect_squashfs(fw_path)
            if parts:
                rootfs_part = {'offset': parts[0].offset, 'size': parts[0].size, 'fs': 'squashfs', 'desc': parts[0].desc}
        except Exception:
            pass
    if rootfs_part is None:
        return False, 'no rootfs part'
    return patch_rootfs_network(fw_path, rootfs_part, out_path, log_func)

def core_patch_root_password(fw_path, rootfs_part, password, out_path, log_func):
    if rootfs_part is None:
        try:
            parts = multisquash.detect_squashfs(fw_path)
            if parts:
                rootfs_part = {'offset': parts[0].offset, 'size': parts[0].size, 'fs': 'squashfs', 'desc': parts[0].desc}
        except Exception:
            pass
    if rootfs_part is None:
        return False, 'no rootfs part'
    return patch_root_password(fw_path, rootfs_part, password, out_path, log_func)

# ---- Utility helpers missing after refactor ----
def sha256sum(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def generate_hexdiff(path_a: str, path_b: str, limit: int = 4096) -> str:
    """Lightweight hex diff used for metadata artifact."""
    try:
        a = open(path_a,'rb').read(limit)
        b = open(path_b,'rb').read(limit)
    except Exception as e:
        return f'hexdiff read error: {e}'
    out = []
    for i in range(0, min(len(a), len(b)), 16):
        chunk_a = a[i:i+16]
        chunk_b = b[i:i+16]
        if chunk_a != chunk_b:
            out.append(f'{i:08x}: {chunk_a.hex()} -> {chunk_b.hex()}')
    if not out:
        return 'no differences (within limit)'
    return '\n'.join(out)

def deep_scan_file(path: str):
    """Placeholder deep scan returning simple summary (can be expanded)."""
    try:
        sz = os.path.getsize(path)
        return {'path': path, 'size': sz}
    except Exception:
        return None

class MainWindow(QMainWindow):
    # signal used for thread -> main-thread logging
    thread_log = Signal(str)

    def __init__(self):
        # runtime health-check: write a persistent small log entry to help diagnose
        try:
            os.makedirs(self.output_dir if hasattr(self, 'output_dir') else os.path.abspath('output'), exist_ok=True)
        except Exception:
            pass
        try:
            health_dir = os.path.expanduser('~/.local/share/firmware_toolkit')
            os.makedirs(health_dir, exist_ok=True)
            health_file = os.path.join(health_dir, 'health.log')
            with open(health_file, 'a') as hf:
                hf.write(f"{datetime.datetime.now(datetime.UTC).isoformat()} pid={os.getpid()} python={sys.executable} argv={sys.argv} DISPLAY={os.environ.get('DISPLAY')}\n")
        except Exception:
            pass
        super().__init__()
        # connect thread log signal to UI log slot to ensure UI updates run on main thread
        try:
            self.thread_log.connect(self.log)
        except Exception:
            pass
        self._bg_threads = []  # keep QThreads alive
        self.setWindowTitle(_('app_title'))

        # ฟังก์ชัน helper สำหรับล็อก 2 ภาษา (เรียกใช้ภายหลังเพื่อให้ code อ่านง่าย)
        def _init_log_helpers():
            try:
                self._th_marker = True  # flag เผื่ออนาคต
            except Exception:
                pass
        _init_log_helpers()

        # Paths / state (ต้องมาก่อนเมนู/Widget อื่น)
        self.original_fw_path = None
        self.patched_fw_path = None
        self.fw_path = None
        self.output_dir = os.path.abspath('output'); os.makedirs(self.output_dir, exist_ok=True)
        self.logs_dir = os.path.abspath('logs'); os.makedirs(self.logs_dir, exist_ok=True)

        # New automatic dependency prepare (first launch)
        self.deps_flag = os.path.expanduser('~/.local/share/firmware_toolkit/deps_installed')
        try:
            os.makedirs(os.path.dirname(self.deps_flag), exist_ok=True)
        except Exception:
            pass
        if not os.path.exists(self.deps_flag):
            import sys
            if os.environ.get("QT_QPA_PLATFORM") == "offscreen" or not sys.stdin.isatty():
                self.thread_log.emit('[SETUP] Headless or no TTY: skipping FMK dependency install prompt')
            else:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1000, self._prompt_install_fmk_deps)
        else:
            self.thread_log.emit('[SETUP] Dependencies already installed (flag present)')

        # --- Menus ---
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        act_open = QAction(_('btn_open_fw'), self); act_open.triggered.connect(self.select_firmware); file_menu.addAction(act_open)
        tools_menu = menubar.addMenu('Tools')
        for txt, act in [(_('btn_patch_boot'),'boot_delay'),(_('btn_patch_serial'),'serial'),(_('btn_patch_network'),'network')]:
            a = QAction(txt, self); a.triggered.connect(lambda _=False, ac=act: self._run_quick_patch(ac)); tools_menu.addAction(a)
        tools_menu.addSeparator()

        for txt, slot in [
            ('Boot Delay (Popup Auto)', self.prompt_and_patch_boot_delay),
            ('Selective Patch...', self.open_selective_patch_dialog),
            ('RootFS Editor', self.edit_rootfs_file),
            ('U-Boot Env Editor', self.open_uboot_env_editor_dialog),
            ('Custom Script', self.run_custom_script),
            ('Check Hash / Signature', self.check_hash_signature),
            ('Tool Chains Summary', self._show_tool_chains),
            ('Binwalk Self-Test', self._binwalk_self_test),
            ]:
            a = QAction(txt, self); a.triggered.connect(slot); tools_menu.addAction(a)

        # Add Install FMK Dependencies action (will auto-hide if nothing missing)
        self.act_install_deps = QAction('Install FMK Dependencies', self)
        self.act_install_deps.triggered.connect(self.install_fmk_deps)
        tools_menu.addAction(self.act_install_deps)
        try: self._update_install_deps_visibility()
        except Exception: pass
        # สร้าง UI หลัก
        try:
            self.build_ui()
        except Exception as e:
            try: self.log(f'[INIT] build_ui error: {e}')
            except: pass
        # แสดงสถานะเครื่องมือ vendor (tools_bin) ทันที
        try: log_vendor_tools(self.thread_log.emit)
        except Exception: pass
        # ลงทะเบียนเมนู vendor
        try: self._register_vendor_tool_actions()
        except Exception as e:
            try: self.log(f'[TOOLS] ผูกเมนู vendor ล้มเหลว: {e}')
            except: pass
        # แสดง summary chain ของเครื่องมือ (สำหรับ debug/fallback)
        try: tool_log_summary(self.thread_log.emit)
        except Exception: pass

        # (ใช้ build_ui สำหรับสร้างหน้าและเมนูทั้งหมดแล้ว ไม่ต้องสร้างซ้ำที่นี่)

    def _prompt_install_fmk_deps(self):
        ans = QMessageBox.question(self, 'FMK dependencies',
            'ต้องการติดตั้ง FMK dependencies (sudo) ตอนนี้หรือไม่?\n\n'
            'จำเป็นสำหรับการใช้งานฟีเจอร์หลักของโปรแกรม',
            QMessageBox.Yes | QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.install_fmk_deps(automatic=True)

    def _update_install_deps_visibility(self):
        """Hide Install FMK Dependencies menu if all required tool capabilities and key packages exist."""
        try:
            from tool_registry import (
                get_candidates,
                CAP_SQUASHFS_EXTRACT, CAP_SQUASHFS_PACK,
                CAP_CRAMFS_EXTRACT, CAP_CRAMFS_PACK,
                CAP_JFFS2_PACK, CAP_YAFFS2_PACK
            )
            import shutil, subprocess
            def _pkg_installed(pkg):
                try:
                    subprocess.check_output(['dpkg','-s',pkg], stderr=subprocess.DEVNULL)
                    return True
                except Exception:
                    return False
            needed_ok = True
            if not get_candidates(CAP_SQUASHFS_EXTRACT) or not get_candidates(CAP_SQUASHFS_PACK): needed_ok = False
            if not get_candidates(CAP_CRAMFS_EXTRACT) or not get_candidates(CAP_CRAMFS_PACK): needed_ok = False
            if not get_candidates(CAP_JFFS2_PACK): needed_ok = False
            # YAFFS2 pack optional
            if shutil.which('binwalk') is None and not _pkg_installed('binwalk'): needed_ok = False
            if needed_ok:
                self.act_install_deps.setVisible(False)
            else:
                self.act_install_deps.setVisible(True)
        except Exception:
            pass

    def _show_tool_chains(self):
        try:
            from tool_registry import log_summary
            buf = []
            def _c(msg): buf.append(msg)
            log_summary(_c)
            QMessageBox.information(self,'Tool Chains','\n'.join(buf))
        except Exception as e:
            QMessageBox.warning(self,'Tool Chains',f'Error: {e}')

    def prompt_and_patch_boot_delay(self):
        """Popup to choose new bootdelay then auto patch all candidate offsets (currently 0x100)."""
        try:
            if not getattr(self, 'fw_path', None):
                QMessageBox.information(self,'Boot Delay','Please open a firmware first'); return
            val, ok = QInputDialog.getInt(self,'Boot Delay','New boot delay (seconds):',3,0,600,1)
            if not ok: return
            outp = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','')+f'_bootdelay{val}.bin')
            okc, msg = core_patch_boot_delay(self.fw_path, None, val, outp, lambda m: self.thread_log.emit(m))
            if okc:
                self.log(f'[BOOT] Patched bootdelay={val} -> {outp}')
                QMessageBox.information(self,'Boot Delay',f'Success -> {outp}')
            else:
                self.log(f'[BOOT] patch failed: {msg}')
                QMessageBox.warning(self,'Boot Delay', f'Failed: {msg}')
        except Exception as e:
            try:
                self.log(f'[BOOT] exception: {e}')
            except Exception: pass
            try: QMessageBox.warning(self,'Boot Delay', f'Exception: {e}')
            except Exception: pass

    def _binwalk_self_test(self):
        import shutil, subprocess, tempfile
        bw = shutil.which('binwalk')
        if not bw:
            QMessageBox.information(self,'Binwalk','ไม่พบ binwalk ใน PATH')
            return
        # simple sanity: run binwalk on itself (should list ELF sections) or a tiny temp file
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(b'\x7fELF\x00testbinwalk')
            tmp.close()
            proc = subprocess.run([bw,'-l','32',tmp.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=8)
            out = proc.stdout.splitlines()[:25]
            QMessageBox.information(self,'Binwalk OK','พบ binwalk และรันสำเร็จ\n'+'\n'.join(out))
        except Exception as e:
            QMessageBox.warning(self,'Binwalk','binwalk run error: '+str(e))

    def build_ui(self):
        """Build the full UI (pages, menus, logs) in a single well‑scoped method."""
        # Containers / base widgets
        self.pages = QStackedWidget()
        self._submenu_connected = False
        self._last_sub_index = {}

        # ---------------- Dashboard Page ----------------
        page_dashboard = QWidget(); dash_l = QVBoxLayout(page_dashboard); dash_l.setSpacing(8); dash_l.setContentsMargins(12,12,12,12)
        b_open = QPushButton(_('btn_open_fw')); b_open.clicked.connect(self.select_firmware); dash_l.addWidget(b_open)
        actions_row = QHBoxLayout(); self.btn_analyze = QPushButton('วิเคราะห์เฟิร์มแวร์ (Analyze Firmware)')
        if hasattr(self, 'start_manual_analysis'): self.btn_analyze.clicked.connect(self.start_manual_analysis)
        actions_row.addWidget(self.btn_analyze)
        for txt, act in [(_('btn_patch_boot'),'boot_delay'),(_('btn_patch_serial'),'serial'),(_('btn_patch_network'),'network')]:
            b = QPushButton(txt); b.clicked.connect(lambda _=False, ac=act: self._run_quick_patch(ac)); actions_row.addWidget(b)
        actions_row.addStretch(); dash_l.addLayout(actions_row)
        self.ai_summary_view = QTextEdit(); self.ai_summary_view.setReadOnly(True); self.ai_summary_view.setFixedHeight(180); dash_l.addWidget(self.ai_summary_view)
        self.apply_suggested_btn = QPushButton('Apply suggested pipeline'); self.apply_suggested_btn.setObjectName('primaryButton'); self.apply_suggested_btn.clicked.connect(self.apply_suggested_pipeline); self.apply_suggested_btn.setEnabled(False)
        self.cancel_apply_btn = QPushButton('Cancel'); self.cancel_apply_btn.setObjectName('cancelButton'); self.cancel_apply_btn.setEnabled(False)
        try: self.apply_suggested_btn.setFixedHeight(36); self.cancel_apply_btn.setFixedHeight(36)
        except Exception: pass
        def _cancel_apply():
            try:
                w = getattr(self, '_active_apply_worker', None)
                if not w: self.log('[AI] No active apply worker to cancel'); return
                ans = QMessageBox.question(self, 'Cancel apply', 'Cancel running apply pipeline?', QMessageBox.Yes | QMessageBox.No)
                if ans != QMessageBox.Yes: return
                if getattr(w, 'request_cancel', None): w.request_cancel(); self.log('[AI] Cancel requested')
                else: self.log('[AI] Worker cannot be cancelled')
            except Exception as e: self.log(f'[AI] cancel error: {e}')
        self.cancel_apply_btn.clicked.connect(_cancel_apply)
        hbtn = QHBoxLayout(); hbtn.addWidget(self.apply_suggested_btn); hbtn.addWidget(self.cancel_apply_btn); hbtn.addStretch(); dash_l.addLayout(hbtn)
        self.apply_progress = QProgressBar(); self.apply_progress.setMinimum(0); self.apply_progress.setMaximum(100); self.apply_progress.setValue(0); self.apply_progress.setVisible(False)
        try: self.apply_progress.setFixedHeight(18); self.apply_progress.setTextVisible(True)
        except Exception: pass
        dash_l.addWidget(self.apply_progress); dash_l.addStretch(); self.pages.addWidget(page_dashboard)

        # ---------------- Tools Page ----------------
        page_tools = QWidget(); t_l = QVBoxLayout(page_tools)
        self.msq_allow_destructive = QCheckBox('Allow destructive trimming (remove logs/tmp/docs)')
        t_l.addWidget(self.msq_allow_destructive)
        for txt, slot in [('Multi-Squash: Dry-run', self.multi_squash_dryrun), ('Multi-Squash: Apply', self.multi_squash_apply)]:
            b = QPushButton(txt); b.clicked.connect(slot); t_l.addWidget(b)
        for txt, slot in [('Auto-Run: Dry (A)', lambda: self.auto_run_mode('A')), ('Auto-Run: Patch (B)', lambda: self.auto_run_mode('B')), ('Archive Outputs', self.archive_outputs)]:
            b = QPushButton(txt); b.clicked.connect(slot); t_l.addWidget(b)
        t_l.addStretch(); self.pages.addWidget(page_tools)

        # ---------------- Special Page ----------------
        page_special = QWidget(); sp_l = QVBoxLayout(page_special); sp_l.addWidget(QLabel('Special functions and utilities'))
        # U-Boot env candidates area (initially hidden until scan)
        self.uboot_env_group = QGroupBox('U-Boot Environment (Detected)')
        env_gl = QVBoxLayout(self.uboot_env_group)
        self.env_list = QTreeWidget(); self.env_list.setHeaderLabels(['Offset','Size','Type','Vars','CRC','Bootdelay','Score'])
        self.env_list.setColumnWidth(0,90); self.env_list.setColumnWidth(1,60); self.env_list.setColumnWidth(2,70)
        env_btn_row = QHBoxLayout()
        self.btn_scan_env = QPushButton('Scan Env (v2)')
        self.btn_export_env = QPushButton('Export JSON')
        self.btn_export_env.setEnabled(False)
        env_btn_row.addWidget(self.btn_scan_env); env_btn_row.addWidget(self.btn_export_env); env_btn_row.addStretch()
        env_gl.addLayout(env_btn_row); env_gl.addWidget(self.env_list)
        self.uboot_env_group.setVisible(False)
        sp_l.addWidget(self.uboot_env_group)
        def _scan_env():
            if not getattr(self, 'fw_path', None):
                QMessageBox.information(self, 'Env Scan', 'Select a firmware first')
                return
            self.log('[UBOOT] scanning (v2)...')
            try:
                keep_mismatch = getattr(self, 'cfg_keep_crc_mismatch', True)
                cands = scan_uboot_env_v2(self.fw_path, deep=True, keep_crc_mismatch=keep_mismatch)
                self.env_list.clear()
                for c in cands[:200]:
                    it = QTreeWidgetItem([
                        f"0x{c['offset']:X}", f"0x{c['size']:X}", c.get('type','block'),
                        str(len(c.get('vars',{}))),
                        'OK' if c.get('crc_ok') else 'BAD',
                        str(c.get('bootdelay','')), f"{c.get('score',0):.1f}"
                    ])
                    if not c.get('crc_ok'):
                        it.setForeground(4, Qt.red)
                    if c.get('type')=='compiled':
                        it.setForeground(2, Qt.blue)
                    it.setData(0, Qt.UserRole, c)
                    self.env_list.addTopLevelItem(it)
                self.uboot_env_group.setVisible(True)
                self.btn_export_env.setEnabled(bool(cands))
                self.log_bilingual(f'สแกนพบ env {len(cands)} ชุด', f'Env candidates {len(cands)}')
            except Exception as e:
                self.log(f'[UBOOT] scan error: {e}')
        def _export_env():
            try:
                items = []
                for i in range(self.env_list.topLevelItemCount()):
                    it = self.env_list.topLevelItem(i)
                    data = it.data(0, Qt.UserRole)
                    if data:
                        # trim vars to safe length
                        vars_lim = {k:(v[:200]+'...') if len(v)>200 else v for k,v in data.get('vars',{}).items()}
                        d = {k:v for k,v in data.items() if k!='vars'}
                        d['vars']=vars_lim
                        items.append(d)
                if not items:
                    QMessageBox.information(self,'Export','No candidates to export')
                    return
                out_path = os.path.join(self.output_dir,'uboot_env_candidates.json')
                with open(out_path,'w',encoding='utf-8') as f: json.dump(items,f,ensure_ascii=False,indent=2)
                self.log(f'[UBOOT] wrote {out_path}')
            except Exception as e:
                self.log(f'[UBOOT] export error: {e}')
        self.btn_scan_env.clicked.connect(_scan_env)
        self.btn_export_env.clicked.connect(_export_env)
        parts_row = QHBoxLayout(); parts_row.addWidget(QLabel('RootFS Parts:'))
        self.parts_detect_btn = QPushButton('Detect Parts'); self.parts_detect_btn.clicked.connect(self.detect_rootfs_parts); parts_row.addWidget(self.parts_detect_btn)
        self.rootfs_part_spin = QSpinBox(); self.rootfs_part_spin.setMinimum(1); self.rootfs_part_spin.setMaximum(1); self.rootfs_part_spin.setEnabled(False)
        parts_row.addWidget(QLabel('Select:')); parts_row.addWidget(self.rootfs_part_spin); parts_row.addStretch(); sp_l.addLayout(parts_row)
        part_actions = QHBoxLayout()
        for txt, slot in [('Open RootFS Editor', self.edit_rootfs_file), ('Run Custom Script', self.run_custom_script), ('U-Boot Env Editor', self.open_uboot_env_editor_dialog)]:
            b = QPushButton(txt); b.clicked.connect(slot); part_actions.addWidget(b)
        part_actions.addStretch(); sp_l.addLayout(part_actions)
        self.parts_info_label = QLabel('No parts detected yet'); sp_l.addWidget(self.parts_info_label); sp_l.addStretch(); self.pages.addWidget(page_special)

        # ---------------- Settings Page ----------------
        page_settings = QWidget(); set_l = QVBoxLayout(page_settings); set_l.addWidget(QLabel('Settings and preferences'))
        try:
            auto_flag = os.path.expanduser('~/.local/share/firmware_toolkit/auto_install_enabled')
            self.chk_auto_install = QCheckBox('Auto-install FMK dependencies on first run'); self.chk_auto_install.setChecked(os.path.exists(auto_flag))
            def _toggle_auto_install(checked):
                try:
                    if checked: open(auto_flag,'w').write(datetime.datetime.now(datetime.UTC).isoformat()+'\n'); self.log('[SETUP] Auto-install enabled by user')
                    else:
                        try: os.remove(auto_flag)
                        except Exception: pass
                        self.log('[SETUP] Auto-install disabled by user')
                except Exception as e: self.log(f'[SETUP] toggle auto-install failed: {e}')
            self.chk_auto_install.toggled.connect(_toggle_auto_install); set_l.addWidget(self.chk_auto_install)
            # Theme
            set_l.addWidget(QLabel('Theme:'))
            self.cmb_theme = QComboBox(); self.cmb_theme.addItems(['dark','light'])
            cur_theme = 'dark'
            try:
                theme_flag = os.path.expanduser('~/.local/share/firmware_toolkit/theme')
                if os.path.exists(theme_flag): cur_theme = open(theme_flag,'r').read().strip()
            except Exception: pass
            idx = 0 if cur_theme=='dark' else 1; self.cmb_theme.setCurrentIndex(idx)
            def _on_theme_change(i):
                try: self.apply_theme(self.cmb_theme.currentText())
                except Exception as e: self.log(f'[THEME] selection failed: {e}')
            self.cmb_theme.currentIndexChanged.connect(_on_theme_change); set_l.addWidget(self.cmb_theme)
            # (Removed legacy Serial Port Section per new requirements)
            self.selected_serial_port = None
            # Advanced scanning options
            adv_box = QGroupBox('Advanced / U-Boot Scan')
            adv_l = QVBoxLayout(adv_box)
            self.chk_keep_crc = QCheckBox('Keep CRC mismatch candidates (recommended)')
            self.chk_keep_crc.setChecked(True)
            def _toggle_keep_crc(v):
                self.cfg_keep_crc_mismatch = bool(v)
            self.chk_keep_crc.toggled.connect(_toggle_keep_crc)
            self.cfg_keep_crc_mismatch = True
            self.chk_dynamic_menu = QCheckBox('Dynamic reorder main menu by usage (top items first)')
            self.chk_dynamic_menu.setChecked(False)
            def _toggle_dyn(v):
                self.cfg_dynamic_menu = bool(v)
                if v: self._maybe_reorder_menu()
            self.chk_dynamic_menu.toggled.connect(_toggle_dyn)
            self.cfg_dynamic_menu = False
            adv_l.addWidget(self.chk_keep_crc)
            adv_l.addWidget(self.chk_dynamic_menu)
            adv_l.addStretch()
            set_l.addWidget(adv_box)
        except Exception: pass
        set_l.addStretch(); self.pages.addWidget(page_settings)

        # ---------------- Left Main Menu ----------------
        self.main_menu_widget = QWidget(); main_menu_layout = QVBoxLayout(self.main_menu_widget); main_menu_layout.setContentsMargins(0,0,0,0); main_menu_layout.setSpacing(6)
        self.sub_menu_list = QListWidget(); self.sub_menu_list.setObjectName('subMenuList'); self.sub_menu_list.setFixedWidth(320)
        self.status_panel = QWidget(); status_l = QVBoxLayout(self.status_panel); self.status_label = QLabel('Ready'); self.status_label.setObjectName('statusLock'); status_l.addWidget(self.status_label); status_l.addStretch()

        # Declarative menu structure
        self.MENU_STRUCTURE = [
            {'key':'dashboard','title':'Dashboard','color':'#2962FF','submenu':[
                {'id':'analyze','text':'วิเคราะห์เฟิร์มแวร์ (Analyze)'},
                {'id':'apply_pipeline','text':'Apply suggested pipeline'}], 'page':page_dashboard},
            # Reordered: Patching before FMK (user focus on quick patch actions) 
            {'key':'patch','title':'Patching','color':'#AD1457','submenu':[
                {'id':None,'text':'— Core Patches —'},  # header (non-selectable)
                {'id':'boot_delay','text':'Boot Delay'},
                {'id':'serial','text':'Serial Shell'},
                {'id':'network','text':'Network'},
                {'id':None,'text':'— Advanced —'},
                {'id':'selective','text':'Selective Patch...'}], 'page':page_tools},
            {'key':'fmk','title':'FMK','color':'#2E7D32','submenu':[
                {'id':'extract','text':'Extract (FW Manager)'},
                {'id':'install','text':'Install/Update FMK'},
                {'id':'install_deps','text':'Install FMK Dependencies'},
                {'id':None,'text':'— Filesystems —'},
                {'id':'fs_squashfs','text':'Browse SquashFS'},
                {'id':'fs_cramfs','text':'Browse CramFS'},
                {'id':'fs_jffs2','text':'Browse JFFS2'},
                {'id':'fs_yaffs2','text':'Browse YAFFS2'}], 'page':page_tools},
            {'key':'tools','title':'Tools','color':'#F57C00','submenu':[
                {'id':'msq_dry','text':'Multi-Squash: Dry-run'},
                {'id':'msq_apply','text':'Multi-Squash: Apply'},
                {'id':'archive','text':'Archive Outputs'}], 'page':page_tools},
            {'key':'special','title':'Special','color':'#6A1B9A','submenu':[], 'page':page_special},
            {'key':'settings','title':'Settings','color':'#455A64','submenu':[], 'page':page_settings},
        ]
        # Icon mapping (emoji placeholders can be replaced with QIcons later)
        self.ACTION_ICONS = {
            ('dashboard','analyze'):'🔍',
            ('dashboard','apply_pipeline'):'⚙️',
            ('patch','boot_delay'):'⏱️',
            ('patch','serial'):'🖧',
            ('patch','network'):'🌐',
            ('patch','selective'):'🧩',
            ('fmk','extract'):'📦',
            ('fmk','install'):'⬇️',
            ('fmk','install_deps'):'🛠️',
            ('fmk','fs_squashfs'):'📂',
            ('fmk','fs_cramfs'):'📂',
            ('fmk','fs_jffs2'):'📂',
            ('fmk','fs_yaffs2'):'📂',
            ('tools','msq_dry'):'🧪',
            ('tools','msq_apply'):'✅',
            ('tools','archive'):'🗜️',
            ('tools','clean_vendor'):'🧹',
        }
        self._action_usage = {}
        self._menu_index_by_key = {}; self._menu_children = {}; self._main_menu_buttons = []
        for idx, item in enumerate(self.MENU_STRUCTURE):
            try:
                if self.pages.indexOf(item['page']) == -1: self.pages.addWidget(item['page'])
            except Exception: pass
            self._menu_index_by_key[item['key']] = idx
            self._menu_children[idx] = [(c['text'], (item['key'], c['id'])) for c in item.get('submenu', [])]
            btn = QPushButton(item['title']); btn.setObjectName('mainMenuButton'); btn.setCheckable(True)
            btn.setToolTip(item['title']+'\n'+item['key'])
            btn.setStyleSheet(f"QPushButton#mainMenuButton{{background:{item['color']};color:#fff;font-weight:bold;padding:10px; text-align:left;}} QPushButton#mainMenuButton:checked{{border:2px solid #fff;}}")
            btn.clicked.connect(lambda _, ix=idx: self._on_main_menu_clicked(ix))
            btn.setMinimumHeight(44)
            main_menu_layout.addWidget(btn); self._main_menu_buttons.append(btn)
        self.btn_open_fw_side = QPushButton('Open Firmware / เปิดไฟล์'); self.btn_open_fw_side.clicked.connect(self.select_firmware); self.btn_open_fw_side.setStyleSheet('QPushButton{background:#455A64;color:#fff;} QPushButton:hover{background:#546E7A;}'); main_menu_layout.addWidget(self.btn_open_fw_side); main_menu_layout.addStretch()
        if self._main_menu_buttons:
            try: self._main_menu_buttons[0].setChecked(True); self._populate_submenu(0); self.pages.setCurrentWidget(self.MENU_STRUCTURE[0]['page'])
            except Exception: pass
        self._register_actions()
        # Warn about missing handlers
        try:
            missing=[(g['key'],c['id']) for g in self.MENU_STRUCTURE for c in g.get('submenu',[]) if (g['key'],c['id']) not in self._action_handlers]
            if missing: self.log_bilingual('เตือน: มี action ไม่มี handler: '+str(missing), 'Warning: missing handlers '+str(missing))
        except Exception: pass
        self.log_bilingual(f'โหลดโครงสร้างเมนู {len(self._main_menu_buttons)} หมวด', f'Loaded {len(self._main_menu_buttons)} menu groups')

        # ---------------- Logs / Right Pane ----------------
        right_tabs = QTabWidget(); right_tabs.setDocumentMode(True)
        self.log_view_th = QTextEdit(); self.log_view_th.setReadOnly(True)
        self.log_view_en = QTextEdit(); self.log_view_en.setReadOnly(True)
        right_tabs.addTab(self.log_view_th,'บันทึก (TH)'); right_tabs.addTab(self.log_view_en,'Logs (EN)')
        self.btn_clear_logs = QPushButton('ล้างบันทึก')
        def _clear_logs():
            try: self.log_view_th.clear(); self.log_view_en.clear(); self.log('[SYSTEM] ล้างบันทึกแล้ว (Logs cleared)')
            except Exception: pass
        self.btn_clear_logs.clicked.connect(_clear_logs)

        # ---------------- Split Layout ----------------
        hsplit = QSplitter(Qt.Horizontal)
        left_widget = QWidget(); left_l = QVBoxLayout(left_widget); left_l.setContentsMargins(6,6,6,6); left_l.addWidget(self.main_menu_widget); left_l.addStretch(); hsplit.addWidget(left_widget)
        center_widget = QWidget(); center_l = QVBoxLayout(center_widget); center_l.setContentsMargins(6,6,6,6); center_l.addWidget(self.sub_menu_list); center_l.addWidget(self.pages); center_widget.setLayout(center_l); hsplit.addWidget(center_widget)
        right_widget = QWidget(); right_wl = QVBoxLayout(right_widget); right_wl.setContentsMargins(4,4,4,4); right_split = QSplitter(Qt.Vertical); self._right_split = right_split
        status_wrap = QWidget(); sw_l = QVBoxLayout(status_wrap); sw_l.setContentsMargins(0,0,0,0); sw_l.addWidget(self.status_panel); sw_l.addWidget(self.btn_clear_logs); sw_l.addStretch()
        logs_wrap = QWidget(); lw_l = QVBoxLayout(logs_wrap); lw_l.setContentsMargins(0,0,0,0); lw_l.addWidget(right_tabs)
        right_split.addWidget(status_wrap); right_split.addWidget(logs_wrap); right_split.setStretchFactor(0,0); right_split.setStretchFactor(1,1)
        right_wl.addWidget(right_split); right_widget.setLayout(right_wl); hsplit.addWidget(right_widget)
        try:
            from PySide6.QtCore import QTimer; QTimer.singleShot(50, lambda: right_split.setSizes([220,420]))
        except Exception: pass
        self.log_view = self.log_view_th
        main_container = QWidget(); main_layout = QVBoxLayout(main_container); main_layout.addWidget(hsplit); self.setCentralWidget(main_container)
        try:
            from PySide6.QtGui import QFont; app = QApplication.instance();
            if app: app.setFont(QFont('Segoe UI',11))
        except Exception: pass
        try:
            theme_flag = os.path.expanduser('~/.local/share/firmware_toolkit/theme'); theme_choice = 'dark'
            if os.path.exists(theme_flag): theme_choice = open(theme_flag,'r').read().strip() or 'dark'
            self.apply_theme(theme_choice)
        except Exception: pass
        # Ensure menu visible if future refactor empties it
        self._ensure_main_menu_visible()
    # (Vendor tool menu already registered in __init__; no extra call here)

    def apply_theme(self, theme_name: str):
        """Apply a simple light/dark stylesheet and persist choice."""
        try:
            dark_qss = '''
                QWidget{ background: #1f1f1f; color: #ededed; }
                QTreeWidget { background: #252525; }
                QTextEdit, QTabWidget, QStackedWidget { background: #181818; color: #eaeaea; }
                QPushButton { background: #2a82da; color: #fff; border-radius:4px; padding:6px; }
                QPushButton:pressed { background: #2266b0; }
                QLineEdit, QSpinBox, QComboBox { background: #2b2b2b; color: #fff; }
            '''
            light_qss = '''
                QWidget{ background: #f6f6f6; color: #111111; }
                QTreeWidget { background: #ffffff; }
                QTextEdit, QTabWidget, QStackedWidget { background: #ffffff; color: #111111; }
                QPushButton { background: #1976d2; color: #fff; border-radius:4px; padding:6px; }
                QPushButton:pressed { background: #0f5ca8; }
                QLineEdit, QSpinBox, QComboBox { background: #ffffff; color: #111; }
            '''
            app = QApplication.instance()
            if not app:
                return
            if theme_name == 'dark':
                app.setStyleSheet(dark_qss)
            else:
                app.setStyleSheet(light_qss)
            try:
                theme_flag = os.path.expanduser('~/.local/share/firmware_toolkit/theme')
                os.makedirs(os.path.dirname(theme_flag), exist_ok=True)
                with open(theme_flag,'w') as f: f.write(theme_name)
            except Exception:
                pass
        except Exception as e:
            self.log(f'[THEME] apply failed: {e}')

    # ---------------- Vendor Tools Integration ----------------
    def _register_vendor_tool_actions(self):
        """สแกน tools_bin และ tools_bin/bin แล้วเพิ่มเป็นเมนู Tools -> Vendor Tools
        ข้ามไฟล์ซอร์ส/ออบเจ็กต์ เหลือเฉพาะไฟล์ executable
        """
        try:
            menubar = self.menuBar()
            tools_menu = None
            for act in menubar.actions():
                if act.text() == 'Tools':
                    tools_menu = act.menu(); break
            if tools_menu is None:
                return
            from PySide6.QtWidgets import QMenu
            vendor_menu = None
            for act in tools_menu.actions():
                if act.menu() and act.text() == 'Vendor Tools':
                    vendor_menu = act.menu(); break
            if vendor_menu is None:
                vendor_menu = QMenu('Vendor Tools', self)
                tools_menu.addMenu(vendor_menu)
            here = os.path.dirname(__file__)
            roots = [os.path.join(here,'tools_bin'), os.path.join(here,'tools_bin','bin')]
            skip_ext = {'.c','.cc','.cpp','.h','.hpp','.o','.obj','.py','.pyc','.md','.txt','.ac','.am','.in','.log'}
            added = 0; seen=set()
            for root in roots:
                if not os.path.isdir(root): continue
                for fn in sorted(os.listdir(root)):
                    if fn in seen: continue
                    seen.add(fn)
                    fp = os.path.join(root, fn)
                    if not os.path.isfile(fp): continue
                    _, ext = os.path.splitext(fn)
                    if ext.lower() in skip_ext: continue
                    if not os.access(fp, os.X_OK): continue
                    act = QAction(fn, self)
                    act.triggered.connect(lambda _=False, p=fp: self._run_vendor_tool(p))
                    vendor_menu.addAction(act); added += 1
            if added:
                self.thread_log.emit(f'[TOOLS] เพิ่มเมนู Vendor Tools {added} รายการ')
            else:
                try: self.thread_log.emit('[TOOLS] ไม่พบเครื่องมือ vendor (ไม่มีไฟล์ executable)')
                except Exception: pass
        except Exception as e:
            try: self.thread_log.emit(f'[TOOLS] vendor menu error: {e}')
            except Exception: pass

    def _run_vendor_tool(self, path):
        try:
            runner = FMKRunner([path,'--help'])  # ใช้ --help เพื่อแสดงข้อมูล ไม่ทำลายข้อมูล
            name = os.path.basename(path)
            runner.log.connect(lambda m,n=name: self.thread_log.emit(f'[VENDOR:{n}] {m}'))
            runner.error.connect(lambda e,n=name: self.thread_log.emit(f'[VENDOR:{n}] ERROR {e}'))
            runner.finished.connect(lambda rc,n=name: self.thread_log.emit(f'[VENDOR:{n}] finished rc={rc}'))
            runner.start(); self._register_thread(runner)
        except Exception as e:
            try: self.thread_log.emit(f'[VENDOR] run error {path}: {e}')
            except Exception: pass

    # ---------------- Menu helper methods ----------------
    def _on_main_menu_clicked(self, index: int):
        """Handle main menu button clicks: check the clicked button and populate submenu."""
        try:
            for i, b in enumerate(self._main_menu_buttons):
                try:
                    b.setChecked(i == index)
                except Exception:
                    pass
            self._populate_submenu(index)
            # แสดงหน้าของกลุ่มเมนูเสมอ (ทำให้ Settings / Special ทำงานชัดเจน)
            try:
                page = self.MENU_STRUCTURE[index]['page']
                if page:
                    self.pages.setCurrentWidget(page)
                # อัพเดตสถานะ
                try:
                    title = self.MENU_STRUCTURE[index]['title']
                    self.status_label.setText(f"{title} | Ready")
                except Exception:
                    pass
            except Exception:
                pass
            # หากไม่มี submenu ให้เปลี่ยนสถานะ log
            if not self._menu_children.get(index):
                self.log_bilingual('เปิดหน้าหมวด: '+self.MENU_STRUCTURE[index]['title'], 'Opened menu page: '+self.MENU_STRUCTURE[index]['title'])
            # restore last submenu selection if exists
            if self.sub_menu_list.count() and index in self._last_sub_index:
                row = self._last_sub_index.get(index, 0)
                if 0 <= row < self.sub_menu_list.count():
                    try: self.sub_menu_list.setCurrentRow(row)
                    except Exception: pass
        except Exception as e:
            try: self.log(f'menu click error: {e}')
            except Exception: pass

    def _populate_submenu(self, main_index: int):
        """Populate the center sub-menu list for the given main menu index."""
        try:
            self.sub_menu_list.clear()
            children = self._menu_children.get(main_index, [])
            for label, action in children:
                # Header rows (non-selectable) when action id is None
                if isinstance(action, tuple) and action[1] is None:
                    it = QListWidgetItem(label)
                    # mark as header
                    it.setFlags(it.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                    it.setData(Qt.UserRole, None)
                    it.setForeground(Qt.gray)
                    font = it.font(); font.setBold(True); it.setFont(font)
                    self.sub_menu_list.addItem(it)
                    continue
                it = QListWidgetItem()
                icon_txt = ''
                if isinstance(action, tuple):
                    icon_txt = self.ACTION_ICONS.get(action, '')
                display = f"{icon_txt+'  ' if icon_txt else ''}{label}"
                it.setText(display)
                it.setData(Qt.UserRole, action)
                it.setToolTip(label)
                self.sub_menu_list.addItem(it)
            # จัดการสัญญาณ itemActivated ป้องกัน warning disconnect
            if not getattr(self, '_submenu_connected', False):
                try:
                    self.sub_menu_list.itemActivated.connect(self._on_submenu_activated)
                    self._submenu_connected = True
                except Exception:
                    pass
            # auto-select first submenu item (optional UX enhancement)
            if self.sub_menu_list.count() > 0:
                try:
                    self.sub_menu_list.setCurrentRow(0)
                except Exception:
                    pass
        except Exception as e:
            try: self.log(f'populate submenu error: {e}')
            except Exception: pass

    def _on_submenu_activated(self, item):
        """Dispatch submenu actions when a user activates an item."""
        try:
            data = item.data(Qt.UserRole)
            if isinstance(data, tuple) and len(data)==2:
                handler = self._action_handlers.get(data)
                # บันทึกตำแหน่ง submenu ล่าสุดของ group
                try:
                    main_index = self._current_main_index()
                    if main_index is not None:
                        self._last_sub_index[main_index] = self.sub_menu_list.currentRow()
                except Exception: pass
                if handler:
                    return self._invoke_action(data, handler)
                else:
                    self.log_bilingual(f'ไม่พบ handler สำหรับ {data}', f'No handler for {data}')
            elif isinstance(data, str) and data == 'open_fw':
                return self.select_firmware()
            elif isinstance(data, int):
                return self.pages.setCurrentIndex(data)
        except Exception as e:
            try: self.log(f'submenu activation error: {e}')
            except Exception: pass

    def _register_actions(self):
        """Central registry for submenu action handlers."""
        try:
            self._action_handlers = {
                ('dashboard','analyze'): lambda: self.start_manual_analysis(),
                ('dashboard','apply_pipeline'): lambda: self.apply_suggested_pipeline(),
                ('fmk','extract'): lambda: self.fmk_extract_wrapper(),
                ('fmk','install'): lambda: self.fmk_build_wrapper(),
                ('fmk','install_deps'): lambda: self.install_fmk_deps(),
                ('fmk','fs_squashfs'): lambda: self._open_fs_browser('squashfs'),
                ('fmk','fs_cramfs'): lambda: self._open_fs_browser('cramfs'),
                ('fmk','fs_jffs2'): lambda: self._open_fs_browser('jffs2'),
                ('fmk','fs_yaffs2'): lambda: self._open_fs_browser('yaffs2'),
                ('patch','boot_delay'): lambda: self._run_quick_patch('boot_delay'),
                ('patch','serial'): lambda: self._run_quick_patch('serial'),
                ('patch','network'): lambda: self._run_quick_patch('network'),
                ('patch','selective'): lambda: self.open_selective_patch_dialog(),
                ('tools','msq_dry'): lambda: self.multi_squash_dryrun(),
                ('tools','msq_apply'): lambda: self.multi_squash_apply(),
                ('tools','archive'): lambda: self.archive_outputs(),
            }
        except Exception as e:
            try: self.log(f'action registry error: {e}')
            except Exception: pass

    def _current_main_index(self):
        try:
            for i,b in enumerate(self._main_menu_buttons):
                if b.isChecked(): return i
        except Exception: pass
        return None

    def _invoke_action(self, key_tuple, handler):
        """Wrap action execution with status updates/logging."""
        try:
            self.status_label.setText(f'Running: {key_tuple}')
        except Exception: pass
        try:
            res = handler()
            # usage stats
            try: self._action_usage[key_tuple] = self._action_usage.get(key_tuple,0)+1
            except Exception: pass
            # dynamic menu reorder if enabled
            self._maybe_reorder_menu()
            try:
                self.status_label.setText(f'Done: {key_tuple}')
            except Exception: pass
            # reset to Ready after short delay (lazy timer if available)
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(1500, lambda: self.status_label.setText('Ready'))
            except Exception: pass
            return res
        except Exception as e:
            try:
                self.status_label.setText(f'Error: {key_tuple}')
            except Exception: pass
            self.log(f'[ACTION] error {key_tuple}: {e}')
            raise

    def _scan_serial_candidates(self):
        """Scan current firmware (light heuristic) + host for plausible serial console device names.
        Returns list of text entries (e.g. 'ttyS0 (in firmware)', 'ttyAMA0 (firmware+host)')."""
        result = []
        # firmware heuristic
        try:
            fw = getattr(self, 'fw_path', None)
            if fw and os.path.exists(fw):
                firmware_ports = ['ttyS0','ttyS1','ttyAMA0','ttyUSB0']
                for p in firmware_ports:
                    if p not in result:
                        result.append(f"{p} (firmware guess)")
        except Exception:
            pass
        # host ports
        try:
            from glob import glob
            host_patterns = ['/dev/ttyUSB*','/dev/ttyACM*','/dev/ttyS*','/dev/ttyAMA*']
            host_found = []
            for pat in host_patterns:
                for path in glob(pat):
                    base = os.path.basename(path)
                    tag = f"{base} (host)"
                    if tag not in result:
                        result.append(tag)
                        host_found.append(base)
        except Exception:
            pass
        # de-duplicate on base
        seen_base = set(); final=[]
        for label in result:
            base = label.split()[0]
            if base in seen_base: continue
            seen_base.add(base); final.append(label)
        if not final: final=['ttyS0']
        return final

    # ---------------- Filesystem Browsers ----------------
    def _open_fs_browser(self, fs_type: str):
        """Open filesystem editor for specified fs_type using first matching detected part.
        Steps:
          1. Ensure firmware loaded and parts detected (self.parts or re-scan via multisquash.detect_squashfs for squashfs only fallback)
          2. Pick first part whose 'fs' matches fs_type
          3. Extract (if not cached) to temp dir using extract_rootfs
          4. Open RootFSEditDialog (re-using existing UI)
        """
        try:
            fw = getattr(self, 'fw_path', None)
            if not fw or not os.path.exists(fw):
                self.log_bilingual('กรุณาเปิดไฟล์เฟิร์มแวร์ก่อน', 'Please open a firmware first')
                return
            # ensure parts list
            parts = getattr(self, 'rootfs_parts', None)
            if not parts:
                # attempt simple detection: reuse earlier logic if available
                parts = []
                try:
                    size = os.path.getsize(fw)
                    # naive scan for fixed-size blocks where magic matches
                    with open(fw,'rb') as f:
                        data = f.read()
                    block_size = 0x20000  # 128KB typical in log examples
                    for off in range(0, len(data), block_size):
                        if off+ block_size > len(data): break
                        head = data[off:off+16]
                        # quick magics
                        if head.startswith(b'hsqs') or head.startswith(b'sqsh'):
                            parts.append({'offset':off,'size':block_size,'fs':'squashfs'})
                        elif head[:4] in (b'\x45\x3d\xcd\x28', b'\x28\xcd\x3d\x45'):
                            parts.append({'offset':off,'size':block_size,'fs':'cramfs'})
                        elif head[:2] == b'\x85\x19':
                            parts.append({'offset':off,'size':block_size,'fs':'jffs2'})
                        elif b'yaffs' in head.lower():
                            parts.append({'offset':off,'size':block_size,'fs':'yaffs2'})
                except Exception:
                    pass
                self.rootfs_parts = parts
            # choose part
            target = None
            for p in parts or []:
                if p.get('fs') == fs_type:
                    target = p; break
            if not target:
                self.log_bilingual(f'ไม่พบพาร์ท {fs_type}', f'No {fs_type} part found')
                return
            # cache check
            cache_attr = f'edit_cache_{fs_type}'
            if getattr(self, cache_attr, None):
                extract_dir = getattr(self, cache_attr)
            else:
                import tempfile
                tmpdir = tempfile.mkdtemp(prefix=f'fsbrowse_{fs_type}_')
                rootfs_bin = os.path.join(tmpdir,'rootfs.bin')
                with open(fw,'rb') as f:
                    f.seek(target['offset']); blob = f.read(target['size'])
                with open(rootfs_bin,'wb') as f: f.write(blob)
                extract_dir = os.path.join(tmpdir,'extract'); os.makedirs(extract_dir, exist_ok=True)
                from app import extract_rootfs
                ok, err = extract_rootfs(fs_type, rootfs_bin, extract_dir, self.log)
                if not ok and fs_type != 'auto':
                    self.log(f'[FS_BROWSER] retry auto after {fs_type} fail: {err}')
                    ok, err = extract_rootfs('auto', rootfs_bin, extract_dir, self.log)
                    if ok:
                        fs_type = 'auto'
                if not ok:
                    self.log_bilingual(f'แตก {fs_type} ล้มเหลว: {err}', f'Extract {fs_type} failed: {err}')
                    return
                setattr(self, cache_attr, extract_dir)
                self.log_bilingual(f'แตก {fs_type} -> {extract_dir}', f'Extracted {fs_type} -> {extract_dir}')
            # open dialog
            try:
                from dialogs.rootfs_editor import RootFSEditDialog
                part_info = {'fs':fs_type,'offset':target['offset'],'size':target['size']}
                dlg = RootFSEditDialog(self, extract_dir, part_info, fw, self.output_dir)
                dlg.exec()
            except Exception as e:
                self.log_bilingual(f'เปิด editor ไม่สำเร็จ: {e}', f'Open editor failed: {e}')
        except Exception as e:
            try: self.log(f'[FS] open {fs_type} error: {e}')
            except Exception: pass

    # ---------------- Responsive behaviour ----------------
    def resizeEvent(self, event):  # type: ignore
        try:
            self._update_responsive()
        except Exception:
            pass
        return super().resizeEvent(event)

    def _update_responsive(self):
        """Compact main menu when window narrow for better responsiveness."""
        if not getattr(self, '_main_menu_buttons', None):
            return
        w = self.width()
        threshold = 1020
        if w < threshold and not getattr(self, '_compact_mode', False):
            self._compact_mode = True
            # store originals
            self._orig_titles = [b.text() for b in self._main_menu_buttons]
            for b in self._main_menu_buttons:
                t = b.text()
                # take first letter + maybe emoji from first action icon
                b.setText(t[:1])
                b.setToolTip(t)
        elif w >= threshold and getattr(self, '_compact_mode', False):
            # restore
            for b, title in zip(self._main_menu_buttons, getattr(self, '_orig_titles', [])):
                b.setText(title)
            self._compact_mode = False
        # adjust submenu header style
        try:
            for i in range(self.sub_menu_list.count()):
                it = self.sub_menu_list.item(i)
                if it and not it.data(Qt.UserRole):
                    font = it.font(); font.setPointSize(10 if w < threshold else 11); it.setFont(font)
        except Exception:
            pass

    def _maybe_reorder_menu(self):
        """Reorder main menu buttons by usage if enabled (keeps relative new order stable)."""
        if not getattr(self,'cfg_dynamic_menu', False):
            return
        try:
            usage_scores = {}
            for (grp, act), count in getattr(self,'_action_usage',{}).items():
                usage_scores[grp] = usage_scores.get(grp,0)+count
            if not usage_scores:
                return
            # sort menu structure copy
            ordered = sorted(self.MENU_STRUCTURE, key=lambda g: -usage_scores.get(g['key'],0))
            if [g['key'] for g in ordered] == [g['key'] for g in self.MENU_STRUCTURE]:
                return  # no change
            self.MENU_STRUCTURE = ordered
            # rebuild buttons
            lay = self.main_menu_widget.layout()
            while lay.count()>0:
                item = lay.takeAt(0)
                w = item.widget()
                if w: w.deleteLater()
            self._main_menu_buttons=[]
            for idx,item in enumerate(self.MENU_STRUCTURE):
                btn = QPushButton(item['title']); btn.setObjectName('mainMenuButton'); btn.setCheckable(True)
                btn.setStyleSheet(f"QPushButton#mainMenuButton{{background:{item['color']};color:#fff;font-weight:bold;padding:10px; text-align:left;}} QPushButton#mainMenuButton:checked{{border:2px solid #fff;}}")
                btn.clicked.connect(lambda _, ix=idx: self._on_main_menu_clicked(ix))
                lay.addWidget(btn); self._main_menu_buttons.append(btn)
            lay.addStretch()
            if self._main_menu_buttons:
                self._main_menu_buttons[0].setChecked(True)
                self._populate_submenu(0)
            self.log_bilingual('จัดลำดับเมนูใหม่ตามการใช้งาน', 'Reordered main menu by usage')
        except Exception as e:
            self.log(f'[DYN] reorder failed: {e}')

    def select_firmware(self):
        res = QFileDialog.getOpenFileName(self, _('btn_open_fw'))
        # QFileDialog.getOpenFileName may return a tuple (path, filter)
        path = res[0] if isinstance(res, (list, tuple)) else res
        if path:
            self.fw_path = path
            self.log(f'Selected {path}')
            # Manual mode: no automatic analysis/patching
            self.log('[INFO] Manual mode: click "Analyze Firmware" to generate suggestions.')

    def start_manual_analysis(self):
        if not getattr(self, 'fw_path', None):
            QMessageBox.information(self, 'Analyze', 'Select a firmware first')
            return
        if getattr(self, '_analysis_running', False):
            self.log('[AI] Analysis already running')
            return
        self._analysis_running = True
        self.log('[AI] Manual analysis started...')
        def _run():
            try:
                self.ai_orchestrator(manual=True)
            finally:
                self._analysis_running = False
        threading.Thread(target=_run, daemon=True).start()

    def log(self, text):
        try:
            msg = str(text)
            if hasattr(self, 'log_view_th') and hasattr(self, 'log_view_en'):
                # ถ้าไม่มีตัวอักษรไทย ให้พยายามแปล
                if not any('\u0e00' <= ch <= '\u0e7f' for ch in msg):
                    th = self._auto_translate_en(msg)
                    if th:
                        self.log_view_th.append(f"{th} ({msg})")
                        self.log_view_en.append(msg)
                    else:
                        self.log_view_th.append(msg)
                        self.log_view_en.append(msg)
                else:
                    # มีไทยแล้ว: แยก EN ในวงเล็บ ถ้ามี
                    en_part = None
                    if '(' in msg and msg.endswith(')'):
                        try:
                            inner = msg[msg.rfind('(')+1:-1]
                            if inner and all(ord(c) < 128 for c in inner):
                                en_part = inner
                        except Exception:
                            pass
                    self.log_view_th.append(msg)
                    self.log_view_en.append(en_part if en_part else msg)
        except Exception:
            try:
                print(text)
            except Exception:
                pass

    def _auto_translate_en(self, en: str) -> str:
        """แปลวลีสถานะทั่วไป EN -> TH (อย่างง่าย) ถ้าไม่รู้จักคืนค่าว่าง"""
        try:
            base = en.strip()
            # ตัดข้อมูลตัวแปร เช่น ชื่อไฟล์ หลัง ':' หรือ ' -> '
            patterns = [
                ('Pipeline cancelled by user', 'ยกเลิกกระบวนการตามผู้ใช้'),
                ('Pipeline finished', 'กระบวนการเสร็จสิ้น'),
                ('Pipeline applied', 'ใช้แพตช์ตามที่เสนอแล้ว'),
                ('Apply suggested pipeline cancelled by user', 'ยกเลิกการใช้แพตช์ที่เสนอ'),
                ('No suggestions chosen', 'ไม่ได้เลือกข้อเสนอใด'),
                ('No active apply worker to cancel', 'ไม่มีงานกำลังทำให้ยกเลิก'),
                ('Cancel requested', 'ร้องขอยกเลิกแล้ว'),
                ('Cancel aborted by user', 'ยกเลิกการยกเลิกโดยผู้ใช้'),
                ('Worker cannot be cancelled', 'งานนี้ไม่สามารถยกเลิกได้'),
                ('Manual analysis started', 'เริ่มการวิเคราะห์แบบแมนนวล'),
                ('Analysis already running', 'กำลังวิเคราะห์อยู่แล้ว'),
                ('Orchestrator started', 'เริ่มตัวควบคุมงาน'),
                ('Orchestrator finished', 'ตัวควบคุมงานเสร็จสิ้น'),
                ('no firmware selected', 'ยังไม่ได้เลือกเฟิร์มแวร์'),
                ('running deep scan', 'กำลังสแกนเชิงลึก'),
                ('deep scan error', 'สแกนเชิงลึกผิดพลาด'),
                ('rootfs/uboot detection error', 'ตรวจหา rootfs/u-boot ผิดพลาด'),
                ('compose summary failed', 'สร้างสรุปล้มเหลว'),
                ('apply pipeline start failed', 'เริ่มใช้ pipeline ล้มเหลว'),
                ('Cancel error', 'ยกเลิกผิดพลาด'),
                ('Install FMK Dependencies', 'ติดตั้ง dependencies ของ FMK'),
                ('Auto-install enabled by user', 'เปิดใช้ติดตั้งอัตโนมัติ'),
                ('Auto-install disabled by user', 'ปิดใช้ติดตั้งอัตโนมัติ'),
                ('apply failed', 'การใช้ล้มเหลว'),
                ('apply succeeded', 'การใช้สำเร็จ'),
            ]
            lower = base.lower()
            for key, th in patterns:
                if key.lower() in lower:
                    return th
            return ''
        except Exception:
            return ''

    def log_bilingual(self, th_text: str, en_text: str):
        """บันทึกสองภาษา: TH (EN) -> TH tab และ EN tab แยกชัด"""
        try:
            if hasattr(self, 'log_view_th'): self.log_view_th.append(f"{th_text} ({en_text})")
            if hasattr(self, 'log_view_en'): self.log_view_en.append(en_text)
        except Exception:
            pass

    def _ensure_main_menu_visible(self):
        try:
            if getattr(self, '_main_menu_buttons', None) and self._main_menu_buttons:
                return
            # Rebuild if empty
            groups = getattr(self, '_groups_data', [])
            if not groups:
                return
            layout = None
            try:
                layout = self.main_menu_widget.layout()
            except Exception:
                pass
            if layout is None:
                from PySide6.QtWidgets import QVBoxLayout
                layout = QVBoxLayout(self.main_menu_widget)
            self._main_menu_buttons = []
            for i,(name, idx, children) in enumerate(groups):
                b = QPushButton(name)
                b.setObjectName('mainMenuButton')
                col = self._menu_colors.get(i)
                if col:
                    b.setStyleSheet(
                        f"QPushButton#mainMenuButton{{background:{col};color:#fff;font-weight:bold;}} "
                        f"QPushButton#mainMenuButton:checked{{border:2px solid #fff;}}"
                    )
                b.setCheckable(True)
                b.clicked.connect(lambda _, ix=i: self._on_main_menu_clicked(ix))
                layout.addWidget(b)
                self._main_menu_buttons.append(b)
                self._menu_children[i] = children
            layout.addStretch()
            if self._main_menu_buttons:
                self._main_menu_buttons[0].setChecked(True)
                self._populate_submenu(0)
            self.log_bilingual('รีเฟรชเมนูหลักสำเร็จ', 'Rebuilt main menu successfully')
        except Exception as e:
            try:
                self.log_bilingual(f'รีเฟรชเมนูล้มเหลว: {e}', f'Failed to rebuild menu: {e}')
            except Exception:
                pass

    def fmk_extract_wrapper(self):
        # Call fw-manager.sh extract <firmware> if available; stream logs into UI
        if not getattr(self, 'fw_path', None):
            QMessageBox.information(self, 'FMK', 'Please select a firmware file first')
            return
        project_root = os.path.abspath(os.path.dirname(__file__))
        fw_mgr = os.path.join(project_root, 'fw-manager.sh')
        if not os.path.exists(fw_mgr):
            fw_mgr = shutil.which('fw-manager.sh') or None
        if not fw_mgr:
            self.log('fw-manager.sh not found; run ./setup.sh or see README to install FMK')
            QMessageBox.information(self, 'FMK', 'fw-manager.sh not found in project; please run setup.sh to install FMK or place fw-manager.sh in the project root')
            return
        cmd = [fw_mgr, 'extract', self.fw_path]
        runner = FMKRunner(cmd, cwd=project_root)
        runner.log.connect(lambda m: self.thread_log.emit(m))
        runner.error.connect(lambda e: self.thread_log.emit(f'FMK runner error: {e}'))
        runner.finished.connect(lambda rc: self.thread_log.emit(f'FMK extract finished (rc={rc})'))
        runner.start(); self._register_thread(runner)

    def fmk_build_wrapper(self):
        # Run fw-manager.sh install/update to ensure FMK is present
        project_root = os.path.abspath(os.path.dirname(__file__))
        fw_mgr = os.path.join(project_root, 'fw-manager.sh')
        if not os.path.exists(fw_mgr):
            fw_mgr = shutil.which('fw-manager.sh') or None
        if not fw_mgr:
            self.log('fw-manager.sh not found; cannot install/update FMK')
            QMessageBox.information(self, 'FMK', 'fw-manager.sh not found; run ./setup.sh to provision FMK')
            return
        cmd = [fw_mgr, 'install']
        runner = FMKRunner(cmd, cwd=project_root)
        runner.log.connect(lambda m: self.thread_log.emit(m))
        runner.error.connect(lambda e: self.thread_log.emit(f'FMK runner error: {e}'))
        runner.finished.connect(lambda rc: self.thread_log.emit(f'FMK install finished (rc={rc})'))
        runner.start(); self._register_thread(runner)

    def _on_sidebar_changed(self, cur_item):
        try:
            if cur_item is None:
                return
            data = cur_item.data(0, Qt.UserRole)
            # data may be an int (page index) or a tuple (page_index, action)
            if isinstance(data, tuple) and len(data) == 2:
                page_idx, action = data
                if isinstance(page_idx, int):
                    self.pages.setCurrentIndex(page_idx)
                # dispatch actions
                if action == 'open_fw':
                    self.select_firmware()
                elif action == 'msq_dry':
                    self.multi_squash_dryrun()
                elif action == 'msq_apply':
                    self.multi_squash_apply()
            elif isinstance(data, int):
                self.pages.setCurrentIndex(data)
        except Exception as e:
            self.log(f'sidebar change error: {e}')

    def _run_quick_patch(self, action: str):
        """Run quick patch actions (dashboard shortcuts) using core.patch helpers.

        action: 'boot_delay' | 'serial' | 'network' | 'all'
        """
        if not getattr(self, 'fw_path', None):
            self.log('No firmware selected for patching')
            QMessageBox.information(self, 'Info', 'Please select a firmware file first')
            return
        fw = self.fw_path
        os.makedirs(self.output_dir, exist_ok=True)

        if action == 'boot_delay':
            # Step 1: ask new value
            val, ok = QInputDialog.getInt(self, 'Boot Delay', 'New boot delay (seconds):', 3, 0, 600, 1)
            if not ok:
                self.log('Boot delay patch cancelled')
                return
            # Step 2: gather env candidates (v1+v2) for optional env-level patch
            env_candidates = self._collect_env_candidates()
            chosen_env = None
            if env_candidates:
                chosen_env = self._select_env_block_dialog(env_candidates)
            # Step 3: decide patch strategy
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_bootdelay.bin')
            if chosen_env:
                # patch inside selected environment block (preferred)
                try:
                    off = chosen_env['offset']; size = chosen_env['size']
                    okc, msg = patch_uboot_env_vars(fw, outp, off, size, {'bootdelay': val}, lambda m: self.thread_log.emit(m))
                    if okc:
                        self.log(f'[UBOOT] bootdelay -> {val} in env @0x{off:X} size=0x{size:X} -> {outp}')
                        return
                    else:
                        self.log(f'[UBOOT] env patch failed ({msg}), fallback raw method')
                except Exception as e:
                    self.log(f'[UBOOT] env patch exception: {e}; falling back')
            # Fallback: generic core patch (may patch raw byte or best env automatically)
            okc, msg = core_patch_boot_delay(fw, None, val, outp, lambda m: self.thread_log.emit(m))
            if okc:
                self.log(f'Boot delay patched -> {outp}')
            else:
                self.log(f'Boot delay patch failed: {msg}')

        elif action == 'serial':
            # Ask user to pick tty port (AI-assisted detection of candidates)
            candidates = self._scan_serial_candidates()
            forced = None
            if candidates:
                try:
                    item, ok = QInputDialog.getItem(self, 'Select Serial Port', 'เลือกพอร์ตอนุกรม / Serial port:', candidates, 0, False)
                    if ok and item:
                        forced = item.split()[0]
                except Exception as e:
                    self.log(f'[SERIAL] port pick cancelled/failed: {e}')
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_serial.bin')
            okc, msg = core_patch_rootfs_shell_serial(fw, None, outp, lambda m: self.thread_log.emit(m), forced_port=forced)
            if okc:
                self.log(f'Serial patch -> {outp}')
            else:
                self.log(f'Serial patch failed: {msg}')

        elif action == 'network':
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_network.bin')
            okc, msg = core_patch_rootfs_network(fw, None, outp, lambda m: self.thread_log.emit(m))
            if okc:
                self.log(f'Network patch -> {outp}')
            else:
                self.log(f'Network patch failed: {msg}')

        elif action == 'all':
            # run serial + network; do not change passwords here
            self._run_quick_patch('serial')
            self._run_quick_patch('network')
            QMessageBox.information(self, 'Info', 'Applied serial and network patches (files in output/)')
        else:
            self.log(f'Unknown quick patch action: {action}')

    # --- U-Boot env selection helpers ---
    def _collect_env_candidates(self):
        """Return combined list of environment block candidates (v1 + v2) with de-duplication.
        Honors the 'keep CRC mismatch' toggle when present.
        """
        try:
            keep_mismatch = getattr(self, 'cfg_keep_crc_mismatch', True)
            v1 = scan_uboot_env(self.fw_path, deep=True) if getattr(self, 'fw_path', None) else []
            v2 = scan_uboot_env_v2(self.fw_path, deep=True, keep_crc_mismatch=keep_mismatch) if getattr(self, 'fw_path', None) else []
            by_off = {}
            for e in (v1 + v2):
                if not e: continue
                off = e.get('offset'); size = e.get('size')
                if off is None or size is None: continue
                key = (off, size)
                # choose higher score or prefer valid CRC
                existing = by_off.get(key)
                if (existing is None or (not existing.get('valid') and e.get('valid')) or (e.get('score',0) > existing.get('score',0))):
                    by_off[key] = e
            out = list(by_off.values())
            out.sort(key=lambda r: (- (1 if r.get('valid') else 0), -r.get('score',0), r.get('offset')))
            return out
        except Exception as e:
            self.log(f'[UBOOT] collect env candidates error: {e}')
            return []

    def _select_env_block_dialog(self, candidates):
        """Show a dialog letting user choose an env block or cancel.
        Returns chosen candidate dict or None.
        """
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QDialogButtonBox
            dlg = QDialog(self)
            dlg.setWindowTitle('Select U-Boot Environment Block')
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel('เลือกบล็อค environment ที่จะ patch bootdelay:\nSelect environment block to patch bootdelay:'))
            lst = QListWidget(); lst.setSelectionMode(QListWidget.SingleSelection)
            for c in candidates:
                off = c.get('offset'); size = c.get('size'); valid = c.get('valid'); bd = c.get('bootdelay')
                crc = c.get('crc'); calc = c.get('crc_calc')
                txt = f"off=0x{off:X} size=0x{size:X} bootdelay={bd or '-'} {'VALID' if valid else 'BADCRC'} score={c.get('score',0):.1f} ({crc}->{calc})"
                it = QListWidgetItem(txt)
                it.setData(Qt.UserRole, c)
                # subtle coloring for invalid CRC
                if not valid:
                    it.setForeground(Qt.gray)
                lst.addItem(it)
            if lst.count():
                lst.setCurrentRow(0)
            layout.addWidget(lst)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            layout.addWidget(bb)
            bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
            if dlg.exec() == QDialog.Accepted and lst.currentItem():
                return lst.currentItem().data(Qt.UserRole)
            return None
        except Exception as e:
            self.log(f'[UBOOT] env select dialog error: {e}')
            return None

    def multi_squash_dryrun(self):
        if not self.fw_path:
            self.log('No firmware selected')
            return
        self.log('Starting multi-squash dry-run...')
        try:
            parts = multisquash.detect_squashfs(self.fw_path)
            self.log(f'detected {len(parts)} parts')
            for i,p in enumerate(parts):
                self.log(f'  part[{i}] offset={hex(p.offset)} size={p.size} desc="{p.desc[:120]}"')
        except Exception as e:
            self.log(f'Error: {e}')

    def multi_squash_apply(self):
        if not self.fw_path:
            self.log('No firmware selected')
            return
        allow_destructive = bool(self.msq_allow_destructive.isChecked())
        fw = self.fw_path
        out_dir = self.output_dir
        self.log(f'Running multi-squash apply on {fw} -> {out_dir} (destructive={allow_destructive})')
        # start worker in background and ensure signals post to main thread via thread_log
        worker = MultiSquashWorker(fw, out_dir, allow_destructive)
        worker.log.connect(lambda m: self.thread_log.emit(m))
        worker.error.connect(lambda e: self.thread_log.emit(f'Pipeline error: {e}'))
        worker.finished_ok.connect(self._on_multisquash_finished)
        worker.start()
        self._register_thread(worker)

    def _on_multisquash_finished(self, out_fw_path: str):
        """Slot: run post-processing (checksums, gzip, signature, diffs, metadata) in the main thread."""
        try:
            orig_sha = sha256sum(self.fw_path)
            patched_sha = sha256sum(out_fw_path)
            sums_path = os.path.join(self.output_dir, 'SHA256SUMS')
            with open(sums_path, 'w') as sf:
                sf.write(f"{orig_sha}  {os.path.basename(self.fw_path)}\n")
                sf.write(f"{patched_sha}  {os.path.basename(out_fw_path)}\n")
            self.log(f'Wrote checksums: {sums_path}')
        except Exception as e:
            self.log(f'Checksum generation failed: {e}')

        try:
            gz_path = out_fw_path + '.gz'
            with open(out_fw_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            self.log(f'Created gzip backup: {gz_path}')
        except Exception as e:
            self.log(f'Gzip backup failed: {e}')

        try:
            gpg = shutil.which('gpg')
            sums_path = os.path.join(self.output_dir, 'SHA256SUMS')
            if gpg and os.path.exists(sums_path):
                sig_out = sums_path + '.sig'
                p = subprocess.run([gpg, '--batch', '--yes', '--output', sig_out, '--sign', sums_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if p.returncode == 0:
                    self.log(f'Created GPG signature: {sig_out}')
                else:
                    self.log(f'GPG sign failed: {p.stderr.strip()}')
            else:
                self.log('gpg not found or SHA256SUMS missing; skipping signature')
        except Exception as e:
            self.log(f'GPG signing error: {e}')

        try:
            diff_path = os.path.join(self.output_dir, 'binary_diff.txt')
            try:
                hd = generate_hexdiff(self.fw_path, out_fw_path)
                with open(diff_path, 'w') as df:
                    df.write(hd)
                self.log(f'Wrote hexdiff: {diff_path}')
            except Exception:
                max_ranges = 2000
                ranges_found = 0
                with open(self.fw_path, 'rb') as a, open(out_fw_path, 'rb') as b, open(diff_path, 'w') as df:
                    ai = a.read()
                    bi = b.read()
                    L = min(len(ai), len(bi))
                    i = 0
                    while i < L and ranges_found < max_ranges:
                        if ai[i] != bi[i]:
                            j = i
                            while j < L and ai[j] != bi[j] and (j - i) < 1024:
                                j += 1
                            df.write(f'Range {i}-{j-1} (len {j-i})\n')
                            df.write('orig: ' + ai[i:i+64].hex() + '\n')
                            df.write('patt: ' + bi[i:i+64].hex() + '\n\n')
                            ranges_found += 1
                            i = j
                        else:
                            i += 1
                self.log(f'Wrote fallback binary diff: {diff_path} (ranges={ranges_found})')
        except Exception as e:
            self.log(f'Binary diff failed: {e}')

        try:
            meta = {
                'original': os.path.basename(self.fw_path),
                'patched': os.path.basename(out_fw_path),
                'timestamp': datetime.datetime.now(datetime.UTC).isoformat(),
                'parts': None,
                'orig_sha256': orig_sha if 'orig_sha' in locals() else None,
                'patched_sha256': patched_sha if 'patched_sha' in locals() else None,
            }
            meta_path = os.path.join(self.output_dir, os.path.basename(out_fw_path) + '.meta.json')
            with open(meta_path, 'w') as mf:
                json.dump(meta, mf, indent=2)
            self.log(f'Wrote metadata: {meta_path}')
        except Exception as e:
            self.log(f'Metadata write failed: {e}')

        self.log('Multi-squash apply completed')

    # --- Convenience wrappers for automated test runner (tools/auto_run_on_file.py) ---
    def check_external_tools(self):
        # quick probe for required external binaries and log findings
        tools = ['unsquashfs', 'mksquashfs', 'binwalk', 'jefferson', 'gpg']
        for t in tools:
            p = shutil.which(t)
            try:
                # prefer emitting via thread-safe signal so this can be called from background threads
                self.thread_log.emit(f'[TOOLS] {t}: {p or "NOT FOUND"}')
            except Exception:
                # fallback to direct log if signal is not available
                try: self.log(f'[TOOLS] {t}: {p or "NOT FOUND"}')
                except Exception: pass

    def auto_detect_rootfs(self):
        try:
            parts = multisquash.detect_squashfs(self.fw_path) if self.fw_path else []
            try:
                self.thread_log.emit(f'[AUTO] detect_squashfs -> {len(parts)} parts')
            except Exception:
                self.log(f'[AUTO] detect_squashfs -> {len(parts)} parts')
        except Exception as e:
            try:
                self.thread_log.emit(f'[AUTO] detect_squashfs error: {e}')
            except Exception:
                self.log(f'[AUTO] detect_squashfs error: {e}')

    def show_fw_info(self):
        if not getattr(self, 'fw_path', None):
            self.log('[INFO] no firmware selected')
            return
        try:
            sz = os.path.getsize(self.fw_path)
            self.log(f'[INFO] firmware {self.fw_path} size={sz}')
        except Exception as e:
            self.log(f'[INFO] show_fw_info error: {e}')

    def ai_analyze_all(self):
        # placeholder: run lightweight analysis (scan rootfs partitions)
        try:
            parts = multisquash.detect_squashfs(self.fw_path) if self.fw_path else []
            for i,p in enumerate(parts):
                self.log(f'[AI] rootfs#{i} at {hex(p.offset)} size={p.size}')
        except Exception as e:
            self.log(f'[AI] analyze error: {e}')

    def ai_orchestrator(self, manual: bool=False):
        """Analysis orchestrator (manual mode, no auto patching)."""
        try:
            self.thread_log.emit('[AI] Orchestrator started')
            if not getattr(self, 'fw_path', None):
                self.thread_log.emit('[AI] no firmware selected')
                return

            # 1) basic tool checks
            try:
                # check_external_tools logs via self.log which is safe when called from main thread
                # but here we're in background thread so call thread_log.emit where needed
                self.check_external_tools()
            except Exception as e:
                self.thread_log.emit(f'[AI] check_external_tools error: {e}')

            # 2) deep scan
            try:
                self.thread_log.emit('[AI] running deep scan...')
                self.run_deep_scan()
            except Exception as e:
                self.thread_log.emit(f'[AI] deep scan error: {e}')

            # 3) detect rootfs parts and u-boot env
            try:
                self.auto_detect_rootfs()
                self.open_uboot_env_editor()
            except Exception as e:
                self.thread_log.emit(f'[AI] rootfs/uboot detection error: {e}')

            # 4) skip auto patch probing in manual analysis mode

            # 5) collect detailed findings and write ai.summary
            try:
                findings = {}
                findings['firmware'] = os.path.basename(self.fw_path)
                findings['timestamp'] = datetime.datetime.now(datetime.UTC).isoformat()
                # rootfs parts
                try:
                    parts = multisquash.detect_squashfs(self.fw_path)
                    findings['parts'] = [{'offset': p.offset, 'size': p.size} for p in parts] if parts else []
                except Exception:
                    findings['parts'] = []
                # u-boot env analysis
                try:
                    env_blocks = scan_uboot_env(self.fw_path, deep=True)
                    findings['uboot_envs'] = env_blocks
                    findings['uboot_findings'] = analyze_bootloader_env(env_blocks)
                except Exception:
                    findings['uboot_envs'] = []
                    findings['uboot_findings'] = ['scan error']
                # bootdelay raw byte if present
                try:
                    bd = read_boot_delay_byte(self.fw_path)
                    findings['bootdelay_byte'] = bd
                except Exception:
                    findings['bootdelay_byte'] = None
                # suggested patches
                suggestions = []
                if findings.get('parts'):
                    suggestions.append({'action': 'patch_serial', 'reason': 'rootfs parts detected'})
                    suggestions.append({'action': 'patch_network', 'reason': 'rootfs parts detected'})
                else:
                    suggestions.append({'action': 'patch_serial', 'reason': 'no rootfs parts; binwalk fallback may be required'})
                if findings.get('bootdelay_byte') is not None:
                    suggestions.insert(0, {'action': 'patch_boot_delay', 'reason': 'bootdelay byte found at 0x100'})
                findings['suggested_patches'] = suggestions

                meta_path = os.path.join(self.output_dir, os.path.basename(self.fw_path) + '.ai.summary.json')
                with open(meta_path, 'w') as mf:
                    json.dump(findings, mf, indent=2)
                self.thread_log.emit(f'[AI] wrote summary: {meta_path}')

                # Update dashboard UI (schedule on main thread if possible)
                try:
                    summary_text = json.dumps(findings, indent=2, ensure_ascii=False)
                    def _ui_update():
                        try:
                            if hasattr(self, 'ai_summary_view'):
                                self.ai_summary_view.setPlainText(summary_text)
                            if hasattr(self, 'apply_suggested_btn'):
                                self.apply_suggested_btn.setEnabled(bool(findings.get('suggested_patches')))
                        except Exception:
                            pass
                    try:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(0, _ui_update)
                    except Exception:
                        _ui_update()
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.thread_log.emit(f'[AI] compose summary failed: {e}')
                except Exception:
                    self.log(f'[AI] compose summary failed: {e}')

            self.thread_log.emit('[AI] Orchestrator finished')
        except Exception as e:
            try: self.thread_log.emit(f'[AI] orchestrator error: {e}')
            except Exception: pass

    def run_deep_scan(self):
        try:
            res = deep_scan_file(self.fw_path) if getattr(self, 'fw_path', None) else None
            self.thread_log.emit(f'[DEEP] deep_scan result: {str(bool(res))}')
        except Exception as e:
            self.thread_log.emit(f'[DEEP] deep_scan error: {e}')

    def open_uboot_env_editor(self):
        # non-interactive: just run scan_uboot_env and log top candidate
        try:
            envs = scan_uboot_env(self.fw_path) if getattr(self, 'fw_path', None) else []
            if envs:
                self.thread_log.emit(f'[UBOOT] found {len(envs)} env blocks; best @{hex(envs[0]["offset"])}')
            else:
                self.thread_log.emit('[UBOOT] no env blocks found')
        except Exception as e:
            self.thread_log.emit(f'[UBOOT] open editor error: {e}')

    def clear_logs(self):
        try:
            self.log_view.clear()
            self.log('[LOG] cleared')
        except Exception:
            pass

    # Patch action wrappers expected by auto-run
    def do_patch_boot_delay(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_boot.bin')
        ok, msg = core_patch_boot_delay(self.fw_path, None, 0, out, lambda m: self.thread_log.emit(m))
        try:
            self.thread_log.emit(f'[PATCH_BOOT] result: {ok} {msg}')
        except Exception:
            try: self.log(f'[PATCH_BOOT] result: {ok} {msg}')
            except Exception: pass

    def do_patch_serial(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_serial.bin')
        ok, msg = core_patch_rootfs_shell_serial(self.fw_path, None, out, lambda m: self.thread_log.emit(m))
        try:
            self.thread_log.emit(f'[PATCH_SERIAL] result: {ok} {msg}')
        except Exception:
            try: self.log(f'[PATCH_SERIAL] result: {ok} {msg}')
            except Exception: pass

    def do_patch_network(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_net.bin')
        ok, msg = core_patch_rootfs_network(self.fw_path, None, out, lambda m: self.thread_log.emit(m))
        try:
            self.thread_log.emit(f'[PATCH_NET] result: {ok} {msg}')
        except Exception:
            try: self.log(f'[PATCH_NET] result: {ok} {msg}')
            except Exception: pass

    def do_patch_all(self):
        self.do_patch_serial(); self.do_patch_network(); self.do_patch_boot_delay()

    def do_patch_rootpw(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_rootpw.bin')
        ok, msg = core_patch_root_password(self.fw_path, None, 'root', out, lambda m: self.thread_log.emit(m))
        try:
            self.thread_log.emit(f'[PATCH_ROOTPW] result: {ok} {msg}')
        except Exception:
            try: self.log(f'[PATCH_ROOTPW] result: {ok} {msg}')
            except Exception: pass

    def auto_run_mode(self, mode='A'):
        """Run the tools/auto_run_on_file.py in a background thread using FMKRunner.
        mode: 'A' or 'B'
        """
        if not getattr(self, 'fw_path', None):
            self.log('No firmware selected for auto-run')
            QMessageBox.information(self, 'Auto-Run', 'Please select a firmware file first')
            return
        python_exec = sys.executable
        script = os.path.join(os.path.dirname(__file__), 'tools', 'auto_run_on_file.py')
        if not os.path.exists(script):
            self.log('auto_run_on_file.py not found')
            return
        cmd = [python_exec, script, self.fw_path, mode, 'auto']
        runner = FMKRunner(cmd, cwd=os.path.abspath(os.path.dirname(__file__)))
        runner.log.connect(lambda m: self.thread_log.emit(m))
        runner.error.connect(lambda e: self.thread_log.emit(f'Auto-run error: {e}'))
        runner.finished.connect(lambda rc: self.thread_log.emit(f'Auto-run finished (rc={rc})'))
        runner.start()
        self._register_thread(runner)

    # ---------- Automatic dependency preparation ----------
    def _auto_prepare_env(self):
        if os.path.exists(getattr(self, 'deps_flag', '/tmp/none')):
            try: self.thread_log.emit('[SETUP] deps flag already present (skip)')
            except Exception: pass
            return
        try: self.thread_log.emit('[SETUP] Auto-preparing FMK dependencies...')
        except Exception: pass
        try:
            self.install_fmk_deps(automatic=True)
        except Exception as e:
            try: self.thread_log.emit(f'[SETUP] auto prepare failed: {e}')
            except Exception: pass

    def install_fmk_deps(self, automatic: bool=False):
        """ตรวจและติดตั้งเฉพาะ dependencies ที่ 'ยังไม่มี' (Debian/Ubuntu เท่านั้น).
        หากระบบไม่ใช่ Debian/Ubuntu หรือไม่มี apt จะข้ามทันที.
        ลำดับ:
          1) ตรวจ core build / python runtime packages
          2) ตรวจความพร้อมของเครื่องมือ filesystem (ผ่าน capability registry + which)
          3) เลือก python3-venv เฉพาะ candidate version ตรง runtime
          4) สร้างรายการที่ขาด -> apt install เฉพาะรายการนั้น
          5) ถ้าไม่ขาดอะไร: log แล้วจบ
        มี fallback ensurepip+virtualenv หากไม่มี python3-venv ที่ตรง
        """
        import sys, subprocess, shutil
        if not shutil.which('apt') or not os.path.exists('/etc/debian_version'):
            try: self.thread_log.emit('[FMK] ข้าม: ไม่มี apt หรือไม่ใช่ Debian/Ubuntu')
            except Exception: pass
            return
        pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
        core_build = [
            'build-essential','git','zlib1g-dev','liblzma-dev','liblzo2-dev','libtool',
            'automake','autoconf','unzip','gawk','wget','cpio'
        ]
        python_runtime = ['python3','python3-pip','python3-setuptools','python3-yaml','python3-pyqt5','python3-pyqt5.qtsvg']
        def _pkg_installed(pkg):
            try:
                subprocess.check_output(['dpkg','-s',pkg], stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False
        missing = []
        for pkg in core_build:
            if not _pkg_installed(pkg): missing.append(pkg)
        for pkg in python_runtime:
            if not _pkg_installed(pkg): missing.append(pkg)
        from tool_registry import get_candidates, CAP_SQUASHFS_EXTRACT, CAP_SQUASHFS_PACK, CAP_CRAMFS_EXTRACT, CAP_CRAMFS_PACK, CAP_JFFS2_PACK
        if not get_candidates(CAP_SQUASHFS_EXTRACT) or not get_candidates(CAP_SQUASHFS_PACK):
            if not _pkg_installed('squashfs-tools'): missing.append('squashfs-tools')
        if not get_candidates(CAP_CRAMFS_EXTRACT) or not get_candidates(CAP_CRAMFS_PACK):
            if not _pkg_installed('cramfsprogs'): missing.append('cramfsprogs')
        if not get_candidates(CAP_JFFS2_PACK):
            if not _pkg_installed('mtd-utils'): missing.append('mtd-utils')
        if not shutil.which('binwalk') and not _pkg_installed('binwalk'):
            missing.append('binwalk')
        # python3-venv candidate
        chosen_venv = None
        def _pkg_info(pkg):
            try: return subprocess.check_output(['apt-cache','policy',pkg], text=True, stderr=subprocess.DEVNULL)
            except Exception: return ''
        info = _pkg_info('python3-venv')
        if info and 'Candidate:' in info and 'Candidate: (none)' not in info:
            for line in info.splitlines():
                if 'Candidate:' in line:
                    cand_ver = line.split('Candidate:',1)[1].strip()
                    if pyver in cand_ver and not _pkg_installed('python3-venv'):
                        chosen_venv = 'python3-venv'
                    elif pyver not in cand_ver:
                        self.thread_log.emit(f'[FMK] ข้าม python3-venv (candidate {cand_ver} != {pyver})')
                    break
        if chosen_venv: missing.append(chosen_venv)
        # normalize unique
        seen=set(); uniq=[]
        for p in missing:
            if p not in seen:
                seen.add(p); uniq.append(p)
        missing = uniq
        if not missing:
            try: self.thread_log.emit('[FMK] ✅ ระบบมี dependencies ครบแล้ว (ไม่มีอะไรต้องติดตั้ง)')
            except Exception: pass
            return
        self.thread_log.emit('[FMK] รายการที่ต้องติดตั้ง: ' + ' '.join(missing))
        apt_update = ['apt','update']
        apt_install = ['apt','install','-y'] + missing
        self.thread_log.emit('[FMK] เริ่มติดตั้งอัตโนมัติ' if automatic else '[FMK] เริ่มติดตั้ง ...')
        flag = getattr(self, 'deps_flag', os.path.expanduser('~/.local/share/firmware_toolkit/deps_installed'))

        def _mark_done():
            try:
                with open(flag,'w') as f:
                    f.write(datetime.datetime.now(datetime.UTC).isoformat()+'\n')
                self.thread_log.emit('[FMK] Dependencies installed (flag written)')
            except Exception as e:
                self.thread_log.emit(f'[FMK] write flag failed: {e}')

        use_fallback = chosen_venv is None
        def _run_and_stream(cmd, use_sudo=False, password=None):
            try:
                if use_sudo:
                    proc = subprocess.Popen(['sudo','-S','-p','']+cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    if password is not None:
                        try: proc.stdin.write(password+'\n'); proc.stdin.flush()
                        except Exception: pass
                else:
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if proc.stdout:
                    for line in iter(proc.stdout.readline, ''):
                        if not line: break
                        try: self.thread_log.emit(line.rstrip())
                        except Exception: print(line.rstrip())
                proc.wait(); return proc.returncode == 0, proc.returncode
            except Exception as e:
                try: self.thread_log.emit(f'[FMK] command error {cmd}: {e}')
                except Exception: pass
                return False, str(e)
        def _mark_done():
            try:
                with open(flag,'w') as f: f.write(datetime.datetime.now(datetime.UTC).isoformat()+'\n')
                self.thread_log.emit('[FMK] Dependencies installed (flag written)')
            except Exception as e:
                self.thread_log.emit(f'[FMK] write flag failed: {e}')
        def _venv_fallback():
            if not use_fallback: return
            self.thread_log.emit('[FMK] fallback: ensurepip + virtualenv (no apt venv)')
            try:
                p = subprocess.run([sys.executable,'-m','ensurepip','--upgrade'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.thread_log.emit(f'[FMK] ensurepip rc={p.returncode}')
            except Exception as e:
                self.thread_log.emit(f'[FMK] ensurepip error: {e}')
            try:
                p = subprocess.run([sys.executable,'-m','pip','install','--upgrade','pip','virtualenv'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.thread_log.emit(f'[FMK] pip virtualenv rc={p.returncode}')
            except Exception as e:
                self.thread_log.emit(f'[FMK] virtualenv install error: {e}')

        if os.geteuid() == 0:
            def _root_flow():
                ok,_ = _run_and_stream(apt_update)
                if not ok:
                    self.thread_log.emit('[FMK] apt update failed (root)'); return
                ok,_ = _run_and_stream(apt_install)
                if ok:
                    self.thread_log.emit('[FMK] ติดตั้งเสร็จสมบูรณ์')
                    _venv_fallback(); _mark_done()
                    try: self._update_install_deps_visibility()
                    except Exception: pass
                else:
                    self.thread_log.emit('[FMK] apt install failed (root)')
            threading.Thread(target=_root_flow, daemon=True).start(); return

        # Non-root path
        if not automatic:
            try:
                ans = QMessageBox.question(self,'FMK dependencies','Install FMK dependencies now?', QMessageBox.Yes|QMessageBox.No)
            except Exception:
                ans = QMessageBox.No
            if ans != QMessageBox.Yes:
                self.thread_log.emit('[FMK] User skipped install (manual commands below)')
                self.thread_log.emit('  '+' '.join(apt_update))
                self.thread_log.emit('  '+' '.join(apt_install))
                return

        def _sudo_flow():
            # Best-effort sudo execution (avoid interactive password if no sudo)
            need_pw = shutil.which('sudo') is not None
            password = None
            if need_pw:
                try:
                    pwd, ok = QInputDialog.getText(self,'Sudo password','Enter sudo password:', QLineEdit.Password)
                    if not ok:
                        self.thread_log.emit('[FMK] sudo password cancelled'); return
                    password = pwd
                except Exception:
                    password = None
            ok,_ = _run_and_stream(apt_update, use_sudo=need_pw, password=password)
            if not ok:
                self.thread_log.emit('[FMK] apt update failed (sudo)'); return
            ok,_ = _run_and_stream(apt_install, use_sudo=need_pw, password=password)
            if ok:
                self.thread_log.emit('[FMK] ติดตั้งเสร็จ (sudo)')
                _venv_fallback(); _mark_done()
                try: self._update_install_deps_visibility()
                except Exception: pass
            else:
                self.thread_log.emit('[FMK] apt install failed (sudo)')
        threading.Thread(target=_sudo_flow, daemon=True).start()
        
    # ---------------- Thread lifecycle helpers ----------------
    def _register_thread(self, thr):
        """Register QThread, attach cleanup signals."""
        try:
            if thr not in self._bg_threads:
                self._bg_threads.append(thr)
        except Exception:
            return
        for sig_name in ('finished', 'finished_ok', 'error'):
            try:
                sig = getattr(thr, sig_name)
                sig.connect(lambda *a, t=thr: self._bg_thread_cleanup(t))  # type: ignore[attr-defined]
            except Exception:
                pass

    def _bg_thread_cleanup(self, thr):
        try:
            if thr in self._bg_threads:
                self._bg_threads.remove(thr)
        except Exception:
            pass

    def wait_for_threads(self, timeout_s: float = 10.0):
        """Process events until all registered threads complete or timeout."""
        import time as _time
        end = _time.time() + timeout_s
        from PySide6.QtWidgets import QApplication as _QApp
        app = _QApp.instance()
        while _time.time() < end:
            alive = [t for t in self._bg_threads if getattr(t, 'isRunning', lambda: False)()]
            if not alive:
                break
            if app:
                try:
                    app.processEvents()
                except Exception:
                    pass
            _time.sleep(0.05)
        for t in list(self._bg_threads):
            try:
                if t.isRunning():
                    t.wait(100)
            except Exception:
                pass
        for t in list(self._bg_threads):
            if not getattr(t, 'isRunning', lambda: False)():
                self._bg_thread_cleanup(t)

    def archive_outputs(self):
        try:
            ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
            archdir = os.path.join(self.output_dir, f'archive_{ts}')
            os.makedirs(archdir, exist_ok=True)
            # copy relevant files
            for fn in os.listdir(self.output_dir):
                if any(fn.endswith(s) for s in ('.bin','.gz','.json','.txt')) or fn == 'SHA256SUMS':
                    src = os.path.join(self.output_dir, fn)
                    dst = os.path.join(archdir, fn)
                    try: shutil.copy2(src, dst)
                    except Exception: pass
            zip_path = os.path.join(self.output_dir, f'archive_{ts}.zip')
            subprocess.check_call(['zip','-r', zip_path, archdir], cwd=self.output_dir)
            self.log(f'Created archive: {zip_path}')
        except Exception as e:
            self.log(f'Archive failed: {e}')

    # ---------------- Newly added extended functionality ----------------
    def detect_rootfs_parts(self, auto: bool=False):
        if not getattr(self, 'fw_path', None):
            if not auto:
                QMessageBox.information(self, 'Detect', 'Select firmware first')
            return
        try:
            raw_parts = multisquash.detect_squashfs(self.fw_path)
            meta_parts = []
            with open(self.fw_path,'rb') as f:
                for i,p in enumerate(raw_parts):
                    try:
                        f.seek(p.offset); head = f.read(512)
                    except Exception:
                        head = b''
                    fs_guess = 'auto'
                    if head.startswith(b'hsqs') or head.startswith(b'sqsh'):
                        fs_guess = 'squashfs'
                    elif head[:4] in (b'\x45\x3d\xcd\x28', b'\x28\xcd\x3d\x45'):
                        fs_guess = 'cramfs'
                    elif head[:2] == b'\x85\x19':
                        fs_guess = 'jffs2'
                    elif b'yaffs' in head.lower():
                        fs_guess = 'yaffs2'
                    meta_parts.append({'offset': p.offset, 'size': p.size, 'fs_guess': fs_guess, 'desc': getattr(p,'desc','')})
                    self.log(f"[PART] #{i+1} off={hex(p.offset)} size={p.size} guess={fs_guess}")
            self.detected_parts = meta_parts
            if meta_parts:
                self.rootfs_part_spin.setEnabled(True)
                self.rootfs_part_spin.setMaximum(len(meta_parts))
                guesses = ', '.join(sorted({m['fs_guess'] for m in meta_parts}))
                self.parts_info_label.setText(f'Detected {len(meta_parts)} parts (fs: {guesses})')
            else:
                self.rootfs_part_spin.setEnabled(False)
                self.parts_info_label.setText('No parts detected')
        except Exception as e:
            self.log(f'[PART] detect error: {e}')
            QMessageBox.warning(self, 'Detect', f'Error: {e}')

    def _selected_part(self):
        parts = getattr(self, 'detected_parts', [])  # list of dicts now
        if not parts:
            QMessageBox.information(self, 'RootFS', 'ยังไม่มี parts (กด Detect Parts ก่อน)')
            return None
        idx = self.rootfs_part_spin.value() - 1
        if idx < 0 or idx >= len(parts):
            QMessageBox.warning(self, 'RootFS', 'index ผิดพลาด')
            return None
        p = parts[idx]
        # Already dict with fs_guess
        return {'offset': p['offset'], 'size': p['size'], 'fs': p.get('fs_guess','auto'), 'desc': p.get('desc','')}

    def edit_rootfs_file(self):
        if not getattr(self, 'fw_path', None):
            QMessageBox.information(self, 'RootFS', 'Select firmware first')
            return
        part = self._selected_part()
        if not part:
            return
        # cache extraction to speed repeat operations
        try:
            import tempfile
            if not hasattr(self, 'edit_cache_dir') or getattr(self, 'edit_cache_part_index', None) != self.rootfs_part_spin.value()-1:
                tmp = tempfile.mkdtemp(prefix='rfse_cache_')
                rootfs_bin = os.path.join(tmp, 'rootfs.bin')
                slice_size = part['size']
                # --- SquashFS size probing (unsquashfs -s -o <offset>) ---
                if part['fs'] in ('squashfs','auto'):
                    sys_unsq = shutil.which('unsquashfs')
                    if sys_unsq:
                        try:
                            import re, subprocess as _sub
                            cmd = [sys_unsq,'-s','-o', str(part['offset']), self.fw_path]
                            p = _sub.run(cmd, stdout=_sub.PIPE, stderr=_sub.STDOUT, text=True, timeout=10)
                            if p.returncode == 0 and p.stdout:
                                m = re.search(r'Filesystem size\s+(\d+)\s+bytes', p.stdout)
                                if m:
                                    probed = int(m.group(1))
                                    if probed > slice_size and probed < 128*1024*1024:  # sanity cap 128MB
                                        self.log(f"[ROOTFS-EDITOR] adjust slice_size {slice_size} -> {probed} (probed)")
                                        slice_size = probed
                        except Exception as pe:
                            self.log(f"[ROOTFS-EDITOR] probe size failed: {pe}")
                with open(self.fw_path,'rb') as f:
                    f.seek(part['offset']); blob = f.read(slice_size)
                with open(rootfs_bin,'wb') as f: f.write(blob)
                extract_dir = os.path.join(tmp,'extract'); os.makedirs(extract_dir, exist_ok=True)
                fs_type = part['fs'] or 'auto'
                self.log(f"[ROOTFS-EDITOR] part_index={self.rootfs_part_spin.value()} fs_guess={fs_type} offset={hex(part['offset'])} size={part['size']}")
                ok, err = extract_rootfs(fs_type, rootfs_bin, extract_dir, self.log)
                if not ok and fs_type != 'auto':
                    self.log(f"[ROOTFS-EDITOR] retry auto after {fs_type} fail: {err}")
                    ok, err = extract_rootfs('auto', rootfs_bin, extract_dir, self.log)
                # --- Fallback: if still failing and small slice, try extended carve (increase window) ---
                if not ok and slice_size < 2*1024*1024 and part['fs'] in ('squashfs','auto'):
                    try:
                        max_extend = min(os.path.getsize(self.fw_path) - part['offset'], 16*1024*1024)
                        if max_extend > slice_size:
                            new_size = max_extend
                            self.log(f"[ROOTFS-EDITOR] extend slice and retry: {slice_size} -> {new_size}")
                            with open(self.fw_path,'rb') as f:
                                f.seek(part['offset']); blob = f.read(new_size)
                            with open(rootfs_bin,'wb') as f: f.write(blob)
                            ok2, err2 = extract_rootfs('squashfs', rootfs_bin, extract_dir, self.log)
                            if not ok2:
                                self.log(f"[ROOTFS-EDITOR] extended retry failed: {err2}")
                            else:
                                ok = True; err = ''
                    except Exception as fe:
                        self.log(f"[ROOTFS-EDITOR] extend slice exception: {fe}")
                if not ok:
                    QMessageBox.critical(self,'RootFS', f'Extract failed: {err}'); return
                self.edit_cache_dir = extract_dir
                self.edit_cache_part_index = self.rootfs_part_spin.value()-1
            from dialogs import RootFSEditDialog
            dlg = RootFSEditDialog(self, self.edit_cache_dir, part, self.fw_path, self.output_dir)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, 'RootFS', f'Error: {e}')

    def run_custom_script(self):
        if not getattr(self,'fw_path',None):
            QMessageBox.information(self,'Script','Select firmware first'); return
        part = self._selected_part();
        if not part: return
        try:
            from dialogs import CustomScriptDialog
            dlg = CustomScriptDialog(self, part)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self,'Script', f'Error: {e}')

    def open_selective_patch_dialog(self):
        if not getattr(self,'fw_path',None):
            QMessageBox.information(self,'Patch','Select firmware first'); return
        try:
            from dialogs import SelectivePatchDialog
            dlg = SelectivePatchDialog(self)
            if dlg.exec():
                actions = dlg.get_actions()
                self.apply_patch_actions(actions)
        except Exception as e:
            QMessageBox.critical(self,'Patch', f'Error: {e}')

    def apply_patch_actions(self, actions: dict):
        # Apply chosen patch actions sequentially updating fw_path incrementally
        if not actions:
            self.log('[SELECTIVE] ไม่มี actions'); return
        cur = self.fw_path
        base = os.path.splitext(os.path.basename(self.fw_path))[0]
        # Boot delay
        if actions.get('boot_delay'):
            out = os.path.join(self.output_dir, base + '_sel_boot.bin')
            ok, msg = core_patch_boot_delay(cur, None, actions.get('boot_delay_value',1), out, lambda m: self.thread_log.emit(m))
            if ok: cur = out; self.thread_log.emit('[SELECTIVE] boot_delay applied');
            else: self.thread_log.emit(f'[SELECTIVE] boot_delay failed: {msg}')
        if actions.get('serial_shell'):
            out = os.path.join(self.output_dir, base + '_sel_serial.bin')
            ok, msg = core_patch_rootfs_shell_serial(cur, None, out, lambda m: self.thread_log.emit(m))
            if ok: cur = out; self.thread_log.emit('[SELECTIVE] serial applied')
            else: self.thread_log.emit(f'[SELECTIVE] serial failed: {msg}')
        if actions.get('network_services'):
            out = os.path.join(self.output_dir, base + '_sel_net.bin')
            ok, msg = core_patch_rootfs_network(cur, None, out, lambda m: self.thread_log.emit(m))
            if ok: cur = out; self.thread_log.emit('[SELECTIVE] network applied')
            else: self.thread_log.emit(f'[SELECTIVE] network failed: {msg}')
        if actions.get('root_password'):
            out = os.path.join(self.output_dir, base + '_sel_rootpw.bin')
            pw = actions.get('root_password_value','admin1234')
            ok, msg = core_patch_root_password(cur, None, pw, out, lambda m: self.thread_log.emit(m))
            if ok: cur = out; self.thread_log.emit('[SELECTIVE] root password applied')
            else: self.thread_log.emit(f'[SELECTIVE] root password failed: {msg}')
        # Update current firmware path if at least one patch succeeded
        if cur != self.fw_path:
            self.fw_path = cur
            self.log(f'[SELECTIVE] Updated working firmware -> {cur}')

    def open_uboot_env_editor_dialog(self):
        if not getattr(self,'fw_path',None):
            QMessageBox.information(self,'U-Boot','Select firmware first'); return
        try:
            from dialogs import UBootEnvEditorDialog
            dlg = UBootEnvEditorDialog(self, lambda deep=False: scan_uboot_env(self.fw_path, deep=deep),
                                       lambda src,dst,off,size,updates: patch_uboot_env_vars(src,dst,off,size,updates, self.log))
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self,'U-Boot', f'Error: {e}')

    def _ensure_unified_path(self):
        # Create a copy for editing operations; keep original safe
        ts = datetime.datetime.now(datetime.UTC).strftime('%Y%m%d%H%M%S')
        out = os.path.join(self.output_dir, f'unified_{ts}.bin')
        try:
            shutil.copy2(self.fw_path, out)
            return out
        except Exception as e:
            self.log(f'[UNIFY] copy failed: {e}')
            return self.fw_path

    def check_hash_signature(self):
        if not getattr(self,'fw_path',None):
            QMessageBox.information(self,'Hash','Select firmware first'); return
        try:
            sha = sha256sum(self.fw_path)
            sums_path = os.path.join(self.output_dir,'SHA256SUMS')
            status = ''
            if os.path.exists(sums_path):
                try:
                    with open(sums_path,'r') as f:
                        lines=f.read().splitlines()
                    match = any(sha in ln and os.path.basename(self.fw_path) in ln for ln in lines)
                    status = ' (match in SHA256SUMS)' if match else ' (NOT listed in SHA256SUMS)'
                except Exception:
                    status = ' (error reading SHA256SUMS)'
            gpg_sig = sums_path + '.sig'
            sig_status = ''
            if os.path.exists(gpg_sig):
                gpg = shutil.which('gpg')
                if gpg:
                    p = subprocess.run([gpg,'--verify',gpg_sig,sums_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    sig_status = ' Signature OK' if p.returncode==0 else ' Signature FAIL'
            QMessageBox.information(self,'Hash', f'SHA256={sha}{status}{sig_status}')
        except Exception as e:
            QMessageBox.critical(self,'Hash', f'Error: {e}')

    def export_patch_profile(self):
        if not getattr(self,'fw_path',None):
            QMessageBox.information(self,'Export','Select firmware first'); return
        profile = {
            'firmware': os.path.basename(self.fw_path),
            'timestamp': datetime.datetime.now(datetime.UTC).isoformat(),
            'available_outputs': [f for f in os.listdir(self.output_dir) if f.endswith('.bin')],
        }
        path, _ = QFileDialog.getSaveFileName(self,'Export Patch Profile','patch_profile.json','JSON (*.json)')
        if not path: return
        try:
            with open(path,'w',encoding='utf-8') as f: json.dump(profile,f,indent=2)
            QMessageBox.information(self,'Export', f'Saved: {path}')
        except Exception as e:
            QMessageBox.critical(self,'Export', f'Error: {e}')

    def import_patch_profile(self):
        path, _ = QFileDialog.getOpenFileName(self,'Import Patch Profile','','JSON (*.json)')
        if not path: return
        try:
            data = json.load(open(path,'r',encoding='utf-8'))
            self.log(f"[PROFILE] Loaded profile for {data.get('firmware')}")
            QMessageBox.information(self,'Import', f"Loaded profile: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self,'Import', f'Error: {e}')

    def apply_suggested_pipeline(self):
        """Read ai.summary and apply suggested patches sequentially after confirmation.
        Runs in a background thread to avoid blocking the UI.
        """
        if not getattr(self, 'fw_path', None):
            QMessageBox.information(self, 'Apply Pipeline', 'Please select a firmware first')
            return
        summary_path = os.path.join(self.output_dir, os.path.basename(self.fw_path) + '.ai.summary.json')
        if not os.path.exists(summary_path):
            QMessageBox.information(self, 'Apply Pipeline', 'AI summary not found. Run scan first by selecting firmware.')
            return
        try:
            data = json.load(open(summary_path, 'r', encoding='utf-8'))
        except Exception as e:
            QMessageBox.critical(self, 'Apply Pipeline', f'Failed to load summary: {e}')
            return
        suggestions = data.get('suggested_patches', [])
        if not suggestions:
            QMessageBox.information(self, 'Apply Pipeline', 'No suggested patches in summary')
            return
        # Show preview dialog so user can pick which suggested actions to apply
        try:
            dlg = SuggestedPipelinePreviewDialog(self, suggestions)
            if dlg.exec() != QDialog.Accepted:
                self.log('[AI] Apply suggested pipeline cancelled by user (preview)')
                return
            chosen = dlg.get_chosen()
            if not chosen:
                self.log('[AI] No suggestions chosen; aborting')
                return
            # start worker with chosen actions
            worker = ApplyPipelineWorker(self.fw_path, chosen, self.output_dir)
            # UI state
            self.apply_progress.setValue(0); self.apply_progress.setVisible(True)
            try:
                self.apply_suggested_btn.setEnabled(False)
                self.apply_suggested_btn.setText('Applying...')
            except Exception:
                pass
            self.cancel_apply_btn.setEnabled(True)
            self._active_apply_worker = worker

            # connect signals
            worker.log.connect(lambda m: self.thread_log.emit(m))
            worker.progress.connect(lambda p: self.apply_progress.setValue(p))
            def _on_finished(applied):
                try:
                    # update fw_path heuristically if boot delay was applied
                    if applied and 'patch_boot_delay' in applied and os.path.exists(os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_ai_bootdelay.bin')):
                        self.fw_path = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_ai_bootdelay.bin')
                    self.log('[AI] Pipeline finished: '+(', '.join(applied) if applied else 'no actions'))
                    if hasattr(self, 'ai_summary_view'):
                        self.ai_summary_view.append('\n[AI] Pipeline applied: '+(', '.join(applied) if applied else 'none'))
                except Exception:
                    pass
                finally:
                    try:
                        self.apply_progress.setVisible(False)
                        try:
                            self.apply_suggested_btn.setEnabled(True)
                            self.apply_suggested_btn.setText('Apply suggested pipeline')
                        except Exception:
                            pass
                        self.cancel_apply_btn.setEnabled(False)
                        self._active_apply_worker = None
                    except Exception:
                        pass

            worker.finished.connect(_on_finished)
            worker.start(); self._register_thread(worker)
        except Exception as e:
            self.log(f'[AI] apply pipeline start failed: {e}')

# ---------------- Helper Implementations (previously missing) ----------------
def preferred_tool(name: str):
    """Return path to preferred variant of a tool if multiple exist.
    Currently just returns shutil.which(name); placeholder for future priority logic.
    """
    try:
        return shutil.which(name)
    except Exception:
        return None

def auto_detect_tty_port_from_context(fw_path, rootfs_part, unsquashfs_dir, log_func=lambda m: None):
    """Heuristic: inspect /etc/inittab or /etc/securetty to guess a serial console.
    Falls back to common defaults (ttyS0, ttyS1)."""
    candidates = []
    try:
        for rel in ['etc/inittab', 'etc/securetty']:
            p = os.path.join(unsquashfs_dir, rel)
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        txt = f.read().lower()
                    for port in ['ttyS0', 'ttyS1', 'ttyAMA0', 'ttyUSB0']:
                        if port.lower() in txt and port not in candidates:
                            candidates.append(port)
                except Exception:
                    pass
    except Exception:
        pass
    for port in ['ttyS0', 'ttyAMA0', 'ttyUSB0', 'ttyS1']:
        if port not in candidates:
            candidates.append(port)
    choice = candidates[0] if candidates else 'ttyS0'
    log_func(f"[SERIAL-DETECT] selected {choice} from {candidates}")
    return choice


def main():
    """Application entry point for launching the PySide6 GUI."""
    # Set High DPI policy BEFORE QApplication creation (Task B)
    try:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)  # type: ignore
    except Exception:
        pass
    # Avoid launching multiple instances if already running in certain automation contexts
    app = QApplication.instance() or QApplication(sys.argv)
    # Load custom QSS style if present
    try:
        qss_path = os.path.join(os.path.dirname(__file__), 'styles.qss')
        if os.path.exists(qss_path):
            with open(qss_path, 'r', encoding='utf-8') as f:
                app.setStyleSheet(f.read())
    except Exception:
        pass
    # Set a sensible default font and size to match mock
    try:
        f = app.font()
        f.setPointSize(12)
        app.setFont(f)
    except Exception:
        pass
    win = MainWindow()
    # Provide a sensible default size if not restored by window manager
    try:
        if win.width() < 800 or win.height() < 600:
            win.resize(1280, 800)
    except Exception:
        pass
    win.show()
    # (Policy already set before QApplication creation)
    sys.exit(app.exec())


if __name__ == '__main__':  # pragma: no cover
    # Guard added so run-gui.sh can detect and execute this file directly.
    main()
