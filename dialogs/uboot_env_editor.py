from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QLineEdit, QMessageBox, QHeaderView, QCheckBox, QWidget, QFileDialog
)
from PySide6.QtCore import Qt


class UBootEnvEditorDialog(QDialog):
    """Dialog for scanning & editing U-Boot environment variables.

    scan_func(deep: bool=False) -> list[dict]
      Each dict: {offset,size,valid,vars,bootdelay,crc,crc_calc,score,heuristic?}
    patch_func(src_fw, dst_fw, offset, size, updates: dict) -> (ok, err)
    Parent (MainWindow) must expose: fw_path, _ensure_unified_path(), log()
    """

    def __init__(self, parent, scan_func, patch_func):
        super().__init__(parent)
        self.setWindowTitle("แก้ไข U-Boot Environment")
        self.resize(980, 640)
        self.scan_func = scan_func
        self.patch_func = patch_func
        self.env_blocks = []
        self.current_block_index = None

        root = QVBoxLayout(self)

        # Info / status label
        self.info_label = QLabel("สแกน environment...")
        root.addWidget(self.info_label)

        # Blocks table
        self.blocks_table = QTableWidget(0, 7)
        self.blocks_table.setHorizontalHeaderLabels([
            "#", "Offset", "Size", "CRC OK", "bootdelay", "Vars", "Mode"
        ])
        self.blocks_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.blocks_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.blocks_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.blocks_table.itemSelectionChanged.connect(self._block_selected)
        root.addWidget(self.blocks_table, 1)

        # Variables table
        self.vars_table = QTableWidget(0, 3)
        self.vars_table.setHorizontalHeaderLabels(["Key", "Value", "ลบ?"])
        self.vars_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.vars_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        root.addWidget(self.vars_table, 3)

        # Add / edit controls
        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("เพิ่ม/แก้ Key:"))
        self.new_key = QLineEdit(); self.new_key.setPlaceholderText("key")
        self.new_val = QLineEdit(); self.new_val.setPlaceholderText("value (เว้นว่าง=ลบ)")
        btn_add = QPushButton("เพิ่ม/เซ็ต"); btn_add.clicked.connect(self._add_update_key)
        edit_row.addWidget(self.new_key); edit_row.addWidget(self.new_val); edit_row.addWidget(btn_add)
        root.addLayout(edit_row)

        # Action buttons
        btns = QHBoxLayout()
        self.deep_box = QCheckBox("Deep Scan (Full File)")
        self.btn_rescan = QPushButton("สแกนใหม่"); self.btn_rescan.clicked.connect(self._rescan)
        self.btn_export = QPushButton("Export .env"); self.btn_export.clicked.connect(self._export_env)
        self.btn_apply = QPushButton("บันทึกการเปลี่ยนแปลง"); self.btn_apply.clicked.connect(self._apply)
        btn_close = QPushButton("ปิด"); btn_close.clicked.connect(self.reject)
        for w in (self.deep_box, self.btn_rescan, self.btn_export, self.btn_apply):
            btns.addWidget(w)
        btns.addStretch(); btns.addWidget(btn_close)
        root.addLayout(btns)

        self._rescan(initial=True)

    # ----------------- Scanning -----------------
    def _rescan(self, initial: bool=False):
        deep = self.deep_box.isChecked()
        try:
            self.env_blocks = self.scan_func(deep=deep) or []
        except Exception as e:
            self.env_blocks = []
            QMessageBox.warning(self, "Scan", f"ล้มเหลว: {e}")
        self._populate_blocks_table(deep)
        if not self.env_blocks and not deep and not initial:
            # Suggest deep scan
            QMessageBox.information(self, "Deep Scan", "ยังไม่พบ environment ลองติ๊ก Deep Scan แล้วสแกนอีกครั้ง")

    def _populate_blocks_table(self, deep: bool):
        self.blocks_table.setRowCount(0)
        for i, b in enumerate(self.env_blocks, start=1):
            row = self.blocks_table.rowCount(); self.blocks_table.insertRow(row)
            mode = 'heuristic' if b.get('heuristic') else ('deep' if deep else 'normal')
            vals = [
                i,
                f"0x{b['offset']:X}",
                f"0x{b['size']:X}",
                '✔' if b.get('valid') else '✘',
                b.get('bootdelay'),
                len(b.get('vars', {})),
                mode
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if col == 3 and not b.get('valid'):
                    item.setForeground(Qt.red)
                if col == 6 and mode == 'heuristic':
                    # heuristic highlight
                    item.setForeground(Qt.darkYellow)
                self.blocks_table.setItem(row, col, item)
        self.info_label.setText(
            f"พบ {len(self.env_blocks)} บล็อค" + (" (deep)" if deep else "")
        )
        if self.env_blocks:
            self.blocks_table.selectRow(0)

    # ----------------- Block selection -----------------
    def _block_selected(self):
        rows = self.blocks_table.selectionModel().selectedRows()
        if not rows:
            self.current_block_index = None
            self.vars_table.setRowCount(0)
            return
        idx = rows[0].row(); self.current_block_index = idx
        block = self.env_blocks[idx]
        vars_dict = block.get('vars', {})
        self.vars_table.setRowCount(0)
        for k, v in sorted(vars_dict.items()):
            row = self.vars_table.rowCount(); self.vars_table.insertRow(row)
            self.vars_table.setItem(row, 0, QTableWidgetItem(k))
            val_item = QTableWidgetItem(v)
            val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
            self.vars_table.setItem(row, 1, val_item)
            chk = QCheckBox(); w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); l.addWidget(chk); l.addStretch(); self.vars_table.setCellWidget(row, 2, w)
        self.vars_table.resizeRowsToContents()

    # ----------------- Add / Update key -----------------
    def _add_update_key(self):
        k = self.new_key.text().strip(); v = self.new_val.text().strip()
        if not k:
            QMessageBox.warning(self, "Key", "ระบุ key")
            return
        # Update if exists
        for r in range(self.vars_table.rowCount()):
            if self.vars_table.item(r, 0).text() == k:
                self.vars_table.item(r, 1).setText(v)
                return
        # Add new row
        row = self.vars_table.rowCount(); self.vars_table.insertRow(row)
        self.vars_table.setItem(row, 0, QTableWidgetItem(k))
        val_item = QTableWidgetItem(v); val_item.setFlags(val_item.flags() | Qt.ItemIsEditable)
        self.vars_table.setItem(row, 1, val_item)
        chk = QCheckBox(); w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0,0,0,0); l.addWidget(chk); l.addStretch(); self.vars_table.setCellWidget(row, 2, w)

    # ----------------- Apply changes -----------------
    def _apply(self):
        if self.current_block_index is None:
            QMessageBox.warning(self, "Env", "ยังไม่ได้เลือกบล็อค")
            return
        block = self.env_blocks[self.current_block_index]
        updates = {}
        for r in range(self.vars_table.rowCount()):
            k = self.vars_table.item(r, 0).text()
            v = self.vars_table.item(r, 1).text()
            chk_widget = self.vars_table.cellWidget(r, 2)
            delete = False
            if chk_widget:
                cb = chk_widget.layout().itemAt(0).widget(); delete = cb.isChecked()
            updates[k] = '' if delete else v
        if not updates:
            QMessageBox.information(self, "Env", "ไม่มีการเปลี่ยนแปลง")
            return
        if QMessageBox.question(self, "ยืนยัน", "แก้ไข environment นี้หรือไม่?") != QMessageBox.Yes:
            return
        parent = self.parent()
        out = parent._ensure_unified_path()
        ok, err = self.patch_func(parent.fw_path, out, block['offset'], block['size'], updates)
        if ok:
            parent.fw_path = out
            QMessageBox.information(self, "Env", "สำเร็จ -> firmware unified ใหม่")
            self._rescan()
        else:
            QMessageBox.critical(self, "Env", f"ล้มเหลว: {err}")

    # ----------------- Export -----------------
    def _export_env(self):
        if self.current_block_index is None:
            QMessageBox.warning(self, "Export", "ยังไม่ได้เลือกบล็อค")
            return
        block = self.env_blocks[self.current_block_index]
        vars_dict = block.get('vars', {})
        if not vars_dict:
            QMessageBox.information(self, "Export", "ไม่มีตัวแปร")
            return
        default_name = f"uboot_env_0x{block['offset']:X}.env"
        path, _ = QFileDialog.getSaveFileName(self, "บันทึกไฟล์ .env", default_name, "Env (*.env)")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                for k, v in sorted(vars_dict.items()):
                    f.write(f"{k}={v}\n")
            QMessageBox.information(self, "Export", f"บันทึกแล้ว: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export", str(e))

