import sys
import os
from PyQt5.QtWidgets import QApplication
from kubernetes_gui import KubernetesGUI

# Suppress macOS warning
os.environ['QT_MAC_WANTS_LAYER'] = '1'

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = KubernetesGUI()
    gui.show()
    sys.exit(app.exec_())