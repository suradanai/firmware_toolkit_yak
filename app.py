import sys
import os

import sys, os, subprocess, threading, hashlib, shutil, tempfile, datetime, struct, time, json, binascii
from dialogs import SelectivePatchDialog, RootFSEditDialog, CustomScriptDialog, SpecialFunctionsWindow, UBootEnvEditorDialog
from core.logging_utils import configure_logging

# --- System library check (Linux: libxcb-cursor0 for Qt) ---
def check_system_libs():
    import platform
    if platform.system() == "Linux":
        # Check for libxcb-cursor0 (required for Qt xcb plugin)
        import ctypes.util
        lib = ctypes.util.find_library("xcb-cursor")
        if not lib:
            msg = (
                "\n[WARNING] ไม่พบ system library ที่จำเป็น: libxcb-cursor0\n"
                "โปรแกรม GUI อาจไม่สามารถแสดงผลได้บน Linux หากขาดไลบรารีนี้\n"
                "\nวิธีติดตั้ง (Debian/Ubuntu):\n"
                "  sudo apt-get update && sudo apt-get install libxcb-cursor0\n"
                "\nหรือดาวน์โหลด .deb ได้ที่: https://packages.ubuntu.com/search?keywords=libxcb-cursor0\n"
                "\nสำหรับ Fedora/RedHat ใช้:\n"
                "  sudo dnf install xcb-util-cursor\n"
            )
            print(msg)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(None, "Missing System Library", msg)
            except Exception:
                pass

# เรียกตรวจสอบก่อนเริ่มโปรแกรมหลัก
check_system_libs()

