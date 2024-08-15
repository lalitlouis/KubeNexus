from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QListWidget, QPushButton, QMessageBox, QProgressDialog,
                             QListWidgetItem, QDialogButtonBox)
from PyQt5.QtCore import Qt
import requests
from requests.auth import HTTPBasicAuth


JIRA_BASE_URL = "https://jira-pro.it.hpe.com:8443"

class ProjectSelectionDialog(QDialog):
    def __init__(self, parent=None, jira_email=None, jira_token=None):
        super().__init__(parent)
        self.jira_email = jira_email
        self.jira_token = jira_token
        self.selected_projects = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Select JIRA Projects")
        self.resize(600, 400)  # Increased size of the dialog
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)  # Increased spacing between widgets

        self.project_list = QListWidget()
        self.project_list.setSelectionMode(QListWidget.MultiSelection)
        self.project_list.setFont(self.project_list.font().setPointSize(12))  # Increased font size
        layout.addWidget(self.project_list)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.setStyleSheet("QPushButton { padding: 10px; font-size: 14px; }")  # Increased button size and font
        layout.addWidget(button_box)

        self.load_projects()
        
        # Center the dialog on the screen
        self.center()

    def load_projects(self):
        progress = QProgressDialog("Loading projects...", "Cancel", 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        try:
            response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/project",
                auth=HTTPBasicAuth(self.jira_email, self.jira_token)
            )
            response.raise_for_status()
            projects = response.json()

            for project in projects:
                item = QListWidgetItem(f"{project['key']} - {project['name']}")
                item.setData(Qt.UserRole, project['key'])
                self.project_list.addItem(item)

        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to load projects: {str(e)}")

        progress.close()

    def accept(self):
        self.selected_projects = [item.data(Qt.UserRole) for item in self.project_list.selectedItems()]
        super().accept()