import sys, os, subprocess, threading, hashlib, shutil, tempfile, datetime, struct, time, json

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

try:
    with open(os.path.join(os.path.dirname(__file__), 'VERSION'),'r',encoding='utf-8') as _vf:
        __version__ = _vf.read().strip()
except Exception:
    __version__ = '0.0.0'

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog, QLabel, QComboBox, QHBoxLayout, QMessageBox, QTabWidget, QLineEdit, QSpinBox, QInputDialog, QDialog, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMenu, QProgressDialog, QProgressBar, QGroupBox, QStatusBar
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QTimer

# -------- Simple i18n (Thai / English) ---------
LANG = os.environ.get("FWTK_LANG", "th")  # default Thai

_STRINGS = {
    'app_title': {'th': 'Firmware Toolkit bY yak', 'en': 'Firmware Toolkit bY yak'},
    'menu_file': {'th': 'ไฟล์', 'en': 'File'},
    'menu_analysis': {'th': 'วิเคราะห์', 'en': 'Analysis'},
    'menu_patching': {'th': 'แพตช์', 'en': 'Patching'},
    'menu_rootfs': {'th': 'RootFS', 'en': 'RootFS'},
    'menu_tools': {'th': 'เครื่องมือ', 'en': 'Tools'},
    'menu_help': {'th': 'ช่วยเหลือ', 'en': 'Help'},
    'act_open_fw': {'th': 'เปิดไฟล์เฟิร์มแวร์', 'en': 'Open Firmware'},
    'act_set_output': {'th': 'ตั้งค่าโฟลเดอร์ Output', 'en': 'Set Output Folder'},
    'act_exit': {'th': 'ออก', 'en': 'Exit'},
    'act_fw_info': {'th': 'ข้อมูลเฟิร์มแวร์', 'en': 'Firmware Info'},
    'act_scan_rootfs': {'th': 'สแกน RootFS', 'en': 'Scan RootFS'},
    'act_ai_analyze': {'th': 'AI วิเคราะห์', 'en': 'AI Analyze'},
    'act_diff_exec': {'th': 'Diff Executables', 'en': 'Diff Executables'},
    'act_hash_sig': {'th': 'Hash/ลายเซ็น', 'en': 'Hash/Signature'},
    'act_patch_boot': {'th': 'Boot Delay', 'en': 'Boot Delay'},
    'act_patch_serial': {'th': 'Serial Shell', 'en': 'Serial Shell'},
    'act_patch_network': {'th': 'Network', 'en': 'Network'},
    'act_patch_all': {'th': 'แพตช์ทั้งหมด', 'en': 'Patch All'},
    'act_patch_rootpw': {'th': 'รหัสผ่าน root', 'en': 'Root Password'},
    'act_patch_selective': {'th': 'เลือกแพตช์', 'en': 'Selective Patch'},
    'act_export_profile': {'th': 'ส่งออกโปรไฟล์', 'en': 'Export Profile'},
    'act_import_profile': {'th': 'นำเข้าโปรไฟล์', 'en': 'Import Profile'},
    'act_edit_rootfs': {'th': 'แก้ไข RootFS', 'en': 'Edit RootFS'},
    'act_custom_script': {'th': 'สคริปต์กำหนดเอง', 'en': 'Custom Script'},
    'act_special_window': {'th': 'หน้าต่างพิเศษ', 'en': 'Special Window'},
    'act_check_tools': {'th': 'ตรวจเครื่องมือ', 'en': 'Check Tools'},
    'act_clear_logs': {'th': 'ล้าง Log', 'en': 'Clear Logs'},
    'act_about': {'th': 'เกี่ยวกับ', 'en': 'About'},
    'menu_language': {'th': 'ภาษา', 'en': 'Language'},
    'lang_th': {'th': 'ไทย', 'en': 'Thai'},
    'lang_en': {'th': 'อังกฤษ', 'en': 'English'},
    # Consent / permission strings
    'consent_title': {'th':'การยืนยันการใช้งาน / ข้อกำหนด','en':'Usage Consent / Terms'},
    'consent_intro': {'th':'โปรดตรวจสอบและยืนยันการอนุญาตสำหรับการทำงานที่มีความเสี่ยงหรือแก้ไขไฟล์เฟิร์มแวร์ (ครั้งแรกเท่านั้น สามารถเปลี่ยนได้ในเมนู Tools).','en':'Please review and grant permissions for potentially risky operations (shown only on first launch; can be changed under Tools).'},
    'consent_patch': {'th':'อนุญาตให้แก้ไข / สร้างไฟล์เฟิร์มแวร์ (patch)','en':'Allow modifying / creating patched firmware images'},
    'consent_external': {'th':'อนุญาตเรียกใช้เครื่องมือภายนอก (unsquashfs, binwalk ฯลฯ)','en':'Allow invoking external tools (unsquashfs, binwalk, etc.)'},
    'consent_scripts': {'th':'อนุญาตให้รันสคริปต์/คำสั่งที่ผู้ใช้กำหนด (Custom Script)','en':'Allow running custom user scripts / commands'},
    'consent_edit': {'th':'อนุญาตแก้ไขไฟล์ภายใน rootfs (เพิ่ม/ลบ/แทนที่)','en':'Allow editing files inside extracted rootfs'},
    'consent_save': {'th':'บันทึกการยืนยัน','en':'Save Consent'},
    'consent_cancel': {'th':'ยกเลิกและออก','en':'Cancel & Exit'},
    'consent_reset_done': {'th':'รีเซ็ตการยืนยันแล้ว จะถามใหม่เมื่อเปิดโปรแกรม','en':'Consent reset. Will ask again on next launch.'},
    'need_consent_patch': {'th':'ยังไม่ได้รับอนุญาต patch (ไปที่ Tools > รีเซ็ต / ตั้งค่าสิทธิ์)','en':'Patch permission not granted (see Tools > Reset Consent).'},
    'need_consent_scripts': {'th':'ยังไม่ได้รับอนุญาตรันสคริปต์','en':'Custom script permission not granted.'},
    'need_consent_edit': {'th':'ยังไม่ได้รับอนุญาตแก้ไข rootfs','en':'RootFS edit permission not granted.'},
    'need_consent_external': {'th':'ยังไม่ได้อนุญาตใช้เครื่องมือภายนอก','en':'External tools permission not granted.'},
    'act_reset_consent': {'th':'รีเซ็ตการยืนยันสิทธิ์','en':'Reset Consent'},
    # Desktop integration
    'desktop_title': {'th':'ติดตั้งช็อตคัตเดสก์ท็อป','en':'Desktop Shortcut Install'},
    'desktop_install_prompt': {'th':'ต้องการสร้างช็อตคัตในเมนู/เดสก์ท็อปและติดตั้งไอคอนอัตโนมัติหรือไม่? (ทำครั้งเดียว)','en':'Do you want to install the application shortcut (desktop menu entry) and icon now? (one-time)'},
    'desktop_install_done': {'th':'ติดตั้งช็อตคัตและไอคอนเรียบร้อย','en':'Desktop shortcut and icon installed.'},
    'desktop_install_fail': {'th':'ติดตั้งช็อตคัตไม่สำเร็จ ดู log','en':'Failed to install desktop shortcut, see log.'},
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
        self.setWindowTitle(_("consent_title"))
        self.resize(650, 420)
        lay = QVBoxLayout(self)
        intro = QLabel(_("consent_intro"))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.cb_patch = QCheckBox(_("consent_patch")); self.cb_patch.setChecked(True)
        self.cb_external = QCheckBox(_("consent_external")); self.cb_external.setChecked(True)
        self.cb_scripts = QCheckBox(_("consent_scripts")); self.cb_scripts.setChecked(False)
        self.cb_edit = QCheckBox(_("consent_edit")); self.cb_edit.setChecked(True)
        for cb in [self.cb_patch,self.cb_external,self.cb_scripts,self.cb_edit]:
            lay.addWidget(cb)
        lay.addStretch()
        btns = QHBoxLayout(); btns.addStretch()
        b_ok = QPushButton(_("consent_save")); b_cancel = QPushButton(_("consent_cancel"))
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
            'timestamp': datetime.datetime.utcnow().isoformat()+"Z"
        }
from passlib.hash import sha512_crypt

