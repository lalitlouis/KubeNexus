from PyQt5.QtWidgets import QLineEdit, QHBoxLayout
from PyQt5.QtCore import Qt, QSortFilterProxyModel
from PyQt5.QtGui import QColor

def setup_search(gui):
    gui.search_input = QLineEdit()
    gui.search_input.setPlaceholderText("Search resources...")
    gui.search_input.textChanged.connect(gui.filter_resources)
    
    # Create a new horizontal layout for the search input
    search_layout = QHBoxLayout()
    search_layout.addWidget(gui.search_input)
    
    # Insert the search layout into the resources layout
    if hasattr(gui, 'resources_layout'):
        gui.resources_layout.insertLayout(1, search_layout)  # Insert after the "Resource Table" label
    else:
        print("Could not find appropriate layout for resource search input")

def setup_info_search(gui):
    gui.info_search_input = QLineEdit()
    gui.info_search_input.setPlaceholderText("Search info...")
    gui.info_search_input.textChanged.connect(gui.filter_info)
    
    if hasattr(gui, 'right_layout'):
        gui.right_layout.insertWidget(0, gui.info_search_input)
    elif hasattr(gui, 'info_text') and gui.info_text.parent() is not None:
        parent_layout = gui.info_text.parent().layout()
        if parent_layout is not None:
            index = parent_layout.indexOf(gui.info_text)
            if index != -1:
                parent_layout.insertWidget(index, gui.info_search_input)
    else:
        print("Could not find appropriate layout for info search input")

def get_color_for_usage(usage):
    try:
        usage_percentage = float(usage)
        if usage_percentage > 80:
            return QColor(255, 0, 0, 127)  # Red with 50% opacity
        elif usage_percentage > 70:
            return QColor(255, 255, 0, 127)  # Yellow with 50% opacity
        else:
            return QColor(255, 255, 255, 0)  # Transparent
    except ValueError:
        return QColor(255, 255, 255, 0)  # Transparent for invalid values

def parse_k8s_cpu(cpu_string):
    if isinstance(cpu_string, (int, float)):
        return float(cpu_string)
    cpu_string = cpu_string.lower()
    if cpu_string.endswith('m'):
        return float(cpu_string[:-1]) / 1000
    elif cpu_string.endswith('n'):
        return float(cpu_string[:-1]) / 1e9
    elif cpu_string.endswith('u'):
        return float(cpu_string[:-1]) / 1e6
    elif cpu_string.endswith('k'):
        return float(cpu_string[:-1]) * 1000
    elif cpu_string.endswith('c'):  # Some systems use 'c' for cores
        return float(cpu_string[:-1])
    else:
        try:
            return float(cpu_string)
        except ValueError:
            print(f"Unable to parse CPU value: {cpu_string}")
            return 0

def parse_k8s_memory(memory_string):
    if isinstance(memory_string, (int, float)):
        return float(memory_string)
    
    memory_string = memory_string.lower()
    
    units = {
        'ki': 1024,
        'mi': 1024**2,
        'gi': 1024**3,
        'ti': 1024**4,
        'pi': 1024**5,
        'ei': 1024**6,
        'k': 1000,
        'm': 1000**2,
        'g': 1000**3,
        't': 1000**4,
        'p': 1000**5,
        'e': 1000**6,
    }

    for unit, multiplier in units.items():
        if memory_string.endswith(unit):
            if unit == 'm' and memory_string[-2].isdigit():  # Handle cases like '2576980377600m'
                return float(memory_string[:-1]) / 1000
            return float(memory_string[:-len(unit)]) * multiplier

    try:
        return float(memory_string)
    except ValueError:
        print(f"Unable to parse memory value: {memory_string}")
        return 0