import logging
import json
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QTreeWidget,
    QTreeWidgetItem, QSplitter, QLineEdit, QPushButton, QFileDialog, QMessageBox
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import QUrl, QTimer, QMetaObject, Qt
from PyQt5.QtGui import QFont
from kubernetes import client, config
from jinja2 import Template
from helper_network_graph_tab.web_bridge import WebBridge
from helper_network_graph_tab.load_graph_thread import LoadGraphThread


logger = logging.getLogger(__name__)

class NetworkGraphTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = None
        self.k8s_objects = {}
        try:
            config.load_kube_config()
        except config.config_exception.ConfigException:
            logger.error("Error loading Kubernetes configuration. Make sure you have a valid kubeconfig file.")
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top controls
        top_controls = QHBoxLayout()
        top_controls.setSpacing(15)

        self.graph_type_combo = QComboBox()
        self.graph_type_combo.addItems([
            "Namespace Overview",
            "Network Policies",
            "Node-to-Pod Mapping",
            "Cluster Level Network Graph",
            "PVC and StorageClass",
            "RBAC Visualization"
        ])
        self.graph_type_combo.currentIndexChanged.connect(self.on_graph_type_changed)
        top_controls.addWidget(QLabel("Graph Type:"))
        top_controls.addWidget(self.graph_type_combo)

        self.namespace_label = QLabel("Namespace:")
        self.namespace_combo = QComboBox()
        self.namespace_combo.setFixedWidth(250)
        self.namespace_combo.currentIndexChanged.connect(self.on_namespace_changed)
        top_controls.addWidget(self.namespace_label)
        top_controls.addWidget(self.namespace_combo)

        top_controls.addStretch(1)

        main_layout.addLayout(top_controls)

        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #4a90e2;
                width: 2px;
            }
        """)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search nodes...")
        self.search_field.textChanged.connect(self.filter_nodes)
        left_layout.addWidget(self.search_field)

        self.node_tree = QTreeWidget()
        self.node_tree.setHeaderHidden(True)
        self.node_tree.itemClicked.connect(self.on_node_selected)
        left_layout.addWidget(self.node_tree)

        self.show_all_button = QPushButton("Show All Nodes")
        self.show_all_button.clicked.connect(self.show_all_nodes)
        left_layout.addWidget(self.show_all_button)

        splitter.addWidget(left_panel)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView()
        right_layout.addWidget(self.web_view)

        splitter.addWidget(right_panel)

        main_layout.addWidget(splitter)

        # Add refresh and download buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)  # Push buttons to the right

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setStyleSheet("background-color: #4CAF50; color: white;")
        self.refresh_button.clicked.connect(self.refresh_graph)
        button_layout.addWidget(self.refresh_button)

        self.download_button = QPushButton("Download Graph")
        self.download_button.setStyleSheet("background-color: #FFD700; color: black;")
        self.download_button.clicked.connect(self.download_graph)
        button_layout.addWidget(self.download_button)

        main_layout.addLayout(button_layout)


        # Set up web channel for communication with JavaScript
        self.channel = QWebChannel()
        self.web_bridge = WebBridge(self)
        self.channel.registerObject('bridge', self.web_bridge)
        self.web_view.page().setWebChannel(self.channel)

        self.load_namespaces()

        # Start with Namespace Overview
        self.graph_type_combo.setCurrentIndex(0)

    def populate_node_tree(self, categories):
        self.node_tree.clear()
        for category, nodes in categories.items():
            if nodes:
                category_item = QTreeWidgetItem(self.node_tree, [f"{category}s"])
                category_item.setFont(0, QFont("Arial", 20, QFont.Bold))
                for node in nodes:
                    node_item = QTreeWidgetItem(category_item, [node['id']])
                    node_item.setFont(0, QFont("Arial", 15))
                category_item.setExpanded(False)

    def filter_nodes(self, text):
        for i in range(self.node_tree.topLevelItemCount()):
            item = self.node_tree.topLevelItem(i)
            item.setHidden(True)
            for j in range(item.childCount()):
                child = item.child(j)
                if text.lower() in child.text(0).lower():
                    child.setHidden(False)
                    item.setHidden(False)
                else:
                    child.setHidden(True)

    def show_all_nodes(self):
        self.web_view.page().runJavaScript("resetHighlight();")

    def on_graph_type_changed(self, index):
        graph_type = self.graph_type_combo.currentText()
        self.search_field.clear()
        if graph_type == "Namespace Overview":
            self.namespace_label.show()
            self.namespace_combo.show()
        else:
            self.namespace_label.hide()
            self.namespace_combo.hide()
        self.load_graph(self.namespace_combo.currentData(), graph_type)

    def load_namespaces(self):
        try:
            v1 = client.CoreV1Api()
            namespaces = v1.list_namespace().items
            self.namespace_combo.clear()
            self.namespace_combo.addItem("Select a namespace", None)
            for ns in namespaces:
                self.namespace_combo.addItem(ns.metadata.name, ns.metadata.name)
            self.namespace_combo.setCurrentIndex(1)
        except Exception as e:
            logger.error(f"Error loading namespaces: {e}")

    def on_namespace_changed(self, index):
        namespace = self.namespace_combo.currentData()
        if namespace:
            graph_type = self.graph_type_combo.currentText()
            self.load_graph(namespace, graph_type)

    def on_node_selected(self, item, column):
        if item.parent() is None:  # Category item
            return
        node_id = item.text(0)
        self.web_view.page().runJavaScript(f"highlightNode('{node_id}');")

    def load_graph(self, namespace, graph_type):
        self.show_loading_indicator(graph_type)
        self.load_thread = LoadGraphThread(namespace, graph_type)
        self.load_thread.graph_loaded.connect(self.on_graph_loaded)
        self.load_thread.error_occurred.connect(self.on_graph_error)
        self.load_thread.start()

    def show_loading_indicator(self, graph_type):
        descriptions = {
            "Namespace Overview": "Visualizing resources and their relationships within the selected namespace.",
            "Network Policies": "Displaying network policies and affected pods.",
            "Node-to-Pod Mapping": "Showing the distribution of pods across nodes.",
            "Cluster Level Network Graph": "Presenting an overview of network connections in the entire cluster.",
            "PVC and StorageClass": "Illustrating the relationships between Persistent Volume Claims and Storage Classes.",
            "RBAC Visualization": "Mapping out Role-Based Access Control configurations."
        }
        description = descriptions.get(graph_type, "Loading graph...")
        js_code = f"""
        if (typeof showLoading === 'function') {{
            showLoading("{description}");
        }} else {{
            console.error('showLoading function is not defined');
        }}
        """
        self.web_view.page().runJavaScript(js_code)

    def hide_loading_indicator(self):
        self.web_view.page().runJavaScript("hideLoading();")

    def on_graph_loaded(self, network, k8s_objects):
        self.network = network
        self.k8s_objects = k8s_objects
        QTimer.singleShot(100, self.generate_graph)

    def on_graph_error(self, error_msg):
        logger.error(f"Error loading graph: {error_msg}")
        self.hide_loading_indicator()

    def generate_graph(self):
        logger.debug(f"generate_graph called, self.network is {type(self.network)}")
        if self.network is None:
            logger.error("Error: self.network is None")
            return
        try:
            logger.debug("Generating graph")
            
            # Convert network data to JSON
            nodes_data = [{"id": node["id"], "label": node["label"], "shape": node.get("shape", "box"), "color": node.get("color", None)} for node in self.network.nodes]
            edges_data = [{"from": edge["from"], "to": edge["to"], "arrows": "to", "title": edge.get("title", "")} for edge in self.network.edges]
            
            logger.debug(f"Number of nodes: {len(nodes_data)}")
            logger.debug(f"Number of edges: {len(edges_data)}")
            logger.debug(f"Edge data sample: {edges_data[:5] if edges_data else 'No edges'}")

            categories = {
                "Node": [], "Pod": [], "Service": [], "Deployment": [], "StatefulSet": [],
                "Secret": [], "ConfigMap": [], "PV": [], "PVC": [],
                "StorageClass": [], "ServiceAccount": [], "Role": [], "RoleBinding": [],
                "ClusterRole": [], "ClusterRoleBinding": [], "Ingress": [], "NetworkPolicy": []
            }

            def get_category(label):
                # Remove the trailing 's' if present
                singular = label[:-1] if label.endswith('s') else label
                return singular if singular in categories else label

            for node in nodes_data:
                label = node["label"].split(":")[0].strip()
                category = get_category(label)
                if category in categories:
                    categories[category].append(node)
                else:
                    logger.warning(f"Unknown resource type: {label}")

            logger.debug(f"Categorized nodes: {', '.join(f'{k}: {len(v)}' for k, v in categories.items() if v)}")

            # Populate the node tree instead of the sidebar
            self.populate_node_tree(categories)

            logger.debug(f"Populated node tree with {self.node_tree.topLevelItemCount()} categories")
            logger.debug(f"Node tree visible: {self.node_tree.isVisible()}")
            logger.debug(f"Node tree size: {self.node_tree.size()}")

            # Create a basic HTML template with improved styling
            html_template = Template("""
            <html>
            <head>
                <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js"></script>
                <link href="https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css" rel="stylesheet" type="text/css" />
                <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
                <style type="text/css">
                    body, html, #mynetwork {
                        width: 100%;
                        height: 100%;
                        margin: 0;
                        padding: 0;
                    }
                    #popup, #legend {
                        position: fixed;
                        background-color: white;
                        padding: 20px;
                        border: 1px solid #ccc;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
                    }
                    #popup {
                        display: none;
                        top: 50%;
                        left: 50%;
                        transform: translate(-50%, -50%);
                        max-width: 80%;
                        max-height: 80%;
                        overflow: auto;
                    }
                    #legend {
                        top: 10px;
                        left: 10px;
                        z-index: 1000;
                    }
                    #popup-content {
                        white-space: pre-wrap;
                        font-family: monospace;
                    }
                    #close-popup {
                        position: absolute;
                        top: 10px;
                        right: 10px;
                        cursor: pointer;
                    }
                    #loading {
                        display: none;
                        position: absolute;
                        top: 50%;
                        left: 50%;
                        transform: translate(-50%, -50%);
                        text-align: center;
                        background-color: rgba(255, 255, 255, 0.7);
                        padding: 20px;
                        border-radius: 10px;
                        z-index: 1001;
                    }
                    #loading-bar {
                        width: 200px;
                        height: 20px;
                        background-color: #f0f0f0;
                        border-radius: 10px;
                        overflow: hidden;
                        margin-bottom: 10px;
                    }
                    #loading-progress {
                        width: 0%;
                        height: 100%;
                        background-color: #4CAF50;
                        transition: width 0.5s;
                    }
                </style>
                <script type="text/javascript">
                    // Define all functions first
                                     
                    function centerGraph() {
                        if (network) {
                            network.fit({
                                animation: {
                                    duration: 1000,
                                    easingFunction: "easeInOutQuad"
                                }
                            });
                        }
                    }

                    window.onload = function() {
                        createNetwork();
                        centerGraph();  // Center the graph on load
                    }
                    function showLoading() {
                        document.getElementById("loading").style.display = "block";
                    }
                    
                    function hideLoading() {
                        document.getElementById("loading").style.display = "none";
                    }
            
                    function updateLoadingMessage(message) {
                        document.getElementById("loading-message").textContent = message;
                    }
            
                    function updateLoadingProgress(progress) {
                        document.getElementById("loading-progress").style.width = progress + "%";
                    }
            
                    function showPopup(content) {
                        document.getElementById('popup-content').textContent = content;
                        document.getElementById('popup').style.display = 'block';
                    }
            
                    function closePopup() {
                        document.getElementById('popup').style.display = 'none';
                    }
            
                    function highlightNode(nodeId) {
                        nodes.update(nodes.get().map(node => {
                            if (node.id === nodeId || edges.get().some(edge => edge.from === nodeId && edge.to === node.id || edge.from === node.id && edge.to === nodeId)) {
                                node.hidden = false;
                            } else {
                                node.hidden = true;
                            }
                            return node;
                        }));
                        edges.update(edges.get().map(edge => {
                            edge.hidden = !(edge.from === nodeId || edge.to === nodeId);
                            return edge;
                        }));
                        
                        // Center on the highlighted node
                        var nodePosition = network.getPositions([nodeId])[nodeId];
                        network.moveTo({
                            position: nodePosition,
                            scale: 1.0,
                            animation: {
                                duration: 1000,
                                easingFunction: "easeInOutQuad"
                            }
                        });
                    }
            
                    function resetHighlight() {
                        nodes.update(nodes.get().map(node => {
                            node.hidden = false;
                            return node;
                        }));
                        edges.update(edges.get().map(edge => {
                            edge.hidden = false;
                            return edge;
                        }));
                    }
            
                    var network;
                    var nodes;
                    var edges;
            
                    function createNetwork() {
                        var container = document.getElementById('mynetwork');
                        nodes = new vis.DataSet({{ nodes }});
                        edges = new vis.DataSet({{ edges }});
                        var data = {
                            nodes: nodes,
                            edges: edges
                        };
                        var options = {
                            nodes: {
                                font: {
                                    size: 12,
                                    face: 'Tahoma',
                                    color: '#000000'  // Ensure text is always black for contrast
                                },
                                color: {
                                    border: '#2B7CE9',
                                    background: '#97C2FC',  // Default background color
                                    highlight: {
                                        border: '#2B7CE9',
                                        background: '#D2E5FF'
                                    }
                                }
                            },
                            edges: {
                                width: 1,
                                color: {color: '#848484'}, 
                                arrows: {
                                    to: {enabled: true, scaleFactor: 1}
                                },
                                smooth: {
                                    type: 'continuous'
                                }
                            },
                            physics: {
                                enabled: true,
                                solver: 'forceAtlas2Based',
                                forceAtlas2Based: {
                                    gravitationalConstant: -50,
                                    centralGravity: 0.01,
                                    springLength: 100,
                                    springConstant: 0.08,
                                    damping: 0.4,
                                    avoidOverlap: 0.5
                                },
                                stabilization: {
                                    enabled: true,
                                    iterations: 1000,
                                    updateInterval: 25
                                },
                                minVelocity: 0.75,
                                maxVelocity: 30
                            },
                            layout: {
                                improvedLayout: true,
                                hierarchical: {
                                    enabled: false
                                }
                            }
                        };
                        network = new vis.Network(container, data, options);
            
                        network.on("stabilizationProgress", function(params) {
                            var progress = Math.round(params.iterations / params.total * 100);
                            updateLoadingProgress(progress);
                        });
            
                        network.on("stabilizationIterationsDone", function() {
                            network.fit(); // Center the graph
                        });
            
                        network.on("oncontext", function (params) {
                            params.event.preventDefault();
                            var nodeId = this.getNodeAt(params.pointer.DOM);
                            if (nodeId) {
                                new QWebChannel(qt.webChannelTransport, function (channel) {
                                    var bridge = channel.objects.bridge;
                                    bridge.getNodeInfo(nodeId, function(info) {
                                        showPopup(info);
                                    });
                                });
                            }
                        });
                    }
            
                    window.onload = function() {
                        createNetwork();
                    }
                </script>
            </head>
            <body>
                <div id="mynetwork"></div>
                <div id="popup">
                    <div id="close-popup" onclick="closePopup()">X</div>
                    <pre id="popup-content"></pre>
                </div>
                <div id="loading">
                    <div id="loading-bar"><div id="loading-progress"></div></div>
                    <p id="loading-message">Loading graph...</p>
                </div>
            </body>
            </html>
            """)

            # Render the HTML
            html_content = html_template.render(
                nodes=json.dumps(nodes_data),
                edges=json.dumps(edges_data)
            )

            # Write the HTML to a file
            html_file = os.path.abspath("namespace_graph.html")
            with open(html_file, 'w') as f:
                f.write(html_content)

            if os.path.exists(html_file):
                self.web_view.setUrl(QUrl.fromLocalFile(html_file))
            self.hide_loading_indicator()
            logger.debug("Graph generation complete")
        except Exception as e:
            logger.error(f"Error in generate_graph: {e}", exc_info=True)
            self.hide_loading_indicator()


    def refresh_graph(self):
        self.load_graph(self.namespace_combo.currentData(), self.graph_type_combo.currentText())

    def download_graph(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Graph", "", "HTML Files (*.html);;All Files (*)", options=options)
        if fileName:
            self.web_view.page().toHtml(lambda html: self.save_html(html, fileName))

    def save_html(self, html, fileName):
        with open(fileName, 'w', encoding='utf-8') as f:
            f.write(html)
        QMessageBox.information(self, "Download Complete", "Graph has been saved successfully.")
