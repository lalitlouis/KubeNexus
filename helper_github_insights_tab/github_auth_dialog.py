from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import Qt
import keyring

class GitHubAuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GitHub Authentication")
        self.setModal(True)
        self.token = None

        layout = QVBoxLayout(self)

        label = QLabel("Please enter your GitHub Personal Access Token:")
        layout.addWidget(label)

        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.token_input)

        submit_button = QPushButton("Submit")
        submit_button.clicked.connect(self.submit_token)
        layout.addWidget(submit_button)

    def submit_token(self):
        self.token = self.token_input.text()
        if self.token:
            keyring.set_password("github_insights", "github_token", self.token)
            self.accept()
        else:
            QLabel("Token cannot be empty").show()