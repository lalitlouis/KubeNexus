from PyQt5.QtGui import QStandardItem, QBrush, QColor
from utils import parse_k8s_cpu, parse_k8s_memory, get_color_for_usage
from datetime import datetime, timezone
from PyQt5.QtCore import QObject, pyqtSignal, QThread
from kubernetes import watch
import time

def add_age_column(model, creation_timestamp, row, column):
    age = calculate_age(creation_timestamp)
    model.setItem(row, column, QStandardItem(age))

def calculate_age(creation_timestamp):
    now = datetime.now(timezone.utc)
    age = now - creation_timestamp
    days, seconds = age.days, age.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"{days}d{hours}h"
    elif hours > 0:
        return f"{hours}h{minutes}m"
    else:
        return f"{minutes}m"

def update_pods(gui, namespaces, model):
    model.setColumnCount(7)  # Not 9, as we'll add the Action column in the main GUI
    model.setHorizontalHeaderLabels(["Namespace", "Pod Name", "Ready", "Status", "Restarts", "Age", "Node"])
    
    row = 0
    for namespace in namespaces:
        pods = gui.v1.list_namespaced_pod(namespace)
        for pod in pods.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(pod.metadata.name))
            
            # Ready status
            container_statuses = pod.status.container_statuses or []
            ready_containers = sum(status.ready for status in container_statuses)
            total_containers = len(container_statuses)
            ready_item = QStandardItem(f"{ready_containers}/{total_containers}")
            if ready_containers == total_containers:
                ready_item.setForeground(QBrush(QColor("green")))
            else:
                ready_item.setForeground(QBrush(QColor("red")))
            model.setItem(row, 2, ready_item)
            
            model.setItem(row, 3, QStandardItem(pod.status.phase))
            
            # Restarts
            restarts = sum(status.restart_count for status in container_statuses)
            model.setItem(row, 4, QStandardItem(str(restarts)))
            
            # Age
            age = calculate_age(pod.metadata.creation_timestamp)
            model.setItem(row, 5, QStandardItem(age))
            
            model.setItem(row, 6, QStandardItem(pod.spec.node_name))
            row += 1
    # After populating the table
    gui.resource_table.setColumnWidth(0, 100)  # Namespace
    gui.resource_table.setColumnWidth(1, 250)  # Pod Name
    gui.resource_table.setColumnWidth(2, 40)   # Ready
    gui.resource_table.setColumnWidth(3, 40)   # Status
    gui.resource_table.setColumnWidth(4, 40)   # Restarts
    gui.resource_table.setColumnWidth(5, 50)   # Age
    gui.resource_table.setColumnWidth(6, 250)   # Node
    

def update_pvcs(gui, namespaces, model):
    model.setColumnCount(5)
    model.setHorizontalHeaderLabels(["Namespace", "PVC Name", "Status", "Capacity", "Age"])
    
    row = 0
    for namespace in namespaces:
        pvcs = gui.v1.list_namespaced_persistent_volume_claim(namespace)
        for pvc in pvcs.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(pvc.metadata.name))
            model.setItem(row, 2, QStandardItem(pvc.status.phase))
            model.setItem(row, 3, QStandardItem(pvc.spec.resources.requests['storage']))
            add_age_column(model, pvc.metadata.creation_timestamp, row, 4)
            row += 1

def update_nodes(gui, model):
    model.setColumnCount(5)
    model.setHorizontalHeaderLabels(["Name", "Status", "Role", "Age", "CPU Usage", "Memory Usage"])
    
    row = 0
    nodes = gui.v1.list_node()
    try:
        metrics = gui.custom_api.list_cluster_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            plural="nodes"
        )
        node_metrics = {item['metadata']['name']: item for item in metrics['items']}
    except:
        node_metrics = {}
    
    for node in nodes.items:
        model.insertRow(row)
        model.setItem(row, 0, QStandardItem(node.metadata.name))
        model.setItem(row, 1, QStandardItem(node.status.conditions[-1].type))
        
        # Determine if node is master or worker
        role = "worker"
        if any(label.startswith("node-role.kubernetes.io/master") or label.startswith("node-role.kubernetes.io/control-plane") for label in node.metadata.labels):
            role = "master"
        model.setItem(row, 2, QStandardItem(role))
        
        add_age_column(model, node.metadata.creation_timestamp, row, 3)
        
        if node.metadata.name in node_metrics:
            metric = node_metrics[node.metadata.name]
            cpu_usage = parse_k8s_cpu(metric['usage']['cpu'])
            memory_usage = parse_k8s_memory(metric['usage']['memory'])
            
            cpu_item = QStandardItem(f"{cpu_usage:.2f}m")
            cpu_item.setBackground(get_color_for_usage(cpu_usage))
            memory_item = QStandardItem(f"{memory_usage/1024/1024:.2f}Mi")
            memory_item.setBackground(get_color_for_usage(memory_usage/1024/1024))
            
            model.setItem(row, 4, cpu_item)
            model.setItem(row, 5, memory_item)
        else:
            model.setItem(row, 4, QStandardItem("N/A"))
            model.setItem(row, 5, QStandardItem("N/A"))
        
        row += 1

def update_statefulsets(gui, namespaces, model):
    model.setColumnCount(4)
    model.setHorizontalHeaderLabels(["Namespace", "StatefulSet Name", "Replicas", "Ready Replicas", "Age"])
    
    row = 0
    for namespace in namespaces:
        statefulsets = gui.apps_v1.list_namespaced_stateful_set(namespace)
        for sts in statefulsets.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(sts.metadata.name))
            model.setItem(row, 2, QStandardItem(str(sts.spec.replicas)))
            model.setItem(row, 3, QStandardItem(str(sts.status.ready_replicas)))
            add_age_column(model, sts.metadata.creation_timestamp, row, 4)
            row += 1

