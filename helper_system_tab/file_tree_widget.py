import os
import shutil
from PyQt5.QtWidgets import (QWidget, QInputDialog, QFileSystemModel, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStyle,QTreeView,
                             QMenu, QAction, QMessageBox, QApplication, QFrame, QTextEdit, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize, QUrl, QDir
from PyQt5.QtGui import QDrag, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from datetime import datetime
import zipfile


class FileContentDialog(QDialog):
    def __init__(self, content, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Content of {os.path.basename(file_path)}")
        self.setGeometry(100, 100, 800, 600)
        
        layout = QVBoxLayout(self)
        
        self.content_view = QTextEdit()
        self.content_view.setPlainText(content)
        self.content_view.setReadOnly(True)
        layout.addWidget(self.content_view)
        
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

class FileTreeWidget(QWidget):
    itemClicked = pyqtSignal(object, int)  # custom signal
    itemDoubleClicked = pyqtSignal(object)  # new signal for double-click

    def __init__(self, path_label, shared_clipboard, parent=None):
        super().__init__(parent)
        self.path_label = path_label
        self.shared_clipboard = shared_clipboard
        
        layout = QVBoxLayout(self)
        
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search files...")
        self.search_input.textChanged.connect(self.filter_files)
        layout.addWidget(self.search_input)
        
        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        
        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(QDir.homePath()))
        self.tree.setColumnWidth(0, 250)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeView.ExtendedSelection)
        layout.addWidget(self.tree)
        
        self.tree.clicked.connect(self.on_item_clicked)
        self.tree.doubleClicked.connect(self.on_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.open_context_menu)
        
        self.current_path = QDir.homePath()
        self.path_history = [self.current_path]
        self.history_index = 0
        self.path_label.setText(self.current_path)

    def clear(self):
        self.model.setRootPath("")
        self.tree.setRootIndex(self.model.index(""))

    def filter_files(self, text):
        if text:
            self.model.setNameFilters([f"*{text}*"])
            self.model.setNameFilterDisables(False)
        else:
            self.model.setNameFilters([])

    def on_item_clicked(self, index):
        file_path = self.model.filePath(index)
        self.path_label.setText(file_path)
        self.itemClicked.emit(index, 0)  # Emit the custom signal

    def navigate_home(self):
        home_path = QDir.homePath()
        self.load_file_system(home_path)

    def navigate_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.load_file_system(self.path_history[self.history_index])

    def navigate_forward(self):
        if self.history_index < len(self.path_history) - 1:
            self.history_index += 1
            self.load_file_system(self.path_history[self.history_index])

    def load_file_system(self, path):
        index = self.model.index(path)
        if index.isValid():
            self.tree.setRootIndex(index)
            self.current_path = path
            self.path_label.setText(path)
            
            if self.history_index < len(self.path_history) - 1:
                self.path_history = self.path_history[:self.history_index + 1]
            if self.path_history[-1] != path:
                self.path_history.append(path)
                self.history_index = len(self.path_history) - 1
            
            # Ensure the model updates its root path
            self.model.setRootPath(path)

    def on_item_double_clicked(self, index):
        file_path = self.model.filePath(index)
        if self.model.isDir(index):
            self.load_file_system(file_path)
        else:
            self.itemDoubleClicked.emit(index)  # Emit the double-click signal

    def open_context_menu(self, position):
        index = self.tree.indexAt(position)
        if index.isValid():
            menu = QMenu(self)
            copy_action = QAction('Copy', self)
            cut_action = QAction('Cut', self)
            paste_action = QAction('Paste', self)
            delete_action = QAction('Delete', self)
            rename_action = QAction('Rename', self)

            copy_action.triggered.connect(lambda: self.copy_items(index))
            cut_action.triggered.connect(lambda: self.cut_items(index))
            paste_action.triggered.connect(self.paste_items)
            delete_action.triggered.connect(lambda: self.delete_items(index))
            rename_action.triggered.connect(lambda: self.rename_item(index))

            menu.addAction(copy_action)
            menu.addAction(cut_action)
            menu.addAction(paste_action)
            menu.addAction(delete_action)
            menu.addAction(rename_action)

            menu.exec_(self.tree.viewport().mapToGlobal(position))

    def copy_items(self, index):
        self.shared_clipboard['action'] = 'copy'
        self.shared_clipboard['items'] = [self.model.filePath(idx) for idx in self.tree.selectedIndexes() if idx.column() == 0]

    def cut_items(self, index):
        self.shared_clipboard['action'] = 'cut'
        self.shared_clipboard['items'] = [self.model.filePath(idx) for idx in self.tree.selectedIndexes() if idx.column() == 0]

    def paste_items(self):
        if 'items' in self.shared_clipboard:
            for item_path in self.shared_clipboard['items']:
                dest_path = os.path.join(self.current_path, os.path.basename(item_path))
                if os.path.exists(dest_path):
                    reply = QMessageBox.question(self, 'File Exists',
                                                f"File {os.path.basename(dest_path)} already exists. Overwrite?",
                                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply == QMessageBox.No:
                        base, ext = os.path.splitext(dest_path)
                        counter = 1
                        while os.path.exists(f"{base}({counter}){ext}"):
                            counter += 1
                        dest_path = f"{base}({counter}){ext}"

                try:
                    if self.shared_clipboard['action'] == 'copy':
                        if os.path.isdir(item_path):
                            shutil.copytree(item_path, dest_path)
                        else:
                            shutil.copy2(item_path, dest_path)
                    elif self.shared_clipboard['action'] == 'cut':
                        shutil.move(item_path, dest_path)
                except Exception as e:
                    QMessageBox.warning(self, "Paste Error", f"Could not paste {item_path}: {str(e)}")

            if self.shared_clipboard['action'] == 'cut':
                self.shared_clipboard['items'] = []
            self.model.setRootPath(self.current_path)  # Refresh the view

    def delete_items(self, index):
        selected_indexes = self.tree.selectedIndexes()
        if selected_indexes:
            reply = QMessageBox.question(self, 'Delete Confirmation',
                                         f"Are you sure you want to delete {len(selected_indexes)} item(s)?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                for idx in selected_indexes:
                    if idx.column() == 0:  # Only process the first column to avoid duplicates
                        path = self.model.filePath(idx)
                        try:
                            if os.path.isdir(path):
                                shutil.rmtree(path)
                            else:
                                os.remove(path)
                        except Exception as e:
                            QMessageBox.warning(self, "Delete Error", f"Could not delete {path}: {str(e)}")
                self.model.setRootPath(self.current_path)  # Refresh the view

    def rename_item(self, index):
        if index.isValid():
            old_name = self.model.fileName(index)
            new_name, ok = QInputDialog.getText(self, 'Rename', 'Enter new name:', text=old_name)
            if ok and new_name:
                old_path = self.model.filePath(index)
                new_path = os.path.join(os.path.dirname(old_path), new_name)
                try:
                    os.rename(old_path, new_path)
                    self.model.setRootPath(self.current_path)  # Refresh the view
                except Exception as e:
                    QMessageBox.warning(self, "Rename Error", f"Could not rename file: {str(e)}")

    def search_files(self):
        search_text = self.search_input.text().lower()
        self.filter_files(search_text)