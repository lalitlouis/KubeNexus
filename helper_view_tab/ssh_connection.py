from PyQt5.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QPushButton, QButtonGroup
from PyQt5.QtCore import QThread, pyqtSignal
import paramiko

class SSHAuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Authentication Method")
        layout = QVBoxLayout(self)

        self.auth_group = QButtonGroup(self)
        self.passkey_radio = QRadioButton("Use Passkey (SSH Key)")
        self.password_radio = QRadioButton("Use Password")
        self.auth_group.addButton(self.passkey_radio)
        self.auth_group.addButton(self.password_radio)
        self.passkey_radio.setChecked(True)

        layout.addWidget(self.passkey_radio)
        layout.addWidget(self.password_radio)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        layout.addWidget(self.ok_button)

    def get_auth_method(self):
        return "passkey" if self.passkey_radio.isChecked() else "password"


class SSHConnectionThread(QThread):
    connection_established = pyqtSignal(paramiko.SSHClient, paramiko.Channel, str, str)
    connection_failed = pyqtSignal(str)

    def __init__(self, hostname, username, auth_method, auth_data):
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.auth_method = auth_method
        self.auth_data = auth_data

    def run(self):
        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if self.auth_method == "passkey":
                ssh_client.connect(self.hostname, username=self.username, key_filename=self.auth_data, timeout=10)
            else:  # password
                ssh_client.connect(self.hostname, username=self.username, password=self.auth_data, timeout=10)

            ssh_channel = ssh_client.invoke_shell(term='xterm')
            ssh_channel.settimeout(0.01)

            self.connection_established.emit(ssh_client, ssh_channel, self.username, self.auth_method)
        except Exception as e:
            self.connection_failed.emit(str(e))