# --- Time helpers ---
def utc_timestamp() -> str:
    """Return an RFC3339-like UTC timestamp with 'Z' suffix (timezone-aware)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

# Helper: prefer bundled external/<tool> before falling back to system PATH
def preferred_tool(name):
    repo_dir = os.path.dirname(__file__)
    # check common bundle locations first
    cand = [
        os.path.join(repo_dir, 'external', name, name),
        os.path.join(repo_dir, 'external', name, 'bin', name),
        os.path.join(repo_dir, 'external', name),
    ]
    for p in cand:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    # fall back to PATH
    which = shutil.which(name)
    return which or ''

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
    import time
    print("\n[INFO] ติดตั้ง dependencies อัตโนมัติ: ", ", ".join(missing))
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        print("[INFO] ติดตั้ง dependencies สำเร็จ กำลังรีสตาร์ทโปรแกรม...\n")
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print("[ERROR] ติดตั้ง dependencies ไม่สำเร็จ: ", e)
        sys.exit(1)

configure_logging()
# --- GUI / i18n / consent helpers (shared) ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog, QLabel, QComboBox, QHBoxLayout, QMessageBox, QTabWidget, QLineEdit, QSpinBox, QInputDialog, QDialog, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMenu, QProgressDialog, QProgressBar, QGroupBox, QStatusBar
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QTimer
from ui_theme import get_stylesheet, available_themes

# Simple i18n (Thai / English)
LANG = "th"  # Thai is default
_STRINGS = {
    'app_title': {'th': 'Firmware Toolkit bY yak', 'en': 'Firmware Toolkit bY yak'},
    # Buttons / actions (English values have no 'btn_' prefix wording)
    'btn_browse': {'th': 'เลือก', 'en': 'Browse'},
    'btn_open_fw': {'th': 'เปิดไฟล์เฟิร์มแวร์', 'en': 'Open Firmware'},
    'btn_patch_boot': {'th': 'Patch Boot Delay', 'en': 'Patch Boot Delay'},
    'btn_patch_serial': {'th': 'Patch Serial', 'en': 'Patch Serial'},
    'btn_patch_network': {'th': 'Patch Network', 'en': 'Patch Network'},
    'btn_patch_all': {'th': 'Patch ทั้งหมด', 'en': 'Patch All'},
    'btn_patch_rootpw': {'th': 'Patch รหัสผ่าน root', 'en': 'Patch Root Password'},
    'btn_ai_analyze': {'th': 'วิเคราะห์', 'en': 'Analyze'},
    'btn_ai_suggest': {'th': 'แนะนำ Patch', 'en': 'Suggest Patches'},
    'btn_ai_apply': {'th': 'ใช้ Patch', 'en': 'Apply Fixes'},
    'btn_ai_findings': {'th': 'ผลการวิเคราะห์', 'en': 'Findings'},
    'btn_special': {'th': 'พิเศษ', 'en': 'Special'},
    'btn_clear_logs': {'th': 'ล้างบันทึก', 'en': 'Clear Logs'},
    # Labels
    'label_output': {'th': 'โฟลเดอร์ผลลัพธ์', 'en': 'Output Folder'},
    'label_firmware': {'th': 'ไฟล์เฟิร์มแวร์', 'en': 'Firmware File'},
    'placeholder_select_fw': {'th': 'เลือกไฟล์เฟิร์มแวร์...', 'en': 'Select firmware file...'},
    'label_boot_delay': {'th': 'Boot Delay', 'en': 'Boot Delay'},
    'label_rootpw': {'th': 'รหัสผ่าน root', 'en': 'Root Password'},
    'grp_ai_security': {'th': 'AI / ความปลอดภัย', 'en': 'AI / Security'},
    'tab_log': {'th': 'บันทึก', 'en': 'Log'},
    'tab_rootfs_info': {'th': 'ข้อมูล RootFS', 'en': 'RootFS Info'},
    'tab_future': {'th': 'อื่น ๆ', 'en': 'Utilities'},
}
def _(key):
    return _STRINGS.get(key, {}).get(LANG, key)

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.config', 'firmware_toolkit')
CONSENT_PATH = os.path.join(CONFIG_DIR, 'consent.json')
ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons', 'firmware_toolkit_yak.svg')

def load_consent():
    try:
        with open(CONSENT_PATH,'r',encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_consent(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONSENT_PATH,'w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)

class ConsentDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("consent_title") if 'consent_title' in _STRINGS else 'Consent')
        self.resize(650, 420)
        lay = QVBoxLayout(self)
        intro = QLabel('Please confirm')
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.cb_patch = QCheckBox('Allow patch'); self.cb_patch.setChecked(True)
        self.cb_external = QCheckBox('Allow external tools'); self.cb_external.setChecked(True)
        self.cb_scripts = QCheckBox('Allow scripts'); self.cb_scripts.setChecked(False)
        self.cb_edit = QCheckBox('Allow edit rootfs'); self.cb_edit.setChecked(True)
        for cb in [self.cb_patch,self.cb_external,self.cb_scripts,self.cb_edit]:
            lay.addWidget(cb)
        lay.addStretch()
        btns = QHBoxLayout(); btns.addStretch()
        b_ok = QPushButton('Save'); b_cancel = QPushButton('Cancel')
        b_ok.clicked.connect(self.accept); b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_ok); btns.addWidget(b_cancel); lay.addLayout(btns)
    def get_result(self):
        return {
            'accepted': True,
            'allow_patch': self.cb_patch.isChecked(),
            'allow_external': self.cb_external.isChecked(),
            'allow_scripts': self.cb_scripts.isChecked(),
            'allow_edit': self.cb_edit.isChecked(),
            'version': 1,
            'timestamp': utc_timestamp()
        }

from passlib.hash import sha512_crypt
from core.fs_scan import scan_all_rootfs_partitions
from core.secret_scan import scan_secrets_in_dir
from core.elf_analyze import analyze_elf
from core.file_utils import sha256sum, md5sum, crc32sum, get_entropy
from core.uboot_env import (
    scan_uboot_env,
    analyze_bootloader_env,
    patch_uboot_env_bootdelay,
    patch_uboot_env_vars,
)


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
        shutil.rmtree(tmpdir)

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

class MainWindow(QMainWindow):
    """Main application window (reconstructed clean version)"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("app_title"))
        # Core state attributes (must exist before menus/status)
        self.original_fw_path: str | None = None  # original selected file
        self.patched_fw_path: str | None = None   # unified patched output path
        self.fw_path: str | None = None           # current working firmware (original or patched)
        # output_dir only for final patched firmware artifacts
        self.output_dir = os.path.abspath("output"); os.makedirs(self.output_dir, exist_ok=True)
        # logs_dir for AI / analysis / extraction logs (separate from firmware outputs)
        self.logs_dir = os.path.abspath("logs"); os.makedirs(self.logs_dir, exist_ok=True)
        self.rootfs_parts = []
        self.analysis_result = None
        self.rootfs_reports = []

        # ---- Build central UI ----
        central = QWidget(); main_v = QVBoxLayout(central)

        # Output folder selector
        out_h = QHBoxLayout(); out_h.addWidget(QLabel(_("label_output")))
        self.output_edit = QLineEdit(self.output_dir); out_h.addWidget(self.output_edit)
        btn_out = QPushButton(_("btn_browse")); btn_out.clicked.connect(self.select_output_folder); out_h.addWidget(btn_out)
        main_v.addLayout(out_h)

        # Firmware selection
        fw_h = QHBoxLayout(); fw_h.addWidget(QLabel(_("label_firmware")))
        self.fw_line = QLineEdit(); self.fw_line.setPlaceholderText(_("placeholder_select_fw")); fw_h.addWidget(self.fw_line)
        btn_fw = QPushButton(_("btn_open_fw")); btn_fw.clicked.connect(self.select_firmware); fw_h.addWidget(btn_fw)
        main_v.addLayout(fw_h)

        # Patch quick controls
        boot_h = QHBoxLayout(); boot_h.addWidget(QLabel(_("label_boot_delay")))
        self.delay_combo = QComboBox(); self.delay_combo.addItems([str(i) for i in range(10)]); boot_h.addWidget(self.delay_combo)
        btn_boot = QPushButton(_("btn_patch_boot")); btn_boot.setProperty('category','patch'); btn_boot.clicked.connect(self.do_patch_boot_delay); boot_h.addWidget(btn_boot)
        # New: direct U-Boot Env editor button on main row
        btn_env = QPushButton("Edit U-Boot Env"); btn_env.setProperty('category','patch'); btn_env.clicked.connect(self.open_uboot_env_editor); boot_h.addWidget(btn_env)
        boot_h.addStretch(); main_v.addLayout(boot_h)

        patch_h = QHBoxLayout()
        # Serial patch section with manual port selection
        self.serial_port_combo = QComboBox(); self.serial_port_combo.addItems([
            'AUTO','ttyS0','ttyS1','ttyS2','ttyAMA0','ttyUSB0'
        ])
        self.serial_port_combo.setToolTip('เลือกพอร์ตอนุกรม (AUTO = ตรวจหาอัตโนมัติ)')
        self.serial_custom_edit = QLineEdit(); self.serial_custom_edit.setPlaceholderText('custom (เช่น ttyS3)')
        patch_h.addWidget(QLabel('Serial Port:'))
        patch_h.addWidget(self.serial_port_combo)
        patch_h.addWidget(self.serial_custom_edit)
        btn_serial = QPushButton(_("btn_patch_serial")); btn_serial.setProperty('category','patch'); btn_serial.clicked.connect(self.do_patch_serial); patch_h.addWidget(btn_serial)
        btn_network = QPushButton(_("btn_patch_network")); btn_network.setProperty('category','patch'); btn_network.clicked.connect(self.do_patch_network); patch_h.addWidget(btn_network)
        patch_h.addStretch(); main_v.addLayout(patch_h)

        # Root password patch
        pw_h = QHBoxLayout(); pw_h.addWidget(QLabel(_("label_rootpw")))
        self.rootpw_edit = QLineEdit(); self.rootpw_edit.setEchoMode(QLineEdit.Password); pw_h.addWidget(self.rootpw_edit)
        btn_pw = QPushButton(_("btn_patch_rootpw")); btn_pw.setProperty('category','patch'); btn_pw.clicked.connect(self.do_patch_rootpw); pw_h.addWidget(btn_pw)
        main_v.addLayout(pw_h)

        # AI & Security group (on-demand actions only – no auto run)
        sec_grp = QGroupBox(_("grp_ai_security")); sec_l = QVBoxLayout(sec_grp)
        ai_btn_row = QHBoxLayout()
        self.btn_ai_analyze = QPushButton(_("btn_ai_analyze")); self.btn_ai_analyze.setProperty('category','ai'); self.btn_ai_analyze.clicked.connect(self.ai_analyze_all); ai_btn_row.addWidget(self.btn_ai_analyze)
        self.btn_ai_patch_suggest = QPushButton(_("btn_ai_suggest")); self.btn_ai_patch_suggest.setProperty('category','ai'); self.btn_ai_patch_suggest.clicked.connect(self.ai_patch_suggestion); ai_btn_row.addWidget(self.btn_ai_patch_suggest)
        self.btn_ai_apply_fixes = QPushButton(_("btn_ai_apply")); self.btn_ai_apply_fixes.setProperty('category','ai'); self.btn_ai_apply_fixes.clicked.connect(self.ai_apply_fixes); ai_btn_row.addWidget(self.btn_ai_apply_fixes)
        sec_l.addLayout(ai_btn_row)
        self.btn_ai_findings = QPushButton(_("btn_ai_findings")); self.btn_ai_findings.setProperty('category','info'); self.btn_ai_findings.clicked.connect(self.show_ai_findings); sec_l.addWidget(self.btn_ai_findings)
        main_v.addWidget(sec_grp)

        # Tabs & future utilities
        self.tabs = QTabWidget(); self.log_view = QTextEdit(); self.log_view.setReadOnly(True); self.info_view = QTextEdit(); self.info_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, _("tab_log")); self.tabs.addTab(self.info_view, _("tab_rootfs_info"))
        self.rootfs_part_spin = QSpinBox(); self.rootfs_part_spin.setRange(1, 32); self.rootfs_part_spin.hide()
        fut = QWidget(); fut_l = QVBoxLayout(fut)
        for text, slot in [
            ("Scan Vulnerabilities", self.scan_vulnerabilities),
            ("Scan Backdoor/Webshell", self.scan_backdoor),
            ("Diff Executables", self.diff_executables),
            ("Selective Patch", self.patch_selective),
            ("Edit U-Boot Env", self.open_uboot_env_editor),
            ("Edit RootFS File", self.edit_rootfs_file),
            ("Run Custom Script", self.run_custom_script),
            ("Check Hash/Signature", self.check_hash_signature),
            ("Export Patch Profile", self.export_patch_profile),
            ("Import Patch Profile", self.import_patch_profile),
        ]:
            b = QPushButton(text); b.clicked.connect(slot); fut_l.addWidget(b)
        fut_l.addStretch(); self.tabs.addTab(fut, _("tab_future")); main_v.addWidget(self.tabs, 1)

        # Utility buttons
        util_h = QHBoxLayout(); btn_special = QPushButton(_("btn_special")); btn_special.setProperty('category','info'); btn_special.clicked.connect(self.open_special_functions_window); util_h.addWidget(btn_special)
        btn_clear = QPushButton(_("btn_clear_logs")); btn_clear.setProperty('category','danger'); btn_clear.clicked.connect(self.clear_logs); util_h.addWidget(btn_clear); util_h.addStretch(); main_v.addLayout(util_h)

        # Finalize central widget & style with theme handling
        self.theme = self._load_theme()
        self.setCentralWidget(central)
        self.setStyleSheet(get_stylesheet(self.theme))
        self.status = QStatusBar(); self.setStatusBar(self.status)
        self._create_menus(); self.update_status()

        # Consent handling (non-blocking close if declined)
        self.consent = load_consent()
        if not self.consent.get('accepted'):
            dlg = ConsentDialog(self)
            if dlg.exec() != QDialog.Accepted:
                QTimer.singleShot(10, self.close)
            else:
                self.consent = dlg.get_result(); save_consent(self.consent); self.log("[CONSENT] saved")
        if self.consent.get('accepted') and not self.consent.get('desktop_installed'):
            try:
                if QMessageBox.question(self, _("desktop_title"), _("desktop_install_prompt"), QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                    if self._install_desktop_shortcut():
                        QMessageBox.information(self, _("desktop_title"), _("desktop_install_done")); self.consent['desktop_installed'] = True; save_consent(self.consent)
                    else:
                        QMessageBox.warning(self, _("desktop_title"), _("desktop_install_fail"))
            except Exception as e:
                self.log(f"[desktop-install-error] {e}")

        # External tools check (best-effort)
        try:
            self.check_external_tools()
        except Exception as e:
            self.log(f"ตรวจเครื่องมือภายนอกมีปัญหา: {e}")
        self.log("พร้อมใช้งาน UI (reconstructed)")
        # widen window for better visibility
        try:
            self.resize(max(self.width()*2, 1400), max(self.height(), 850))
        except Exception:
            pass

    # ---------- Utility / Logging ----------
    def log(self, text):
        self.log_view.append(text); self.log_view.ensureCursorVisible(); self.status.showMessage(text[:120])
    def info(self, text):
        self.info_view.append(text); self.info_view.ensureCursorVisible()
    def clear_logs(self):
        self.log_view.clear(); self.info_view.clear(); self.log("[LOG CLEARED]")
    # Persist log lines to category file under logs_dir
    def log_to_file(self, category: str, text: str):
        try:
            cat_dir = os.path.join(self.logs_dir, category)
            os.makedirs(cat_dir, exist_ok=True)
            day = datetime.datetime.utcnow().strftime('%Y%m%d')
            with open(os.path.join(cat_dir, f"{day}.log"), 'a', encoding='utf-8') as f:
                f.write(text + "\n")
        except Exception:
            pass
    def update_status(self):
        fw = os.path.basename(self.fw_path) if self.fw_path else "(no fw)"; self.status.showMessage(f"FW: {fw} | Parts: {len(self.rootfs_parts)} | Out: {self.output_dir}")

    # ---------- Menus ----------
    def _create_menus(self):
        mb = self.menuBar()
        # File
        m_file = mb.addMenu(_("menu_file"))
        a_fw = QAction(QIcon(ICON_PATH), _("act_open_fw"), self)
        a_fw.triggered.connect(self.select_firmware)
        m_file.addAction(a_fw)
        a_out = QAction(QIcon(ICON_PATH), _("act_set_output"), self)
        a_out.triggered.connect(self.select_output_folder)
        m_file.addAction(a_out)
        m_file.addSeparator()
        m_file.addAction(QAction(QIcon(ICON_PATH), _("act_exit"), self, triggered=self.close))
        # RootFS Info
        self.rootfs_menu = mb.addMenu(_("menu_rootfs_info"))
        self.update_rootfs_info()
        # Other menus...
        # Analysis
        m_an = mb.addMenu(_("menu_analysis"))
        for key,func in [('act_fw_info',self.show_fw_info),('act_ai_analyze',self.ai_analyze_all),('act_diff_exec',self.diff_executables),('act_hash_sig',self.check_hash_signature)]:
            m_an.addAction(QAction(QIcon(ICON_PATH), _(key),self,triggered=func))
        # Patching
        m_patch = mb.addMenu(_("menu_patching"))
        for key,func in [('act_patch_boot',self.do_patch_boot_delay),('act_patch_serial',self.do_patch_serial),('act_patch_network',self.do_patch_network),('act_patch_all',self.do_patch_all),('act_patch_rootpw',self.do_patch_rootpw),('act_patch_selective',self.patch_selective),('act_export_profile',self.export_patch_profile),('act_import_profile',self.import_patch_profile)]:
            m_patch.addAction(QAction(QIcon(ICON_PATH), _(key),self,triggered=func))
        # RootFS
        m_root = mb.addMenu(_("menu_rootfs"))
        for key,func in [('act_edit_rootfs',self.edit_rootfs_file),('act_custom_script',self.run_custom_script),('act_special_window',self.open_special_functions_window)]:
            m_root.addAction(QAction(QIcon(ICON_PATH), _(key),self,triggered=func))
        # Tools
        m_tools = mb.addMenu(_("menu_tools"))
        m_tools.addAction(QAction(QIcon(ICON_PATH), _("act_check_tools"), self, triggered=self.check_external_tools))
        m_tools.addAction(QAction(QIcon(ICON_PATH), _("act_clear_logs"), self, triggered=self.clear_logs))
        m_tools.addAction(QAction(QIcon(ICON_PATH), _("act_reset_consent"), self, triggered=self.reset_consent))
        # Theme submenu
        theme_menu = m_tools.addMenu("Themes")
        from PySide6.QtGui import QActionGroup
        grp = QActionGroup(self); grp.setExclusive(True)
        cur = self.theme
        for name in available_themes():
            act = QAction(name, self, checkable=True)
            if name == cur: act.setChecked(True)
            def make_apply(nm):
                return lambda: self._apply_theme(nm)
            act.triggered.connect(make_apply(name))
            grp.addAction(act); theme_menu.addAction(act)
        # Language submenu
        lang_menu = m_tools.addMenu(_("menu_language"))
        act_th = QAction(QIcon(ICON_PATH), _("lang_th"), self, checkable=True)
        act_en = QAction(QIcon(ICON_PATH), _("lang_en"), self, checkable=True)
        act_th.setChecked(LANG == 'th')
        act_en.setChecked(LANG == 'en')

        def _set_lang(code):
            global LANG
            LANG = code
            self.menuBar().clear()
            self._create_menus()
            self.setWindowTitle(_("app_title"))

        act_th.triggered.connect(lambda: _set_lang('th'))
        act_en.triggered.connect(lambda: _set_lang('en'))
        lang_menu.addAction(act_th)
        lang_menu.addAction(act_en)
        # Help
        m_help = mb.addMenu(_("menu_help")); m_help.addAction(QAction(QIcon(ICON_PATH), _("act_about"),self,triggered=lambda: QMessageBox.information(self,_("act_about"),"Firmware Toolkit bY yak")))

    # ---- Theme helpers ----
    def _theme_config_path(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        return os.path.join(CONFIG_DIR, 'theme.json')
    def _load_theme(self):
        try:
            with open(self._theme_config_path(),'r',encoding='utf-8') as f:
                data=json.load(f)
                if isinstance(data,dict):
                    return data.get('name','dark')
        except Exception:
            pass
        return 'dark'
    def _save_theme(self):
        try:
            with open(self._theme_config_path(),'w',encoding='utf-8') as f:
                json.dump({'name': self.theme}, f)
        except Exception:
            pass
    def _apply_theme(self, name):
        self.theme = name
        self.setStyleSheet(get_stylesheet(name))
        self._save_theme()

    # ---------- Desktop install helper ----------
    def _install_desktop_shortcut(self):
        try:
            base = os.path.dirname(__file__)
            desktop_src = os.path.join(base, 'FirmwareWorkbench.desktop')
            if not os.path.isfile(desktop_src):
                self.log('[desktop] source .desktop not found')
                return False
            # ensure run-gui.sh executable
            launcher = os.path.join(base, 'run-gui.sh')
            if os.path.isfile(launcher):
                mode = os.stat(launcher).st_mode
                if not (mode & 0o111):
                    os.chmod(launcher, mode | 0o755)
                    self.log('[desktop] chmod +x run-gui.sh')
            # copy desktop file
            target_dir = os.path.join(os.path.expanduser('~'), '.local', 'share', 'applications')
            os.makedirs(target_dir, exist_ok=True)
            target_desktop = os.path.join(target_dir, 'FirmwareWorkbench.desktop')
            # Optionally rewrite Exec/Icon lines to current absolute path
            try:
                with open(desktop_src,'r',encoding='utf-8') as f: lines = f.readlines()
                new_lines = []
                abs_exec = os.path.abspath(launcher)
                icon_name = 'firmware_toolkit_yak'
                for ln in lines:
                    if ln.startswith('Exec='):
                        new_lines.append(f'Exec={abs_exec}\n')
                    elif ln.startswith('Icon=') and '/' in ln:
                        new_lines.append('Icon=firmware_toolkit_yak\n')
                    else:
                        new_lines.append(ln)
                with open(target_desktop,'w',encoding='utf-8') as f: f.writelines(new_lines)
            except Exception:
                shutil.copy2(desktop_src, target_desktop)
            self.log(f'[desktop] installed .desktop -> {target_desktop}')
            # install icon
            icon_src = os.path.join(base, 'icons', 'firmware_toolkit_yak.svg')
            if os.path.isfile(icon_src):
                icon_dest = os.path.join(os.path.expanduser('~'), '.local','share','icons','hicolor','scalable','apps','firmware_toolkit_yak.svg')
                os.makedirs(os.path.dirname(icon_dest), exist_ok=True)
                try:
                    shutil.copy2(icon_src, icon_dest)
                    self.log('[desktop] icon installed')
                except Exception as e:
                    self.log(f'[desktop] icon copy failed: {e}')
            # refresh caches
            for cmd in ['update-desktop-database', 'gtk-update-icon-cache']:
                if shutil.which(cmd):
                    try:
                        subprocess.run([cmd, os.path.expanduser('~/.local/share/icons/hicolor')] if 'icon' in cmd else [cmd, os.path.expanduser('~/.local/share/applications')], timeout=8)
                        self.log(f'[desktop] ran {cmd}')
                    except Exception as e:
                        self.log(f'[desktop] {cmd} failed: {e}')
            return True
        except Exception as e:
            self.log(f'[desktop] install exception: {e}')
            return False

    # -------- consent helpers --------
    def is_allowed(self, feature):
        if not self.consent.get('accepted'): return False
        mapping = {
            'patch': 'allow_patch',
            'external': 'allow_external',
            'script': 'allow_scripts',
            'edit': 'allow_edit'
        }
        flag = mapping.get(feature)
        if not flag: return True
        return bool(self.consent.get(flag))
    def require(self, feature, msg_key):
        if not self.is_allowed(feature):
            QMessageBox.warning(self, _("consent_title"), _(msg_key))
            return False
        return True
    def reset_consent(self):
        try:
            if os.path.exists(CONSENT_PATH): os.remove(CONSENT_PATH)
        except Exception: pass
        self.consent = {}
        QMessageBox.information(self, _("consent_title"), _("consent_reset_done"))

    # ---------- External tools ----------
    def check_external_tools(self):
        tools = ["unsquashfs","jefferson","ubireader_extract_files","binwalk"]
        missing = [t for t in tools if not shutil.which(t)]
        if missing:
            self.log("⚠️ ขาด external tools บางตัว จะใช้ binwalk fallback เท่าที่ทำได้:")
            for t in missing:
                self.log(f"   - {t}")
        else:
            self.log("✅ พบ external tools หลักครบ (unsquashfs / jefferson / binwalk ฯลฯ)")
        self.update_status()

    # ---------- Basic actions ----------
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ Output", self.output_dir)
        if folder:
            self.output_dir = folder; self.output_edit.setText(folder); os.makedirs(folder, exist_ok=True); self.update_status()
    def select_firmware(self):
        file, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์เฟิร์มแวร์")
        if file:
            self.original_fw_path = file
            self.patched_fw_path = os.path.join(self.output_dir, f"patched_{os.path.basename(file)}")
            self.fw_path = self.original_fw_path
            self.fw_line.setText(file)
            self.log(f"เลือกไฟล์: {file}")
            self.auto_detect_rootfs()  # Automatically scan rootfs after selecting firmware
            self.update_rootfs_info()  # Update rootfs info in the menu
            self.update_status()
            # Schedule automatic AI analysis (non-blocking) after short delay
            QTimer.singleShot(200, lambda: self.ai_analyze_all())

    def update_rootfs_info(self):
        """Update the rootfs information in the menu."""
        self.rootfs_menu.clear()
        if not self.rootfs_parts:
            self.rootfs_menu.addAction("ไม่พบ rootfs")
            return
        for i, part in enumerate(self.rootfs_parts, 1):
            size_mb = part['size'] / (1024 * 1024)
            self.rootfs_menu.addAction(f"RootFS {i}: {part['fs']} - {size_mb:.2f} MB")

    def auto_detect_rootfs(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        self.rootfs_parts = scan_all_rootfs_partitions(self.fw_path, log_func=self.log)
        if self.rootfs_parts:
            self.rootfs_part_spin.setMaximum(len(self.rootfs_parts))
            self.log(f"พบ rootfs {len(self.rootfs_parts)} ส่วน")
        else:
            self.rootfs_part_spin.setMaximum(1)
            self.log("ไม่พบ rootfs ในไฟล์นี้")
        self.update_status()
    def get_selected_rootfs_part(self):
        if not self.rootfs_parts:
            self.auto_detect_rootfs()
        idx = self.rootfs_part_spin.value()-1
        if idx<0 or idx>=len(self.rootfs_parts):
            raise ValueError("index ผิดพลาด")
        return self.rootfs_parts[idx]

    # helper to create combined UI + file logger per function
    def _func_logger(self, category):
        return lambda m: (self.log(m), self.log_to_file(category, m))

    # ---------- Patch operations ----------
    def _ensure_unified_path(self):
        if not self.patched_fw_path and self.fw_path:
            self.patched_fw_path = os.path.join(self.output_dir, f"patched_{os.path.basename(self.fw_path)}")
        return self.patched_fw_path

    def do_patch_boot_delay(self):
        if not self.fw_path:
            QMessageBox.warning(self, "เลือกไฟล์ก่อน", "กรุณาเลือกไฟล์ firmware ก่อน"); return
        new_val = int(self.delay_combo.currentText())
        unified = self._ensure_unified_path()
        logger = self._func_logger('patch_boot')
        # try U-Boot env patch first (single), then deep+all fallback, finally raw byte
        tried_env = patch_uboot_env_bootdelay(self.fw_path, unified, new_val, logger)
        if not tried_env:
            # deep + all blocks
            logger('[INFO] ลอง deep scan + patch ทุกบล็อค')
            if not patch_uboot_env_bootdelay_all(self.fw_path, unified, new_val, logger):
                # compiled-in default env inside U-Boot binary
                logger('[INFO] ลอง patch bootdelay ภายใน U-Boot binary')
                if not patch_compiled_uboot_bootdelay(self.fw_path, unified, new_val, logger):
                    logger('[INFO] compiled-in patch ไม่พบในช่วงแรก ลองทั้งไฟล์')
                    if not patch_compiled_uboot_bootdelay(self.fw_path, unified, new_val, logger, search_limit=None):
                        logger('[INFO] ใช้ fallback แก้ byte @0x100')
                        patch_boot_delay(self.fw_path, None, new_val, unified, logger)
        # verify by rescanning unified
        try:
            envs_after = scan_uboot_env(unified, deep=True)
            any_bd = [e.get('bootdelay') for e in envs_after if e.get('bootdelay') is not None]
            logger(f"[VERIFY] env bootdelay values now: {any_bd}")
        except Exception as e:
            logger(f"[VERIFY] env rescan error: {e}")
        self.fw_path = unified
        # log boot delay change
        try:
            before = getattr(self, '_last_boot_delay', None)
            after = None
            try:
                after = read_boot_delay_byte(self.fw_path)
            except Exception:
                pass
            self.log(f"[BOOTDELAY] before={before} after={after}")
            self._last_boot_delay = after
        except Exception:
            pass
        self.update_status(); QMessageBox.information(self, "Boot Delay", f"เสร็จสิ้น: {unified}")

    def do_patch_serial(self):
        if not self.fw_path:
            QMessageBox.warning(self, "เลือกไฟล์ก่อน", "กรุณาเลือกไฟล์ firmware ก่อน"); return
        part = self.get_selected_rootfs_part(); unified = self._ensure_unified_path()
        # Determine user-selected port preference
        sel = self.serial_port_combo.currentText().strip()
        custom = self.serial_custom_edit.text().strip()
        if sel != 'AUTO':
            preferred = custom if custom else sel
        else:
            preferred = custom if custom else None  # None -> auto
        self._preferred_serial_port = preferred  # store for patch function to read
        patch_rootfs_shell_serial(self.fw_path, part, unified, self._func_logger('patch_serial'))
        self.fw_path = unified; self.update_status(); QMessageBox.information(self, "Serial", f"เสร็จสิ้น: {unified}")

    def do_patch_network(self):
        if not self.fw_path:
            QMessageBox.warning(self, "เลือกไฟล์ก่อน", ""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part(); unified = self._ensure_unified_path()
        patch_rootfs_network(self.fw_path, part, unified, self._func_logger('patch_network'))
        self.fw_path = unified; self.update_status(); QMessageBox.information(self, "Network", f"เสร็จสิ้น: {unified}")

    def do_patch_all(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน","" ); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part(); unified = self._ensure_unified_path()
        tmp_serial = unified + ".serial.tmp"; tmp_net = unified + ".net.tmp"
        patch_rootfs_shell_serial(self.fw_path, part, tmp_serial, self._func_logger('patch_all'))
        patch_rootfs_network(tmp_serial, part, tmp_net, self._func_logger('patch_all'))
        try:
            shutil.move(tmp_net, unified)
        finally:
            for t in (tmp_serial,):
                try: os.remove(t)
                except Exception: pass
        self.fw_path = unified; self.update_status(); QMessageBox.information(self,"Patch All",f"เสร็จสิ้น: {unified}")

    def do_patch_rootpw(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part(); pw = self.rootpw_edit.text(); unified = self._ensure_unified_path()
        patch_root_password(self.fw_path, part, pw, unified, self._func_logger('patch_rootpw'))
        self.fw_path = unified; self.update_status(); QMessageBox.information(self,"Root Password",f"เสร็จสิ้น: {unified}")

    # ---------- Info / Analysis ----------
    def show_fw_info(self):
        if not self.fw_path: QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์","เลือก firmware ก่อน"); return
        self.info_view.clear(); self.info(f"*** Firmware Info ***\n{self.fw_path}\n")
        try:
            s=os.stat(self.fw_path); self.info(f"Size: {s.st_size} bytes\nSHA256: {sha256sum(self.fw_path)}\nMD5: {md5sum(self.fw_path)}\n")
            self.info(f"Filetype: {get_filetype(self.fw_path)}\n")
            self.info(f"Entropy: {get_entropy(self.fw_path)}\n")
            # Boot delay info (env + raw byte)
            try:
                envs=scan_uboot_env(self.fw_path)
            except Exception:
                envs=[]
            if envs:
                for i,e in enumerate(envs,1):
                    bd=e.get('bootdelay')
                    self.info(f"BootDelay[env#{i}] @0x{e['offset']:X} size=0x{e['size']:X} crc_ok={e['valid']} => {bd if bd is not None else '?'}")
            else:
                self.info("BootDelay[env]: ไม่พบ U-Boot environment")
            b=read_boot_delay_byte(self.fw_path)
            if b is not None:
                self.info(f"BootDelay[byte@0x100]={b}")
        except Exception as e:
            self.info(f"error: {e}")
        parts = scan_all_rootfs_partitions(self.fw_path, log_func=lambda x: None)
        if parts:
            self.info("RootFS:")
            for i,p in enumerate(parts,1): self.info(f" [{i}] {p['fs']} 0x{p['offset']:X} size=0x{p['size']:X}")
        else:
            self.info("ไม่พบ rootfs")
    def ai_analyze_all(self):
        if not self.fw_path: QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์",""); return
        self.log("=== เริ่ม AI วิเคราะห์ ==="); self.info_view.clear()
        # --- Boot Delay (U-Boot env + fallback byte) pre-scan ---
        pre_findings=[]
        try:
            envs=scan_uboot_env(self.fw_path)
        except Exception:
            envs=[]
        if envs:
            for i,e in enumerate(envs,1):
                val=e.get('bootdelay')
                pre_findings.append(
                    f"Boot Delay (U-Boot env#{i} @0x{e['offset']:X} size=0x{e['size']:X} crc_ok={e['valid']}) = {val if val is not None else '?'}"
                )
            # Add env AI analysis (best env)
            env_ai_findings, env_ai_suggestions = analyze_bootloader_env(envs)
            pre_findings.extend(env_ai_findings)
            # store suggestions for later combined AI patch suggestions if needed
            self.bootenv_suggestions = env_ai_suggestions
        else:
            byte_val=read_boot_delay_byte(self.fw_path)
            pre_findings.append(f"Boot Delay (U-Boot env): ไม่พบ environment (byte@0x100={byte_val if byte_val is not None else '?'})")
        # Always include raw byte@0x100 line (helps heuristic suggestions)
        byte_val=read_boot_delay_byte(self.fw_path)
        if byte_val is not None:
            pre_findings.append(f"Boot Delay (byte@0x100): {byte_val}")
        # --- RootFS + other analysis ---
        findings, reports = self.analyze_all_rootfs_firmware(
            self.fw_path,
            log_func=lambda m: (self.log(m), self.log_to_file('analysis', m)),
            output_dir=self.logs_dir
        )
        all_findings = pre_findings + findings
        self.analysis_result = all_findings; self.rootfs_reports = reports
        for line in all_findings:
            self.log(line)
        self.log("==== จบการวิเคราะห์ ====")
        QMessageBox.information(self, "AI วิเคราะห์", f"เสร็จสิ้น rootfs={len(reports)}")
    def analyze_all_rootfs_firmware(self, fw_path, log_func, output_dir):
        findings=[]; reports=[]; tmpdir=tempfile.mkdtemp(prefix="ai-fw-rootfs-"); log_func(f"[TEMP] ai analysis workspace: {tmpdir}")
        try:
            parts=scan_all_rootfs_partitions(fw_path, log_func=log_func, use_cache=True)
            if not parts:
                findings.append("❌ ไม่พบ rootfs ใดๆ ใน firmware นี้"); return findings,reports
            for idx,part in enumerate(parts):
                log_func(f"== RootFS #{idx+1}: {part['fs']} @0x{part['offset']:X} size=0x{part['size']:X} ==")
                findings.append(f"-- RootFS#{idx+1}: {part['fs']} size=0x{part['size']:X}")
                rootfs_bin=os.path.join(tmpdir,f"rootfs_{idx+1}.bin")
                with open(fw_path,'rb') as f: f.seek(part['offset']); data=f.read(part['size'])
                with open(rootfs_bin,'wb') as fo: fo.write(data)
                extract_dir=os.path.join(tmpdir,f"extract_{idx+1}"); os.makedirs(extract_dir,exist_ok=True)
                ok,err=extract_rootfs(part['fs'],rootfs_bin,extract_dir,log_func)
                report_lines=[]
                if ok:
                    files=list_files_in_rootfs(extract_dir); findings.append(f"ไฟล์: {len(files)}")
                    # Secret scan (lightweight)
                    secrets = scan_secrets_in_dir(extract_dir)
                    if secrets:
                        findings.append(f"[SECRETS] พบ {len(secrets)} รายการ (แสดงสูงสุด 5)")
                        for s in secrets[:5]:
                            findings.append(f"  {s['type']} -> {s['file']} :: {s['snippet'][:60]}")
                    # ELF summary (sample up to 30 executables)
                    elf_infos = []
                    for rel, ftype in files:
                        if len(elf_infos) >= 30:
                            break
                        fpath = os.path.join(extract_dir, rel)
                        try:
                            with open(fpath,'rb') as ef:
                                if ef.read(4) != b'\x7fELF':
                                    continue
                            elf_infos.append(analyze_elf(fpath))
                        except Exception:
                            continue
                    arch_count = {}
                    for info in elf_infos:
                        arch = info.get('arch','?')
                        arch_count[arch] = arch_count.get(arch,0)+1
                    if arch_count:
                        findings.append('[ELF] Arch summary: ' + ', '.join(f"{k}:{v}" for k,v in arch_count.items()))
                    for critical in ["etc/passwd","etc/shadow","etc/inittab","etc/inetd.conf"]:
                        fp=os.path.join(extract_dir,critical)
                        if os.path.exists(fp):
                            findings.append(f"พบ {critical}")
                        else:
                            findings.append(f"ไม่พบ {critical}")
                else:
                    findings.append(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
                ts=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                analysis_dir = os.path.join(self.logs_dir, 'analysis'); os.makedirs(analysis_dir, exist_ok=True)
                outname=os.path.join(analysis_dir,f"ai_rootfs{idx+1}_{part['fs']}_0x{part['offset']:X}_{ts}.txt")
                with open(outname,'w',encoding='utf-8') as f:
                    for line in findings: f.write(line+"\n")
                reports.append(outname); findings.append(f"บันทึก {outname}")
        finally:
            shutil.rmtree(tmpdir,ignore_errors=True)
        return findings,reports
    def show_ai_findings(self):
        if not self.analysis_result: QMessageBox.warning(self,"ยังไม่มีผล",""); return
        txt="\n".join(self.analysis_result); QMessageBox.information(self,"AI Findings",txt)
    def ai_patch_suggestion(self):
        if not self.analysis_result: QMessageBox.warning(self,"ยังไม่มีผล",""); return
        recs=[]; 
        for line in self.analysis_result:
            if line.lower().startswith("boot delay") and any(ch.isdigit() for ch in line):
                recs.append("ลด boot delay เป็น 1")
        if any("telnet" in l.lower() for l in self.analysis_result): recs.append("ปิด telnet")
        if any("ftp" in l.lower() for l in self.analysis_result): recs.append("ปิด ftp")
        if any("ไม่พบ etc/shadow" in l.lower() or "ไม่พบ /etc/shadow" in l.lower() for l in self.analysis_result): recs.append("เพิ่ม /etc/shadow ตั้งรหัสผ่าน root แข็งแรง")
        # incorporate bootloader env AI suggestions if available
        if hasattr(self,'bootenv_suggestions'):
            for s in self.bootenv_suggestions:
                if s not in recs:
                    recs.append(s)
        self.recommended_actions=recs or ["ไม่พบข้อเสนอเพิ่มเติม"]; QMessageBox.information(self,"AI Patch Suggestion","\n".join(self.recommended_actions))
    def ai_apply_fixes(self):
        if not getattr(self,'recommended_actions',None): QMessageBox.warning(self,"ยังไม่มีคำแนะนำ",""); return
        if not self.fw_path: QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์",""); return
        applied=[]; part=self.get_selected_rootfs_part()
        if any("boot delay" in r.lower() for r in self.recommended_actions):
            out=os.path.join(self.output_dir,f"auto_fix_bootdelay_{int(time.time())}.bin"); patch_boot_delay(self.fw_path,part,1,out,self.log); applied.append("bootdelay->1")
        if any("telnet" in r.lower() or "ftp" in r.lower() for r in self.recommended_actions):
            out=os.path.join(self.output_dir,f"auto_fix_network_{int(time.time())}.bin"); patch_rootfs_network(self.fw_path,part,out,self.log); applied.append("network")
        if any("รหัสผ่าน" in r or "password" in r.lower() for r in self.recommended_actions):
            out=os.path.join(self.output_dir,f"auto_fix_rootpw_{int(time.time())}.bin"); patch_root_password(self.fw_path,part,self.rootpw_edit.text().strip() or "admin1234",out,self.log); applied.append("rootpw")
        QMessageBox.information(self,"Auto Fix", "\n".join(applied) if applied else "ไม่มีการแก้ไข")

    # ---------- Diff, Selective Patch, Editing ----------
    def diff_executables(self):
        if not self.fw_path: QMessageBox.warning(self,"Diff","เลือก firmware ก่อน"); return
        second,_=QFileDialog.getOpenFileName(self,"เลือกไฟล์เทียบ",os.path.dirname(self.fw_path))
        if not second: return
        try: part=self.get_selected_rootfs_part()
        except Exception as e: QMessageBox.warning(self,"Diff",str(e)); return
        prog=QProgressDialog("Diff executables...","ยกเลิก",0,0,self); prog.setWindowModality(Qt.WindowModal); prog.show(); QApplication.processEvents()
        tmp_base=tempfile.mkdtemp(prefix="diff_fw_"); self.log(f"[TEMP] diff executables workspace: {tmp_base}")
        try:
            def _extract(image, target):
                parts2=scan_all_rootfs_partitions(image, log_func=lambda x: None)
                m=None
                for p2 in parts2:
                    if p2['offset']==part['offset'] and p2['size']==part['size'] and _normalize_fs(p2['fs'])==_normalize_fs(part['fs']): m=p2; break
                if not m and parts2: m=parts2[0]
                if not m: raise RuntimeError("ไม่พบ rootfs")
                slice_path=os.path.join(target,"slice.bin");
                with open(image,'rb') as f: f.seek(m['offset']); data=f.read(m['size'])
                with open(slice_path,'wb') as f: f.write(data)
                ok,err=extract_rootfs(m['fs'],slice_path,target,log_func=lambda x: None)
                if not ok: raise RuntimeError(err)
            orig=os.path.join(tmp_base,"orig"); new=os.path.join(tmp_base,"new"); os.makedirs(orig); os.makedirs(new)
            _extract(self.fw_path,orig); _extract(second,new)
            execs=[]
            for base,root in [("orig",orig),("new",new)]:
                for dp,_,files in os.walk(root):
                    for nm in files:
                        fp=os.path.join(dp,nm); rel=os.path.relpath(fp,root)
                        try:
                            with open(fp,'rb') as f: hdr=f.read(4); st=os.stat(fp)
                        except Exception: continue
                        if hdr==b'\x7fELF' or (st.st_mode & 0o111): execs.append((base,rel,fp))
            pairs={};
            for base,rel,fp in execs: pairs.setdefault(rel,{})[base]=fp
            added=[]; removed=[]; changed=[]
            for rel,m in pairs.items():
                if 'orig' in m and 'new' in m:
                    h1=hashlib.sha256(open(m['orig'],'rb').read()).hexdigest(); h2=hashlib.sha256(open(m['new'],'rb').read()).hexdigest()
                    if h1!=h2: changed.append((rel,h1[:12],h2[:12]))
                elif 'orig' in m: removed.append(rel)
                else: added.append(rel)
            lines=[f"Executables (orig/new): {len([e for e in execs if e[0]=='orig'])}/{len([e for e in execs if e[0]=='new'])}", f"Added {len(added)} Removed {len(removed)} Changed {len(changed)}"]
            if added: lines.append("[Added]"); lines+= [" + "+a for a in added[:40]]
            if removed: lines.append("[Removed]"); lines+= [" - "+r for r in removed[:40]]
            if changed: lines.append("[Changed]"); lines+= [f" * {r} {h1}->{h2}" for r,h1,h2 in changed[:80]]
            report="\n".join(lines); self.log("[Diff Executables]\n"+report)
            dlg=QDialog(self); dlg.setWindowTitle("Diff Executables Report"); v=QVBoxLayout(dlg); te=QTextEdit(); te.setReadOnly(True); te.setText(report); v.addWidget(te); btn=QPushButton("ปิด"); btn.clicked.connect(dlg.accept); v.addWidget(btn); dlg.resize(900,600); prog.close(); dlg.exec()
        except Exception as e:
            prog.close(); QMessageBox.critical(self,"Diff",str(e))
        finally:
            shutil.rmtree(tmp_base,ignore_errors=True)
    def patch_selective(self):
        if not self.fw_path: QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์",""); return
        dlg=SelectivePatchDialog(self)
        if dlg.exec()!=QDialog.Accepted: return
        actions=dlg.get_actions();
        if not actions: QMessageBox.information(self,"Selective Patch","ไม่ได้เลือก patch"); return
        try: part=self.get_selected_rootfs_part()
        except Exception as e: QMessageBox.critical(self,"Selective Patch",str(e)); return
        ts=int(time.time()); current=self.fw_path; temps=[]; applied=[]
        try:
            if actions.get('boot_delay'):
                out=os.path.join(self.output_dir,f"_tmp_boot_{ts}.bin"); ok,_=patch_boot_delay(current,part,actions['boot_delay_value'],out,self.log); current=out; temps.append(out); applied.append(f"BootDelay={actions['boot_delay_value']}")
            if actions.get('serial_shell'):
                out=os.path.join(self.output_dir,f"_tmp_serial_{ts}.bin"); ok,_=patch_rootfs_shell_serial(current,part,out,self.log); current=out; temps.append(out); applied.append("SerialShell")
            if actions.get('network_services'):
                out=os.path.join(self.output_dir,f"_tmp_net_{ts}.bin"); ok,_=patch_rootfs_network(current,part,out,self.log); current=out; temps.append(out); applied.append("DisableTelnet/FTP")
            if actions.get('root_password'):
                out=os.path.join(self.output_dir,f"_tmp_rootpw_{ts}.bin"); ok,_=patch_root_password(current,part,actions['root_password_value'],out,self.log); current=out; temps.append(out); applied.append("RootPassword")
            final=os.path.join(self.output_dir,f"selective_patch_{ts}.bin"); shutil.copyfile(current,final); self.log(f"✅ Selective Patch -> {final}"); QMessageBox.information(self,"Selective Patch",f"สำเร็จ: {final}\n{', '.join(applied)}")
        finally:
            for t in temps:
                try: os.remove(t)
                except: pass
    def edit_rootfs_file(self):
        if not self.fw_path:
            QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์",""); return
        try:
            part=self.get_selected_rootfs_part()
        except Exception as e:
            QMessageBox.critical(self,"RootFS",str(e)); return
        if not hasattr(self,'edit_cache_dir'):
            self.edit_cache_dir=None; self.edit_cache_part_index=None
        idx=self.rootfs_part_spin.value()-1
        need=True
        if self.edit_cache_dir and os.path.isdir(self.edit_cache_dir) and self.edit_cache_part_index==idx and os.listdir(self.edit_cache_dir): need=False
        if need:
            tmp_work=tempfile.mkdtemp(prefix="edit_rootfs_"); self.log(f"[TEMP] rootfs edit workspace: {tmp_work}")
            rootfs_bin=os.path.join(tmp_work,"rootfs.bin")
            with open(self.fw_path,'rb') as f: f.seek(part['offset']); data=f.read(part['size'])
            with open(rootfs_bin,'wb') as fo: fo.write(data)
            extract_dir=os.path.join(tmp_work,"extract"); os.makedirs(extract_dir,exist_ok=True)
            ok,err=extract_rootfs(part['fs'],rootfs_bin,extract_dir,self.log)
            if not ok:
                shutil.rmtree(tmp_work,ignore_errors=True); QMessageBox.critical(self,"RootFS",err); return
            if self.edit_cache_dir and os.path.exists(self.edit_cache_dir):
                try: shutil.rmtree(self.edit_cache_dir)
                except: pass
            self.edit_cache_dir=extract_dir; self.edit_cache_workspace=tmp_work; self.edit_cache_part_index=idx
            self.log(f"แตก rootfs -> {extract_dir}")
        dlg=RootFSEditDialog(self,self.edit_cache_dir,part,self.fw_path,self.output_dir); dlg.exec()
    def run_custom_script(self):
        if not self.fw_path:
            QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์","เลือกไฟล์ก่อน"); return
        if not self.require('script','need_consent_scripts'): return
        try:
            part=self.get_selected_rootfs_part()
        except Exception as e:
            QMessageBox.warning(self,"Run Script",str(e)); return
        dlg=CustomScriptDialog(self,part); dlg.exec()
    def check_hash_signature(self):
        if not self.fw_path: QMessageBox.warning(self,"Hash","ยังไม่ได้เลือกไฟล์"); return
        fw_sha=sha256sum(self.fw_path); fw_md5=md5sum(self.fw_path); details=[f"Firmware: {os.path.basename(self.fw_path)}",f"SHA256: {fw_sha}",f"MD5: {fw_md5}"]
        if self.rootfs_parts:
            details.append("\n[RootFS Slice Hashes]")
            with open(self.fw_path,'rb') as f:
                for i,p in enumerate(self.rootfs_parts,1): f.seek(p['offset']); seg=f.read(min(65536,p['size'])); details.append(f"Part{i} {p['fs']} slice_sha25616={hashlib.sha256(seg).hexdigest()[:16]}")
        dlg=QDialog(self); dlg.setWindowTitle("Hash & Signature Report"); v=QVBoxLayout(dlg); te=QTextEdit(); te.setReadOnly(True); te.setText("\n".join(details)); v.addWidget(te); b=QPushButton("ปิด"); b.clicked.connect(dlg.accept); v.addWidget(b); dlg.resize(700,600); dlg.exec()
    def export_patch_profile(self):
        if not self.fw_path: QMessageBox.warning(self,"Export Profile","เลือก firmware ก่อน"); return
        dlg=SelectivePatchDialog(self)
        if dlg.exec()!=QDialog.Accepted: return
        actions=dlg.get_actions(); import json, time as _t
        profile={"version":1,"created":utc_timestamp(),"firmware_hint":os.path.basename(self.fw_path),"patches":actions}
        default=os.path.join(self.output_dir,f"patch_profile_{int(_t.time())}.json")
        path,_=QFileDialog.getSaveFileName(self,"บันทึก Patch Profile",default,"JSON (*.json)")
        if not path: return
        with open(path,'w',encoding='utf-8') as f:
            json.dump(profile,f,ensure_ascii=False,indent=2)
        self.log(f"บันทึก Patch Profile -> {path}")
    def import_patch_profile(self):
        if not self.fw_path: QMessageBox.warning(self,"Import Profile","เลือก firmware ก่อน"); return
        file,_=QFileDialog.getOpenFileName(self,"เลือก Patch Profile",self.output_dir,"JSON (*.json)")
        if not file: return
        import json; profile=json.load(open(file,'r',encoding='utf-8'))
        patches=profile.get('patches',{})
        dlg_text=", ".join(k for k,v in patches.items() if v)
        if QMessageBox.question(self,"ยืนยัน","Apply: "+dlg_text+" ?")!=QMessageBox.Yes: return
        try: part=self.get_selected_rootfs_part()
        except Exception as e: QMessageBox.warning(self,"Import",str(e)); return
        ts=int(time.time()); current=self.fw_path; temps=[]
        try:
            if patches.get('boot_delay'):
                out=os.path.join(self.output_dir,f"_tmp_prof_boot_{ts}.bin"); patch_boot_delay(current,part,patches['boot_delay_value'],out,self.log); temps.append(out); current=out
            if patches.get('serial_shell'):
                out=os.path.join(self.output_dir,f"_tmp_prof_serial_{ts}.bin"); patch_rootfs_shell_serial(current,part,out,self.log); temps.append(out); current=out
            if patches.get('network_services'):
                out=os.path.join(self.output_dir,f"_tmp_prof_net_{ts}.bin"); patch_rootfs_network(current,part,out,self.log); temps.append(out); current=out
            if patches.get('root_password'):
                out=os.path.join(self.output_dir,f"_tmp_prof_rootpw_{ts}.bin"); patch_root_password(current,part,patches.get('root_password_value','admin1234'),out,self.log); temps.append(out); current=out
            final=os.path.join(self.output_dir,f"apply_profile_{ts}.bin"); shutil.copyfile(current,final); self.log(f"✅ Apply Patch Profile -> {final}")
        finally:
            for t in temps:
                try: os.remove(t)
                except: pass
    def open_uboot_env_editor(self):
        if not self.fw_path:
            QMessageBox.warning(self,"U-Boot Env","เลือก firmware ก่อน")
            return
        def _scan(deep: bool=False):
            # forward deep flag to scanner
            return scan_uboot_env(self.fw_path, deep=deep)
        def _patch(src_fw, out_fw, off, size, updates):
            # ensure unified path for output
            return patch_uboot_env_vars(src_fw, out_fw, off, size, updates, self.log)
        dlg=UBootEnvEditorDialog(self,_scan,_patch)
        dlg.exec()
    # ---------- Special window ----------
    def open_special_functions_window(self):
        if hasattr(self,'special_win') and self.special_win:
            self.special_win.raise_(); self.special_win.activateWindow(); return
        self.special_win=SpecialFunctionsWindow(self); self.special_win.show()
    # ---------- Demo placeholders ----------
    def scan_vulnerabilities(self): QMessageBox.information(self,"Vuln Scan","[DEMO]")
    def scan_backdoor(self): QMessageBox.information(self,"Backdoor Scan","[DEMO]")

def auto_detect_tty_port_from_context(fw_path, rootfs_part, extracted_rootfs_dir, log_func):
    """Detect serial console port using multiple heuristics (bootargs, inittab, securetty)."""
    candidates=[]
    # user preference (stored on MainWindow if present)
    try:
        from inspect import currentframe
        # We cannot access MainWindow directly here reliably; placeholder logic: if global singleton or attribute set on caller.
    except Exception:
        pass
    # 1. U-Boot env bootargs
    try:
        envs = scan_uboot_env(fw_path, deep=True)
        if envs:
            bootargs = envs[0].get('vars',{}).get('bootargs','')
            import re
            m = re.search(r'console=(tty[A-Za-z0-9]+)', bootargs)
            if m:
                candidates.append(m.group(1))
    except Exception:
        pass
    # 2. inittab existing getty lines
    inittab_path = os.path.join(extracted_rootfs_dir,'etc','inittab')
    if os.path.exists(inittab_path):
        try:
            import re
            txt=open(inittab_path,'r',encoding='utf-8',errors='ignore').read()
            for m in re.finditer(r'getty[^\n]*?(tty\w+)', txt):
                candidates.append(m.group(1))
        except Exception:
            pass
    # 3. securetty
    securetty_path = os.path.join(extracted_rootfs_dir,'etc','securetty')
    if os.path.exists(securetty_path):
        try:
            for line in open(securetty_path,'r',encoding='utf-8',errors='ignore'):
                line=line.strip()
                if line.startswith('tty') and len(line)<16:
                    candidates.append(line)
        except Exception:
            pass
    # 4. common fallbacks
    candidates += ['ttyS0','ttyS1','ttyAMA0']
    # choose first existing inittab mention else first candidate
    seen=[]
    for c in candidates:
        if c not in seen:
            seen.append(c)
    # If caller (MainWindow) set _preferred_serial_port use it
    chosen = seen[0]
    try:
        # attempt to retrieve via global reference to QApplication activeWindow
        from PySide6.QtWidgets import QApplication
        w = QApplication.activeWindow()
        if w and hasattr(w, '_preferred_serial_port') and w._preferred_serial_port:
            pref = w._preferred_serial_port
            if pref.startswith('tty') and pref not in seen:
                seen.insert(0, pref)
            if pref.startswith('tty'):
                chosen = pref
                log_func(f"[AUTO-TTY] ใช้ค่าที่ผู้ใช้เลือก: {chosen}")
    except Exception:
        pass
    log_func(f"[AUTO-TTY] candidates={seen} -> เลือก {chosen}")
    return chosen
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())