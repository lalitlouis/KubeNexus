
import psutil
from PyQt5.QtWidgets import (QWidget, QInputDialog, QFileSystemModel, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStyle,
                             QMenu, QAction, QMessageBox, QApplication, QFrame, QTextEdit, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt
from pygments.formatters import BBCodeFormatter
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from datetime import datetime
import matplotlib
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QTableWidget, QHeaderView, QGridLayout

class ApplicationTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Name", "PID", "CPU %"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.itemSelectionChanged.connect(self.on_selection_changed)

        self.force_quit_button = QPushButton("Force Quit")
        self.force_quit_button.clicked.connect(self.force_quit_app)

    def search_applications(self, search_text):
        search_text = search_text.lower()
        for row in range(self.rowCount()):
            if search_text in self.item(row, 0).text().lower():
                self.setRowHidden(row, False)
            else:
                self.setRowHidden(row, True)

    def load_applications(self):
        self.setRowCount(0)
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                if proc.exe():  # Only include processes with an executable path
                    row_position = self.rowCount()
                    self.insertRow(row_position)
                    self.setItem(row_position, 0, QTableWidgetItem(proc.name()))
                    self.setItem(row_position, 1, QTableWidgetItem(str(proc.pid)))
                    self.setItem(row_position, 2, QTableWidgetItem(f"{proc.cpu_percent():.2f}"))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        self.sortItems(2, Qt.DescendingOrder)  # Sort by CPU usage

    def on_selection_changed(self):
        selected_items = self.selectedItems()
        if selected_items:
            self.force_quit_button.setEnabled(True)
        else:
            self.force_quit_button.setEnabled(False)

    def force_quit_app(self):
        selected_items = self.selectedItems()
        if selected_items:
            pid = int(self.item(selected_items[0].row(), 1).text())
            try:
                process = psutil.Process(pid)
                process.terminate()
                QMessageBox.information(self, "Force Quit", f"Application with PID {pid} has been terminated.")
                self.load_applications()
            except psutil.NoSuchProcess:
                QMessageBox.warning(self, "Error", f"Application with PID {pid} not found.")
            except psutil.AccessDenied:
                QMessageBox.warning(self, "Error", f"Access denied. Unable to terminate application with PID {pid}.")
