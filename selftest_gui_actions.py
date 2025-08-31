#!/usr/bin/env python3
"""Headless self-test (offscreen) สำหรับ MainWindow actions.

หมวดทดสอบ:
 1) Core (ควรผ่านได้แม้ firmware ปลอม และไม่มี external tools)
 2) Optional (ต้องการเครื่องมือภายนอก / rootfs จริง)

รายงานผล JSON + สรุปภาษาไทยท้ายสุด
"""
import os, sys, json, tempfile, traceback, shutil, time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app import MainWindow, QApplication
from PySide6.QtCore import QEventLoop, QTimer
try:
    from PySide6.QtWidgets import QMessageBox, QFileDialog, QInputDialog
except Exception:
    QMessageBox = QFileDialog = QInputDialog = None

# --- Monkeypatch GUI blocking dialogs ---
if QMessageBox:
    QMessageBox.information = staticmethod(lambda *a, **k: 0)
    QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    QMessageBox.critical = staticmethod(lambda *a, **k: 0)
if QFileDialog:
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("/tmp/dummy.bin",""))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("/tmp/export_profile.json",""))
if QInputDialog:
    # คืนค่า (value, okFlag)
    QInputDialog.getInt = staticmethod(lambda *a, **k: (3, True))

CORE_ACTIONS = [
    ("multi_squash_dryrun", lambda w: w.multi_squash_dryrun(), True),
    ("detect_rootfs_parts", lambda w: w.detect_rootfs_parts(), True),
    ("quick_boot_delay", lambda w: w._run_quick_patch('boot_delay'), True),
    ("quick_serial", lambda w: w._run_quick_patch('serial'), True),
    ("quick_network", lambda w: w._run_quick_patch('network'), True),
    ("quick_all", lambda w: w._run_quick_patch('all'), True),
    ("apply_patch_actions(sample)", lambda w: w.apply_patch_actions({'boot_delay':True,'boot_delay_value':2,'serial_shell':True,'network_services':True}), True),
    ("archive_outputs", lambda w: w.archive_outputs(), False),
    ("check_hash_signature", lambda w: w.check_hash_signature(), True),
    ("export_patch_profile", lambda w: w.export_patch_profile(), True),
    ("import_patch_profile", lambda w: w.import_patch_profile(), False),
]

OPTIONAL_ACTIONS = [
    # multi_squash_apply skipped (thread teardown ใน headless ก่อให้เกิด abort)
    ("auto_run_mode_A", lambda w: w.auto_run_mode('A'), True),
]

def build_dummy_firmware(path: str):
    # ใส่บรรทัด ASCII สำหรับ regex detect_squashfs (offset + size=...)
    text_line = b"0x100 squashfs filesystem size=0x40000 Dummy\n"
    filler = os.urandom(256*1024)
    with open(path,'wb') as f:
        f.write(text_line + filler)

def run_actions(win, specs, category):
    results = []
    for name, func, need_fw in specs:
        entry = {"action": name, "category": category, "status": "OK", "time_s": 0.0}
        t0 = time.time()
        try:
            if need_fw and not getattr(win, 'fw_path', None):
                entry["status"] = "SKIP:no_fw"
            else:
                func(win)
                # process events briefly (handle signals/log updates)
                loop = QEventLoop()
                QTimer.singleShot(80, loop.quit)
                loop.exec()
        except Exception:
            entry["status"] = "ERROR"
            entry["trace"] = traceback.format_exc().splitlines()[-6:]
        finally:
            entry["time_s"] = round(time.time()-t0,3)
        results.append(entry)
    # wait for any threads spawned during this category
    try:
        win.wait_for_threads()
    except Exception:
        pass
    return results

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    # เตรียม dummy firmware
    tmp_fw = os.path.join(tempfile.gettempdir(), 'headless_dummy_fw.bin')
    build_dummy_firmware(tmp_fw)
    win.fw_path = tmp_fw
    os.makedirs(win.output_dir, exist_ok=True)

    core_res = run_actions(win, CORE_ACTIONS, 'core')
    opt_res = run_actions(win, OPTIONAL_ACTIONS, 'optional')

    all_res = core_res + opt_res
    # final wait to ensure no background threads remain
    try:
        win.wait_for_threads()
    except Exception:
        pass
    # จัดลำดับ: ERROR -> OK -> SKIP
    order_key = {'ERROR':0,'OK':1,'SKIP:no_fw':2}
    all_res.sort(key=lambda r: order_key.get(r['status'], 3))

    print(json.dumps(all_res, indent=2, ensure_ascii=False))
    # สรุปไทย
    total = len(all_res)
    errors = [r for r in all_res if r['status']=='ERROR']
    print('\n===== สรุป (ไทย) =====')
    print(f'รวม {total} actions | ERROR {len(errors)}')
    if errors:
        print('รายการที่ล้มเหลว:')
        for e in errors:
            print(f" - {e['action']} :: {' | '.join(e.get('trace', [])[-1:])}")
    else:
        print('ไม่มี ERROR')
    return 0 if not errors else 1

if __name__ == '__main__':
    sys.exit(main())
