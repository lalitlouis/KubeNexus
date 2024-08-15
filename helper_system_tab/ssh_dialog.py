from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QMessageBox, QRadioButton, QButtonGroup)
import paramiko

class SSHDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Connection")
        self.setGeometry(100, 100, 300, 250)
        
        layout = QVBoxLayout(self)
        
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("Host")
        layout.addWidget(self.host_input)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        layout.addWidget(self.username_input)
        
        # Radio buttons for authentication method
        auth_layout = QHBoxLayout()
        self.password_radio = QRadioButton("Password")
        self.key_radio = QRadioButton("SSH Key")
        auth_group = QButtonGroup(self)
        auth_group.addButton(self.password_radio)
        auth_group.addButton(self.key_radio)
        auth_layout.addWidget(self.password_radio)
        auth_layout.addWidget(self.key_radio)
        layout.addLayout(auth_layout)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        
        self.passkey_input = QLineEdit()
        self.passkey_input.setPlaceholderText("SSH Key Passphrase")
        self.passkey_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.passkey_input)
        
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_ssh)
        layout.addWidget(self.connect_button)
        
        self.ssh_client = None
        
        # Set default to password authentication
        self.password_radio.setChecked(True)
        self.passkey_input.setEnabled(False)
        
        # Connect radio buttons to enable/disable fields
        self.password_radio.toggled.connect(self.toggle_auth_fields)
        self.key_radio.toggled.connect(self.toggle_auth_fields)

    def toggle_auth_fields(self):
        is_password = self.password_radio.isChecked()
        self.password_input.setEnabled(is_password)
        self.passkey_input.setEnabled(not is_password)

    def connect_ssh(self):
        host = self.host_input.text()
        username = self.username_input.text()
        
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if self.password_radio.isChecked():
                password = self.password_input.text()
                self.ssh_client.connect(hostname=host, username=username, password=password)
            else:
                passkey = self.passkey_input.text()
                # Here we assume the SSH key is in the default location (~/.ssh/id_rsa)
                # You might want to add an option to specify the key file path if needed
                self.ssh_client.connect(hostname=host, username=username, key_filename='~/.ssh/id_rsa', passphrase=passkey)
            
            QMessageBox.information(self, "SSH Connection", "Successfully connected to SSH server.")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "SSH Connection Error", f"Could not connect to SSH server: {str(e)}")
            self.ssh_client = None