def update_deployments(gui, namespaces, model):
    model.setColumnCount(5)
    model.setHorizontalHeaderLabels(["Namespace", "Deployment Name", "Replicas", "Available Replicas", "Age"])
    
    row = 0
    for namespace in namespaces:
        deployments = gui.apps_v1.list_namespaced_deployment(namespace)
        for deploy in deployments.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(deploy.metadata.name))
            model.setItem(row, 2, QStandardItem(str(deploy.spec.replicas)))
            model.setItem(row, 3, QStandardItem(str(deploy.status.available_replicas)))
            add_age_column(model, deploy.metadata.creation_timestamp, row, 4)
            row += 1

def update_pvs(gui, model):
    model.setColumnCount(5)
    model.setHorizontalHeaderLabels(["PV Name", "Capacity", "Access Modes", "Status", "Age"])
    
    row = 0
    pvs = gui.v1.list_persistent_volume()
    for pv in pvs.items:
        model.insertRow(row)
        model.setItem(row, 0, QStandardItem(pv.metadata.name))
        model.setItem(row, 1, QStandardItem(pv.spec.capacity['storage']))
        model.setItem(row, 2, QStandardItem(', '.join(pv.spec.access_modes)))
        model.setItem(row, 3, QStandardItem(pv.status.phase))
        model.setItem(row, 4, QStandardItem(calculate_age(pv.metadata.creation_timestamp)))
        row += 1

def update_secrets(gui, namespaces, model):
    model.setColumnCount(4)
    model.setHorizontalHeaderLabels(["Namespace", "Secret Name", "Type", "Age"])
    
    row = 0
    for namespace in namespaces:
        secrets = gui.v1.list_namespaced_secret(namespace)
        for secret in secrets.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(secret.metadata.name))
            model.setItem(row, 2, QStandardItem(secret.type))
            model.setItem(row, 3, QStandardItem(calculate_age(secret.metadata.creation_timestamp)))
            row += 1

def update_configmaps(gui, namespaces, model):
    model.setColumnCount(3)
    model.setHorizontalHeaderLabels(["Namespace", "ConfigMap Name", "Age"])
    
    row = 0
    for namespace in namespaces:
        configmaps = gui.v1.list_namespaced_config_map(namespace)
        for cm in configmaps.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(cm.metadata.name))
            model.setItem(row, 2, QStandardItem(calculate_age(cm.metadata.creation_timestamp)))
            row += 1

def update_jobs(gui, namespaces, model):
    model.setColumnCount(5)
    model.setHorizontalHeaderLabels(["Namespace", "Job Name", "Completions", "Succeeded", "Age"])
    
    row = 0
    for namespace in namespaces:
        jobs = gui.batch_v1.list_namespaced_job(namespace)
        for job in jobs.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(job.metadata.name))
            model.setItem(row, 2, QStandardItem(f"{job.status.succeeded or 0}/{job.spec.completions or 1}"))
            model.setItem(row, 3, QStandardItem(str(job.status.succeeded or 0)))
            model.setItem(row, 4, QStandardItem(calculate_age(job.metadata.creation_timestamp)))
            
            duration = "N/A"
            if job.status.start_time and job.status.completion_time:
                duration = str(job.status.completion_time - job.status.start_time)
            model.setItem(row, 5, QStandardItem(duration))
            
            row += 1

def update_cronjobs(gui, namespaces, model):
    model.setColumnCount(7)
    model.setHorizontalHeaderLabels(["Namespace", "CronJob Name", "Schedule", "Suspend", "Active", "Last Schedule" , "Age"])
    
    row = 0
    for namespace in namespaces:
        cronjobs = gui.batch_v1.list_namespaced_cron_job(namespace)
        for cronjob in cronjobs.items:
            model.insertRow(row)
            model.setItem(row, 0, QStandardItem(namespace))
            model.setItem(row, 1, QStandardItem(cronjob.metadata.name))
            model.setItem(row, 2, QStandardItem(cronjob.spec.schedule))
            model.setItem(row, 3, QStandardItem(str(cronjob.spec.suspend or False)))
            model.setItem(row, 4, QStandardItem(str(len(cronjob.status.active or []))))
            model.setItem(row, 5, QStandardItem(calculate_age(cronjob.metadata.creation_timestamp)))
            
            last_schedule = "N/A"
            if cronjob.status.last_schedule_time:
                last_schedule = calculate_age(cronjob.status.last_schedule_time)
            model.setItem(row, 5, QStandardItem(last_schedule))
            
            row += 1



class LogStreamerThread(QThread):
    new_log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, v1, pod_name, namespace, containers, since_time=None):
        super().__init__()
        self.v1 = v1
        self.pod_name = pod_name
        self.namespace = namespace
        self.containers = containers
        self.is_running = True
        self.w = watch.Watch()
        self.since_time = since_time or datetime.now(timezone.utc).isoformat()

    def run(self):
        try:
            for container in self.containers:
                self.new_log.emit(f"\n--- Logs for container: {container} ---\n")
                for line in self.w.stream(self.v1.read_namespaced_pod_log,
                                     name=self.pod_name,
                                     namespace=self.namespace,
                                     container=container,
                                     timestamp=True,
                                     since_time=self.since_time):
                    if not self.is_running:
                        break
                    log_time = line['timestamp']
                    log_message = line['message']
                    self.new_log.emit(f"[{container}] [{log_time}] {log_message}")
                    # Add a small sleep to allow for interruption
                    time.sleep(0.01)
                if not self.is_running:
                    break
        except Exception as e:
            self.new_log.emit(f"Error streaming logs: {str(e)}")
        finally:
            self.w.stop()
            self.finished.emit()

    def stop(self):
        self.is_running = False
        self.w.stop()