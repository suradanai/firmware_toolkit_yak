import sys
import os
import subprocess, threading, hashlib, shutil, tempfile, datetime, struct, time, json, binascii, gzip

# Qt imports (added / restored after patch issues)
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
        QTreeWidget, QTreeWidgetItem, QSplitter, QTextEdit, QTabWidget, QFileDialog,
        QMessageBox, QInputDialog, QCheckBox, QSpinBox
    )
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

# --- System library check (Linux: libxcb-cursor0 for Qt) ---
def check_system_libs():
    # Minimal check: ensure required Qt system libs likely present
    try:
        # Example check: try importing PySide6 Qt platform plugin dependencies
        import importlib
        importlib.import_module('PySide6')
        return True
    except Exception:
        return False

# --- Auto install dependencies if missing ---
REQUIRED = [
    ("PySide6", "PySide6>=6.4.0"),
    ("passlib", "passlib>=1.7.4"),
    ("jefferson", "jefferson>=0.4.0"),
    ("yaml", "PyYAML>=6.0"),
]
missing = []
for mod, pipname in REQUIRED:
    try:
        if mod == "yaml":
            import yaml
        else:
            __import__(mod)
    except ImportError:
        missing.append(pipname)
if missing:
    print("\n[INFO] ติดตั้ง dependencies อัตโนมัติ:", ", ".join(missing))
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
    except Exception as e:
        print('[WARN] auto-install dependencies failed:', e)

# Simple translation shim (identity) to avoid NameError if i18n system not loaded
def _(key: str):
    return key

class FMKRunner(QThread):
    """Generic background process runner to stream stdout into GUI log."""
    log = Signal(str)
    finished = Signal(int)
    error = Signal(str)
    def __init__(self, cmd, cwd=None, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.cwd = cwd
    def run(self):  # type: ignore[override]
        try:
            p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=self.cwd)
            if p.stdout:
                for line in iter(p.stdout.readline, ''):
                    if not line:
                        break
                    self.log.emit(line.rstrip())
            p.wait()
            self.finished.emit(p.returncode)
        except Exception as e:
            self.error.emit(str(e))

class MultiSquashWorker(QThread):
    """Worker to execute multi-squash shrink & assembly pipeline without blocking GUI."""
    log = Signal(str)
    error = Signal(str)
    finished_ok = Signal(str)  # emits output firmware path
    def __init__(self, fw_path: str, out_dir: str, allow_destructive: bool=False, parent=None):
        super().__init__(parent)
        self.fw_path = fw_path
        self.out_dir = out_dir
        self.allow_destructive = allow_destructive
    def run(self):  # type: ignore[override]
        import core.multisquash as multisquash
        try:
            self.log.emit('[MSQ] detecting squashfs parts...')
            parts = multisquash.detect_squashfs(self.fw_path)
            if not parts:
                raise RuntimeError('No squashfs parts detected')
            tmp = tempfile.mkdtemp(prefix='msq-')
            try:
                replaced_files = []
                for idx, part in enumerate(parts):
                    part_file = os.path.join(tmp, f'part{idx}.bin')
                    multisquash.extract_part(self.fw_path, part, part_file)
                    self.log.emit(f'[MSQ] extracted part#{idx} off={hex(part.offset)} size={part.size}')
                    # attempt shrink
                    try:
                        unsq_dir = os.path.join(tmp, f'unsq{idx}')
                        os.makedirs(unsq_dir, exist_ok=True)
                        ok, err = extract_rootfs('squashfs', part_file, unsq_dir, lambda m: self.log.emit('[EXTRACT] '+m))
                        if not ok:
                            self.log.emit(f'[MSQ] skip shrink part#{idx} (extract fail: {err})')
                            replaced_files.append(part_file); continue
                        success, new_path, new_size = multisquash.shrink_pipeline(unsq_dir, part.size, allow_destructive=self.allow_destructive)
                        if success and new_path:
                            dest = os.path.join(tmp, f'shrunk{idx}.bin')
                            shutil.copy2(new_path, dest)
                            replaced_files.append(dest)
                            self.log.emit(f'[MSQ] shrunk part#{idx} -> {new_size} bytes')
                        else:
                            self.log.emit(f'[MSQ] shrink failed/oversize part#{idx}; keeping original')
                            replaced_files.append(part_file)
                    except Exception as e:
                        self.log.emit(f'[MSQ] error shrinking part#{idx}: {e}'); replaced_files.append(part_file)
                out_fw = os.path.join(self.out_dir, os.path.splitext(os.path.basename(self.fw_path))[0] + '_patched.bin')
                multisquash.assemble_parts(replaced_files, out_fw)
                self.log.emit(f'[MSQ] assembled firmware -> {out_fw}')
                self.finished_ok.emit(out_fw)
            finally:
                try: shutil.rmtree(tmp, ignore_errors=True)
                except Exception: pass
        except Exception as e:
            self.error.emit(str(e))


