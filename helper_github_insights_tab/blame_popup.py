from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLabel
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import requests

class BlameWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, token, org_name, repo, branch, file_path, line_number):
        super().__init__()
        self.token = token
        self.org_name = org_name
        self.repo = repo
        self.branch = branch
        self.file_path = file_path
        self.line_number = line_number

    def run(self):
        headers = {"Authorization": f"token {self.token}"}
        try:
            content_url = f"https://github.hpe.com/api/v3/repos/{self.org_name}/{self.repo}/contents/{self.file_path}?ref={self.branch}"
            content_response = requests.get(content_url, headers=headers)
            content_response.raise_for_status()
            file_sha = content_response.json()['sha']

            commits_url = f"https://github.hpe.com/api/v3/repos/{self.org_name}/{self.repo}/commits?path={self.file_path}&sha={self.branch}"
            commits_response = requests.get(commits_url, headers=headers)
            commits_response.raise_for_status()
            commits = commits_response.json()

            if commits:
                last_commit = commits[0]
                author = last_commit['commit']['author']['name']
                date = last_commit['commit']['author']['date']
                message = last_commit['commit']['message']
                sha = last_commit['sha']

                blame_info = f"File: {self.file_path}\n"
                blame_info += f"Line: {self.line_number}\n"
                blame_info += f"Last modified by: {author}\n"
                blame_info += f"Date: {date}\n"
                blame_info += f"Commit: {sha}\n"
                blame_info += f"Message: {message}\n"
            else:
                blame_info = "No commit history found for this file."
        except requests.exceptions.RequestException as e:
            blame_info = f"Error fetching blame data: {str(e)}"

        self.finished.emit(blame_info)

class BlamePopup(QDialog):
    def __init__(self, parent, token, org_name, repo, branch, file_path, line_number):
        super().__init__(parent)
        self.token = token
        self.org_name = org_name
        self.repo = repo
        self.branch = branch
        self.file_path = file_path
        self.line_number = line_number
        self.setup_ui()
        self.load_blame_info()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.setLayout(layout)
        self.setWindowTitle(f"Blame Info for {self.file_path}:{self.line_number}")
        self.blame_text = QTextEdit(self)
        self.blame_text.setReadOnly(True)
        layout.addWidget(self.blame_text)
        self.setMinimumSize(400, 300)

    def load_blame_info(self):
        self.blame_text.setText("Loading blame information...")
        self.worker = BlameWorker(self.token, self.org_name, self.repo, self.branch, self.file_path, self.line_number)
        self.worker.finished.connect(self.update_blame_text)
        self.worker.start()

    def update_blame_text(self, blame_info):
        self.blame_text.setText(blame_info)