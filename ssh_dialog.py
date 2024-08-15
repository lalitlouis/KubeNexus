import paramiko
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QMessageBox, QLineEdit

class SSHDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Terminal")
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout(self)
        
        self.terminal = QTextEdit(self)
        self.terminal.setReadOnly(True)
        layout.addWidget(self.terminal)

        self.input = QLineEdit(self)
        self.input.returnPressed.connect(self.send_command)
        layout.addWidget(self.input)

        self.close_button = QPushButton("Close SSH", self)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.ssh_client = None

    def set_ssh_client(self, ssh_client):
        self.ssh_client = ssh_client

    def send_command(self):
        if self.ssh_client:
            command = self.input.text()
            self.input.clear()
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            output = stdout.read().decode()
            self.terminal.append(f"> {command}")
            self.terminal.append(output)

    def closeEvent(self, event):
        if self.ssh_client:
            self.ssh_client.close()
        super().closeEvent(event)