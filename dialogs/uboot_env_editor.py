from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView, QAbstractItemView,
    QComboBox
)

# This implementation supersedes the previously corrupted multi-definition version.
# Backend contract summary (attributes/methods accessed if available):
#   backend.env_blocks -> List[{'offset':int,'size':int,'crc_valid':bool,'vars':Dict[str,str]}]
#   backend.raw_data -> bytes
#   backend.search_compiled_envs(raw:bytes) -> List[Dict[str,str]]
#   backend.repair_uboot_env_block(offset,size) -> (bool, Dict[str,str])
#   backend.force_rebuild_uboot_env_block(offset,size,vars_dict) -> bool
#   backend.patch_uboot_env_vars(offset,size,vars_dict) -> bool
#   backend.last_compiled_env_hits -> optional cache list of dicts

ESSENTIAL_KEYS = ["bootcmd", "bootdelay", "baudrate", "bootargs"]
NUMERIC_KEYS = {"bootdelay", "baudrate"}


class UBootEnvEditorDialog(QDialog):
    """Single clean U-Boot environment editor dialog (view/filter/edit/validate/repair/rebuild)."""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.setWindowTitle("U-Boot Environment Editor")
        self.resize(1100, 640)

        self._compiled_hits: List[Dict[str,str]] = getattr(self.backend, 'last_compiled_env_hits', []) or []
        self.current_block_index: Optional[int] = None
        self.current_vars: Dict[str,str] = {}

        main = QVBoxLayout(self)

        # Block selection
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Block:"))
        self.block_combo = QComboBox()
        for i, blk in enumerate(getattr(self.backend, 'env_blocks', [])):
            status = "OK" if blk.get('crc_valid') else "BADCRC"
            self.block_combo.addItem(f"#{i} @0x{blk['offset']:X} ({blk['size']} bytes) [{status}]")
        self.block_combo.currentIndexChanged.connect(self._on_block_changed)
        top_row.addWidget(self.block_combo)
        top_row.addStretch(1)
        main.addLayout(top_row)

        # Filter & utility row
        util_row = QHBoxLayout()
        util_row.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("substring or /regex/")
        self.filter_edit.textChanged.connect(self._apply_filter)
        util_row.addWidget(self.filter_edit)
        self.template_btn = QPushButton("Insert Template")
        self.template_btn.clicked.connect(self._insert_basic_template)
        util_row.addWidget(self.template_btn)
        self.import_btn = QPushButton("Import Compiled Hit")
        self.import_btn.clicked.connect(self._import_compiled_hit)
        util_row.addWidget(self.import_btn)
        util_row.addStretch(1)
        main.addLayout(util_row)

        # Table of variables
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Key", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.itemChanged.connect(self._on_item_changed)
        main.addWidget(self.table, 1)

        # Recommendation label
        self.reco_label = QLabel()
        self.reco_label.setWordWrap(True)
        main.addWidget(self.reco_label)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_repair_crc = QPushButton("Repair CRC")
        self.btn_repair_crc.clicked.connect(self._repair_crc)
        btn_row.addWidget(self.btn_repair_crc)
        self.btn_force_rebuild = QPushButton("Force Rebuild")
        self.btn_force_rebuild.clicked.connect(self._force_rebuild)
        btn_row.addWidget(self.btn_force_rebuild)
        self.btn_apply = QPushButton("Apply Changes")
        self.btn_apply.clicked.connect(self._apply_changes)
        btn_row.addWidget(self.btn_apply)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        btn_row.addStretch(1)
        main.addLayout(btn_row)

        # Initialize
        if self.block_combo.count():
            self.block_combo.setCurrentIndex(0)
            self._on_block_changed(0)
        self._update_recommendation()

    # ---------- Block handling ----------
    def _on_block_changed(self, idx: int):
        blocks = getattr(self.backend, 'env_blocks', [])
        if idx < 0 or idx >= len(blocks):
            return
        self.current_block_index = idx
        blk = blocks[idx]
        self.current_vars = dict(blk.get('vars', {}))
        self._populate_table()
        self._update_recommendation()

    # ---------- Table population ----------
    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for k, v in sorted(self.current_vars.items()):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(k))
            self.table.setItem(row, 1, QTableWidgetItem(v))
        self.table.blockSignals(False)
        self._apply_filter()

    # ---------- Filtering ----------
    def _apply_filter(self):
        text = self.filter_edit.text().strip()
        regex: Optional[re.Pattern] = None
        if text.startswith('/') and text.endswith('/') and len(text) > 2:
            try:
                regex = re.compile(text[1:-1])
            except re.error:
                regex = None
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).text() if self.table.item(row,0) else ''
            val = self.table.item(row, 1).text() if self.table.item(row,1) else ''
            show = True
            if text:
                if regex:
                    show = bool(regex.search(key) or regex.search(val))
                else:
                    t = text.lower()
                    show = t in key.lower() or t in val.lower()
            self.table.setRowHidden(row, not show)

    # ---------- Editing / validation ----------
    def _on_item_changed(self, _item: QTableWidgetItem):
        new_vars: Dict[str,str] = {}
        duplicate = False
        for r in range(self.table.rowCount()):
            k = self.table.item(r,0).text().strip() if self.table.item(r,0) else ''
            v = self.table.item(r,1).text().strip() if self.table.item(r,1) else ''
            if not k:
                continue
            if k in new_vars:
                duplicate = True
            new_vars[k] = v
        if duplicate:
            QMessageBox.warning(self, "Duplicate", "Duplicate keys are not allowed; change reverted.")
            self._populate_table()
            return
        self.current_vars = new_vars
        self._update_recommendation()

    def _validate(self, vars_dict: Dict[str,str], for_rebuild: bool=False) -> Tuple[bool,str]:
        if len(vars_dict) != len(set(vars_dict.keys())):
            return False, "Duplicate keys"
        for k in NUMERIC_KEYS:
            if k in vars_dict and not vars_dict[k].isdigit():
                return False, f"{k} must be numeric"
        if for_rebuild:
            missing = [k for k in ESSENTIAL_KEYS if k not in vars_dict]
            if missing:
                return False, "Missing essentials: " + ', '.join(missing)
        return True, "OK"

    def _update_recommendation(self):
        if not self.current_vars:
            self.reco_label.setText("No variables.")
            return
        missing = [k for k in ESSENTIAL_KEYS if k not in self.current_vars]
        parts = []
        if missing:
            parts.append("Missing: " + ', '.join(missing))
        for nk in NUMERIC_KEYS:
            if nk in self.current_vars and not self.current_vars[nk].isdigit():
                parts.append(f"{nk} not numeric")
        if not parts:
            parts.append("All essential keys OK")
        self.reco_label.setText(' | '.join(parts))

    # ---------- Template ----------
    def _insert_basic_template(self):
        template = {
            "bootdelay": "3",
            "baudrate": "115200",
            "bootcmd": "run bootcmd_default",
            "bootargs": "console=ttyS0,115200 root=/dev/mtdblock0 rw",
        }
        changed = False
        for k,v in template.items():
            if k not in self.current_vars:
                self.current_vars[k] = v
                changed = True
        if changed:
            self._populate_table()
            self._update_recommendation()
        else:
            QMessageBox.information(self, "Template", "All template keys already exist.")

    # ---------- Import compiled defaults ----------
    def _import_compiled_hit(self):
        if not self._compiled_hits:
            search_fn = getattr(self.backend, 'search_compiled_envs', None)
            if callable(search_fn):
                try:
                    self._compiled_hits = search_fn(self.backend.raw_data) or []
                except Exception:
                    self._compiled_hits = []
        if not self._compiled_hits:
            QMessageBox.information(self, "Compiled", "No compiled env hits available.")
            return
        hit = self._compiled_hits[0]
        added = 0
        for k,v in hit.items():
            if k not in self.current_vars:
                self.current_vars[k] = v
                added += 1
        if added:
            self._populate_table()
            self._update_recommendation()
            QMessageBox.information(self, "Imported", f"Imported {added} keys from compiled hit.")
        else:
            QMessageBox.information(self, "Imported", "No new keys imported.")

    # ---------- CRC repair ----------
    def _repair_crc(self):
        if self.current_block_index is None:
            return
        fn = getattr(self.backend, 'repair_uboot_env_block', None)
        if not callable(fn):
            QMessageBox.warning(self, "Unsupported", "Backend missing repair function")
            return
        blk = self.backend.env_blocks[self.current_block_index]
        ok, new_vars = fn(blk['offset'], blk['size'])
        if ok and new_vars:
            self.current_vars = dict(new_vars)
            self._populate_table()
            self._update_recommendation()
            QMessageBox.information(self, "CRC", "CRC repair successful.")
        else:
            QMessageBox.warning(self, "CRC", "CRC repair failed.")

    # ---------- Force rebuild ----------
    def _force_rebuild(self):
        if self.current_block_index is None:
            return
        valid, msg = self._validate(self.current_vars, for_rebuild=True)
        if not valid:
            QMessageBox.warning(self, "Validation", msg)
            return
        if QMessageBox.question(self, "Confirm", "Force rebuild this entire block?") != QMessageBox.StandardButton.Yes:
            return
        fn = getattr(self.backend, 'force_rebuild_uboot_env_block', None)
        if not callable(fn):
            QMessageBox.warning(self, "Unsupported", "Backend missing force rebuild")
            return
        blk = self.backend.env_blocks[self.current_block_index]
        if fn(blk['offset'], blk['size'], dict(self.current_vars)):
            QMessageBox.information(self, "Rebuild", "Block rebuilt.")
            self._refresh_block_metadata()
        else:
            QMessageBox.warning(self, "Rebuild", "Rebuild failed.")

    def _refresh_block_metadata(self):
        blocks = getattr(self.backend, 'env_blocks', [])
        for i, blk in enumerate(blocks):
            status = "OK" if blk.get('crc_valid') else "BADCRC"
            if i < self.block_combo.count():
                self.block_combo.setItemText(i, f"#{i} @0x{blk['offset']:X} ({blk['size']} bytes) [{status}]")

    # ---------- Apply changes ----------
    def _apply_changes(self):
        if self.current_block_index is None:
            return
        valid, msg = self._validate(self.current_vars)
        if not valid:
            QMessageBox.warning(self, "Validation", msg)
            return
        fn = getattr(self.backend, 'patch_uboot_env_vars', None)
        if not callable(fn):
            QMessageBox.warning(self, "Unsupported", "Backend missing patch function")
            return
        blk = self.backend.env_blocks[self.current_block_index]
        if fn(blk['offset'], blk['size'], dict(self.current_vars)):
            QMessageBox.information(self, "Apply", "Patch applied (layered strategy).")
            self._refresh_block_metadata()
        else:
            QMessageBox.warning(self, "Apply", "Patch failed.")

    # ---------- Dialog overrides ----------
    def accept(self):  # keep default
        super().accept()

    def reject(self):  # keep default
        super().reject()


