from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton, QLabel, QTableView, QProgressBar, QGroupBox, QFileDialog, QMessageBox, QDialog, QTextEdit, QSizePolicy, QHeaderView, QFormLayout, QLineEdit, QDialogButtonBox
from PyQt5.QtGui import QFont, QStandardItemModel, QStandardItem, QFontMetrics
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMetaObject, Q_ARG
from kubernetes import client
from resource_updaters import parse_k8s_cpu, parse_k8s_memory
import csv
import traceback
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, 
                             QTreeView, QTextEdit, QLineEdit, QSplitter, QMessageBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea, QFrame, QDialog)


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

    def showEvent(self, event):
        self.setGeometry(self.parent().rect())

class NodeTableWorker(QThread):
    update_signal = pyqtSignal(list)

    def __init__(self, v1, prom):
        super().__init__()
        self.v1 = v1
        self.prom = prom

    def run(self):
        try:
            nodes = self.v1.list_node().items
            print(f"Found {len(nodes)} nodes")
            
            # Fetch metrics from Prometheus
            cpu_usage = self.fetch_prometheus_metric('100 * avg(1 - rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance)')
            mem_usage = self.fetch_prometheus_metric('100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))')
            cpu_allocatable = self.fetch_prometheus_metric('kube_node_status_allocatable{resource="cpu"}')
            mem_allocatable = self.fetch_prometheus_metric('kube_node_status_allocatable{resource="memory"}')
            cpu_req = self.fetch_prometheus_metric('sum(kube_pod_container_resource_requests{resource="cpu"}) by (node)')
            cpu_limit = self.fetch_prometheus_metric('sum(kube_pod_container_resource_limits{resource="cpu"}) by (node)')
            mem_req = self.fetch_prometheus_metric('sum(kube_pod_container_resource_requests{resource="memory"}) by (node)')
            mem_limit = self.fetch_prometheus_metric('sum(kube_pod_container_resource_limits{resource="memory"}) by (node)')

            node_data = []
            for node in nodes:
                node_name = node.metadata.name
                instance_ip = next((address.address for address in node.status.addresses if address.type in ['InternalIP', 'ExternalIP']), None)
                print(f"Processing node: {node_name}, Instance IP: {instance_ip}")
                
                if instance_ip:
                    node_data.append({
                        'name': node_name,
                        'role': 'master' if any(label.startswith("node-role.kubernetes.io/master") or label.startswith("node-role.kubernetes.io/control-plane") for label in node.metadata.labels) else 'worker',
                        'ip': instance_ip,
                        'cpu_req': self.get_metric_value(cpu_req, node_name),
                        'cpu_limit': self.get_metric_value(cpu_limit, node_name),
                        'cpu_usage': self.get_metric_value(cpu_usage, instance_ip, 'instance', True),
                        'mem_req': self.get_metric_value(mem_req, node_name),
                        'mem_limit': self.get_metric_value(mem_limit, node_name),
                        'mem_usage': self.get_metric_value(mem_usage, instance_ip, 'instance', True),
                        'status': node.status.conditions[-1].type if node.status.conditions else 'Unknown',
                        'cordoned': "Yes" if node.spec.unschedulable else "No",
                        'cpu_allocatable': self.get_allocatable_value(cpu_allocatable, node_name, 'cpu'),
                        'mem_allocatable': self.get_allocatable_value(mem_allocatable, node_name, 'memory')
                    })
                
                    print(f"Node {node_name} data:")
                    for key, value in node_data[-1].items():
                        print(f"  {key}: {value}")
                else:
                    print(f"Skipping node {node_name} due to missing instance address")

            self.update_signal.emit(node_data)
        except Exception as e:
            print(f"Error in NodeTableWorker: {e}")
            traceback.print_exc()

    def fetch_prometheus_metric(self, query):
        try:
            print(f"Executing Prometheus query: {query}")
            result = self.prom.custom_query(query)
            print(f"Query result: {result}")
            return result
        except Exception as e:
            print(f"Error fetching Prometheus metric: {e}")
            traceback.print_exc()
            return []

    def get_metric_value(self, metric_list, node_name, key='node', use_instance_port=False):
        for item in metric_list:
            if key in item['metric']:
                metric_value = item['metric'][key]
                if use_instance_port:
                    if metric_value.startswith(node_name):
                        return float(item['value'][1])
                elif metric_value == node_name:
                    return float(item['value'][1])
        return 0

    def get_allocatable_value(self, metric_list, node_name, resource_type):
        for item in metric_list:
            if 'node' in item['metric'] and item['metric']['node'] == node_name and 'resource' in item['metric'] and item['metric']['resource'] == resource_type:
                value = float(item['value'][1])
                if resource_type == 'cpu':
                    return value  # CPU is already in cores
                elif resource_type == 'memory':
                    return value / (1024 * 1024 * 1024)  # Convert bytes to GB
        return 0


    def parse_cpu_value(self, cpu_string):
        try:
            if isinstance(cpu_string, (int, float)):
                return float(cpu_string)
            if isinstance(cpu_string, str):
                if cpu_string.endswith('m'):
                    return float(cpu_string[:-1]) / 1000
                if cpu_string.endswith('n'):
                    return float(cpu_string[:-1]) / 1e9
                return float(cpu_string)
        except ValueError as e:
            print(f"Error parsing CPU value '{cpu_string}': {e}")
        return 0.0

    def parse_memory_value(self, mem_string):
        try:
            if isinstance(mem_string, (int, float)):
                return float(mem_string)
            if isinstance(mem_string, str):
                if mem_string.endswith('Ki'):
                    return float(mem_string[:-2]) * 1024
                if mem_string.endswith('Mi'):
                    return float(mem_string[:-2]) * 1024 * 1024
                if mem_string.endswith('Gi'):
                    return float(mem_string[:-2]) * 1024 * 1024 * 1024
                return float(mem_string)
        except ValueError as e:
            print(f"Error parsing memory value '{mem_string}': {e}")
        return 0.0

