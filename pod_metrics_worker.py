import sys
import base64
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
                             QComboBox, QTableView, QTextEdit, QPushButton, QSplitter, QLabel, QGridLayout,
                             QLineEdit, QStyleFactory, QStatusBar, QTabWidget,  QHeaderView, QCheckBox, QDialog, QInputDialog, QMessageBox, QDialogButtonBox, QFormLayout, QSpinBox, QTableWidget, QTableWidgetItem, QSizePolicy)
from PyQt5.QtGui import QStandardItemModel, QFont, QColor, QTextCharFormat, QStandardItem, QTextCursor, QPalette, QTextDocument
from PyQt5.QtCore import Qt, QSortFilterProxyModel, QTimer
from kubernetes import client, config
from kubernetes.stream import stream
from resource_updaters import update_pods, update_pvcs, update_statefulsets, update_deployments, update_pvs, update_secrets, update_configmaps, update_jobs, update_cronjobs, update_nodes, LogStreamerThread,  parse_k8s_cpu, parse_k8s_memory
from utils import setup_info_search
import yaml, csv, time
import sip
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QFileDialog, QMessageBox


class PodMetricsWorker(QThread):
    update_signal = pyqtSignal(int, dict, str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, v1, custom_api, namespace=None, label_selector=None):
        super().__init__()
        self.v1 = v1
        self.custom_api = custom_api
        self.namespace = namespace
        self.label_selector = label_selector
        self.is_running = True

    def run(self):
        try:
            if self.namespace:
                pods = self.v1.list_namespaced_pod(self.namespace, label_selector=self.label_selector).items
            else:
                pods = self.v1.list_pod_for_all_namespaces(label_selector=self.label_selector).items
            
            totals = {
                'cpu_usage': 0, 'cpu_request': 0, 'cpu_limit': 0,
                'memory_usage': 0, 'memory_request': 0, 'memory_limit': 0,
                'gpu_limit': 0
            }

            for i, pod in enumerate(pods):
                if not self.is_running:
                    break
                pod_metrics = self.get_pod_metrics(pod.metadata.name, pod.metadata.namespace)
                self.update_signal.emit(i, {
                    'name': pod.metadata.name,
                    'metrics': pod_metrics,
                    'status': pod.status.phase
                }, pod.metadata.namespace)

                for key in totals:
                    totals[key] += pod_metrics[key]

            if self.is_running:
                self.finished_signal.emit(totals)
        except Exception as e:
            print(f"Error in PodMetricsWorker: {str(e)}")


    def stop(self):
        self.is_running = False

    def get_pod_metrics(self, pod_name, namespace):
        try:
            pod = self.v1.read_namespaced_pod(pod_name, namespace)
            try:
                metrics = self.custom_api.get_namespaced_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="pods",
                    name=pod_name
                )
                
                cpu_usage = parse_k8s_cpu(metrics['containers'][0]['usage'].get('cpu', '0')) if metrics else 0
                memory_usage = parse_k8s_memory(metrics['containers'][0]['usage'].get('memory', '0')) if metrics else 0
            except Exception as metrics_error:
                print(f"Error fetching metrics for pod {pod_name}: {metrics_error}")
                cpu_usage = 0
                memory_usage = 0
            
            containers = pod.spec.containers[0] if pod and pod.spec and pod.spec.containers else None
            cpu_request = parse_k8s_cpu(containers.resources.requests.get('cpu', '0')) if containers and containers.resources and containers.resources.requests else 0
            cpu_limit = parse_k8s_cpu(containers.resources.limits.get('cpu', '0')) if containers and containers.resources and containers.resources.limits else 0
            memory_request = parse_k8s_memory(containers.resources.requests.get('memory', '0')) if containers and containers.resources and containers.resources.requests else 0
            memory_limit = parse_k8s_memory(containers.resources.limits.get('memory', '0')) if containers and containers.resources and containers.resources.limits else 0
            gpu_limit = float(containers.resources.limits.get('nvidia.com/gpu', '0')) if containers and containers.resources and containers.resources.limits else 0
            
            return {
                'cpu_usage': float(cpu_usage),
                'cpu_request': float(cpu_request),
                'cpu_limit': float(cpu_limit),
                'memory_usage': float(memory_usage),
                'memory_request': float(memory_request),
                'memory_limit': float(memory_limit),
                'gpu_limit': float(gpu_limit)
            }
        except Exception as e:
            print(f"Error getting pod metrics for {pod_name} in namespace {namespace}: {e}")
            return {
                'cpu_usage': 0.0, 'cpu_request': 0.0, 'cpu_limit': 0.0,
                'memory_usage': 0.0, 'memory_request': 0.0, 'memory_limit': 0.0,
                'gpu_limit': 0.0
            }