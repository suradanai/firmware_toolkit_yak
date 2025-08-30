from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

class SpecialFunctionsWindow(QWidget):
    """Minimal placeholder for legacy 'special functions' window.
    Extend as needed later.
    """
    def __init__(self, main_win):
        super().__init__(main_win)
        self.setWindowTitle("Special Functions")
        lay = QVBoxLayout(self)
        for text, slot in [
            ("Edit RootFS File", getattr(main_win, 'edit_rootfs_file', lambda: None)),
            ("Run Custom Script", getattr(main_win, 'run_custom_script', lambda: None)),
            ("Check Hash/Signature", getattr(main_win, 'check_hash_signature', lambda: None)),
            ("Export Patch Profile", getattr(main_win, 'export_patch_profile', lambda: None)),
            ("Import Patch Profile", getattr(main_win, 'import_patch_profile', lambda: None)),
        ]:
            b = QPushButton(text); b.clicked.connect(slot); lay.addWidget(b)
        lay.addStretch()
        close_btn = QPushButton("ปิดหน้าต่างนี้"); close_btn.clicked.connect(self.close); lay.addWidget(close_btn)
