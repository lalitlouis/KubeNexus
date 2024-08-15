import os
import shutil
import psutil
import platform
import json
import yaml
from PyQt5.QtWidgets import (QWidget, QInputDialog, QFileSystemModel, QVBoxLayout, QHBoxLayout, QTabWidget, QTreeWidget, QTreeWidgetItem,
                             QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QStyle,
                             QMenu, QAction, QMessageBox, QApplication, QFrame, QTextEdit, QDialog, QDialogButtonBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize, QUrl
from PyQt5.QtGui import QDrag, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QColor
import pygments
from pygments.lexers import get_lexer_for_filename
from pygments.formatters import BBCodeFormatter
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from datetime import datetime
import matplotlib
from matplotlib.figure import Figure
from PyQt5.QtWidgets import QTableWidget, QHeaderView, QGridLayout
import paramiko
import zipfile
import time
import stat

from helper_system_tab.file_tree_widget import FileTreeWidget
from helper_system_tab.ssh_dialog import SSHDialog
from helper_system_tab.ssh_file_browser import SSHFileBrowser
from helper_system_tab.file_edit_dialog import FileEditDialog
from helper_system_tab.application_table import ApplicationTable
from helper_system_tab.utils import FileContentViewer, SystemInfoThread

matplotlib.use('Qt5Agg')

class SystemTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.shared_clipboard = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # System Overview tab
        overview_tab = QWidget()
        overview_layout = QHBoxLayout(overview_tab)

        # Left panel - system info
        left_panel = QVBoxLayout()
        self.system_table = self.create_info_table("System Information")
        self.cpu_table = self.create_info_table("CPU Information")
        self.memory_table = self.create_info_table("Memory Information")
        self.disk_table = self.create_info_table("Disk Information")
        self.network_table = self.create_info_table("Network Information")

        left_panel.addWidget(self.system_table)
        left_panel.addWidget(self.cpu_table)
        left_panel.addWidget(self.memory_table)
        left_panel.addWidget(self.disk_table)
        left_panel.addWidget(self.network_table)
        left_panel.addStretch()

        # Right panel - charts
        right_panel = QVBoxLayout()
        self.charts_layout = QGridLayout()
        right_panel.addLayout(self.charts_layout)

        self.setup_charts()

        # Use QSplitter to manage space
        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([200, 400])

        overview_layout.addWidget(splitter)

        overview_tab.setLayout(overview_layout)

        # File Browser tab
        file_browser_tab = QWidget()
        file_browser_layout = QHBoxLayout(file_browser_tab)

        # Left file browser
        left_panel = QVBoxLayout()
        left_nav_layout = QHBoxLayout()
        # Add SSH button
        self.ssh_button = QPushButton("SSH")
        self.ssh_button.clicked.connect(self.open_ssh_dialog)
        left_nav_layout.addWidget(self.ssh_button)
        self.left_home_button = QPushButton("Home")
        self.left_back_button = QPushButton("Back")
        self.left_forward_button = QPushButton("Forward")
        left_nav_layout.addWidget(self.left_home_button)
        left_nav_layout.addWidget(self.left_back_button)
        left_nav_layout.addWidget(self.left_forward_button)
        self.left_current_path = QLabel(os.path.expanduser("~"))
        left_panel.addWidget(self.left_current_path)
        left_panel.addLayout(left_nav_layout)
        self.left_file_tree = FileTreeWidget(self.left_current_path, self.shared_clipboard, parent=self)
        left_panel.addWidget(self.left_file_tree.search_input)
        left_panel.addWidget(self.left_file_tree)

        # Right content viewer
        right_panel = QVBoxLayout()
        right_button_layout = QHBoxLayout()  
        self.delete_button = QPushButton("Delete")
        self.edit_button = QPushButton("Edit")
        right_button_layout.addWidget(self.delete_button)
        right_button_layout.addWidget(self.edit_button)
        right_panel.addLayout(right_button_layout)
        self.file_content_viewer = FileContentViewer()
        right_panel.addWidget(self.file_content_viewer)

        # Connect signals
        self.left_home_button.clicked.connect(self.left_file_tree.navigate_home)
        self.left_back_button.clicked.connect(self.left_file_tree.navigate_back)
        self.left_forward_button.clicked.connect(self.left_file_tree.navigate_forward)
        self.left_file_tree.itemClicked.connect(self.on_file_clicked)
        self.delete_button.clicked.connect(self.delete_file)
        self.edit_button.clicked.connect(self.edit_file)

        # Add panels to the file browser layout
        file_browser_splitter = QSplitter(Qt.Horizontal)
        left_frame = QFrame()
        left_frame.setLayout(left_panel)
        left_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        right_frame = QFrame()
        right_frame.setLayout(right_panel)
        right_frame.setFrameStyle(QFrame.Box | QFrame.Raised)
        file_browser_splitter.addWidget(left_frame)
        file_browser_splitter.addWidget(right_frame)
        file_browser_splitter.setSizes([int(self.width() * 0.4), int(self.width() * 0.6)])
        file_browser_layout.addWidget(file_browser_splitter)

        # Activity Monitor tab
        activity_tab = QWidget()
        activity_layout = QVBoxLayout(activity_tab)

        # Add search input for applications
        self.application_search_input = QLineEdit()
        self.application_search_input.setPlaceholderText("Search applications...")
        activity_layout.addWidget(self.application_search_input)

        application_splitter = QSplitter(Qt.Horizontal)
        self.application_details = QTextEdit()
        self.application_details.setReadOnly(True)
        self.application_table = ApplicationTable()
        application_splitter.addWidget(self.application_table)

        application_details_widget = QWidget()
        application_details_layout = QVBoxLayout(application_details_widget)
        application_details_layout.addWidget(self.application_details)
        application_details_layout.addWidget(self.application_table.force_quit_button)
        application_splitter.addWidget(application_details_widget)

        activity_layout.addWidget(application_splitter)

        tabs.addTab(overview_tab, "System Overview")
        tabs.addTab(file_browser_tab, "File Browser")
        tabs.addTab(activity_tab, "Activity Monitor")
        layout.addWidget(tabs)

        self.load_system_info()
        self.left_file_tree.load_file_system(os.path.expanduser("~"))
        self.application_table.load_applications()

        self.info_thread = SystemInfoThread()
        self.info_thread.update_signal.connect(self.update_system_info)
        self.info_thread.start()

        # Connect application search
        self.application_search_input.textChanged.connect(self.application_table.search_applications)

        # Set font size for all widgets
        font = QFont()
        font.setPointSize(12)
        self.setFont(font)

    def open_ssh_dialog(self):
        ssh_dialog = SSHDialog(self)
        if ssh_dialog.exec_() == QDialog.Accepted and ssh_dialog.ssh_client:
            ssh_browser = SSHFileBrowser(ssh_dialog.ssh_client, self)
            ssh_browser.exec_()

    def on_file_clicked(self, index, column):
        file_path = self.left_file_tree.model.filePath(index)
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'r', errors='ignore') as file:
                    content = file.read()
                self.file_content_viewer.set_content(content, file_path)
                self.current_file_path = file_path
                self.delete_button.setEnabled(True)
                self.edit_button.setEnabled(True)
            except Exception:
                self.file_content_viewer.clear()
                self.current_file_path = None
                self.delete_button.setEnabled(False)
                self.edit_button.setEnabled(False)
        else:
            self.file_content_viewer.clear()
            self.current_file_path = None
            self.delete_button.setEnabled(False)
            self.edit_button.setEnabled(False)

    def create_info_table(self, title):
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([title, "Value"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet("QTableWidget { border: none; }")
        return table

    def create_chart(self, title):
        figure = Figure(figsize=(4, 3), facecolor='#F0F0F0')
        canvas = FigureCanvas(figure)
        ax = figure.add_subplot(111)
        ax.set_title(title, fontsize=10, fontweight='bold')
        figure.subplots_adjust(bottom=0.2)  # Add more space at the bottom
        return canvas, ax

    def delete_file(self):
        if self.current_file_path:
            reply = QMessageBox.question(self, 'Delete Confirmation',
                                         f"Are you sure you want to delete {self.current_file_path}?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                try:
                    os.remove(self.current_file_path)
                    self.left_file_tree.load_file_system(os.path.dirname(self.current_file_path))
                    self.file_content_viewer.clear()
                    self.current_file_path = None
                    self.delete_button.setEnabled(False)
                    self.edit_button.setEnabled(False)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not delete file: {str(e)}")

    def edit_file(self):
        if self.current_file_path:
            try:
                with open(self.current_file_path, 'r') as file:
                    content = file.read()
                dialog = FileEditDialog(content, self.current_file_path, self)
                if dialog.exec_() == QDialog.Accepted:
                    new_content = dialog.get_content()
                    with open(self.current_file_path, 'w') as file:
                        file.write(new_content)
                    self.file_content_viewer.set_content(new_content, self.current_file_path)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not edit file: {str(e)}")

    def load_system_info(self):
        info = {
            'cpu': psutil.cpu_percent(),
            'memory': psutil.virtual_memory().percent,
            'disk': psutil.disk_usage('/').percent
        }
        self.update_system_info(info)

    def setup_charts(self):
        self.cpu_canvas, self.cpu_ax = self.create_chart("CPU Usage")
        self.memory_canvas, self.memory_ax = self.create_chart("Memory Usage")
        self.disk_canvas, self.disk_ax = self.create_chart("Disk Usage")
        self.network_canvas, self.network_ax = self.create_chart("Network Usage (MB)")
        self.cpu_freq_canvas, self.cpu_freq_ax = self.create_chart("CPU Frequency (MHz)")
        self.battery_canvas, self.battery_ax = self.create_chart("Battery (%)")
        self.processes_canvas, self.processes_ax = self.create_chart("Processes")
        self.disk_io_canvas, self.disk_io_ax = self.create_chart("Disk I/O (MB)")
        self.cpu_temp_canvas, self.cpu_temp_ax = self.create_chart("CPU Temperature (°C)")

        self.charts_layout.addWidget(self.cpu_canvas, 0, 0)
        self.charts_layout.addWidget(self.memory_canvas, 0, 1)
        self.charts_layout.addWidget(self.disk_canvas, 1, 0)
        self.charts_layout.addWidget(self.network_canvas, 1, 1)
        self.charts_layout.addWidget(self.cpu_freq_canvas, 2, 0)
        self.charts_layout.addWidget(self.battery_canvas, 2, 1)
        self.charts_layout.addWidget(self.processes_canvas, 3, 0)
        self.charts_layout.addWidget(self.disk_io_canvas, 3, 1)
        self.charts_layout.addWidget(self.cpu_temp_canvas, 4, 0)

    def update_system_info(self, info):
        self.update_system_table(info)
        self.update_cpu_table(info)
        self.update_memory_table(info)
        self.update_disk_table(info)
        self.update_network_table(info)
        self.update_charts(info)

    def update_system_table(self, info):
        self.system_table.setRowCount(0)
        self.add_table_row(self.system_table, "OS", platform.system())
        self.add_table_row(self.system_table, "OS Version", platform.version())
        self.add_table_row(self.system_table, "Architecture", platform.machine())
        self.add_table_row(self.system_table, "Hostname", platform.node())
        self.add_table_row(self.system_table, "Uptime", self.format_uptime(psutil.boot_time()))

    def update_cpu_table(self, info):
        self.cpu_table.setRowCount(0)
        self.add_table_row(self.cpu_table, "Physical cores", psutil.cpu_count(logical=False))
        self.add_table_row(self.cpu_table, "Total cores", psutil.cpu_count(logical=True))
        self.add_table_row(self.cpu_table, "Max Frequency", f"{psutil.cpu_freq().max:.2f}Mhz")
        self.add_table_row(self.cpu_table, "Current Frequency", f"{psutil.cpu_freq().current:.2f}Mhz")
        self.add_table_row(self.cpu_table, "CPU Usage", f"{info['cpu']}%")

    def update_memory_table(self, info):
        self.memory_table.setRowCount(0)
        mem = psutil.virtual_memory()
        self.add_table_row(self.memory_table, "Total", self.format_bytes(mem.total))
        self.add_table_row(self.memory_table, "Available", self.format_bytes(mem.available))
        self.add_table_row(self.memory_table, "Used", self.format_bytes(mem.used))
        self.add_table_row(self.memory_table, "Percentage", f"{mem.percent}%")

    def update_disk_table(self, info):
        self.disk_table.setRowCount(0)
        disk = psutil.disk_usage('/')
        total = disk.total
        used = disk.used
        free = disk.free
        self.add_table_row(self.disk_table, "Total", self.format_bytes(total))
        self.add_table_row(self.disk_table, "Used", self.format_bytes(used))
        self.add_table_row(self.disk_table, "Free", self.format_bytes(free))
        self.add_table_row(self.disk_table, "Percentage Used", f"{(used / total) * 100:.2f}%")

    def update_network_table(self, info):
        self.network_table.setRowCount(0)
        net_io = psutil.net_io_counters()
        self.add_table_row(self.network_table, "Bytes Sent", self.format_bytes(net_io.bytes_sent))
        self.add_table_row(self.network_table, "Bytes Received", self.format_bytes(net_io.bytes_recv))
        self.add_table_row(self.network_table, "Packets Sent", net_io.packets_sent)
        self.add_table_row(self.network_table, "Packets Received", net_io.packets_recv)

    def add_table_row(self, table, name, value):
        row_position = table.rowCount()
        table.insertRow(row_position)
        table.setItem(row_position, 0, QTableWidgetItem(str(name)))
        table.setItem(row_position, 1, QTableWidgetItem(str(value)))

    def update_charts(self, info):
        self.update_pie_chart(self.cpu_ax, info['cpu'], "CPU Usage")
        self.update_pie_chart(self.memory_ax, info['memory'], "Memory Usage")
        self.update_pie_chart(self.disk_ax, info['disk'], "Disk Usage")
        
        net_io = psutil.net_io_counters()
        self.update_bar_chart(self.network_ax, [net_io.bytes_sent / 1e6, net_io.bytes_recv / 1e6], 
                              "Network Usage (MB)", ['Sent', 'Received'])
        
        self.update_bar_chart(self.cpu_freq_ax, [psutil.cpu_freq().current], "CPU Frequency (MHz)", ['Frequency'])
        
        if hasattr(psutil, 'sensors_battery'):
            battery = psutil.sensors_battery()
            if battery:
                self.update_bar_chart(self.battery_ax, [battery.percent], "Battery (%)", ['Level'])
            else:
                self.update_bar_chart(self.battery_ax, [0], "Battery (N/A)", ['Level'])
        else:
            self.update_bar_chart(self.battery_ax, [0], "Battery (N/A)", ['Level'])

        self.update_bar_chart(self.processes_ax, [len(psutil.pids())], "Processes", ['Count'])
        
        disk_io = psutil.disk_io_counters()
        self.update_bar_chart(self.disk_io_ax, [disk_io.read_bytes / 1e6, disk_io.write_bytes / 1e6], 
                              "Disk I/O (MB)", ['Read', 'Write'])

        if hasattr(psutil, 'sensors_temperatures'):
            temps = psutil.sensors_temperatures()
            if 'coretemp' in temps and temps['coretemp']:
                self.update_bar_chart(self.cpu_temp_ax, [temps['coretemp'][0].current], 
                                      "CPU Temperature (°C)", ['Temp'])
            else:
                self.update_bar_chart(self.cpu_temp_ax, [0], "CPU Temperature (N/A)", ['Temp'])
        else:
            self.update_bar_chart(self.cpu_temp_ax, [0], "CPU Temperature (N/A)", ['Temp'])

    def update_pie_chart(self, ax, percent, title):
        ax.clear()
        colors = ['#007ACC', '#FFA500']
        wedges, texts, autotexts = ax.pie([percent, 100 - percent], 
                                          labels=['Used', 'Free'], 
                                          autopct='%1.1f%%',
                                          colors=colors,
                                          startangle=90)
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.figure.tight_layout()
        ax.figure.canvas.draw()

    def update_bar_chart(self, ax, values, title, labels):
        ax.clear()
        ax.bar(labels, values, color=['#007ACC', '#FFA500'])
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_ylabel('Value')
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels)
        ax.figure.tight_layout()
        ax.figure.canvas.draw()

    @staticmethod
    def format_bytes(bytes):
        for unit in ['', 'K', 'M', 'G', 'T', 'P']:
            if bytes < 1024:
                return f"{bytes:.2f}{unit}B"
            bytes /= 1024
        return f"{bytes:.2f}PB"

    @staticmethod
    def format_uptime(boot_time):
        uptime = datetime.now().timestamp() - boot_time
        days, remainder = divmod(int(uptime), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

    def kill_selected_process(self):
        selected_items = self.application_table.selectedItems()
        if selected_items:
            pid = int(self.application_table.item(selected_items[0].row(), 1).text())
            try:
                process = psutil.Process(pid)
                process.terminate()
                QMessageBox.information(self, "Application Terminated", f"Application with PID {pid} has been terminated.")
                self.application_table.load_applications()
            except psutil.NoSuchProcess:
                QMessageBox.warning(self, "Error", f"Application with PID {pid} not found.")
            except psutil.AccessDenied:
                QMessageBox.warning(self, "Error", f"Access denied. Unable to terminate application with PID {pid}.")
