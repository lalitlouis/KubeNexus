import json
from PyQt5.QtCore import QObject, pyqtSlot
from .date_time_encoder import DateTimeEncoder
import logging

logger = logging.getLogger(__name__)

class WebBridge(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab = parent

    @pyqtSlot(str, result=str)
    def getNodeInfo(self, node_id):
        k8s_object = self.tab.k8s_objects.get(node_id)
        if k8s_object:
            try:
                obj_dict = k8s_object.to_dict()
                return json.dumps(obj_dict, indent=2, cls=DateTimeEncoder)
            except Exception as e:
                logger.error(f"Error serializing object: {e}")
                return f"Error getting info for node: {node_id}"
        return f"No detailed info available for node: {node_id}"