def get_filetype(fpath):
    try:
        return subprocess.check_output(["file", "-b", fpath], text=True).strip()
    except Exception as e:
        return f"file error: {e}"



    

def list_files_in_rootfs(rootfs_dir):
    filelist = []
    for root, dirs, files in os.walk(rootfs_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, rootfs_dir)
            ftype = get_filetype(fpath)
            filelist.append((rel, ftype))
    return filelist

def _normalize_fs(fs_type: str) -> str:
    if not fs_type:
        return fs_type
    fs = fs_type.lower()
    # Map common substrings / variants
    if 'squash' in fs:
        return 'squashfs'
    if 'cramfs' in fs:
        return 'cramfs'
    if 'jffs2' in fs or fs == 'jffs':
        return 'jffs2'
    if fs.startswith('ubi') or 'ubifs' in fs:
        return 'ubi'
    return fs_type  # fallback original

def extract_rootfs(fs_type, rootfs_bin, extract_dir, log_func):
    fs_type = _normalize_fs(fs_type)
    if fs_type == "squashfs":
        # Primary tool unsquashfs; fallback to sasquatch (unmodified squashfs) if available; then binwalk
        unsq = shutil.which("unsquashfs")
        sasq = shutil.which("sasquatch")  # patched unsquashfs for LZMA edge cases
        if unsq:
            try:
                subprocess.check_output([unsq, "-d", extract_dir, rootfs_bin], stderr=subprocess.STDOUT, timeout=45)
                return True, ""
            except Exception as e:
                log_func(f"unsquashfs error: {e}; จะลอง sasquatch/ binwalk fallback")
        if sasq:
            try:
                subprocess.check_output([sasq, "-d", extract_dir, rootfs_bin], stderr=subprocess.STDOUT, timeout=60)
                return True, ""
            except Exception as e:
                log_func(f"sasquatch error: {e}; จะลอง binwalk fallback")
    elif fs_type == "cramfs":
        try:
            subprocess.check_output(["cramfsck", "-x", extract_dir, rootfs_bin],
                                   stderr=subprocess.STDOUT, timeout=30)
            return True, ""
        except Exception as e:
            log_func(f"cramfsck error: {e}; จะลอง binwalk fallback")
    elif fs_type in ("jffs2", "jffs"):
        jefferson = shutil.which("jefferson")
        if jefferson:
            try:
                subprocess.check_output([jefferson, rootfs_bin, extract_dir],
                                       stderr=subprocess.STDOUT, timeout=60)
                return True, ""
            except Exception as e:
                log_func(f"jefferson error: {e}; จะลอง binwalk fallback")
        else:
            log_func("jefferson tool not found for jffs2; จะลอง binwalk fallback")
    elif fs_type == "ubi":
        ubireader = shutil.which("ubireader_extract_files")
        if ubireader:
            try:
                subprocess.check_output([
                    "ubireader_extract_files", "-o", extract_dir, rootfs_bin
                ], stderr=subprocess.STDOUT, timeout=120)
                return True, ""
            except Exception as e:
                log_func(f"ubireader error: {e}; จะลอง binwalk fallback")
        else:
            log_func("ubireader_extract_files tool not found for ubi; จะลอง binwalk fallback")
    else:
        log_func(f"ไม่รองรับการแตก {fs_type}; จะลอง binwalk fallback")

    # ---- Binwalk fallback ----
    bw = preferred_tool('binwalk') or shutil.which("binwalk")
    if not bw:
        return False, "ไม่สำเร็จและไม่มี binwalk fallback (ติดตั้งด้วย: sudo apt install binwalk หรือ pip install binwalk --break-system-packages)"
    try:
        # Run extraction (-e) into a temp dir then move best candidate into extract_dir
        tmp_bw = tempfile.mkdtemp(prefix="bw-extract-")
        try:
            subprocess.check_output([bw, "-e", rootfs_bin, "--directory", tmp_bw], stderr=subprocess.STDOUT, timeout=180)
        except subprocess.CalledProcessError as e:
            # binwalk returns non‑zero sometimes even if it extracted; continue
            log_func(f"binwalk non-zero exit: {e}")
        # Find candidate dirs (common names)
        candidates = []
        for r, dirs, files in os.walk(tmp_bw):
            for d in dirs:
                name = d.lower()
                if any(x in name for x in ["squashfs-root", "rootfs", "fs_", "_extracted"]):
                    candidates.append(os.path.join(r, d))
        if not candidates:
            # maybe binwalk created _rootfs.bin etc; as last resort copy everything
            for d in os.listdir(tmp_bw):
                p = os.path.join(tmp_bw, d)
                if os.path.isdir(p):
                    candidates.append(p)
        if not candidates:
            shutil.rmtree(tmp_bw, ignore_errors=True)
            return False, "binwalk fallback ไม่พบโฟลเดอร์ rootfs"
        # Pick largest candidate
        def dir_size(p):
            total=0
            for rp, _, fs in os.walk(p):
                for f in fs:
                    try: total += os.path.getsize(os.path.join(rp,f))
                    except: pass
            return total
        best = max(candidates, key=dir_size)
        shutil.copytree(best, extract_dir, dirs_exist_ok=True)
        shutil.rmtree(tmp_bw, ignore_errors=True)
        log_func(f"✅ binwalk fallback extract สำเร็จ (เลือก {os.path.basename(best)})")
        return True, ""
    except Exception as e:
        return False, f"binwalk fallback ล้มเหลว: {e}"

