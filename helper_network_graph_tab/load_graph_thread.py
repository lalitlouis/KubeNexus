from PyQt5.QtCore import QThread, pyqtSignal
from kubernetes import client
from pyvis.network import Network
import logging

logger = logging.getLogger(__name__)

class LoadGraphThread(QThread):
    graph_loaded = pyqtSignal(object, dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, namespace, graph_type):
        super().__init__()
        self.namespace = namespace
        self.graph_type = graph_type

    def run(self):
        try:
            if self.graph_type == "Namespace Overview":
                self.load_namespace_overview()
            elif self.graph_type == "Network Policies":
                self.load_network_policies()
            elif self.graph_type == "Node-to-Pod Mapping":
                self.load_node_to_pod_mapping()
            elif self.graph_type == "Cluster Level Network Graph":
                self.load_cluster_level_network_graph()
            elif self.graph_type == "PVC and StorageClass":
                self.load_pvc_and_storage_class_graph()
            elif self.graph_type == "RBAC Visualization":
                self.load_rbac_visualization()
        except Exception as e:
            logger.error(f"Error in graph load thread: {e}", exc_info=True)
            self.error_occurred.emit(str(e))

    def load_pvc_and_storage_class_graph(self):
        v1 = client.CoreV1Api()
        storage_v1 = client.StorageV1Api()

        pvcs = v1.list_persistent_volume_claim_for_all_namespaces().items
        pvs = v1.list_persistent_volume().items
        storage_classes = storage_v1.list_storage_class().items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        for sc in storage_classes:
            network.add_node(sc.metadata.name, label=f"StorageClass: {sc.metadata.name}", shape="hexagon", size="30")
            k8s_objects[sc.metadata.name] = sc

        for pv in pvs:
            color = "#F08080" if pv.status.phase != "Bound" else None
            network.add_node(pv.metadata.name, label=f"PV: {pv.metadata.name}", shape="square", size="30", color=color)
            k8s_objects[pv.metadata.name] = pv
            if pv.spec.storage_class_name:
                network.add_edge(pv.metadata.name, pv.spec.storage_class_name, title="Uses")

        for pvc in pvcs:
            color = "#F08080" if pvc.status.phase != "Bound" else None
            network.add_node(pvc.metadata.name, label=f"PVC: {pvc.metadata.name}\nNamespace: {pvc.metadata.namespace}", shape="database", size="30", color=color)
            k8s_objects[pvc.metadata.name] = pvc
            if pvc.spec.volume_name:
                network.add_edge(pvc.metadata.name, pvc.spec.volume_name, title="Bound to")
            if pvc.spec.storage_class_name:
                network.add_edge(pvc.metadata.name, pvc.spec.storage_class_name, title="Uses")

        self.graph_loaded.emit(network, k8s_objects)

    def load_rbac_visualization(self):
        v1 = client.CoreV1Api()
        rbac_v1 = client.RbacAuthorizationV1Api()

        service_accounts = v1.list_service_account_for_all_namespaces().items
        roles = rbac_v1.list_role_for_all_namespaces().items
        role_bindings = rbac_v1.list_role_binding_for_all_namespaces().items
        cluster_roles = rbac_v1.list_cluster_role().items
        cluster_role_bindings = rbac_v1.list_cluster_role_binding().items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        def add_node_if_not_exists(node_id, label, shape, size):
            if node_id not in k8s_objects:
                network.add_node(node_id, label=label, shape=shape, size=size)
                k8s_objects[node_id] = {"kind": label.split(":")[0], "metadata": {"name": node_id.split(".")[0], "namespace": node_id.split(".")[1] if "." in node_id else None}}

        # Add all nodes first
        for sa in service_accounts:
            sa_node = f"{sa.metadata.name}.{sa.metadata.namespace}"
            add_node_if_not_exists(sa_node, f"ServiceAccount: {sa.metadata.name}\nNamespace: {sa.metadata.namespace}", "dot", "30")
            k8s_objects[sa_node] = sa

        for role in roles:
            role_node = f"{role.metadata.name}.{role.metadata.namespace}"
            add_node_if_not_exists(role_node, f"Role: {role.metadata.name}\nNamespace: {role.metadata.namespace}", "square", "30")
            k8s_objects[role_node] = role

        for cr in cluster_roles:
            add_node_if_not_exists(cr.metadata.name, f"ClusterRole: {cr.metadata.name}", "triangle", "30")
            k8s_objects[cr.metadata.name] = cr

        for rb in role_bindings:
            rb_node = f"{rb.metadata.name}.{rb.metadata.namespace}"
            add_node_if_not_exists(rb_node, f"RoleBinding: {rb.metadata.name}\nNamespace: {rb.metadata.namespace}", "diamond", "30")
            k8s_objects[rb_node] = rb

        for crb in cluster_role_bindings:
            add_node_if_not_exists(crb.metadata.name, f"ClusterRoleBinding: {crb.metadata.name}", "star", "30")
            k8s_objects[crb.metadata.name] = crb

        # Add a "No Subjects" node
        add_node_if_not_exists("No Subjects", "No Subjects", "box", "30")

        # Now add edges
        for rb in role_bindings:
            rb_node = f"{rb.metadata.name}.{rb.metadata.namespace}"
            if rb.role_ref.kind == "Role":
                role_node = f"{rb.role_ref.name}.{rb.metadata.namespace}"
            else:  # ClusterRole
                role_node = rb.role_ref.name
            add_node_if_not_exists(role_node, f"{rb.role_ref.kind}: {rb.role_ref.name}", "square" if rb.role_ref.kind == "Role" else "triangle", "30")
            network.add_edge(rb_node, role_node, title="References")

            if rb.subjects:
                for subject in rb.subjects:
                    if subject.kind == "ServiceAccount":
                        sa_node = f"{subject.name}.{subject.namespace}"
                        add_node_if_not_exists(sa_node, f"ServiceAccount: {subject.name}\nNamespace: {subject.namespace}", "dot", "30")
                        network.add_edge(rb_node, sa_node, title="Binds")
            else:
                network.add_edge(rb_node, "No Subjects", title="Has no subjects")

        for crb in cluster_role_bindings:
            add_node_if_not_exists(crb.role_ref.name, f"ClusterRole: {crb.role_ref.name}", "triangle", "30")
            network.add_edge(crb.metadata.name, crb.role_ref.name, title="References")
            if crb.subjects:
                for subject in crb.subjects:
                    if subject.kind == "ServiceAccount":
                        sa_node = f"{subject.name}.{subject.namespace}"
                        add_node_if_not_exists(sa_node, f"ServiceAccount: {subject.name}\nNamespace: {subject.namespace}", "dot", "30")
                        network.add_edge(crb.metadata.name, sa_node, title="Binds")
            else:
                network.add_edge(crb.metadata.name, "No Subjects", title="Has no subjects")

        self.graph_loaded.emit(network, k8s_objects)

    def get_pod_color(self, pod):
        if pod.status.container_statuses:
            for container_status in pod.status.container_statuses:
                logger.debug(f"Pod: {pod.metadata.name}, Container: {container_status.name}, Ready: {container_status.ready}, State: {container_status.state}, Pod Phase: {pod.status.phase}")
                if container_status.ready != True or container_status.state.waiting:
                    logger.debug(f"Pod: {pod.metadata.name}, Container: {container_status.name} is not ready. Setting color to red.")
                    return "#F08080"
        logger.debug(f"Pod: {pod.metadata.name}, Phase: {pod.status.phase} is running fine. Setting color to None.")
        return None

    def load_namespace_overview(self):
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        pods = v1.list_namespaced_pod(self.namespace).items
        services = v1.list_namespaced_service(self.namespace).items
        deployments = apps_v1.list_namespaced_deployment(self.namespace).items
        statefulsets = apps_v1.list_namespaced_stateful_set(self.namespace).items
        secrets = v1.list_namespaced_secret(self.namespace).items
        configmaps = v1.list_namespaced_config_map(self.namespace).items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        # Add nodes
        for pod in pods:
            color = self.get_pod_color(pod)
            logger.debug(f"Pod: {pod.metadata.name}, Phase: {pod.status.phase}, Color: {color}")
            network.add_node(pod.metadata.name, label=f"Pod: {pod.metadata.name}", shape="dot", size="30", color=color)
            k8s_objects[pod.metadata.name] = pod

        for service in services:
            color = "#F08080" if not service.spec.cluster_ip else None
            logger.debug(f"Service: {service.metadata.name}, Cluster IP: {service.spec.cluster_ip}, Color: {color}")
            network.add_node(service.metadata.name, label=f"Service: {service.metadata.name}", shape="triangle", size="30", color=color)
            k8s_objects[service.metadata.name] = service

        for deployment in deployments:
            color = "#F08080" if deployment.status.available_replicas != deployment.status.replicas else None
            logger.debug(f"Deployment: {deployment.metadata.name}, Available Replicas: {deployment.status.available_replicas}, Replicas: {deployment.status.replicas}, Color: {color}")
            network.add_node(deployment.metadata.name, label=f"Deployment: {deployment.metadata.name}", shape="box", size="30", color=color)
            k8s_objects[deployment.metadata.name] = deployment

        for statefulset in statefulsets:
            color = "#F08080" if statefulset.status.ready_replicas != statefulset.status.replicas else None
            logger.debug(f"StatefulSet: {statefulset.metadata.name}, Ready Replicas: {statefulset.status.ready_replicas}, Replicas: {statefulset.status.replicas}, Color: {color}")
            network.add_node(statefulset.metadata.name, label=f"StatefulSet: {statefulset.metadata.name}", shape="box", size="30", color=color)
            k8s_objects[statefulset.metadata.name] = statefulset

        for secret in secrets:
            network.add_node(secret.metadata.name, label=f"Secret: {secret.metadata.name}", shape="diamond", size="30")
            k8s_objects[secret.metadata.name] = secret

        for configmap in configmaps:
            network.add_node(configmap.metadata.name, label=f"ConfigMap: {configmap.metadata.name}", shape="star", size="30")
            k8s_objects[configmap.metadata.name] = configmap

        # Add edges
        for service in services:
            if service.spec.selector:
                for pod in pods:
                    if all(item in pod.metadata.labels.items() for item in service.spec.selector.items()):
                        network.add_edge(service.metadata.name, pod.metadata.name, title="Selects")

        for deployment in deployments:
            for pod in pods:
                if pod.metadata.owner_references and any(owner.kind == "ReplicaSet" and owner.name.startswith(deployment.metadata.name) for owner in pod.metadata.owner_references):
                    network.add_edge(deployment.metadata.name, pod.metadata.name, title="Manages")

        for statefulset in statefulsets:
            for pod in pods:
                if pod.metadata.owner_references and any(owner.kind == "StatefulSet" and owner.name == statefulset.metadata.name for owner in pod.metadata.owner_references):
                    network.add_edge(statefulset.metadata.name, pod.metadata.name, title="Manages")

        # Add edges for secrets and configmaps
        for pod in pods:
            # Check volumes for secret and configmap references
            if pod.spec.volumes:
                for volume in pod.spec.volumes:
                    if volume.secret:
                        network.add_edge(pod.metadata.name, volume.secret.secret_name, title="Uses Secret")
                    if volume.config_map:
                        network.add_edge(pod.metadata.name, volume.config_map.name, title="Uses ConfigMap")
            
            # Check environment variables for secret and configmap references
            if pod.spec.containers:
                for container in pod.spec.containers:
                    if container.env:
                        for env in container.env:
                            if env.value_from:
                                if env.value_from.secret_key_ref:
                                    network.add_edge(pod.metadata.name, env.value_from.secret_key_ref.name, title="Uses Secret")
                                if env.value_from.config_map_key_ref:
                                    network.add_edge(pod.metadata.name, env.value_from.config_map_key_ref.name, title="Uses ConfigMap")
                    
                    # Check envFrom for secret and configmap references
                    if container.env_from:
                        for env_from in container.env_from:
                            if env_from.secret_ref:
                                network.add_edge(pod.metadata.name, env_from.secret_ref.name, title="Uses Secret")
                            if env_from.config_map_ref:
                                network.add_edge(pod.metadata.name, env_from.config_map_ref.name, title="Uses ConfigMap")

        self.graph_loaded.emit(network, k8s_objects)

    def load_network_policies(self):
        v1 = client.CoreV1Api()
        networking_v1 = client.NetworkingV1Api()

        network_policies = networking_v1.list_namespaced_network_policy(self.namespace).items
        pods = v1.list_namespaced_pod(self.namespace).items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        for policy in network_policies:
            network.add_node(policy.metadata.name, label=f"NetworkPolicy: {policy.metadata.name}", shape="hexagon", size="30")
            k8s_objects[policy.metadata.name] = policy

        for pod in pods:
            color = self.get_pod_color(pod)
            network.add_node(pod.metadata.name, label=f"Pod: {pod.metadata.name}", shape="dot", size="30", color=color)
            k8s_objects[pod.metadata.name] = pod

        for policy in network_policies:
            pod_selector = policy.spec.pod_selector
            for pod in pods:
                if all(item in pod.metadata.labels.items() for item in pod_selector.match_labels.items()):
                    network.add_edge(policy.metadata.name, pod.metadata.name, title="Applies to")

        self.graph_loaded.emit(network, k8s_objects)

    def load_node_to_pod_mapping(self):
        v1 = client.CoreV1Api()

        nodes = v1.list_node().items
        pods = v1.list_pod_for_all_namespaces().items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        for node in nodes:
            ready_condition = next((condition for condition in node.status.conditions if condition.type == "Ready"), None)
            color = "#F08080" if not ready_condition or ready_condition.status != "True" else None
            network.add_node(node.metadata.name, label=f"Node: {node.metadata.name}", shape="square", size="30", color=color)
            k8s_objects[node.metadata.name] = node

        for pod in pods:
            color = self.get_pod_color(pod)
            network.add_node(pod.metadata.name, label=f"Pod: {pod.metadata.name}", shape="dot", size="30", color=color)
            k8s_objects[pod.metadata.name] = pod
            if pod.spec.node_name:
                network.add_edge(pod.spec.node_name, pod.metadata.name, title="Hosts", size="30")

        self.graph_loaded.emit(network, k8s_objects)

    def load_cluster_level_network_graph(self):
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        networking_v1 = client.NetworkingV1Api()

        pods = v1.list_pod_for_all_namespaces().items
        services = v1.list_service_for_all_namespaces().items
        nodes = v1.list_node().items
        ingresses = networking_v1.list_ingress_for_all_namespaces().items

        network = Network(notebook=False, directed=True)
        k8s_objects = {}

        # Add nodes
        for node in nodes:
            ready_condition = next((condition for condition in node.status.conditions if condition.type == "Ready"), None)
            color = "#F08080" if not ready_condition or ready_condition.status != "True" else None
            network.add_node(node.metadata.name, label=f"Node: {node.metadata.name}", shape="square", size="30", color=color)
            k8s_objects[node.metadata.name] = node

        for pod in pods:
            color = self.get_pod_color(pod)
            network.add_node(pod.metadata.name, label=f"Pod: {pod.metadata.name}\nNamespace: {pod.metadata.namespace}", shape="dot", size="30", color=color)
            k8s_objects[pod.metadata.name] = pod
            if pod.spec.node_name:
                network.add_edge(pod.spec.node_name, pod.metadata.name, title="Hosts")

        for service in services:
            color = "#F08080" if not service.spec.cluster_ip else None
            network.add_node(service.metadata.name, label=f"Service: {service.metadata.name}\nNamespace: {service.metadata.namespace}", shape="triangle", size="30", color=color)
            k8s_objects[service.metadata.name] = service

        for ingress in ingresses:
            network.add_node(ingress.metadata.name, label=f"Ingress: {ingress.metadata.name}\nNamespace: {ingress.metadata.namespace}", shape="diamond", size="30")
            k8s_objects[ingress.metadata.name] = ingress

        # Add edges
        for service in services:
            for pod in pods:
                if service.spec.selector and all(item in pod.metadata.labels.items() for item in service.spec.selector.items()):
                    network.add_edge(service.metadata.name, pod.metadata.name, title="Selects")

        for ingress in ingresses:
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            service_name = path.backend.service.name
                            network.add_edge(ingress.metadata.name, f"{service_name}.{ingress.metadata.namespace}", title=f"Routes {path.path}")

        self.graph_loaded.emit(network, k8s_objects)
