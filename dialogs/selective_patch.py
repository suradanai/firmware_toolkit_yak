from PySide6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QHBoxLayout, QPushButton, QLineEdit

class SelectivePatchDialog(QDialog):
    """Lightweight dialog to pick a set of patch actions.
    Extracted from legacy firmware_workbench.app to allow removal of that module.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("เลือกชุด Patch")
        self.setModal(True)
        lay = QVBoxLayout(self)
        self.cb_boot = QCheckBox("ปรับ Boot Delay -> 1")
        self.cb_serial = QCheckBox("เปิด Shell Debug ผ่าน Serial")
        self.cb_net = QCheckBox("ปิด Telnet / FTP (Shell Network)")
        self.cb_rootpw = QCheckBox("ตั้งรหัสผ่าน root (ใช้ค่าจากช่องด้านหลัก หรือ admin1234)")
        for cb in (self.cb_boot, self.cb_serial, self.cb_net, self.cb_rootpw):
            lay.addWidget(cb)
        btns = QHBoxLayout()
        btn_ok = QPushButton("ตกลง"); btn_cancel = QPushButton("ยกเลิก")
        btn_ok.clicked.connect(self.accept); btn_cancel.clicked.connect(self.reject)
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
            parent_pw = getattr(self.parent(), 'rootpw_edit', None)
            if parent_pw and isinstance(parent_pw, QLineEdit):
                val = parent_pw.text().strip()
                actions['root_password_value'] = val or "admin1234"
            else:
                actions['root_password_value'] = "admin1234"
        return actions
