from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit
from PyQt5.QtGui import QFont, QTextCharFormat, QTextCursor
from PyQt5.QtCore import Qt, QRegExp
import yaml

import json

class EditResourceDialog(QDialog):
    def __init__(self, resource_type, name, namespace, k8s_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {resource_type} Spec")
        self.setGeometry(100, 100, 800, 600)
        self.resource_type = resource_type
        self.name = name
        self.namespace = namespace
        self.k8s_client = k8s_client
        
        layout = QVBoxLayout(self)
        
        # Add search field
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.textChanged.connect(self.highlight_search)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        self.yaml_edit = QTextEdit()
        self.yaml_edit.setPlainText(self.get_resource_spec())
        self.yaml_edit.setFont(QFont("Courier", 10))
        layout.addWidget(self.yaml_edit)
        
        button_layout = QHBoxLayout()
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)

    def get_resource_spec(self):
        try:
            spec = {}
            if self.resource_type == "Pods":
                resource = self.k8s_client.v1.read_namespaced_pod(self.name, self.namespace)
                spec = {
                    'containers': [{
                        'name': c.name,
                        'image': c.image,
                        'resources': c.resources.to_dict() if c.resources else {}
                    } for c in resource.spec.containers]
                }
            elif self.resource_type == "Deployments":
                resource = self.k8s_client.apps_v1.read_namespaced_deployment(self.name, self.namespace)
                spec = {
                    'replicas': resource.spec.replicas,
                    'template': {
                        'spec': {
                            'containers': [{
                                'name': c.name,
                                'image': c.image,
                                'resources': c.resources.to_dict() if c.resources else {}
                            } for c in resource.spec.template.spec.containers]
                        }
                    }
                }
            elif self.resource_type == "StatefulSets":
                resource = self.k8s_client.apps_v1.read_namespaced_stateful_set(self.name, self.namespace)
                spec = {
                    'replicas': resource.spec.replicas,
                    'template': {
                        'spec': {
                            'containers': [{
                                'name': c.name,
                                'image': c.image,
                                'resources': c.resources.to_dict() if c.resources else {}
                            } for c in resource.spec.template.spec.containers]
                        }
                    }
                }
            elif self.resource_type == "Jobs":
                resource = self.k8s_client.batch_v1.read_namespaced_job(self.name, self.namespace)
                spec = {
                    'template': {
                        'spec': {
                            'containers': [{
                                'name': c.name,
                                'image': c.image,
                                'resources': c.resources.to_dict() if c.resources else {}
                            } for c in resource.spec.template.spec.containers]
                        }
                    }
                }
            elif self.resource_type == "CronJobs":
                resource = self.k8s_client.batch_v1.read_namespaced_cron_job(self.name, self.namespace)
                spec = {
                    'schedule': resource.spec.schedule,
                    'jobTemplate': {
                        'spec': {
                            'template': {
                                'spec': {
                                    'containers': [{
                                        'name': c.name,
                                        'image': c.image,
                                        'resources': c.resources.to_dict() if c.resources else {}
                                    } for c in resource.spec.job_template.spec.template.spec.containers]
                                }
                            }
                        }
                    }
                }
            elif self.resource_type == "PVC":
                resource = self.k8s_client.v1.read_namespaced_persistent_volume_claim(self.name, self.namespace)
                spec = {
                    'accessModes': resource.spec.access_modes,
                    'resources': resource.spec.resources.to_dict()
                }
            elif self.resource_type == "PV":
                resource = self.k8s_client.v1.read_persistent_volume(self.name)
                spec = {
                    'capacity': resource.spec.capacity,
                    'accessModes': resource.spec.access_modes,
                    'persistentVolumeReclaimPolicy': resource.spec.persistent_volume_reclaim_policy
                }
            elif self.resource_type == "Secrets":
                resource = self.k8s_client.v1.read_namespaced_secret(self.name, self.namespace)
                spec = {
                    'type': resource.type,
                    'data': resource.data
                }
            elif self.resource_type == "ConfigMaps":
                resource = self.k8s_client.v1.read_namespaced_config_map(self.name, self.namespace)
                spec = {
                    'data': resource.data
                }
            elif self.resource_type == "Services":
                resource = self.k8s_client.v1.read_namespaced_service(self.name, self.namespace)
                spec = {
                    'ports': [p.to_dict() for p in resource.spec.ports],
                    'selector': resource.spec.selector
                }
            elif self.resource_type == "Nodes":
                resource = self.k8s_client.v1.read_node(self.name)
                spec = {
                    'taints': [t.to_dict() for t in resource.spec.taints] if resource.spec.taints else [],
                    'unschedulable': resource.spec.unschedulable
                }
            else:
                raise ValueError(f"Unsupported resource type: {self.resource_type}")
            return yaml.dump({'spec': spec}, default_flow_style=False)
        except Exception as e:
            return f"Error fetching resource spec: {str(e)}"

    def get_edited_yaml(self):
        return self.yaml_edit.toPlainText()

    def highlight_search(self, text):
        cursor = self.yaml_edit.textCursor()
        format = QTextCharFormat()
        format.setBackground(Qt.yellow)

        # Reset to default
        cursor.select(QTextCursor.Document)
        cursor.setCharFormat(QTextCharFormat())
        cursor.clearSelection()

        if not text:
            return

        regex = QRegExp(text)
        pos = 0
        index = regex.indexIn(self.yaml_edit.toPlainText(), pos)
        while index != -1:
            cursor.setPosition(index)
            cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, len(text))
            cursor.mergeCharFormat(format)
            pos = index + regex.matchedLength()
            index = regex.indexIn(self.yaml_edit.toPlainText(), pos)
