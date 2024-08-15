import sys
import logging
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, 
                             QTreeView, QTextEdit, QLineEdit, QSplitter, QMessageBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QFrame, QDialog)
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QFont, QGuiApplication, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QThreadPool, QRunnable, pyqtSlot
import requests
import base64
import markdown
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QListWidget, QPlainTextEdit
import re
import markdown
from PyQt5.QtWidgets import QSplitter, QPushButton, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl
import sip
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import keyring
from helper_github_insights_tab.github_auth_dialog import GitHubAuthDialog
from helper_github_insights_tab.loading_overlay import LoadingOverlay
from helper_github_insights_tab.code_editor import LineNumberArea, CodeEditor, CodeHighlighter
from helper_github_insights_tab.blame_popup import BlamePopup
from cachetools import TTLCache
import asyncio
import aiohttp
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtCore import QMetaType
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
import requests

class SearchableUserList(QWidget):
    search_completed = pyqtSignal(list)

    def __init__(self, parent=None, token=None, org_name=None):
        super().__init__(parent)
        self.token = token
        self.org_name = org_name
        self.layout = QVBoxLayout(self)
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search for users...")
        self.user_list = QListWidget(self)
        self.layout.addWidget(self.search_input)
        self.layout.addWidget(self.user_list)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search_users)

        self.search_input.textChanged.connect(self.start_search_timer)
        print("SearchableUserList initialized")  # Debug print

    def start_search_timer(self):
        print(f"Search timer started for: {self.search_input.text()}")  # Debug print
        self.search_timer.start(300)  # Wait for 300ms after the user stops typing

    def search_users(self):
        query = self.search_input.text()
        print(f"Searching for: {query}")  # Debug print
        if len(query) < 3:  # Only search if at least 3 characters are entered
            self.user_list.clear()
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            url = f"https://github.hpe.com/api/v3/search/users"
            params = {
                "q": f"{query} in:login type:user org:{self.org_name}",
                "per_page": 100
            }
            print(f"API call: {url}")  # Debug print
            print(f"Params: {params}")  # Debug print
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            users = [user['login'] for user in response.json()['items']]
            print(f"Found users: {users}")  # Debug print
            self.update_user_list(users)
            self.search_completed.emit(users)
        except requests.exceptions.RequestException as e:
            print(f"Error searching users: {str(e)}")
            self.user_list.clear()

    def update_user_list(self, users):
        self.user_list.clear()
        for user in users:
            item = QListWidgetItem(user)
            self.user_list.addItem(item)
        print(f"User list updated with {len(users)} users")  # Debug print

    def get_selected_users(self):
        return [item.text() for item in self.user_list.selectedItems()]

class SyncedScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.viewport() and event.type() == QEvent.Scroll:
            self.parent().sync_scroll(self)
        return super().eventFilter(obj, event)

