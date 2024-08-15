from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QTextEdit, QPushButton

class CreateResourceDialog(QDialog):
    def __init__(self, namespaces, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Resource")
        self.setGeometry(100, 100, 600, 400)
        
        layout = QVBoxLayout(self)
        
        namespace_layout = QHBoxLayout()
        namespace_layout.addWidget(QLabel("Namespace:"))
        self.namespace_combo = QComboBox()
        self.namespace_combo.addItems(namespaces)
        namespace_layout.addWidget(self.namespace_combo)
        layout.addLayout(namespace_layout)
        
        self.yaml_edit = QTextEdit()
        self.yaml_edit.setPlaceholderText("Enter resource YAML here...")
        layout.addWidget(self.yaml_edit)
        
        button_layout = QHBoxLayout()
        apply_button = QPushButton("Apply")
        apply_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)

    def get_namespace(self):
        return self.namespace_combo.currentText()

    def get_resource_yaml(self):
        return self.yaml_edit.toPlainText()
