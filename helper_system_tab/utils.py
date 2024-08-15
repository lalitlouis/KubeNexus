
import os
import psutil
from PyQt5.QtWidgets import (QWidget, QInputDialog, QFileSystemModel, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStyle,
                             QMenu, QAction, QMessageBox, QApplication, QFrame, QTextEdit, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize, QUrl
from PyQt5.QtGui import QDrag, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QColor
from pygments.lexers import get_lexer_for_filename
from pygments.formatters import BBCodeFormatter


class SyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent, lexer):
        super().__init__(parent)
        self.lexer = lexer
        self.formatter = BBCodeFormatter()

    def highlightBlock(self, text):
        tokens = self.lexer.get_tokens(text)
        for token, value in tokens:
            format = QTextCharFormat()
            color = self.formatter.style_for_token(token)['color']
            if color:
                format.setForeground(QColor(f"#{color}"))
            self.setFormat(self.currentBlock().position(), len(value), format)

class FileContentViewer(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        font = QFont("Courier", 10)
        self.setFont(font)

    def set_content(self, content, file_path):
        self.setPlainText(content)
        try:
            lexer = get_lexer_for_filename(file_path)
            highlighter = SyntaxHighlighter(self.document(), lexer)
        except:
            pass  # If no lexer is found, no syntax highlighting will be applied



class SystemInfoThread(QThread):
    update_signal = pyqtSignal(dict)

    def run(self):
        while True:
            info = {
                'cpu': psutil.cpu_percent(interval=1),
                'memory': psutil.virtual_memory().percent,
                'disk': psutil.disk_usage('/').percent
            }
            self.update_signal.emit(info)
            self.sleep(1)

