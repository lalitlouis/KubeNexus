from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QStyle,
                             QLabel, QMessageBox, QPushButton, QFileSystemModel, QTreeView, QHeaderView, QCheckBox)
from PyQt5.QtCore import Qt, QDir
from PyQt5.QtGui import QIcon
import os
import stat
from datetime import datetime

class SSHFileBrowser(QDialog):
    def __init__(self, ssh_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH File Browser")
        self.setGeometry(100, 100, 1200, 600)
        
        layout = QHBoxLayout(self)
        
        # Local file browser
        local_layout = QVBoxLayout()
        self.local_path_label = QLabel(os.path.expanduser("~"))
        local_layout.addWidget(self.local_path_label)
        
        self.local_model = QFileSystemModel()
        self.local_model.setRootPath(QDir.rootPath())
        self.local_tree = QTreeView()
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(os.path.expanduser("~")))
        self.local_tree.setColumnWidth(0, 250)
        self.local_tree.setSortingEnabled(True)
        self.local_tree.doubleClicked.connect(self.on_local_item_double_clicked)
        local_layout.addWidget(self.local_tree)
        
        local_nav_layout = QHBoxLayout()
        self.local_home_button = QPushButton("Home")
        self.local_up_button = QPushButton("Up")
        self.local_show_hidden = QCheckBox("Show Hidden Files")
        local_nav_layout.addWidget(self.local_home_button)
        local_nav_layout.addWidget(self.local_up_button)
        local_nav_layout.addWidget(self.local_show_hidden)
        local_layout.addLayout(local_nav_layout)
        
        self.local_home_button.clicked.connect(self.local_go_home)
        self.local_up_button.clicked.connect(self.local_go_up)
        self.local_show_hidden.stateChanged.connect(self.toggle_local_hidden_files)
        
        layout.addLayout(local_layout)
        
        # Transfer buttons
        transfer_layout = QVBoxLayout()
        self.transfer_to_ssh = QPushButton("->")
        self.transfer_to_local = QPushButton("<-")
        transfer_layout.addStretch()
        transfer_layout.addWidget(self.transfer_to_ssh)
        transfer_layout.addWidget(self.transfer_to_local)
        transfer_layout.addStretch()
        
        self.transfer_to_ssh.clicked.connect(self.transfer_to_ssh_clicked)
        self.transfer_to_local.clicked.connect(self.transfer_to_local_clicked)
        
        layout.addLayout(transfer_layout)
        
        # SSH file browser
        ssh_layout = QVBoxLayout()
        self.ssh_path_label = QLabel("/")
        ssh_layout.addWidget(self.ssh_path_label)
        
        self.ssh_tree = QTreeWidget()
        self.ssh_tree.setHeaderLabels(["Name", "Size", "Date Modified", "Permissions"])
        self.ssh_tree.itemDoubleClicked.connect(self.on_ssh_item_double_clicked)
        self.ssh_tree.setSortingEnabled(True)
        self.ssh_tree.header().setSectionsClickable(True)
        self.ssh_tree.header().sectionClicked.connect(self.sort_ssh_tree)
        ssh_layout.addWidget(self.ssh_tree)
        
        ssh_nav_layout = QHBoxLayout()
        self.ssh_home_button = QPushButton("Home")
        self.ssh_up_button = QPushButton("Up")
        self.ssh_show_hidden = QCheckBox("Show Hidden Files")
        ssh_nav_layout.addWidget(self.ssh_home_button)
        ssh_nav_layout.addWidget(self.ssh_up_button)
        ssh_nav_layout.addWidget(self.ssh_show_hidden)
        ssh_layout.addLayout(ssh_nav_layout)
        
        self.ssh_home_button.clicked.connect(self.ssh_go_home)
        self.ssh_up_button.clicked.connect(self.ssh_go_up)
        self.ssh_show_hidden.stateChanged.connect(self.toggle_ssh_hidden_files)
        
        layout.addLayout(ssh_layout)
        
        self.ssh_client = ssh_client
        self.sftp_client = self.ssh_client.open_sftp()
        self.current_ssh_path = '/'
        
        self.sort_column = 0
        self.sort_order = Qt.AscendingOrder
        
        self.load_ssh_files(self.current_ssh_path)
    
    def toggle_local_hidden_files(self, state):
        if state == Qt.Checked:
            self.local_model.setFilter(QDir.AllEntries | QDir.Hidden | QDir.System)
        else:
            self.local_model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        self.local_tree.setRootIndex(self.local_model.index(self.local_model.rootPath()))

    def toggle_ssh_hidden_files(self, state):
        self.load_ssh_files(self.current_ssh_path)


    def transfer_to_ssh_clicked(self):
        selected_indexes = self.local_tree.selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(self, "No Selection", "Please select a file to transfer.")
            return
        
        file_path = self.local_model.filePath(selected_indexes[0])
        remote_path = os.path.join(self.current_ssh_path, os.path.basename(file_path))
        
        try:
            self.sftp_client.put(file_path, remote_path)
            self.load_ssh_files(self.current_ssh_path)  # Refresh SSH view
            QMessageBox.information(self, "File Transfer", f"File transferred successfully to {remote_path}")
        except Exception as e:
            QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")
    
    def transfer_to_local_clicked(self):
        selected_items = self.ssh_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a file to transfer.")
            return
        
        remote_path = selected_items[0].data(0, Qt.UserRole)
        local_path = os.path.join(self.local_model.filePath(self.local_tree.rootIndex()), os.path.basename(remote_path))
        
        try:
            self.sftp_client.get(remote_path, local_path)
            self.local_model.setRootPath(self.local_model.filePath(self.local_tree.rootIndex()))  # Refresh local view
            QMessageBox.information(self, "File Transfer", f"File transferred successfully to {local_path}")
        except Exception as e:
            QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")

    def local_go_home(self):
        home_path = os.path.expanduser("~")
        self.local_tree.setRootIndex(self.local_model.index(home_path))
        self.local_path_label.setText(home_path)

    def local_go_up(self):
        current_index = self.local_tree.rootIndex()
        parent_index = current_index.parent()
        if parent_index.isValid():
            self.local_tree.setRootIndex(parent_index)
            self.local_path_label.setText(self.local_model.filePath(parent_index))

    def on_local_item_double_clicked(self, index):
        if self.local_model.isDir(index):
            self.local_tree.setRootIndex(index)
            self.local_path_label.setText(self.local_model.filePath(index))

    def ssh_go_home(self):
        self.load_ssh_files('/')

    def ssh_go_up(self):
        parent_path = os.path.dirname(self.current_ssh_path)
        if parent_path != self.current_ssh_path:
            self.load_ssh_files(parent_path)

    def load_ssh_files(self, path):
        self.ssh_tree.clear()
        try:
            for entry in self.sftp_client.listdir_attr(path):
                if not self.ssh_show_hidden.isChecked() and entry.filename.startswith('.'):
                    continue
                item = QTreeWidgetItem([
                    entry.filename,
                    str(entry.st_size),
                    datetime.fromtimestamp(entry.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    oct(entry.st_mode)[-4:]
                ])
                item.setData(0, Qt.UserRole, os.path.join(path, entry.filename))
                if stat.S_ISDIR(entry.st_mode):
                    item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                else:
                    item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                self.ssh_tree.addTopLevelItem(item)
            self.current_ssh_path = path
            self.ssh_path_label.setText(path)
            self.ssh_tree.sortItems(self.sort_column, self.sort_order)
        except Exception as e:
            QMessageBox.warning(self, "SSH File List Error", f"Could not list SSH files: {str(e)}")
            if path != '/':
                self.load_ssh_files('/')

    def on_ssh_item_double_clicked(self, item, column):
        path = item.data(0, Qt.UserRole)
        try:
            if stat.S_ISDIR(self.sftp_client.stat(path).st_mode):
                self.load_ssh_files(path)
        except Exception as e:
            QMessageBox.warning(self, "SSH Navigation Error", f"Could not navigate to directory: {str(e)}")

    def closeEvent(self, event):
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
        super().closeEvent(event)

    def transfer_file(self, file_path, direction):
        if direction == 'local_to_ssh':
            local_path = file_path
            remote_path = os.path.join(self.current_ssh_path, os.path.basename(file_path))
            try:
                self.sftp_client.put(local_path, remote_path)
                self.load_ssh_files(self.current_ssh_path)  # Refresh SSH view
                QMessageBox.information(self, "File Transfer", f"File transferred successfully to {remote_path}")
            except Exception as e:
                QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")
        elif direction == 'ssh_to_local':
            remote_path = file_path
            local_path = os.path.join(self.local_model.filePath(self.local_tree.rootIndex()), os.path.basename(file_path))
            try:
                self.sftp_client.get(remote_path, local_path)
                self.local_model.setRootPath(self.local_model.filePath(self.local_tree.rootIndex()))  # Refresh local view
                QMessageBox.information(self, "File Transfer", f"File transferred successfully to {local_path}")
            except Exception as e:
                QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")
    
    def transfer_file(self, file_path, direction):
        if direction == 'local_to_ssh':
            local_path = file_path
            remote_path = os.path.join(self.current_ssh_path, os.path.basename(file_path))
            try:
                self.sftp_client.put(local_path, remote_path)
                self.load_ssh_files(self.current_ssh_path)  # Refresh SSH view
                QMessageBox.information(self, "File Transfer", f"File transferred successfully to {remote_path}")
            except Exception as e:
                QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")
        elif direction == 'ssh_to_local':
            remote_path = file_path
            local_path = os.path.join(self.local_model.filePath(self.local_tree.rootIndex()), os.path.basename(file_path))
            try:
                self.sftp_client.get(remote_path, local_path)
                self.local_model.setRootPath(self.local_model.filePath(self.local_tree.rootIndex()))  # Refresh local view
                QMessageBox.information(self, "File Transfer", f"File transferred successfully to {local_path}")
            except Exception as e:
                QMessageBox.warning(self, "File Transfer Error", f"Could not transfer file: {str(e)}")

    def sort_ssh_tree(self, column):
        print(f"Sorting column: {column}")  # Debug print
        if column == self.sort_column:
            self.sort_order = Qt.DescendingOrder if self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.sort_order = Qt.AscendingOrder
        
        self.sort_column = column
        print(f"New sort order: {'Descending' if self.sort_order == Qt.DescendingOrder else 'Ascending'}")  # Debug print
        self.ssh_tree.sortItems(column, self.sort_order)