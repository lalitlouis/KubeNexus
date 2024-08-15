import threading
import csv
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QTableWidget, 
                             QTableWidgetItem, QTextEdit, QSplitter, QLabel, QLineEdit, 
                             QProgressBar, QHeaderView, QComboBox, QPushButton, QDialog,
                             QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QMetaObject, Q_ARG
from PyQt5.QtGui import QColor
from kubernetes import client
import yaml
from datetime import datetime, timezone
import dateutil.parser
from helper_custom_resources_tab.resources_info_dialog import ResourceInfoDialog

class CustomResourcesTab(QWidget):
    resource_loaded_signal = pyqtSignal(object)
    table_update_signal = pyqtSignal(list)
    info_loaded_signal = pyqtSignal(str)
    show_loading_signal = pyqtSignal()
    hide_loading_signal = pyqtSignal()
    cr_deleted_signal = pyqtSignal(str, str)  # Add this line
    cr_delete_failed_signal = pyqtSignal(str)  # Add this line

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.resources = {}
        self.init_ui()
        # Connect signals
        self.cr_deleted_signal.connect(self.cr_deleted_successfully)  # Add this line
        self.cr_delete_failed_signal.connect(self.show_error_message)  

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top controls
        top_controls = QHBoxLayout()
        top_controls.setSpacing(15)

        self.resource_type_combo = QComboBox()
        self.resource_type_combo.addItems([
            "Custom Resources", "Cluster Roles", "Service Accounts", 
            "Roles", "Cluster Role Bindings", "Role Bindings"
        ])
        self.resource_type_combo.currentIndexChanged.connect(self.on_resource_type_changed)
        top_controls.addWidget(QLabel("Resource Type:"))
        top_controls.addWidget(self.resource_type_combo)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setStyleSheet("background-color: #4CAF50; color: white;")
        self.refresh_button.clicked.connect(self.show_event)
        top_controls.addWidget(self.refresh_button)

        self.view_crd_button = QPushButton("View CRD Definition")
        self.view_crd_button.setStyleSheet("background-color: #3498db; color: white;")
        self.view_crd_button.clicked.connect(self.view_crd_definition)
        top_controls.addWidget(self.view_crd_button)

        top_controls.addStretch(1)

        main_layout.addLayout(top_controls)

        # Main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #4a90e2;
                width: 2px;
            }
        """)

        # Left side: Resource list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self.resource_filter = QLineEdit()
        self.resource_filter.setPlaceholderText("Filter resources...")
        self.resource_filter.textChanged.connect(self.filter_resources)
        left_layout.addWidget(self.resource_filter)

        self.resource_list = QListWidget()
        self.resource_list.itemClicked.connect(self.on_resource_selected)
        left_layout.addWidget(self.resource_list)

        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)  # Indeterminate progress
        self.loading_bar.hide()
        left_layout.addWidget(self.loading_bar)

        main_splitter.addWidget(left_widget)

        # Right side: Table and info
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Table controls
        table_controls = QHBoxLayout()
        self.table_filter = QLineEdit()
        self.table_filter.setPlaceholderText("Filter table...")
        self.table_filter.textChanged.connect(self.filter_table)
        table_controls.addWidget(self.table_filter)

        self.download_table_button = QPushButton("Download Table")
        self.download_table_button.setStyleSheet("background-color: #FFD700; color: black;")
        self.download_table_button.clicked.connect(self.download_table)
        table_controls.addWidget(self.download_table_button)

        # Add the Delete CR button
        self.delete_cr_button = QPushButton("Delete CR")
        self.delete_cr_button.setStyleSheet("background-color: #FF6347; color: white;")
        self.delete_cr_button.clicked.connect(self.delete_selected_cr)
        table_controls.addWidget(self.delete_cr_button)

        right_layout.addLayout(table_controls)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Namespace", "Created", "Age"])
        self.table.itemClicked.connect(self.on_table_item_clicked)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        right_layout.addWidget(self.table)

        # Info controls
        info_controls = QHBoxLayout()
        info_controls.addWidget(QLabel("Resource Details:"))
        self.download_info_button = QPushButton("Download Info")
        self.download_info_button.setStyleSheet("background-color: #FFD700; color: black;")
        self.download_info_button.clicked.connect(self.download_info)
        info_controls.addWidget(self.download_info_button)
        right_layout.addLayout(info_controls)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        right_layout.addWidget(self.info_text)

        self.loading_bar_right = QProgressBar()
        self.loading_bar_right.setRange(0, 0)  # Indeterminate progress
        self.loading_bar_right.hide()
        right_layout.addWidget(self.loading_bar_right)

        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([300, 700])  # Adjusted ratio

        main_layout.addWidget(main_splitter)

        # Connect signals
        self.resource_loaded_signal.connect(self.add_resource_to_list)
        self.table_update_signal.connect(self.update_table)
        self.info_loaded_signal.connect(self.update_info)
        self.show_loading_signal.connect(self.loading_bar_right.show)
        self.hide_loading_signal.connect(self.loading_bar_right.hide)

    def delete_selected_cr(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a Custom Resource to delete.")
            return

        row = selected_items[0].row()
        name = self.table.item(row, 0).text()
        namespace = self.table.item(row, 1).text()

        reply = QMessageBox.question(self, 'Delete Custom Resource',
                                    f"Are you sure you want to delete the Custom Resource '{name}'?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.delete_cr(name, namespace)

    def delete_cr(self, name, namespace):
        try:
            self.loading_bar_right.show()
            crd = self.resources[self.resource_list.currentItem().text()]
            custom_api = client.CustomObjectsApi()

            if namespace != 'Cluster-scoped':
                custom_api.delete_namespaced_custom_object(
                    group=crd.spec.group,
                    version=crd.spec.versions[0].name,
                    namespace=namespace,
                    plural=crd.spec.names.plural,
                    name=name
                )
            else:
                custom_api.delete_cluster_custom_object(
                    group=crd.spec.group,
                    version=crd.spec.versions[0].name,
                    plural=crd.spec.names.plural,
                    name=name
                )

            QMessageBox.information(self, "Deletion Successful", f"Custom Resource '{name}' has been deleted successfully.")
            self.show_event()  # Refresh the view after deletion
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error deleting Custom Resource: {str(e)}")
        finally:
            self.loading_bar_right.hide()

    def cr_deleted_successfully(self, name, namespace):
        QMessageBox.information(self, "Deletion Successful", f"Custom Resource '{name}' has been deleted successfully.")
        self.show_event()

    def show_error_message(self, message):
      QMessageBox.critical(self, "Error", f"Error deleting Custom Resource: {message}")

    def on_resource_type_changed(self):
        resource_type = self.resource_type_combo.currentText()
        self.delete_cr_button.setEnabled(resource_type == "Custom Resources")
        self.show_event()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.show_event)

    def download_table(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Table Data", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if fileName:
            with open(fileName, 'w', newline='') as file:
                writer = csv.writer(file)
                headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
                writer.writerow(headers)
                for row in range(self.table.rowCount()):
                    row_data = []
                    for column in range(self.table.columnCount()):
                        item = self.table.item(row, column)
                        if item is not None:
                            row_data.append(item.text())
                        else:
                            row_data.append('')
                    writer.writerow(row_data)
            QMessageBox.information(self, "Download Complete", "Table data has been saved successfully.")

    def download_info(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Resource Info", "", "YAML Files (*.yaml);;All Files (*)", options=options)
        if fileName:
            with open(fileName, 'w') as file:
                file.write(self.info_text.toPlainText())
            QMessageBox.information(self, "Download Complete", "Resource info has been saved successfully.")

    def show_event(self):
        self.resource_list.clear()
        self.table.setRowCount(0)
        self.info_text.clear()
        self.resources.clear()
        self.loading_bar.show()
        self.load_resources()

    def load_resources(self):
        resource_type = self.resource_type_combo.currentText()
        
        def background_load():
            try:
                QMetaObject.invokeMethod(self.loading_bar, "show", Qt.QueuedConnection)
                if resource_type == "Custom Resources":
                    api = client.ApiextensionsV1Api()
                    items = api.list_custom_resource_definition().items
                elif resource_type == "Cluster Roles":
                    api = client.RbacAuthorizationV1Api()
                    items = api.list_cluster_role().items
                elif resource_type == "Service Accounts":
                    api = client.CoreV1Api()
                    items = api.list_service_account_for_all_namespaces().items
                elif resource_type == "Roles":
                    api = client.RbacAuthorizationV1Api()
                    items = api.list_role_for_all_namespaces().items
                elif resource_type == "Cluster Role Bindings":
                    api = client.RbacAuthorizationV1Api()
                    items = api.list_cluster_role_binding().items
                elif resource_type == "Role Bindings":
                    api = client.RbacAuthorizationV1Api()
                    items = api.list_role_binding_for_all_namespaces().items
                else:
                    items = []

                for item in items:
                    self.resources[item.metadata.name] = item
                    self.resource_loaded_signal.emit(item)

            except Exception as e:
                print(f"Error loading resources: {e}")
            finally:
                QMetaObject.invokeMethod(self.loading_bar, "hide", Qt.QueuedConnection)

        threading.Thread(target=background_load, daemon=True).start()

    def add_resource_to_list(self, resource):
        self.resource_list.addItem(resource.metadata.name)

    def filter_resources(self, text):
        for i in range(self.resource_list.count()):
            item = self.resource_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def on_resource_type_changed(self):
        self.show_event()

    def on_resource_selected(self, item):
        resource = self.resources[item.text()]
        self.load_resource_details(resource)

    def load_resource_details(self, resource):
        def background_load():
            try:
                self.show_loading_signal.emit()
                resource_type = self.resource_type_combo.currentText()
                if resource_type == "Custom Resources":
                    custom_api = client.CustomObjectsApi()
                    items = custom_api.list_cluster_custom_object(
                        group=resource.spec.group,
                        version=resource.spec.versions[0].name,
                        plural=resource.spec.names.plural
                    )['items']
                elif resource_type == "Service Accounts":
                    api = client.CoreV1Api()
                    items = api.list_namespaced_service_account(resource.metadata.namespace).items
                else:
                    items = [resource]  # For other types, just use the resource itself

                self.table_update_signal.emit(items)
            except Exception as e:
                print(f"Error loading resource details: {e}")
            finally:
                self.hide_loading_signal.emit()

        self.table.setRowCount(0)
        self.info_text.clear()
        threading.Thread(target=background_load, daemon=True).start()

    def update_table(self, items):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        
        def add_items(start, end):
            for row in range(start, min(end, len(items))):
                item = items[row]
                self.table.setItem(row, 0, QTableWidgetItem(item.get('metadata', {}).get('name', 'N/A')))
                self.table.setItem(row, 1, QTableWidgetItem(item.get('metadata', {}).get('namespace', 'Cluster-scoped')))
                created = item.get('metadata', {}).get('creationTimestamp', 'N/A')
                self.table.setItem(row, 2, QTableWidgetItem(str(created)))
                self.table.setItem(row, 3, QTableWidgetItem(self.calculate_age(created)))

                # Add hyperlinks for related resources
                self.add_hyperlinks(row, item)
            
            if end < len(items):
                QTimer.singleShot(0, lambda: add_items(end, end + 100))
            else:
                self.table.setSortingEnabled(True)

        add_items(0, 100)  # Start with first 100 items

    def add_hyperlinks(self, row, item):
        resource_type = self.resource_type_combo.currentText()
        if resource_type == "Service Accounts":
            secrets = item.get('secrets', [])
            if secrets:
                secret_names = ", ".join([secret.get('name', '') for secret in secrets])
                secret_item = QTableWidgetItem(secret_names)
                secret_item.setForeground(QColor('blue'))
                secret_item.setData(Qt.UserRole, ('Secret', item.get('metadata', {}).get('namespace', '')))
                self.table.setItem(row, 4, secret_item)

    def calculate_age(self, creation_timestamp):
        if creation_timestamp == 'N/A':
            return 'N/A'
        try:
            creation_time = dateutil.parser.isoparse(str(creation_timestamp)).replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - creation_time
            return f"{age.days}d {age.seconds // 3600}h {(age.seconds % 3600) // 60}m"
        except Exception as e:
            print(f"Error calculating age: {e}")
            return "Unknown"

    def on_table_item_clicked(self, item):
        if item.column() == 4:  # Hyperlink column
            resource_type, namespace = item.data(Qt.UserRole)
            resource_name = item.text()
            self.show_resource_info(resource_type, namespace, resource_name)
        else:
            row = item.row()
            name = self.table.item(row, 0).text()
            namespace = self.table.item(row, 1).text()
            self.load_resource_info(name, namespace)

    def show_resource_info(self, resource_type, namespace, name):
        def background_load():
            try:
                if resource_type == 'Secret':
                    api = client.CoreV1Api()
                    resource = api.read_namespaced_secret(name, namespace)
                else:
                    return

                info = yaml.dump(resource.to_dict(), default_flow_style=False)
                dialog = ResourceInfoDialog(f"{resource_type}: {name}", info, self)
                dialog.exec_()
            except Exception as e:
                print(f"Error loading resource info: {e}")

        threading.Thread(target=background_load, daemon=True).start()

    def load_resource_info(self, name, namespace):
        def background_load():
            try:
                resource_type = self.resource_type_combo.currentText()
                if resource_type == "Custom Resources":
                    crd = self.resources[self.resource_list.currentItem().text()]
                    custom_api = client.CustomObjectsApi()
                    if namespace != 'Cluster-scoped':
                        resource = custom_api.get_namespaced_custom_object(
                            group=crd.spec.group,
                            version=crd.spec.versions[0].name,
                            namespace=namespace,
                            plural=crd.spec.names.plural,
                            name=name
                        )
                    else:
                        resource = custom_api.get_cluster_custom_object(
                            group=crd.spec.group,
                            version=crd.spec.versions[0].name,
                            plural=crd.spec.names.plural,
                            name=name
                        )
                else:
                    resource = self.resources[name]

                # Extract only relevant information
                resource_dict = resource if isinstance(resource, dict) else resource.to_dict()
                relevant_info = {
                    "labels": resource_dict.get("metadata", {}).get("labels", {}),
                    "spec": resource_dict.get("spec", {})
                }

                self.info_loaded_signal.emit(yaml.dump(relevant_info, default_flow_style=False))
            except Exception as e:
                print(f"Error loading resource info: {e}")

        self.info_text.clear()
        threading.Thread(target=background_load, daemon=True).start()

    def update_info(self, info):
        self.info_text.setPlainText(info)

    def filter_table(self, text):
        for row in range(self.table.rowCount()):
            should_show = any(
                text.lower() in (self.table.item(row, col).text().lower() if self.table.item(row, col) else "")
                for col in range(self.table.columnCount())
            )
            self.table.setRowHidden(row, not should_show)

    def view_crd_definition(self):
        try:
            crd_name = self.resource_list.currentItem().text()
            crd = self.resources[crd_name]
            crd_definition = yaml.dump(crd.to_dict(), default_flow_style=False)
            dialog = ResourceInfoDialog(f"CRD Definition: {crd_name}", crd_definition, self)
            dialog.exec_()
        except Exception as e:
            print(f"Error loading CRD definition: {e}")