def sha256sum(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def md5sum(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024*1024)
            if not b: break
            h.update(b)
    return h.hexdigest()

def get_filetype(fpath):
    try:
        return subprocess.check_output(["file", "-b", fpath], text=True).strip()
    except Exception as e:
        return f"file error: {e}"

def get_entropy(fw_path, sample_size=65536, samples=4):
    import math, random
    res = []
    filesize = os.path.getsize(fw_path)
    with open(fw_path, "rb") as f:
        for _ in range(samples):
            if filesize > sample_size:
                offset = random.randint(0, filesize - sample_size)
                f.seek(offset)
            else:
                f.seek(0)
            b = f.read(sample_size)
            if not b: break
            freq = [0]*256
            for x in b: freq[x] += 1
            e = -sum((c/len(b))*math.log2(c/len(b)) for c in freq if c)
            res.append(round(e, 3))
    if not res: return "-"
    return f"min={min(res):.3f}, max={max(res):.3f}, avg={sum(res)/len(res):.3f}"

def scan_all_rootfs_partitions(fw_path, log_func=print):
    FS_SIGNATURES = [
        (b'hsqs', "squashfs"),
        (b'sqsh', "squashfs"),
        (b'CrAm', "cramfs"),
        (b'UBI#', "ubi"),
        (b'UBI!', "ubi"),
        (b'F2FS', "f2fs"),
        (b'JFFS', "jffs2"),
    ]
    results = []
    with open(fw_path, "rb") as f:
        data = f.read()
        for sig, name in FS_SIGNATURES:
            idx = 0
            while True:
                idx = data.find(sig, idx)
                if idx == -1: break
                results.append((name, sig, idx))
                idx += 1
    if results:
        parts = []
        sorted_results = sorted(results, key=lambda x: x[2])
        for i, (fs_name, sig, offset) in enumerate(sorted_results):
            next_offset = len(data)
            if i + 1 < len(sorted_results):
                next_offset = sorted_results[i + 1][2]
            size = next_offset - offset
            parts.append(dict(fs=fs_name, offset=offset, size=size, sig=sig.hex()))
        # Build display list separately to avoid nested quote issues
        display_parts = [f"{p['fs']}@0x{p['offset']:X}" for p in parts]
        log_func(f"พบ rootfs {len(parts)} ชุด: {display_parts}")
        return parts
    # Fallback: try binwalk if installed
    bw = shutil.which("binwalk")
    if not bw:
        log_func("ไม่พบ FS signatures และไม่มี binwalk ติดตั้ง -> ติดตั้ง binwalk เพื่อ improve detection (pip install binwalk3)")
        return []
    try:
        out = subprocess.check_output([bw, '--term', '--signature', '--raw-bytes=4', fw_path], text=True, stderr=subprocess.STDOUT)
    except Exception as e:
        log_func(f"binwalk error: {e}")
        return []
    # Simple parse: lines with known FS keywords & offset at start
    lines = out.splitlines()
    found = []
    for line in lines:
        line = line.strip()
        # Format: offset   description
        if not line or not line[0].isdigit():
            continue
        parts_line = line.split(None, 1)
        if len(parts_line) < 2:
            continue
        try:
            off = int(parts_line[0])
        except ValueError:
            continue
        desc = parts_line[1].lower()
        for key, mapped in [("squashfs", "squashfs"), ("cramfs", "cramfs"), ("jffs2", "jffs2"), ("ubifs", "ubi"), ("ubi volume", "ubi")]:
            if key in desc:
                found.append((mapped, off, desc))
                break
    if not found:
        log_func("binwalk fallback ยังไม่พบ rootfs")
        return []
    # Build partition list: assume until next offset or EOF
    with open(fw_path, 'rb') as f:
        size_fw = len(f.read())
    found_sorted = sorted(found, key=lambda x: x[1])
    parts = []
    for i, (fs_name, offset, desc) in enumerate(found_sorted):
        next_offset = size_fw
        if i + 1 < len(found_sorted):
            next_offset = found_sorted[i+1][1]
        part_size = next_offset - offset
        parts.append(dict(fs=fs_name, offset=offset, size=part_size, sig='bw', note=desc[:60]))
    display_parts = [f"{p['fs']}@0x{p['offset']:X}" for p in parts]
    log_func(f"(binwalk) พบ rootfs {len(parts)} ชุด: {display_parts}")
    return parts

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
        try:
            subprocess.check_output(["unsquashfs", "-d", extract_dir, rootfs_bin],
                                   stderr=subprocess.STDOUT, timeout=30)
            return True, ""
        except Exception as e:
            log_func(f"unsquashfs error: {e}; จะลอง binwalk fallback")
            # fallthrough to binwalk fallback later
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
    bw = shutil.which("binwalk")
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

def repack_rootfs(fs_type, unsquashfs_dir, rootfs_bin_out, log_func):
    fs_type = _normalize_fs(fs_type)
    if fs_type == "squashfs":
        mksquashfs = shutil.which("mksquashfs")
        if not mksquashfs:
            return False, "mksquashfs tool not found"
        try:
            subprocess.check_output(
                [mksquashfs, unsquashfs_dir, rootfs_bin_out, "-noappend", "-comp", "gzip"],
                stderr=subprocess.STDOUT, timeout=60
            )
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

def patch_rootfs_shell_serial(fw_path, rootfs_part, out_path, log_func):
    # เพิ่ม getty ttyS0 ให้ inittab
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
        unsquashfs_dir = os.path.join(tmpdir, "unsquashfs")
        os.makedirs(unsquashfs_dir)
        ok, err = extract_rootfs(rootfs_part['fs'], rootfs_bin, unsquashfs_dir, log_func)
        if not ok:
            log_func(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
            return False, err
        inittab_path = os.path.join(unsquashfs_dir, "etc", "inittab")
        if os.path.exists(inittab_path):
            with open(inittab_path, "a", encoding="utf-8") as f:
                f.write("\nS0:12345:respawn:/sbin/getty -L ttyS0 115200 vt100\n")
            log_func("เพิ่ม getty ttyS0 ใน inittab สำเร็จ")
        else:
            log_func("ไม่พบ /etc/inittab ใน rootfs")
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
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1300, 950)
        # state
        self.fw_path = None
        self.rootfs_parts = []
        self.analysis_result = None
        self.rootfs_reports = []
        self.output_dir = os.path.abspath("output"); os.makedirs(self.output_dir, exist_ok=True)
        # central layout
        central = QWidget(); main_v = QVBoxLayout(central)
        # output folder
        out_h = QHBoxLayout(); out_h.addWidget(QLabel("Output:" if LANG=='en' else 'Output:'))
        self.output_edit = QLineEdit(self.output_dir); out_h.addWidget(self.output_edit)
        btn_out = QPushButton("Browse"); btn_out.clicked.connect(self.select_output_folder); out_h.addWidget(btn_out); main_v.addLayout(out_h)
        # firmware select
        fw_h = QHBoxLayout(); fw_h.addWidget(QLabel("Firmware:" if LANG=='en' else 'Firmware:'))
        self.fw_line = QLineEdit(); self.fw_line.setPlaceholderText("Select firmware" if LANG=='en' else "เลือก firmware"); fw_h.addWidget(self.fw_line)
        btn_fw = QPushButton("Open" if LANG=='en' else "เลือกไฟล์ Firmware"); btn_fw.clicked.connect(self.select_firmware); fw_h.addWidget(btn_fw); main_v.addLayout(fw_h)
        # rootfs scan / entropy
        scan_h = QHBoxLayout(); scan_h.addWidget(QLabel("RootFS Index:" if LANG=='en' else 'RootFS Index:'))
        self.rootfs_part_spin = QSpinBox(); self.rootfs_part_spin.setRange(1, 32); scan_h.addWidget(self.rootfs_part_spin)
        btn_scan = QPushButton("Scan All RootFS" if LANG=='en' else "Scan RootFS ทั้งหมด"); btn_scan.clicked.connect(self.auto_detect_rootfs); scan_h.addWidget(btn_scan); scan_h.addStretch(); main_v.addLayout(scan_h)
        ent_h = QHBoxLayout(); ent_h.addWidget(QLabel("Entropy samples" if LANG=='en' else 'Entropy samples'))
        self.entropy_samples_spin = QSpinBox(); self.entropy_samples_spin.setRange(1,32); self.entropy_samples_spin.setValue(4); ent_h.addWidget(self.entropy_samples_spin)
        ent_h.addWidget(QLabel("size KB")); self.entropy_size_spin = QSpinBox(); self.entropy_size_spin.setRange(1,1024); self.entropy_size_spin.setValue(64); ent_h.addWidget(self.entropy_size_spin); ent_h.addStretch(); main_v.addLayout(ent_h)
        # patch controls
        boot_h = QHBoxLayout(); boot_h.addWidget(QLabel("Boot Delay:" if LANG=='en' else 'Boot Delay:')); self.delay_combo = QComboBox(); self.delay_combo.addItems([str(i) for i in range(10)]); boot_h.addWidget(self.delay_combo)
        btn_boot = QPushButton("Patch Boot Delay" if LANG=='en' else "Patch Boot Delay"); btn_boot.clicked.connect(self.do_patch_boot_delay); boot_h.addWidget(btn_boot); boot_h.addStretch(); main_v.addLayout(boot_h)
        patch_h = QHBoxLayout();
        b_serial = QPushButton("Patch Serial Shell" if LANG=='en' else "Patch Serial Shell"); b_serial.clicked.connect(self.do_patch_serial); patch_h.addWidget(b_serial)
        b_net = QPushButton("Patch Network (Telnet/FTP)" if LANG=='en' else "Patch Network (Telnet/FTP)"); b_net.clicked.connect(self.do_patch_network); patch_h.addWidget(b_net)
        b_all = QPushButton("Patch All" if LANG=='en' else "Patch All"); b_all.clicked.connect(self.do_patch_all); patch_h.addWidget(b_all); patch_h.addStretch(); main_v.addLayout(patch_h)
        pw_h = QHBoxLayout(); pw_h.addWidget(QLabel("Root Password (blank=none)" if LANG=='en' else "Root Password (เว้นว่าง=lock/root no pass)")); self.rootpw_edit = QLineEdit(); self.rootpw_edit.setEchoMode(QLineEdit.Password); pw_h.addWidget(self.rootpw_edit)
        btn_pw = QPushButton("Patch Root Password" if LANG=='en' else "Patch Root Password"); btn_pw.clicked.connect(self.do_patch_rootpw); pw_h.addWidget(btn_pw); main_v.addLayout(pw_h)
        # AI & Security group
        sec_grp = QGroupBox("AI & Security Tools" if LANG=='en' else "AI & Security Tools"); sec_l = QVBoxLayout(sec_grp)
        ai_btn_row = QHBoxLayout()
        self.btn_ai_analyze = QPushButton("AI Analyze" if LANG=='en' else "AI วิเคราะห์ความปลอดภัย"); self.btn_ai_analyze.clicked.connect(self.ai_analyze_all); ai_btn_row.addWidget(self.btn_ai_analyze)
        self.btn_ai_patch_suggest = QPushButton("Suggest Patches" if LANG=='en' else "แนะนำ Patch อัตโนมัติ"); self.btn_ai_patch_suggest.clicked.connect(self.ai_patch_suggestion); ai_btn_row.addWidget(self.btn_ai_patch_suggest)
        self.btn_ai_apply_fixes = QPushButton("Apply Fixes" if LANG=='en' else "Apply Fixes"); self.btn_ai_apply_fixes.clicked.connect(self.ai_apply_fixes); ai_btn_row.addWidget(self.btn_ai_apply_fixes)
        sec_l.addLayout(ai_btn_row)
        self.btn_ai_findings = QPushButton("AI Findings" if LANG=='en' else "สรุปข้อควรระวัง (AI)"); self.btn_ai_findings.clicked.connect(self.show_ai_findings); sec_l.addWidget(self.btn_ai_findings)
        main_v.addWidget(sec_grp)
        # tabs
        self.tabs = QTabWidget(); self.log_view = QTextEdit(); self.log_view.setReadOnly(True); self.info_view = QTextEdit(); self.info_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, "Log"); self.tabs.addTab(self.info_view, "RootFS Info")
        # future features panel widget
        fut = QWidget(); fut_l = QVBoxLayout(fut)
        for text, slot in [
            ("Scan Vulnerabilities", self.scan_vulnerabilities),
            ("Scan Backdoor/Webshell", self.scan_backdoor),
            ("Diff Executables", self.diff_executables),
            ("Selective Patch", self.patch_selective),
            ("Edit RootFS File", self.edit_rootfs_file),
            ("Run Custom Script", self.run_custom_script),
            ("Check Hash/Signature", self.check_hash_signature),
            ("Export Patch Profile", self.export_patch_profile),
            ("Import Patch Profile", self.import_patch_profile),
        ]:
            b = QPushButton(text); b.clicked.connect(slot); fut_l.addWidget(b)
        fut_l.addStretch(); self.tabs.addTab(fut, "Future")
        main_v.addWidget(self.tabs, 1)
        # special window button + clear logs
        util_h = QHBoxLayout(); btn_special = QPushButton("Special Window" if LANG=='en' else "Special Functions Window"); btn_special.clicked.connect(self.open_special_functions_window); util_h.addWidget(btn_special)
        btn_clear = QPushButton("Clear Logs" if LANG=='en' else "Clear Logs"); btn_clear.clicked.connect(self.clear_logs); util_h.addWidget(btn_clear); util_h.addStretch(); main_v.addLayout(util_h)
        self.setCentralWidget(central)
        # status bar / menus
        self.status = QStatusBar(); self.setStatusBar(self.status); self._create_menus(); self.update_status()
        # consent
        self.consent = load_consent()
        if not self.consent.get('accepted'):
            dlg = ConsentDialog(self)
            if dlg.exec() != QDialog.Accepted:
                # user cancelled -> exit
                QTimer.singleShot(10, self.close)
            else:
                self.consent = dlg.get_result(); save_consent(self.consent); self.log("[CONSENT] saved")
        # After consent, offer desktop shortcut installation once
        if self.consent.get('accepted') and not self.consent.get('desktop_installed'):
            try:
                if QMessageBox.question(self, _("desktop_title"), _("desktop_install_prompt"), QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                    if self._install_desktop_shortcut():
                        QMessageBox.information(self, _("desktop_title"), _("desktop_install_done"))
                        self.consent['desktop_installed'] = True; save_consent(self.consent)
                    else:
                        QMessageBox.warning(self, _("desktop_title"), _("desktop_install_fail"))
            except Exception as e:
                self.log(f"[desktop-install-error] {e}")
        try:
            self.check_external_tools()
        except Exception as e:
            self.log(f"ตรวจเครื่องมือภายนอกมีปัญหา: {e}")
        self.log("พร้อมใช้งาน UI (reconstructed)")

    # ---------- Utility / Logging ----------
    def log(self, text):
        self.log_view.append(text); self.log_view.ensureCursorVisible(); self.status.showMessage(text[:120])
    def info(self, text):
        self.info_view.append(text); self.info_view.ensureCursorVisible()
    def clear_logs(self):
        self.log_view.clear(); self.info_view.clear(); self.log("[LOG CLEARED]")
    def update_status(self):
        fw = os.path.basename(self.fw_path) if self.fw_path else "(no fw)"; self.status.showMessage(f"FW: {fw} | Parts: {len(self.rootfs_parts)} | Out: {self.output_dir}")

    # ---------- Menus ----------
    def _create_menus(self):
        mb = self.menuBar()
        # File
        m_file = mb.addMenu(_("menu_file")); a_fw = QAction(QIcon(ICON_PATH), _("act_open_fw"),self); a_fw.triggered.connect(self.select_firmware); m_file.addAction(a_fw)
        a_out = QAction(QIcon(ICON_PATH), _("act_set_output"),self); a_out.triggered.connect(self.select_output_folder); m_file.addAction(a_out); m_file.addSeparator(); m_file.addAction(QAction(QIcon(ICON_PATH), _("act_exit"),self,triggered=self.close))
        # Analysis
        m_an = mb.addMenu(_("menu_analysis"))
        for key,func in [('act_fw_info',self.show_fw_info),('act_scan_rootfs',self.auto_detect_rootfs),('act_ai_analyze',self.ai_analyze_all),('act_diff_exec',self.diff_executables),('act_hash_sig',self.check_hash_signature)]:
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
        # Language submenu
        lang_menu = m_tools.addMenu(_("menu_language"))
        act_th = QAction(QIcon(ICON_PATH), _("lang_th"), self, checkable=True)
        act_en = QAction(QIcon(ICON_PATH), _("lang_en"), self, checkable=True)
        act_th.setChecked(LANG=='th'); act_en.setChecked(LANG=='en')
        def _set_lang(code):
            global LANG
            LANG = code
            self.menuBar().clear(); self._create_menus(); self.setWindowTitle(_("app_title"))
        act_th.triggered.connect(lambda: _set_lang('th'))
        act_en.triggered.connect(lambda: _set_lang('en'))
        lang_menu.addAction(act_th); lang_menu.addAction(act_en)
        # Help
        m_help = mb.addMenu(_("menu_help")); m_help.addAction(QAction(QIcon(ICON_PATH), _("act_about"),self,triggered=lambda: QMessageBox.information(self,_("act_about"),"Firmware Toolkit bY yak")))

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
            self.log("⚠️ Missing tools: " + ", ".join(missing))
        else:
            self.log("✅ External tools OK")

    # ---------- Basic actions ----------
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ Output", self.output_dir)
        if folder:
            self.output_dir = folder; self.output_edit.setText(folder); os.makedirs(folder, exist_ok=True); self.update_status()
    def select_firmware(self):
        file, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์เฟิร์มแวร์")
        if file:
            self.fw_path = file; self.fw_line.setText(file); self.log(f"เลือกไฟล์: {file}"); self.update_status()
    def auto_detect_rootfs(self):
        if not self.fw_path:
            QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์","เลือก firmware ก่อน"); return
        self.rootfs_parts = scan_all_rootfs_partitions(self.fw_path, log_func=self.log)
        if self.rootfs_parts:
            self.rootfs_part_spin.setMaximum(len(self.rootfs_parts)); self.log(f"พบ rootfs {len(self.rootfs_parts)} ส่วน")
        else:
            self.rootfs_part_spin.setMaximum(1); self.log("ไม่พบ rootfs")
        self.update_status()
    def get_selected_rootfs_part(self):
        if not self.rootfs_parts:
            self.auto_detect_rootfs()
        idx = self.rootfs_part_spin.value()-1
        if idx<0 or idx>=len(self.rootfs_parts):
            raise ValueError("index ผิดพลาด")
        return self.rootfs_parts[idx]

    # ---------- Patch operations ----------
    def do_patch_boot_delay(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        out = os.path.join(self.output_dir,f"patched_bootdelay_{os.path.basename(self.fw_path)}")
        patch_boot_delay(self.fw_path,None,int(self.delay_combo.currentText()),out,self.log)
        QMessageBox.information(self,"Boot Delay",f"เสร็จสิ้น: {out}")
    def do_patch_serial(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part()
        out = os.path.join(self.output_dir,f"patched_serial_{os.path.basename(self.fw_path)}")
        patch_rootfs_shell_serial(self.fw_path,part,out,self.log)
        QMessageBox.information(self,"Serial",f"เสร็จสิ้น: {out}")
    def do_patch_network(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part()
        out = os.path.join(self.output_dir,f"patched_network_{os.path.basename(self.fw_path)}")
        patch_rootfs_network(self.fw_path,part,out,self.log)
        QMessageBox.information(self,"Network",f"เสร็จสิ้น: {out}")
    def do_patch_all(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part()
        tmp = os.path.join(self.output_dir,"_tmp_all.bin")
        final = os.path.join(self.output_dir,f"patched_all_{os.path.basename(self.fw_path)}")
        patch_rootfs_shell_serial(self.fw_path,part,tmp,self.log)
        patch_rootfs_network(tmp,part,final,self.log)
        try:
            os.remove(tmp)
        except Exception:
            pass
        QMessageBox.information(self,"Patch All",f"เสร็จสิ้น: {final}")
    def do_patch_rootpw(self):
        if not self.fw_path:
            QMessageBox.warning(self,"เลือกไฟล์ก่อน",""); return
        if not self.require('patch','need_consent_patch'): return
        part = self.get_selected_rootfs_part()
        pw = self.rootpw_edit.text()
        out = os.path.join(self.output_dir,f"patched_rootpw_{os.path.basename(self.fw_path)}")
        patch_root_password(self.fw_path,part,pw,out,self.log)
        QMessageBox.information(self,"Root Password",f"เสร็จสิ้น: {out}")

    # ---------- Info / Analysis ----------
    def show_fw_info(self):
        if not self.fw_path: QMessageBox.warning(self,"ยังไม่ได้เลือกไฟล์","เลือก firmware ก่อน"); return
        self.info_view.clear(); self.info(f"*** Firmware Info ***\n{self.fw_path}\n")
        try:
            s=os.stat(self.fw_path); self.info(f"Size: {s.st_size} bytes\nSHA256: {sha256sum(self.fw_path)}\nMD5: {md5sum(self.fw_path)}\n")
            self.info(f"Filetype: {get_filetype(self.fw_path)}\n")
            self.info(f"Entropy: {get_entropy(self.fw_path, sample_size=self.entropy_size_spin.value()*1024, samples=self.entropy_samples_spin.value())}\n")
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
        findings, reports = self.analyze_all_rootfs_firmware(self.fw_path, log_func=self.log, output_dir=self.output_dir)
        self.analysis_result = findings; self.rootfs_reports = reports
        for line in findings: self.log(line)
        self.log("==== จบการวิเคราะห์ ====")
        QMessageBox.information(self,"AI วิเคราะห์", f"เสร็จสิ้น rootfs={len(reports)}")
    def analyze_all_rootfs_firmware(self, fw_path, log_func, output_dir):
        findings=[]; reports=[]; tmpdir=tempfile.mkdtemp(prefix="ai-fw-rootfs-"); log_func(f"[TEMP] ai analysis workspace: {tmpdir}")
        try:
            parts=scan_all_rootfs_partitions(fw_path, log_func=log_func)
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
                    for critical in ["etc/passwd","etc/shadow","etc/inittab","etc/inetd.conf"]:
                        fp=os.path.join(extract_dir,critical)
                        if os.path.exists(fp):
                            findings.append(f"พบ {critical}")
                        else:
                            findings.append(f"ไม่พบ {critical}")
                else:
                    findings.append(f"❌ แตก rootfs ไม่สำเร็จ: {err}")
                ts=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                outname=os.path.join(output_dir,f"ai_rootfs{idx+1}_{part['fs']}_0x{part['offset']:X}_{ts}.txt")
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
                out=os.path.join(self.output_dir,f"_tmp_boot_{ts}.bin"); ok,_=patch_boot_delay(current,None,actions['boot_delay_value'],out,self.log); current=out; temps.append(out); applied.append(f"BootDelay={actions['boot_delay_value']}")
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
        if not self.require('edit','need_consent_edit'): return
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
            QMessageBox.warning(self,"Run Script","เลือกไฟล์ก่อน"); return
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
        profile={"version":1,"created":datetime.datetime.utcnow().isoformat()+"Z","firmware_hint":os.path.basename(self.fw_path),"patches":actions}
        default=os.path.join(self.output_dir,f"patch_profile_{int(_t.time())}.json"); path,_=QFileDialog.getSaveFileName(self,"บันทึก Patch Profile",default,"JSON (*.json)")
        if not path: return
        with open(path,'w',encoding='utf-8') as f: json.dump(profile,f,ensure_ascii=False,indent=2)
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
                out=os.path.join(self.output_dir,f"_tmp_prof_boot_{ts}.bin"); patch_boot_delay(current,None,patches['boot_delay_value'],out,self.log); temps.append(out); current=out
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
    # ---------- Special window ----------
    def open_special_functions_window(self):
        if hasattr(self,'special_win') and self.special_win:
            self.special_win.raise_(); self.special_win.activateWindow(); return
        self.special_win=SpecialFunctionsWindow(self); self.special_win.show()
    # ---------- Demo placeholders ----------
    def scan_vulnerabilities(self): QMessageBox.information(self,"Vuln Scan","[DEMO]")
    def scan_backdoor(self): QMessageBox.information(self,"Backdoor Scan","[DEMO]")

    def patch_selective(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        dlg = SelectivePatchDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        actions = dlg.get_actions()
        if not actions:
            QMessageBox.information(self, "Selective Patch", "ไม่ได้เลือก patch ใดๆ")
            return
        try:
            rootfs_part = self.get_selected_rootfs_part()
        except Exception as e:
            QMessageBox.critical(self, "Selective Patch", f"ผิดพลาดเลือก rootfs: {e}")
            return
        ts = int(time.time())
        final_out = os.path.join(self.output_dir, f"selective_patch_{ts}.bin")
        current_fw = self.fw_path
        temp_files = []
        applied = []
        try:
            if actions.get('boot_delay'):
                out1 = os.path.join(self.output_dir, f"_tmp_boot_{ts}.bin")
                ok, msg = patch_boot_delay(current_fw, rootfs_part, actions['boot_delay_value'], out1, self.log)
                if not ok:
                    QMessageBox.critical(self, "Selective Patch", f"Boot delay ล้มเหลว: {msg}")
                    return
                current_fw = out1; temp_files.append(out1); applied.append(f"BootDelay={actions['boot_delay_value']}")
            if actions.get('serial_shell'):
                out2 = os.path.join(self.output_dir, f"_tmp_serial_{ts}.bin")
                ok, msg = patch_rootfs_shell_serial(current_fw, rootfs_part, out2, self.log)
                if not ok:
                    QMessageBox.critical(self, "Selective Patch", f"Serial shell ล้มเหลว: {msg}")
                    return
                current_fw = out2; temp_files.append(out2); applied.append("SerialShell")
            if actions.get('network_services'):
                out3 = os.path.join(self.output_dir, f"_tmp_net_{ts}.bin")
                ok, msg = patch_rootfs_network(current_fw, rootfs_part, out3, self.log)
                if not ok:
                    QMessageBox.critical(self, "Selective Patch", f"Network patch ล้มเหลว: {msg}")
                    return
                current_fw = out3; temp_files.append(out3); applied.append("DisableTelnet/FTP")
            if actions.get('root_password'):
                out4 = os.path.join(self.output_dir, f"_tmp_rootpw_{ts}.bin")
                ok, msg = patch_root_password(current_fw, rootfs_part, actions['root_password_value'], out4, self.log)
                if not ok:
                    QMessageBox.critical(self, "Selective Patch", f"Root password patch ล้มเหลว: {msg}")
                    return
                current_fw = out4; temp_files.append(out4); applied.append("RootPassword")
            shutil.copyfile(current_fw, final_out)
            self.log(f"✅ Selective Patch สำเร็จ -> {final_out}")
            QMessageBox.information(self, "Selective Patch", f"สำเร็จ: {final_out}\nรวม: {', '.join(applied)}")
        finally:
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass


    def edit_rootfs_file(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        try:
            rootfs_part = self.get_selected_rootfs_part()
        except Exception as e:
            QMessageBox.critical(self, "RootFS", f"เลือก rootfs ไม่ได้: {e}")
            return
        # สร้าง/ใช้แคชการแตก rootfs (ลดเวลาทำซ้ำ)
        if not hasattr(self, 'edit_cache_dir'):
            self.edit_cache_dir = None
            self.edit_cache_part_index = None
        part_index = self.rootfs_part_spin.value() - 1
        need_extract = True
        if self.edit_cache_dir and os.path.isdir(self.edit_cache_dir) and self.edit_cache_part_index == part_index:
            # ตรวจสอบว่ามีไฟล์บางอย่างอยู่ เพื่อยืนยัน
            if os.listdir(self.edit_cache_dir):
                need_extract = False
        if need_extract:
            # แตกใหม่
            tmp_work = tempfile.mkdtemp(prefix="edit_rootfs_")
            rootfs_bin = os.path.join(tmp_work, "rootfs.bin")
            with open(self.fw_path, "rb") as f:
                f.seek(rootfs_part['offset'])
                data = f.read(rootfs_part['size'])
            with open(rootfs_bin, "wb") as fo:
                fo.write(data)
            extract_dir = os.path.join(tmp_work, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            ok, err = extract_rootfs(rootfs_part['fs'], rootfs_bin, extract_dir, self.log)
            if not ok:
                shutil.rmtree(tmp_work, ignore_errors=True)
                QMessageBox.critical(self, "RootFS", f"แตก rootfs ไม่สำเร็จ: {err}")
                return
            # เก็บไว้เป็นแคช
            # ลบของเก่า (ถ้ามี) เพื่อไม่ให้กินพื้นที่
            if self.edit_cache_dir and os.path.exists(self.edit_cache_dir):
                try: shutil.rmtree(self.edit_cache_dir)
                except Exception: pass
            self.edit_cache_dir = extract_dir
            self.edit_cache_workspace = tmp_work  # เก็บ tmp base เพื่อ cleanup ตอนปิดโปรแกรมได้
            self.edit_cache_part_index = part_index
            self.log(f"📦 แตก rootfs สำหรับแก้ไข -> {extract_dir}")
        dlg = RootFSEditDialog(self, self.edit_cache_dir, rootfs_part, self.fw_path, self.output_dir)
        dlg.exec()

    def run_custom_script(self):
        if not self.fw_path:
            QMessageBox.warning(self, "Run Custom Script", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        try:
            part = self.get_selected_rootfs_part()
        except Exception:
            QMessageBox.warning(self, "Run Custom Script", "ยังไม่ได้ scan rootfs หรือ index ไม่ถูกต้อง")
            return
        dlg = CustomScriptDialog(self, part)
        dlg.exec()

    def check_hash_signature(self):
        if not self.fw_path:
            QMessageBox.warning(self, "Hash/Signature", "ยังไม่ได้เลือกไฟล์ firmware")
            return
        # Compute hashes of firmware and (if selected) extracted rootfs partition
        try:
            fw_sha256 = sha256sum(self.fw_path)
            fw_md5 = md5sum(self.fw_path)
        except Exception as e:
            QMessageBox.critical(self, "Hash", f"อ่านไฟล์ firmware ไม่ได้: {e}")
            return
        details = [f"Firmware: {os.path.basename(self.fw_path)}", f"SHA256: {fw_sha256}", f"MD5: {fw_md5}"]
        # If rootfs parts already scanned, show per-part quick hash (segment slice)
        if self.rootfs_parts:
            details.append("\n[RootFS Partitions Slice Hash (first 64KB)]")
            try:
                with open(self.fw_path, 'rb') as f:
                    for i,p in enumerate(self.rootfs_parts,1):
                        f.seek(p['offset'])
                        segment = f.read(min(65536, p['size']))
                        h = hashlib.sha256(segment).hexdigest()[:16]
                        details.append(f"Part{i} {p['fs']} @0x{p['offset']:X} size=0x{p['size']:X} slice_sha25616={h}")
            except Exception as e:
                details.append(f"(อ่าน rootfs slice ล้มเหลว: {e})")
        # If a cached extracted rootfs exists (from edit), hash a few critical files
        critical = ['etc/passwd','etc/shadow','etc/inittab','etc/rc.local','etc/banner','bin/busybox','sbin/init']
        if getattr(self, 'edit_cache_dir', None) and os.path.isdir(self.edit_cache_dir):
            details.append("\n[Critical File Hashes]")
            for rel in critical:
                fp = os.path.join(self.edit_cache_dir, rel)
                if os.path.exists(fp) and os.path.isfile(fp):
                    try:
                        details.append(f"{rel} sha256={sha256sum(fp)[:20]}")
                    except Exception as e:
                        details.append(f"{rel} error={e}")
                else:
                    details.append(f"{rel} (missing)")
        # Look for ASCII signature markers (simple heuristic)
        sig_markers = []
        try:
            with open(self.fw_path,'rb') as f:
                blob = f.read()
            for marker in [b'-----BEGIN CERTIFICATE-----', b'-----BEGIN PUBLIC KEY-----', b'OPENSSL', b'RSA PUBLIC KEY']:
                if marker in blob:
                    sig_markers.append(marker.decode('latin1'))
        except Exception:
            pass
        if sig_markers:
            details.append("\n[Plausible Embedded Signature/Key Markers]")
            details += [f"- {m}" for m in sig_markers]
        # Show dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Hash & Signature Report")
        v = QVBoxLayout(dlg)
        te = QTextEdit(); te.setReadOnly(True); te.setText("\n".join(details))
        v.addWidget(te)
        btn = QPushButton("ปิด")
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        dlg.resize(700,600)
        dlg.exec()

    def export_patch_profile(self):
        # Let user choose patches similar to selective patch dialog, then write JSON profile
        if not self.fw_path:
            QMessageBox.warning(self, "Export Patch Profile", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        dlg = SelectivePatchDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        actions = dlg.get_actions()
        if not actions:
            QMessageBox.information(self, "Export Patch Profile", "ไม่ได้เลือก patch ใดๆ")
            return
        profile = {
            "version": 1,
            "created": datetime.datetime.utcnow().isoformat()+"Z",
            "firmware_hint": os.path.basename(self.fw_path),
            "patches": {
                "boot_delay": {
                    "enabled": bool(actions.get('boot_delay')),
                    "value": actions.get('boot_delay_value') if actions.get('boot_delay') else None
                },
                "serial_shell": {"enabled": bool(actions.get('serial_shell'))},
                "network_services": {"enabled": bool(actions.get('network_services'))},
                "root_password": {
                    "enabled": bool(actions.get('root_password')),
                    # store plain only if user provided; else only store hash later when applied
                    "password_plain": actions.get('root_password_value') if actions.get('root_password') else None
                }
            }
        }
        # Ask location
        ts = int(time.time())
        default_name = os.path.join(self.output_dir, f"patch_profile_{ts}.json")
        out_path, _ = QFileDialog.getSaveFileName(self, "บันทึก Patch Profile", default_name, "JSON (*.json)")
        if not out_path:
            return
        try:
            import json
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            self.log(f"บันทึก Patch Profile -> {out_path}")
            QMessageBox.information(self, "Export Patch Profile", f"สำเร็จ: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Patch Profile", f"ล้มเหลว: {e}")

    def import_patch_profile(self):
        if not self.fw_path:
            QMessageBox.warning(self, "Import Patch Profile", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        file, _ = QFileDialog.getOpenFileName(self, "เลือก Patch Profile JSON", self.output_dir, "JSON (*.json)")
        if not file:
            return
        try:
            import json
            with open(file, 'r', encoding='utf-8') as f:
                profile = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Patch Profile", f"อ่านไฟล์ไม่สำเร็จ: {e}")
            return
        patches = profile.get('patches', {})
        summary = []
        if patches.get('boot_delay', {}).get('enabled'):
            summary.append(f"BootDelay->{patches['boot_delay'].get('value')}")
        if patches.get('serial_shell', {}).get('enabled'):
            summary.append("SerialShell")
        if patches.get('network_services', {}).get('enabled'):
            summary.append("DisableTelnet/FTP")
        if patches.get('root_password', {}).get('enabled'):
            pw_plain = patches['root_password'].get('password_plain')
            summary.append(f"RootPassword({'set' if pw_plain else 'hash_only/unknown'})")
        if not summary:
            QMessageBox.information(self, "Import Patch Profile", "ไฟล์นี้ไม่เปิดใช้ patch ใดๆ")
            return
        part = self.get_selected_rootfs_part()
        if not part:
            QMessageBox.warning(self, "Import Patch Profile", "ยังไม่ได้เลือก rootfs part")
            return
        if QMessageBox.question(self, "ยืนยันนำเข้า", "จะ apply patches: " + ", ".join(summary) + "\nดำเนินการต่อ?") != QMessageBox.Yes:
            return
        # Apply sequentially similar to selective patch
        ts = int(time.time())
        current_fw = self.fw_path
        temp_files = []
        applied = []
        try:
            if patches.get('boot_delay', {}).get('enabled'):
                val = int(patches['boot_delay'].get('value') or 1)
                out1 = os.path.join(self.output_dir, f"_tmp_prof_boot_{ts}.bin")
                ok, msg = patch_boot_delay(current_fw, part, val, out1, self.log)
                if not ok:
                    raise RuntimeError(f"BootDelay ล้มเหลว: {msg}")
                current_fw = out1; temp_files.append(out1); applied.append(f"BootDelay={val}")
            if patches.get('serial_shell', {}).get('enabled'):
                out2 = os.path.join(self.output_dir, f"_tmp_prof_serial_{ts}.bin")
                ok, msg = patch_rootfs_shell_serial(current_fw, part, out2, self.log)
                if not ok:
                    raise RuntimeError(f"SerialShell ล้มเหลว: {msg}")
                current_fw = out2; temp_files.append(out2); applied.append("SerialShell")
            if patches.get('network_services', {}).get('enabled'):
                out3 = os.path.join(self.output_dir, f"_tmp_prof_net_{ts}.bin")
                ok, msg = patch_rootfs_network(current_fw, part, out3, self.log)
                if not ok:
                    raise RuntimeError(f"Network patch ล้มเหลว: {msg}")
                current_fw = out3; temp_files.append(out3); applied.append("DisableTelnet/FTP")
            if patches.get('root_password', {}).get('enabled'):
                out4 = os.path.join(self.output_dir, f"_tmp_prof_rootpw_{ts}.bin")
                pw_plain = patches['root_password'].get('password_plain') or self.rootpw_edit.text().strip()
                if not pw_plain:
                    # final fallback locked account if not provided
                    pw_plain = "!"  # indicates lock
                ok, msg = patch_root_password(current_fw, part, pw_plain, out4, self.log)
                if not ok:
                    raise RuntimeError(f"Root password patch ล้มเหลว: {msg}")
                current_fw = out4; temp_files.append(out4); applied.append("RootPassword")
            final_out = os.path.join(self.output_dir, f"apply_profile_{ts}.bin")
            shutil.copyfile(current_fw, final_out)
            self.log(f"✅ Apply Patch Profile สำเร็จ -> {final_out}")
            QMessageBox.information(self, "Import Patch Profile", f"สำเร็จ: {final_out}\nรวม: {', '.join(applied)}")
        except Exception as e:
            QMessageBox.critical(self, "Import Patch Profile", f"ล้มเหลว: {e}")
        finally:
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass
    # (duplicate legacy __init__ removed)


    # --- Main logic functions ---

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ Output", self.output_dir)
        if folder:
            self.output_dir = folder
            self.output_edit.setText(folder)
            os.makedirs(self.output_dir, exist_ok=True)

    def log(self, text):
        self.log_view.append(text)
        self.log_view.ensureCursorVisible()
        # also mirror last line to status (shortened)
        if isinstance(text, str):
            self.status.showMessage(text[:120])

    def info(self, text):
        self.info_view.append(text)
        self.info_view.ensureCursorVisible()

    # ---------- ตรวจสอบ external tools ----------
    def check_external_tools(self):
        tools = [
            ("unsquashfs", "squashfs-tools"),
            ("cramfsck", "(Ubuntu ใหม่อาจไม่มี cramfsprogs แล้ว ถ้าไม่ใช้ cramfs ข้ามได้)"),
            ("jefferson", "pip install jefferson"),
            ("ubireader_extract_files", "pip install ubi_reader  หรือ  sudo apt install ubireader"),
            ("binwalk", "sudo apt install binwalk"),
        ]
        missing = []
        for tool, hint in tools:
            if not shutil.which(tool):
                missing.append((tool, hint))
        if missing:
            self.log("⚠️ ขาด external tools บางตัว จะใช้ binwalk fallback เท่าที่ทำได้:")
            for tool, hint in missing:
                self.log(f"   - {tool} (ติดตั้ง: {hint})")
        else:
            self.log("✅ พบ external tools หลักครบ (unsquashfs / jefferson / binwalk ฯลฯ)")
        self.update_status()

    def update_status(self):
        fw = os.path.basename(self.fw_path) if self.fw_path else "(no firmware)"
        parts = len(self.rootfs_parts) if getattr(self, 'rootfs_parts', None) else 0
        self.status.showMessage(f"FW: {fw} | RootFS parts: {parts} | Output: {self.output_dir}")

    def clear_logs(self):
        self.log_view.clear(); self.info_view.clear()
        self.log("[LOG] cleared")

    def select_firmware(self):
        file, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์เฟิร์มแวร์")
        if file:
            self.fw_path = file
            self.fw_line.setText(file)
            self.log(f"เลือกไฟล์: {file}")
            self.log(f"เลือกไฟล์: {file}")
            self.update_status()

    def auto_detect_rootfs(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        self.rootfs_parts = scan_all_rootfs_partitions(self.fw_path, log_func=self.log)
        if self.rootfs_parts:
            self.rootfs_part_spin.setMaximum(len(self.rootfs_parts))
            self.log(f"เลือก rootfs index: 1 - {len(self.rootfs_parts)} (แก้ไขได้ที่ช่อง RootFS Partition Index)")
            self.update_status()
        else:
            self.rootfs_part_spin.setMaximum(1)
            self.log("ไม่พบ rootfs ในไฟล์นี้")
            self.update_status()

    def get_selected_rootfs_part(self):
        idx = self.rootfs_part_spin.value() - 1
        if not self.rootfs_parts:
            self.rootfs_parts = scan_all_rootfs_partitions(self.fw_path, log_func=self.log)
        if idx < 0 or idx >= len(self.rootfs_parts):
            QMessageBox.warning(self, "Index rootfs ไม่ถูกต้อง", "กรุณากด Scan rootfs ก่อน และเลือก index ให้ถูกต้อง")
            return None
        return self.rootfs_parts[idx]

    def do_patch_boot_delay(self):
        if not self.fw_path:
            QMessageBox.warning(self, "โปรดเลือกไฟล์ firmware ก่อน")
            return
        out_path = os.path.join(self.output_dir, f"patched_bootdelay_{os.path.basename(self.fw_path)}")
        delay = int(self.delay_combo.currentText())
        patch_boot_delay(self.fw_path, None, delay, out_path, self.log)
        QMessageBox.information(self, "Patch Boot Delay", f"เสร็จสิ้น: {out_path}")

    def do_patch_serial(self):
        if not self.fw_path:
            QMessageBox.warning(self, "โปรดเลือกไฟล์ firmware ก่อน")
            return
        part = self.get_selected_rootfs_part()
        if not part: return
        out_path = os.path.join(self.output_dir, f"patched_serial_{os.path.basename(self.fw_path)}")
        patch_rootfs_shell_serial(self.fw_path, part, out_path, self.log)
        QMessageBox.information(self, "Patch Shell Serial", f"เสร็จสิ้น: {out_path}")

    def do_patch_network(self):
        if not self.fw_path:
            QMessageBox.warning(self, "โปรดเลือกไฟล์ firmware ก่อน")
            return
        part = self.get_selected_rootfs_part()
        if not part: return
        out_path = os.path.join(self.output_dir, f"patched_network_{os.path.basename(self.fw_path)}")
        patch_rootfs_network(self.fw_path, part, out_path, self.log)
        QMessageBox.information(self, "Patch Shell Network", f"เสร็จสิ้น: {out_path}")

    def do_patch_all(self):
        if not self.fw_path:
            QMessageBox.warning(self, "โปรดเลือกไฟล์ firmware ก่อน")
            return
        part = self.get_selected_rootfs_part()
        if not part: return
        tmp_path = os.path.join(self.output_dir, f"tmp_patch_all_{os.path.basename(self.fw_path)}")
        out_path = os.path.join(self.output_dir, f"patched_all_{os.path.basename(self.fw_path)}")
        self.log("[1/3] กำลัง patch serial shell ...")
        patch_rootfs_shell_serial(self.fw_path, part, tmp_path, self.log)
        self.log("[2/3] กำลัง patch network ...")
        patch_rootfs_network(tmp_path, part, out_path, self.log)
        try:
            os.remove(tmp_path)
        except: pass
        QMessageBox.information(self, "Patch รวม", f"เสร็จสิ้น: {out_path}")

    def do_patch_rootpw(self):
        if not self.fw_path:
            QMessageBox.warning(self, "โปรดเลือกไฟล์ firmware ก่อน")
            return
        part = self.get_selected_rootfs_part()
        if not part: return
        password = self.rootpw_edit.text()
        out_path = os.path.join(self.output_dir, f"patched_rootpw_{os.path.basename(self.fw_path)}")
        patch_root_password(self.fw_path, part, password, out_path, self.log)
        QMessageBox.information(self, "Patch Root Password", f"เสร็จสิ้น: {out_path}")

    def show_fw_info(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        self.info_view.clear()
        self.info(f"*** ข้อมูลไฟล์ Firmware ***\n{self.fw_path}\n")
        try:
            s = os.stat(self.fw_path)
            self.info(f"ขนาดไฟล์: {s.st_size} bytes\nSHA256: {sha256sum(self.fw_path)}\nMD5: {md5sum(self.fw_path)}\n")
        except Exception as e:
            self.info(f"stat error: {e}\n")
        try:
            self.info(f"ชนิดไฟล์: {get_filetype(self.fw_path)}\n")
        except Exception as e:
            self.info(f"filetype error: {e}\n")
        try:
            samples = self.entropy_samples_spin.value()
            sample_size = self.entropy_size_spin.value() * 1024
            self.info(f"Entropy (ตัวอย่าง): {get_entropy(self.fw_path, sample_size=sample_size, samples=samples)}\n")
        except Exception as e:
            self.info(f"entropy error: {e}\n")
        try:
            parts = scan_all_rootfs_partitions(self.fw_path, log_func=self.info)
            if parts:
                self.info("RootFS Table:")
                for i, p in enumerate(parts):
                    self.info(f"  [{i+1}] {p['fs']:10}  Offset=0x{p['offset']:07X}  Size=0x{p['size']:X}")
            else:
                self.info("ไม่พบ rootfs partition")
        except Exception as e:
            self.info(f"partition error: {e}\n")

    def ai_analyze_all(self):
        if not self.fw_path:
            QMessageBox.warning(self, "ยังไม่ได้เลือกไฟล์", "กรุณาเลือกไฟล์ firmware ก่อน")
            return
        self.log("=== เริ่ม AI วิเคราะห์ Firmware ทุก rootfs ===")
        self.info_view.clear()
        findings, txt_report_paths = self.analyze_all_rootfs_firmware(self.fw_path, log_func=self.log, output_dir=self.output_dir)
        # --- ตรวจสอบ Boot delay ---
        boot_delay = None
        try:
            with open(self.fw_path, "rb") as f:
                f.seek(0x100)
                b = f.read(1)
                if b:
                    boot_delay = int.from_bytes(b, 'little')
        except Exception as e:
            boot_delay = None
        if boot_delay is not None:
            findings.insert(0, f"Boot delay: {boot_delay} วินาที (offset 0x100)")
        else:
            findings.insert(0, "Boot delay: ไม่สามารถอ่านค่าได้ (offset 0x100)")
        self.analysis_result = findings
        self.rootfs_reports = txt_report_paths
        self.log("==== สรุปผลวิเคราะห์ ====")
        for line in findings:
            self.log(line)
        if txt_report_paths:
            self.info("สร้างรายงาน rootfs แยกไฟล์เรียบร้อย:")
            for path in txt_report_paths:
                self.info(path)
        self.log("==== จบการวิเคราะห์ AI ====")
        if txt_report_paths:
            QMessageBox.information(self, "AI วิเคราะห์สำเร็จ",
                f"เสร็จสิ้นการวิเคราะห์\nบันทึกไฟล์ผลวิเคราะห์ rootfs แยกไฟล์ ({len(txt_report_paths)}) ที่:\n" +
                "\n".join(txt_report_paths))
        else:
            QMessageBox.information(self, "AI วิเคราะห์สำเร็จ", "เสร็จสิ้นการวิเคราะห์ (ไม่มี rootfs)")

    # (legacy duplicated code removed)

class SpecialFunctionsWindow(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.setWindowTitle("Special Functions")
        self.resize(500, 600)
        lay = QVBoxLayout(self)
        title = QLabel("⚙️ Special Functions (แยกหน้าต่าง)")
        title.setStyleSheet("font-weight:bold;font-size:16px;")
        lay.addWidget(title)
        desc = QLabel("รวมปุ่มฟังก์ชันพิเศษ (เหมือน Future Features) แยกออกมาดูโล่ง ๆ")
        lay.addWidget(desc)
        # ปุ่มต่าง ๆ reuse methods จาก main window
        buttons = [
            ("Scan Vulnerabilities", main_win.scan_vulnerabilities),
            ("Scan Backdoor/Webshell", main_win.scan_backdoor),
            ("Diff Executables", main_win.diff_executables),
            ("Selective Patch", main_win.patch_selective),
            ("Edit RootFS File", main_win.edit_rootfs_file),
            ("Run Custom Script", main_win.run_custom_script),
            ("Check Hash/Signature", main_win.check_hash_signature),
            ("Export Patch Profile", main_win.export_patch_profile),
            ("Import Patch Profile", main_win.import_patch_profile),
        ]
        for text, slot in buttons:
            b = QPushButton(text)
            b.clicked.connect(slot)
            lay.addWidget(b)
        lay.addStretch()
        close_btn = QPushButton("ปิดหน้าต่างนี้")
        close_btn.clicked.connect(self.close)
        lay.addWidget(close_btn)


# ---------------- Dialog เลือก Patch -----------------
class SelectivePatchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("เลือกชุด Patch")
        self.setModal(True)
        lay = QVBoxLayout(self)
        self.cb_boot = QCheckBox("ปรับ Boot Delay -> 1")
        self.cb_serial = QCheckBox("เปิด Shell Debug ผ่าน Serial")
        self.cb_net = QCheckBox("ปิด Telnet / FTP (Shell Network)")
        self.cb_rootpw = QCheckBox("ตั้งรหัสผ่าน root (ใช้ค่าจากช่องด้านหลัก หรือ admin1234)")
        lay.addWidget(self.cb_boot)
        lay.addWidget(self.cb_serial)
        lay.addWidget(self.cb_net)
        lay.addWidget(self.cb_rootpw)
        # ปุ่ม OK / Cancel
        btns = QHBoxLayout()
        btn_ok = QPushButton("ตกลง")
        btn_cancel = QPushButton("ยกเลิก")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok); btns.addWidget(btn_cancel)
        lay.addLayout(btns)

    def get_actions(self):
        actions = {}
        if self.cb_boot.isChecked():
            actions['boot_delay'] = True
            actions['boot_delay_value'] = 1
        if self.cb_serial.isChecked():
            actions['serial_shell'] = True
        if self.cb_net.isChecked():
            actions['network_services'] = True
        if self.cb_rootpw.isChecked():
            actions['root_password'] = True
            # root password value จะถูกอ่านจากหน้าหลักตอน apply
            # แต่ถ้าผู้ใช้ไม่ได้ใส่ จะ fallback ใน patch_selective (ใช้ default เมื่อเรียก patch_root_password)
            actions['root_password_value'] = parent_pw = getattr(self.parent(), 'rootpw_edit', None)
            if isinstance(parent_pw, QLineEdit):
                val = parent_pw.text().strip()
                actions['root_password_value'] = val or "admin1234"
            else:
                actions['root_password_value'] = "admin1234"
        return actions

# --------------- Dialog แก้ไขไฟล์ใน RootFS -----------------
class RootFSEditDialog(QDialog):
    """Dialog for browsing and editing extracted rootfs files."""
    def __init__(self, parent, extract_dir, rootfs_part, fw_path, output_dir):
        super().__init__(parent)
        self.setWindowTitle("แก้ไขไฟล์ใน RootFS (Full Editor)")
        self.resize(1000, 600)
        self.extract_dir = extract_dir
        self.rootfs_part = rootfs_part
        self.fw_path = fw_path
        self.output_dir = output_dir
        self.parent_win = parent
        self.pending_changes = []  # track changes
        self._build_ui()
        self.load_tree()

    # ---------- UI Construction ----------
    def _build_ui(self):
        from PySide6.QtWidgets import QLineEdit as _QLE
        main_lay = QVBoxLayout(self)
        self.dir_label = QLabel(f"RootFS: {self.rootfs_part['fs']} @ 0x{self.rootfs_part['offset']:X} size=0x{self.rootfs_part['size']:X}\nExtract dir: {self.extract_dir}")
        self.dir_label.setStyleSheet("font-weight:bold;")
        main_lay.addWidget(self.dir_label)

        split = QSplitter()
        main_lay.addWidget(split, 1)

        # Left: file tree
        left_widget = QWidget(); left_lay = QVBoxLayout(left_widget); left_lay.setContentsMargins(0,0,0,0)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Path", "Size", "Perms"])
        self.tree.itemClicked.connect(self.on_tree_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_menu)
        left_lay.addWidget(self.tree, 1)
        refresh_row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_open_dir = QPushButton("เปิดในระบบ (xdg-open)")
        refresh_row.addWidget(btn_refresh); refresh_row.addWidget(btn_open_dir); refresh_row.addStretch()
        left_lay.addLayout(refresh_row)
        split.addWidget(left_widget)

        # Right: operations
        right_widget = QWidget(); rlay = QVBoxLayout(right_widget)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Internal path:"))
        self.internal_edit = _QLE(); self.internal_edit.setPlaceholderText("เช่น etc/banner หรือ usr/bin/app")
        path_row.addWidget(self.internal_edit)
        rlay.addLayout(path_row)

        btn_row1 = QHBoxLayout()
        self.btn_add = QPushButton("เพิ่ม/แทนที่ (Add/Replace)")
        self.btn_view = QPushButton("ดูไฟล์ (View)")
        self.btn_delete = QPushButton("ลบ (Delete)")
        btn_row1.addWidget(self.btn_add); btn_row1.addWidget(self.btn_view); btn_row1.addWidget(self.btn_delete)
        rlay.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_mkdir = QPushButton("สร้างโฟลเดอร์ (mkdir)")
        self.btn_export = QPushButton("Export ไฟล์ออก")
        self.btn_repack = QPushButton("Repack -> Firmware ใหม่")
        btn_row2.addWidget(self.btn_mkdir); btn_row2.addWidget(self.btn_export); btn_row2.addWidget(self.btn_repack)
        rlay.addLayout(btn_row2)

        self.log_view = QTextEdit(); self.log_view.setReadOnly(True)
        rlay.addWidget(self.log_view, 1)

        btn_close = QPushButton("ปิด")
        rlay.addWidget(btn_close)
        split.addWidget(right_widget)
        split.setStretchFactor(0,4); split.setStretchFactor(1,6)

        # Connect signals
        btn_close.clicked.connect(self.close)
        self.btn_add.clicked.connect(self.do_add_replace)
        self.btn_delete.clicked.connect(self.do_delete)
        self.btn_view.clicked.connect(self.do_view)
        self.btn_repack.clicked.connect(self.do_repack)
        self.btn_mkdir.clicked.connect(self.do_mkdir)
        self.btn_export.clicked.connect(self.do_export)
        btn_refresh.clicked.connect(self.load_tree)
        btn_open_dir.clicked.connect(self.open_in_file_manager)

    def _norm_internal(self):
        rel = self.internal_edit.text().strip().lstrip('/')
        if not rel:
            raise ValueError("ยังไม่ได้ระบุ internal path")
        if '..' in rel.split('/'):
            raise ValueError("ห้ามใช้ '..'")
        return rel

    # ---------- Tree Handling ----------
    def load_tree(self):
        self.tree.clear()
        base = self.extract_dir
        max_nodes = 5000
        max_depth = 12
        count = 0
        symlink_skipped = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            rel_root = os.path.relpath(root, base)
            if rel_root == '.':
                rel_root = ''
                depth = 0
            else:
                depth = rel_root.count('/') + 1
            # จำกัด depth
            if depth > max_depth:
                continue
            parent_item = None
            if rel_root:
                parent_item = self._ensure_path_item(rel_root)
            # จำกัดจำนวน
            for name in sorted(files):
                if count >= max_nodes:
                    break
                rel_path = os.path.join(rel_root, name) if rel_root else name
                full_path = os.path.join(base, rel_path)
                try:
                    if os.path.islink(full_path):
                        symlink_skipped += 1
                        # แสดงเป็นรายการแต่ size '-' และ perms 'link'
                        item = QTreeWidgetItem([rel_path, '-', 'link'])
                    else:
                        size = os.path.getsize(full_path)
                        try:
                            st = os.lstat(full_path)
                            perms = oct(st.st_mode & 0o777)
                        except Exception:
                            perms = '?'
                        item = QTreeWidgetItem([rel_path, str(size), perms])
                except (FileNotFoundError, OSError):
                    continue
                if parent_item:
                    parent_item.addChild(item)
                else:
                    self.tree.addTopLevelItem(item)
                count += 1
            if count >= max_nodes:
                break
        if count >= max_nodes:
            self.tree.addTopLevelItem(QTreeWidgetItem([f"[แสดงบางส่วน จำกัด {max_nodes} ไฟล์]", "", ""]))
        if symlink_skipped:
            self.tree.addTopLevelItem(QTreeWidgetItem([f"[ข้าม symlink {symlink_skipped} รายการ]", "", ""]))
        self.tree.sortItems(0, Qt.AscendingOrder)

    def _ensure_path_item(self, rel_root):
        # หา/สร้าง item สำหรับโฟลเดอร์ลึก ๆ
        parts = rel_root.split('/')
        path_accum = []
        parent = None
        for part in parts:
            path_accum.append(part)
            key = '/'.join(path_accum)
            parent = self._find_or_create_dir_item(parent, key, part)
        return parent

    def _find_or_create_dir_item(self, parent, key, label):
        container = self.tree if parent is None else parent
        for i in range(container.childCount() if parent else container.topLevelItemCount()):
            it = container.child(i) if parent else container.topLevelItem(i)
            if it.text(0) == key:
                return it
        new_item = QTreeWidgetItem([key, "", "dir"])
        if parent:
            parent.addChild(new_item)
        else:
            self.tree.addTopLevelItem(new_item)
        return new_item

    def on_tree_click(self, item):
        path_text = item.text(0)
        # ถ้าเป็นโฟลเดอร์ให้ไม่เติมอะไรเพิ่ม
        if path_text.startswith('[แสดงบางส่วน'): return
        if path_text:
            # ถ้าเป็น path ย่อย แสดงชื่อไฟล์เต็ม
            if os.path.isdir(os.path.join(self.extract_dir, path_text)):
                # directory
                self.internal_edit.setText(path_text)
            else:
                self.internal_edit.setText(path_text)

    def on_tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item: return
        path_text = item.text(0)
        if not path_text or path_text.startswith('[แสดงบางส่วน'): return
        menu = QMenu(self)
        act_view = menu.addAction("View")
        act_delete = menu.addAction("Delete")
        act_export = menu.addAction("Export")
        act = menu.exec(self.tree.mapToGlobal(pos))
        if act == act_view:
            self.internal_edit.setText(path_text); self.do_view()
        elif act == act_delete:
            self.internal_edit.setText(path_text); self.do_delete()
        elif act == act_export:
            self.internal_edit.setText(path_text); self.do_export()

    # ---------- Extra operations ----------
    def do_mkdir(self):
        try:
            rel = self._norm_internal()
        except Exception as e:
            QMessageBox.warning(self, "mkdir", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        try:
            os.makedirs(dst, exist_ok=True)
            self.log(f"mkdir: {rel}")
            self.load_tree()
        except Exception as e:
            QMessageBox.critical(self, "mkdir", f"ล้มเหลว: {e}")

    def do_export(self):
        try:
            rel = self._norm_internal()
        except Exception as e:
            QMessageBox.warning(self, "Export", str(e)); return
        src = os.path.join(self.extract_dir, rel)
        if not os.path.exists(src):
            QMessageBox.information(self, "Export", "ไม่มีไฟล์นี้")
            return
        if os.path.isdir(src):
            QMessageBox.information(self, "Export", "ยังไม่รองรับโฟลเดอร์")
            return
        dst, _ = QFileDialog.getSaveFileName(self, "บันทึกเป็น", os.path.basename(rel))
        if not dst: return
        try:
            shutil.copyfile(src, dst)
            self.log(f"Export: {rel} -> {dst}")
        except Exception as e:
            QMessageBox.critical(self, "Export", f"ล้มเหลว: {e}")

    def open_in_file_manager(self):
        try:
            subprocess.Popen(["xdg-open", self.extract_dir])
        except Exception as e:
            QMessageBox.warning(self, "เปิดโฟลเดอร์", f"ไม่สำเร็จ: {e}")

    def log(self, msg):
        self.log_view.append(msg)
        self.log_view.ensureCursorVisible()
        if hasattr(self.parent_win, 'log'):
            self.parent_win.log(f"[RootFS-Edit] {msg}")

    def do_add_replace(self):
        try:
            rel = self._norm_internal()
        except Exception as e:
            QMessageBox.warning(self, "Path", str(e)); return
        src, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์ต้นทาง")
        if not src:
            return
        dst = os.path.join(self.extract_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copyfile(src, dst)
            self.log(f"Add/Replace: {rel} <- {src}")
            self.pending_changes.append(("add_replace", rel, src))
        except Exception as e:
            QMessageBox.critical(self, "Add/Replace", f"ล้มเหลว: {e}")

    def do_delete(self):
        try:
            rel = self._norm_internal()
        except Exception as e:
            QMessageBox.warning(self, "Path", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        if not os.path.exists(dst):
            QMessageBox.information(self, "Delete", "ไม่มีไฟล์นี้")
            return
        try:
            os.remove(dst)
            self.log(f"Delete: {rel}")
            self.pending_changes.append(("delete", rel, None))
        except Exception as e:
            QMessageBox.critical(self, "Delete", f"ล้มเหลว: {e}")

    def do_view(self):
        try:
            rel = self._norm_internal()
        except Exception as e:
            QMessageBox.warning(self, "Path", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        if not os.path.exists(dst):
            QMessageBox.information(self, "View", "ไม่มีไฟล์นี้")
            return
        try:
            with open(dst, 'r', encoding='utf-8', errors='ignore') as f:
                data = f.read(4096)
        except Exception as e:
            QMessageBox.critical(self, "View", f"อ่านไม่ได้: {e}")
            return
        QMessageBox.information(self, rel, data if data else "(ว่าง)")

    def do_repack(self):
        # สร้าง rootfs ใหม่ -> ใส่กลับเข้า firmware -> ไฟล์ผลลัพธ์ใหม่
        self.log("เริ่ม repack rootfs ...")
        tmpdir = tempfile.mkdtemp(prefix="rfse_pack_")
        try:
            new_rootfs_bin = os.path.join(tmpdir, "new_rootfs.bin")
            ok, err = repack_rootfs(self.rootfs_part['fs'], self.extract_dir, new_rootfs_bin, self.log)
            if not ok:
                QMessageBox.critical(self, "Repack", f"ไม่สำเร็จ: {err}")
                return
            with open(self.fw_path, 'rb') as f:
                fw_data = bytearray(f.read())
            with open(new_rootfs_bin, 'rb') as f:
                new_rootfs = f.read()
            if len(new_rootfs) > self.rootfs_part['size']:
                QMessageBox.critical(self, "Repack", "rootfs ใหม่ใหญ่เกินขนาดเดิม")
                return
            fw_data[self.rootfs_part['offset']:self.rootfs_part['offset']+len(new_rootfs)] = new_rootfs
            if len(new_rootfs) < self.rootfs_part['size']:
                fw_data[self.rootfs_part['offset']+len(new_rootfs):self.rootfs_part['offset']+self.rootfs_part['size']] = b'\x00' * (self.rootfs_part['size'] - len(new_rootfs))
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            out_fw = os.path.join(self.output_dir, f"edited_rootfs_{self.rootfs_part['fs']}_0x{self.rootfs_part['offset']:X}_{ts}.bin")
            with open(out_fw, 'wb') as f:
                f.write(fw_data)
            self.log(f"✅ Repack สำเร็จ -> {out_fw}")
            QMessageBox.information(self, "Repack", f"สำเร็จ: {out_fw}\nเปลี่ยนแปลง {len(self.pending_changes)} รายการ")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# --------------- Dialog Run Custom Script (Step 6) -----------------
class CustomScriptDialog(QDialog):
    """Allow user to execute simple scripts/commands against an extracted rootfs temp copy.
    Supports:
      - Shell command (executed in temp rootfs chroot-like simulation by prefixing PATH)
      - Python inline (run with access to helper variables)
      - Simple search (grep) over files
    """
    def __init__(self, parent, rootfs_part):
        super().__init__(parent)
        self.setWindowTitle("Run Custom Script / Command")
        self.resize(900, 650)
        self.parent_win = parent
        self.rootfs_part = rootfs_part
        self._build_ui()
        self._prepare_rootfs()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        desc = QLabel("เครื่องมือนี้จะ extract rootfs (ถ้ายัง) ไปยัง temp dir และให้รันคำสั่ง / สคริปต์เบื้องต้น")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox(); self.mode_combo.addItems(["shell", "python", "grep"])
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(); lay.addLayout(mode_row)
        self.input_edit = QTextEdit(); self.input_edit.setPlaceholderText("เช่น\n# shell\nfind . -maxdepth 2 -type f | head\n\n# python\nfor p in list_files('.')[:10]:\n    print(p)\n\n# grep mode: ใส่ pattern หนึ่งบรรทัด เช่น root:x:")
        lay.addWidget(self.input_edit, 1)
        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self.run_action)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_run); btn_row.addWidget(self.btn_close); btn_row.addStretch()
        lay.addLayout(btn_row)
        self.out_edit = QTextEdit(); self.out_edit.setReadOnly(True)
        lay.addWidget(self.out_edit, 2)

    def log(self, msg):
        self.out_edit.append(msg)
        self.out_edit.ensureCursorVisible()
        if hasattr(self.parent_win, 'log'):
            self.parent_win.log(f"[CustomScript] {msg}")

    def _prepare_rootfs(self):
        # reuse existing extracted cache if matches part index else extract a temp copy (read-only operations recommended)
        part_index = self.parent_win.rootfs_part_spin.value() - 1
        use_cache = False
        if getattr(self.parent_win, 'edit_cache_dir', None) and self.parent_win.edit_cache_part_index == part_index:
            if os.path.isdir(self.parent_win.edit_cache_dir):
                self.work_dir = self.parent_win.edit_cache_dir
                use_cache = True
        if use_cache:
            self.log("ใช้ rootfs cache เดิม")
            return
        # extract minimal for script use
        tmp_work = tempfile.mkdtemp(prefix="custom_script_")
        self.parent_win.log(f"[TEMP] custom script workspace: {tmp_work}")
        rootfs_bin = os.path.join(tmp_work, "rootfs.bin")
        with open(self.parent_win.fw_path, 'rb') as f:
            f.seek(self.rootfs_part['offset'])
            blob = f.read(self.rootfs_part['size'])
        with open(rootfs_bin, 'wb') as f:
            f.write(blob)
        extract_dir = os.path.join(tmp_work, 'extract')
        os.makedirs(extract_dir, exist_ok=True)
        ok, err = extract_rootfs(self.rootfs_part['fs'], rootfs_bin, extract_dir, self.log)
        if not ok:
            self.log(f"❌ extract ไม่สำเร็จ: {err}")
            self.work_dir = None
        else:
            self.work_dir = extract_dir
            self.log(f"เตรียม rootfs สำหรับ script: {extract_dir}")
        self._temp_workspace = tmp_work

    def closeEvent(self, event):
        # cleanup only if not using shared cache
        if hasattr(self, '_temp_workspace'):
            try: shutil.rmtree(self._temp_workspace, ignore_errors=True)
            except: pass
        super().closeEvent(event)

    # Helper listing for python mode
    def _list_files(self, base):
        out = []
        for root, dirs, files in os.walk(base):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), base)
                out.append(rel)
                if len(out) >= 10000:  # cap
                    return out
        return out

    def run_action(self):
        if not self.work_dir:
            QMessageBox.warning(self, "Run", "ยังไม่มี rootfs พร้อมใช้งาน")
            return
        mode = self.mode_combo.currentText()
        code = self.input_edit.toPlainText().strip()
        if not code:
            QMessageBox.information(self, "Run", "ไม่มี input")
            return
        self.out_edit.clear()
        if mode == 'shell':
            self._run_shell(code)
        elif mode == 'python':
            self._run_python(code)
        else:
            self._run_grep(code)

    def _run_shell(self, cmd):
        # run in work_dir; restrict length
        if len(cmd) > 4000:
            self.log("คำสั่งยาวเกิน ตัดออก")
            cmd = cmd[:4000]
        try:
            proc = subprocess.Popen(cmd, cwd=self.work_dir, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out, _ = proc.communicate(timeout=30)
            self.log(out or "(no output)")
            self.log(f"[exit={proc.returncode}]")
        except subprocess.TimeoutExpired:
            self.log("Timeout (30s)")
        except Exception as e:
            self.log(f"error: {e}")

    # ---------------- Menus -----------------
    def _create_menus(self):
        mb = self.menuBar()
        # File
        m_file = mb.addMenu("File")
        act_open = QAction("Open Firmware", self); act_open.triggered.connect(self.select_firmware)
        act_out = QAction("Set Output Folder", self); act_out.triggered.connect(self.select_output_folder)
        act_exit = QAction("Exit", self); act_exit.triggered.connect(self.close)
        for a in (act_open, act_out): m_file.addAction(a)
        m_file.addSeparator(); m_file.addAction(act_exit)
        # Analysis
        m_analysis = mb.addMenu("Analysis")
        for text, slot in [
            ("Firmware Info", self.show_fw_info),
            ("Scan RootFS", self.auto_detect_rootfs),
            ("AI Analyze", self.ai_analyze_all),
            ("Diff Executables", self.diff_executables),
            ("Check Hash/Signature", self.check_hash_signature),
            ("Vulnerability Scan (demo)", self.scan_vulnerabilities),
            ("Backdoor Scan (demo)", self.scan_backdoor),
        ]:
            act = QAction(text, self); act.triggered.connect(slot); m_analysis.addAction(act)
        # Patching
        m_patch = mb.addMenu("Patching")
        for text, slot in [
            ("Patch Boot Delay", self.do_patch_boot_delay),
            ("Patch Serial Shell", self.do_patch_serial),
            ("Patch Network", self.do_patch_network),
            ("Patch All", self.do_patch_all),
            ("Patch Root Password", self.do_patch_rootpw),
            ("Selective Patch Dialog", self.patch_selective),
            ("Export Patch Profile", self.export_patch_profile),
            ("Import Patch Profile", self.import_patch_profile),
        ]:
            act = QAction(text, self); act.triggered.connect(slot); m_patch.addAction(act)
        # RootFS
        m_root = mb.addMenu("RootFS")
        for text, slot in [
            ("Edit RootFS", self.edit_rootfs_file),
            ("Run Custom Script", self.run_custom_script),
            ("Open Special Functions Window", self.open_special_functions_window),
        ]:
            act = QAction(text, self); act.triggered.connect(slot); m_root.addAction(act)
        # Tools
        m_tools = mb.addMenu("Tools")
        act_ext = QAction("Check External Tools", self); act_ext.triggered.connect(self.check_external_tools)
        act_clearlog = QAction("Clear Logs", self); act_clearlog.triggered.connect(self.clear_logs)
        m_tools.addAction(act_ext); m_tools.addAction(act_clearlog)
        # Help
        m_help = mb.addMenu("Help")
        act_about = QAction("About", self); act_about.triggered.connect(lambda: QMessageBox.information(self, "About", "Firmware Workbench\nEnhanced UI & Menu System"))
        m_help.addAction(act_about)

    def _run_python(self, code):
        # Provide minimal sandbox namespace
        ns = {
            '__builtins__': {k: getattr(__builtins__, k) for k in ['len','range','print','open','enumerate','min','max','sum','sorted','any','all'] if k in __builtins__},
            'WORK_DIR': self.work_dir,
            'list_files': lambda p='.': self._list_files(os.path.join(self.work_dir, p)) if os.path.isdir(os.path.join(self.work_dir, p)) else [],
            'read_text': lambda p: open(os.path.join(self.work_dir, p), 'r', encoding='utf-8', errors='ignore').read(2048),
            'sha256sum': lambda p: sha256sum(os.path.join(self.work_dir, p)) if os.path.exists(os.path.join(self.work_dir, p)) else None,
        }
        output_lines = []
        def _printer(*a, **kw):
            s = " ".join(str(x) for x in a)
            output_lines.append(s)
        ns['print'] = _printer
        try:
            exec(code, ns, {})
            for line in output_lines:
                self.log(line)
            self.log("[python done]")
        except Exception as e:
            self.log(f"Exception: {e}")

    def _run_grep(self, pattern):
        # simple case-insensitive search up to 200 matches
        pat = pattern.strip()
        if not pat:
            self.log("ไม่มี pattern")
            return
        count = 0
        try:
            for root, dirs, files in os.walk(self.work_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        with open(fp, 'rb') as fh:
                            data = fh.read(4096)  # head only for speed
                        if pat.lower().encode('utf-8') in data.lower():
                            rel = os.path.relpath(fp, self.work_dir)
                            self.log(rel)
                            count += 1
                            if count >= 200:
                                self.log("ถึงขีดจำกัด 200 รายการ")
                                raise StopIteration
                    except StopIteration:
                        raise
                    except Exception:
                        continue
        except StopIteration:
            pass
        self.log(f"[grep matches={count}]")

###############################
# Program entry point - DO NOT REMOVE
###############################
if __name__ == "__main__":
    # Support running headless (no DISPLAY) gracefully
    if os.environ.get("DISPLAY", "") == "":
        print("[WARN] ไม่มี DISPLAY environment (X11). หากต้องการ GUI ให้ export DISPLAY หรือใช้ xvfb-run.")
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

