import sys, json, signal, os, psutil
import subprocess
import threading
import traceback
import requests
import time
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget, QStyleFactory, QHBoxLayout,
    QComboBox, QLabel, QPushButton, QMessageBox, QDialog, QFrame
)
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt, QTimer
from kubernetes import client, config
from view_tab import ViewTab
from node_metrics_tab import NodeMetricsTab
from pod_metrics_tab import PodMetricsTab
from network_graph_tab import NetworkGraphTab
from custom_resources_tab import CustomResourcesTab
from github_insights_tab import GitHubInsightsTab
from jenkins_tab import JenkinsTab
from jira_insights_tab import JiraInsightsTab   
from system_tab import SystemTab
from helper_view_tab.create_resource_dialog import CreateResourceDialog
import os
from prometheus_api_client import PrometheusConnect
from requests.exceptions import RequestException, Timeout
import socket
import subprocess
import time

os.environ['QT_MAC_WANTS_LAYER'] = '1'

QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)

PROMETHEUS_PORT = 29090



def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def is_prometheus_on_port(port):
    try:
        response = requests.get(f"http://localhost:{port}/-/healthy")
        return response.status_code == 200
    except requests.RequestException:
        return False

def get_available_port(start_port=29090, max_port=29100):
    for port in range(start_port, max_port + 1):
        if not is_port_in_use(port):
            return port
    return None


def kill_port_forward_processes(pattern):
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'kubectl' in proc.info['name'] and 'port-forward' in proc.info['cmdline'] and any(pattern in arg for arg in proc.info['cmdline']):
                proc.terminate()
                proc.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            pass
    
class ClusterMetricsBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("Initializing ClusterMetricsBar...")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        self.layout.setSpacing(20)

        self.pods_label = QLabel("Pods: -/-")
        self.ram_label = QLabel("RAM: -/- GB")
        self.cpu_label = QLabel("CPU: -/- cores")
        self.disk_label = QLabel("Disk: -/- GB")
        self.nodes_label = QLabel("Nodes: -/-")
        self.namespaces_label = QLabel("Namespaces: -")

        for label in [self.pods_label, self.ram_label, self.cpu_label, self.disk_label, self.nodes_label, self.namespaces_label]:
            self.layout.addWidget(label)
            if label != self.namespaces_label:
                separator = QFrame()
                separator.setFrameShape(QFrame.VLine)
                self.layout.addWidget(separator)

        self.layout.addStretch()


        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_metrics)
        self.timer.start(30000)  # Update every 30 seconds

        self.prometheus_url = None
        self.prom = None
        self.prometheus_status = QLabel("Prometheus: Disconnected")
        self.layout.addWidget(self.prometheus_status)
        
        self.setup_prometheus_connection()
    
    def handle_metric_error(self):
        for label in [self.pods_label, self.ram_label, self.cpu_label, self.disk_label, self.nodes_label, self.namespaces_label]:
            label.setText(label.text().split(':')[0] + ": N/A")
        
        # Check if port forwarding is active and restart if not
        self.setup_prometheus_connection()

    def connect_to_prometheus(self):
        try:
            self.prom = PrometheusConnect(url=self.prometheus_url, disable_ssl=True)
            print("Successfully connected to Prometheus")
            self.update_metrics()
        except Exception as e:
            print(f"Error connecting to Prometheus: {e}")
            self.prom = None
    
    def setup_prometheus_connection(self):
        print("Setting up Prometheus connection...")
        try:
            self.prometheus_url = self.parent().get_prometheus_url()
            if self.prometheus_url:
                self.prom = PrometheusConnect(url=self.prometheus_url, disable_ssl=True)
                print("Successfully connected to Prometheus")
                self.prometheus_status.setText("Prometheus: Connected")
            else:
                print("Failed to get Prometheus URL")
                self.prom = None
                self.prometheus_status.setText("Prometheus: Unavailable")
        except Exception as e:
            print(f"Error connecting to Prometheus: {e}")
            self.prom = None
            self.prometheus_status.setText("Prometheus: Error")


    def update_metrics(self):
        if not self.prom:
            self.handle_metric_error()
            return

        try:
            timeout = 10  # seconds

            def query_with_timeout(query):
                result = None
                exception = None

                def target():
                    nonlocal result, exception
                    try:
                        result = self.prom.custom_query(query)
                    except Exception as e:
                        exception = e

                thread = threading.Thread(target=target)
                thread.start()
                thread.join(timeout)

                if thread.is_alive():
                    print(f"Query timed out after {timeout} seconds")
                    return None
                if exception:
                    raise exception
                return result

            # Get pod count
            running_pods = query_with_timeout("count(kube_pod_status_phase{phase='Running'})")
            total_pods = query_with_timeout("count(kube_pod_info)")
            if running_pods and total_pods:
                self.pods_label.setText(f"Pods: {running_pods[0]['value'][1]}/{total_pods[0]['value'][1]}")

            # Get node count
            ready_nodes = query_with_timeout("count(kube_node_status_condition{condition='Ready',status='true'})")
            total_nodes = query_with_timeout("count(kube_node_info)")
            if ready_nodes and total_nodes:
                self.nodes_label.setText(f"Nodes: {ready_nodes[0]['value'][1]}/{total_nodes[0]['value'][1]}")

            # Get namespace count
            namespaces = query_with_timeout("count(kube_namespace_created)")
            if namespaces:
                self.namespaces_label.setText(f"Namespaces: {namespaces[0]['value'][1]}")

            # Get CPU usage
            cpu_usage = query_with_timeout("sum(rate(container_cpu_usage_seconds_total[5m]))")
            cpu_capacity = query_with_timeout("sum(machine_cpu_cores)")
            if cpu_usage and cpu_capacity:
                self.cpu_label.setText(f"CPU: {float(cpu_usage[0]['value'][1]):.2f}/{float(cpu_capacity[0]['value'][1]):.2f} cores")

            # Get memory usage
            memory_usage = query_with_timeout("sum(container_memory_usage_bytes) / (1024*1024*1024)")
            memory_capacity = query_with_timeout("sum(machine_memory_bytes) / (1024*1024*1024)")
            if memory_usage and memory_capacity:
                self.ram_label.setText(f"RAM: {float(memory_usage[0]['value'][1]):.2f}/{float(memory_capacity[0]['value'][1]):.2f} GB")

            # Get disk usage (this might need to be adjusted based on your specific storage setup)
            disk_usage = query_with_timeout("sum(container_fs_usage_bytes) / (1024*1024*1024)")
            disk_capacity = query_with_timeout("sum(container_fs_limit_bytes) / (1024*1024*1024)")
            if disk_usage and disk_capacity:
                self.disk_label.setText(f"Disk: {float(disk_usage[0]['value'][1]):.2f}/{float(disk_capacity[0]['value'][1]):.2f} GB")

            for label in [self.pods_label, self.ram_label, self.cpu_label, self.disk_label, self.nodes_label, self.namespaces_label]:
                label.setStyleSheet("color: #FFFFFF; font-size: 16px; font-weight: bold;")

            
        except requests.exceptions.ConnectionError:
            print("Connection to Prometheus failed, attempting to re-establish...")
            self.setup_prometheus_connection()
        except Exception as e:
            print(f"Error updating metrics: {e}")
            self.handle_metric_error()

    def handle_metric_error(self):
        for label in [self.pods_label, self.ram_label, self.cpu_label, self.disk_label, self.nodes_label, self.namespaces_label]:
            label.setText(label.text().split(':')[0] + ": N/A")
        self.prometheus_status.setText("Prometheus: Disconnected")

class KubernetesGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        print("Initializing KubernetesGUI...")
        self.setWindowTitle("Kubernetes Debugger Pro")
        self.showMaximized()

        self.clusters = self.load_clusters()
        self.current_cluster = None
        self.pod_metrics_worker = None
        
        self.prometheus_port_forward_active = False
        self.prometheus_port_forward_process = None
        
        # Initialize Kubernetes API clients
        self.load_current_cluster()
        
        try:
            self.prom = self.initialize_prometheus_client()
        except Exception as e:
            print(f"Failed to initialize Prometheus client: {e}")
            self.prom = None

        self.init_ui()
        self.set_dark_mode()
        print("KubernetesGUI initialization complete")
    
    def initialize_prometheus_client(self):
        prometheus_url = self.get_prometheus_url()
        if prometheus_url:
            try:
                return PrometheusConnect(url=prometheus_url, disable_ssl=True)
            except Exception as e:
                print(f"Failed to initialize Prometheus client: {str(e)}")
                # Handle the error appropriately
                return None
        else:
            print("Failed to get Prometheus URL")
            return None


    def init_ui(self):
        print("Initializing UI...")
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(0)
        self.setCentralWidget(central_widget)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setElideMode(Qt.ElideRight)

        self.view_tab = ViewTab(self)
        self.node_metrics_tab = None
        self.pod_metrics_tab = None
        self.custom_resources_tab = None
        self.network_graph_tab = None
        self.github_insights_tab = None
        self.jenkins_tab = None
        self.jira_insights_tab = None
        self.system_tab = None

        self.tab_widget.addTab(self.view_tab, "Resources")
        self.tab_widget.addTab(QWidget(), "Nodes")
        self.tab_widget.addTab(QWidget(), "Pods")
        self.tab_widget.addTab(QWidget(), "CRs")
        self.tab_widget.addTab(QWidget(), "Network")
        self.tab_widget.addTab(QWidget(), "Github")
        self.tab_widget.addTab(QWidget(), "JIRA")
        self.tab_widget.addTab(QWidget(), "Jenkins")
        self.tab_widget.addTab(QWidget(), "System")

        top_bar = self.create_top_bar()
        main_layout.addWidget(top_bar)
        main_layout.addWidget(self.tab_widget)

        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        self.statusBar().setStyleSheet("QStatusBar { font-size: 12px; }")
        self.statusBar().showMessage("Checking cluster connectivity...")

        if self.check_cluster_connectivity():
            self.statusBar().showMessage("Connected to cluster")
        else:
            self.statusBar().showMessage("Unable to connect to cluster")
            self.show_cluster_unreachable_message()
            self.disable_cluster_dependent_ui()

        self.statusBar().setStyleSheet("QStatusBar { font-size: 12px; }")
        self.statusBar().showMessage("Ready")
        print("UI initialization complete")

    def on_tab_changed(self, index):
        print(f"Changing to tab index: {index}")
        try:
            if index == 1 and not self.node_metrics_tab:
                self.node_metrics_tab = NodeMetricsTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.node_metrics_tab, "Nodes")
                self.tab_widget.setCurrentIndex(index)
            elif index == 2 and not self.pod_metrics_tab:
                self.pod_metrics_tab = PodMetricsTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.pod_metrics_tab, "Pods")
                self.tab_widget.setCurrentIndex(index)
            elif index == 3 and not self.custom_resources_tab:
                self.custom_resources_tab = CustomResourcesTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.custom_resources_tab, "CRs")
                self.tab_widget.setCurrentIndex(index)
            elif index == 4 and not self.network_graph_tab:
                self.network_graph_tab = NetworkGraphTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.network_graph_tab, "Network")
                self.tab_widget.setCurrentIndex(index)
            elif index == 5 and not self.github_insights_tab:
                self.github_insights_tab = GitHubInsightsTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.github_insights_tab, "Github")
                self.tab_widget.setCurrentIndex(index)
            elif index == 6 and not self.jira_insights_tab:
                self.jira_insights_tab = JiraInsightsTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.jira_insights_tab, "JIRA")
                self.tab_widget.setCurrentIndex(index)
            elif index == 7 and not self.jenkins_tab:
                self.jenkins_tab = JenkinsTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.jenkins_tab, "Jenkins")
                self.tab_widget.setCurrentIndex(index)
            elif index == 8 and not self.system_tab:
                self.system_tab = SystemTab(self)
                self.tab_widget.removeTab(index)
                self.tab_widget.insertTab(index, self.system_tab, "System")
                self.tab_widget.setCurrentIndex(index)
            print(f"Successfully changed to tab index: {index}")
        except Exception as e:
            print(f"Error switching tabs: {e}")
            traceback.print_exc()

    def show_cluster_unreachable_message(self):
        QMessageBox.warning(self, "Cluster Unreachable", 
                            "Unable to connect to the Kubernetes cluster. "
                            "Please check your connection and credentials.")

    def disable_cluster_dependent_ui(self):
        self.cluster_metrics_bar.setEnabled(False)
        self.cluster_combo.setEnabled(False)
        self.auto_refresh_combo.setEnabled(False)
        self.view_tab.disable_cluster_dependent_ui()
        for label in [self.cluster_metrics_bar.pods_label, self.cluster_metrics_bar.ram_label, 
                  self.cluster_metrics_bar.cpu_label, self.cluster_metrics_bar.disk_label,
                  self.cluster_metrics_bar.nodes_label, self.cluster_metrics_bar.namespaces_label]:
            label.setEnabled(False)

    def enable_cluster_dependent_ui(self):
        self.cluster_metrics_bar.setEnabled(True)
        self.cluster_combo.setEnabled(True)
        self.auto_refresh_combo.setEnabled(True)
        self.view_tab.enable_cluster_dependent_ui()
        for label in [self.cluster_metrics_bar.pods_label, self.cluster_metrics_bar.ram_label, 
                  self.cluster_metrics_bar.cpu_label, self.cluster_metrics_bar.disk_label,
                  self.cluster_metrics_bar.nodes_label, self.cluster_metrics_bar.namespaces_label]:
            label.setEnabled(True)
    
    def change_cluster(self, cluster_name):
        try:
            self.current_cluster = cluster_name
            config.load_kube_config(context=cluster_name)
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.batch_v1 = client.BatchV1Api()
            self.custom_api = client.CustomObjectsApi()
            
            if self.check_cluster_connectivity():
                self.statusBar().showMessage(f"Connected to cluster: {cluster_name}")
                self.enable_cluster_dependent_ui()
            else:
                self.statusBar().showMessage(f"Unable to connect to cluster: {cluster_name}")
                self.show_cluster_unreachable_message()
                self.disable_cluster_dependent_ui()
        except config.config_exception.ConfigException as e:
            QMessageBox.critical(self, "Error", f"Failed to change cluster: {str(e)}")

    def check_cluster_connectivity(self):
        try:
            self.v1.list_namespace(limit=1)
            return True
        except Exception as e:
            print(f"Error connecting to cluster: {str(e)}")
            return False

    def create_top_bar(self):
        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(20)
        
        self.cluster_metrics_bar = ClusterMetricsBar(self)
        top_layout.addWidget(self.cluster_metrics_bar)
        
        top_layout.addStretch()
        
        cluster_label = QLabel("Cluster:")
        self.cluster_combo = QComboBox()
        self.cluster_combo.addItems(list(self.clusters.keys()))
        self.cluster_combo.currentTextChanged.connect(self.change_cluster)
        self.cluster_combo.setFixedWidth(150)

        auto_refresh_label = QLabel("Auto-refresh:")
        self.auto_refresh_combo = QComboBox()
        self.auto_refresh_combo.addItems(["Off", "5s", "10s", "30s"])
        self.auto_refresh_combo.currentTextChanged.connect(self.set_auto_refresh)
        self.auto_refresh_combo.setFixedWidth(80)
        
        top_layout.addWidget(cluster_label)
        top_layout.addWidget(self.cluster_combo)
        top_layout.addWidget(auto_refresh_label)
        top_layout.addWidget(self.auto_refresh_combo)
        
        create_resource_button = QPushButton("Create Resource")
        create_resource_button.setFixedSize(150, 30)
        create_resource_button.clicked.connect(self.create_new_resource)

        top_layout.addWidget(create_resource_button, alignment=Qt.AlignRight)
        
        theme_label = QLabel("Theme:")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light", "Sunset", "Royal Purple"])
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        self.theme_combo.setFixedWidth(150)

        top_layout.addWidget(theme_label)
        top_layout.addWidget(self.theme_combo)

        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background-color: #333333; border-bottom: 1px solid #505050;")
        return top_bar

    def create_new_resource(self):
        namespaces = self.view_tab.load_namespaces()
        if namespaces is None:
            QMessageBox.critical(self, "Error", "Failed to load namespaces.")
            return
        dialog = CreateResourceDialog(namespaces, self)
        if dialog.exec_() == QDialog.Accepted:
            namespace = dialog.get_namespace()
            resource_yaml = dialog.get_resource_yaml()
            self.view_tab.apply_new_resource(namespace, resource_yaml)

    def set_auto_refresh(self, value):
        # Implement auto-refresh logic here
        pass

    def load_clusters(self):
        try:
            config.load_kube_config()
            contexts, _ = config.list_kube_config_contexts()
            return {context['name']: context['name'] for context in contexts}
        except config.config_exception.ConfigException as e:
            QMessageBox.critical(self, "Error", f"Failed to load Kubernetes config: {str(e)}")
            return {}

    def load_current_cluster(self):
        try:
            if self.current_cluster:
                config.load_kube_config(context=self.current_cluster)
            else:
                config.load_kube_config()
            
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.batch_v1 = client.BatchV1Api()
            self.custom_api = client.CustomObjectsApi()
        except config.config_exception.ConfigException as e:
            QMessageBox.critical(self, "Error", f"Failed to load cluster configuration: {str(e)}")

    

    def stop_all_threads(self):
        if self.pod_metrics_worker and self.pod_metrics_worker.isRunning():
            self.pod_metrics_worker.stop()
            self.pod_metrics_worker.wait()

        self.view_tab.stop_log_streaming()
    
    def kill_process_by_command(self, command_pattern):
        try:
            # Find PIDs of processes matching the command pattern
            pids = subprocess.check_output(["pgrep", "-f", command_pattern]).decode().split()
            
            # Terminate each process
            for pid in pids:
                pid = int(pid)
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"Terminated process {pid}")
                except ProcessLookupError:
                    print(f"Process {pid} not found")
                except PermissionError:
                    print(f"Permission denied to terminate process {pid}")
        except subprocess.CalledProcessError:
            # No matching processes found
            pass
    
    def stop_all_port_forwarding(self):
        # Stop Prometheus port forwarding
        if self.prometheus_port_forward_active:
            try:
                self.prometheus_port_forward_process.terminate()
                self.prometheus_port_forward_process.wait(timeout=5)
            except psutil.TimeoutExpired:
                self.prometheus_port_forward_process.kill()
            self.prometheus_port_forward_active = False
            if hasattr(self, 'view_tab'):
                key = "prometheus/prometheus-operated"
                if key in self.view_tab.port_forwarding_dict:
                    del self.view_tab.port_forwarding_dict[key]
                    self.view_tab.save_port_forwarding()
        
        # Stop service port forwarding
        if hasattr(self, 'view_tab'):
            self.view_tab.stop_all_port_forwarding()
        
        # Kill any remaining kubectl port-forward processes
        kill_port_forward_processes("kubectl port-forward")

    def closeEvent(self, event):
        print("Cleaning up...")
        self.stop_all_port_forwarding()
        self.stop_all_threads()
        super().closeEvent(event)
    
    def set_common_styles(self):
        self.setStyleSheet(self.styleSheet() + """
            QTabBar::tab {
                font-size: 16px;
                height: 40px;
                padding: 0 15px;
                min-width: 120px;
            }
            QTabWidget::pane {
                border-top: 2px solid #3c3c3c;
            }
            QTabBar::tab:selected {
                font-weight: bold;
            }
            QTableView {
                font-size: 14px;
            }
            QTableView::item {
                padding: 5px;
            }
            QHeaderView::section {
                font-size: 16px;
                padding: 5px;
            }
            QWidget {
                font-size: 14px;
            }
            QPushButton {
                font-size: 14px;
                padding: 8px 12px;
            }
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
                font-size: 14px;
                padding: 5px;
            }
        """)

    def set_royal_purple_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(40, 20, 60))
        palette.setColor(QPalette.WindowText, QColor(230, 230, 250))
        palette.setColor(QPalette.Base, QColor(30, 15, 45))
        palette.setColor(QPalette.AlternateBase, QColor(50, 25, 75))
        palette.setColor(QPalette.ToolTipBase, QColor(40, 20, 60))
        palette.setColor(QPalette.ToolTipText, QColor(230, 230, 250))
        palette.setColor(QPalette.Text, QColor(230, 230, 250))
        palette.setColor(QPalette.Button, QColor(60, 30, 90))
        palette.setColor(QPalette.ButtonText, QColor(230, 230, 250))
        palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
        palette.setColor(QPalette.Highlight, QColor(128, 0, 128))
        palette.setColor(QPalette.HighlightedText, QColor(230, 230, 250))

        self.setPalette(palette)

        self.setStyleSheet("""
            QWidget { 
                font-family: 'Baskerville', serif; 
                color: #e6e6fa;
                background-color: #28143c;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #1e0f2d;
                color: #e6e6fa;
                border: 1px solid #800080;
            }
            QGroupBox {
                border: 2px solid #800080;
            }
            QGroupBox::title {
                color: #e6e6fa;
            }
            QComboBox, QLineEdit { 
                background-color: #1e0f2d; 
                color: #e6e6fa;
                border: 1px solid #800080;
            }
            QTableView { 
                gridline-color: #800080; 
                background-color: #1e0f2d;
                color: #e6e6fa;
                alternate-background-color: #28143c;
            }
            QHeaderView::section {
                background-color: #28143c;
                color: #e6e6fa;
                border: 1px solid #800080;
            }
            QPushButton {
                background-color: #800080;
                color: #e6e6fa;
            }
            QPushButton:hover {
                background-color: #9932cc;
            }
            QPushButton:pressed {
                background-color: #4b0082;
            }
            QTabWidget::pane {
                border: 1px solid #800080;
                background-color: #1e0f2d;
            }
            QTabBar::tab {
                background-color: #28143c;
                color: #e6e6fa;
                border: 1px solid #800080;
            }
            QTabBar::tab:selected, QTabBar::tab:hover {
                background-color: #1e0f2d;
                color: #9932cc;
            }
            QStatusBar {
                background-color: #28143c;
                color: #e6e6fa;
            }
            QScrollBar:vertical {
                border: none;
                background: #3c1f5c;
                width: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #800080;
                min-height: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #3c1f5c;
                height: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #800080;
                min-width: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.set_common_styles()

    def set_light_mode(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(240, 240, 245))
        palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.AlternateBase, QColor(245, 245, 250))
        palette.setColor(QPalette.ToolTipBase, QColor(240, 240, 245))
        palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.Button, QColor(230, 230, 235))
        palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.Highlight, QColor(0, 120, 215))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

        self.setPalette(palette)

        self.setStyleSheet("""
            QWidget { 
                font-family: 'Baskerville', serif; 
                color: #000000;
                background-color: #f0f0f5;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #d0d0d5;
            }
            QGroupBox {
                border: 2px solid #d0d0d5;
            }
            QGroupBox::title {
                color: #000000;
            }
            QComboBox, QLineEdit { 
                background-color: #ffffff; 
                color: #000000;
                border: 1px solid #d0d0d5;
            }
            QTableView { 
                gridline-color: #d0d0d5; 
                background-color: #ffffff;
                color: #000000;
                alternate-background-color: #f5f5fa;
            }
            QHeaderView::section {
                background-color: #e6e6eb;
                color: #000000;
                border: 1px solid #d0d0d5;
            }
            QPushButton {
                background-color: #0078d7;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #1e90ff;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QTabWidget::pane {
                border: 1px solid #d0d0d5;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #e6e6eb;
                color: #000000;
                border: 1px solid #d0d0d5;
            }
            QTabBar::tab:selected, QTabBar::tab:hover {
                background-color: #ffffff;
                color: #0078d7;
            }
            QStatusBar {
                background-color: #e6e6eb;
                color: #000000;
            }
            QScrollBar:vertical {
                border: none;
                background: #d0d0d5;
                width: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #0078d7;
                min-height: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #d0d0d5;
                height: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #0078d7;
                min-width: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.set_common_styles()

    def set_dark_mode(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.Base, QColor(45, 45, 45))
        palette.setColor(QPalette.AlternateBase, QColor(50, 50, 50))
        palette.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
        palette.setColor(QPalette.ToolTipText, QColor(220, 220, 220))
        palette.setColor(QPalette.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.Button, QColor(60, 60, 60))
        palette.setColor(QPalette.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, QColor(220, 220, 220))

        self.setPalette(palette)

        self.setStyleSheet("""
            QWidget { 
                font-family: 'Baskerville', serif; 
                color: #dcdcdc;
                background-color: #1e1e1e;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #2d2d2d;
                color: #dcdcdc;
                border: 1px solid #505050;
            }
            QGroupBox {
                border: 2px solid #505050;
            }
            QGroupBox::title {
                color: #dcdcdc;
            }
            QComboBox, QLineEdit { 
                background-color: #2d2d2d; 
                color: #dcdcdc;
                border: 1px solid #505050;
            }
            QTableView { 
                gridline-color: #505050; 
                background-color: #2d2d2d;
                color: #dcdcdc;
                alternate-background-color: #323232;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                color: #dcdcdc;
                border: 1px solid #505050;
            }
            QPushButton {
                background-color: #2a82da;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #3c95ea;
            }
            QPushButton:pressed {
                background-color: #1c5a99;
            }
            QTabWidget::pane {
                border: 1px solid #505050;
                background-color: #2d2d2d;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #dcdcdc;
                border: 1px solid #505050;
            }
            QTabBar::tab:selected, QTabBar::tab:hover {
                background-color: #2d2d2d;
                color: #2a82da;
            }
            QStatusBar {
                background-color: #3c3c3c;
                color: #dcdcdc;
            }
            QScrollBar:vertical {
                border: none;
                background: #3c3c3c;
                width: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #2a82da;
                min-height: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #3c3c3c;
                height: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #2a82da;
                min-width: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.set_common_styles()

    def set_default_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(188, 158, 130))  # LV Tan
        palette.setColor(QPalette.WindowText, QColor(67, 45, 31))  # Dark Brown
        palette.setColor(QPalette.Base, QColor(255, 255, 255))  # White
        palette.setColor(QPalette.AlternateBase, QColor(235, 220, 200))  # Light Tan
        palette.setColor(QPalette.ToolTipBase, QColor(188, 158, 130))
        palette.setColor(QPalette.ToolTipText, QColor(67, 45, 31))
        palette.setColor(QPalette.Text, QColor(67, 45, 31))
        palette.setColor(QPalette.Button, QColor(188, 158, 130))
        palette.setColor(QPalette.ButtonText, QColor(67, 45, 31))
        palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
        palette.setColor(QPalette.Highlight, QColor(140, 107, 70))  # Darker


        self.setPalette(palette)

        self.setStyleSheet("""
            QWidget { 
                font-family: 'Baskerville', serif; 
                color: #432d1f;
                background-color: #bc9e82;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #ffffff;
                color: #432d1f;
                border: 1px solid #8c6b46;
            }
            QGroupBox {
                border: 2px solid #8c6b46;
            }
            QGroupBox::title {
                color: #432d1f;
            }
            QComboBox, QLineEdit { 
                background-color: #ffffff; 
                color: #432d1f;
                border: 1px solid #8c6b46;
            }
            QTableView { 
                gridline-color: #8c6b46; 
                background-color: #ffffff;
                color: #432d1f;
                alternate-background-color: #ebdcc8;
            }
            QHeaderView::section {
                background-color: #bc9e82;
                color: #432d1f;
                border: 1px solid #8c6b46;
            }
            QPushButton {
                background-color: #8c6b46;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #a47d53;
            }
            QPushButton:pressed {
                background-color: #745939;
            }
            QTabWidget::pane {
                border: 1px solid #8c6b46;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #bc9e82;
                color: #432d1f;
                border: 1px solid #8c6b46;
            }
            QTabBar::tab:selected, QTabBar::tab:hover {
                background-color: #ffffff;
                color: #8c6b46;
            }
            QStatusBar {
                background-color: #bc9e82;
                color: #432d1f;
            }
            QScrollBar:vertical {
                border: none;
                background: #d4bc9f;
                width: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #8c6b46;
                min-height: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #d4bc9f;
                height: 14px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:horizontal {
                background: #8c6b46;
                min-width: 30px;
                border-radius: 7px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.set_common_styles()
    
    def get_prometheus_url(self):
        if self.prometheus_port_forward_active:
            return f"http://localhost:{self.prometheus_port_forward_process.cmdline()[-1].split(':')[0]}"

        print("Setting up port-forwarding for Prometheus...")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                available_port = get_available_port(PROMETHEUS_PORT)
                if not available_port:
                    print("No available ports found")
                    return None

                # Kill any existing port-forward processes
                kill_port_forward_processes(f"kubectl port-forward.*{available_port}:9090")

                # Start port-forwarding in the background
                process = subprocess.Popen(
                    ["kubectl", "port-forward", "-n", "prometheus", "service/prometheus-operated", f"{available_port}:9090"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                print(f"Port-forwarding set up on port {available_port}")
                
                # Wait for the port to become available
                for _ in range(10):  # Try for 10 seconds
                    if is_port_in_use(available_port):
                        self.update_prometheus_port_forwarding(available_port, process.pid)
                        return f"http://localhost:{available_port}"
                    time.sleep(1)
                
                print("Timed out waiting for port-forwarding to establish")
            except Exception as e:
                print(f"Error setting up port-forwarding: {e}")
            
            print(f"Retrying... (Attempt {attempt + 1}/{max_retries})")
        
        print("Failed to set up port-forwarding after multiple attempts")
        return None

    def update_prometheus_port_forwarding(self, port, pid):
        if hasattr(self, 'view_tab'):
            key = "prometheus/prometheus-operated"
            self.view_tab.port_forwarding_dict[key] = (port, pid)
            self.view_tab.save_port_forwarding()
            self.prometheus_port_forward_active = True
            self.prometheus_port_forward_process = psutil.Process(pid)
            self.view_tab.update_resources()  # Refresh the table to show the new port forwarding status

    def update_top_bar_theme(self):
        # Get the current palette and style
        palette = self.palette()
        style = self.styleSheet()

        # Update the top bar widget
        top_bar = self.centralWidget().layout().itemAt(0).widget()
        top_bar.setPalette(palette)
        top_bar.setStyleSheet(style)

        # Update the cluster metrics bar
        self.cluster_metrics_bar.setPalette(palette)
        self.cluster_metrics_bar.setStyleSheet(style)

        # Update labels and buttons in the top bar
        for i in range(top_bar.layout().count()):
            item = top_bar.layout().itemAt(i).widget()
            if isinstance(item, (QLabel, QPushButton, QComboBox)):
                item.setPalette(palette)
                item.setStyleSheet(style)

        # Specifically update the Create Resource button to match theme buttons
        create_resource_button = top_bar.layout().itemAt(5).widget()
        button_style = self.styleSheet().split("QPushButton {")[1].split("}")[0]
        create_resource_button.setStyleSheet(f"QPushButton {{ {button_style} }}")

        # Update the cluster metrics labels
        for label in [self.cluster_metrics_bar.pods_label, self.cluster_metrics_bar.ram_label, 
                    self.cluster_metrics_bar.cpu_label, self.cluster_metrics_bar.disk_label,
                    self.cluster_metrics_bar.nodes_label, self.cluster_metrics_bar.namespaces_label]:
            label.setPalette(palette)
            label.setStyleSheet(style)

    def change_theme(self, theme):
        if theme == "Light":
            self.set_light_mode()
        elif theme == "Dark":
            self.set_dark_mode()
        elif theme == "Royal Purple":
            self.set_royal_purple_theme()
        elif theme == "Sunset":
            self.set_default_theme()
        
        self.update_top_bar_theme()