def repack_rootfs(fs_type, unsquashfs_dir, rootfs_bin_out, log_func, force_comp=None):
    fs_type = _normalize_fs(fs_type)
    if fs_type == "squashfs":
        mksquashfs = shutil.which("mksquashfs")
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
                        out = subprocess.check_output(["unsquashfs", "-s", orig_path], text=True, stderr=subprocess.DEVNULL)
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
        mkcramfs = shutil.which("mkcramfs")
        if not mkcramfs:
            return False, "mkcramfs tool not found"
        try:
            subprocess.check_output(
                [mkcramfs, unsquashfs_dir, rootfs_bin_out],
                stderr=subprocess.STDOUT, timeout=60
            )
            return True, ""
        except Exception as e:
            return False, f"mkcramfs error: {e}"

    elif fs_type in ("jffs2", "jffs"):
        mkfsjffs2 = shutil.which("mkfs.jffs2")
        if not mkfsjffs2:
            return False, "mkfs.jffs2 tool not found"
        try:
            subprocess.check_output(
                [mkfsjffs2, "-d", unsquashfs_dir, "-o", rootfs_bin_out],
                stderr=subprocess.STDOUT, timeout=120
            )
            return True, ""
        except Exception as e:
            return False, f"mkfs.jffs2 error: {e}"

    else:
        return False, f"ไม่รองรับการ pack {fs_type}"

def patch_boot_delay(fw_path, rootfs_part, new_delay, out_path, log_func):
    # Patch at offset 0x100 (example, may vary by firmware)
    try:
        with open(fw_path, "rb") as f:
            data = bytearray(f.read())
        if len(data) <= 0x100:
            log_func("❌ ไฟล์เล็กเกินไป ไม่มี offset 0x100")
            return False, "file too small"
        data[0x100] = new_delay & 0xFF
        with open(out_path, "wb") as f:
            f.write(data)
        log_func(f"✅ Patch boot delay ที่ offset 0x100 เป็น {new_delay} วินาที สำเร็จ: {out_path}")
        return True, ""
    except Exception as e:
        log_func(f"❌ Patch boot delay ผิดพลาด: {e}")
        return False, str(e)

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

def patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func):
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
                if ok:
                    new_size = os.path.getsize(new_rootfs_bin)
                    log_func(f"[AI] หลังใช้ xz ขนาด rootfs: {new_size} bytes")
                    if new_size <= rootfs_part['size']:
                        success = True
                else:
                    log_func(f"[AI] repack ด้วย xz ล้มเหลว: {err}")

            if not success:
                log_func("❌ พยายามลดขนาดอัตโนมัติทั้งหมดแล้วแต่ยังไม่พอ -> แสดงไฟล์แนะนำเพื่อลดด้วยมือ")
                file_sizes = []
                for dp, dn, fn in os.walk(unsquashfs_dir):
                    for f in fn:
                        fpath = os.path.join(dp, f)
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

def core_patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func):
    if rootfs_part is None:
        try:
            parts = multisquash.detect_squashfs(fw_path)
            if parts:
                rootfs_part = {'offset': parts[0].offset, 'size': parts[0].size, 'fs': 'squashfs', 'desc': parts[0].desc}
        except Exception:
            pass
    if rootfs_part is None:
        return False, 'no rootfs part'
    return patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func)

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
                hf.write(f"{datetime.datetime.utcnow().isoformat()}Z pid={os.getpid()} python={sys.executable} argv={sys.argv} DISPLAY={os.environ.get('DISPLAY')}\n")
        except Exception:
            pass
        super().__init__()
        self._bg_threads = []  # keep QThreads alive
        self.setWindowTitle(_('app_title'))

        # --- Menus ---
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        act_open = QAction(_('btn_open_fw'), self); act_open.triggered.connect(self.select_firmware); file_menu.addAction(act_open)
        tools_menu = menubar.addMenu('Tools')
        for txt, act in [(_('btn_patch_boot'),'boot_delay'),(_('btn_patch_serial'),'serial'),(_('btn_patch_network'),'network')]:
            a = QAction(txt, self); a.triggered.connect(lambda _=False, ac=act: self._run_quick_patch(ac)); tools_menu.addAction(a)
        tools_menu.addSeparator()
        for txt, slot in [
            ('Selective Patch...', self.open_selective_patch_dialog),
            ('RootFS Editor', self.edit_rootfs_file),
            ('Custom Script', self.run_custom_script),
            ('U-Boot Env Editor', self.open_uboot_env_editor_dialog),
            ('Check Hash / Signature', self.check_hash_signature),
            ('Export Patch Profile', self.export_patch_profile),
            ('Import Patch Profile', self.import_patch_profile),
        ]:
            a = QAction(txt, self); a.triggered.connect(slot); tools_menu.addAction(a)
        fmk_menu = menubar.addMenu('FMK')
        for txt, slot in [('Extract (FMK)', self.fmk_extract_wrapper), ('Build (FMK)', self.fmk_build_wrapper)]:
            a = QAction(txt, self); a.triggered.connect(slot); fmk_menu.addAction(a)

        # Paths / state
        self.original_fw_path = None; self.patched_fw_path = None; self.fw_path = None
        self.output_dir = os.path.abspath('output'); os.makedirs(self.output_dir, exist_ok=True)
        self.logs_dir = os.path.abspath('logs'); os.makedirs(self.logs_dir, exist_ok=True)

        # Sidebar + pages
        sidebar = QTreeWidget(); sidebar.setHeaderHidden(True); sidebar.setIndentation(0); sidebar.setFixedWidth(220)
        from PySide6.QtWidgets import QStackedWidget
        self.pages = QStackedWidget()

        # Dashboard page
        page_dashboard = QWidget(); dash_l = QVBoxLayout(page_dashboard)
        b_open = QPushButton(_('btn_open_fw')); b_open.clicked.connect(self.select_firmware); dash_l.addWidget(b_open)
        hpatch = QHBoxLayout()
        for txt, act in [(_('btn_patch_boot'),'boot_delay'),(_('btn_patch_serial'),'serial'),(_('btn_patch_network'),'network'),(_('btn_patch_all'),'all')]:
            b = QPushButton(txt); b.clicked.connect(lambda _=False, ac=act: self._run_quick_patch(ac)); hpatch.addWidget(b)
        dash_l.addLayout(hpatch); dash_l.addStretch(); self.pages.addWidget(page_dashboard)

        # Tools page
        page_tools = QWidget(); t_l = QVBoxLayout(page_tools)
        self.msq_allow_destructive = QCheckBox('Allow destructive trimming (remove logs/tmp/docs)')
        for txt, slot in [('Multi-Squash: Dry-run', self.multi_squash_dryrun), ('Multi-Squash: Apply', self.multi_squash_apply)]:
            b = QPushButton(txt); b.clicked.connect(slot); t_l.addWidget(b)
        for txt, slot in [('Auto-Run: Dry (A)', lambda: self.auto_run_mode('A')), ('Auto-Run: Patch (B)', lambda: self.auto_run_mode('B')), ('Archive Outputs', self.archive_outputs)]:
            b = QPushButton(txt); b.clicked.connect(slot); t_l.addWidget(b)
        t_l.addStretch(); self.pages.addWidget(page_tools)

        # AI page placeholder
        page_ai = QWidget(); ai_l = QVBoxLayout(page_ai); ai_l.addWidget(QLabel('AI / Scan tools (placeholder)')); ai_l.addStretch(); self.pages.addWidget(page_ai)

        # Special page
        page_special = QWidget(); sp_l = QVBoxLayout(page_special)
        sp_l.addWidget(QLabel('Special functions and utilities'))
        parts_row = QHBoxLayout(); parts_row.addWidget(QLabel('RootFS Parts:'))
        self.parts_detect_btn = QPushButton('Detect Parts'); self.parts_detect_btn.clicked.connect(self.detect_rootfs_parts); parts_row.addWidget(self.parts_detect_btn)
        self.rootfs_part_spin = QSpinBox(); self.rootfs_part_spin.setMinimum(1); self.rootfs_part_spin.setMaximum(1); self.rootfs_part_spin.setEnabled(False)
        parts_row.addWidget(QLabel('Select:')); parts_row.addWidget(self.rootfs_part_spin); parts_row.addStretch(); sp_l.addLayout(parts_row)
        part_actions = QHBoxLayout()
        for txt, slot in [('Open RootFS Editor', self.edit_rootfs_file), ('Run Custom Script', self.run_custom_script), ('U-Boot Env Editor', self.open_uboot_env_editor_dialog)]:
            b = QPushButton(txt); b.clicked.connect(slot); part_actions.addWidget(b)
        part_actions.addStretch(); sp_l.addLayout(part_actions)
        self.parts_info_label = QLabel('No parts detected yet'); sp_l.addWidget(self.parts_info_label); sp_l.addStretch(); self.pages.addWidget(page_special)

        # Settings page
        page_settings = QWidget(); set_l = QVBoxLayout(page_settings); set_l.addWidget(QLabel('Settings and preferences')); set_l.addStretch(); self.pages.addWidget(page_settings)

        # Sidebar population
        for name, idx in [('Dashboard',0),('Tools',1),('AI / Scan',2),('Special',3),('Settings',4)]:
            it = QTreeWidgetItem(sidebar); it.setText(0,name); it.setData(0, Qt.UserRole, idx)
        tools_root = sidebar.topLevelItem(1)
        if tools_root:
            for text, action in [('Open Firmware','open_fw'),('Multi-Squash: Dry-run','msq_dry'),('Multi-Squash: Apply','msq_apply')]:
                child = QTreeWidgetItem(tools_root); child.setText(0,text); child.setData(0, Qt.UserRole, (1, action))
        sidebar.currentItemChanged.connect(lambda cur, prev: self._on_sidebar_changed(cur))
        try:
            if sidebar.topLevelItemCount()>0: sidebar.setCurrentItem(sidebar.topLevelItem(0))
        except Exception:
            pass

        right_tabs = QTabWidget(); self.log_view = QTextEdit(); self.log_view.setReadOnly(True); right_tabs.addTab(self.log_view, _('tab_log'))
        hsplit = QSplitter(Qt.Horizontal)
        left_widget = QWidget(); left_l = QVBoxLayout(left_widget); left_l.addWidget(sidebar); left_l.addStretch(); hsplit.addWidget(left_widget)
        mid_widget = QWidget(); mid_l = QVBoxLayout(mid_widget); mid_l.addWidget(self.pages); mid_widget.setLayout(mid_l); hsplit.addWidget(mid_widget); hsplit.addWidget(right_tabs)
        main_container = QWidget(); main_layout = QVBoxLayout(main_container); main_layout.addWidget(hsplit); self.setCentralWidget(main_container)

    def select_firmware(self):
        res = QFileDialog.getOpenFileName(self, _('btn_open_fw'))
        # QFileDialog.getOpenFileName may return a tuple (path, filter)
        path = res[0] if isinstance(res, (list, tuple)) else res
        if path:
            self.fw_path = path
            self.log(f'Selected {path}')
            # auto-detect parts immediately for convenience
            self.detect_rootfs_parts(auto=True)

    def log(self, text):
        try:
            self.log_view.append(str(text))
        except Exception:
            print(text)

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
        runner.log.connect(self.log)
        runner.error.connect(lambda e: self.log(f'FMK runner error: {e}'))
        runner.finished.connect(lambda rc: self.log(f'FMK extract finished (rc={rc})'))
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
        runner.log.connect(self.log)
        runner.error.connect(lambda e: self.log(f'FMK runner error: {e}'))
        runner.finished.connect(lambda rc: self.log(f'FMK install finished (rc={rc})'))
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
            # PySide6 getInt signature: (parent, title, label, value=0, min=-2147483647, max=2147483647, step=1)
            val, ok = QInputDialog.getInt(self, 'Boot Delay', 'New boot delay (seconds):', 5, 0, 600, 1)
            if not ok:
                self.log('Boot delay patch cancelled')
                return
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_bootdelay.bin')
            okc, msg = core_patch_boot_delay(fw, None, val, outp, lambda m: self.log(m))
            if okc:
                self.log(f'Boot delay patched -> {outp}')
            else:
                self.log(f'Boot delay patch failed: {msg}')

        elif action == 'serial':
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_serial.bin')
            okc, msg = core_patch_rootfs_shell_serial(fw, None, outp, lambda m: self.log(m))
            if okc:
                self.log(f'Serial patch -> {outp}')
            else:
                self.log(f'Serial patch failed: {msg}')

        elif action == 'network':
            outp = os.path.join(self.output_dir, os.path.basename(fw).replace('.bin','') + f'_patched_network.bin')
            okc, msg = core_patch_rootfs_network(fw, None, outp, lambda m: self.log(m))
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
        worker = MultiSquashWorker(fw, out_dir, allow_destructive)
        worker.log.connect(self.log)
        worker.error.connect(lambda e: self.log(f'Pipeline error: {e}'))
        worker.finished_ok.connect(self._on_multisquash_finished)
        worker.start(); self._register_thread(worker)

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
                'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
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
            self.log(f'[TOOLS] {t}: {p or "NOT FOUND"}')

    def auto_detect_rootfs(self):
        try:
            parts = multisquash.detect_squashfs(self.fw_path) if self.fw_path else []
            self.log(f'[AUTO] detect_squashfs -> {len(parts)} parts')
        except Exception as e:
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

    def run_deep_scan(self):
        try:
            res = deep_scan_file(self.fw_path) if getattr(self, 'fw_path', None) else None
            self.log(f'[DEEP] deep_scan result: {str(bool(res))}')
        except Exception as e:
            self.log(f'[DEEP] deep_scan error: {e}')

    def open_uboot_env_editor(self):
        # non-interactive: just run scan_uboot_env and log top candidate
        try:
            envs = scan_uboot_env(self.fw_path) if getattr(self, 'fw_path', None) else []
            if envs:
                self.log(f'[UBOOT] found {len(envs)} env blocks; best @{hex(envs[0]["offset"])}')
            else:
                self.log('[UBOOT] no env blocks found')
        except Exception as e:
            self.log(f'[UBOOT] open editor error: {e}')

    def clear_logs(self):
        try:
            self.log_view.clear()
            self.log('[LOG] cleared')
        except Exception:
            pass

    # Patch action wrappers expected by auto-run
    def do_patch_boot_delay(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_boot.bin')
        ok, msg = core_patch_boot_delay(self.fw_path, None, 0, out, lambda m: self.log(m))
        self.log(f'[PATCH_BOOT] result: {ok} {msg}')

    def do_patch_serial(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_serial.bin')
        ok, msg = core_patch_rootfs_shell_serial(self.fw_path, None, out, lambda m: self.log(m))
        self.log(f'[PATCH_SERIAL] result: {ok} {msg}')

    def do_patch_network(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_net.bin')
        ok, msg = core_patch_rootfs_network(self.fw_path, None, out, lambda m: self.log(m))
        self.log(f'[PATCH_NET] result: {ok} {msg}')

    def do_patch_all(self):
        self.do_patch_serial(); self.do_patch_network(); self.do_patch_boot_delay()

    def do_patch_rootpw(self):
        out = os.path.join(self.output_dir, os.path.basename(self.fw_path).replace('.bin','') + '_patched_auto_rootpw.bin')
        ok, msg = core_patch_root_password(self.fw_path, None, 'root', out, lambda m: self.log(m))
        self.log(f'[PATCH_ROOTPW] result: {ok} {msg}')

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
        runner.log.connect(self.log)
        runner.error.connect(lambda e: self.log(f'Auto-run error: {e}'))
        runner.finished.connect(lambda rc: self.log(f'Auto-run finished (rc={rc})'))
        runner.start(); self._register_thread(runner)
        
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
            ts = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
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
            parts = multisquash.detect_squashfs(self.fw_path)
            self.detected_parts = parts
            if parts:
                self.rootfs_part_spin.setEnabled(True)
                self.rootfs_part_spin.setMaximum(len(parts))
                self.parts_info_label.setText(f'Detected {len(parts)} parts')
            else:
                self.rootfs_part_spin.setEnabled(False)
                self.parts_info_label.setText('No parts detected')
            for i,p in enumerate(parts):
                self.log(f'[PART] #{i+1} off={hex(p.offset)} size={p.size}')
        except Exception as e:
            self.log(f'[PART] detect error: {e}')
            QMessageBox.warning(self, 'Detect', f'Error: {e}')

    def _selected_part(self):
        parts = getattr(self, 'detected_parts', [])
        if not parts:
            QMessageBox.information(self, 'RootFS', 'ยังไม่มี parts (กด Detect Parts ก่อน)')
            return None
        idx = self.rootfs_part_spin.value() - 1
        if idx < 0 or idx >= len(parts):
            QMessageBox.warning(self, 'RootFS', 'index ผิดพลาด')
            return None
        p = parts[idx]
        # convert to dict format expected by patch helpers
        return {'offset': p.offset, 'size': p.size, 'fs': 'squashfs', 'desc': p.desc}

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
                with open(self.fw_path,'rb') as f:
                    f.seek(part['offset']); blob = f.read(part['size'])
                with open(rootfs_bin,'wb') as f: f.write(blob)
                extract_dir = os.path.join(tmp,'extract'); os.makedirs(extract_dir, exist_ok=True)
                ok, err = extract_rootfs(part['fs'], rootfs_bin, extract_dir, self.log)
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
            ok, msg = core_patch_boot_delay(cur, None, actions.get('boot_delay_value',1), out, lambda m: self.log(m))
            if ok: cur = out; self.log('[SELECTIVE] boot_delay applied');
            else: self.log(f'[SELECTIVE] boot_delay failed: {msg}')
        if actions.get('serial_shell'):
            out = os.path.join(self.output_dir, base + '_sel_serial.bin')
            ok, msg = core_patch_rootfs_shell_serial(cur, None, out, lambda m: self.log(m))
            if ok: cur = out; self.log('[SELECTIVE] serial applied')
            else: self.log(f'[SELECTIVE] serial failed: {msg}')
        if actions.get('network_services'):
            out = os.path.join(self.output_dir, base + '_sel_net.bin')
            ok, msg = core_patch_rootfs_network(cur, None, out, lambda m: self.log(m))
            if ok: cur = out; self.log('[SELECTIVE] network applied')
            else: self.log(f'[SELECTIVE] network failed: {msg}')
        if actions.get('root_password'):
            out = os.path.join(self.output_dir, base + '_sel_rootpw.bin')
            pw = actions.get('root_password_value','admin1234')
            ok, msg = core_patch_root_password(cur, None, pw, out, lambda m: self.log(m))
            if ok: cur = out; self.log('[SELECTIVE] root password applied')
            else: self.log(f'[SELECTIVE] root password failed: {msg}')
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
        ts = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
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
            'timestamp': datetime.datetime.utcnow().isoformat()+'Z',
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
    # Avoid launching multiple instances if already running in certain automation contexts
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    # Provide a sensible default size if not restored by window manager
    try:
        if win.width() < 800 or win.height() < 600:
            win.resize(1280, 800)
    except Exception:
        pass
    win.show()
    # Basic high-DPI attribute (Qt6 usually auto, but enforce just in case)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)  # type: ignore
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == '__main__':  # pragma: no cover
    # Guard added so run-gui.sh can detect and execute this file directly.
    main()
