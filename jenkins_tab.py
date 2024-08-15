import base64
import os
import json
from cryptography.fernet import Fernet
import requests
from datetime import datetime
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QTabWidget, QScrollArea, QFormLayout,
                             QDialog, QDialogButtonBox, QMessageBox, QTableWidget,
                             QTableWidgetItem, QTextEdit, QComboBox, QGroupBox,
                             QHeaderView, QFileDialog, QSplitter)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QFont, QColor, QTextCursor

# Disable SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class JenkinsTab(QWidget):
    build_triggered = pyqtSignal(int)  # Signal to emit when a build is triggered

    def __init__(self, parent=None):
        super().__init__(parent)
        self.username = None
        self.api_token = None
        self.jenkins_url = "https://lr1-ez-jenkins.mip.storage.hpecorp.net:8443/"
        self.init_ui()
        self.load_credentials()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        
        # Left side tabs
        left_tab_widget = QTabWidget()
        left_tab_widget.setTabPosition(QTabWidget.North)
        
        # Build with Parameters tab
        build_params_widget = QWidget()
        build_params_layout = QVBoxLayout(build_params_widget)
        
        # Add build button at the top left
        self.build_button = QPushButton("Build")
        self.build_button.clicked.connect(self.trigger_build)
        build_params_layout.addWidget(self.build_button, alignment=Qt.AlignLeft)
        
        # Create two columns for parameters
        params_layout = QHBoxLayout()
        
        self.params_form_left = QFormLayout()
        self.params_form_right = QVBoxLayout()  # Changed to QVBoxLayout for IP widget
        
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_content = QWidget()
        left_content.setLayout(self.params_form_left)
        left_scroll.setWidget(left_content)
        
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_content = QWidget()
        right_content.setLayout(self.params_form_right)
        right_scroll.setWidget(right_content)
        
        params_layout.addWidget(left_scroll)
        params_layout.addWidget(right_scroll)
        
        build_params_layout.addLayout(params_layout)
                
        left_tab_widget.addTab(build_params_widget, "Build")
        
        
        # Build History tab
        build_history_widget = QWidget()
        build_history_layout = QVBoxLayout(build_history_widget)
        self.build_history_table = QTableWidget()
        self.build_history_table.setColumnCount(5)
        self.build_history_table.setHorizontalHeaderLabels(["Build #", "Status", "Duration", "Timestamp", "User"])
        self.build_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.build_history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.build_history_table.setSelectionMode(QTableWidget.SingleSelection)
        self.build_history_table.itemClicked.connect(self.show_build_details)
        build_history_layout.addWidget(self.build_history_table)
        left_tab_widget.addTab(build_history_widget, "Build History")
        
        # Right side build details
        right_layout = QVBoxLayout()
        
        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search logs...")
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search_logs)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        right_layout.addLayout(search_layout)
        
        self.build_details_widget = QTabWidget()
        self.build_info_tab = QTextEdit()
        self.console_output_tab = QTextEdit()
        self.build_params_tab = QTextEdit()
        self.build_details_widget.addTab(self.build_info_tab, "Build Information")
        self.build_details_widget.addTab(self.console_output_tab, "Console Output")
        self.build_details_widget.addTab(self.build_params_tab, "Build Parameters")
        right_layout.addWidget(self.build_details_widget)
        
        # Buttons for download, stream, and rebuild
        button_layout = QHBoxLayout()
        self.download_button = QPushButton("Download Logs")
        self.stream_button = QPushButton("Stream Logs")
        # Modify the rebuild button creation
        self.rebuild_button = QPushButton("Rebuild")
        # Add this after creating the build_history_layout
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_data)
        self.rebuild_button.clicked.connect(self.confirm_rebuild)
        self.rebuild_button.setEnabled(False)  # Disable by default
        button_layout.addWidget(self.rebuild_button)
        self.download_button.clicked.connect(self.download_logs)
        self.stream_button.clicked.connect(self.stream_logs)
        self.rebuild_button.clicked.connect(self.rebuild)
        button_layout.addWidget(self.download_button)
        button_layout.addWidget(self.stream_button)
        button_layout.addWidget(self.rebuild_button)
        button_layout.addWidget(self.refresh_button)
        right_layout.addLayout(button_layout)
        
        # Main splitter
        splitter = QSplitter(Qt.Vertical)  # Change to Vertical split
        splitter.addWidget(left_tab_widget)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        splitter.setSizes([int(self.height() * 0.4), int(self.height() * 0.6)])

        main_layout.addWidget(splitter)

    def refresh_data(self):
        self.fetch_build_history()
        selected_items = self.build_history_table.selectedItems()
        if selected_items:
            build_number = self.build_history_table.item(selected_items[0].row(), 0).text()
            self.fetch_build_details(build_number)
        else:
            # Clear the details panels if no build is selected
            self.build_info_tab.clear()
            self.console_output_tab.clear()
            self.build_params_tab.clear()

    def load_credentials(self):
        key_file = os.path.expanduser('~/.jenkins_key')
        cred_file = os.path.expanduser('~/.jenkins_cred')
        
        if os.path.exists(key_file) and os.path.exists(cred_file):
            try:
                with open(key_file, 'rb') as f:
                    key = f.read()
                fernet = Fernet(key)
                with open(cred_file, 'rb') as f:
                    encrypted_data = f.read()
                decrypted_data = fernet.decrypt(encrypted_data)
                cred = json.loads(decrypted_data.decode())
                self.username = cred['username']
                self.api_token = cred['api_token']
                self.fetch_jenkins_data()
            except Exception as e:
                print(f"Error loading credentials: {str(e)}")
                self.show_credentials_dialog()
        else:
            self.show_credentials_dialog()
    
    def save_credentials(self):
        key = Fernet.generate_key()
        fernet = Fernet(key)
        cred = {'username': self.username, 'api_token': self.api_token}
        encrypted_data = fernet.encrypt(json.dumps(cred).encode())
        
        key_file = os.path.expanduser('~/.jenkins_key')
        cred_file = os.path.expanduser('~/.jenkins_cred')
        
        with open(key_file, 'wb') as f:
            f.write(key)
        with open(cred_file, 'wb') as f:
            f.write(encrypted_data)

    def show_credentials_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Jenkins Credentials")
        layout = QVBoxLayout(dialog)

        form_layout = QFormLayout()
        self.username_input = QLineEdit(dialog)
        self.api_token_input = QLineEdit(dialog)
        self.api_token_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("Username:", self.username_input)
        form_layout.addRow("API Token:", self.api_token_input)
        layout.addLayout(form_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        result = dialog.exec_()
        if result == QDialog.Accepted:
            self.username = self.username_input.text()
            self.api_token = self.api_token_input.text()
            if not self.username or not self.api_token:
                QMessageBox.warning(self, "Input Error", "Username and API Token are required.")
                self.show_credentials_dialog()
            else:
                self.fetch_jenkins_data()
        else:
            # User cancelled, you might want to handle this case
            pass

    def fetch_jenkins_data(self):
        self.fetch_build_parameters()
        self.fetch_build_history()

    def fetch_build_parameters(self):
        try:
            response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/api/json?tree=actions[parameterDefinitions[name,type,choices,defaultValue]]")
            if response.status_code == 200:
                data = response.json()
                param_defs = None
                for action in data.get('actions', []):
                    if 'parameterDefinitions' in action:
                        param_defs = action['parameterDefinitions']
                        break
                
                if param_defs:
                    self.create_parameter_inputs(param_defs)
                else:
                    print("No parameter definitions found")
            else:
                print(f"Failed to fetch build parameters: {response.status_code}")
        except Exception as e:
            print(f"Error fetching build parameters: {str(e)}")

    def create_parameter_inputs(self, param_defs):
        while self.params_form_left.rowCount() > 0:
            self.params_form_left.removeRow(0)
        
        for widget in self.params_form_right.children():
            if isinstance(widget, QWidget):
                widget.deleteLater()

        required_params = [
            'OS', 'check_os_blocking_file', 'add_os_blocking_file', 
            'NetworkManager', 'selinux', 'sudo', 'start_firewall'
        ]
        
        for param in param_defs:
            if param['name'] in required_params:
                if param['type'] == 'ChoiceParameterDefinition':
                    input_widget = QComboBox()
                    input_widget.addItems(param['choices'])
                else:
                    input_widget = QLineEdit(param.get('defaultValue', ''))
                
                self.params_form_left.addRow(QLabel(param['name']), input_widget)
            elif param['name'] == 'host_public_IPs':
                self.create_ip_input()

    def create_ip_input(self):
        ip_widget = QWidget()
        ip_layout = QVBoxLayout(ip_widget)
        
        label = QLabel("Host Public IPs")
        ip_layout.addWidget(label)
        
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Enter IP address")
        self.ip_input.returnPressed.connect(self.add_ip_address)
        ip_layout.addWidget(self.ip_input)
        
        self.ip_list_widget = QWidget()
        self.ip_list_layout = QVBoxLayout(self.ip_list_widget)
        ip_layout.addWidget(self.ip_list_widget)
        
        self.params_form_right.addWidget(ip_widget)

    def add_ip_address(self):
        ip = self.ip_input.text().strip()
        if ip:
            ip_row = QHBoxLayout()
            ip_label = QLabel(ip)
            remove_button = QPushButton("Remove")
            remove_button.clicked.connect(lambda: self.remove_ip_address(ip_row))
            
            ip_row.addWidget(ip_label)
            ip_row.addWidget(remove_button)
            
            self.ip_list_layout.addLayout(ip_row)
            self.ip_input.clear()

    def remove_ip_address(self, ip_row):
        while ip_row.count():
            item = ip_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.ip_list_layout.removeItem(ip_row)

    def fetch_build_history(self):
        try:
            # Store the currently selected build number, if any
            current_build = None
            selected_items = self.build_history_table.selectedItems()
            if selected_items:
                current_build = self.build_history_table.item(selected_items[0].row(), 0).text()

            response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/api/json?tree=builds[number,result,duration,timestamp,actions[causes[userName]]]")
            if response.status_code == 200:
                builds = response.json().get('builds', [])
                self.build_history_table.setRowCount(len(builds))
                for i, build in enumerate(builds):
                    self.build_history_table.setItem(i, 0, QTableWidgetItem(str(build['number'])))
                    self.build_history_table.setItem(i, 1, QTableWidgetItem(build.get('result', 'IN PROGRESS')))
                    duration = build['duration'] / 3600000  # Convert to hours
                    self.build_history_table.setItem(i, 2, QTableWidgetItem(f"{duration:.2f} hours"))
                    timestamp = datetime.fromtimestamp(build['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    self.build_history_table.setItem(i, 3, QTableWidgetItem(timestamp))
                    user = next((cause.get('userName', 'N/A') for action in build['actions'] if 'causes' in action for cause in action['causes'] if 'userName' in cause), 'N/A')
                    self.build_history_table.setItem(i, 4, QTableWidgetItem(user))

                # Reselect the previously selected build, if it still exists
                if current_build:
                    items = self.build_history_table.findItems(current_build, Qt.MatchExactly)
                    if items:
                        self.build_history_table.selectRow(items[0].row())

            else:
                print(f"Failed to fetch build history: {response.status_code}")
        except Exception as e:
            print(f"Error fetching build history: {str(e)}")

    def show_build_details(self, item):
        build_number = self.build_history_table.item(item.row(), 0).text()
        user = self.build_history_table.item(item.row(), 4).text()
        
        # Enable rebuild button only if the current user matches the build user
        self.rebuild_button.setEnabled(user == self.username)
        
        self.fetch_build_details(build_number)
    
    def confirm_rebuild(self):
        selected_items = self.build_history_table.selectedItems()
        if selected_items:
            build_number = self.build_history_table.item(selected_items[0].row(), 0).text()
            reply = QMessageBox.question(self, 'Confirm Rebuild', 
                                         f"Are you sure you want to rebuild job #{build_number}?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.rebuild(build_number)

    def fetch_build_details(self, build_number):
        try:
            response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/{build_number}/api/json")
            if response.status_code == 200:
                build_data = response.json()
                self.build_info_tab.setText(f"Build #{build_number}\nResult: {build_data.get('result', 'IN PROGRESS')}\nDuration: {build_data['duration'] / 1000:.2f} seconds")
                self.fetch_console_output(build_number)
                self.build_params_tab.setText("\n".join([f"{a['name']}: {a.get('value', '')}" for a in build_data['actions'] if 'name' in a]))
                
                # Update the build status in the table
                for row in range(self.build_history_table.rowCount()):
                    if self.build_history_table.item(row, 0).text() == str(build_number):
                        self.build_history_table.setItem(row, 1, QTableWidgetItem(build_data.get('result', 'IN PROGRESS')))
                        break
            else:
                print(f"Failed to fetch build details: {response.status_code}")
        except Exception as e:
            print(f"Error fetching build details: {str(e)}")
    
    def stream_logs(self):
        # Implement log streaming functionality
        QMessageBox.information(self, "Stream Logs", "Log streaming functionality not implemented yet.")

    def pre_fill_build_params(self, params):
        for form in [self.params_form_left, self.params_form_right]:
            for i in range(form.rowCount()):
                label_item = form.itemAt(i, QFormLayout.LabelRole)
                field_item = form.itemAt(i, QFormLayout.FieldRole)
                if label_item and field_item:
                    label = label_item.widget().text()
                    field = field_item.widget()
                    param_value = next((param['value'] for param in params if param['name'] == label), None)
                    if param_value is not None:
                        if isinstance(field, QComboBox):
                            index = field.findText(param_value)
                            if index >= 0:
                                field.setCurrentIndex(index)
                        elif isinstance(field, QGroupBox):  # For host_public_IPs
                            ips = param_value.split()
                            for j, ip in enumerate(ips):
                                if j < len(self.ip_inputs):
                                    self.ip_inputs[j].setText(ip)
                                else:
                                    self.add_ip_input()
                                    self.ip_inputs[-1].setText(ip)
                        else:
                            field.setText(param_value)

    def fetch_console_output(self, build_number):
        try:
            response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/{build_number}/consoleText")
            if response.status_code == 200:
                self.console_output_tab.setText(response.text)
            else:
                print(f"Failed to fetch console output: {response.status_code}")
        except Exception as e:
            print(f"Error fetching console output: {str(e)}")
    
    def rebuild(self, build_number):
        response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/{build_number}/api/json")
        if response.status_code == 200:
            build_data = response.json()
            params = next((action['parameters'] for action in build_data['actions'] if 'parameters' in action), [])
            self.pre_fill_build_params(params)
            self.nav_tabs.setCurrentWidget(self.build_params_widget)  # Switch to Build with Parameters tab
    
    def download_logs(self):
        selected_items = self.build_history_table.selectedItems()
        if selected_items:
            build_number = self.build_history_table.item(selected_items[0].row(), 0).text()
            response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/{build_number}/consoleText")
            if response.status_code == 200:
                file_name, _ = QFileDialog.getSaveFileName(self, "Save Log File", f"build_{build_number}_log.txt", "Text Files (*.txt)")
                if file_name:
                    with open(file_name, 'w') as f:
                        f.write(response.text)
                    QMessageBox.information(self, "Download Complete", "Log file has been downloaded successfully.")
            else:
                QMessageBox.warning(self, "Download Failed", "Failed to download log file.")

    def trigger_build(self):
        reply = QMessageBox.question(self, 'Confirm Build', 
                                    "Are you sure you want to trigger this build?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            params = {}
            
            # Handle left form (QFormLayout)
            for i in range(self.params_form_left.rowCount()):
                label_item = self.params_form_left.itemAt(i, QFormLayout.LabelRole)
                field_item = self.params_form_left.itemAt(i, QFormLayout.FieldRole)
                if label_item and field_item:
                    label = label_item.widget().text()
                    field = field_item.widget()
                    if isinstance(field, QComboBox):
                        value = field.currentText()
                    else:
                        value = field.text()
                    params[label] = value
            
            # Handle right form (QVBoxLayout) - specifically for IP addresses
            ip_addresses = []
            for i in range(self.ip_list_layout.count()):
                item = self.ip_list_layout.itemAt(i)
                if item.layout():
                    ip_label = item.layout().itemAt(0).widget()
                    if isinstance(ip_label, QLabel):
                        ip_addresses.append(ip_label.text())
            
            params['host_public_IPs'] = " ".join(ip_addresses)

            try:
                response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/buildWithParameters", method="POST", data=params)
                if response.status_code == 201:
                    QMessageBox.information(self, "Build Triggered", "Build has been triggered successfully.")
                    self.fetch_build_history()
                    self.build_triggered.emit(response.json()['number'])
                else:
                    QMessageBox.warning(self, "Build Failed", f"Failed to trigger build: {response.status_code}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error triggering build: {str(e)}")
    
    def stream_logs(self):
        selected_items = self.build_history_table.selectedItems()
        if selected_items:
            build_number = self.build_history_table.item(selected_items[0].row(), 0).text()
            self.stream_dialog = QDialog(self)
            self.stream_dialog.setWindowTitle(f"Streaming Logs for Build #{build_number}")
            layout = QVBoxLayout(self.stream_dialog)
            self.stream_output = QTextEdit()
            self.stream_output.setReadOnly(True)
            layout.addWidget(self.stream_output)
            self.stream_dialog.resize(600, 400)
            self.stream_dialog.show()
            
            self.stream_timer = QTimer()
            self.stream_timer.timeout.connect(lambda: self.update_stream(build_number))
            self.stream_timer.start(5000)  # Update every 5 seconds
    
    def update_stream(self, build_number):
        response = self.jenkins_request(f"{self.jenkins_url}job/OS_install/{build_number}/logText/progressiveText")
        if response.status_code == 200:
            self.stream_output.append(response.text)
            self.stream_output.moveCursor(QTextCursor.End)
            if 'Finished: ' in response.text:
                self.stream_timer.stop()
    
    def search_logs(self):
        search_text = self.search_input.text()
        if search_text:
            cursor = self.console_output_tab.textCursor()
            format = QTextCharFormat()
            format.setBackground(QColor(255, 255, 0))
            cursor.beginEditBlock()
            self.console_output_tab.moveCursor(QTextCursor.Start)
            while self.console_output_tab.find(search_text):
                cursor.mergeCharFormat(format)
            cursor.endEditBlock()

    def jenkins_request(self, url, method="GET", data=None):
        credentials = base64.b64encode(f"{self.username}:{self.api_token}".encode()).decode()
        headers = {
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        if method == "GET":
            return requests.get(url, headers=headers, verify=False, timeout=30)
        elif method == "POST":
            return requests.post(url, headers=headers, data=data, verify=False, timeout=30)
