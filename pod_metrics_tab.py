import csv
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableView, 
    QLineEdit, QFileDialog, QMessageBox, QDialog, QTextEdit, QHeaderView,
    QFormLayout, QDialogButtonBox, QApplication, QComboBox, QProgressBar, QAbstractItemView
)
from PyQt5.QtGui import QFont, QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSortFilterProxyModel, QAbstractTableModel
from prometheus_api_client import PrometheusConnect
from kubernetes import client
import traceback
import logging
from PyQt5.QtWidgets import QSplitter, QWidget, QVBoxLayout, QLabel, QScrollArea
from helper_github_insights_tab.loading_overlay import LoadingOverlay


logging.basicConfig(level=logging.INFO)



class TotalRowTableModel(QAbstractTableModel):
    def __init__(self, data, headers, parent=None):
        super().__init__(parent)
        self._data = data
        self._headers = headers
        self._total_row = ['Total'] + ['0'] * (len(headers) - 1)
        self._filtered_data = data

    def rowCount(self, parent=None):
        return len(self._filtered_data) + 1  # +1 for the total row

    def columnCount(self, parent=None):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.DisplayRole:
            if index.row() == 0:
                return self._total_row[index.column()]
            return self._filtered_data[index.row() - 1][index.column()]

        if role == Qt.FontRole and index.row() == 0:
            font = QFont()
            font.setBold(True)
            return font

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._headers[section]
        return None

    def update_total_row(self):
        self._total_row = ['Total'] + [''] * (len(self._headers) - 1)
        for row in self._filtered_data:
            for col in [3, 4, 6, 7]:  # Only sum CPU request, CPU limit, Mem request, Mem limit
                try:
                    self._total_row[col] = f"{float(self._total_row[col] or 0) + float(row[col].rstrip('%')):.2f}"
                except ValueError:
                    pass
        self.dataChanged.emit(self.index(0, 0), self.index(0, self.columnCount() - 1))

    def update_data(self, new_data):
        self.beginResetModel()
        self._data = new_data
        self._filtered_data = new_data
        self.update_total_row()
        self.endResetModel()

    def set_filtered_data(self, filtered_data):
        self.beginResetModel()
        self._filtered_data = filtered_data
        self.update_total_row()
        self.endResetModel()

class SortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)

    def lessThan(self, left, right):
        # Always keep the total row (index 0) at the top
        if left.row() == 0 or right.row() == 0:
            return left.row() < right.row()

        left_data = self.sourceModel().data(left)
        right_data = self.sourceModel().data(right)
        
        # Handle percentage values
        if isinstance(left_data, str) and '%' in left_data:
            return float(left_data.rstrip('%')) < float(right_data.rstrip('%'))
        
        try:
            return float(left_data) < float(right_data)
        except ValueError:
            return left_data < right_data

    def filterAcceptsRow(self, source_row, source_parent):
        # Always show the total row
        if source_row == 0:
            return True
        return super().filterAcceptsRow(source_row, source_parent)
