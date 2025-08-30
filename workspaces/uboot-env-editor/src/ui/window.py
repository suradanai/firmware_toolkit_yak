from PyQt5.QtWidgets import QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QMessageBox

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("U-Boot Environment Editor")
        self.setGeometry(100, 100, 800, 600)  # Increased width for better visibility

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        self.label = QLabel("Welcome to the U-Boot Environment Editor")
        layout.addWidget(self.label)

        self.editButton = QPushButton("Edit Environment")
        self.editButton.clicked.connect(self.edit_environment)
        layout.addWidget(self.editButton)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def edit_environment(self):
        # Placeholder for the edit environment functionality
        QMessageBox.information(self, "Edit Environment", "This will open the environment editing functionality.")