import os
import json
import yaml
from PyQt5.QtWidgets import (QWidget, QInputDialog, QFileSystemModel, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStyle,
                             QMenu, QAction, QMessageBox, QApplication, QFrame, QTextEdit, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize, QUrl
from PyQt5.QtGui import QDrag, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QColor
import pygments
from pygments.lexers import get_lexer_for_filename
from .utils import SyntaxHighlighter

class FileEditDialog(QDialog):
    def __init__(self, content, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {os.path.basename(file_path)}")
        self.setGeometry(100, 100, 800, 600)
        
        layout = QVBoxLayout(self)
        
        self.editor = QTextEdit()
        self.editor.setPlainText(content)
        layout.addWidget(self.editor)
        
        self.format_button = QPushButton("Check Format")
        self.format_button.clicked.connect(self.check_format)
        layout.addWidget(self.format_button)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.file_path = file_path
        
        try:
            lexer = get_lexer_for_filename(file_path)
            highlighter = SyntaxHighlighter(self.editor.document(), lexer)
        except:
            pass

    def get_content(self):
        return self.editor.toPlainText()

    def check_format(self):
        content = self.editor.toPlainText()
        file_ext = os.path.splitext(self.file_path)[1].lower()

        # Clear previous highlighting
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.Document)
        format = QTextCharFormat()
        format.setBackground(Qt.transparent)
        cursor.mergeCharFormat(format)

        try:
            if file_ext in ['.json']:
                json.loads(content)
            elif file_ext in ['.yaml', '.yml']:
                yaml.safe_load(content)
            # Add more format checks here for other file types
            
            QMessageBox.information(self, "Format Check", "The file format is valid.")
        except Exception as e:
            error_message = str(e)
            line_number = 1
            if "line" in error_message:
                try:
                    line_number = int(error_message.split("line")[1].split(",")[0].strip())
                except:
                    pass
            
            cursor.movePosition(QTextCursor.Start)
            for _ in range(line_number - 1):
                cursor.movePosition(QTextCursor.NextBlock)
            cursor.select(QTextCursor.LineUnderCursor)
            format = QTextCharFormat()
            format.setBackground(QColor("yellow"))
            cursor.mergeCharFormat(format)
            
            QMessageBox.warning(self, "Format Error", f"The file format is invalid: {error_message}")