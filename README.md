# KubeNexus

## Installation

### macOS

1. Download the `kubernetes_debugger_pro_mac` executable.
2. Place the executable in your desired directory.
3. Open Terminal and navigate to the directory containing the executable.
4. Run the executable:
    ```sh
    ./kubernetes_debugger_pro_mac
    ```

## Configuration

Ensure your Kubernetes configuration file is set up correctly:
- **macOS**: `~/.kube/config`



## Features

1. **View and Manage Resources**
2. **Monitor Cluster Metrics**
3. **Explore Custom Resources**
4. **Visualize Network Graphs**


## Detailed Description


![image](https://github.com/user-attachments/assets/73240dc5-0f58-4896-9bd1-5e5de2e064ff)

Context based buttons for resource types 

Pods - 
![image](https://github.com/user-attachments/assets/4d6c5fd3-206c-4ec9-a81e-f47a94a5e28c)

![image](https://github.com/user-attachments/assets/07b293c5-66c7-4590-b751-73cc4955cc7d)

Services -

![image](https://github.com/user-attachments/assets/8ccbed08-141e-476e-9428-dd2603dc19ab)

Secrets - 

![image](https://github.com/user-attachments/assets/4b01a360-e1a0-4728-88e7-09d266f84634)

![image](https://github.com/user-attachments/assets/253a4a06-48db-4fc0-b19b-3a6728e3ceb8)


Events - 

![image](https://github.com/user-attachments/assets/67725537-230c-479f-8aed-fad2d0b7daad)


In built terminal for quick access - 

![image](https://github.com/user-attachments/assets/8255eeea-ab79-447a-b11c-9b3dbac6fbba)



### 1. View and Manage Resources
This tab provides a comprehensive interface to view and manage various Kubernetes resources such as Pods, Deployments, StatefulSets, Jobs, CronJobs, PVCs, PVs, Secrets, ConfigMaps, and Nodes.

#### Monitor Cluster Metrics
This tab provides a real-time overview of node and pod metrics, including CPU and memory usage, requests, and limits.

![image](https://github.com/user-attachments/assets/d949aa33-763b-4822-8953-34b8180fa72a)


#### How It Helps
- **Node Metrics:** Displays metrics for all nodes in the cluster including CPU and memory capacities, requests, limits, and usage percentages.
- **Pod Metrics:** Shows detailed metrics for pods filtered by namespace or labels, including CPU and memory usage, requests, limits, and GPU usage.
- **Auto-Refresh:** Options to auto-refresh metrics at specified intervals.
- **Search and Filter:** Allows users to search and filter pod metrics to quickly find specific data.
- **Export Metrics:** Provides functionality to download pod metrics as CSV files.

#### How It Helps
- **Resource Overview:** Allows users to view detailed information about resources across different namespaces.
- **Manual and Auto-Refresh:** Provides options for auto-refresh intervals to keep resource information up-to-date.
- **Namespace Comparison:** Enables comparison of resources between two namespaces.
- **Resource Actions:** Facilitates actions like editing, deleting, and streaming logs for resources.
- **Resource Filtering:** Offers search and filter capabilities to quickly locate specific resources.
- **Event Monitoring:** Displays latest events in the cluster with filtering options.

#### How to Use
1. **Select Cluster:** Choose the desired cluster from the dropdown menu.
2. **Set Auto-refresh:** Select an auto-refresh interval or choose 'Off' to disable auto-refresh.
3. **Choose Namespaces:** Select two namespaces to compare resources.
4. **Select Resource Type:** Pick the resource type (Pods, Deployments, etc.) from the dropdown.
5. **View Resource Table:** The table will display resources based on the selected filters. Use the 'Refresh' button for manual refresh.
6. **Perform Actions:** Use the action buttons in the table to delete, edit, or stream logs of resources.
7. **Filter Events:** Use the filter input to narrow down events displayed in the events table.


### 2. Node metrics
![image](https://github.com/user-attachments/assets/1fc9faa5-4ef8-41bc-8455-502b010ce1dd)

### 3. Pod metrics
![image](https://github.com/user-attachments/assets/1c110988-3f95-49b5-a3a4-4744dfc09dce)


### 4. Explore Custom Resources
This tab enables users to explore custom resources, cluster roles, service accounts, roles, and bindings.

#### How It Helps
- **Custom Resource Definitions:** Allows viewing and managing custom resource definitions (CRDs).
- **Cluster Roles and Bindings:** Provides a list of cluster roles, service accounts, roles, and their bindings.
- **Resource Details:** Displays detailed information about selected resources, including metadata and spec details.
- **CRD Definitions:** Offers the capability to view CRD definitions in a readable format.

#### How to Use
1. **Select Resource Type:** Choose from 'Custom Resources', 'Cluster Roles', 'Service Accounts', 'Roles', 'Cluster Role Bindings', or 'Role Bindings'.
2. **Filter Resources:** Use the filter input to narrow down the resource list.
3. **Select Resource:** Click on a resource to view its details.
4. **View Details:** The table and info pane will display detailed information about the selected resource.
5. **View CRD Definition:** Click the 'View CRD Definition' button to see the CRD definition.

![image](https://github.com/user-attachments/assets/0148e955-d3b7-4c0e-8c5a-d6b3092b803f)

![image](https://github.com/user-attachments/assets/a2753b42-6e27-4922-bb9a-160776c49ca9)


### 5. Visualize Network Graphs
This tab provides graphical visualizations of the cluster's network topology, including namespace overviews, service dependencies, ingress traffic flows, network policies, node-to-pod mappings, and PVC connections.

#### How It Helps
- **Namespace Overview:** Visualizes the relationships between different resources within a namespace.
- **Service Dependency:** Shows the dependencies between services and endpoints.
- **Ingress Traffic Flow:** Illustrates the traffic flow through ingress resources to services.
- **Network Policy:** Displays the application of network policies on pods.
- **Node-to-Pod Mapping:** Maps pods to the nodes they are running on.
- **PVC Connections:** Shows the connections between pods and persistent volume claims (PVCs).
- **Custom Resource Dependency:** Visualizes dependencies involving custom resources.

#### How to Use
1. **Select Namespace:** Choose a namespace from the dropdown menu.
2. **Select Graph Type:** Choose from 'Namespace Overview', 'Service Dependency', 'Ingress Traffic Flow', 'Network Policy', 'Node-to-Pod Mapping', 'PVC Connections', or 'Custom Resource Dependency'.
3. **View Graph:** The graph will be generated and displayed in the web view.
4. **Interact with Graph:** Right-click on nodes to view detailed information.

![image](https://github.com/user-attachments/assets/9491867f-f26a-44cd-940e-788fa6a57ed5)

![image](https://github.com/user-attachments/assets/5737adab-751f-4987-b903-8de2e0e9fe4e)

### 6. Github

![image](https://github.com/user-attachments/assets/368e1207-d85f-471f-a78e-8acbd133bd5a)

![image](https://github.com/user-attachments/assets/4b6848e8-b994-41f2-a561-a35825743db4)

![image](https://github.com/user-attachments/assets/1b131f1e-a1a2-464d-863e-4726c7c2eb1f)

![image](https://github.com/user-attachments/assets/3eef489e-e320-4670-83f6-09be73082f98)



### 7. JIRA

![image](https://github.com/user-attachments/assets/2828cd5c-dc27-459c-88d1-0eafc2c6de44)

![image](https://github.com/user-attachments/assets/aa608134-52ec-49ab-9c57-e5d39b1dbeb6)



### 8. Jenkins

![image](https://github.com/user-attachments/assets/c26e7858-7fdc-456d-ba5b-61e298edf634)


### 9. System

![image](https://github.com/user-attachments/assets/99c743f1-b3f9-49d7-83ca-94c453a44a67)

![image](https://github.com/user-attachments/assets/56df65be-fbbe-46c9-b4fe-26f78e81ca75)

![image](https://github.com/user-attachments/assets/748eee74-a81d-4e19-8f0b-43e84ccafc1d)


![image](https://github.com/user-attachments/assets/c7691993-703a-4527-a77c-980aceebd724)





By using the kubenexus tool, users can effectively manage Kubernetes resources, monitor cluster performance, explore custom resources, and visualize network topologies, all from a single, lightweight GUI application.
