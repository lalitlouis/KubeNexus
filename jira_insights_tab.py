import sys
import os
import json
import requests
import markdown
from datetime import datetime
from cryptography.fernet import Fernet
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtGui import QPainter, QColor
from requests.auth import HTTPBasicAuth
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, 
                             QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, 
                             QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox, 
                             QSplitter, QFileDialog, QHeaderView, QTextBrowser)
from PyQt5.QtCore import Qt, QThreadPool, QRunnable, pyqtSlot, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QHBoxLayout, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtCore import QUrl, pyqtSignal
from PyQt5.QtWebEngineCore import QWebEngineCookieStore
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QPushButton, QLabel, QFrame
from PyQt5.QtGui import QPixmap, QImage, QTextCursor
from PyQt5.QtCore import Qt
from io import BytesIO
from jira import JIRA
from PyQt5.QtWidgets import QTextEdit, QCompleter
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtCore import QStringListModel
from PyQt5.QtWidgets import QTextEdit, QCompleter
from PyQt5.QtCore import Qt, QTimer
from helper_jira_insights_tab.rich_text_editor import RichTextEditor, AutocompleteComboBox

import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


JIRA_BASE_URL = "https://jira-pro.it.hpe.com:8443"
CREDS_FILE = os.path.expanduser("~/.jira_creds.enc")
KEY_FILE = os.path.expanduser("~/.jira_key")
PROJECTS_FILE = os.path.expanduser("~/.jira_selected_projects.json")


class CommentWidget(QWidget):
    def __init__(self, comment, parent=None):
        super().__init__(parent)
        self.comment = comment
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()
        author_label = QLabel(f"<b>{self.comment['author']['displayName']}</b>")
        time_label = QLabel(self.parent.get_relative_time(self.comment['created']))
        header_layout.addWidget(author_label)
        header_layout.addWidget(time_label)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Comment body
        body_label = QTextBrowser()
        body_label.setHtml(self.parent.markdown_to_html(self.comment['body']))
        body_label.setOpenExternalLinks(True)
        layout.addWidget(body_label)


class MentionTextEdit(QTextEdit):
    def __init__(self, fetch_users_callback, parent=None):
        super().__init__(parent)
        self.fetch_users_callback = fetch_users_callback
        self.completer = QCompleter(self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)
        self.mention_pos = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.update_completions)

    def keyPressEvent(self, event):
        if self.completer.popup().isVisible():
            if event.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab):
                event.ignore()
                return
        super().keyPressEvent(event)
        if event.key() == Qt.Key_At:
            self.mention_pos = self.textCursor().position()
        elif self.mention_pos:
            cursor = self.textCursor()
            if cursor.position() - self.mention_pos > 1:
                self.timer.start(200)  # Delay to avoid too frequent API calls

    def update_completions(self):
        cursor = self.textCursor()
        current_pos = cursor.position()
        if current_pos > self.mention_pos:
            text = self.toPlainText()[self.mention_pos:current_pos]
            users = self.fetch_users_callback(text)
            self.completer.setModel(QStringListModel([user['displayName'] for user in users]))
            self.completer.setCompletionPrefix(text)
            popup = self.completer.popup()
            popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
            cursor.setPosition(self.mention_pos)
            rect = self.cursorRect(cursor)
            rect.setWidth(self.completer.popup().sizeHintForColumn(0) + 
                          self.completer.popup().verticalScrollBar().sizeHint().width())
            self.completer.complete(rect)
        else:
            self.mention_pos = 0

    def insert_completion(self, completion):
        cursor = self.textCursor()
        cursor.setPosition(self.mention_pos - 1, QTextCursor.MoveAnchor)
        cursor.movePosition(QTextCursor.EndOfWord, QTextCursor.KeepAnchor)
        cursor.insertText(f"@{completion} ")
        self.setTextCursor(cursor)
        self.mention_pos = 0


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(object)

class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

class LoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        
        self.loading_label = QLabel("Loading...", self)
        self.loading_label.setStyleSheet("""
            background-color: #2a2a2a;
            color: white;
            border: 2px solid #3a3a3a;
            border-radius: 5px;
            padding: 10px;
            font-size: 16px;
        """)
        layout.addWidget(self.loading_label)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate progress
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(200, 20)
        layout.addWidget(self.progress)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 128))  # # Semi-transparent black

    def showEvent(self, event):
        self.setGeometry(self.parent().rect())

class JiraAuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JIRA Authentication")
        layout = QVBoxLayout(self)
        
        message = QLabel("Please enter your JIRA bearer token.")
        layout.addWidget(message)
        
        form_layout = QFormLayout()
        self.token_input = QLineEdit(self)
        self.token_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("JIRA Bearer Token:", self.token_input)
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_credentials(self):
        return self.token_input.text()
    
class JiraInsightsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = requests.Session()
        self.jira_token = self.get_jira_credentials()
        self.session.headers.update({"Authorization": f"Bearer {self.jira_token}"})
        self.current_start = 0
        self.issues_per_load = 10
        self.total_issues = 0
        self.threadpool = QThreadPool()
        self.is_loading = False
        self.current_tab = "personal"
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
        self.searched_issues = []
        
        if self.jira_token:
            self.selected_projects = self.load_selected_projects()
            self.init_ui()
            QTimer.singleShot(0, self.initialize_data)
        else:
            self.show_auth_failed_message()

    def initialize_data(self):
        self.show_loading_overlay()
        self.load_data_async("personal")

    def show_loading_overlay(self):
        self.loading_overlay.show()
        self.loading_overlay.raise_()
        QApplication.processEvents()

    def hide_loading_overlay(self):
        self.loading_overlay.hide()
        QApplication.processEvents()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.setGeometry(self.rect())

    def get_jira_credentials(self):
        if os.path.exists(CREDS_FILE) and os.path.exists(KEY_FILE):
            with open(KEY_FILE, 'rb') as key_file:
                key = key_file.read()
            fernet = Fernet(key)
            with open(CREDS_FILE, 'rb') as cred_file:
                encrypted_creds = cred_file.read()
            token = fernet.decrypt(encrypted_creds).decode()
            return token
        else:
            return self.prompt_for_credentials()

    def prompt_for_credentials(self):
        dialog = JiraAuthDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            token = dialog.get_credentials()
            if self.verify_credentials(token):
                self.save_credentials(token)
                return token
            else:
                QMessageBox.critical(self, "Authentication Failed", "Invalid token. Please try again.")
        return None

    def verify_credentials(self, token):
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/myself",
                headers=headers
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def save_credentials(self, token):
        key = Fernet.generate_key()
        fernet = Fernet(key)
        encrypted_token = fernet.encrypt(token.encode())
        with open(KEY_FILE, 'wb') as key_file:
            key_file.write(key)
        with open(CREDS_FILE, 'wb') as cred_file:
            cred_file.write(encrypted_token)


    def show_auth_failed_message(self):
        QMessageBox.critical(self, "Authentication Required", "JIRA credentials are required to use this feature.")

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget(self)
        layout.addWidget(self.tab_widget)

        personal_tab = QWidget()
        personal_layout = QVBoxLayout(personal_tab)
        self.setup_common_tab(personal_layout, "personal")
        self.tab_widget.addTab(personal_tab, "Personal Issues")

        reported_tab = QWidget()
        reported_layout = QVBoxLayout(reported_tab)
        self.setup_common_tab(reported_layout, "reported")
        self.tab_widget.addTab(reported_tab, "Reported by Me")

        project_tab = QWidget()
        project_layout = QVBoxLayout(project_tab)
        self.setup_common_tab(project_layout, "project")
        self.tab_widget.addTab(project_tab, "Project Issues")

        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)
        self.setup_search_tab(search_layout)
        self.tab_widget.addTab(search_tab, "Search Issues")

        self.tab_widget.currentChanged.connect(self.on_tab_change)

        self.setLayout(layout)
        
    def setup_common_tab(self, layout, tab_type):
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        filter_layout = QHBoxLayout()
        severity_filter = QComboBox()
        severity_filter.addItem("All Severities")
        severity_filter.currentIndexChanged.connect(self.filter_issues)

        status_filter = QComboBox()
        status_filter.addItem("All Statuses")
        status_filter.currentIndexChanged.connect(self.filter_issues)

        release_filter = QComboBox()
        release_filter.addItem("All Releases")
        release_filter.currentIndexChanged.connect(self.filter_issues)

        if tab_type == "project" or tab_type == "search":
            project_filter = QComboBox()
            self.selected_projects = self.load_selected_projects()
            project_filter.addItems(self.selected_projects)
            if tab_type == "project":
                project_filter.currentIndexChanged.connect(self.load_project_issues)
            filter_layout.addWidget(QLabel("Project:"))
            filter_layout.addWidget(project_filter)
            self.project_filter = project_filter

        filter_layout.addWidget(QLabel("Severity:"))
        filter_layout.addWidget(severity_filter)
        filter_layout.addWidget(QLabel("Status:"))
        filter_layout.addWidget(status_filter)
        filter_layout.addWidget(QLabel("Release:"))
        filter_layout.addWidget(release_filter)
        left_layout.addLayout(filter_layout)

        search_filter = QLineEdit()
        search_filter.setPlaceholderText("Search issues...")
        search_filter.textChanged.connect(self.filter_issues)
        left_layout.addWidget(search_filter)

        issues_table = QTableWidget()
        self.setup_issues_table(issues_table, include_assignee=(tab_type != "personal"))
        left_layout.addWidget(issues_table)

        fetch_more_button = QPushButton("Fetch 10 more issues")
        fetch_more_button.clicked.connect(self.load_more_data)
        left_layout.addWidget(fetch_more_button)

        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        button_layout = QHBoxLayout()
        download_btn = QPushButton("Download")
        refresh_btn = QPushButton("Refresh")
        edit_btn = QPushButton("Edit")
        add_comment_btn = QPushButton("Add Comment")
        
        for btn in [download_btn, refresh_btn, edit_btn, add_comment_btn]:
            button_layout.addWidget(btn)
            btn.setVisible(False)

        right_layout.addLayout(button_layout)

        details_tab_widget = QTabWidget()
        description_tab = QTextBrowser()
        description_tab.setStyleSheet("QTextBrowser { margin: 10px; }")
        
        comments_tab = QWidget()
        comments_tab_layout = QVBoxLayout(comments_tab)
        comments_scroll_area = QScrollArea()
        comments_scroll_area.setWidgetResizable(True)
        comments_content = QWidget()
        comments_content.setLayout(QVBoxLayout())  # Initialize the layout here
        comments_scroll_area.setWidget(comments_content)
        comments_tab_layout.addWidget(comments_scroll_area)
        
        attachments_tab = QWidget()
        activity_tab = QTextBrowser()
        activity_tab.setStyleSheet("QTextBrowser { margin: 10px; }")

        details_tab_widget.addTab(description_tab, "Description")
        details_tab_widget.addTab(comments_tab, "Comments")
        details_tab_widget.addTab(attachments_tab, "Attachments")
        details_tab_widget.addTab(activity_tab, "Activity")

        right_layout.addWidget(details_tab_widget)
        splitter.addWidget(right_widget)



        # Ensure the splitter is set to 50-50
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        download_btn.clicked.connect(self.download_description)
        refresh_btn.clicked.connect(self.refresh_issue)
        edit_btn.clicked.connect(self.edit_issue)
        add_comment_btn.clicked.connect(self.add_comment)

        if tab_type == "personal":
            self.personal_severity_filter = severity_filter
            self.personal_status_filter = status_filter
            self.personal_release_filter = release_filter
            self.personal_search_filter = search_filter
            self.personal_issues_table = issues_table
            self.personal_fetch_more_button = fetch_more_button
            self.personal_description_tab = description_tab
            self.personal_comments_content = comments_content
            self.personal_attachments_tab = attachments_tab
            self.personal_activity_tab = activity_tab
            self.personal_details_tab_widget = details_tab_widget
            self.personal_download_btn = download_btn
            self.personal_refresh_btn = refresh_btn
            self.personal_edit_btn = edit_btn
            self.personal_add_comment_btn = add_comment_btn
        elif tab_type == "reported":
            self.reported_severity_filter = severity_filter
            self.reported_status_filter = status_filter
            self.reported_release_filter = release_filter
            self.reported_search_filter = search_filter
            self.reported_issues_table = issues_table
            self.reported_fetch_more_button = fetch_more_button
            self.reported_description_tab = description_tab
            self.reported_comments_content = comments_content
            self.reported_attachments_tab = attachments_tab
            self.reported_activity_tab = activity_tab
            self.reported_details_tab_widget = details_tab_widget
            self.reported_download_btn = download_btn
            self.reported_refresh_btn = refresh_btn
            self.reported_edit_btn = edit_btn
            self.reported_add_comment_btn = add_comment_btn
        if tab_type == "project":
            self.project_severity_filter = severity_filter
            self.project_status_filter = status_filter
            self.project_release_filter = release_filter
            self.project_search_filter = search_filter
            self.project_issues_table = issues_table
            self.project_fetch_more_button = fetch_more_button
            self.project_description_tab = description_tab
            self.project_comments_content = comments_content
            self.project_attachments_tab = attachments_tab
            self.project_activity_tab = activity_tab
            self.project_details_tab_widget = details_tab_widget
            self.project_download_btn = download_btn
            self.project_refresh_btn = refresh_btn
            self.project_edit_btn = edit_btn
            self.project_add_comment_btn = add_comment_btn
            
            # Load issues for the first project
            if self.selected_projects:
                self.load_project_issues()
        elif tab_type == "search":
            self.search_severity_filter = severity_filter
            self.search_status_filter = status_filter
            self.search_release_filter = release_filter
            self.search_search_filter = search_filter
            self.search_issues_table = issues_table
            self.search_fetch_more_button = fetch_more_button
            self.search_description_tab = description_tab
            self.search_comments_content = comments_content
            self.search_attachments_tab = attachments_tab
            self.search_activity_tab = activity_tab
            self.search_details_tab_widget = details_tab_widget
            self.search_download_btn = download_btn
            self.search_refresh_btn = refresh_btn
            self.search_edit_btn = edit_btn
            self.search_add_comment_btn = add_comment_btn

        self.load_data_async(tab_type)

    def setup_search_tab(self, layout):
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Search row: Project dropdown, Issue number input, and Apply button
        search_row_layout = QHBoxLayout()
        
        self.search_project_filter = QComboBox()
        self.search_project_filter.addItems(self.selected_projects)
        self.search_project_filter.setFixedWidth(100)  # Set fixed width to 100px
        search_row_layout.addWidget(QLabel("Project:"))
        search_row_layout.addWidget(self.search_project_filter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter JIRA issue number...")
        search_row_layout.addWidget(self.search_input)

        search_apply_btn = QPushButton("Apply")
        search_apply_btn.clicked.connect(self.apply_search)
        search_row_layout.addWidget(search_apply_btn)

        left_layout.addLayout(search_row_layout)

        # Issues table
        self.search_issues_table = QTableWidget()
        self.setup_issues_table(self.search_issues_table)
        left_layout.addWidget(self.search_issues_table)

        splitter.addWidget(left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        button_layout = QHBoxLayout()
        self.search_download_btn = QPushButton("Download")
        self.search_refresh_btn = QPushButton("Refresh")
        self.search_edit_btn = QPushButton("Edit")
        self.search_add_comment_btn = QPushButton("Add Comment")
        
        for btn in [self.search_download_btn, self.search_refresh_btn, self.search_edit_btn, self.search_add_comment_btn]:
            button_layout.addWidget(btn)
            btn.setVisible(False)

        right_layout.addLayout(button_layout)

        details_tab_widget = QTabWidget()
        self.search_description_tab = QTextBrowser()
        self.search_description_tab.setStyleSheet("QTextBrowser { margin: 10px; }")
        self.search_comments_tab = QTextBrowser()
        self.search_comments_tab.setStyleSheet("QTextBrowser { margin: 10px; }")
        self.search_attachments_tab = QWidget()

        details_tab_widget.addTab(self.search_description_tab, "Description")
        details_tab_widget.addTab(self.search_comments_tab, "Comments")
        details_tab_widget.addTab(self.search_attachments_tab, "Attachments")

        right_layout.addWidget(details_tab_widget)
        splitter.addWidget(right_widget)

        # Set the splitter to 50-50
        splitter.setSizes([int(self.width() * 0.5), int(self.width() * 0.5)])

        self.search_download_btn.clicked.connect(self.download_description)
        self.search_refresh_btn.clicked.connect(self.refresh_issue)
        self.search_edit_btn.clicked.connect(self.edit_issue)
        self.search_add_comment_btn.clicked.connect(self.add_comment)

        layout.addWidget(splitter)

    def apply_search(self):
        project = self.search_project_filter.currentText()
        issue_number = self.search_input.text().strip()
        if project and issue_number:
            query = f"{project}-{issue_number}"
            self.search_issues_table.setRowCount(0)  # Clear the table
            self.load_single_issue(query)
        else:
            QMessageBox.warning(self, "Warning", "Please select a project and enter an issue number.")

    def load_issue_and_add_to_table(self, issue_key):
        try:
            issue = self.fetch_issue_details(issue_key)
            self.add_issue_to_table(self.search_issues_table, issue)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load issue: {str(e)}")

    def load_data_async(self, tab_type, query=None):
        if self.is_loading:
            return

        self.is_loading = True
        self.show_loading_overlay()

        worker = Worker(self.fetch_issues, tab_type, query)
        worker.signals.result.connect(lambda issues: self.update_issues_table(tab_type, issues))
        worker.signals.finished.connect(self.finish_loading)
        worker.signals.error.connect(self.handle_error)
        self.threadpool.start(worker)
    
    def update_issues_table(self, tab_type, issues):
        if tab_type == "personal":
            self.update_personal_issues_table(issues)
        elif tab_type == "reported":
            self.update_reported_issues_table(issues)
        elif tab_type == "project":
            self.update_project_issues_table(issues)
        elif tab_type == "search":
            self.update_search_issues_table(issues)
    
    def load_single_issue(self, issue_key):
        print(f"Searching for issue: {issue_key}")  # Debug print
        headers = {
            "Authorization": f"Bearer {self.jira_token}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}",
                headers=headers
            )
            response.raise_for_status()
            issue_data = response.json()
            print(f"Issue data received: {issue_data}")  # Debug print
            
            # Check if the issue is already in the list
            if not any(issue['key'] == issue_data['key'] for issue in self.searched_issues):
                self.searched_issues.append(issue_data)
            
            self.update_search_table(issue_data)
            self.show_issue_details_async(issue_key)
        except requests.RequestException as e:
            print(f"Error fetching issue: {str(e)}")  # Debug print
            QMessageBox.warning(self, "Error", f"Failed to fetch issue: {str(e)}")

    def update_search_table(self, issue_data):
        self.search_issues_table.setRowCount(0)
        for issue in self.searched_issues:
            self.add_issue_to_table(self.search_issues_table, issue_data, include_assignee=True)
    
    def load_project_issues(self):
        try:
            self.current_start = 0
            self.project_issues_table.setRowCount(0)
            selected_project = self.project_filter.currentText()
            if not selected_project:
                raise ValueError("No project selected")
            self.load_data_async("project")
        except ValueError as e:
            QMessageBox.warning(self, "Warning", str(e))
    
    def add_issue_to_table(self, table, issue, include_assignee=True):
        row_position = table.rowCount()
        table.insertRow(row_position)
        table.setItem(row_position, 0, QTableWidgetItem(issue['key']))
        table.setItem(row_position, 1, QTableWidgetItem(issue['fields']['summary']))
        
        col = 2
        if include_assignee:
            assignee = issue['fields'].get('assignee', {})
            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
            table.setItem(row_position, col, QTableWidgetItem(assignee_name))
            col += 1
        
        table.setItem(row_position, col, QTableWidgetItem(issue['fields']['status']['name']))
        col += 1
        table.setItem(row_position, col, QTableWidgetItem(issue['fields'].get('priority', {}).get('name', 'N/A')))
        col += 1

        fix_versions = issue['fields'].get('fixVersions', [])
        fix_version = fix_versions[0]['name'] if fix_versions else 'N/A'
        table.setItem(row_position, col, QTableWidgetItem(fix_version))
        col += 1

        updated = self.get_relative_time(issue['fields']['updated'])
        table.setItem(row_position, col, QTableWidgetItem(updated))

    def finish_loading(self):
        self.is_loading = False
        self.hide_loading_overlay()
        self.current_start += self.issues_per_load

    def update_personal_issues_table(self, issues):
        for issue in issues:
            self.add_issue_to_table(self.personal_issues_table, issue, include_assignee=False)
        self.update_filter_options(issues)

    def update_reported_issues_table(self, issues):
        for issue in issues:
            self.add_issue_to_table(self.reported_issues_table, issue, include_assignee=True)
        self.update_filter_options(issues)

    def update_project_issues_table(self, issues):
        for issue in issues:
            self.add_issue_to_table(self.project_issues_table, issue, include_assignee=True)
        self.update_filter_options(issues)

    def update_search_issues_table(self, issues):
        for issue in issues:
            self.add_issue_to_table(self.search_issues_table, issue, include_assignee=True)
        self.update_filter_options(issues)

    def fetch_issues(self, tab_type, query=None):
        jql = ""
        if tab_type == "personal":
            jql = "assignee=currentUser() ORDER BY updated DESC"
        elif tab_type == "reported":
            jql = "reporter=currentUser() ORDER BY updated DESC"
        elif tab_type == "project":
            project = self.project_filter.currentText()
            if not project:
                raise ValueError("No project selected")
            jql = f'project="{project}" ORDER BY updated DESC'
        elif tab_type == "search" and query:
            jql = f"key={query}"

        if not jql:
            raise ValueError("Invalid tab type or missing query")

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/search",
            params={
                "jql": jql,
                "startAt": self.current_start,
                "maxResults": self.issues_per_load
            },
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        response.raise_for_status()
        data = response.json()
        self.total_issues = data.get('total', 0)
        issues = data.get('issues', [])
        return issues

    def filter_issues(self):
        if self.current_tab == "personal":
            table = self.personal_issues_table
            filter_text = self.personal_search_filter.text().lower()
            selected_severity = self.personal_severity_filter.currentText()
            selected_status = self.personal_status_filter.currentText()
            selected_release = self.personal_release_filter.currentText()
        elif self.current_tab == "reported":
            table = self.reported_issues_table
            filter_text = self.reported_search_filter.text().lower()
            selected_severity = self.reported_severity_filter.currentText()
            selected_status = self.reported_status_filter.currentText()
            selected_release = self.reported_release_filter.currentText()
        elif self.current_tab == "project":
            table = self.project_issues_table
            filter_text = self.project_search_filter.text().lower()
            selected_severity = self.project_severity_filter.currentText()
            selected_status = self.project_status_filter.currentText()
            selected_release = self.project_release_filter.currentText()
        elif self.current_tab == "search":
            table = self.search_issues_table
            filter_text = self.search_search_filter.text().lower()
            selected_severity = self.search_severity_filter.currentText()
            selected_status = self.search_status_filter.currentText()
            selected_release = self.search_release_filter.currentText()

        for row in range(table.rowCount()):
            match = True
            if filter_text:
                match = any(
                    filter_text in table.item(row, col).text().lower()
                    for col in range(table.columnCount())
                )
            if selected_severity != "All Severities":
                match &= (selected_severity == table.item(row, 3).text())
            if selected_status != "All Statuses":
                match &= (selected_status == table.item(row, 2).text())
            if selected_release != "All Releases":
                match &= (selected_release == table.item(row, 4).text())

            table.setRowHidden(row, not match)

    def setup_issues_table(self, table, include_assignee=True):
        columns = ["Key", "Title", "Status", "Severity", "Release", "Updated"]
        if include_assignee:
            columns.insert(2, "Assignee")  # Insert Assignee after Title
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # Title column
        for i in range(len(columns)):
            if i != 1:  # Skip Title column
                table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.itemSelectionChanged.connect(self.on_issue_selected)
        table.setSortingEnabled(True)

    def update_filter_options(self, issues):
        severities = set()
        statuses = set()
        releases = set()
        for issue in issues:
            severities.add(issue['fields'].get('priority', {}).get('name', 'N/A'))
            statuses.add(issue['fields']['status']['name'])
            fix_versions = issue['fields'].get('fixVersions', [])
            for version in fix_versions:
                releases.add(version['name'])
        
        if self.current_tab == "personal":
            self.update_combobox(self.personal_severity_filter, severities, "All Severities")
            self.update_combobox(self.personal_status_filter, statuses, "All Statuses")
            self.update_combobox(self.personal_release_filter, releases, "All Releases")
        elif self.current_tab == "reported":
            self.update_combobox(self.reported_severity_filter, severities, "All Severities")
            self.update_combobox(self.reported_status_filter, statuses, "All Statuses")
            self.update_combobox(self.reported_release_filter, releases, "All Releases")
        elif self.current_tab == "project":
            self.update_combobox(self.project_severity_filter, severities, "All Severities")
            self.update_combobox(self.project_status_filter, statuses, "All Statuses")
            self.update_combobox(self.project_release_filter, releases, "All Releases")
        elif self.current_tab == "search":
            self.update_combobox(self.search_severity_filter, severities, "All Severities")
            self.update_combobox(self.search_status_filter, statuses, "All Statuses")
            self.update_combobox(self.search_release_filter, releases, "All Releases")

    def update_combobox(self, combobox, items, default_item):
        current_item = combobox.currentText()
        combobox.blockSignals(True)
        combobox.clear()
        combobox.addItem(default_item)
        combobox.addItems(sorted(items))
        combobox.setCurrentText(current_item)
        combobox.blockSignals(False)

    def get_relative_time(self, timestamp):
        then = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")
        now = datetime.now(then.tzinfo)
        delta = now - then

        if delta.days > 365:
            return f"{delta.days // 365} years ago"
        elif delta.days > 30:
            return f"{delta.days // 30} months ago"
        elif delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            return f"{delta.seconds // 3600} hours ago"
        elif delta.seconds > 60:
            return f"{delta.seconds // 60} minutes ago"
        else:
            return "Just now"

    def load_more_data(self):
        if not self.is_loading and self.current_start < self.total_issues:
            self.load_data_async(self.current_tab)

    def on_issue_selected(self):
        selected_items = self.sender().selectedItems()
        if selected_items:
            issue_key = selected_items[0].text()
            self.show_issue_details_async(issue_key)
            if self.current_tab == "personal":
                for btn in [self.personal_download_btn, self.personal_refresh_btn, self.personal_edit_btn, self.personal_add_comment_btn]:
                    btn.setVisible(True)
            elif self.current_tab == "reported":
                for btn in [self.reported_download_btn, self.reported_refresh_btn, self.reported_edit_btn, self.reported_add_comment_btn]:
                    btn.setVisible(True)
            elif self.current_tab == "project":
                for btn in [self.project_download_btn, self.project_refresh_btn, self.project_edit_btn, self.project_add_comment_btn]:
                    btn.setVisible(True)
            elif self.current_tab == "search":
                for btn in [self.search_download_btn, self.search_refresh_btn, self.search_edit_btn, self.search_add_comment_btn]:
                    btn.setVisible(True)
        else:
            if self.current_tab == "personal":
                for btn in [self.personal_download_btn, self.personal_refresh_btn, self.personal_edit_btn, self.personal_add_comment_btn]:
                    btn.setVisible(False)
            elif self.current_tab == "reported":
                for btn in [self.reported_download_btn, self.reported_refresh_btn, self.reported_edit_btn, self.reported_add_comment_btn]:
                    btn.setVisible(False)
            elif self.current_tab == "project":
                for btn in [self.project_download_btn, self.project_refresh_btn, self.project_edit_btn, self.project_add_comment_btn]:
                    btn.setVisible(False)
            elif self.current_tab == "search":
                for btn in [self.search_download_btn, self.search_refresh_btn, self.search_edit_btn, self.search_add_comment_btn]:
                    btn.setVisible(False)

    def show_issue_details_async(self, issue_key):
        self.show_loading_overlay()

        worker = Worker(self.fetch_issue_details, issue_key)
        if self.current_tab == "personal":
            worker.signals.result.connect(lambda data: self.display_issue_details(data, "personal"))
        elif self.current_tab == "reported":
            worker.signals.result.connect(lambda data: self.display_issue_details(data, "reported"))
        elif self.current_tab == "project":
            worker.signals.result.connect(lambda data: self.display_issue_details(data, "project"))
        elif self.current_tab == "search":
            worker.signals.result.connect(lambda data: self.display_issue_details(data, "search"))
        worker.signals.finished.connect(self.hide_loading_overlay)
        worker.signals.error.connect(lambda e: self.handle_error(e))
        self.threadpool.start(worker)

    def fetch_issue_details(self, issue_key):
        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}",
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        response.raise_for_status()
        return response.json()
    
    def update_comments_tab(self, comments, tab_type):
        if tab_type == "personal":
            comments_content = self.personal_comments_content
        elif tab_type == "reported":
            comments_content = self.reported_comments_content
        elif tab_type == "project":
            comments_content = self.project_comments_content
        elif tab_type == "search":
            comments_content = self.search_comments_content
        else:
            return

        # Initialize layout if it doesn't exist
        if comments_content.layout() is None:
            comments_content.setLayout(QVBoxLayout())

        comments_layout = comments_content.layout()

        # Clear existing comments
        while comments_layout.count():
            item = comments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for comment in comments:
            comment_widget = CommentWidget(comment, self)
            comments_layout.addWidget(comment_widget)
            
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Sunken)
            comments_layout.addWidget(separator)

        comments_layout.addStretch()


    def display_issue_details(self, issue_data, tab_type):
        description_markdown = issue_data['fields']['description'] or "No description available."
        description_html = self.markdown_to_html(description_markdown)
        comments = issue_data['fields']['comment']['comments']
        attachments = issue_data['fields']['attachment']
        activities = self.fetch_issue_activity(issue_data['key'])
        activity_html = self.format_activity_log(activities)

        if tab_type == "personal":
            self.personal_description_tab.setHtml(description_html)
            self.update_comments_tab(comments, "personal")
            self.update_attachments_tab(self.personal_attachments_tab, attachments)
            self.personal_activity_tab.setHtml(activity_html)
            self.personal_details_tab_widget.setCurrentIndex(0)  # Set to Description tab
        elif tab_type == "reported":
            self.reported_description_tab.setHtml(description_html)
            self.update_comments_tab(comments, "reported")
            self.update_attachments_tab(self.reported_attachments_tab, attachments)
            self.reported_activity_tab.setHtml(activity_html)
            self.reported_details_tab_widget.setCurrentIndex(0)  # Set to Description tab
        elif tab_type == "project":
            self.project_description_tab.setHtml(description_html)
            self.update_comments_tab(comments, "project")
            self.update_attachments_tab(self.project_attachments_tab, attachments)
            self.project_activity_tab.setHtml(activity_html)
            self.project_details_tab_widget.setCurrentIndex(0)  # Set to Description tab
        elif tab_type == "search":
            self.search_description_tab.setHtml(description_html)
            self.update_comments_tab(comments, "search")
            self.update_attachments_tab(self.search_attachments_tab, attachments)
            self.search_activity_tab.setHtml(activity_html)
            self.search_details_tab_widget.setCurrentIndex(0)  # Set to Description tab

        # Update issue details (you might want to add this information to a header or separate widget)
        issue_key = issue_data['key']
        summary = issue_data['fields']['summary']
        status = issue_data['fields']['status']['name']
        issue_type = issue_data['fields']['issuetype']['name']
        priority = issue_data['fields']['priority']['name']
        assignee = issue_data['fields']['assignee']['displayName'] if issue_data['fields']['assignee'] else "Unassigned"
        reporter = issue_data['fields']['reporter']['displayName']
        created_date = self.get_relative_time(issue_data['fields']['created'])
        updated_date = self.get_relative_time(issue_data['fields']['updated'])

        issue_details_html = f"""
        <h2>{issue_key}: {summary}</h2>
        <p><strong>Status:</strong> {status}</p>
        <p><strong>Type:</strong> {issue_type}</p>
        <p><strong>Priority:</strong> {priority}</p>
        <p><strong>Assignee:</strong> {assignee}</p>
        <p><strong>Reporter:</strong> {reporter}</p>
        <p><strong>Created:</strong> {created_date}</p>
        <p><strong>Updated:</strong> {updated_date}</p>
        """

        # You might want to add a QLabel or QTextBrowser to display this information
        # For example:
        # self.issue_details_label.setText(issue_details_html)

        # Make buttons visible
        if tab_type == "personal":
            for btn in [self.personal_download_btn, self.personal_refresh_btn, self.personal_edit_btn, self.personal_add_comment_btn]:
                btn.setVisible(True)
        elif tab_type == "reported":
            for btn in [self.reported_download_btn, self.reported_refresh_btn, self.reported_edit_btn, self.reported_add_comment_btn]:
                btn.setVisible(True)
        elif tab_type == "project":
            for btn in [self.project_download_btn, self.project_refresh_btn, self.project_edit_btn, self.project_add_comment_btn]:
                btn.setVisible(True)
        elif tab_type == "search":
            for btn in [self.search_download_btn, self.search_refresh_btn, self.search_edit_btn, self.search_add_comment_btn]:
                btn.setVisible(True)

    def markdown_to_html(self, markdown_text):
        html = markdown.markdown(markdown_text, extensions=['fenced_code', 'tables', 'nl2br'])
        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                pre {{ background-color: #f0f0f0; padding: 10px; border-radius: 5px; }}
                code {{ font-family: "Courier New", monospace; }}  # Changed from Consolas to Courier New
            </style>
        </head>
        <body>
            {html}
        </body>
        </html>
        """

    def format_comments_html(self, comments):
        html = """
        <style>
        body { background-color: #1e1e1e; color: #d4d4d4; font-family: Arial, sans-serif; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; background-color: #252526; }
        th { background-color: #333333; color: #ffffff; font-size: 14px; font-weight: bold; padding: 10px; text-align: left; }
        td { background-color: #2d2d2d; padding: 10px; border-top: 1px solid #404040; }
        </style>
        """
        for comment in comments:
            author = comment['author']['displayName']
            created = comment['created']
            date, time = created.split('T')
            time = time.split('.')[0]
            comment_body_html = self.markdown_to_html(comment['body'])
            html += f"""
            <table>
                <tr><th>Comment by {author} on {date} at {time}</th></tr>
                <tr><td>{comment_body_html}</td></tr>
            </table>
            """
        return html
    
    def download_description(self):
        description = self.personal_description_tab.toPlainText() if self.current_tab == "personal" else (
            self.reported_description_tab.toPlainText() if self.current_tab == "reported" else (
                self.project_description_tab.toPlainText() if self.current_tab == "project" else self.search_description_tab.toPlainText()
            )
        )
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Description", "", "Text Files (*.txt)")
        if file_name:
            with open(file_name, 'w') as f:
                f.write(description)
            QMessageBox.information(self, "Success", "Description downloaded successfully.")

    def get_selected_issue_key(self):
        if self.current_tab == "personal":
            table = self.personal_issues_table
        elif self.current_tab == "reported":
            table = self.reported_issues_table
        elif self.current_tab == "project":
            table = self.project_issues_table
        elif self.current_tab == "search":
            table = self.search_issues_table
        else:
            return None

        selected_items = table.selectedItems()
        if selected_items:
            return selected_items[0].text()
        return None

    def edit_issue(self):
        issue_key = self.get_selected_issue_key()
        if issue_key:
            self.show_edit_dialog(issue_key)

    def show_edit_dialog(self, issue_key):
        worker = Worker(self.fetch_issue_details, issue_key)
        worker.signals.result.connect(lambda data: self.create_edit_dialog(issue_key, data))
        worker.signals.error.connect(lambda e: QMessageBox.critical(self, "Error", str(e)))
        self.threadpool.start(worker)

    def create_edit_dialog(self, issue_key, issue_data):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Issue: {issue_key}")
        layout = QFormLayout(dialog)

        current_status = issue_data['fields']['status']['name']
        current_assignee = issue_data['fields']['assignee']['name'] if issue_data['fields']['assignee'] else ""
        current_severity = issue_data['fields'].get('priority', {}).get('name', "")
        current_release = issue_data['fields']['fixVersions'][0]['name'] if issue_data['fields']['fixVersions'] else ""

        status_input = QComboBox()
        status_input.setMinimumWidth(200)
        assignee_input = AutocompleteComboBox(fetch_users_callback=self.fetch_users)
        assignee_input.setMinimumWidth(300)  # Increased width
        if issue_data['fields']['assignee']:
            assignee_input.setCurrentText(issue_data['fields']['assignee']['name'])
        severity_input = QComboBox()
        severity_input.setMinimumWidth(200)
        release_input = QComboBox()
        release_input.setMinimumWidth(200)

        self.populate_edit_dialog_fields(issue_key, status_input, severity_input, release_input, current_status, current_severity, current_release)

        layout.addRow("Status:", status_input)
        layout.addRow("Assignee:", assignee_input)
        layout.addRow("Severity:", severity_input)
        layout.addRow("Release:", release_input)

        description_label = QLabel("Description:")
        layout.addWidget(description_label)
        
        description_editor = RichTextEditor(dialog)
        description_editor.setPlainText(issue_data['fields']['description'] or "")
        layout.addWidget(description_editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            self.update_issue(issue_key, status_input.currentText(), assignee_input.get_selected_username(), 
                            severity_input.currentText(), release_input.currentText(),
                            description_editor.toPlainText())

    def populate_edit_dialog_fields(self, issue_key, status_input, severity_input, release_input, current_status, current_severity, current_release):
        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/transitions",
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        transitions = response.json().get('transitions', [])
        statuses = [transition['to']['name'] for transition in transitions]
        status_input.addItems(statuses)
        status_input.setCurrentText(current_status)

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/priority",
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        severities = [priority['name'] for priority in response.json()]
        severity_input.addItems(severities)
        severity_input.setCurrentText(current_severity)

        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/project/{issue_key.split('-')[0]}/versions",
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        releases = [version['name'] for version in response.json() if not version['archived']]
        release_input.addItems(releases)
        release_input.setCurrentText(current_release)

    def update_issue(self, issue_key, new_status, new_assignee, new_severity, new_release, new_description):
        update_payload = {
            "fields": {
                "assignee": {"name": new_assignee} if new_assignee else None,
                "priority": {"name": new_severity},
                "fixVersions": [{"name": new_release}] if new_release else [],
                "description": new_description
            }
        }

        try:
            response = requests.put(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}",
                json=update_payload,
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            response.raise_for_status()

            current_status = self.personal_issues_table.item(self.personal_issues_table.currentRow(), 2).text()
            if new_status != current_status:
                self.transition_issue_status(issue_key, new_status)

            QMessageBox.information(self, "Success", "Issue updated successfully.")
            self.refresh_issue()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to update issue: {str(e)}")

    def refresh_issue(self):
        issue_key = self.get_selected_issue_key()
        if issue_key:
            self.show_issue_details_async(issue_key)

    def transition_issue_status(self, issue_key, new_status):
        response = requests.get(
            f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/transitions",
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        transitions = response.json().get('transitions', [])
        transition_id = next(transition['id'] for transition in transitions if transition['to']['name'] == new_status)
        
        transition_payload = {
            "transition": {
                "id": transition_id
            }
        }
        response = requests.post(
            f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/transitions",
            json=transition_payload,
            headers={"Authorization": f"Bearer {self.jira_token}"}
        )
        response.raise_for_status()

    def add_comment(self):
        issue_key = self.get_selected_issue_key()
        if issue_key:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Add Comment to Issue: {issue_key}")
            layout = QVBoxLayout(dialog)

            comment_input = RichTextEditor(dialog)
            layout.addWidget(comment_input)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)

            if dialog.exec_() == QDialog.Accepted:
                self.post_comment(issue_key, comment_input.toPlainText())  # Use toPlainText() instead of toHtml()

    def post_comment(self, issue_key, comment_html):
        try:
            response = requests.post(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/comment",
                json={"body": comment_html},
                headers={
                    "Authorization": f"Bearer {self.jira_token}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            QMessageBox.information(self, "Success", "Comment added successfully.")
            self.refresh_issue()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to add comment: {str(e)}")

    def download_attachment(self, attachment_url, filename):
        print(f"Starting download for attachment: {filename}")
        try:
            headers = {
                "Authorization": f"Bearer {self.jira_token}"
            }
            
            print(f"Requesting attachment from: {attachment_url}")
            
            response = requests.get(attachment_url, headers=headers, verify=False, allow_redirects=True)
            
            response.raise_for_status()
            
            print(f"Response status code: {response.status_code}")
            
            file_name, _ = QFileDialog.getSaveFileName(self, "Save Attachment", filename, "All Files (*)")
            
            if file_name:
                print(f"Saving attachment to: {file_name}")
                with open(file_name, 'wb') as file:
                    file.write(response.content)
                print("Attachment saved successfully")
                QMessageBox.information(self, "Success", "Attachment downloaded successfully.")
            else:
                print("File save cancelled by user")

        except requests.RequestException as e:
            print(f"Error downloading attachment: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to download attachment: {str(e)}")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            QMessageBox.critical(self, "Error", f"An unexpected error occurred: {str(e)}")


    def save_attachment(self, response, filename):
        print("Starting save_attachment function")  # Debug print
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Attachment", filename, "All Files (*)")
        if file_name:
            print(f"Saving attachment to: {file_name}")  # Debug print
            with open(file_name, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print("Attachment saved successfully")  # Debug print
            QMessageBox.information(self, "Success", "Attachment downloaded successfully.")
        else:
            print("File save cancelled by user")  # Debug print

    def load_selected_projects(self):
        default_projects = ["ezaf", "ezit", "ezkf", "ezesc"]
        
        if not os.path.exists(PROJECTS_FILE):
            # Create the projects file with default projects
            with open(PROJECTS_FILE, 'w') as f:
                json.dump(default_projects, f)
            return default_projects
        else:
            # Load projects from existing file
            with open(PROJECTS_FILE, 'r') as f:
                projects = json.load(f)
            
            # If the file is empty or invalid, use default projects
            if not projects or not isinstance(projects, list):
                projects = default_projects
                with open(PROJECTS_FILE, 'w') as f:
                    json.dump(projects, f)
            
            return projects

    def handle_error(self, error):
        self.is_loading = False
        self.hide_loading_overlay()
        QMessageBox.critical(self, "Error", str(error))

    def on_tab_change(self, index):
        if index == 0:
            self.current_tab = "personal"
            self.current_start = 0
            self.personal_issues_table.setRowCount(0)
            self.load_data_async("personal")
        elif index == 1:
            self.current_tab = "reported"
            self.current_start = 0
            self.reported_issues_table.setRowCount(0)
            self.load_data_async("reported")
        elif index == 2:
            self.current_tab = "project"
            self.current_start = 0
            self.project_issues_table.setRowCount(0)
            self.load_data_async("project")
        elif index == 3:
            self.current_tab = "search"
            self.search_input.clear()
            # Don't clear the table, just update it
            self.update_search_table()

    def fetch_users(self, input_text):
        try:
            response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/user/search",
                params={"username": input_text, "maxResults": 10},
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            response.raise_for_status()
            return [{'name': user['name'], 'displayName': user['displayName']} for user in response.json()]
        except requests.RequestException as e:
            print(f"Error fetching users: {str(e)}")
            return []

    def update_attachments_tab(self, attachments_tab, attachments):
        scroll = QScrollArea()
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        enlarge_instruction = QLabel("<b>Click thumbnail to enlarge</b>")
        enlarge_instruction.setAlignment(Qt.AlignCenter)
        layout.addWidget(enlarge_instruction)

        for attachment in attachments:
            item_widget = QWidget()
            item_layout = QVBoxLayout(item_widget)
            
            # First line: Filename
            filename_label = QLabel(attachment.get('filename', 'Unknown file'))
            filename_label.setWordWrap(True)
            item_layout.addWidget(filename_label)
            
            # Second line: Thumbnail (if image)
            mime_type = attachment.get('mimeType', '')
            if mime_type.startswith('image/'):
                thumbnail = QLabel()
                pixmap = QPixmap()
                thumbnail_url = attachment.get('thumbnail')
                
                if thumbnail_url:
                    try:
                        response = requests.get(
                            thumbnail_url, 
                            headers={"Authorization": f"Bearer {self.jira_token}"},
                            verify=False
                        )
                        response.raise_for_status()
                        pixmap.loadFromData(response.content)
                        
                        if not pixmap.isNull():
                            thumbnail.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                        else:
                            thumbnail.setText("Thumbnail not available")
                    except Exception as e:
                        print(f"Error loading thumbnail: {str(e)}")
                        thumbnail.setText("Error loading thumbnail")
                else:
                    thumbnail.setText("Thumbnail not available")
                
                thumbnail.setAlignment(Qt.AlignCenter)
                thumbnail.setCursor(Qt.PointingHandCursor)
                thumbnail.mousePressEvent = lambda e, url=attachment.get('content'): self.show_full_image(url)
                item_layout.addWidget(thumbnail)
            else:
                non_image_label = QLabel("No preview available")
                non_image_label.setAlignment(Qt.AlignCenter)
                item_layout.addWidget(non_image_label)
            
            # Third line: Buttons
            button_layout = QHBoxLayout()
            
            download_btn = QPushButton("Download")
            download_btn.clicked.connect(lambda _, url=attachment.get('content'), fn=attachment.get('filename'): 
                                        self.download_attachment(url, fn) if url and fn else None)
            button_layout.addWidget(download_btn)
            
            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(lambda _, id=attachment.get('id'): 
                                    self.delete_attachment(id) if id else None)
            button_layout.addWidget(delete_btn)
            
            item_layout.addLayout(button_layout)
            
            # Add a separator line
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setFrameShadow(QFrame.Sunken)
            
            layout.addWidget(item_widget)
            layout.addWidget(separator)
        
        layout.addStretch()
        scroll.setWidget(content_widget)
        scroll.setWidgetResizable(True)

        if attachments_tab.layout() is None:
            attachments_tab.setLayout(QVBoxLayout())
        
        # Clear previous content
        while attachments_tab.layout().count():
            child = attachments_tab.layout().takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        attachments_tab.layout().addWidget(scroll)

        # Add upload button
        upload_btn = QPushButton("Upload Attachment")
        upload_btn.clicked.connect(self.upload_attachment)
        attachments_tab.layout().addWidget(upload_btn)

        print(f"Number of attachments: {len(attachments)}")  # Debug print

    def show_full_image(self, image_url):
        try:
            response = requests.get(
                image_url,
                headers={"Authorization": f"Bearer {self.jira_token}"},
                verify=False
            )
            response.raise_for_status()
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Full Image")
            
            scroll_area = QScrollArea(dialog)
            full_image = QLabel(scroll_area)
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            full_image.setPixmap(pixmap)
            full_image.setAlignment(Qt.AlignCenter)
            
            scroll_area.setWidget(full_image)
            scroll_area.setWidgetResizable(True)
            
            layout = QVBoxLayout(dialog)
            layout.addWidget(scroll_area)
            
            dialog.resize(800, 600)  # Set a default size, adjust as needed
            dialog.exec_()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to load full image: {str(e)}")


    def get_attachment_meta(self):
        try:
            response = self.session.get(
                f"{JIRA_BASE_URL}/rest/api/2/attachment/meta",
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to get attachment metadata: {str(e)}")
            return None
    
    
    def delete_attachment(self, attachment_id):
        try:
            response = self.session.delete(
                f"{JIRA_BASE_URL}/rest/api/2/attachment/{attachment_id}",
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            response.raise_for_status()
            QMessageBox.information(self, "Success", "Attachment deleted successfully.")
            self.refresh_issue()
        except requests.RequestException as e:
            QMessageBox.critical(self, "Error", f"Failed to delete attachment: {str(e)}")
    
    def upload_attachment(self):
        issue_key = self.get_selected_issue_key()
        if not issue_key:
            QMessageBox.warning(self, "Warning", "No issue selected.")
            return

        file_name, _ = QFileDialog.getOpenFileName(self, "Select File to Upload")
        if file_name:
            try:
                meta = self.get_attachment_meta()
                if meta and meta['uploadLimit'] < os.path.getsize(file_name):
                    QMessageBox.warning(self, "Warning", f"File size exceeds upload limit of {meta['uploadLimit']} bytes.")
                    return

                with open(file_name, 'rb') as file:
                    files = {'file': (os.path.basename(file_name), file)}
                    response = requests.post(
                        f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/attachments",
                        files=files,
                        headers={
                            "Authorization": f"Bearer {self.jira_token}",
                            "X-Atlassian-Token": "no-check"
                        }
                    )
                    response.raise_for_status()
                QMessageBox.information(self, "Success", "Attachment uploaded successfully.")
                self.refresh_issue()
            except requests.RequestException as e:
                QMessageBox.critical(self, "Error", f"Failed to upload attachment: {str(e)}")

    def fetch_issue_activity(self, issue_key):
        try:
            # Fetch issue history
            history_response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}?expand=changelog",
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            history_response.raise_for_status()
            history_data = history_response.json().get('changelog', {}).get('histories', [])

            # Fetch worklog
            worklog_response = requests.get(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/worklog",
                headers={"Authorization": f"Bearer {self.jira_token}"}
            )
            worklog_response.raise_for_status()
            worklog_data = worklog_response.json().get('worklogs', [])

            # Combine history and worklog data
            combined_activity = history_data + worklog_data
            combined_activity.sort(key=lambda x: x.get('created', ''), reverse=True)

            print(f"Activity data for {issue_key}: {combined_activity}")  # Debug print
            return combined_activity
        except requests.RequestException as e:
            print(f"Error fetching issue activity: {str(e)}")
            return []
        
    def format_activity_log(self, activities):
        formatted_log = """
        <style>
            body { font-family: Arial, sans-serif; }
            h3 { margin-bottom: 5px; color: #333; }
            ul { margin-top: 5px; }
            li { margin-bottom: 3px; }
            hr { border: 0; height: 1px; background: #ddd; margin: 15px 0; }
        </style>
        """
        for activity in activities:
            if 'author' in activity:  # This is a history entry
                author = activity['author']['displayName']
                created = self.get_relative_time(activity['created'])
                formatted_log += f"<h3>{author} - {created}</h3>"
                formatted_log += "<ul>"
                for item in activity.get('items', []):
                    field = item['field']
                    from_string = item.get('fromString', 'None')
                    to_string = item.get('toString', 'None')
                    formatted_log += f"<li><b>{field}</b>: {from_string} → {to_string}</li>"
                formatted_log += "</ul>"
            elif 'updateAuthor' in activity:  # This is a worklog entry
                author = activity['updateAuthor']['displayName']
                created = self.get_relative_time(activity['created'])
                time_spent = activity.get('timeSpent', 'Unknown')
                formatted_log += f"<h3>{author} logged work - {created}</h3>"
                formatted_log += f"<p>Time spent: {time_spent}</p>"
                if activity.get('comment'):
                    formatted_log += f"<p>Comment: {activity['comment']}</p>"
            formatted_log += "<hr>"
        return formatted_log