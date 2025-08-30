import os, shutil, tempfile, datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QSplitter, QWidget, QHBoxLayout,
    QPushButton, QTextEdit, QFileDialog, QMessageBox, QMenu, QLineEdit
)
from PySide6.QtCore import Qt

# Expect extract_rootfs & repack_rootfs helpers to be imported at runtime from main module
from typing import Callable

class RootFSEditDialog(QDialog):
    """Simplified RootFS editor dialog migrated from legacy code.
    Requires parent window to provide: log(), fw_path, output_dir, rootfs_part_spin
    """
    def __init__(self, parent, extract_dir, rootfs_part, fw_path, output_dir):
        super().__init__(parent)
        self.setWindowTitle("แก้ไขไฟล์ใน RootFS (Full Editor)")
        self.resize(1000, 600)
        self.extract_dir = extract_dir
        self.rootfs_part = rootfs_part
        self.fw_path = fw_path
        self.output_dir = output_dir
        self.parent_win = parent
        self.pending_changes = []
        self._build_ui()
        self.load_tree()

    def _build_ui(self):
        main_lay = QVBoxLayout(self)
        self.dir_label = QLabel(f"RootFS: {self.rootfs_part['fs']} @ 0x{self.rootfs_part['offset']:X} size=0x{self.rootfs_part['size']:X}\nExtract dir: {self.extract_dir}")
        self.dir_label.setStyleSheet("font-weight:bold;")
        main_lay.addWidget(self.dir_label)
        split = QSplitter(); main_lay.addWidget(split, 1)
        left_widget = QWidget(); left_lay = QVBoxLayout(left_widget); left_lay.setContentsMargins(0,0,0,0)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Path", "Size", "Perms"])
        self.tree.itemClicked.connect(self.on_tree_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_tree_menu)
        left_lay.addWidget(self.tree, 1)
        refresh_row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_open_dir = QPushButton("เปิดในระบบ (xdg-open)")
        refresh_row.addWidget(btn_refresh); refresh_row.addWidget(btn_open_dir); refresh_row.addStretch(); left_lay.addLayout(refresh_row)
        split.addWidget(left_widget)
        right_widget = QWidget(); rlay = QVBoxLayout(right_widget)
        path_row = QHBoxLayout(); path_row.addWidget(QLabel("Internal path:"))
        self.internal_edit = QLineEdit(); self.internal_edit.setPlaceholderText("เช่น etc/banner หรือ usr/bin/app")
        path_row.addWidget(self.internal_edit); rlay.addLayout(path_row)
        btn_row1 = QHBoxLayout()
        self.btn_add = QPushButton("เพิ่ม/แทนที่ (Add/Replace)")
        self.btn_view = QPushButton("ดูไฟล์ (View)")
        self.btn_delete = QPushButton("ลบ (Delete)")
        for b in (self.btn_add, self.btn_view, self.btn_delete): btn_row1.addWidget(b)
        rlay.addLayout(btn_row1)
        btn_row2 = QHBoxLayout()
        self.btn_mkdir = QPushButton("สร้างโฟลเดอร์ (mkdir)")
        self.btn_export = QPushButton("Export ไฟล์ออก")
        self.btn_repack = QPushButton("Repack -> Firmware ใหม่")
        for b in (self.btn_mkdir, self.btn_export, self.btn_repack): btn_row2.addWidget(b)
        rlay.addLayout(btn_row2)
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True); rlay.addWidget(self.log_view,1)
        btn_close = QPushButton("ปิด"); rlay.addWidget(btn_close)
        split.addWidget(right_widget); split.setStretchFactor(0,4); split.setStretchFactor(1,6)
        btn_close.clicked.connect(self.close)
        self.btn_add.clicked.connect(self.do_add_replace)
        self.btn_delete.clicked.connect(self.do_delete)
        self.btn_view.clicked.connect(self.do_view)
        self.btn_repack.clicked.connect(self.do_repack)
        self.btn_mkdir.clicked.connect(self.do_mkdir)
        self.btn_export.clicked.connect(self.do_export)
        btn_refresh.clicked.connect(self.load_tree)
        btn_open_dir.clicked.connect(self.open_in_file_manager)

    # ----- helpers -----
    def _norm_internal(self):
        rel = self.internal_edit.text().strip().lstrip('/')
        if not rel: raise ValueError("ยังไม่ได้ระบุ internal path")
        if '..' in rel.split('/'): raise ValueError("ห้ามใช้ '..'")
        return rel

    def log(self, msg):
        self.log_view.append(msg); self.log_view.ensureCursorVisible()
        if hasattr(self.parent_win, 'log'): self.parent_win.log(f"[RootFS-Edit] {msg}")

    # ----- tree -----
    def load_tree(self):
        self.tree.clear(); base = self.extract_dir; max_nodes = 5000; max_depth = 12; count = 0; symlink_skipped = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            rel_root = os.path.relpath(root, base)
            if rel_root == '.': rel_root = ''; depth = 0
            else: depth = rel_root.count('/') + 1
            if depth > max_depth: continue
            parent_item = None
            if rel_root: parent_item = self._ensure_path_item(rel_root)
            for name in sorted(files):
                if count >= max_nodes: break
                rel_path = os.path.join(rel_root, name) if rel_root else name
                full_path = os.path.join(base, rel_path)
                try:
                    if os.path.islink(full_path):
                        item = QTreeWidgetItem([rel_path, '-', 'link'])
                    else:
                        size = os.path.getsize(full_path)
                        try: perms = oct(os.lstat(full_path).st_mode & 0o777)
                        except Exception: perms = '?'
                        item = QTreeWidgetItem([rel_path, str(size), perms])
                except (FileNotFoundError, OSError): continue
                if parent_item: parent_item.addChild(item)
                else: self.tree.addTopLevelItem(item)
                count += 1
            if count >= max_nodes: break
        if count >= max_nodes: self.tree.addTopLevelItem(QTreeWidgetItem([f"[แสดงบางส่วน จำกัด {max_nodes} ไฟล์]", "", ""]))
        if symlink_skipped: self.tree.addTopLevelItem(QTreeWidgetItem([f"[ข้าม symlink {symlink_skipped} รายการ]", "", ""]))
        self.tree.sortItems(0, Qt.AscendingOrder)

    def _ensure_path_item(self, rel_root):
        parts = rel_root.split('/'); path_accum = []; parent = None
        for part in parts:
            path_accum.append(part); key = '/'.join(path_accum); parent = self._find_or_create_dir_item(parent, key, part)
        return parent

    def _find_or_create_dir_item(self, parent, key, label):
        container = self.tree if parent is None else parent
        for i in range(container.childCount() if parent else container.topLevelItemCount()):
            it = container.child(i) if parent else container.topLevelItem(i)
            if it.text(0) == key: return it
        new_item = QTreeWidgetItem([key, "", "dir"])
        if parent: parent.addChild(new_item)
        else: self.tree.addTopLevelItem(new_item)
        return new_item

    # ----- tree interactions -----
    def on_tree_click(self, item):
        path_text = item.text(0)
        if path_text.startswith('[แสดงบางส่วน'): return
        if path_text: self.internal_edit.setText(path_text)

    def on_tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item: return
        path_text = item.text(0)
        if not path_text or path_text.startswith('[แสดงบางส่วน'): return
        menu = QMenu(self)
        act_view = menu.addAction("View"); act_delete = menu.addAction("Delete"); act_export = menu.addAction("Export")
        act = menu.exec(self.tree.mapToGlobal(pos))
        if act == act_view: self.internal_edit.setText(path_text); self.do_view()
        elif act == act_delete: self.internal_edit.setText(path_text); self.do_delete()
        elif act == act_export: self.internal_edit.setText(path_text); self.do_export()

    # ----- file ops -----
    def do_mkdir(self):
        try: rel = self._norm_internal()
        except Exception as e: QMessageBox.warning(self, "mkdir", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        try: os.makedirs(dst, exist_ok=True); self.log(f"mkdir: {rel}"); self.load_tree()
        except Exception as e: QMessageBox.critical(self, "mkdir", f"ล้มเหลว: {e}")

    def do_export(self):
        try: rel = self._norm_internal()
        except Exception as e: QMessageBox.warning(self, "Export", str(e)); return
        src = os.path.join(self.extract_dir, rel)
        if not os.path.exists(src): QMessageBox.information(self, "Export", "ไม่มีไฟล์นี้"); return
        if os.path.isdir(src): QMessageBox.information(self, "Export", "ยังไม่รองรับโฟลเดอร์"); return
        dst, _ = QFileDialog.getSaveFileName(self, "บันทึกเป็น", os.path.basename(rel))
        if not dst: return
        try: shutil.copyfile(src, dst); self.log(f"Export: {rel} -> {dst}")
        except Exception as e: QMessageBox.critical(self, "Export", f"ล้มเหลว: {e}")

    def open_in_file_manager(self):
        import subprocess
        try: subprocess.Popen(["xdg-open", self.extract_dir])
        except Exception as e: QMessageBox.warning(self, "เปิดโฟลเดอร์", f"ไม่สำเร็จ: {e}")

    def do_add_replace(self):
        try: rel = self._norm_internal()
        except Exception as e: QMessageBox.warning(self, "Path", str(e)); return
        src, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์ต้นทาง")
        if not src: return
        dst = os.path.join(self.extract_dir, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        try: shutil.copyfile(src, dst); self.log(f"Add/Replace: {rel} <- {src}"); self.pending_changes.append(("add_replace", rel, src))
        except Exception as e: QMessageBox.critical(self, "Add/Replace", f"ล้มเหลว: {e}")

    def do_delete(self):
        try: rel = self._norm_internal()
        except Exception as e: QMessageBox.warning(self, "Path", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        if not os.path.exists(dst): QMessageBox.information(self, "Delete", "ไม่มีไฟล์นี้"); return
        try: os.remove(dst); self.log(f"Delete: {rel}"); self.pending_changes.append(("delete", rel, None))
        except Exception as e: QMessageBox.critical(self, "Delete", f"ล้มเหลว: {e}")

    def do_view(self):
        try: rel = self._norm_internal()
        except Exception as e: QMessageBox.warning(self, "Path", str(e)); return
        dst = os.path.join(self.extract_dir, rel)
        if not os.path.exists(dst): QMessageBox.information(self, "View", "ไม่มีไฟล์นี้"); return
        try:
            with open(dst, 'r', encoding='utf-8', errors='ignore') as f: data = f.read(4096)
        except Exception as e: QMessageBox.critical(self, "View", f"อ่านไม่ได้: {e}"); return
        QMessageBox.information(self, rel, data if data else "(ว่าง)")

    def do_repack(self):
        from app import repack_rootfs  # local import to avoid circular
        self.log("เริ่ม repack rootfs ...")
        tmpdir = tempfile.mkdtemp(prefix="rfse_pack_")
        try:
            new_rootfs_bin = os.path.join(tmpdir, "new_rootfs.bin")
            ok, err = repack_rootfs(self.rootfs_part['fs'], self.extract_dir, new_rootfs_bin, self.log)
            if not ok: QMessageBox.critical(self, "Repack", f"ไม่สำเร็จ: {err}"); return
            with open(self.fw_path, 'rb') as f: fw_data = bytearray(f.read())
            with open(new_rootfs_bin, 'rb') as f: new_rootfs = f.read()
            if len(new_rootfs) > self.rootfs_part['size']:
                QMessageBox.critical(self, "Repack", "rootfs ใหม่ใหญ่เกินขนาดเดิม"); return
            fw_data[self.rootfs_part['offset']:self.rootfs_part['offset']+len(new_rootfs)] = new_rootfs
            if len(new_rootfs) < self.rootfs_part['size']:
                fw_data[self.rootfs_part['offset']+len(new_rootfs):self.rootfs_part['offset']+self.rootfs_part['size']] = b'\x00' * (self.rootfs_part['size'] - len(new_rootfs))
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            out_fw = os.path.join(self.output_dir, f"edited_rootfs_{self.rootfs_part['fs']}_0x{self.rootfs_part['offset']:X}_{ts}.bin")
            with open(out_fw, 'wb') as f: f.write(fw_data)
            self.log(f"✅ Repack สำเร็จ -> {out_fw}")
            QMessageBox.information(self, "Repack", f"สำเร็จ: {out_fw}\nเปลี่ยนแปลง {len(self.pending_changes)} รายการ")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # utilities
    def open_in_file_manager(self): pass  # already defined above