class CommentSeparator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)  # Adjust this value to change the separator height

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(240, 240, 240))  # Light gray background
        painter.setPen(QPen(QColor(200, 200, 200), 1))  # Lighter gray line
        painter.drawLine(0, self.height() // 2, self.width(), self.height() // 2)

class CommentWidget(QWidget):
    def __init__(self, comment, parent=None):
        super().__init__(parent)
        self.comment = comment
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()
        author_label = QLabel(f"<b>{self.comment['user']['login']}</b>")
        time_label = QLabel(self.comment['created_at'])
        header_layout.addWidget(author_label)
        header_layout.addWidget(time_label)
        header_layout.addStretch()

        if not self.comment.get('resolved', False) and self.comment['type'] == 'review_comment':
            resolve_button = QPushButton("Resolve")
            resolve_button.clicked.connect(self.resolve_comment)
            header_layout.addWidget(resolve_button)

        layout.addLayout(header_layout)

        # Comment body in Markdown
        body_text = self.comment.get('body', '')
        if body_text is not None:
            body_html = markdown.markdown(body_text)
            body_label = QLabel(body_html)
            body_label.setWordWrap(True)
            body_label.setTextFormat(Qt.RichText)
            layout.addWidget(body_label)
        else:
            body_label = QLabel("No content")
            layout.addWidget(body_label)

        # Associated code (if any)
        if self.comment['type'] == 'review_comment' and 'path' in self.comment and 'position' in self.comment:
            code_frame = QFrame()
            code_frame.setFrameShape(QFrame.StyledPanel)
            code_layout = QVBoxLayout(code_frame)
            code_label = QLabel(f"<b>File:</b> {self.comment['path']}")
            code_layout.addWidget(code_label)
            code_text = QTextEdit()
            code_text.setReadOnly(True)
            code_text.setMinimumHeight(300)  # Increase the minimum height
            code_text.setFont(QFont("Courier", 10))  # Set a monospace font and increase size
            code_snippet = self.comment.get('code_snippet', 'Code snippet not available')
            if code_snippet.startswith("Error fetching code snippet:"):
                code_text.setStyleSheet("color: red;")
            code_text.setPlainText(code_snippet)
            code_layout.addWidget(code_text)
            layout.addWidget(code_frame)

    def resolve_comment(self):
        print(f"Resolving comment: {self.comment.get('id', 'Unknown ID')}")
        # Implement the actual resolution logic here

class Signals(QObject):
    update_repo_combo = pyqtSignal(list)
    update_repo_info = pyqtSignal(dict)
    update_language_chart = pyqtSignal(dict)
    update_commit_chart = pyqtSignal(list)
    update_branches = pyqtSignal(list)
    update_file_structure = pyqtSignal(list)
    update_file_content = pyqtSignal(dict)
    update_search_results = pyqtSignal(list)
    update_prs = pyqtSignal(list)
    update_pr_details = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

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

class GitHubInsightsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.org_name = "hpe"
        self.token = self.get_github_token()
        self.cache = TTLCache(maxsize=100, ttl=300)  # Cache with 5 minutes TTL
        self.threadpool = QThreadPool()
        self.signals = Signals()
        
        # Separate reviewer widgets for PR tab
        self.pr_reviewer_combo = QComboBox()
        self.pr_reviewer_list = QListWidget()
        self.pr_add_reviewer_button = QPushButton("Add Reviewer")
        self.pr_remove_reviewer_button = QPushButton("Remove Reviewer")

        # Separate reviewer widgets for Create PR tab
        self.create_pr_reviewer_combo = QComboBox()
        self.create_pr_reviewer_list = QListWidget()
        self.create_pr_add_reviewer_button = QPushButton("Add Reviewer")
        self.create_pr_remove_reviewer_button = QPushButton("Remove Reviewer")

        # Connect signals
        self.pr_add_reviewer_button.clicked.connect(self.add_pr_reviewer)
        self.pr_remove_reviewer_button.clicked.connect(self.remove_pr_reviewer)
        self.pr_reviewer_list.itemSelectionChanged.connect(self.update_pr_remove_reviewer_button)

        self.create_pr_add_reviewer_button.clicked.connect(self.add_create_pr_reviewer)
        self.create_pr_remove_reviewer_button.clicked.connect(self.remove_create_pr_reviewer)
        self.create_pr_reviewer_list.itemSelectionChanged.connect(self.update_create_pr_remove_reviewer_button)

        
        self.init_ui()
        self.setup_browse_tab()
        self.connect_signals()
        
        # Create loading overlay after UI setup
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
        
        # Load repositories after setup
        QTimer.singleShot(0, self.load_repositories)
    
    def add_pr_reviewer(self):
        reviewer = self.pr_reviewer_combo.currentText()
        if reviewer and self.pr_reviewer_list.findItems(reviewer, Qt.MatchExactly) == []:
            self.add_reviewer_to_pr(reviewer)

    def remove_pr_reviewer(self):
        selected_items = self.pr_reviewer_list.selectedItems()
        if selected_items:
            reviewer = selected_items[0].text()
            self.remove_reviewer_from_pr(reviewer)
    
    def add_create_pr_reviewer(self):
        selected_users = self.create_pr_user_search.get_selected_users()
        for user in selected_users:
            if self.create_pr_reviewer_list.findItems(user, Qt.MatchExactly) == []:
                self.create_pr_reviewer_list.addItem(user)
        self.create_pr_user_search.user_list.clearSelection()
        self.create_pr_user_search.search_input.clear()

    def remove_create_pr_reviewer(self):
        selected_items = self.create_pr_reviewer_list.selectedItems()
        for item in selected_items:
            self.create_pr_reviewer_list.takeItem(self.create_pr_reviewer_list.row(item))
    
    def update_pr_remove_reviewer_button(self):
        self.pr_remove_reviewer_button.setEnabled(bool(self.pr_reviewer_list.selectedItems()))

    def update_create_pr_remove_reviewer_button(self):
        self.create_pr_remove_reviewer_button.setEnabled(bool(self.create_pr_reviewer_list.selectedItems()))

        
    
    def update_remove_reviewer_button(self):
        self.remove_reviewer_button.setEnabled(bool(self.reviewer_list.selectedItems()))

    
    def connect_signals(self):
        self.signals.update_repo_combo.connect(self.update_repo_combo)
        self.signals.update_repo_info.connect(self.update_repo_info)
        self.signals.update_language_chart.connect(self.update_language_chart)
        self.signals.update_commit_chart.connect(self.update_commit_chart)
        self.signals.update_branches.connect(self.update_branches)
        self.signals.update_file_structure.connect(self.update_file_structure)
        self.signals.update_file_content.connect(self.update_file_content)
        self.signals.update_search_results.connect(self.update_search_results)
        self.signals.update_prs.connect(self.update_prs)
        self.signals.update_pr_details.connect(self.update_pr_details)
        self.signals.error_occurred.connect(self.show_error_message)

    def get_github_token(self):
        token = keyring.get_password("github_insights", "github_token")
        if not token:
            dialog = GitHubAuthDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                token = dialog.token
                keyring.set_password("github_insights", "github_token", token)
            else:
                QMessageBox.critical(self, "Authentication Required", "GitHub token is required to use this feature.")
                return None
        return token
    
    def showEvent(self, event):
        super().showEvent(event)
        self.loading_overlay.setGeometry(self.rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.setGeometry(self.rect())

    def show_loading(self):
        self.loading_overlay.setGeometry(self.rect())
        self.loading_overlay.raise_()  # Ensure it's on top
        self.loading_overlay.show()
        QApplication.processEvents()  # Force update of the UI

    def hide_loading(self):
        self.loading_overlay.hide()
        QApplication.processEvents()  # Force update of the UI


    def init_ui(self):
        layout = QVBoxLayout(self)

        # Repository selection
        repo_layout = QHBoxLayout()
        self.repo_combo = QComboBox()
        repo_layout.addWidget(QLabel("Select Repository:"))
        repo_layout.addWidget(self.repo_combo)
        layout.addLayout(repo_layout)

        # Tabs
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Info Tab
        self.info_tab = QScrollArea()
        self.info_tab.setWidgetResizable(True)
        self.info_content = QWidget()
        self.info_layout = QVBoxLayout(self.info_content)
        self.info_tab.setWidget(self.info_content)
        self.tab_widget.addTab(self.info_tab, "Info")

        # Browse Tab
        self.browse_tab = QWidget()
        self.browse_layout = QVBoxLayout(self.browse_tab)
        self.tab_widget.addTab(self.browse_tab, "Browse")

        # PRs Tab
        self.prs_tab = QWidget()
        self.prs_layout = QVBoxLayout(self.prs_tab)
        self.tab_widget.addTab(self.prs_tab, "PRs")

        # Create PR Tab
        self.create_pr_tab = QWidget()
        self.create_pr_layout = QVBoxLayout(self.create_pr_tab)
        self.tab_widget.addTab(self.create_pr_tab, "Create PR")

        self.setup_info_tab()
        self.setup_prs_tab()
        self.setup_create_pr_tab()

        # Connect signals
        self.repo_combo.currentTextChanged.connect(self.load_repo_data)

    
    def show_loading_overlay(self):
        self.create_pr_loading_overlay.setGeometry(self.rect())
        self.create_pr_loading_overlay.show()
        QApplication.processEvents()
    
    def hide_loading_overlay(self):
        self.create_pr_loading_overlay.hide()
        QApplication.processEvents()
    
    def setup_create_pr_tab(self):
        main_layout = QHBoxLayout()
        self.create_pr_layout.addLayout(main_layout)

        # Left panel
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Source branch
        self.source_branch_combo = QComboBox()
        left_layout.addWidget(QLabel("Source Branch:"))
        left_layout.addWidget(self.source_branch_combo)

        # Target branch
        self.dest_branch_combo = QComboBox()
        left_layout.addWidget(QLabel("Target Branch:"))
        left_layout.addWidget(self.dest_branch_combo)
        
        # Reviewers section
        reviewer_widget = QWidget()
        reviewer_layout = QVBoxLayout(reviewer_widget)
        reviewer_layout.addWidget(QLabel("Search and Select Reviewers:"))
        self.create_pr_user_search = SearchableUserList(token=self.token, org_name=self.org_name)
        reviewer_layout.addWidget(self.create_pr_user_search)

        self.create_pr_add_reviewer_button = QPushButton("Add Selected Reviewers")
        self.create_pr_add_reviewer_button.clicked.connect(self.add_create_pr_reviewer)
        reviewer_layout.addWidget(self.create_pr_add_reviewer_button)
        self.create_pr_reviewer_list = QListWidget()
        reviewer_layout.addWidget(self.create_pr_reviewer_list)
        self.create_pr_remove_reviewer_button = QPushButton("Remove Selected Reviewer")
        self.create_pr_remove_reviewer_button.clicked.connect(self.remove_create_pr_reviewer)
        reviewer_layout.addWidget(self.create_pr_remove_reviewer_button)
        left_layout.addWidget(reviewer_widget)

        # Create PR button
        create_pr_button = QPushButton("Create PR")
        create_pr_button.clicked.connect(self.create_pr)
        left_layout.addWidget(create_pr_button)

        left_layout.addStretch()
        main_layout.addWidget(left_widget, 1)
        # Right panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # File changes dropdown
        self.file_changes_combo = QComboBox()
        self.file_changes_combo.currentTextChanged.connect(self.load_pr_file_diff)
        right_layout.addWidget(QLabel("Changed Files:"))
        right_layout.addWidget(self.file_changes_combo)

        # Diff view
        diff_splitter = QSplitter(Qt.Vertical)
        self.old_diff_view = QTextEdit()
        self.old_diff_view.setReadOnly(True)
        self.old_diff_view.setStyleSheet("font-size: 14px; background-color: #f0f0f0;")
        self.old_diff_view.verticalScrollBar().valueChanged.connect(lambda value: self.sync_scroll(self.old_diff_view))
        
        self.new_diff_view = QTextEdit()
        self.new_diff_view.setReadOnly(True)
        self.new_diff_view.setStyleSheet("font-size: 14px; background-color: #f0f0f0;")
        self.new_diff_view.verticalScrollBar().valueChanged.connect(lambda value: self.sync_scroll(self.new_diff_view))
        
        diff_splitter.addWidget(self.old_diff_view)
        diff_splitter.addWidget(self.new_diff_view)
        right_layout.addWidget(diff_splitter)

        main_layout.addWidget(right_widget, 2)

        self.source_branch_combo.currentTextChanged.connect(self.update_file_changes)
        self.dest_branch_combo.currentTextChanged.connect(self.update_file_changes)

        # Add loading overlay
        self.create_pr_loading_overlay = LoadingOverlay(self)
        self.create_pr_loading_overlay.hide()
    
    def remove_reviewer_from_pr(self, reviewer):
        repo = self.repo_combo.currentText()
        pr_number = self.current_pr_number
        headers = {"Authorization": f"token {self.token}"}
        
        try:
            response = requests.delete(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/requested_reviewers",
                json={"reviewers": [reviewer]},
                headers=headers
            )
            response.raise_for_status()
            items = self.pr_reviewer_list.findItems(reviewer, Qt.MatchExactly)  # Changed from self.reviewer_list to self.pr_reviewer_list
            if items:
                self.pr_reviewer_list.takeItem(self.pr_reviewer_list.row(items[0]))  # Changed from self.reviewer_list to self.pr_reviewer_list
        except requests.exceptions.RequestException as e:
            self.show_error_message(f"Failed to remove reviewer: {str(e)}")
    
    def remove_reviewer(self):
        selected_items = self.reviewer_list.selectedItems()
        if selected_items:
            reviewer = selected_items[0].text()
            if hasattr(self, 'current_pr_number'):
                # We're in the PR tab, so update the PR
                self.remove_reviewer_from_pr(reviewer)
            else:
                # We're in the Create PR tab, just remove from the list
                self.reviewer_list.takeItem(self.reviewer_list.row(selected_items[0]))


    def load_reviewers(self, repo, pr_number):
        headers = {"Authorization": f"token {self.token}"}
        try:
            # Fetch requested reviewers
            requested_reviewers_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/requested_reviewers",
                headers=headers
            )
            requested_reviewers_response.raise_for_status()
            requested_reviewers = requested_reviewers_response.json()['users']

            # Fetch reviews to get additional reviewers who have already submitted reviews
            reviews_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/reviews",
                headers=headers
            )
            reviews_response.raise_for_status()
            reviews = reviews_response.json()

            # Combine all unique reviewers
            all_reviewers = set(reviewer['login'] for reviewer in requested_reviewers)
            all_reviewers.update(review['user']['login'] for review in reviews)

            self.pr_reviewer_list.clear()
            for reviewer in all_reviewers:
                self.pr_reviewer_list.addItem(reviewer)
            
            print(f"Fetched reviewers: {list(all_reviewers)}")
            
        except requests.exceptions.RequestException as e:
            self.show_error_message(f"Failed to load reviewers: {str(e)}")

    def load_repositories(self):
        if not self.token:
            return

        self.show_loading()
        worker = Worker(self.fetch_repositories)
        worker.signals.result.connect(self.update_repo_combo)
        worker.signals.finished.connect(self.hide_loading)
        worker.signals.error.connect(self.handle_error)
        self.threadpool.start(worker)

    def handle_error(self, error_message):
        self.hide_loading()
        self.show_error_message(error_message)

    def fetch_repositories(self):
        headers = {"Authorization": f"token {self.token}"}
        org_name = "hpe"
        
        try:
            response = requests.get(
                f"https://github.hpe.com/api/v3/search/repositories",
                params={
                    "q": f"org:{org_name} ez in:name",
                    "sort": "updated",
                    "order": "desc",
                    "per_page": 100
                },
                headers=headers
            )
            response.raise_for_status()
            search_results = response.json()
            
            ez_repos = [repo['name'] for repo in search_results.get('items', [])]
            return sorted(ez_repos)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to search repositories: {str(e)}")
        
    def update_repo_combo(self, repos):
        self.repo_combo.clear()
        self.repo_combo.addItems(repos)

    

    def load_repo_data(self, repo):
        if not self.token or not repo:
            return
        
        self.show_loading()
        worker = Worker(self.fetch_repo_data, repo)
        worker.signals.result.connect(self.update_repo_info)
        worker.signals.finished.connect(self.hide_loading)
        worker.signals.error.connect(self.handle_error)
        self.threadpool.start(worker)

        # Only load branches if a repository is selected
        if repo:
            self.load_branches()
            self.update_file_changes()

    def fetch_repo_data(self, repo):
        repo_info = self.fetch_repo_info(repo)
        branches = self.fetch_branches(repo)
        prs = self.fetch_prs(repo)
        return {'repo_info': repo_info, 'branches': branches, 'prs': prs}

    def sync_scroll(self, source):
        if source == self.old_diff_view:
            self.new_diff_view.verticalScrollBar().setValue(source.verticalScrollBar().value())
        else:
            self.old_diff_view.verticalScrollBar().setValue(source.verticalScrollBar().value())

    def fetch_repo_info(self, repo):
        cache_key = f"repo_info_{repo}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}", headers=headers)
            response.raise_for_status()
            repo_data = response.json()
            self.cache[cache_key] = repo_data
            return repo_data
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to fetch repo info: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f"\nStatus code: {e.response.status_code}"
                error_message += f"\nResponse text: {e.response.text}"
            self.signals.error_occurred.emit(error_message)
            return None
        
    def update_repo_info(self, repo_data):
        if not isinstance(repo_data, dict) or 'repo_info' not in repo_data:
            self.repo_summary.setText("Failed to fetch repository information.")
            return

        repo_info = repo_data['repo_info']
        if not isinstance(repo_info, dict):
            self.repo_summary.setText("Invalid repository information format.")
            return

        summary = f"Repository: {repo_info.get('name', 'Unknown')}\n"
        summary += f"Description: {repo_info.get('description', 'No description')}\n"
        summary += f"Stars: {repo_info.get('stargazers_count', 'N/A')}\n"
        summary += f"Forks: {repo_info.get('forks_count', 'N/A')}\n"
        summary += f"Open Issues: {repo_info.get('open_issues_count', 'N/A')}\n"
        summary += f"Created: {repo_info.get('created_at', 'N/A')}\n"
        summary += f"Last Updated: {repo_info.get('updated_at', 'N/A')}\n"
        self.repo_summary.setText(summary)

        if 'name' in repo_info:
            self.load_language_chart(repo_info['name'])
            self.load_commit_chart(repo_info['name'])
        else:
            print("Warning: Repository name not found in repo_info")

        # Ensure the info tab is visible and updated
        self.tab_widget.setCurrentWidget(self.info_tab)
        self.info_tab.update()

    def load_language_chart(self, repo):
        worker = Worker(self.fetch_language_data, repo)
        worker.setAutoDelete(True)
        self.threadpool.start(worker)

    def fetch_language_data(self, repo):
        cache_key = f"language_data_{repo}"
        if cache_key in self.cache:
            self.signals.update_language_chart.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/languages", headers=headers)
            response.raise_for_status()
            languages = response.json()
            self.cache[cache_key] = languages
            self.signals.update_language_chart.emit(languages)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Error fetching language data: {str(e)}")

    def update_language_chart(self, languages):
        ax = self.language_chart.figure.subplots()
        ax.clear()
        ax.pie(languages.values(), labels=languages.keys(), autopct='%1.1f%%')
        ax.set_title("Language Breakdown")
        self.language_chart.draw()

    def load_commit_chart(self, repo):
        worker = Worker(self.fetch_commit_data, repo)
        worker.setAutoDelete(True)
        self.threadpool.start(worker)

    def fetch_commit_data(self, repo):
        cache_key = f"commit_data_{repo}"
        if cache_key in self.cache:
            self.signals.update_commit_chart.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/stats/commit_activity", headers=headers)
            response.raise_for_status()
            commit_data = response.json()
            self.cache[cache_key] = commit_data
            self.signals.update_commit_chart.emit(commit_data)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Error fetching commit data: {str(e)}")

    def update_commit_chart(self, commit_data):
        ax = self.commit_chart.figure.subplots()
        ax.clear()
        weeks = range(len(commit_data))
        commits = [week['total'] for week in commit_data]
        ax.bar(weeks, commits)
        ax.set_title("Commit Activity (Last 52 Weeks)")
        ax.set_xlabel("Weeks Ago")
        ax.set_ylabel("Number of Commits")
        self.commit_chart.draw()

    def fetch_branches(self, repo):
        cache_key = f"branches_{repo}"
        if cache_key in self.cache:
            self.signals.update_branches.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/branches", headers=headers)
            response.raise_for_status()
            branches = [branch['name'] for branch in response.json()]
            self.cache[cache_key] = branches
            self.signals.update_branches.emit(branches)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Failed to fetch branches: {str(e)}")

    def update_branches(self, branches):
        self.branch_combo.clear()
        self.branch_combo.addItems(branches)
        if branches:
            self.branch_combo.setCurrentIndex(0)
            self.load_file_structure(branches[0])

    def load_file_structure(self, branch):
        if not branch or not hasattr(self, 'file_tree'):
            return
        
        repo = self.repo_combo.currentText()
        worker = Worker(self.fetch_file_structure, repo, branch)
        worker.setAutoDelete(True)
        self.threadpool.start(worker)

    def fetch_file_structure(self, repo, branch):
        cache_key = f"file_structure_{repo}_{branch}"
        if cache_key in self.cache:
            self.signals.update_file_structure.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/git/trees/{branch}?recursive=1", headers=headers)
            response.raise_for_status()
            tree = response.json()['tree']
            self.cache[cache_key] = tree
            self.signals.update_file_structure.emit(tree)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Failed to fetch file structure: {str(e)}")

    def update_file_structure(self, tree):
        model = QStandardItemModel()
        root = model.invisibleRootItem()
        
        for item in tree:
            path = item['path'].split('/')
            parent = root
            for i, folder in enumerate(path):
                if i == len(path) - 1:
                    child = QStandardItem(folder)
                    child.setData(item['path'], Qt.UserRole)
                    parent.appendRow(child)
                else:
                    found = False
                    for row in range(parent.rowCount()):
                        if parent.child(row).text() == folder:
                            parent = parent.child(row)
                            found = True
                            break
                    if not found:
                        new_folder = QStandardItem(folder)
                        parent.appendRow(new_folder)
                        parent = new_folder
        
        if self.file_tree is not None and not sip.isdeleted(self.file_tree):
            self.file_tree.setModel(model)

    def load_file_content(self, index):
        item = self.file_tree.model().itemFromIndex(index)
        file_path = item.data(Qt.UserRole)
        if not file_path:
            return
        
        repo = self.repo_combo.currentText()
        branch = self.branch_combo.currentText()
        worker = Worker(self.fetch_file_content, repo, branch, file_path)
        worker.setAutoDelete(True)
        self.threadpool.start(worker)

    def fetch_file_content(self, repo, branch, file_path):
        cache_key = f"file_content_{repo}_{branch}_{file_path}"
        if cache_key in self.cache:
            self.signals.update_file_content.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/contents/{file_path}?ref={branch}", headers=headers)
            response.raise_for_status()
            file_data = response.json()
            self.cache[cache_key] = file_data
            self.signals.update_file_content.emit(file_data)
        except requests.exceptions.RequestException as e:
            if response.status_code == 404:
                error_message = f"Error fetching file content: File {file_path} not found in branch {branch}"
            else:
                error_message = f"Failed to fetch file content: {str(e)}"
            self.signals.error_occurred.emit(error_message)

    def update_file_content(self, file_data):
        if isinstance(file_data, dict) and file_data.get('type') == 'file':
            if file_data['encoding'] == 'base64':
                try:
                    content = base64.b64decode(file_data['content']).decode('utf-8')
                    self.file_content.setPlainText(content)
                    
                    # Apply syntax highlighting
                    highlighter = CodeHighlighter(self.file_content.document())
                except UnicodeDecodeError:
                    self.file_content.setPlainText(f"Binary file: {file_data['path']}\nSize: {file_data['size']} bytes")
            else:
                self.file_content.setPlainText(f"Unsupported encoding: {file_data['encoding']}")
        else:
            self.file_content.setPlainText(f"This is not a file or the response is unexpected.")

    def search_repository(self):
        query = self.search_input.text()
        if not query:
            return
        
        repo = self.repo_combo.currentText()
        worker = Worker(self.fetch_search_results, repo, query)
        worker.setAutoDelete(True)
        self.threadpool.start(worker)

    def fetch_search_results(self, repo, query):
        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(
                f"https://github.hpe.com/api/v3/search/code",
                params={
                    "q": f"repo:{self.org_name}/{repo} {query}",
                    "per_page": 100
                },
                headers=headers
            )
            response.raise_for_status()
            results = response.json()['items']
            self.signals.update_search_results.emit(results)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Failed to search repository: {str(e)}")

    def update_search_results(self, results):
        search_results = "Search Results:\n\n"
        for item in results:
            search_results += f"File: {item['path']}\n"
            search_results += f"URL: {item['html_url']}\n\n"
        
        self.file_content.setText(search_results)

    def fetch_prs(self, repo):
        cache_key = f"prs_{repo}"
        if cache_key in self.cache:
            self.signals.update_prs.emit(self.cache[cache_key])
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            # Fetch last 50 PRs (both open and closed)
            prs_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls",
                params={"state": "all", "sort": "created", "direction": "desc", "per_page": 50},
                headers=headers
            )
            prs_response.raise_for_status()
            all_prs = prs_response.json()

            self.cache[cache_key] = all_prs
            self.signals.update_prs.emit(all_prs)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Failed to fetch PRs: {str(e)}")

    def update_prs(self, all_prs):
        self.pr_table.setRowCount(0)
        self.pr_table.setColumnCount(7)
        self.pr_table.setHorizontalHeaderLabels(["PR #", "Title", "Owner", "Source", "Target", "Date Opened", "Status"])
        
        # Set column widths
        self.pr_table.setColumnWidth(0, 60)  # PR #
        self.pr_table.setColumnWidth(1, 400)  # Title
        self.pr_table.setColumnWidth(2, 200)  # Owner
        self.pr_table.setColumnWidth(3, 100)  # Source
        self.pr_table.setColumnWidth(4, 100)  # Target
        self.pr_table.setColumnWidth(5, 150)  # Date Opened
        self.pr_table.setColumnWidth(6, 100)  # Status

        owners = set(["All Owners"])

        for pr in all_prs:
            row_position = self.pr_table.rowCount()
            self.pr_table.insertRow(row_position)
            self.pr_table.setItem(row_position, 0, QTableWidgetItem(str(pr['number'])))
            self.pr_table.setItem(row_position, 1, QTableWidgetItem(pr['title']))
            self.pr_table.setItem(row_position, 2, QTableWidgetItem(pr['user']['login']))
            self.pr_table.setItem(row_position, 3, QTableWidgetItem(pr['head']['ref']))
            self.pr_table.setItem(row_position, 4, QTableWidgetItem(pr['base']['ref']))
            self.pr_table.setItem(row_position, 5, QTableWidgetItem(pr['created_at']))
            self.pr_table.setItem(row_position, 6, QTableWidgetItem(pr['state']))

            owners.add(pr['user']['login'])

        # Update owner filter
        current_owner = self.owner_filter.currentText()
        self.owner_filter.clear()
        self.owner_filter.addItems(sorted(owners))
        if current_owner in owners:
            self.owner_filter.setCurrentText(current_owner)
        else:
            self.owner_filter.setCurrentText("All Owners")

        # Make the title column stretch to fill remaining space
        self.pr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        self.apply_filters()

    def load_pr_details(self, item):
        if isinstance(item, str):
            pr_number = item
        else:
            pr_number = self.pr_table.item(item.row(), 0).text()
        
        self.current_pr_number = pr_number  # Store the current PR number
        repo = self.repo_combo.currentText()
        worker = Worker(self.fetch_pr_details, repo, pr_number)
        worker.signals.result.connect(self.update_pr_details)
        worker.signals.finished.connect(self.hide_loading)
        worker.signals.error.connect(self.handle_error)
        self.threadpool.start(worker)
        
        # Load comments and reviewers
        self.load_pr_comments(repo, pr_number)
        self.load_reviewers(repo, pr_number)  # Make sure this line is present
        
    def fetch_pr_details(self, repo, pr_number):
        cache_key = f"pr_details_{repo}_{pr_number}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        headers = {"Authorization": f"token {self.token}"}
        try:
            # Fetch PR details
            pr_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}",
                headers=headers
            )
            pr_response.raise_for_status()
            pr_data = pr_response.json()

            # Fetch commits for this PR
            commits_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/commits",
                headers=headers
            )
            commits_response.raise_for_status()
            commits = commits_response.json()

            pr_details = {
                'pr_data': pr_data,
                'commits': commits
            }
            self.cache[cache_key] = pr_details
            return pr_details
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to fetch PR details: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f"\nStatus code: {e.response.status_code}"
                error_message += f"\nResponse text: {e.response.text}"
            raise Exception(error_message)

    def update_pr_details(self, pr_details):
        pr_data = pr_details['pr_data']
        commits = pr_details['commits']

        # Update description tab
        self.pr_description_editor.setPlainText(pr_data.get('body', ''))
        self.update_description_preview()

    def load_commit_file_diff(self, filename):
        print(f"Debug: load_commit_file_diff called with filename: {filename}")
        file_data = self.file_combo.currentData()
        print(f"Debug: file_data: {file_data}")
        if file_data:
            old_content = []
            new_content = []
            if 'patch' in file_data:
                for line in file_data['patch'].split('\n'):
                    if line.startswith('-'):
                        old_content.append(line)
                    elif line.startswith('+'):
                        new_content.append(line)
                    else:
                        old_content.append(line)
                        new_content.append(line)

            self.old_diff_view.setPlainText('\n'.join(old_content))
            self.new_diff_view.setPlainText('\n'.join(new_content))
        else:
            self.old_diff_view.setPlainText("No changes")
            self.new_diff_view.setPlainText("No changes")

    def show_blame_popup(self, line_number):
        file_path = self.file_tree.currentIndex().data(Qt.UserRole)
        if file_path:
            repo = self.repo_combo.currentText()
            branch = self.branch_combo.currentText()
            blame_popup = BlamePopup(self, self.token, self.org_name, repo, branch, file_path, line_number)
            blame_popup.setAttribute(Qt.WA_DeleteOnClose)
            blame_popup.show()
        else:
            print("No file selected")
    
    def setup_info_tab(self):
        self.repo_summary = QLabel()
        self.repo_summary.setWordWrap(True)
        self.info_layout.addWidget(self.repo_summary)

        self.language_chart = FigureCanvas(plt.Figure(figsize=(5, 4)))
        self.info_layout.addWidget(self.language_chart)

        self.commit_chart = FigureCanvas(plt.Figure(figsize=(5, 4)))
        self.info_layout.addWidget(self.commit_chart)

        # Add a stretch to push content to the top
        self.info_layout.addStretch(1)
    
    def setup_prs_tab(self):
        main_layout = QHBoxLayout()  # Main horizontal layout
        self.prs_layout.addLayout(main_layout)

        # Left panel (PR list and filters)
        left_panel = QVBoxLayout()

        # Filters
        filter_layout = QHBoxLayout()
        self.owner_filter = QComboBox()
        self.owner_filter.setMinimumWidth(200)  # Increase the minimum width
        self.owner_filter.setStyleSheet("QComboBox { min-height: 30px; }")  # Increase the height
        self.owner_filter.addItem("All Owners")
        self.status_filter = QComboBox()
        self.status_filter.setMinimumWidth(150)  # Increase the minimum width
        self.status_filter.setStyleSheet("QComboBox { min-height: 30px; }")  # Increase the height
        self.status_filter.addItems(["All", "Open", "Closed"])
        filter_layout.addWidget(QLabel("Filter by Owner:"))
        filter_layout.addWidget(self.owner_filter)
        filter_layout.addWidget(QLabel("Filter by Status:"))
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        left_panel.addLayout(filter_layout)

        # PR list
        self.pr_table = QTableWidget()
        self.pr_table.setColumnCount(7)
        self.pr_table.setHorizontalHeaderLabels(["PR #", "Title", "Owner", "Source", "Target", "Date Opened", "Status"])
        self.pr_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.pr_table.horizontalHeader().setStretchLastSection(True)
        self.pr_table.setSelectionBehavior(QTableWidget.SelectRows)
        left_panel.addWidget(self.pr_table)

        main_layout.addLayout(left_panel, 1)  # Add left panel to main layout

        # Right panel (PR details)
        right_panel = QVBoxLayout()

        # Tab widget for Description, Comments, and Reviewers
        self.pr_tabs = QTabWidget()
        
        # Description tab
        description_tab = QWidget()
        description_layout = QVBoxLayout(description_tab)
        
        description_splitter = QSplitter(Qt.Vertical)
        
        self.pr_description_editor = QTextEdit()
        self.pr_description_preview = QWebEngineView()
        
        description_splitter.addWidget(self.pr_description_editor)
        description_splitter.addWidget(self.pr_description_preview)
        
        description_layout.addWidget(description_splitter)
        
        save_button = QPushButton("Save Description")
        save_button.clicked.connect(self.save_pr_description)
        description_layout.addWidget(save_button)
        
        self.pr_tabs.addTab(description_tab, "Description")

        # Comments tab
        comments_tab = QWidget()
        comments_layout = QVBoxLayout(comments_tab)
        self.comments_scroll_area = QScrollArea()
        self.comments_scroll_area.setWidgetResizable(True)
        self.comments_widget = QWidget()
        self.comments_layout = QVBoxLayout(self.comments_widget)
        self.comments_scroll_area.setWidget(self.comments_widget)
        comments_layout.addWidget(self.comments_scroll_area)
        self.pr_tabs.addTab(comments_tab, "Comments")

        # Reviewers tab
        reviewers_tab = QWidget()
        reviewers_layout = QVBoxLayout(reviewers_tab)
        
        # Existing reviewers list
        reviewers_layout.addWidget(QLabel("Current Reviewers:"))
        reviewers_layout.addWidget(self.pr_reviewer_list)

        # Add new reviewer
        add_reviewer_layout = QHBoxLayout()
        add_reviewer_layout.addWidget(self.pr_reviewer_combo)
        add_reviewer_layout.addWidget(self.pr_add_reviewer_button)
        reviewers_layout.addLayout(add_reviewer_layout)

        # Remove reviewer button
        reviewers_layout.addWidget(self.pr_remove_reviewer_button)

        self.pr_tabs.addTab(reviewers_tab, "Reviewers")

        right_panel.addWidget(self.pr_tabs)
        main_layout.addLayout(right_panel, 1)  # Add right panel to main layout

        # Connect signals
        self.pr_table.itemClicked.connect(self.load_pr_details)
        self.pr_description_editor.textChanged.connect(self.update_description_preview)
        self.pr_reviewer_list.itemSelectionChanged.connect(self.update_pr_remove_reviewer_button)
        self.owner_filter.currentTextChanged.connect(self.apply_filters)
        self.status_filter.currentTextChanged.connect(self.apply_filters)

    def apply_filters(self):
        owner = self.owner_filter.currentText()
        status = self.status_filter.currentText()

        for row in range(self.pr_table.rowCount()):
            show_row = True
            if owner != "All Owners" and self.pr_table.item(row, 2).text() != owner:
                show_row = False
            if status != "All" and self.pr_table.item(row, 6).text().lower() != status.lower():
                show_row = False
            self.pr_table.setRowHidden(row, not show_row)

    def setup_open_pr_tab(self):
        # Top panel
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)

        # Branch selection
        branch_widget = QWidget()
        branch_layout = QVBoxLayout(branch_widget)
        self.source_branch_combo = QComboBox()
        self.dest_branch_combo = QComboBox()
        branch_layout.addWidget(QLabel("Source Branch:"))
        branch_layout.addWidget(self.source_branch_combo)
        branch_layout.addWidget(QLabel("Destination Branch:"))
        branch_layout.addWidget(self.dest_branch_combo)
        top_layout.addWidget(branch_widget)

        # Reviewers selection
        reviewer_widget = QWidget()
        reviewer_layout = QVBoxLayout(reviewer_widget)
        self.user_combo = QComboBox()
        add_reviewer_button = QPushButton("Add Reviewer")
        add_reviewer_button.clicked.connect(self.add_reviewer)
        reviewer_layout.addWidget(QLabel("Select Reviewer:"))
        reviewer_layout.addWidget(self.user_combo)
        reviewer_layout.addWidget(add_reviewer_button)
        self.reviewer_list = QListWidget()
        reviewer_layout.addWidget(self.reviewer_list)
        top_layout.addWidget(reviewer_widget)

        # Create PR button
        create_pr_button = QPushButton("Create PR")
        create_pr_button.clicked.connect(self.create_pr)
        top_layout.addWidget(create_pr_button, alignment=Qt.AlignTop | Qt.AlignRight)

        self.open_pr_layout.addWidget(top_panel)

        # Bottom panel
        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)
        self.file_changes_combo = QComboBox()
        self.file_changes_combo.currentTextChanged.connect(self.load_pr_file_diff)
        bottom_layout.addWidget(QLabel("Changed Files:"))
        bottom_layout.addWidget(self.file_changes_combo)

        diff_widget = QSplitter(Qt.Horizontal)
        self.old_diff_view = QPlainTextEdit()
        self.old_diff_view.setReadOnly(True)
        self.new_diff_view = QPlainTextEdit()
        self.new_diff_view.setReadOnly(True)
        diff_widget.addWidget(self.old_diff_view)
        diff_widget.addWidget(self.new_diff_view)
        bottom_layout.addWidget(diff_widget)

        self.open_pr_layout.addWidget(bottom_panel)

        # Load initial data
        self.load_branches()
        self.load_users()
        self.source_branch_combo.currentTextChanged.connect(self.update_file_changes)
        self.dest_branch_combo.currentTextChanged.connect(self.update_file_changes)
    
    def update_file_changes(self):
        repo = self.repo_combo.currentText()
        source_branch = self.source_branch_combo.currentText()
        dest_branch = self.dest_branch_combo.currentText()
        
        if not repo or not source_branch or not dest_branch:
            self.file_changes_combo.clear()
            return

        headers = {"Authorization": f"token {self.token}"}
        
        try:
            response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/compare/{dest_branch}...{source_branch}",
                headers=headers
            )
            response.raise_for_status()
            compare_data = response.json()
            
            self.file_changes_combo.clear()
            for file in compare_data['files']:
                self.file_changes_combo.addItem(file['filename'])
            
            # Load the first file diff by default
            if self.file_changes_combo.count() > 0:
                self.load_pr_file_diff(self.file_changes_combo.itemText(0))
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to fetch file changes: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    error_message = f"Could not compare branches. Make sure both branches exist and you have access to them."
                elif e.response.status_code == 401:
                    error_message = "Authentication failed. Please check your GitHub token."
            QMessageBox.warning(self, "Error", error_message)
            self.file_changes_combo.clear()
    
    def load_pr_file_diff(self, filename):
        if not filename:
            return
        
        repo = self.repo_combo.currentText()
        source_branch = self.source_branch_combo.currentText()
        dest_branch = self.dest_branch_combo.currentText()
        headers = {"Authorization": f"token {self.token}"}
        
        try:
            self.show_loading_overlay()
            
            compare_url = f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/compare/{dest_branch}...{source_branch}"
            response = requests.get(compare_url, headers=headers)
            response.raise_for_status()
            compare_data = response.json()
            
            file_found = False
            for file in compare_data['files']:
                if file['filename'] == filename:
                    file_found = True
                    if 'patch' in file:
                        lines = file['patch'].split('\n')
                        old_content = []
                        new_content = []
                        for line in lines:
                            if line.startswith('-'):
                                old_content.append(line)
                                new_content.append('')
                            elif line.startswith('+'):
                                old_content.append('')
                                new_content.append(line)
                            else:
                                old_content.append(line)
                                new_content.append(line)
                        self.old_diff_view.setPlainText('\n'.join(old_content))
                        self.new_diff_view.setPlainText('\n'.join(new_content))
                    else:
                        self.old_diff_view.setPlainText(f"No changes in file: {filename}")
                        self.new_diff_view.setPlainText(f"No changes in file: {filename}")
                    break
            
            if not file_found:
                self.old_diff_view.setPlainText(f"File {filename} not found in the diff")
                self.new_diff_view.setPlainText(f"File {filename} not found in the diff")

        except requests.RequestException as e:
            error_message = f"Failed to fetch file diff: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    error_message = f"File {filename} not found in the repository"
                elif e.response.status_code == 401:
                    error_message = "Authentication failed. Please check your GitHub token."
            QMessageBox.warning(self, "Error", error_message)
            self.old_diff_view.setPlainText(error_message)
            self.new_diff_view.setPlainText(error_message)
        finally:
            self.hide_loading_overlay()

        # Ensure both views are scrolled to the top after loading new content
        self.old_diff_view.verticalScrollBar().setValue(0)
        self.new_diff_view.verticalScrollBar().setValue(0)
    
    def create_pr(self):
        repo = self.repo_combo.currentText()
        source_branch = self.source_branch_combo.currentText()
        dest_branch = self.dest_branch_combo.currentText()
        reviewers = [self.create_pr_reviewer_list.item(i).text() for i in range(self.create_pr_reviewer_list.count())]

        
        
        confirmation = QMessageBox.question(self, "Create PR", 
                                            f"Are you sure you want to create a PR?\n\nRepo: {repo}\nFrom: {source_branch}\nTo: {dest_branch}\nReviewers: {', '.join(reviewers)}",
                                            QMessageBox.Yes | QMessageBox.No)
        
        if confirmation == QMessageBox.Yes:
            headers = {"Authorization": f"token {self.token}"}
            data = {
                "title": "New Pull Request",  # You might want to add a title input field
                "head": source_branch,
                "base": dest_branch,
                "body": "Pull request created via GitHub Insights Tab"  # You might want to add a description input field
            }
            
            try:
                response = requests.post(
                    f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls",
                    json=data,
                    headers=headers
                )
                response.raise_for_status()
                pr_data = response.json()
                pr_number = pr_data['number']
                
                # Add reviewers
                if reviewers:
                    requests.post(
                        f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/requested_reviewers",
                        json={"reviewers": reviewers},
                        headers=headers
                    )
                
                QMessageBox.information(self, "PR Created", f"Pull Request #{pr_number} has been created successfully.")
                return pr_number
            except requests.exceptions.RequestException as e:
                QMessageBox.warning(self, "Error", f"Failed to create PR: {str(e)}")
                return None
        else:
            return None

    
    def add_reviewer(self):
        reviewer = self.reviewer_combo.currentText()
        if reviewer and self.reviewer_list.findItems(reviewer, Qt.MatchExactly) == []:
            if hasattr(self, 'current_pr_number'):
                # We're in the PR tab, so update the PR
                self.add_reviewer_to_pr(reviewer)
            else:
                # We're in the Create PR tab, just add to the list
                self.reviewer_list.addItem(reviewer)
    
    def add_reviewer_to_pr(self, reviewer):
        repo = self.repo_combo.currentText()
        pr_number = self.current_pr_number
        headers = {"Authorization": f"token {self.token}"}
        
        try:
            response = requests.post(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/requested_reviewers",
                json={"reviewers": [reviewer]},
                headers=headers
            )
            response.raise_for_status()
            self.pr_reviewer_list.addItem(reviewer)  # Changed from self.reviewer_list to self.pr_reviewer_list
        except requests.exceptions.RequestException as e:
            self.show_error_message(f"Failed to add reviewer: {str(e)}")
    

    
    def load_users(self):
        repo = self.repo_combo.currentText()
        if not repo:
            QMessageBox.warning(self, "Error", "No repository selected. Please select a repository first.")
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/collaborators", headers=headers)
            response.raise_for_status()
            users = [user['login'] for user in response.json()]
            self.user_combo.clear()
            self.user_combo.addItems(users)
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to fetch users: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    error_message = f"Repository '{repo}' not found or you don't have access to view collaborators."
                elif e.response.status_code == 401:
                    error_message = "Authentication failed. Please check your GitHub token."
                elif e.response.status_code == 403:
                    error_message = "You don't have permission to view collaborators for this repository."
            QMessageBox.warning(self, "Error", error_message)
    
    def load_branches(self):
        repo = self.repo_combo.currentText()
        if not repo:
            QMessageBox.warning(self, "Error", "No repository selected. Please select a repository first.")
            return

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.get(f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/branches", headers=headers)
            response.raise_for_status()
            branches = [branch['name'] for branch in response.json()]
            self.source_branch_combo.clear()
            self.dest_branch_combo.clear()
            self.source_branch_combo.addItems(branches)
            self.dest_branch_combo.addItems(branches)
        except requests.exceptions.RequestException as e:
            error_message = f"Failed to fetch branches: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code == 404:
                    error_message = f"Repository '{repo}' not found. Please check if it exists and you have access to it."
                elif e.response.status_code == 401:
                    error_message = "Authentication failed. Please check your GitHub token."
            QMessageBox.warning(self, "Error", error_message)
    
    def update_description_preview(self):
        markdown_text = self.pr_description_editor.toPlainText()
        html_text = markdown.markdown(markdown_text)

        # Replace relative image URLs with absolute URLs
        repo = self.repo_combo.currentText()
        base_url = f"https://github.hpe.com/{self.org_name}/{repo}/raw/master/"
        html_text = re.sub(r'<img src="(?!http)([^"]+)"', f'<img src="{base_url}\\1"', html_text)

        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    padding: 20px;
                }}
                img {{
                    max-width: 100%;
                    height: auto;
                }}
                pre {{
                    background-color: #f4f4f4;
                    padding: 10px;
                    border-radius: 5px;
                }}
                code {{
                    font-family: Consolas, monospace;
                }}
            </style>
        </head>
        <body>
        {content}
        </body>
        </html>
        """

        full_html = html_template.format(content=html_text)
        self.pr_description_preview.setHtml(full_html, QUrl(f"https://github.hpe.com/{self.org_name}/{repo}/"))
    
    def save_pr_description(self):
        if not hasattr(self, 'current_pr_number'):
            QMessageBox.warning(self, "Error", "No PR selected")
            return

        new_description = self.pr_description_editor.toPlainText()
        repo = self.repo_combo.currentText()
        pr_number = self.current_pr_number

        headers = {"Authorization": f"token {self.token}"}
        try:
            response = requests.patch(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}",
                json={"body": new_description},
                headers=headers
            )
            response.raise_for_status()
            QMessageBox.information(self, "Success", "PR description updated successfully")
            
            # Refresh PR details
            self.load_pr_details(pr_number)
        except requests.exceptions.RequestException as e:
            QMessageBox.warning(self, "Error", f"Failed to update PR description: {str(e)}")

    def load_pr_comments(self, repo, pr_number):
        headers = {"Authorization": f"token {self.token}"}
        try:
            # Fetch PR details including description
            pr_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}",
                headers=headers
            )
            pr_response.raise_for_status()
            pr_data = pr_response.json()

            # Fetch PR comments (review comments)
            review_comments_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/pulls/{pr_number}/comments",
                headers=headers
            )
            review_comments_response.raise_for_status()
            review_comments = review_comments_response.json()

            # Fetch PR issue comments (conversation)
            issue_comments_response = requests.get(
                f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/issues/{pr_number}/comments",
                headers=headers
            )
            issue_comments_response.raise_for_status()
            issue_comments = issue_comments_response.json()

            # Combine all comments
            all_comments = [
                {
                    "type": "description",
                    "user": pr_data["user"],
                    "body": pr_data["body"],
                    "created_at": pr_data["created_at"],
                }
            ] + [
                {**comment, "type": "issue_comment"}
                for comment in issue_comments
            ] + [
                {**comment, "type": "review_comment"}
                for comment in review_comments
            ]

            # Sort all comments by creation time
            all_comments.sort(key=lambda x: x["created_at"])

            for comment in all_comments:
                if comment["type"] == "review_comment" and 'path' in comment:
                    try:
                        # Use the commit_id from the comment to fetch the correct version of the file
                        file_response = requests.get(
                            f"https://github.hpe.com/api/v3/repos/{self.org_name}/{repo}/contents/{comment['path']}?ref={comment['commit_id']}",
                            headers=headers
                        )
                        file_response.raise_for_status()
                        file_content = base64.b64decode(file_response.json()['content']).decode('utf-8')
                        lines = file_content.splitlines()
                        
                        if 'diff_hunk' in comment:
                            comment['code_snippet'] = comment['diff_hunk']
                        else:
                            position = comment.get('position') or comment.get('original_position')
                            if position is not None:
                                start = max(0, position - 3)
                                end = min(len(lines), position + 3)
                                comment['code_snippet'] = '\n'.join(lines[start:end])
                            else:
                                comment['code_snippet'] = "Code snippet not available"
                        
                    except requests.exceptions.RequestException as file_error:
                        if file_error.response.status_code == 404:
                            comment['code_snippet'] = f"File not found: {comment['path']}\nThe file may have been deleted or moved."
                        else:
                            comment['code_snippet'] = f"Error fetching code snippet: {str(file_error)}"
                    
                    print(f"Debug: Comment {comment.get('id')} - Code snippet: {comment['code_snippet'][:100]}...")  # Debug print

            self.update_pr_comments(all_comments)
        except requests.exceptions.RequestException as e:
            self.signals.error_occurred.emit(f"Failed to fetch PR comments: {str(e)}")

    def update_pr_comments(self, comments):
        # Clear existing comments
        while self.comments_layout.count():
            item = self.comments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Create a dictionary to store threads
        threads = {}

        for comment in comments:
            if comment['type'] == 'description':
                # PR description is always at the top
                comment_widget = CommentWidget(comment)
                self.comments_layout.addWidget(comment_widget)
                self.comments_layout.addWidget(CommentSeparator())
            elif comment['type'] == 'issue_comment':
                # Issue comments are part of the main conversation
                comment_widget = CommentWidget(comment)
                self.comments_layout.addWidget(comment_widget)
                self.comments_layout.addWidget(CommentSeparator())
            elif comment['type'] == 'review_comment':
                # Review comments are grouped by their original_position
                thread_key = (comment.get('path', ''), comment.get('original_position', ''))
                if thread_key not in threads:
                    threads[thread_key] = []
                threads[thread_key].append(comment)

        # Add review comment threads
        for thread in threads.values():
            thread_widget = QWidget()
            thread_layout = QVBoxLayout(thread_widget)
            for comment in thread:
                comment_widget = CommentWidget(comment)
                thread_layout.addWidget(comment_widget)
            self.comments_layout.addWidget(thread_widget)
            self.comments_layout.addWidget(CommentSeparator())

        # Add stretch to push all comments to the top
        self.comments_layout.addStretch()


    def resolve_comment(self, comment):
        # Implement the logic to resolve the comment
        # This might involve making an API call to GitHub to update the comment status
        print(f"Resolving comment: {comment['id']}")
        # After resolving, you might want to refresh the comments list
        # self.load_pr_comments(self.repo_combo.currentText(), self.current_pr_number)

    def setup_browse_tab(self):
        browse_layout = QVBoxLayout()

        # Branch selection and search
        top_layout = QHBoxLayout()
        self.branch_combo = QComboBox()
        self.branch_combo.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(QLabel("Branch:"))
        top_layout.addWidget(self.branch_combo)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search in repository...")
        self.search_input.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(self.search_input)
        # Add copy and download buttons
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_file_content)
        top_layout.addWidget(self.copy_button)

        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.download_file_content)
        top_layout.addWidget(self.download_button)

        browse_layout.addLayout(top_layout)
        browse_layout.addLayout(top_layout)
        

        self.browse_layout.addLayout(browse_layout)

        # File browser and content viewer
        splitter = QSplitter(Qt.Horizontal)
        self.file_tree = QTreeView(self)  # Ensure it's a child of this widget
        self.file_tree.setStyleSheet("font-size: 18px;")
        splitter.addWidget(self.file_tree)
        browse_layout.addWidget(splitter)
        
        self.file_content = CodeEditor(self)
        self.file_content.setReadOnly(True)
        self.file_content.set_github_insights_tab(self)
        self.file_content.line_number_area.mousePressEvent = self.file_content.line_number_area_mouse_press_event
        splitter.addWidget(self.file_content)
        self.browse_layout.addLayout(browse_layout)

        # Connect signals
        self.branch_combo.currentTextChanged.connect(self.load_file_structure)
        self.file_tree.clicked.connect(self.load_file_content)
        self.search_input.returnPressed.connect(self.search_repository)
    

    def show_error_message(self, message):
        QMessageBox.warning(self, "Error", message)

    def copy_file_content(self):
        content = self.file_content.toPlainText()
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(content)
        QMessageBox.information(self, "Copied", "File content copied to clipboard.")

    def download_file_content(self):
        content = self.file_content.toPlainText()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save File", "", "All Files (*)")
        if file_path:
            try:
                with open(file_path, 'w') as file:
                    file.write(content)
                QMessageBox.information(self, "Downloaded", f"File content saved to {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to save file: {str(e)}")