class NodeDetailsFetcher(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, prom, node_name):
        super().__init__()
        self.prom = prom
        self.node_name = node_name

    def run(self):
        try:
            # Fetch pod metrics from Prometheus
            cpu_usage = self.fetch_prometheus_metric(f'sum(rate(container_cpu_usage_seconds_total{{container!="POD", container!="", node="{self.node_name}"}}[5m])) by (pod)')
            mem_usage = self.fetch_prometheus_metric(f'sum(container_memory_working_set_bytes{{container!="POD", container!="", node="{self.node_name}"}}) by (pod)')
            cpu_requests = self.fetch_prometheus_metric(f'sum(kube_pod_container_resource_requests{{node="{self.node_name}", resource="cpu"}}) by (pod)')
            cpu_limits = self.fetch_prometheus_metric(f'sum(kube_pod_container_resource_limits{{node="{self.node_name}", resource="cpu"}}) by (pod)')
            mem_requests = self.fetch_prometheus_metric(f'sum(kube_pod_container_resource_requests{{node="{self.node_name}", resource="memory"}}) by (pod)')
            mem_limits = self.fetch_prometheus_metric(f'sum(kube_pod_container_resource_limits{{node="{self.node_name}", resource="memory"}}) by (pod)')

            # Fetch node allocatable resources
            cpu_allocatable = self.fetch_prometheus_metric(f'kube_node_status_allocatable{{node="{self.node_name}", resource="cpu"}}')
            mem_allocatable = self.fetch_prometheus_metric(f'kube_node_status_allocatable{{node="{self.node_name}", resource="memory"}}')

            print(f"Node: {self.node_name}")
            print(f"CPU Usage: {cpu_usage}")
            print(f"Memory Usage: {mem_usage}")
            print(f"CPU Requests: {cpu_requests}")
            print(f"CPU Limits: {cpu_limits}")
            print(f"Memory Requests: {mem_requests}")
            print(f"Memory Limits: {mem_limits}")
            print(f"CPU Allocatable: {cpu_allocatable}")
            print(f"Memory Allocatable: {mem_allocatable}")

            # Process the data into a format suitable for the UI
            pods_data = self.process_pod_data(cpu_usage, mem_usage, cpu_requests, cpu_limits, mem_requests, mem_limits)

            result = {
                'pods': pods_data,
                'cpu_allocatable': self.get_scalar_value(cpu_allocatable),
                'mem_allocatable': self.get_scalar_value(mem_allocatable)
            }
            self.finished.emit(result)
        except Exception as e:
            print(f"Error fetching node details: {e}")
            traceback.print_exc()

    def fetch_prometheus_metric(self, query):
        try:
            print(f"Executing Prometheus query: {query}")
            result = self.prom.custom_query(query)
            print(f"Query result: {result}")
            return result
        except Exception as e:
            print(f"Error fetching Prometheus metric: {e}")
            traceback.print_exc()
            return []

    def process_pod_data(self, cpu_usage, mem_usage, cpu_requests, cpu_limits, mem_requests, mem_limits):
        pods_data = {}
        for metric in [cpu_usage, mem_usage, cpu_requests, cpu_limits, mem_requests, mem_limits]:
            for item in metric:
                pod_name = item['metric']['pod']
                value = float(item['value'][1])
                if pod_name not in pods_data:
                    pods_data[pod_name] = {'name': pod_name}
                if metric == cpu_usage:
                    pods_data[pod_name]['cpu_usage'] = value
                elif metric == mem_usage:
                    pods_data[pod_name]['mem_usage'] = value
                elif metric == cpu_requests:
                    pods_data[pod_name]['cpu_request'] = value
                elif metric == cpu_limits:
                    pods_data[pod_name]['cpu_limit'] = value
                elif metric == mem_requests:
                    pods_data[pod_name]['mem_request'] = value
                elif metric == mem_limits:
                    pods_data[pod_name]['mem_limit'] = value
        return list(pods_data.values())

    def get_scalar_value(self, metric):
        if metric and len(metric) > 0:
            return float(metric[0]['value'][1])
        return 0
    
class NodeMetricsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.node_table_worker = None
        self.cpu_bars = {}
        self.mem_bars = {}
        
        # Create loading overlay
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()
        
        self.init_ui()
        self.update_node_table()
    
    def showEvent(self, event):
        super().showEvent(event)
        self.loading_overlay.setGeometry(self.rect())

    def show_loading(self):
        self.loading_overlay.setGeometry(self.rect())
        self.loading_overlay.show()
        QApplication.processEvents()

    def hide_loading(self):
        self.loading_overlay.hide()
        QApplication.processEvents()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(self.rect())


    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # Top controls
        top_controls = QHBoxLayout()
        self.refresh_button = self.create_button("Refresh", "#4CAF50", self.update_node_table)
        self.download_button = self.create_button("Download", "#FFD700", self.download_node_metrics)
        top_controls.addWidget(self.refresh_button)
        top_controls.addWidget(self.download_button)
        top_controls.addStretch(1)
        main_layout.addLayout(top_controls)

        # Node table
        self.node_table = self.create_table()
        self.node_model = self.node_table.model()
        main_layout.addWidget(self.node_table)

        # Details section
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setSpacing(10)

        # Labels for Pod Details and Node Usage
        labels_layout = QHBoxLayout()
        pod_details_label = QLabel("Pod Details")
        node_usage_label = QLabel("Node Usage")
        pod_details_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        node_usage_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        labels_layout.addWidget(pod_details_label)
        labels_layout.addWidget(node_usage_label)
        details_layout.addLayout(labels_layout)

        # Pod Details and Node Usage widgets
        content_layout = QHBoxLayout()
        self.pod_details = self.create_pod_details()
        self.node_usage = self.create_node_usage()
        content_layout.addWidget(self.pod_details)
        content_layout.addWidget(self.node_usage)
        details_layout.addLayout(content_layout)

        main_layout.addWidget(details_widget)

        # Set stretch factors to control relative sizes
        main_layout.setStretchFactor(self.node_table, 1)
        main_layout.setStretchFactor(details_widget, 2)
        self.loading_overlay.raise_()
    
    def adjust_splitter_sizes(self):
        total_height = self.height()
        self.splitter.setSizes([int(total_height * 0.4), int(total_height * 0.6)])
    
    def create_stylish_node_usage(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        usage_panel = QWidget()
        usage_panel.setObjectName("usagePanel")
        usage_layout = QHBoxLayout(usage_panel)
        
        cpu_widget = self.create_usage_widget("CPU Utilization")
        mem_widget = self.create_usage_widget("Memory Utilization")
        
        usage_layout.addWidget(cpu_widget)
        usage_layout.addWidget(mem_widget)
        
        layout.addWidget(usage_panel)
        
        # Add stylish background and polish to the usage panel
        usage_panel.setStyleSheet("""
            QWidget#usagePanel {
                background-color: #f0f0f0;
                border-radius: 10px;
                border: 1px solid #d0d0d0;
            }
            QLabel {
                font-weight: bold;
                color: #333;
            }
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4CAF50, stop:1 #45a049);
                border-radius: 5px;
            }
        """)
        
        return widget
    
    def create_button(self, text, color, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def create_table(self):
        table = QTableView()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.setSelectionMode(QTableView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setFont(QFont("Arial", 10))
        
        # Disable scrollbars
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Create an empty model and set it to the table
        model = QStandardItemModel()
        table.setModel(model)
        
        # Connect the selectionChanged signal
        table.selectionModel().selectionChanged.connect(self.update_node_details)
        
        return table

    def create_group_box(self, title, content):
        group_box = QGroupBox(title)
        layout = QVBoxLayout(group_box)
        layout.addWidget(content)
        return group_box

    def create_pod_details(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.top_pods_table = self.create_table()
        self.top_pods_model = QStandardItemModel()
        self.top_pods_table.setModel(self.top_pods_model)
        layout.addWidget(self.top_pods_table)

        button_layout = QHBoxLayout()
        self.logs_button = self.create_button("View Logs", "#2196F3", self.view_pod_logs)
        self.edit_button = self.create_button("Edit Resources", "#FF9800", self.edit_pod_resources)
        button_layout.addWidget(self.logs_button)
        button_layout.addWidget(self.edit_button)
        layout.addLayout(button_layout)
        
        return widget

    def create_node_usage(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        usage_panel = QWidget()
        usage_panel.setObjectName("usagePanel")
        usage_layout = QHBoxLayout(usage_panel)
        
        cpu_widget = self.create_usage_widget("CPU Utilization")
        mem_widget = self.create_usage_widget("Memory Utilization")
        
        usage_layout.addWidget(cpu_widget)
        usage_layout.addWidget(self.create_vertical_line())
        usage_layout.addWidget(mem_widget)
        
        layout.addWidget(usage_panel)
        
        # Add stylish background and polish to the usage panel
        usage_panel.setStyleSheet("""
            QWidget#usagePanel {
                background-color: #f0f0f0;
                border: 2px solid #d0d0d0;
                border-radius: 10px;
            }
            QLabel {
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4CAF50, stop:1 #45a049);
                border-radius: 5px;
            }
        """)
        
        return widget
    
    def create_vertical_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #d0d0d0;")
        return line

    def create_usage_widget(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(10)
        
        layout.addWidget(QLabel(title, alignment=Qt.AlignCenter))
        
        bars = {}
        for label in ["Usage", "Requests", "Limits"]:
            bars[label.lower()] = self.create_usage_bar(layout, label)
            if label != "Limits":
                layout.addWidget(self.create_horizontal_line())
        
        if title.startswith("CPU"):
            self.cpu_bars = bars
        else:
            self.mem_bars = bars
        
        return widget

    def create_horizontal_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("background-color: #d0d0d0;")
        return line

    def init_node_details_section(self, parent_layout):
        details_layout = QHBoxLayout()

        # Left section: Pod Details
        left_section = QGroupBox("Pod Details")
        left_layout = QVBoxLayout()
        
        self.top_pods_table = QTableView()
        self.top_pods_model = QStandardItemModel()
        self.top_pods_table.setModel(self.top_pods_model)
        self.top_pods_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.top_pods_table.setSelectionMode(QTableView.SingleSelection)
        self.top_pods_table.setSelectionBehavior(QTableView.SelectRows)

        font = QFont()
        font.setPointSize(12)
        self.top_pods_table.setFont(font)

        left_layout.addWidget(self.top_pods_table)

        button_layout = QHBoxLayout()
        self.logs_button = QPushButton("View Logs")
        self.logs_button.clicked.connect(self.view_pod_logs)
        self.edit_button = QPushButton("Edit Resources")
        self.edit_button.clicked.connect(self.edit_pod_resources)
        button_layout.addWidget(self.logs_button)
        button_layout.addWidget(self.edit_button)
        left_layout.addLayout(button_layout)
        
        left_section.setLayout(left_layout)
        details_layout.addWidget(left_section)

        # Right section: Node Usage
        right_section = QGroupBox("Node Usage")
        right_layout = QHBoxLayout()
        
        cpu_widget = QWidget()
        cpu_layout = QVBoxLayout(cpu_widget)
        cpu_layout.addWidget(QLabel("Node CPU Utilization"))
        self.cpu_usage_bar = self.create_usage_bar("Usage/Capacity")
        self.cpu_requests_bar = self.create_usage_bar("Requests/Capacity")
        self.cpu_limits_bar = self.create_usage_bar("Limits/Capacity")
        cpu_layout.addWidget(self.cpu_usage_bar)
        cpu_layout.addWidget(self.cpu_requests_bar)
        cpu_layout.addWidget(self.cpu_limits_bar)
        
        mem_widget = QWidget()
        mem_layout = QVBoxLayout(mem_widget)
        mem_layout.addWidget(QLabel("Node Memory Utilization"))
        self.mem_usage_bar = self.create_usage_bar("Usage/Capacity")
        self.mem_requests_bar = self.create_usage_bar("Requests/Capacity")
        self.mem_limits_bar = self.create_usage_bar("Limits/Capacity")
        mem_layout.addWidget(self.mem_usage_bar)
        mem_layout.addWidget(self.mem_requests_bar)
        mem_layout.addWidget(self.mem_limits_bar)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(cpu_widget)
        splitter.addWidget(mem_widget)
        right_layout.addWidget(splitter)

        right_section.setLayout(right_layout)
        details_layout.addWidget(right_section)

        parent_layout.addLayout(details_layout)

    def create_usage_bar(self, layout, label):
        bar_widget = QWidget()
        bar_layout = QVBoxLayout(bar_widget)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(2)

        label_widget = QLabel(f"{label}:")
        bar_layout.addWidget(label_widget)

        info_label = QLabel()
        info_label.setAlignment(Qt.AlignCenter)
        bar_layout.addWidget(info_label)

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(20)
        bar_layout.addWidget(bar)

        value_label = QLabel()
        value_label.setAlignment(Qt.AlignCenter)
        bar_layout.addWidget(value_label)

        layout.addWidget(bar_widget)
        return {"bar": bar, "label": value_label, "info": info_label}

    def update_node_table(self):
        if self.v1 is None or self.parent.prom is None:
            print("Kubernetes API client or Prometheus client is not initialized")
            return
        self.show_loading()

        self.node_table_worker = NodeTableWorker(self.v1, self.parent.prom)
        self.node_table_worker.update_signal.connect(self.populate_node_table)
        self.node_table_worker.finished.connect(self.update_pod_details)
        self.node_table_worker.finished.connect(self.hide_loading)
        self.node_table_worker.start()
    
    def update_pod_details(self):
        # Get the currently selected node
        selected_indexes = self.node_table.selectionModel().selectedIndexes()
        if selected_indexes:
            row = selected_indexes[0].row()
            node_name = self.node_model.item(row, 0).text()
            
            self.fetcher = NodeDetailsFetcher(self.parent.prom, node_name)
            self.fetcher.finished.connect(self.process_node_details)
            self.fetcher.start()
        else:
            # If no node is selected, clear the pod details and usage bars
            self.clear_pod_details()
    
    def clear_pod_details(self):
        self.top_pods_model.clear()
        self.top_pods_model.setHorizontalHeaderLabels([
            "Pod Name", "CPU Usage %", "CPU Req", "CPU Limit", "Mem Usage %", "Mem Req", "Mem Limit"
        ])
        self.update_usage_bars(0, 0, 0, 0, 0, 0, 1, 1)  # Set all values to 0 and capacity to 1 to avoid division by zero

    def hide_loading_indicator(self):
        self.loading_label.deleteLater()
        self.node_table.setVisible(True)

    def populate_node_table(self, node_data):
        self.node_model.clear()
        self.node_model.setHorizontalHeaderLabels([
            "Node Name", "Role", "IP", "CPU Req", "CPU Limit", 
            "CPU Usage %", "Mem Req (GB)", "Mem Limit (GB)", "Mem Usage %", "CPU Allocatable", "Mem Allocatable (GB)", "Status", "Cordoned"
        ])
        
        max_node_name_width = self.calculate_max_text_width("Node Name")
        
        for node in node_data:
            try:
                row = [
                    QStandardItem(node['name']),
                    QStandardItem(node['role']),
                    QStandardItem(node['ip']),
                    QStandardItem(f"{node['cpu_req']:.2f}"),
                    QStandardItem(f"{node['cpu_limit']:.2f}"),
                    QStandardItem(f"{node['cpu_usage']:.2f}"),
                    QStandardItem(f"{node['mem_req']/ (1024**3):.2f}"),
                    QStandardItem(f"{node['mem_limit']/ (1024**3):.2f}"),
                    QStandardItem(f"{node['mem_usage']:.2f}"),
                    QStandardItem(f"{node['cpu_allocatable']:.2f}"),
                    QStandardItem(f"{node['mem_allocatable']:.2f}"),
                    QStandardItem(node['status']),
                    QStandardItem(node['cordoned'])
                ]
                self.node_model.appendRow(row)
                max_node_name_width = max(max_node_name_width, self.calculate_max_text_width(node['name']))
                print(f"Added row for node {node['name']}")
            except Exception as e:
                print(f"Error populating row for node {node.get('name', 'unknown')}: {e}")
                traceback.print_exc()

        self.node_table.sortByColumn(5, Qt.DescendingOrder)  # Sort by CPU Usage

        # Adjust column widths
        self.node_table.setColumnWidth(0, max(800, max_node_name_width + 50))  # Node Name - increased width

        # Add tooltips for non-metric columns
        for row in range(self.node_model.rowCount()):
            for col in [0, 1, 2, 11, 12]:
                item = self.node_model.item(row, col)
                if item:
                    item.setToolTip(item.text())
        self.adjust_table_size()

        # Select the first row
        if self.node_model.rowCount() > 0:
            self.node_table.selectRow(0)

    def calculate_max_text_width(self, text):
        font = self.node_table.font()
        metrics = QFontMetrics(font)
        return metrics.width(text)

    def adjust_table_size(self):
        # Calculate the total height needed for all rows
        total_height = self.node_table.horizontalHeader().height()
        for i in range(self.node_model.rowCount()):
            total_height += self.node_table.rowHeight(i)

        # Set the table height to fit all rows
        self.node_table.setFixedHeight(total_height)

        # Adjust column widths
        self.node_table.resizeColumnsToContents()

    def update_node_details(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            self.show_loading()
            row = indexes[0].row()
            node_name = self.node_model.item(row, 0).text()

            self.fetcher = NodeDetailsFetcher(self.parent.prom, node_name)
            self.fetcher.finished.connect(self.process_node_details)
            self.fetcher.start()

    def process_node_details(self, result):
        pods = result['pods']
        cpu_allocatable = result['cpu_allocatable']
        mem_allocatable = result['mem_allocatable']

        self.update_usage_bars(
            sum(pod.get('cpu_request', 0) for pod in pods),
            sum(pod.get('mem_request', 0) for pod in pods),
            sum(pod.get('cpu_usage', 0) for pod in pods),
            sum(pod.get('mem_usage', 0) for pod in pods),
            sum(pod.get('cpu_limit', 0) for pod in pods),
            sum(pod.get('mem_limit', 0) for pod in pods),
            cpu_allocatable,
            mem_allocatable
        )
        self.update_top_pods_table(pods, cpu_allocatable, mem_allocatable)
        self.hide_loading()


    def calculate_node_usage(self, node, pods, pod_metrics):
        cpu_req, cpu_limit, mem_req, mem_limit, cpu_usage, mem_usage = 0, 0, 0, 0, 0, 0

        for pod in pods:
            key = f"{pod.metadata.namespace}/{pod.metadata.name}"
            metrics = pod_metrics.get(key, {})
            
            cpu_usage += parse_k8s_cpu(metrics.get('cpu', '0'))
            mem_usage += parse_k8s_memory(metrics.get('memory', '0'))

            for container in pod.spec.containers:
                resources = container.resources
                if resources:
                    requests = resources.requests or {}
                    limits = resources.limits
                    cpu_req += parse_k8s_cpu(requests.get('cpu', '0'))
                    mem_req += parse_k8s_memory(requests.get('memory', '0'))
                    
                    if limits:
                        cpu_limit += parse_k8s_cpu(limits.get('cpu', '0'))
                        mem_limit += parse_k8s_memory(limits.get('memory', '0'))

        return cpu_req, cpu_limit, mem_req, mem_limit, cpu_usage, mem_usage

    def update_usage_bars(self, cpu_req, mem_req, cpu_usage, mem_usage, cpu_limit, mem_limit, cpu_allocatable, mem_allocatable):
        self.update_bar(self.cpu_bars['usage'], cpu_usage, cpu_allocatable, "CPU Usage")
        self.update_bar(self.cpu_bars['requests'], cpu_req, cpu_allocatable, "CPU Requests")
        self.update_bar(self.cpu_bars['limits'], cpu_limit, cpu_allocatable, "CPU Limits")
        self.update_bar(self.mem_bars['usage'], mem_usage, mem_allocatable, "Memory Usage")
        self.update_bar(self.mem_bars['requests'], mem_req, mem_allocatable, "Memory Requests")
        self.update_bar(self.mem_bars['limits'], mem_limit, mem_allocatable, "Memory Limits")

    def update_bar(self, bar_dict, value, capacity, text):
        bar = bar_dict["bar"]
        label = bar_dict["label"]
        info_label = bar_dict["info"]
        percentage = min((value / capacity) * 100 if capacity > 0 else 0, 100)  # Cap at 100%
        bar.setValue(int(percentage))
        
        if text.startswith("CPU"):
            label.setText(f"{value:.2f}/{capacity:.2f} cores ({percentage:.2f}%)")
            info_label.setText(f"{text}: {value:.2f}/{capacity:.2f} cores")
        else:
            value_gb = value / (1024**3)
            capacity_gb = capacity / (1024**3)
            label.setText(f"{value_gb:.2f}/{capacity_gb:.2f} GB ({percentage:.2f}%)")
            info_label.setText(f"{text}: {value_gb:.2f}/{capacity_gb:.2f} GB")
        
        if percentage < 60:
            color = "#4CAF50"  # Green
        elif percentage < 80:
            color = "#FFC107"  # Yellow
        else:
            color = "#F44336"  # Red
        
        bar.setStyleSheet(f"""
            QProgressBar {{
                border: 2px solid {color};
                border-radius: 5px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {color};
            }}
        """)

    def update_top_pods_table(self, pods, node_cpu_allocatable, node_mem_allocatable):
        self.top_pods_model.clear()
        self.top_pods_model.setHorizontalHeaderLabels([
            "Pod Name", "CPU Usage %", "CPU Req", "CPU Limit", "Mem Usage %", "Mem Req", "Mem Limit"
        ])

        for pod in pods:
            cpu_usage_percent = (pod.get('cpu_usage', 0) / pod.get('cpu_limit', 1)) * 100 if pod.get('cpu_limit', 0) > 0 else 0
            mem_usage_percent = (pod.get('mem_usage', 0) / pod.get('mem_limit', 1)) * 100 if pod.get('mem_limit', 0) > 0 else 0
            
            row = [
                QStandardItem(pod['name']),
                QStandardItem(f"{cpu_usage_percent:.2f}"),
                QStandardItem(f"{pod.get('cpu_request', 0):.2f}"),
                QStandardItem(f"{pod.get('cpu_limit', 0):.2f}"),
                QStandardItem(f"{mem_usage_percent:.2f}"),
                QStandardItem(f"{pod.get('mem_request', 0) / (1024**3):.2f}"),
                QStandardItem(f"{pod.get('mem_limit', 0) / (1024**3):.2f}")
            ]
            self.top_pods_model.appendRow(row)

        self.top_pods_table.setSortingEnabled(True)
        self.top_pods_table.sortByColumn(1, Qt.DescendingOrder)  # Sort by CPU Usage

        # Adjust column widths
        for i in range(self.top_pods_model.columnCount()):
            self.top_pods_table.resizeColumnToContents(i)

    def view_pod_logs(self):
        self.show_loading()
        selected_indexes = self.top_pods_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            self.hide_loading()
            QMessageBox.warning(self, "No Pod Selected", "Please select a pod to view logs.")
            return
        
        
        row = selected_indexes[0].row()
        pod_name = self.top_pods_model.item(row, 0).text()
        namespace = self.get_pod_namespace(pod_name)
        
        logs_dialog = QDialog(self)
        logs_dialog.setWindowTitle(f"Logs for {pod_name}")
        logs_dialog.setMinimumSize(800, 600)
        
        layout = QVBoxLayout(logs_dialog)
        
        logs_text = QTextEdit()
        logs_text.setReadOnly(True)
        layout.addWidget(logs_text)
        
        try:
            logs = self.v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
            self.hide_loading()
            logs_text.setText(logs)
        except Exception as e:
            self.hide_loading()
            logs_text.setText(f"Error fetching logs: {str(e)}")
        logs_dialog.exec_()

    def edit_pod_resources(self):
        selected_indexes = self.top_pods_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(self, "No Pod Selected", "Please select a pod to edit its resources.")
            return

        row = selected_indexes[0].row()
        pod_name = self.top_pods_model.item(row, 0).text()
        namespace = self.get_pod_namespace(pod_name)

        if namespace is None:
            QMessageBox.critical(self, "Error", f"Could not determine namespace for pod {pod_name}")
            return

        try:
            pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to retrieve pod information: {str(e)}")
            return

        owner_ref = pod.metadata.owner_references[0] if pod.metadata.owner_references else None
        if not owner_ref:
            QMessageBox.critical(self, "Error", "No owner reference found for the pod.")
            return

        controller_name = owner_ref.name
        controller_kind = owner_ref.kind

        # Traverse the owner references until we find a Deployment, StatefulSet, or DaemonSet
        while controller_kind.lower() == 'replicaset':
            try:
                replicaset = self.apps_v1.read_namespaced_replica_set(name=controller_name, namespace=namespace)
                owner_ref = replicaset.metadata.owner_references[0] if replicaset.metadata.owner_references else None
                if not owner_ref:
                    QMessageBox.critical(self, "Error", "No owner reference found for the ReplicaSet.")
                    return
                controller_name = owner_ref.name
                controller_kind = owner_ref.kind
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to retrieve ReplicaSet information: {str(e)}")
                return

        if controller_kind.lower() not in ['deployment', 'statefulset', 'daemonset']:
            QMessageBox.information(self, "Cannot Edit", f"Editing resources is only supported for Deployments, StatefulSets, and DaemonSets. This pod is controlled by a {controller_kind}.")
            return

        try:
            if controller_kind.lower() == 'deployment':
                controller = self.apps_v1.read_namespaced_deployment(name=controller_name, namespace=namespace)
            elif controller_kind.lower() == 'statefulset':
                controller = self.apps_v1.read_namespaced_stateful_set(name=controller_name, namespace=namespace)
            elif controller_kind.lower() == 'daemonset':
                controller = self.apps_v1.read_namespaced_daemon_set(name=controller_name, namespace=namespace)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to retrieve {controller_kind} information: {str(e)}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Resources for {controller_kind}: {controller_name}")
        layout = QVBoxLayout(dialog)

        # Add a label to show the controller type and name
        controller_label = QLabel(f"Controller: {controller_kind} - {controller_name}")
        controller_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(controller_label)

        container_widgets = []
        for container in controller.spec.template.spec.containers:
            group_box = QGroupBox(f"Container: {container.name}")
            group_layout = QFormLayout(group_box)
            
            cpu_request = QLineEdit(container.resources.requests.get('cpu', '0') if container.resources and container.resources.requests else '0')
            cpu_limit = QLineEdit(container.resources.limits.get('cpu', '0') if container.resources and container.resources.limits else '0')
            mem_request = QLineEdit(container.resources.requests.get('memory', '0') if container.resources and container.resources.requests else '0')
            mem_limit = QLineEdit(container.resources.limits.get('memory', '0') if container.resources and container.resources.limits else '0')
            
            group_layout.addRow("CPU Request:", cpu_request)
            group_layout.addRow("CPU Limit:", cpu_limit)
            group_layout.addRow("Memory Request:", mem_request)
            group_layout.addRow("Memory Limit:", mem_limit)
            
            layout.addWidget(group_box)
            container_widgets.append({
                'name': container.name,
                'cpu_request': cpu_request,
                'cpu_limit': cpu_limit,
                'mem_request': mem_request,
                'mem_limit': mem_limit
            })

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() == QDialog.Accepted:
            try:
                self.show_loading()
                for container, widgets in zip(controller.spec.template.spec.containers, container_widgets):
                    cpu_request = widgets['cpu_request'].text()
                    cpu_limit = widgets['cpu_limit'].text()
                    mem_request = widgets['mem_request'].text()
                    mem_limit = widgets['mem_limit'].text()
                    
                    container.resources = client.V1ResourceRequirements(
                        requests={"cpu": cpu_request, "memory": mem_request},
                        limits={"cpu": cpu_limit, "memory": mem_limit}
                    )

                if controller_kind.lower() == 'deployment':
                    self.apps_v1.patch_namespaced_deployment(name=controller_name, namespace=namespace, body=controller)
                elif controller_kind.lower() == 'statefulset':
                    self.apps_v1.patch_namespaced_stateful_set(name=controller_name, namespace=namespace, body=controller)
                elif controller_kind.lower() == 'daemonset':
                    self.apps_v1.patch_namespaced_daemon_set(name=controller_name, namespace=namespace, body=controller)
                self.hide_loading()
                QMessageBox.information(self, "Success", f"Resources updated successfully for {controller_kind}: {controller_name}")
                self.update_node_table()  # Refresh the node table after updating resources
            except Exception as e:
                self.hide_loading()
                QMessageBox.critical(self, "Error", f"Failed to update resources: {str(e)}")
                print(f"Detailed error: {traceback.format_exc()}")  # This will print the full stack trace

    def get_pod_namespace(self, pod_name):
        try:
            pods = self.v1.list_pod_for_all_namespaces(field_selector=f'metadata.name={pod_name}').items
            if pods:
                return pods[0].metadata.namespace
        except Exception as e:
            print(f"Error getting pod namespace: {e}")
        return None

    def download_node_metrics(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Node Metrics", "", "CSV Files (*.csv);;All Files (*)", options=options)
        if fileName:
            with open(fileName, 'w', newline='') as file:
                writer = csv.writer(file)
                headers = [self.node_model.headerData(i, Qt.Horizontal) for i in range(self.node_model.columnCount())]
                writer.writerow(headers)
                for row in range(self.node_model.rowCount()):
                    row_data = []
                    for column in range(self.node_model.columnCount()):
                        item = self.node_model.item(row, column)
                        if item is not None:
                            row_data.append(item.text())
                        else:
                            row_data.append('')
                    writer.writerow(row_data)
            QMessageBox.information(self, "Download Complete", "Node metrics have been saved successfully.")

    @property
    def v1(self):
        return self.parent.v1

    @property
    def custom_api(self):
        return self.parent.custom_api

    @property
    def apps_v1(self):
        return self.parent.apps_v1