import os
import json
import time
import base64
import pty
import select
import subprocess
import termios
import tty
import re
import threading
import socket
import psutil
import yaml
from datetime import datetime, timezone
import csv
from functools import lru_cache 
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QProgressDialog, 
    QComboBox, QTableView, QTextEdit, QPushButton, QSplitter, QLabel, QGridLayout,
    QLineEdit, QStyleFactory, QStatusBar, QTabWidget, QHeaderView, QCheckBox, QDialog, QInputDialog, 
    QGroupBox, QScrollArea, QMessageBox, QDialogButtonBox, QFormLayout, QSpinBox, QTableWidget, 
    QTableWidgetItem, QSizePolicy, QRadioButton, QButtonGroup, QAbstractItemView, QFrame
)
from PyQt5.QtGui import (
    QStandardItemModel, QFont, QColor, QTextCharFormat, QStandardItem, QTextCursor, QPalette, 
    QTextDocument, QTextBlockFormat, QKeyEvent, QTextTableFormat, QTextFrameFormat, QTextLength
)
from PyQt5.QtCore import Qt, QSortFilterProxyModel, QTimer, QRegExp, QThread, pyqtSignal, QMetaObject, QUrl, QProcess, pyqtSlot, Q_ARG, QMetaType
from kubernetes import client, config
from kubernetes.stream import stream
from resource_updaters import (
    update_pods, update_pvcs, update_statefulsets, update_deployments, update_pvs, 
    update_secrets, update_configmaps, update_jobs, update_cronjobs, update_nodes, 
    LogStreamerThread, parse_k8s_cpu, parse_k8s_memory
)
from utils import setup_info_search
import numpy as np
import sip
from ssh_dialog import SSHDialog
from pod_metrics_worker import PodMetricsWorker
from helper_view_tab.create_resource_dialog import CreateResourceDialog
from helper_view_tab.edit_resource_dialog import EditResourceDialog
from helper_view_tab.ssh_connection import SSHAuthDialog, SSHConnectionThread
from helper_view_tab.terminal_widget import TerminalWidget
from helper_view_tab.utils import clean_resource_dict, decode_base64_in_yaml, save_port_forwarding, load_port_forwarding


def kill_port_forward_processes(pattern):
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'kubectl' in proc.info['name'] and 'port-forward' in proc.info['cmdline'] and any(pattern in arg for arg in proc.info['cmdline']):
                proc.terminate()
                proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass

class ViewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.selected_namespaces = []
        self.port_forwarding_file = os.path.join(os.path.expanduser("~"), ".kube_debugger_port_forwarding.json")
        self.port_forwarding_dict = load_port_forwarding(self.port_forwarding_file)
        self.edit_dialog_open = False
        self.init_ui()
        self.check_active_port_forwardings()
        self.separate_terminal_window = None
        self.load_ssh_key_from_kubeconfig()
        self.ssh_output_buffer = ""
        self.ssh_timer = QTimer()
        self.ssh_timer.timeout.connect(self.process_ssh_output)
        self.ssh_timer.start(50)
        self.selection_timer = QTimer()
        self.selection_timer.setSingleShot(True)
        self.selection_timer.timeout.connect(self.delayed_update_resource_info)
        
        # Load namespaces only once
        self.load_namespaces()
        self.update_resources()
        self.refresh_events()
        
        # Connect signals after initialization
        self.namespace_combo1.currentIndexChanged.connect(self.on_namespace_changed)
        self.namespace_combo2.currentIndexChanged.connect(self.on_namespace_changed)
        
    
    def on_namespace_changed(self):
        self.update_resources()

    def create_labeled_combo(self, label_text, combo_items=None):
        layout = QHBoxLayout()
        layout.setSpacing(50)
        layout.setContentsMargins(2, 2, 2, 2)
        
        label = QLabel(label_text)
        label.setFixedWidth(200)  # Adjust this value as needed
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        combo = QComboBox()
        if combo_items:
            combo.addItems(combo_items)
            combo.setFixedWidth(200)  # Adjust this value as needed
        
        layout.addWidget(label)
        layout.addWidget(combo)
        layout.addStretch(1)
        
        return layout, combo

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        self.main_layout = main_layout
        self.main_layout.setSpacing(2)
        self.main_layout.setContentsMargins(2, 2, 2, 2)

        # Create splitter for left and right panels
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)

        # Left panel
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)

        # First line: Namespace and Resource Type
        first_line_layout = QHBoxLayout()
        first_line_layout.addWidget(QLabel("Namespace 1:"))
        self.namespace_combo1 = QComboBox()
        first_line_layout.addWidget(self.namespace_combo1)
        first_line_layout.addWidget(QLabel("Namespace 2:"))
        self.namespace_combo2 = QComboBox()

        first_line_layout.addWidget(self.namespace_combo2)

        # Add "More Namespaces" dropdown
        self.more_namespaces_button = QPushButton("More namespaces")
        self.more_namespaces_button.clicked.connect(self.show_namespace_dialog)
        first_line_layout.addWidget(self.more_namespaces_button)
        first_line_layout.addStretch(1)
        left_layout.addLayout(first_line_layout)
        # Resource type tabs
        self.resource_tabs = QTabWidget()
        self.resource_tabs.setDocumentMode(True)
        self.resource_tabs.setTabPosition(QTabWidget.North)
        self.resource_tabs.addTab(QWidget(), "Pods")
        self.resource_tabs.addTab(QWidget(), "Deployments")
        self.resource_tabs.addTab(QWidget(), "StatefulSets")
        self.resource_tabs.addTab(QWidget(), "Jobs")
        self.resource_tabs.addTab(QWidget(), "CronJobs")
        self.resource_tabs.addTab(QWidget(), "PVC")
        self.resource_tabs.addTab(QWidget(), "PV")
        self.resource_tabs.addTab(QWidget(), "Secrets")
        self.resource_tabs.addTab(QWidget(), "ConfigMaps")
        self.resource_tabs.addTab(QWidget(), "Services")
        self.resource_tabs.addTab(QWidget(), "Nodes")
        left_layout.addWidget(self.resource_tabs)

        # Adjust size policy of the tab widget
        self.resource_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Second line: Search, Refresh, and Download
        second_line_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter resources...")
        second_line_layout.addWidget(self.search_input)
        self.refresh_button = QPushButton("Refresh")
        second_line_layout.addWidget(self.refresh_button)

        self.download_resources_button = QPushButton("Download")
        second_line_layout.addWidget(self.download_resources_button)
        left_layout.addLayout(second_line_layout)

        # Resource Table
        resource_label = QLabel("Resource Table")
        left_layout.addWidget(resource_label)

        self.resource_table = QTableView()
        self.table_model = QStandardItemModel()
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.resource_table.setModel(self.proxy_model)
        self.resource_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.resource_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.resource_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.resource_table.horizontalHeader().setStretchLastSection(True)
        self.resource_table.verticalHeader().setVisible(False)
        
        # Add these lines
        self.resource_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.resource_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.resource_table.setShowGrid(False)
        left_layout.addWidget(self.resource_table)

        # Events and Terminal section
        events_terminal_widget = QWidget()
        self.events_terminal_layout = QVBoxLayout(events_terminal_widget)

        # Create a tab widget for events and terminal
        self.events_terminal_tabs = QTabWidget()
        self.events_terminal_layout.addWidget(self.events_terminal_tabs)

        left_layout.addWidget(events_terminal_widget)


        # Events tab
        events_tab = QWidget()
        events_tab_layout = QVBoxLayout(events_tab)

        # Events controls
        events_controls_layout = QHBoxLayout()
        events_label = QLabel("Latest Events")
        events_controls_layout.addWidget(events_label)

        self.events_filter = QLineEdit()
        self.events_filter.setPlaceholderText("Filter events...")
        events_controls_layout.addWidget(self.events_filter)

        refresh_events_button = QPushButton("Refresh")
        events_controls_layout.addWidget(refresh_events_button)
        refresh_events_button.clicked.connect(self.refresh_events)

        download_events_button = QPushButton("Download")
        events_controls_layout.addWidget(download_events_button)
        download_events_button.clicked.connect(self.download_events_table) 

        events_tab_layout.addLayout(events_controls_layout)

        self.events_table = QTableWidget()
        self.events_table.setColumnCount(5)
        self.events_table.setHorizontalHeaderLabels(["Namespace", "Event Time", "Reason", "Object", "Message"])
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setSortingEnabled(True)
        events_tab_layout.addWidget(self.events_table)
        self.events_terminal_tabs.addTab(events_tab, "Events")

        # Terminal tab
        self.terminal_tab = QWidget()
        terminal_layout = QVBoxLayout(self.terminal_tab)

        self.terminal_widget = TerminalWidget(self)

        terminal_layout.addWidget(self.terminal_widget)
        expand_button = QPushButton("Expand Terminal")
        expand_button.clicked.connect(self.expand_terminal)
        terminal_layout.addWidget(expand_button)

        self.events_terminal_tabs.addTab(self.terminal_tab, "Terminal")

        self.splitter.addWidget(left_widget)

        # Right panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(10)

        # Resource Info Header
        self.current_resource_label = QLabel()
        right_layout.addWidget(self.current_resource_label)

        # Container selection
        container_layout = QHBoxLayout()
        self.container_label = QLabel("Container:")
        self.container_combo = QComboBox()
        container_layout.addWidget(self.container_label)
        container_layout.addWidget(self.container_combo)
        right_layout.addLayout(container_layout)

        # Action buttons and checkboxes layout
        action_info_layout = QHBoxLayout()
        action_info_layout.setSpacing(10)  # Add spacing between widgets

        # Create a widget to hold all buttons
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setSpacing(5)  # Spacing between buttons
        button_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins

        info_download_button = QPushButton("Download")
        info_download_button.clicked.connect(self.download_info)
        info_download_button.setFixedSize(120, 30)  # Set fixed size
        button_layout.addWidget(info_download_button)

        self.edit_yaml_button = QPushButton("Edit")
        self.edit_yaml_button.setFixedSize(120, 30)  # Set fixed size
        button_layout.addWidget(self.edit_yaml_button)

        # Create action buttons
        self.action_buttons = {}
        button_data = [
            ('delete', "Delete", self.delete_current_resource),
            ('stream_logs', "Stream", self.stream_logs),
            ('port_forward', "Port Forward", self.port_forward_current_service),
            ('ssh', "SSH", lambda: self.ssh_to_node(self.current_resource_name)),
            ('exec', "Exec", self.toggle_exec_panel)
        ]

        for key, text, action in button_data:
            button = QPushButton(text)
            button.setFixedSize(120, 30)  # Set fixed size
            button.clicked.connect(action)
            if key == 'exec':
                button.setCheckable(True)
            self.action_buttons[key] = button
            button_layout.addWidget(button)
            button.hide()

        action_info_layout.addWidget(button_widget)

        # Add stretch to push checkboxes to the right
        action_info_layout.addStretch(1)

        self.decode_checkbox = QCheckBox("Decode Base64")
        self.decode_checkbox.hide()
        action_info_layout.addWidget(self.decode_checkbox)

        self.show_full_yaml_checkbox = QCheckBox("Show Full YAML")
        action_info_layout.addWidget(self.show_full_yaml_checkbox)
        self.show_full_yaml_checkbox.stateChanged.connect(self.update_info_display)

        right_layout.addLayout(action_info_layout)

        # New section with QTabWidget
        self.info_tabs = QTabWidget()
        self.describe_tab = QWidget()
        self.logs_tab = QWidget()
        self.events_tab = QWidget()
        self.volumes_tab = QWidget()

        # Create layouts for each tab
        describe_layout = QVBoxLayout(self.describe_tab)
        logs_layout = QVBoxLayout(self.logs_tab)
        events_layout = QVBoxLayout(self.events_tab)
        volumes_layout = QVBoxLayout(self.volumes_tab)

        # Add separate QTextEdit to each tab
        self.describe_text = QTextEdit()
        self.describe_text.setReadOnly(True)

        describe_layout.addWidget(self.describe_text)

        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)

        logs_layout.addWidget(self.logs_text)

        self.events_text = QTextEdit()
        self.events_text.setReadOnly(True)

        events_layout.addWidget(self.events_text)

        self.volumes_text = QTextEdit()
        self.volumes_text.setReadOnly(True)

        volumes_layout.addWidget(self.volumes_text)

        self.info_tabs.addTab(self.describe_tab, "Describe")
        self.info_tabs.addTab(self.logs_tab, "Logs")
        self.info_tabs.addTab(self.events_tab, "Events")
        self.info_tabs.addTab(self.volumes_tab, "Volumes")
        self.update_info_type_combo()

        # Add info_tabs to the layout
        right_layout.addWidget(self.info_tabs)

        # Exec section
        self.exec_label = QLabel("Execute Command")

        right_layout.addWidget(self.exec_label)

        exec_layout = QHBoxLayout()
        self.exec_input = QLineEdit()
        self.exec_input.setPlaceholderText("Enter command")
        exec_layout.addWidget(self.exec_input)

        self.exec_button = QPushButton("Execute")

        exec_layout.addWidget(self.exec_button)

        self.exec_download_button = QPushButton("Download")

        exec_layout.addWidget(self.exec_download_button)

        right_layout.addLayout(exec_layout)

        self.exec_output = QTextEdit()
        self.exec_output.setReadOnly(True)

        right_layout.addWidget(self.exec_output)

        self.splitter.addWidget(right_widget)

        # Set initial splitter sizes
        self.splitter.setSizes([int(self.width() * 0.7), int(self.width() * 0.3)])

        # Connect signals
        self.refresh_button.clicked.connect(self.manual_refresh)
        self.resource_tabs.currentChanged.connect(self.on_resource_type_changed)
        self.search_input.textChanged.connect(self.filter_resources)
        self.resource_table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.container_combo.currentIndexChanged.connect(self.update_info_display)
        self.info_tabs.currentChanged.connect(self.update_info_display)
        self.decode_checkbox.stateChanged.connect(self.update_info_display)
        self.edit_yaml_button.clicked.connect(self.edit_resource_yaml)
        self.events_filter.textChanged.connect(self.filter_events)
        self.download_resources_button.clicked.connect(self.download_resource_table)
        self.exec_button.clicked.connect(self.execute_command)
        self.exec_download_button.clicked.connect(self.download_exec_output)

        # Hide container selection by default
        self.container_label.hide()
        self.container_combo.hide()

        # Hide exec panel by default
        self.exec_label.hide()
        self.exec_input.hide()
        self.exec_button.hide()
        self.exec_download_button.hide()
        self.exec_output.hide()

        # Set up info search
        setup_info_search(self)

        # Load namespaces and initial resources
        self.load_namespaces()

        # Start the terminal
        self.start_terminal()
        self.terminal_widget.command_entered.connect(self.send_command)

    def on_selection_changed(self, selected, deselected):
        if selected.indexes():
            # Cancel any pending update
            self.selection_timer.stop()
            # Schedule a new update
            self.selection_timer.start(50)  # 50ms delay


    def show_namespace_dialog(self):
        namespaces = [ns.metadata.name for ns in self.v1.list_namespace().items]
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Namespaces")
        dialog.setMinimumWidth(300)  # Set a minimum width for the dialog
        
        main_layout = QVBoxLayout(dialog)
        
        # Create a scroll area for the namespaces
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        namespace_checkboxes = []
        
        all_selected_namespaces = set(self.selected_namespaces)
        all_selected_namespaces.add(self.namespace_combo1.currentText())
        all_selected_namespaces.add(self.namespace_combo2.currentText())
        
        for ns in namespaces:
            checkbox = QCheckBox(ns)
            if ns in all_selected_namespaces:
                checkbox.setChecked(True)
            namespace_checkboxes.append(checkbox)
            scroll_layout.addWidget(checkbox)
        
        scroll_area.setWidget(scroll_content)
        
        # Set a maximum height for the scroll area
        scroll_area.setMaximumHeight(300)  # Adjust this value as needed
        
        main_layout.addWidget(scroll_area)
        
        # Add a separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(lambda: self.set_selected_namespaces(namespace_checkboxes, dialog))
        button_box.rejected.connect(dialog.reject)
        main_layout.addWidget(button_box)
        
        dialog.exec_()


    def set_selected_namespaces(self, namespace_checkboxes, dialog):
        self.selected_namespaces = [checkbox.text() for checkbox in namespace_checkboxes if checkbox.isChecked()]
        print(f"Selected namespaces: {self.selected_namespaces}")  # Log message
        dialog.accept()
        self.update_resources()



    def get_selected_namespaces(self):
        return [self.namespace_combo1.currentText(), self.namespace_combo2.currentText()] + self.selected_namespaces


    def toggle_exec_panel(self):
        if self.action_buttons['exec'].isChecked():
            self.show_exec_elements()
        else:
            self.hide_exec_elements()


    def display_resource_info(self, resource):
        resource_dict = resource.to_dict()
        self.clean_resource_dict(resource_dict)
        
        if self.show_full_yaml_checkbox.isChecked():
            formatted_output = self.format_resource_info(resource_dict)
        else:
            formatted_output = self.format_resource_info({'spec': resource_dict.get('spec', {})})
        
        self.describe_text.setPlainText(formatted_output)

    def disable_cluster_dependent_ui(self):
        self.namespace_combo1.setEnabled(False)
        self.namespace_combo2.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.download_resources_button.setEnabled(False)
        self.resource_table.setEnabled(False)
    
    def enable_cluster_dependent_ui(self):
        self.namespace_combo1.setEnabled(True)
        self.namespace_combo2.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.download_resources_button.setEnabled(True)
        self.resource_table.setEnabled(True)

    def update_info_type_combo(self):
        resource_type = self.get_current_resource_type()
        
        if resource_type == "Pods":
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.describe_tab), True)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.logs_tab), True)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.events_tab), True)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.volumes_tab), True)
        else:
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.describe_tab), True)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.logs_tab), False)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.events_tab), False)
            self.info_tabs.setTabEnabled(self.info_tabs.indexOf(self.volumes_tab), False)
        
        # Select the first available tab if the current one is disabled
        if not self.info_tabs.isTabEnabled(self.info_tabs.currentIndex()):
            self.info_tabs.setCurrentIndex(self.info_tabs.indexOf(self.describe_tab))

    def on_resource_type_changed(self):
        try:
            # Disconnect previous connections if they exist
            try:
                self.resource_table.selectionModel().selectionChanged.disconnect()
            except TypeError:
                pass  # No connections to disconnect

            resource_type = self.get_current_resource_type()
            
            # Show/hide action buttons based on resource type
            self.action_buttons['delete'].setVisible(resource_type != "Nodes")
            self.action_buttons['stream_logs'].setVisible(resource_type == "Pods")
            self.action_buttons['port_forward'].setVisible(resource_type == "Services")
            self.action_buttons['ssh'].setVisible(resource_type == "Nodes")

            self.update_resources()

            
            # Reconnect the signal
            self.resource_table.selectionModel().selectionChanged.connect(self.update_resource_info)
        except Exception as e:
            print(f"Error in on_resource_type_changed: {str(e)}")
            # You might want to show an error message to the user here

        self.update_info_type_combo()  # Ensure tabs are updated based on resource type
        self.update_info_display()

    def update_action_buttons(self):
        resource_type = self.get_current_resource_type()
        for button in self.action_buttons.values():
            button.hide()

        if resource_type != "Nodes":
            self.action_buttons['delete'].show()
        if resource_type == "Pods":
            self.action_buttons['stream_logs'].show()
            self.action_buttons['exec'].show()
        if resource_type == "Services":
            self.action_buttons['port_forward'].show()
        if resource_type == "Nodes":
            self.action_buttons['ssh'].show()


    
    def download_resource_table(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Resource Table", "", "CSV Files (*.csv)")
        if file_name:
            with open(file_name, 'w', newline='') as file:
                writer = csv.writer(file)
                # Write headers
                headers = [self.table_model.headerData(i, Qt.Horizontal) for i in range(self.table_model.columnCount())]
                writer.writerow(headers)
                # Write data
                for row in range(self.table_model.rowCount()):
                    row_data = [self.table_model.data(self.table_model.index(row, col)) for col in range(self.table_model.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Download Complete", "Resource table has been saved successfully.")

    def download_events_table(self):
        self.download_events_button.setEnabled(False)
        self.download_events_button.setText("Downloading...")
        QApplication.processEvents()  # Update the UI immediately

        progress_dialog = QProgressDialog("Downloading events table...", "Cancel", 0, 0, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setRange(0, 0)  # Indeterminate progress
        progress_dialog.show()

        try:
            file_name, _ = QFileDialog.getSaveFileName(self, "Save Events Table", "", "CSV Files (*.csv)")
            if file_name:
                with open(file_name, 'w', newline='') as file:
                    writer = csv.writer(file)
                    # Write headers
                    headers = [self.events_table.horizontalHeaderItem(i).text() for i in range(self.events_table.columnCount())]
                    writer.writerow(headers)
                    # Write data
                    for row in range(self.events_table.rowCount()):
                        row_data = [self.events_table.item(row, col).text() if self.events_table.item(row, col) else '' for col in range(self.events_table.columnCount())]
                        writer.writerow(row_data)
                QMessageBox.information(self, "Download Complete", "Events table has been saved successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to download events table: {str(e)}")
        finally:
            self.download_events_button.setEnabled(True)
            self.download_events_button.setText("Download")
            progress_dialog.close()


    def edit_resource_yaml(self):
        if not self.current_resource_name:
            QMessageBox.warning(self, "No Resource Selected", "Please select a resource to edit.")
            return

        resource_type = self.get_current_resource_type()
        dialog = EditResourceDialog(resource_type, self.current_resource_name, self.current_namespace, self, self)
        if dialog.exec_() == QDialog.Accepted:
            edited_yaml = dialog.get_edited_yaml()
            self.apply_edited_resource(edited_yaml, resource_type)

    def apply_edited_resource(self, edited_yaml, resource_type):
        try:
            edited_spec = yaml.safe_load(edited_yaml)['spec']
            name = self.current_resource_name
            namespace = self.current_namespace

            # Show loading indicator
            progress_dialog = QProgressDialog("Applying changes...", "Cancel", 0, 0, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.show()

            try:
                if resource_type == "Pods":
                    current_pod = self.v1.read_namespaced_pod(name, namespace)
                    if 'containers' in edited_spec:
                        for i, container in enumerate(edited_spec['containers']):
                            if i < len(current_pod.spec.containers):
                                if 'image' in container:
                                    current_pod.spec.containers[i].image = container['image']
                                if 'resources' in container:
                                    current_pod.spec.containers[i].resources = client.V1ResourceRequirements(**container['resources'])
                    self.v1.replace_namespaced_pod(name, namespace, current_pod)

                elif resource_type == "Deployments":
                    current_deployment = self.apps_v1.read_namespaced_deployment(name, namespace)
                    if 'replicas' in edited_spec:
                        current_deployment.spec.replicas = edited_spec['replicas']
                    if 'template' in edited_spec and 'spec' in edited_spec['template']:
                        template_spec = edited_spec['template']['spec']
                        if 'containers' in template_spec:
                            for i, container in enumerate(template_spec['containers']):
                                if i < len(current_deployment.spec.template.spec.containers):
                                    if 'image' in container:
                                        current_deployment.spec.template.spec.containers[i].image = container['image']
                                    if 'resources' in container:
                                        current_deployment.spec.template.spec.containers[i].resources = client.V1ResourceRequirements(**container['resources'])
                    self.apps_v1.replace_namespaced_deployment(name, namespace, current_deployment)

                elif resource_type == "StatefulSets":
                    current_statefulset = self.apps_v1.read_namespaced_stateful_set(name, namespace)
                    if 'replicas' in edited_spec:
                        current_statefulset.spec.replicas = edited_spec['replicas']
                    if 'template' in edited_spec and 'spec' in edited_spec['template']:
                        template_spec = edited_spec['template']['spec']
                        if 'containers' in template_spec:
                            for i, container in enumerate(template_spec['containers']):
                                if i < len(current_statefulset.spec.template.spec.containers):
                                    if 'image' in container:
                                        current_statefulset.spec.template.spec.containers[i].image = container['image']
                                    if 'resources' in container:
                                        current_statefulset.spec.template.spec.containers[i].resources = client.V1ResourceRequirements(**container['resources'])
                    self.apps_v1.replace_namespaced_stateful_set(name, namespace, current_statefulset)

                elif resource_type == "Jobs":
                    current_job = self.batch_v1.read_namespaced_job(name, namespace)
                    if 'template' in edited_spec and 'spec' in edited_spec['template']:
                        template_spec = edited_spec['template']['spec']
                        if 'containers' in template_spec:
                            for i, container in enumerate(template_spec['containers']):
                                if i < len(current_job.spec.template.spec.containers):
                                    if 'image' in container:
                                        current_job.spec.template.spec.containers[i].image = container['image']
                                    if 'resources' in container:
                                        current_job.spec.template.spec.containers[i].resources = client.V1ResourceRequirements(**container['resources'])
                    self.batch_v1.replace_namespaced_job(name, namespace, current_job)

                elif resource_type == "CronJobs":
                    current_cronjob = self.batch_v1.read_namespaced_cron_job(name, namespace)
                    if 'schedule' in edited_spec:
                        current_cronjob.spec.schedule = edited_spec['schedule']
                    if 'jobTemplate' in edited_spec and 'spec' in edited_spec['jobTemplate']:
                        job_template_spec = edited_spec['jobTemplate']['spec']
                        if 'template' in job_template_spec and 'spec' in job_template_spec['template']:
                            template_spec = job_template_spec['template']['spec']
                            if 'containers' in template_spec:
                                for i, container in enumerate(template_spec['containers']):
                                    if i < len(current_cronjob.spec.job_template.spec.template.spec.containers):
                                        if 'image' in container:
                                            current_cronjob.spec.job_template.spec.template.spec.containers[i].image = container['image']
                                        if 'resources' in container:
                                            current_cronjob.spec.job_template.spec.template.spec.containers[i].resources = client.V1ResourceRequirements(**container['resources'])
                    self.batch_v1.replace_namespaced_cron_job(name, namespace, current_cronjob)

                elif resource_type == "PVC":
                    current_pvc = self.v1.read_namespaced_persistent_volume_claim(name, namespace)
                    if 'resources' in edited_spec:
                        current_pvc.spec.resources = client.V1ResourceRequirements(**edited_spec['resources'])
                    self.v1.replace_namespaced_persistent_volume_claim(name, namespace, current_pvc)

                elif resource_type == "PV":
                    current_pv = self.v1.read_persistent_volume(name)
                    if 'capacity' in edited_spec:
                        current_pv.spec.capacity = edited_spec['capacity']
                    self.v1.replace_persistent_volume(name, current_pv)

                elif resource_type == "Secrets":
                    current_secret = self.v1.read_namespaced_secret(name, namespace)
                    if 'data' in edited_spec:
                        current_secret.data = {k: base64.b64encode(v.encode()).decode() for k, v in edited_spec['data'].items()}
                    self.v1.replace_namespaced_secret(name, namespace, current_secret)

                elif resource_type == "ConfigMaps":
                    current_configmap = self.v1.read_namespaced_config_map(name, namespace)
                    if 'data' in edited_spec:
                        current_configmap.data = edited_spec['data']
                    self.v1.replace_namespaced_config_map(name, namespace, current_configmap)

                elif resource_type == "Services":
                    current_service = self.v1.read_namespaced_service(name, namespace)
                    if 'ports' in edited_spec:
                        current_service.spec.ports = [client.V1ServicePort(**port) for port in edited_spec['ports']]
                    if 'selector' in edited_spec:
                        current_service.spec.selector = edited_spec['selector']
                    self.v1.replace_namespaced_service(name, namespace, current_service)

                elif resource_type == "Nodes":
                    current_node = self.v1.read_node(name)
                    if 'metadata' in edited_spec and 'labels' in edited_spec['metadata']:
                        current_node.metadata.labels = edited_spec['metadata']['labels']
                    self.v1.replace_node(name, current_node)

                else:
                    raise ValueError(f"Editing not supported for resource type: {resource_type}")

                QMessageBox.information(self, "Success", f"{resource_type} '{name}' updated successfully")
                self.update_info_display()  # Refresh the resource info display
            except client.exceptions.ApiException as e:
                error_message = json.loads(e.body)['message'] if e.body else str(e)
                QMessageBox.critical(self, "Error", f"Failed to apply changes: {error_message}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to apply changes: {str(e)}")
            finally:
                progress_dialog.close()

        except yaml.YAMLError as e:
            QMessageBox.critical(self, "Error", f"Failed to parse edited YAML: {str(e)}")
        except KeyError as e:
            QMessageBox.critical(self, "Error", f"Invalid structure in edited YAML: {str(e)}")


    def create_new_resource(self):
        namespaces = [ns.metadata.name for ns in self.v1.list_namespace().items]
        dialog = CreateResourceDialog(namespaces, self)
        if dialog.exec_() == QDialog.Accepted:
            namespace = dialog.get_namespace()
            resource_yaml = dialog.get_resource_yaml()
            
            # Show loading indicator
            progress_dialog = QProgressDialog("Creating resource...", "Cancel", 0, 0, self)
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.show()

            try:
                self.apply_new_resource(namespace, resource_yaml)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create resource: {str(e)}")
            finally:
                progress_dialog.close()

    @lru_cache(maxsize=100)
    def get_resource_info(self, resource_type, resource_name, namespace):
        try:
            if resource_type == "Pods":
                return self.v1.read_namespaced_pod(resource_name, namespace)
            elif resource_type == "Deployments":
                return self.apps_v1.read_namespaced_deployment(resource_name, namespace)
            elif resource_type == "StatefulSets":
                return self.apps_v1.read_namespaced_stateful_set(resource_name, namespace)
            elif resource_type == "Jobs":
                return self.batch_v1.read_namespaced_job(resource_name, namespace)
            elif resource_type == "CronJobs":
                return self.batch_v1.read_namespaced_cron_job(resource_name, namespace)
            elif resource_type == "PVC":
                return self.v1.read_namespaced_persistent_volume_claim(resource_name, namespace)
            elif resource_type == "Secrets":
                return self.v1.read_namespaced_secret(resource_name, namespace)
            elif resource_type == "ConfigMaps":
                return self.v1.read_namespaced_config_map(resource_name, namespace)
            elif resource_type == "Services":
                return self.v1.read_namespaced_service(resource_name, namespace)
            elif resource_type == "PV":
                return self.v1.read_persistent_volume(resource_name)
            elif resource_type == "Nodes":
                return self.v1.read_node(resource_name)
            else:
                raise ValueError(f"Unsupported resource type: {resource_type}")
        except client.exceptions.ApiException as e:
            print(f"API Exception when fetching {resource_type} {resource_name}: {e}")
            return None

    def update_describe_tab(self):
        resource_type = self.get_current_resource_type()
        resource = self.get_resource_info(resource_type, self.current_resource_name, self.current_namespace)
        self.display_resource_info(resource)
        
    def update_logs_tab(self):
        container = self.container_combo.currentText() if self.container_combo.isVisible() else None
        try:
            logs = self.v1.read_namespaced_pod_log(
                self.current_resource_name, 
                self.current_namespace, 
                container=container
            )
            self.logs_text.setPlainText(logs)
        except client.rest.ApiException as e:
            self.logs_text.setPlainText(f"Error fetching logs: {str(e)}")

    def apply_new_resource(self, namespace, resource_yaml):
        try:
            resource_dict = yaml.safe_load(resource_yaml)
            kind = resource_dict["kind"]
            name = resource_dict["metadata"]["name"]

            confirm_msg = f"Are you sure you want to apply the {kind} '{name}' in namespace '{namespace}'?"
            reply = QMessageBox.question(self, 'Confirm Apply', confirm_msg, 
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
            if reply == QMessageBox.No:
                return

            api_client = client.ApiClient()
            utils = client.ApiClient().sanitize_for_serialization(resource_dict)
            
            if kind == "Pod":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_pod(namespace, utils)
            elif kind == "Deployment":
                api_instance = client.AppsV1Api(api_client)
                api_instance.create_namespaced_deployment(namespace, utils)
            elif kind == "Service":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_service(namespace, utils)
            elif kind == "PersistentVolumeClaim" or kind == "PVC":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_persistent_volume_claim(namespace, utils)
            elif kind == "StatefulSet":
                api_instance = client.AppsV1Api(api_client)
                api_instance.create_namespaced_stateful_set(namespace, utils)
            elif kind == "PersistentVolume" or kind == "PV":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_persistent_volume(utils)
            elif kind == "Secret":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_secret(namespace, utils)
            elif kind == "ConfigMap":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_config_map(namespace, utils)
            elif kind == "Job":
                api_instance = client.BatchV1Api(api_client)
                api_instance.create_namespaced_job(namespace, utils)
            elif kind == "CronJob":
                api_instance = client.BatchV1Api(api_client)
                api_instance.create_namespaced_cron_job(namespace, utils)
            else:
                raise ValueError(f"Unsupported resource type: {kind}")

            QMessageBox.information(self, "Success", f"{kind} applied successfully in namespace {namespace}")
            self.update_resources()
        except Exception as e:
            raise Exception(f"Failed to apply new resource: {str(e)}")

    def check_active_port_forwardings(self):
        self.verify_port_forwarding()
        for key, (local_port, pid) in self.port_forwarding_dict.items():
            namespace, service_name = key.split('/')
            QMetaObject.invokeMethod(self, "update_port_forwarding_status",
                                    Qt.QueuedConnection,
                                    Q_ARG(str, namespace),
                                    Q_ARG(str, service_name),
                                    Q_ARG(bool, True))
            


    def stop_port_forwarding(self, namespace, service_name):
        key = f"{namespace}/{service_name}"
        if key in self.port_forwarding_dict:
            local_port, pid = self.port_forwarding_dict[key]
            
            try:
                process = psutil.Process(pid)
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
            except psutil.NoSuchProcess:
                print(f"Process for {key} not found")
            
            # Kill any remaining kubectl port-forward process for this service
            kill_port_forward_processes(f"kubectl port-forward.*{namespace}/{service_name}")
            
            del self.port_forwarding_dict[key]
            self.save_port_forwarding()
            
            self.update_resources()  # Refresh the table to update the button status
            QMessageBox.information(self, "Port Forwarding", f"Port forwarding stopped for service {service_name}")
        else:
            QMessageBox.warning(self, "Port Forwarding", f"No active port forwarding found for service {service_name}")

    
    @pyqtSlot(str, str, bool)
    def update_port_forwarding_status(self, namespace, service_name, is_active):
        key = f"{namespace}/{service_name}"
        if is_active:
            # Port forwarding started
            if key not in self.port_forwarding_dict:
                print(f"Error: Key {key} not found in port_forwarding_dict")
                return
            port = self.port_forwarding_dict[key]
            QMessageBox.information(self, "Port Forwarding", 
                                    f"Port forwarding active for {service_name}\n"
                                    f"Local address: localhost:{port}")
        else:
            # Port forwarding stopped
            if key in self.port_forwarding_dict:
                del self.port_forwarding_dict[key]
            QMessageBox.information(self, "Port Forwarding", 
                                    f"Port forwarding stopped for {service_name}")
        self.update_resources()

    @pyqtSlot(str)
    def show_error_message(self, message):
        QMessageBox.critical(self, "Error", message)

    def port_forward_service(self, service_name, namespace):
        try:
            service = self.v1.read_namespaced_service(service_name, namespace)
            available_ports = [f"{port.port}:{port.target_port}" for port in service.spec.ports]
            
            port_dialog = QDialog(self)
            port_dialog.setWindowTitle("Choose Port")
            port_layout = QVBoxLayout(port_dialog)
            
            port_combo = QComboBox()
            port_combo.addItems(available_ports)
            port_layout.addWidget(QLabel("Select port to forward:"))
            port_layout.addWidget(port_combo)
            
            local_port_input = QLineEdit()
            local_port_input.setPlaceholderText("Enter local port")
            port_layout.addWidget(QLabel("Local port:"))
            port_layout.addWidget(local_port_input)
            
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(port_dialog.accept)
            button_box.rejected.connect(port_dialog.reject)
            port_layout.addWidget(button_box)
            
            if port_dialog.exec_() == QDialog.Accepted:
                selected_port = port_combo.currentText().split(':')[0]
                local_port = local_port_input.text()
                if not local_port:
                    local_port = selected_port
                
                cmd = f"kubectl port-forward service/{service_name} {local_port}:{selected_port} -n {namespace}"
            
                process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Wait for a short time to allow the port-forwarding to start
                time.sleep(2)

                # Check if the port is actually open and accessible
                def check_port():
                    retry_count = 0
                    while retry_count < 5:  # Try 5 times
                        try:
                            with socket.create_connection(("localhost", local_port), timeout=1):
                                return True
                        except (socket.timeout, ConnectionRefusedError):
                            retry_count += 1
                            time.sleep(1)
                    return False

                # Run the check in a separate thread to avoid blocking the UI
                check_thread = threading.Thread(target=check_port)
                check_thread.start()
                check_thread.join(timeout=10)  # Wait for up to 10 seconds

                if check_thread.is_alive() or not check_port():
                    # If the thread is still running or returned False, the port is not accessible
                    process.terminate()
                    process.wait()
                    QMessageBox.critical(self, "Error", f"Port {local_port} is not accessible. Port forwarding failed.")
                    return

                key = f"{namespace}/{service_name}"
                self.port_forwarding_dict[key] = (local_port, process.pid)
                self.save_port_forwarding()
                
                QMetaObject.invokeMethod(self, "update_port_forwarding_status",
                                        Qt.QueuedConnection,
                                        Q_ARG(str, namespace),
                                        Q_ARG(str, service_name),
                                        Q_ARG(bool, True))
                
                QMessageBox.information(self, "Port Forwarding", 
                                        f"Port forwarding started successfully for service {service_name}\n"
                                        f"Local address: localhost:{local_port}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start port forwarding: {str(e)}")

    def manual_refresh(self):
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")
        QApplication.processEvents()  # This will update the UI immediately

        try:
            self.update_resources()
        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")

    def save_port_forwarding(self):
        with open(self.port_forwarding_file, 'w') as f:
            json.dump(self.port_forwarding_dict, f)

    def load_port_forwarding(self):
        if os.path.exists(self.port_forwarding_file):
            with open(self.port_forwarding_file, 'r') as f:
                return json.load(f)
        return {}
    
    def change_cluster(self, cluster_name):
        self.parent.current_cluster = cluster_name
        self.parent.load_current_cluster()
    
    def update_status(self, message):
        if self.parent and hasattr(self.parent, 'statusBar'):
            self.parent.statusBar().showMessage(message, 5000) 

    # Add these methods to access parent's attributes and methods
    @property
    def v1(self):
        return self.parent.v1

    @property
    def apps_v1(self):
        return self.parent.apps_v1

    @property
    def batch_v1(self):
        return self.parent.batch_v1

    @property
    def custom_api(self):
        return self.parent.custom_api

    def clusters(self):
        return self.parent.clusters

    def filter_resources(self, text):
        self.proxy_model.setFilterKeyColumn(-1)  # Search all columns
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.setFilterRegExp(text)

    def can_exec_into_pod(self, pod_name, namespace):
        try:
            pod = self.v1.read_namespaced_pod(pod_name, namespace)
            # Check if pod is in a running state and has at least one container
            if pod.status.phase == "Running" and pod.spec.containers:
                return True
            return False
        except client.exceptions.ApiException as e:
            print(f"Error checking pod state: {e}")
            return False


    def hide_exec_elements(self):
        if hasattr(self, 'exec_input'):
            self.exec_label.hide()
            self.exec_input.hide()
            self.exec_button.hide()
            self.exec_download_button.hide()
            self.exec_output.hide()


    def show_exec_elements(self):
        if hasattr(self, 'exec_input'):
            self.exec_label.show()
            self.exec_input.show()
            self.exec_button.show()
            self.exec_download_button.show()
            self.exec_output.show()

    
    def export_data(self):
        # Implement export functionality
        pass

    def show_help(self):
        # Implement help functionality
        pass

    def set_auto_refresh(self, value):
        self.refresh_timer.stop()
        if value != "Off":
            seconds = int(value.split()[0])
            self.refresh_timer.start(seconds * 1000)
            self.refresh_timer.timeout.connect(self.refresh_events) 
            self.refresh_timer.timeout.connect(self.update_resources) 

    def filter_info(self, text):
        # Store the current cursor position
        current_cursor = self.describe_text.textCursor()
        current_position = current_cursor.position()

        # Clear all existing highlights
        cursor = self.describe_text.textCursor()
        cursor.select(QTextCursor.Document)
        format = QTextCharFormat()
        format.setBackground(QColor("#2A2A2A"))  # Set to the dark background color
        format.setForeground(Qt.white)  # Set text color to white
        cursor.mergeCharFormat(format)

        if text:
            # Create a format for highlighting
            highlight_format = QTextCharFormat()
            highlight_format.setBackground(QColor("yellow"))
            highlight_format.setForeground(Qt.black)  # Set highlighted text color to black for better contrast

            # Reset cursor to the beginning of the document
            cursor.setPosition(0)

            # Find and highlight all occurrences
            while True:
                cursor = self.describe_text.document().find(text, cursor, QTextDocument.FindCaseSensitively)
                if cursor.isNull():
                    break
                cursor.mergeCharFormat(highlight_format)

        # Restore the original cursor position
        current_cursor.setPosition(current_position)
        self.describe_text.setTextCursor(current_cursor)

    def load_namespaces(self):
        try:
            namespaces = [ns.metadata.name for ns in self.v1.list_namespace().items]
            self.namespace_combo1.clear()
            self.namespace_combo2.clear()
            self.namespace_combo1.addItems(namespaces)
            self.namespace_combo2.addItems(namespaces)
            if namespaces:
                self.namespace_combo1.setCurrentIndex(0)
                if len(namespaces) > 1:
                    self.namespace_combo2.setCurrentIndex(1)
                else:
                    self.namespace_combo2.setCurrentIndex(0)
            return namespaces
        except Exception as e:
            print(f"Error loading namespaces: {str(e)}")
            return None

    def delete_resource(self, resource_type, resource_name, namespace):
        try:
            if resource_type == "Pods":
                self.v1.delete_namespaced_pod(resource_name, namespace)
            elif resource_type == "Services":
                self.v1.delete_namespaced_service(resource_name, namespace)
            elif resource_type == "Deployments":
                self.apps_v1.delete_namespaced_deployment(resource_name, namespace)
            elif resource_type == "StatefulSets":
                self.apps_v1.delete_namespaced_stateful_set(resource_name, namespace)
            elif resource_type == "PVC":
                self.v1.delete_namespaced_persistent_volume_claim(resource_name, namespace)
            elif resource_type == "PV":
                self.v1.delete_persistent_volume(resource_name)
            elif resource_type == "Secrets":
                self.v1.delete_namespaced_secret(resource_name, namespace)
            elif resource_type == "ConfigMaps":
                self.v1.delete_namespaced_config_map(resource_name, namespace)
            elif resource_type == "Jobs":
                self.batch_v1.delete_namespaced_job(resource_name, namespace)
            elif resource_type == "CronJobs":
                self.batch_v1.delete_namespaced_cron_job(resource_name, namespace)
            self.update_status(f"{resource_type} {resource_name} deleted successfully")
        except Exception as e:
            raise Exception(f"Error deleting {resource_type} {resource_name}: {str(e)}")
    
    def perform_action(self, action):
        if not self.current_resource_name:
            return

        resource_type = self.get_current_resource_type()

        # Confirmation dialog
        confirm_msg = f"Are you sure you want to {action.lower()} the {resource_type} '{self.current_resource_name}'"
        if self.current_namespace:
            confirm_msg += f" in namespace '{self.current_namespace}'"
        confirm_msg += "?"
        
        reply = QMessageBox.question(self, 'Confirm Action', confirm_msg, 
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.No:
            return

        try:
            if action == "Delete":
                self.delete_resource(resource_type, self.current_resource_name, self.current_namespace)
            elif action == "Stream":
                if resource_type == "Pods":
                    self.stream_logs()
            elif action == "SSH":
                if resource_type == "Nodes":
                    self.ssh_to_node(self.current_resource_name)
            elif action == "Port Forward":
                if resource_type == "Services":
                    self.port_forward_service(self.current_resource_name, self.current_namespace)

            # Update the resources after performing the action
            self.update_resources()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def create_resource_tab(self, resource_type):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        namespace_layout = QHBoxLayout()
        namespace_layout.addWidget(QLabel("Namespace:"))
        namespace_combo = QComboBox()
        namespace_layout.addWidget(namespace_combo)
        layout.addLayout(namespace_layout)

        table = QTableView()
        model = QStandardItemModel()
        proxy_model = QSortFilterProxyModel()
        proxy_model.setSourceModel(model)
        table.setModel(proxy_model)
        layout.addWidget(table)

        self.resource_tabs.addTab(tab, resource_type)

        setattr(self, f"{resource_type.lower()}_namespace_combo", namespace_combo)
        setattr(self, f"{resource_type.lower()}_table", table)
        setattr(self, f"{resource_type.lower()}_model", model)
        setattr(self, f"{resource_type.lower()}_proxy_model", proxy_model)

        table.selectionModel().selectionChanged.connect(lambda: self.update_resource_info(resource_type))

    def edit_resource(self, row):
        resource_type = self.get_current_resource_type()
        source_row = self.proxy_model.mapToSource(self.proxy_model.index(row, 0)).row()
        namespace = self.table_model.item(source_row, 0).text()
        resource_name = self.table_model.item(source_row, 1).text()

        try:
            if resource_type == "Deployments":
                resource = self.apps_v1.read_namespaced_deployment(resource_name, namespace)
            elif resource_type == "StatefulSets":
                resource = self.apps_v1.read_namespaced_stateful_set(resource_name, namespace)
            elif resource_type == "Services":
                resource = self.v1.read_namespaced_service(resource_name, namespace)
            elif resource_type == "ConfigMaps":
                resource = self.v1.read_namespaced_config_map(resource_name, namespace)
            elif resource_type == "Secrets":
                resource = self.v1.read_namespaced_secret(resource_name, namespace)
            else:
                QMessageBox.information(self, "Not Implemented", f"Editing for {resource_type} is not implemented yet")
                return

            edit_dialog = EditResourceDialog(resource_type, resource, self)
            result = edit_dialog.exec_()

            if result == QDialog.Accepted:
                updated_resource = edit_dialog.get_updated_resource()

                # Apply changes
                if resource_type == "Deployments":
                    self.apps_v1.replace_namespaced_deployment(resource_name, namespace, updated_resource)
                elif resource_type == "StatefulSets":
                    self.apps_v1.replace_namespaced_stateful_set(resource_name, namespace, updated_resource)
                elif resource_type == "Services":
                    self.v1.replace_namespaced_service(resource_name, namespace, updated_resource)
                elif resource_type == "ConfigMaps":
                    self.v1.replace_namespaced_config_map(resource_name, namespace, updated_resource)
                elif resource_type == "Secrets":
                    # For secrets, we need to ensure the data is base64 encoded
                    if updated_resource.data:
                        updated_resource.data = {k: base64.b64encode(v.encode()).decode() for k, v in updated_resource.data.items()}
                    self.v1.replace_namespaced_secret(resource_name, namespace, updated_resource)

                QMessageBox.information(self, "Success", f"{resource_type} '{resource_name}' updated successfully")
                self.update_resources()
            else:
                QMessageBox.information(self, "Cancelled", "No changes were made")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def update_resource_field(self, resource, category, field, value):
        if category == "Metadata":
            if field == "labels":
                resource.metadata.labels = value
        elif category == "Spec":
            if field == "replicas":
                resource.spec.replicas = value
            elif field == "image":
                resource.spec.template.spec.containers[0].image = value
            elif field == "env":
                resource.spec.template.spec.containers[0].env = [{"name": k, "value": v} for k, v in value.items()]
            elif field == "resources":
                resource.spec.template.spec.containers[0].resources = client.V1ResourceRequirements(**value)
        elif category == "Data":
            resource.data = value

    def get_pod_editable_fields(self, pod):
        return {
            "Metadata": {
                "labels": pod.metadata.labels
            },
            "Spec": {
                "image": pod.spec.containers[0].image,
                "env": self.get_env_vars(pod.spec.containers[0].env),
                "resources": self.get_resources(pod.spec.containers[0].resources)
            }
        }

    def get_deployment_editable_fields(self, deployment):
        return {
            "Metadata": {
                "labels": deployment.metadata.labels
            },
            "Spec": {
                "replicas": deployment.spec.replicas,
                "image": deployment.spec.template.spec.containers[0].image,
                "env": self.get_env_vars(deployment.spec.template.spec.containers[0].env),
                "resources": self.get_resources(deployment.spec.template.spec.containers[0].resources)
            }
        }

    def get_statefulset_editable_fields(self, statefulset):
        return {
            "Metadata": {
                "labels": statefulset.metadata.labels
            },
            "Spec": {
                "replicas": statefulset.spec.replicas,
                "image": statefulset.spec.template.spec.containers[0].image,
                "env": self.get_env_vars(statefulset.spec.template.spec.containers[0].env),
                "resources": self.get_resources(statefulset.spec.template.spec.containers[0].resources)
            }
        }

    def get_pvc_editable_fields(self, pvc):
        return {
            "Metadata": {
                "labels": pvc.metadata.labels
            },
            "Spec": {
                "storage": pvc.spec.resources.requests['storage']
            }
        }

    def get_configmap_editable_fields(self, configmap):
        return {
            "Metadata": {
                "labels": configmap.metadata.labels
            },
            "Data": configmap.data
        }

    def get_secret_editable_fields(self, secret):
        return {
            "Metadata": {
                "labels": secret.metadata.labels
            },
            "Data": {k: base64.b64decode(v).decode() for k, v in secret.data.items()}
        }

    def get_env_vars(self, env_list):
        return {env.name: env.value for env in env_list if env.value is not None}

    def get_resources(self, resources):
        if resources is None:
            return {}
        return {
            "limits": resources.limits,
            "requests": resources.requests
        }

    def load_ssh_key_from_kubeconfig(self):
        try:
            contexts, active_context = config.list_kube_config_contexts()
            if active_context:
                user = active_context['context']['user']
                clusters = config.list_kube_config_clusters()
                for cluster in clusters:
                    if 'users' in cluster:
                        for cluster_user in cluster['users']:
                            if cluster_user['name'] == user and 'client-key' in cluster_user['user']:
                                self.ssh_key_file = cluster_user['user']['client-key']
                                return
            raise ValueError("No valid SSH key found in kubeconfig")
        except Exception as e:
            print(f"Error loading SSH key from kubeconfig: {str(e)}")
        
        # Fall back to default ~/.ssh/id_rsa
        self.ssh_key_file = os.path.expanduser("~/.ssh/id_rsa")
        print(f"Using default SSH key: {self.ssh_key_file}")

    def verify_port_forwarding(self):
        for key, (local_port, pid) in list(self.port_forwarding_dict.items()):
            if not self.is_process_running(pid):
                del self.port_forwarding_dict[key]
        self.save_port_forwarding()

    def is_process_running(self, pid):
        try:
            process = psutil.Process(pid)
            return process.is_running() and 'kubectl' in process.name() and 'port-forward' in process.cmdline()
        except psutil.NoSuchProcess:
            return False

    def clean_resource_dict(self, d):
        if isinstance(d, dict):
            # Remove kubernetes-specific fields that can't be updated
            keys_to_remove = ['status', 'metadata.resourceVersion', 'metadata.uid', 'metadata.creationTimestamp', 
                            'metadata.generation', 'metadata.managedFields']
            
            for key in keys_to_remove:
                parts = key.split('.')
                current = d
                for part in parts[:-1]:
                    if part in current:
                        current = current[part]
                    else:
                        break
                if parts[-1] in current:
                    del current[parts[-1]]

            # Recursively clean nested dictionaries
            for k, v in list(d.items()):
                if k == 'managedFields':
                    del d[k]
                elif isinstance(v, dict):
                    self.clean_resource_dict(v)
                elif isinstance(v, list):
                    d[k] = [self.clean_resource_dict(item) if isinstance(item, dict) else item for item in v]

        # Remove None values
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if v is not None}
        return d

    def on_resource_selected(self, selected, deselected):
        if selected.indexes():
            self.selection_timer.start(200)  # 200ms debounce

    def delayed_update_resource_info(self):
        selected_indexes = self.resource_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        row = selected_indexes[0].row()
        resource_type = self.get_current_resource_type()

        if resource_type in ["Nodes", "PV"]:
            self.current_resource_name = self.proxy_model.data(self.proxy_model.index(row, 0))
            self.current_namespace = None
        else:
            self.current_namespace = self.proxy_model.data(self.proxy_model.index(row, 0))
            self.current_resource_name = self.proxy_model.data(self.proxy_model.index(row, 1))

        self.current_resource_label.setText(f"Current {resource_type}: {self.current_resource_name}")
        self.update_info_type_combo()
        self.update_action_buttons()

        # Show decode checkbox only for Secrets
        if resource_type == "Secrets":
            self.decode_checkbox.show()
        else:
            self.decode_checkbox.hide()

        # Add this block to update container list for Pods
        if resource_type == "Pods":
            self.update_container_list()
        else:
            self.container_label.hide()
            self.container_combo.hide()

        # Only update the currently visible tab
        current_tab = self.info_tabs.currentWidget()
        if current_tab == self.describe_tab:
            self.update_describe_tab()
        elif current_tab == self.logs_tab:
            self.update_logs_tab()
        elif current_tab == self.events_tab:
            self.show_events()
        elif current_tab == self.volumes_tab:
            self.show_volumes()

    def update_resources(self):
        self.table_model.clear()
        self.current_resource_name = None
        self.current_namespace = None
        self.table_model.setHorizontalHeaderLabels([])
        self.update_status("Refreshing resources...")
        
        resource_type = self.get_current_resource_type()
        namespaces = self.get_selected_namespaces()
        print(f"Updating resources for type: {resource_type}")
        print(f"Selected namespaces for resources: {namespaces}")
        
        # Use QTimer to defer the heavy operation
        QTimer.singleShot(0, lambda: self._update_resources(resource_type, namespaces))


    def get_current_resource_type(self):
        resource_types = ["Pods", "Deployments", "StatefulSets", "Jobs", "CronJobs", "PVC", "PV", "Secrets", "ConfigMaps", "Services", "Nodes"]
        return resource_types[self.resource_tabs.currentIndex()]

    def _update_resources(self, resource_type, namespaces):
        QApplication.processEvents()  # This will update the UI immediately

        self.table_model.clear()
        try:
            if resource_type == "Pods":
                update_pods(self, namespaces, self.table_model)
            elif resource_type == "Deployments":
                update_deployments(self, namespaces, self.table_model)
            elif resource_type == "StatefulSets":
                update_statefulsets(self, namespaces, self.table_model)
            elif resource_type == "Jobs":
                update_jobs(self, namespaces, self.table_model)
            elif resource_type == "CronJobs":
                update_cronjobs(self, namespaces, self.table_model)
            elif resource_type == "PVC":
                update_pvcs(self, namespaces, self.table_model)
            elif resource_type == "PV":
                update_pvs(self, self.table_model)
            elif resource_type == "Secrets":
                update_secrets(self, namespaces, self.table_model)
            elif resource_type == "ConfigMaps":
                update_configmaps(self, namespaces, self.table_model)
            elif resource_type == "Services":
                self.update_services(namespaces, self.table_model)
            elif resource_type == "Nodes":
                update_nodes(self, self.table_model)
            self.update_status("Resources refreshed successfully.")
        except Exception as e:
            self.update_status("Error fetching resources")
            print(f"Error fetching resources: {str(e)}")
            self.table_model.clear()

        # Update the view after populating the model
        self.resource_table.resizeColumnsToContents()
        self.resource_table.resizeRowsToContents()
        self.resource_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.resource_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    def get_port_forwarding_status(self, namespace, service_name):
        key = f"{namespace}/{service_name}"
        if key in self.port_forwarding_dict:
            port, _ = self.port_forwarding_dict[key]
            return f"localhost:{port}"
        return "Not forwarded"

    def update_services(self, namespaces, model):
        services = []
        for ns in namespaces:
            services.extend(self.v1.list_namespaced_service(ns).items)

        model.setHorizontalHeaderLabels(["Namespace", "Name", "Cluster IP", "External IP", "Ports", "Age", "Port Forwarding", "Actions"])
        
        for i, service in enumerate(services):
            model.setItem(i, 0, QStandardItem(service.metadata.namespace))
            model.setItem(i, 1, QStandardItem(service.metadata.name))
            model.setItem(i, 2, QStandardItem(service.spec.cluster_ip))
            external_ips = service.status.load_balancer.ingress[0].ip if service.status.load_balancer.ingress else "None"
            model.setItem(i, 3, QStandardItem(external_ips))
            ports = ", ".join([f"{port.port}/{port.protocol}" for port in service.spec.ports])
            model.setItem(i, 4, QStandardItem(ports))
            model.setItem(i, 5, QStandardItem(str(service.metadata.creation_timestamp)))
            
            # Add Port Forwarding status
            key = f"{service.metadata.namespace}/{service.metadata.name}"
            port_forwarding = self.get_port_forwarding_status(service.metadata.namespace, service.metadata.name)
            model.setItem(i, 6, QStandardItem(port_forwarding))

            # Add Stop Port Forwarding button
            if key in self.port_forwarding_dict:
                stop_button = QPushButton("Stop Port Forwarding")
                stop_button.clicked.connect(lambda _, ns=service.metadata.namespace, name=service.metadata.name: self.stop_port_forwarding(ns, name))
                model.setItem(i, 7, QStandardItem(""))
                self.resource_table.setIndexWidget(model.index(i, 7), stop_button)
            else:
                model.setItem(i, 7, QStandardItem(""))

        self.resource_table.resizeColumnsToContents()

    def stop_all_port_forwarding(self):
        for key in list(self.port_forwarding_dict.keys()):
            namespace, service_name = key.split('/')
            self.stop_port_forwarding(namespace, service_name)

    def update_resource_info(self):
        selected_indexes = self.resource_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        row = selected_indexes[0].row()
        resource_type = self.get_current_resource_type()

        if resource_type == "Nodes" or resource_type == "PV":
            self.current_resource_name = self.proxy_model.data(self.proxy_model.index(row, 0))
            self.current_namespace = None
        else:
            self.current_namespace = self.proxy_model.data(self.proxy_model.index(row, 0))
            self.current_resource_name = self.proxy_model.data(self.proxy_model.index(row, 1))

        self.current_resource_label.setText(f"Current {resource_type}: {self.current_resource_name}")
        
         # Show decode checkbox only for Secrets
        if resource_type == "Secrets":
            self.decode_checkbox.show()
        else:
            self.decode_checkbox.hide()

        if resource_type == "Pods":
            try:
                pod = self.v1.read_namespaced_pod(self.current_resource_name, self.current_namespace)
                self.update_container_list() 
                containers = [container.name for container in pod.spec.containers]
                
                print(f"Containers: {containers}")  # Debug print
                
                if len(containers) > 1:
                    self.container_combo.clear()
                    self.container_combo.addItems(containers)
                    self.container_combo.setCurrentIndex(0)
                    self.container_label.show()
                    self.container_combo.show()
                    print("Showing container dropdown")  # Debug print
                else:
                    self.container_label.hide()
                    self.container_combo.hide()
                    print("Hiding container dropdown")  # Debug print
                
                # Force layout update
                self.container_label.parent().layout().update()
                
            except Exception as e:
                print(f"Error fetching pod info: {str(e)}")  # Debug print
        else:
            self.container_label.hide()
            self.container_combo.hide()
        
        self.update_action_buttons()
        self.update_info_display()

    def update_container_list(self):
        if not self.current_resource_name or not self.current_namespace:
            print("No resource selected or namespace not set")
            self.container_label.hide()
            self.container_combo.hide()
            return

        try:
            pod = self.v1.read_namespaced_pod(self.current_resource_name, self.current_namespace)
            containers = [container.name for container in pod.spec.containers]
            
            print(f"Containers found: {containers}")  # Debug print
            
            self.container_combo.clear()
            self.container_combo.addItems(containers)
            
            if len(containers) > 1:
                self.container_label.show()
                self.container_combo.show()
                print("Showing container dropdown")  # Debug print
            else:
                self.container_label.hide()
                self.container_combo.hide()
                print("Hiding container dropdown")  # Debug print
            
            # Force layout update
            self.layout().update()
            self.repaint()
            
        except Exception as e:
            print(f"Error updating container list: {str(e)}")
            self.container_label.hide()
            self.container_combo.hide()

    def show_events(self):

        # Clear existing content
        self.events_text.clear()

        # Create a table for events
        events_table = QTableWidget()
        events_table.setColumnCount(4)
        events_table.setHorizontalHeaderLabels(["Time", "Type", "Reason", "Message"])
        events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        events_table.setSelectionMode(QAbstractItemView.SingleSelection)
        events_table.horizontalHeader().setStretchLastSection(True)
        events_table.verticalHeader().setVisible(False)

        # Fetch events
        events = self.v1.list_namespaced_event(
            namespace=self.current_namespace,
            field_selector=f"involvedObject.name={self.current_resource_name}"
        )

        # Populate the table
        for event in events.items:
            row_position = events_table.rowCount()
            events_table.insertRow(row_position)
            event_time = event.last_timestamp or event.event_time
            event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S') if event_time else ''
            events_table.setItem(row_position, 0, QTableWidgetItem(event_time_str))
            events_table.setItem(row_position, 1, QTableWidgetItem(event.type))
            events_table.setItem(row_position, 2, QTableWidgetItem(event.reason))
            events_table.setItem(row_position, 3, QTableWidgetItem(event.message))

        # Set the table as the content of events_text
        self.events_text.setPlainText("")  # Clear any existing text
        text_cursor = self.events_text.textCursor()
        
        # Create a table that spans the full width
        table_format = QTextTableFormat()
        table_format.setAlignment(Qt.AlignLeft)
        table_format.setCellPadding(2)
        table_format.setCellSpacing(2)
        
        table = text_cursor.insertTable(events_table.rowCount() + 1, 4, table_format)
        
        # Insert headers
        for col in range(4):
            cell = table.cellAt(0, col)
            cellCursor = cell.firstCursorPosition()
            cellCursor.insertText(events_table.horizontalHeaderItem(col).text())
        
        # Insert data
        for row in range(events_table.rowCount()):
            for col in range(4):
                cell = table.cellAt(row + 1, col)
                cellCursor = cell.firstCursorPosition()
                cellCursor.insertText(events_table.item(row, col).text())


    def show_volumes(self):
        if self.get_current_resource_type() != "Pods":
            self.volumes_text.setPlainText("Volumes are only available for Pods.")
            return

        # Clear existing content
        self.volumes_text.clear()

        # Fetch pod information
        pod = self.v1.read_namespaced_pod(self.current_resource_name, self.current_namespace)

        # Create a table for volumes
        volumes_table = QTableWidget()
        volumes_table.setColumnCount(3)
        volumes_table.setHorizontalHeaderLabels(["Name", "Type", "Details"])
        volumes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        volumes_table.setSelectionMode(QAbstractItemView.SingleSelection)
        volumes_table.horizontalHeader().setStretchLastSection(True)
        volumes_table.verticalHeader().setVisible(False)

        # Populate the table
        for volume in pod.spec.volumes:
            row_position = volumes_table.rowCount()
            volumes_table.insertRow(row_position)
            volumes_table.setItem(row_position, 0, QTableWidgetItem(volume.name))
            
            volume_type, details = self.get_volume_type_and_details(volume)
            volumes_table.setItem(row_position, 1, QTableWidgetItem(volume_type))
            volumes_table.setItem(row_position, 2, QTableWidgetItem(details))

        # Set the table as the content of volumes_text
        self.volumes_text.setPlainText("")  # Clear any existing text
        text_cursor = self.volumes_text.textCursor()
        
        # Create a table that spans the full width
        table_format = QTextTableFormat()
        table_format.setAlignment(Qt.AlignLeft)
        table_format.setBorderStyle(QTextFrameFormat.BorderStyle_None)
        table_format.setCellPadding(2)
        table_format.setCellSpacing(2)
        table_format.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        
        table = text_cursor.insertTable(volumes_table.rowCount() + 1, 3, table_format)
        
        # Insert headers
        for col in range(3):
            cell = table.cellAt(0, col)
            cellCursor = cell.firstCursorPosition()
            cellCursor.insertText(volumes_table.horizontalHeaderItem(col).text())
        
        # Insert data
        for row in range(volumes_table.rowCount()):
            for col in range(3):
                cell = table.cellAt(row + 1, col)
                cellCursor = cell.firstCursorPosition()
                cellCursor.insertText(volumes_table.item(row, col).text())


    def get_volume_type_and_details(self, volume):
        if volume.secret:
            return "Secret", volume.secret.secret_name
        elif volume.config_map:
            return "ConfigMap", volume.config_map.name
        elif volume.aws_elastic_block_store:
            return "AWSElasticBlockStore", f"Volume ID: {volume.aws_elastic_block_store.volume_id}"
        elif volume.nfs:
            return "NFS", f"Server: {volume.nfs.server}, Path: {volume.nfs.path}"
        elif volume.empty_dir:
            return "EmptyDir", "N/A"
        elif volume.persistent_volume_claim:
            return "PersistentVolumeClaim", volume.persistent_volume_claim.claim_name
        elif volume.projected:
            return "Projected", "Multiple sources"
        # Add other volume types as needed
        else:
            return "Unknown", "N/A"

    def update_info_display(self):
        if not self.current_resource_name:
            return
        
        QTimer.singleShot(0, self._update_info_display)

    def _update_info_display(self):

        resource_type = self.get_current_resource_type()
        info_type = self.info_tabs.tabText(self.info_tabs.currentIndex())

        try:
            if resource_type == "Pods":
                if info_type == "Describe":
                    resource = self.v1.read_namespaced_pod(self.current_resource_name, self.current_namespace)
                    self.display_resource_info(resource)
                elif info_type == "Events":
                    self.show_events()
                elif info_type == "Logs":
                    container = self.container_combo.currentText() if self.container_combo.isVisible() else None
                    logs = self.v1.read_namespaced_pod_log(self.current_resource_name, self.current_namespace, container=container)
                    self.logs_text.setPlainText(logs)
                elif info_type == "Volumes":
                    self.show_volumes()
            elif resource_type == "Deployments":
                resource = self.apps_v1.read_namespaced_deployment(self.current_resource_name, self.current_namespace)
            elif resource_type == "StatefulSets":
                resource = self.apps_v1.read_namespaced_stateful_set(self.current_resource_name, self.current_namespace)
            elif resource_type == "Jobs":
                resource = self.batch_v1.read_namespaced_job(self.current_resource_name, self.current_namespace)
            elif resource_type == "CronJobs":
                resource = self.batch_v1.read_namespaced_cron_job(self.current_resource_name, self.current_namespace)
            elif resource_type == "PVC":
                resource = self.v1.read_namespaced_persistent_volume_claim(self.current_resource_name, self.current_namespace)
            elif resource_type == "PV":
                resource = self.v1.read_persistent_volume(self.current_resource_name)
            elif resource_type == "Secrets":
                resource = self.v1.read_namespaced_secret(self.current_resource_name, self.current_namespace)
            elif resource_type == "ConfigMaps":
                resource = self.v1.read_namespaced_config_map(self.current_resource_name, self.current_namespace)
            elif resource_type == "Services":
                resource = self.v1.read_namespaced_service(self.current_resource_name, self.current_namespace)
            elif resource_type == "Nodes":
                resource = self.v1.read_node(self.current_resource_name)
            else:
                self.describe_text.setPlainText(f"Description not available for resource type: {resource_type}")
                return

            if info_type == "Describe":
                resource_dict = resource.to_dict()
                self.clean_resource_dict(resource_dict)
                
                if self.show_full_yaml_checkbox.isChecked():
                    formatted_output = self.format_resource_info(resource_dict)
                else:
                    if resource_type in ["Secrets", "ConfigMaps"]:
                        # For Secrets and ConfigMaps, show 'data' instead of 'spec'
                        data = resource_dict.get('data', {}) or {}  # Use empty dict if data is None
                        formatted_output = self.format_resource_info({'data': data, 'type': resource_dict.get('type')})
                    else:
                        formatted_output = self.format_resource_info({'spec': resource_dict.get('spec', {})})
                
                if self.decode_checkbox.isChecked() and resource_type in ["Secrets", "ConfigMaps"]:
                    formatted_output = self.decode_base64_in_yaml(formatted_output)
                
                self.describe_text.setPlainText(formatted_output)

        except Exception as e:
            self.describe_text.setPlainText(f"Error fetching resource info: {str(e)}")


    def format_resource_info(self, resource_dict):
        formatted_output = ""
        
        if 'metadata' in resource_dict:
            formatted_output += "Metadata:\n"
            for key, value in resource_dict['metadata'].items():
                if key not in ['managedFields', 'annotations']:
                    formatted_output += f"  {key}: {value}\n"
            formatted_output += "\n"
        
        if 'spec' in resource_dict:
            formatted_output += "Spec:\n"
            formatted_output += self.format_dict(resource_dict['spec'], indent=2)
            formatted_output += "\n"
        
        if 'data' in resource_dict:
            formatted_output += "Data:\n"
            formatted_output += self.format_dict(resource_dict['data'], indent=2)
            formatted_output += "\n"
        
        if 'type' in resource_dict:
            formatted_output += f"Type: {resource_dict['type']}\n\n"
        
        if 'status' in resource_dict:
            formatted_output += "Status:\n"
            formatted_output += self.format_dict(resource_dict['status'], indent=2)
        
        return formatted_output

    def format_dict(self, d, indent=0):
        formatted = ""
        for key, value in d.items():
            if isinstance(value, dict):
                formatted += f"{'  ' * indent}{key}:\n"
                formatted += self.format_dict(value, indent + 1)
            elif isinstance(value, list):
                formatted += f"{'  ' * indent}{key}:\n"
                for item in value:
                    if isinstance(item, dict):
                        formatted += self.format_dict(item, indent + 1)
                    else:
                        formatted += f"{'  ' * (indent + 1)}- {item}\n"
            else:
                formatted += f"{'  ' * indent}{key}: {value}\n"
        return formatted

    def download_info(self):
        content = self.describe_text.toPlainText()
        if not content:
            QMessageBox.warning(self, "No Content", "There's no information to download.")
            return

        file_name, _ = QFileDialog.getSaveFileName(self, "Save Info", "", "YAML Files (*.yaml);;All Files (*)")
        if file_name:
            with open(file_name, 'w') as f:
                f.write(content)
            QMessageBox.information(self, "Download Complete", "Information has been saved successfully.")

    def download_exec_output(self):
        content = self.exec_output.toPlainText()
        if not content:
            QMessageBox.warning(self, "No Content", "There's no execution output to download.")
            return

        file_name, _ = QFileDialog.getSaveFileName(self, "Save Exec Output", "", "Text Files (*.txt);;All Files (*)")
        if file_name:
            with open(file_name, 'w') as f:
                f.write(content)
            QMessageBox.information(self, "Download Complete", "Execution output has been saved successfully.")

    def decode_base64_in_yaml(self, yaml_str):
        lines = yaml_str.split('\n')
        decoded_lines = []
        for line in lines:
            if ': ' in line:
                key, value = line.split(': ', 1)
                try:
                    decoded_value = base64.b64decode(value.strip()).decode('utf-8')
                    decoded_lines.append(f"{key}: {decoded_value}")
                except:
                    decoded_lines.append(line)
            else:
                decoded_lines.append(line)
        return '\n'.join(decoded_lines)

    def show_disk_usage(self):
        try:
            container = self.container_combo.currentText() if self.container_combo.isVisible() else None
            exec_command = [
                '/bin/sh',
                '-c',
                'df -h'
            ]
            resp = stream(self.v1.connect_get_namespaced_pod_exec,
                        self.current_resource_name,  # Changed from current_pod_name
                        self.current_namespace,
                        command=exec_command,
                        container=container,
                        stderr=True, stdin=False,
                        stdout=True, tty=False)
            
            self.describe_text.clear()
            cursor = self.describe_text.textCursor()
            
            for line in resp.split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        usage = int(parts[4].rstrip('%'))
                        if usage >= 90:
                            color = QColor(255, 0, 0)  # Red
                        elif usage >= 70:
                            color = QColor(255, 255, 0)  # Yellow
                        else:
                            color = QColor(255, 255, 255)  # white
                        
                        format = QTextCharFormat()
                        format.setForeground(color)
                        cursor.insertText(line + '\n', format)
                    except ValueError:
                        cursor.insertText(line + '\n')
                else:
                    cursor.insertText(line + '\n')
            
            self.describe_text.setTextCursor(cursor)
        except Exception as e:
            self.describe_text.setPlainText(f"Error fetching disk usage: {str(e)}")

    def execute_command(self):
        if not self.current_resource_name or self.get_current_resource_type() != "Pods":
            self.exec_output.setPlainText("Please select a pod to execute commands.")
            return

        command = self.exec_input.text()
        container = self.container_combo.currentText() if self.container_combo.isVisible() else None

        try:
            exec_command = ['/bin/sh', '-c', command]
            resp = stream(self.v1.connect_get_namespaced_pod_exec,
                        self.current_resource_name,
                        self.current_namespace,
                        command=exec_command,
                        container=container,
                        stderr=True, stdin=False,
                        stdout=True, tty=False)
            self.exec_output.setPlainText(resp)
        except Exception as e:
            self.exec_output.setPlainText(f"Error executing command: {str(e)}")

    def resource_action(self, action, row):
        resource_type = self.get_current_resource_type()
        source_row = self.proxy_model.mapToSource(self.proxy_model.index(row, 0)).row()
        namespace = self.table_model.item(source_row, 0).text()
        resource_name = self.table_model.item(source_row, 1).text()

        # Confirmation dialog
        confirm_msg = f"Are you sure you want to {action.lower()} the {resource_type} '{resource_name}'"
        if namespace:
            confirm_msg += f" in namespace '{namespace}'"
        confirm_msg += "?"
        
        reply = QMessageBox.question(self, 'Confirm Action', confirm_msg, 
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.No:
            return

        try:
            if action == "Delete":
                if resource_type == "Pods":
                    self.v1.delete_namespaced_pod(resource_name, namespace)
                elif resource_type == "PVC":
                    self.v1.delete_namespaced_persistent_volume_claim(resource_name, namespace)
                elif resource_type == "PV":
                    self.v1.delete_persistent_volume(resource_name)
                elif resource_type == "Secrets":
                    self.v1.delete_namespaced_secret(resource_name, namespace)
                elif resource_type == "ConfigMaps":
                    self.v1.delete_namespaced_config_map(resource_name, namespace)
                elif resource_type == "Jobs":
                    self.batch_v1.delete_namespaced_job(resource_name, namespace)
                elif resource_type == "CronJobs":
                    self.batch_v1.delete_namespaced_cron_job(resource_name, namespace)
                self.update_status(f"{resource_type} {resource_name} deleted successfully")
            
            self.update_resources()
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def stream_logs(self, row=None):
        if hasattr(self, 'log_thread') and self.log_thread.isRunning():
            print("A log streaming thread is already running. Please close the existing log window first.")
            if self.log_dialog:
                self.log_dialog.raise_()
                self.log_dialog.activateWindow()
            return

        if row is not None:
            # If called from the table action button
            resource_type = self.get_current_resource_type()
            source_row = self.proxy_model.mapToSource(self.proxy_model.index(row, 0)).row()
            namespace = self.table_model.item(source_row, 0).text()
            pod_name = self.table_model.item(source_row, 1).text()
        else:
            # If called from the info display
            pod_name = self.current_resource_name
            namespace = self.current_namespace

        if pod_name and self.get_current_resource_type() == "Pods":
            # Get all containers in the pod
            pod = self.v1.read_namespaced_pod(pod_name, namespace)
            containers = [container.name for container in pod.spec.containers]
            
            # Create a new dialog for log streaming
            self.log_dialog = QDialog(self)
            self.log_dialog.setWindowTitle(f"Logs: {pod_name}")
            self.log_dialog.setGeometry(100, 100, 800, 600)
            
            log_text = QTextEdit(self.log_dialog)
            log_text.setReadOnly(True)
            
            layout = QVBoxLayout(self.log_dialog)
            layout.addWidget(log_text)

            # Create the log streamer thread with since_time parameter
            current_time = datetime.now(timezone.utc).isoformat()
            self.log_thread = LogStreamerThread(self.v1, pod_name, namespace, containers, since_time=current_time)

            # Connect signals and slots
            self.log_thread.new_log.connect(log_text.append)
            self.log_thread.finished.connect(self.on_log_thread_finished)

            # Start the thread
            self.log_thread.start()

            # Disconnect any existing connections
            try:
                self.log_dialog.finished.disconnect()
            except:
                pass

            # Clean up when the dialog is closed
            self.log_dialog.finished.connect(self.stop_log_streaming)

            self.log_dialog.exec_()

    def on_log_thread_finished(self):
        print("Log thread finished.")
        if hasattr(self, 'log_thread'):
            self.log_thread.deleteLater()
            delattr(self, 'log_thread')

    def stop_log_streaming(self, _=None):
        if not hasattr(self, 'log_thread') or sip.isdeleted(self.log_thread):
            print("No active log thread to stop.")
            return

        print("Stopping log streaming...")
        
        try:
            if hasattr(self, 'log_thread') and self.log_thread.isRunning():
                print("Stopping log thread...")
                self.log_thread.stop()
                if not self.log_thread.wait(5000):  # Wait for 5 seconds
                    print("Log thread did not finish in time, forcing termination...")
                    self.log_thread.terminate()
                    self.log_thread.wait()  # Wait for the thread to be fully terminated
                print("Log thread finished")
        except RuntimeError as e:
            print(f"Error while stopping log thread: {e}")
        
        print("Log streaming stopped")
        
        # Clean up the references
        if hasattr(self, 'log_thread'):
            self.log_thread.deleteLater()
            delattr(self, 'log_thread')
        if hasattr(self, 'log_dialog') and self.log_dialog and not sip.isdeleted(self.log_dialog):
            self.log_dialog.reject()  # Use reject() instead of accept()
            self.log_dialog = None

        # Ensure we're not triggering any unintended actions
        QApplication.processEvents()

    def apply_resource(self):
        yaml_content = self.yaml_input.toPlainText()
        namespace = self.apply_namespace_combo.currentText()

        try:
            resource = yaml.safe_load(yaml_content)
            kind = resource["kind"]
            name = resource["metadata"]["name"]

            confirm_msg = f"Are you sure you want to apply the {kind} '{name}' in namespace '{namespace}'?"
            reply = QMessageBox.question(self, 'Confirm Apply', confirm_msg, 
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
            if reply == QMessageBox.No:
                return
            api_client = client.ApiClient()
            utils = client.ApiClient().sanitize_for_serialization(resource)
            
            kind = resource["kind"]
            
            if kind == "Pod":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_pod(namespace, utils)
            elif kind == "Deployment":
                api_instance = client.AppsV1Api(api_client)
                api_instance.create_namespaced_deployment(namespace, utils)
            elif kind == "Service":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_service(namespace, utils)
            elif kind == "PersistentVolumeClaim" or kind == "PVC":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_persistent_volume_claim(namespace, utils)
            elif kind == "StatefulSet":
                api_instance = client.AppsV1Api(api_client)
                api_instance.create_namespaced_stateful_set(namespace, utils)
            elif kind == "PersistentVolume" or kind == "PV":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_persistent_volume(utils)
            elif kind == "Secret":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_secret(namespace, utils)
            elif kind == "ConfigMap":
                api_instance = client.CoreV1Api(api_client)
                api_instance.create_namespaced_config_map(namespace, utils)
            elif kind == "Job":
                api_instance = client.BatchV1Api(api_client)
                api_instance.create_namespaced_job(namespace, utils)
            elif kind == "CronJob":
                api_instance = client.BatchV1Api(api_client)
                api_instance.create_namespaced_cron_job(namespace, utils)
            else:
                raise ValueError(f"Unsupported resource type: {kind}")

            QMessageBox.information(self, "Success", f"{kind} applied successfully in namespace {namespace}")
            self.update_resources()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while applying the resource: {str(e)}")

    def update_custom_resources(self, namespaces, model):
        model.clear()
        model.setHorizontalHeaderLabels(["Namespace", "Name", "Kind", "API Version", "Age"])
        row = 0
        for ns in namespaces:
            crds = self.custom_api.list_cluster_custom_resource_definition()
            for crd in crds.items:
                resources = self.custom_api.list_namespaced_custom_object(
                    crd.spec.group, crd.spec.version, ns, crd.spec.names.plural)
                for resource in resources['items']:
                    model.insertRow(row)
                    model.setItem(row, 0, QStandardItem(ns))
                    model.setItem(row, 1, QStandardItem(resource['metadata']['name']))
                    model.setItem(row, 2, QStandardItem(crd.spec.names.kind))
                    model.setItem(row, 3, QStandardItem(f"{crd.spec.group}/{crd.spec.version}"))
                    model.setItem(row, 4, QStandardItem(self.calculate_age(resource['metadata']['creationTimestamp'])))
                    row += 1

    def refresh_events(self):
        try:
            self.events_table.setRowCount(0)
            all_events = []

            # Fetch events from all namespaces
            events = self.v1.list_event_for_all_namespaces(limit=100)  # Adjust the limit as needed
            all_events.extend(events.items)

            # Sort events by last timestamp, most recent first
            all_events.sort(key=lambda e: e.last_timestamp or e.event_time, reverse=True)

            # Take only the top 25 events
            top_events = all_events[:100]

            for event in top_events:
                row = self.events_table.rowCount()
                self.events_table.insertRow(row)
                # Determine the correct timestamp to use and convert to string
                event_time = event.last_timestamp or event.event_time
                event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S') if event_time else ''
                
                self.events_table.setItem(row, 0, QTableWidgetItem(event.involved_object.namespace))
                self.events_table.setItem(row, 1, QTableWidgetItem(event_time_str))
                self.events_table.setItem(row, 2, QTableWidgetItem(event.reason))
                self.events_table.setItem(row, 3, QTableWidgetItem(f"{event.involved_object.kind}/{event.involved_object.name}"))
                self.events_table.setItem(row, 4, QTableWidgetItem(event.message))
            
            self.events_terminal_tabs.setCurrentIndex(0)  # Switch to Events tab
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to refresh events: {str(e)}")
        finally:
            self.refresh_button.setEnabled(True)
            self.refresh_button.setText("Refresh")


    def filter_events(self):
        filter_text = self.events_filter.text().lower()
        for row in range(self.events_table.rowCount()):
            should_show = any(
                filter_text in self.events_table.item(row, col).text().lower()
                for col in range(self.events_table.columnCount())
            )
            self.events_table.setRowHidden(row, not should_show)

    def start_terminal(self):
        self.master_fd, slave_fd = pty.openpty()
        shell = os.environ.get('SHELL', '/bin/bash')  # Changed from /bin/zsh to /bin/bash
        self.terminal_process = subprocess.Popen(
            [shell, '-i'],  # Added '-i' for interactive mode
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            universal_newlines=True
        )
        os.close(slave_fd)

        # Set the terminal to raw mode
        old_settings = termios.tcgetattr(self.master_fd)
        new_settings = termios.tcgetattr(self.master_fd)
        new_settings[3] = new_settings[3] & ~(termios.ICANON | termios.ECHO)
        termios.tcsetattr(self.master_fd, termios.TCSANOW, new_settings)

        self.terminal_timer = QTimer()
        self.terminal_timer.timeout.connect(self.check_terminal_output)
        self.terminal_timer.start(100)

    def send_command(self, command):
        os.write(self.master_fd, (command + '\n').encode())
        # Do not append the command again here, as it causes duplication

    def check_terminal_output(self):
        if self.terminal_process.poll() is not None:
            self.terminal_timer.stop()
            return

        r, _, _ = select.select([self.master_fd], [], [], 0)
        if self.master_fd in r:
            output = os.read(self.master_fd, 1024).decode()
            output = re.sub(r'\x1b\[([0-9]{1,2}(;[0-9]{1,2})?)?[m|K]', '', output)
            self.terminal_widget.append_output(output)

    def clear_initial_messages(self):
        while True:
            r, _, _ = select.select([self.master_fd], [], [], 0)
            if self.master_fd not in r:
                break
            os.read(self.master_fd, 1024)
        os.write(self.master_fd, b"clear\n")
        self.terminal_widget.clear()
        self.terminal_widget.set_prompt_position()
    
    def expand_terminal(self):
        if not self.separate_terminal_window:
            self.separate_terminal_window = QWidget()
            self.separate_terminal_window.setWindowTitle("Terminal")
            layout = QVBoxLayout(self.separate_terminal_window)
            
            layout.addWidget(self.terminal_widget)
            
            rejoin_button = QPushButton("Rejoin Terminal")
            rejoin_button.clicked.connect(self.rejoin_terminal)
            layout.addWidget(rejoin_button)
            
            self.separate_terminal_window.setGeometry(100, 100, 800, 600)
            self.separate_terminal_window.show()
            
            # Remove the terminal tab and disable it
            self.events_terminal_tabs.removeTab(self.events_terminal_tabs.indexOf(self.terminal_tab))
            self.events_terminal_tabs.setTabEnabled(self.events_terminal_tabs.indexOf(self.terminal_tab), False)

    def rejoin_terminal(self):
        if self.separate_terminal_window:
            terminal_layout = self.terminal_tab.layout()
            terminal_layout.addWidget(self.terminal_widget)
            
            self.events_terminal_tabs.addTab(self.terminal_tab, "Terminal")
            self.events_terminal_tabs.setCurrentWidget(self.terminal_tab)
            
            self.separate_terminal_window.close()
            self.separate_terminal_window = None
    
    def set_terminal_node(self, node_name):
        self.terminal_widget.set_node(node_name)

    def ssh_to_node(self, node_name):
        try:
            node = self.v1.read_node(node_name)
            node_ip = next((addr.address for addr in node.status.addresses if addr.type == 'InternalIP'), None)

            if not node_ip:
                QMessageBox.critical(self, "Error", f"Could not find IP address for node {node_name}")
                return

            # Switch to the terminal tab
            terminal_index = self.events_terminal_tabs.indexOf(self.terminal_tab)
            self.events_terminal_tabs.setCurrentIndex(terminal_index)

            # Prompt for username
            username, ok = QInputDialog.getText(self, "SSH Connection", "Enter username:")
            if not ok:
                return

            # Ask user to choose authentication method
            auth_dialog = SSHAuthDialog(self)
            if auth_dialog.exec_() != QDialog.Accepted:
                return
            
            auth_method = auth_dialog.get_auth_method()
            
            if auth_method == "passkey":
                auth_data = self.ssh_key_file
            else:  # password
                password, ok = QInputDialog.getText(self, "SSH Authentication", "Enter password:", QLineEdit.Password)
                if not ok:
                    return
                auth_data = password

            # Start SSH connection in a separate thread
            self.ssh_thread = SSHConnectionThread(node_ip, username, auth_method, auth_data)
            self.ssh_thread.connection_established.connect(self.on_ssh_connected)
            self.ssh_thread.connection_failed.connect(self.on_ssh_failed)
            self.ssh_thread.start()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to initiate SSH connection: {str(e)}")

    def on_ssh_connected(self, ssh_client, ssh_channel, username, auth_method):
        self.terminal_widget.set_ssh_connection(ssh_client, ssh_channel, username, auth_method)
        self.ssh_channel = ssh_channel
        QMessageBox.information(self, "SSH Connection", f"Successfully connected to the node as {username} using {auth_method} authentication.")

    def process_ssh_output(self):
        if hasattr(self, 'ssh_channel') and self.ssh_channel and self.ssh_channel.recv_ready():
            chunk = self.ssh_channel.recv(1024).decode('utf-8')
            self.ssh_output_buffer += chunk
            lines = self.ssh_output_buffer.split('\n')
            for line in lines[:-1]:
                self.terminal_widget.append_output(line + '\n')
            self.ssh_output_buffer = lines[-1]

    def on_ssh_failed(self, error_message):
        QMessageBox.critical(self, "SSH Connection Failed", f"Failed to connect: {error_message}")

    def delete_current_resource(self):
        if self.current_resource_name:
            resource_type = self.get_current_resource_type()
            resource_name = self.current_resource_name
            namespace = self.current_namespace

            # Confirmation dialog
            confirm_msg = f"Are you sure you want to delete the {resource_type} '{resource_name}'"
            if namespace:
                confirm_msg += f" in namespace '{namespace}'"
            confirm_msg += "?"
            
            reply = QMessageBox.question(self, 'Confirm Delete', confirm_msg, 
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            
            if reply == QMessageBox.No:
                return

            try:
                self.delete_resource(resource_type, resource_name, namespace)
                self.update_resources()
                QMessageBox.information(self, "Success", f"{resource_type} '{resource_name}' deleted successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")


    def port_forward_current_service(self):
        if self.current_resource_name and self.get_current_resource_type() == "Services":
            self.port_forward_service(self.current_resource_name, self.current_namespace)
