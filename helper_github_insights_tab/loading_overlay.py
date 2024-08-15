from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor

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