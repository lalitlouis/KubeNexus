import json
import os
import base64

def clean_resource_dict(d):
    if isinstance(d, dict):
        # Remove kubernetes-specific fields that can't be updated
        keys_to_remove = ['status', 'metadata.resourceVersion', 'metadata.uid', 'metadata.creationTimestamp', 
                        'metadata.generation', 'metadata.managedFields']
        
        for key in keys_to_remove:
            parts = key.split('.')
            current = d
            for part in parts[:-1]:
                if part in current:
                    current = current[part]
                else:
                    break
            if parts[-1] in current:
                del current[parts[-1]]

        # Recursively clean nested dictionaries
        for k, v in list(d.items()):
            if k == 'managedFields':
                del d[k]
            elif isinstance(v, dict):
                clean_resource_dict(v)
            elif isinstance(v, list):
                d[k] = [clean_resource_dict(item) if isinstance(item, dict) else item for item in v]

    # Remove None values
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if v is not None}
    return d

def decode_base64_in_yaml(yaml_str):
    lines = yaml_str.split('\n')
    decoded_lines = []
    for line in lines:
        if ': ' in line:
            key, value = line.split(': ', 1)
            try:
                decoded_value = base64.b64decode(value.strip()).decode('utf-8')
                decoded_lines.append(f"{key}: {decoded_value}")
            except:
                decoded_lines.append(line)
        else:
            decoded_lines.append(line)
    return '\n.join(decoded_lines)'

def save_port_forwarding(port_forwarding_file, port_forwarding_dict):
    with open(port_forwarding_file, 'w') as f:
        json.dump(port_forwarding_dict, f)

def load_port_forwarding(port_forwarding_file):
    if os.path.exists(port_forwarding_file):
        with open(port_forwarding_file, 'r') as f:
            return json.load(f)
    return {}