class PodMetricsWorker(QThread):
    update_signal = pyqtSignal(list)

    def __init__(self, prom):
        super().__init__()
        self.prom = prom

    def run(self):
        try:
            queries = {
                'cpu_usage': "sum(rate(container_cpu_usage_seconds_total{container!=''}[5m])) by (namespace, pod)",
                'mem_usage': "sum(container_memory_working_set_bytes{container!=''}) by (namespace, pod)",
                'cpu_limits': "sum(kube_pod_container_resource_limits{resource='cpu'}) by (namespace, pod)",
                'mem_limits': "sum(kube_pod_container_resource_limits{resource='memory'}) by (namespace, pod)",
                'container_ready': "kube_pod_container_status_ready",
                'pod_owner': "kube_pod_owner",
                'cpu_requests': "sum(kube_pod_container_resource_requests{resource='cpu'}) by (namespace, pod)",
                'mem_requests': "sum(kube_pod_container_resource_requests{resource='memory'}) by (namespace, pod)",
            }

            results = {}
            for name, query in queries.items():
                results[name] = self.prom.custom_query(query)

            pod_data = {}
            for name, result in results.items():
                for item in result:
                    metric = item['metric']
                    namespace = metric.get('namespace')
                    pod_name = metric.get('pod')
                    
                    if not namespace or not pod_name:
                        continue
                    
                    if (namespace, pod_name) not in pod_data:
                        pod_data[(namespace, pod_name)] = {'namespace': namespace, 'name': pod_name}
                    
                    value = float(item['value'][1])
                    
                    if name == 'cpu_usage':
                        pod_data[(namespace, pod_name)]['cpu_usage'] = value
                    elif name == 'mem_usage':
                        pod_data[(namespace, pod_name)]['mem_usage'] = value / (1024 * 1024 * 1024)  # Convert to GB
                    elif name == 'container_ready':
                        pod_data[(namespace, pod_name)]['status'] = 'Ready' if value == 1 else 'Not Ready'
                    elif name == 'pod_owner':
                        controller_type = metric.get('owner_kind', 'Unknown')
                        pod_data[(namespace, pod_name)]['controller_type'] = controller_type
                        pod_data[(namespace, pod_name)]['controller_name'] = metric.get('owner_name', 'Unknown')
                        # Ignore readiness for Jobs
                        if controller_type == 'Job':
                            pod_data[(namespace, pod_name)]['status'] = 'N/A'
                    elif name == 'cpu_requests':
                        pod_data[(namespace, pod_name)]['cpu_request'] = value
                    elif name == 'cpu_limits':
                        pod_data[(namespace, pod_name)]['cpu_limit'] = value
                    elif name == 'mem_requests':
                        pod_data[(namespace, pod_name)]['mem_request'] = value / (1024 * 1024 * 1024)  # Convert to GB
                    elif name == 'mem_limits':
                        pod_data[(namespace, pod_name)]['mem_limit'] = value / (1024 * 1024 * 1024)  # Convert to GB

            # Calculate percentages after all data is collected
            for pod in pod_data.values():
                if 'cpu_usage' in pod and 'cpu_limit' in pod and pod['cpu_limit'] > 0:
                    pod['cpu_usage_percent'] = (pod['cpu_usage'] / pod['cpu_limit']) * 100
                else:
                    pod['cpu_usage_percent'] = 0

                if 'mem_usage' in pod and 'mem_limit' in pod and pod['mem_limit'] > 0:
                    pod['mem_usage_percent'] = (pod['mem_usage'] / pod['mem_limit']) * 100
                else:
                    pod['mem_usage_percent'] = 0
            
            self.update_signal.emit(list(pod_data.values()))
        except Exception as e:
            logging.error(f"Error in PodMetricsWorker: {e}")
            traceback.print_exc()

class PodMetricsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.pod_metrics_worker = None
        self.pod_data = []
        
        # Create loading overlay
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
        
        self.init_ui()
        self.update_pod_metrics()
    
    def showEvent(self, event):
        super().showEvent(event)
        self.loading_overlay.setGeometry(self.rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.loading_overlay:
            self.loading_overlay.setGeometry(self.rect())

    def show_loading(self):
        self.loading_overlay.setGeometry(self.rect())
        self.loading_overlay.raise_()
        self.loading_overlay.show()
        QApplication.processEvents()

    def hide_loading(self):
        self.loading_overlay.hide()
        QApplication.processEvents()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Top controls
        top_controls = QHBoxLayout()
        top_controls.setContentsMargins(10, 10, 10, 10)
        
        # Increase size of refresh and download buttons
        button_style = "QPushButton { min-width: 120px; min-height: 30px; font-size: 14px; }"
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setStyleSheet(button_style)
        self.refresh_button.clicked.connect(self.update_pod_metrics)
        top_controls.addWidget(self.refresh_button)

        self.download_button = QPushButton("Download")
        self.download_button.setStyleSheet(button_style)
        self.download_button.clicked.connect(self.download_pod_metrics)
        top_controls.addWidget(self.download_button)

        top_controls.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search pods...")
        self.search_input.textChanged.connect(self.filter_pod_table)
        self.search_input.setMaximumWidth(200)  # Reduce size of search bar
        top_controls.addWidget(self.search_input)

        # Increase size of dropdowns
        dropdown_style = "QComboBox { min-width: 150px; min-height: 30px; font-size: 14px; }"

        top_controls.addWidget(QLabel("Namespace:"))
        self.namespace_filter = QComboBox()
        self.namespace_filter.setStyleSheet(dropdown_style)
        self.namespace_filter.setPlaceholderText("Filter namespace...")
        self.namespace_filter.currentTextChanged.connect(self.filter_pod_table)
        top_controls.addWidget(self.namespace_filter)

        top_controls.addWidget(QLabel("Controller Type:"))
        self.controller_type_filter = QComboBox()
        self.controller_type_filter.setStyleSheet(dropdown_style)
        self.controller_type_filter.setPlaceholderText("Filter controller type...")
        self.controller_type_filter.currentTextChanged.connect(self.filter_pod_table)
        top_controls.addWidget(self.controller_type_filter)

        top_controls.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.setStyleSheet(dropdown_style)
        self.status_filter.setPlaceholderText("Filter status...")
        self.status_filter.currentTextChanged.connect(self.filter_pod_table)
        top_controls.addWidget(self.status_filter)

        layout.addLayout(top_controls)


        # Pod table
        self.pod_table = QTableView()
        self.pod_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.pod_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.pod_table.setSelectionBehavior(QTableView.SelectRows)
        self.pod_table.setSelectionMode(QTableView.SingleSelection)
        headers = [
            "Namespace", "Pod Name", "CPU Usage %", "CPU Request", "CPU Limit",
            "Memory Usage %", "Memory Request (GB)", "Memory Limit (GB)",
            "Status", "Controller Type", "Controller Name"
        ]
        self.pod_model = TotalRowTableModel([], headers)
        self.proxy_model = SortFilterProxyModel()
        self.proxy_model.setSourceModel(self.pod_model)
        self.pod_table.setModel(self.proxy_model)
        self.pod_table.setSortingEnabled(True)
        self.pod_table.verticalHeader().setVisible(False)
        
        # Set stretch mode for all columns
        header = self.pod_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        # Set a larger width for the Pod Name column
        header.resizeSection(1, 250)  # Set Pod Name column width to 250 pixels
        
        font = QFont()
        font.setPointSize(10)
        self.pod_table.setFont(font)
        layout.addWidget(self.pod_table)

        # Connect the header's sectionResized signal to update column widths
        header.sectionResized.connect(self.on_section_resized)

        # Bottom controls
        bottom_controls = QHBoxLayout()
        bottom_controls.setContentsMargins(10, 10, 10, 10)
        
        self.logs_button = QPushButton("View Logs")
        self.logs_button.clicked.connect(self.view_pod_logs)
        bottom_controls.addWidget(self.logs_button)

        self.edit_button = QPushButton("Edit Resources")
        self.edit_button.clicked.connect(self.edit_controller_resources)
        bottom_controls.addWidget(self.edit_button)

        layout.addLayout(bottom_controls)
    
    def on_section_resized(self, logical_index, old_size, new_size):
        # Distribute remaining space among other columns
        header = self.pod_table.horizontalHeader()
        total_width = sum(header.sectionSize(i) for i in range(header.count()))
        available_width = self.pod_table.viewport().width()
        if total_width < available_width:
            extra_space = available_width - total_width
            for i in range(header.count()):
                if i != logical_index:
                    current_width = header.sectionSize(i)
                    new_width = current_width + extra_space // (header.count() - 1)
                    header.resizeSection(i, new_width)
    
    
    def adjust_column_widths(self):
        header = self.pod_table.horizontalHeader()
        total_width = self.pod_table.viewport().width()
        column_count = header.count()
        
        # Set Pod Name column (index 1) to 25% of total width
        pod_name_width = int(total_width * 0.25)
        header.resizeSection(1, pod_name_width)
        
        # Distribute remaining width among other columns
        remaining_width = total_width - pod_name_width
        default_column_width = remaining_width // (column_count - 1)
        
        for i in range(column_count):
            if i != 1:  # Skip Pod Name column
                header.resizeSection(i, default_column_width)

    def update_pod_metrics(self):
        if self.parent.prom is None:
            print("Prometheus client is not initialized")
            return
        
        # Clear existing data
        self.pod_data = []
        
        # Show loading indicator
        self.show_loading()
        
        # Create and start the worker thread
        self.pod_metrics_worker = PodMetricsWorker(self.parent.prom)
        self.pod_metrics_worker.update_signal.connect(self.on_pod_metrics_updated)
        self.pod_metrics_worker.finished.connect(self.on_update_finished)
        self.pod_metrics_worker.start()
    
    def on_update_finished(self):
        # Hide loading indicator
        self.hide_loading()

    def on_pod_metrics_updated(self, pod_data):
        self.pod_data = pod_data
        self.populate_pod_table()
        self.filter_pod_table()
        self.hide_loading()

    def populate_pod_table(self):
        table_data = []
        namespaces = set()
        controller_types = set()
        statuses = set()

        for pod in self.pod_data:
            row = [
                pod.get('namespace', ''),
                pod.get('name', ''),
                f"{pod.get('cpu_usage_percent', 0):.2f}",
                f"{pod.get('cpu_request', 0):.2f}",
                f"{pod.get('cpu_limit', 0):.2f}",
                f"{pod.get('mem_usage_percent', 0):.2f}",
                f"{pod.get('mem_request', 0):.2f}",
                f"{pod.get('mem_limit', 0):.2f}",
                pod.get('status', ''),
                pod.get('controller_type', ''),
                pod.get('controller_name', '')
            ]
            table_data.append(row)
            namespaces.add(pod.get('namespace', ''))
            controller_types.add(pod.get('controller_type', ''))
            statuses.add(pod.get('status', ''))

        self.pod_model.update_data(table_data)
        
        self.update_filter_options(self.namespace_filter, namespaces)
        self.update_filter_options(self.controller_type_filter, controller_types)
        self.update_filter_options(self.status_filter, statuses)

        # Adjust column widths
        self.adjust_column_widths()
        
        self.pod_table.sortByColumn(2, Qt.DescendingOrder) 

    def update_filter_options(self, combobox, items):
        current_text = combobox.currentText()
        combobox.clear()
        combobox.addItem("All")
        combobox.addItems(sorted(filter(None, items)))
        index = combobox.findText(current_text)
        if index >= 0:
            combobox.setCurrentIndex(index)
        else:
            combobox.setCurrentText("All")

    def filter_pod_table(self):
        search_text = self.search_input.text().lower()
        namespace = self.namespace_filter.currentText()
        controller_type = self.controller_type_filter.currentText()
        status = self.status_filter.currentText()

        filtered_data = []
        for row in self.pod_model._data:
            if (namespace == "All" or row[0] == namespace) and \
               (controller_type == "All" or row[9] == controller_type) and \
               (status == "All" or row[8] == status) and \
               (search_text in ' '.join(map(str, row)).lower()):
                filtered_data.append(row)

        self.pod_model.set_filtered_data(filtered_data)
        self.proxy_model.invalidate()
        self.pod_table.sortByColumn(self.pod_table.horizontalHeader().sortIndicatorSection(),
                                    self.pod_table.horizontalHeader().sortIndicatorOrder())

    def view_pod_logs(self):
        selected_indexes = self.pod_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(self, "No Pod Selected", "Please select a pod to view logs.")
            return
        
        row = selected_indexes[0].row()
        namespace = self.proxy_model.data(self.proxy_model.index(row, 0))
        pod_name = self.proxy_model.data(self.proxy_model.index(row, 1))
        
        logs_dialog = QDialog(self)
        logs_dialog.setWindowTitle(f"Logs for {pod_name}")
        logs_dialog.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(logs_dialog)
        
        logs_text = QTextEdit()
        logs_text.setReadOnly(True)
        layout.addWidget(logs_text)
        
        try:
            # Fetch logs from Prometheus
            query = f'{{namespace="{namespace}", pod="{pod_name}"}}'
            logs = self.parent.prom.custom_query(f'container_log{query}')
            logs_text.setText("\n".join([log['_line'] for log in logs]))
        except Exception as e:
            logs_text.setText(f"Error fetching logs: {str(e)}")
        
        logs_dialog.exec_()
    
    def find_actual_controller(self, pod, namespace):
        for owner_ref in pod.metadata.owner_references:
            if owner_ref.kind == "ReplicaSet":
                try:
                    rs = self.parent.apps_v1.read_namespaced_replica_set(name=owner_ref.name, namespace=namespace)
                    for rs_owner_ref in rs.metadata.owner_references:
                        if rs_owner_ref.kind in ["Deployment", "StatefulSet", "DaemonSet"]:
                            return rs_owner_ref.kind, rs_owner_ref.name
                except Exception as e:
                    print(f"Error finding ReplicaSet owner: {e}")
            elif owner_ref.kind in ["Deployment", "StatefulSet", "DaemonSet"]:
                return owner_ref.kind, owner_ref.name
        return "Unknown", "Unknown"

    def edit_controller_resources(self):
        selected_indexes = self.pod_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(self, "No Pod Selected", "Please select a pod to edit its controller's resources.")
            return

        row = selected_indexes[0].row()
        namespace = self.proxy_model.data(self.proxy_model.index(row, 0))
        pod_name = self.proxy_model.data(self.proxy_model.index(row, 1))
        initial_controller_type = self.proxy_model.data(self.proxy_model.index(row, 9))
        initial_controller_name = self.proxy_model.data(self.proxy_model.index(row, 10))

        try:
            # Fetch pod information
            pod = self.parent.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            # Find the actual controller
            controller_type, controller_name = self.find_actual_controller(pod, namespace)
            
            if controller_type not in ["Deployment", "StatefulSet", "DaemonSet"]:
                QMessageBox.warning(self, "Unsupported Controller", 
                                    f"Editing resources is only supported for Deployments, StatefulSets, and DaemonSets. "
                                    f"This pod is controlled by a {controller_type}.")
                return

            # Fetch controller information using Kubernetes API
            if controller_type == "Deployment":
                controller = self.parent.apps_v1.read_namespaced_deployment(name=controller_name, namespace=namespace)
            elif controller_type == "StatefulSet":
                controller = self.parent.apps_v1.read_namespaced_stateful_set(name=controller_name, namespace=namespace)
            elif controller_type == "DaemonSet":
                controller = self.parent.apps_v1.read_namespaced_daemon_set(name=controller_name, namespace=namespace)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to retrieve controller information: {str(e)}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Resources for {controller_type}: {controller_name}")
        dialog.setMinimumSize(800, 600)
        layout = QVBoxLayout(dialog)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        splitter = QSplitter(Qt.Vertical)

        for container in controller.spec.template.spec.containers:
            container_widget = QWidget()
            container_layout = QVBoxLayout(container_widget)

            container_layout.addWidget(QLabel(f"Container: {container.name}"))

            form_layout = QFormLayout()
            cpu_request = QLineEdit(container.resources.requests.get('cpu', ''))
            cpu_limit = QLineEdit(container.resources.limits.get('cpu', ''))
            mem_request = QLineEdit(container.resources.requests.get('memory', ''))
            mem_limit = QLineEdit(container.resources.limits.get('memory', ''))
            image = QLineEdit(container.image)

            form_layout.addRow("CPU Request:", cpu_request)
            form_layout.addRow("CPU Limit:", cpu_limit)
            form_layout.addRow("Memory Request:", mem_request)
            form_layout.addRow("Memory Limit:", mem_limit)
            form_layout.addRow("Image:", image)

            container_layout.addLayout(form_layout)
            splitter.addWidget(container_widget)

        scroll_layout.addWidget(splitter)
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            try:
                for i, container in enumerate(controller.spec.template.spec.containers):
                    container_widget = splitter.widget(i)
                    form_layout = container_widget.layout().itemAt(1).layout()

                    cpu_request = form_layout.itemAt(0, QFormLayout.FieldRole).widget().text()
                    cpu_limit = form_layout.itemAt(1, QFormLayout.FieldRole).widget().text()
                    mem_request = form_layout.itemAt(2, QFormLayout.FieldRole).widget().text()
                    mem_limit = form_layout.itemAt(3, QFormLayout.FieldRole).widget().text()
                    image = form_layout.itemAt(4, QFormLayout.FieldRole).widget().text()

                    container.resources = client.V1ResourceRequirements(
                        requests={"cpu": cpu_request, "memory": mem_request},
                        limits={"cpu": cpu_limit, "memory": mem_limit}
                    )
                    container.image = image

                # Update the controller using Kubernetes API
                if controller_type == "Deployment":
                    self.parent.apps_v1.patch_namespaced_deployment(
                        name=controller_name, namespace=namespace, body=controller)
                elif controller_type == "StatefulSet":
                    self.parent.apps_v1.patch_namespaced_stateful_set(
                        name=controller_name, namespace=namespace, body=controller)
                elif controller_type == "DaemonSet":
                    self.parent.apps_v1.patch_namespaced_daemon_set(
                        name=controller_name, namespace=namespace, body=controller)

                QMessageBox.information(self, "Success", "Resources and images updated successfully.")
                self.update_pod_metrics()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to update resources: {str(e)}")
    def download_pod_metrics(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Pod Metrics", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if fileName:
            with open(fileName, 'w', newline='') as file:
                writer = csv.writer(file)
                headers = [self.pod_model.headerData(i, Qt.Horizontal) for i in range(self.pod_model.columnCount())]
                writer.writerow(headers)
                for row in range(self.proxy_model.rowCount()):
                    row_data = [self.proxy_model.data(self.proxy_model.index(row, col)) for col in range(self.proxy_model.columnCount())]
                    writer.writerow(row_data)
            QMessageBox.information(self, "Download Complete", "Pod metrics have been saved successfully.")