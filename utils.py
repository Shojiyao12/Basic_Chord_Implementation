import socket
import hashlib

def get_local_ip():
    """Automatically retrieve the local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def generate_node_id(ip, port, m):
    """Generate a node ID based on IP, port, and m bits."""
    identifier = f"{ip}:{port}"
    sha1_hash = hashlib.sha1(identifier.encode()).hexdigest()
    node_id = int(sha1_hash, 16) & ((1 << m) - 1)
    return node_id

def generate_key_id(data, m):
    """Generate a key ID from a given data string."""
    sha1_hash = hashlib.sha1(data.encode()).hexdigest()
    key_id = int(sha1_hash, 16) & ((1 << m) - 1)
    return key_id

def display_finger_table(node_id, finger_table, m):
    """Display the finger table of a node."""
    print(f"\nFinger Table for Node {node_id}:")
    print(f"{'Index':<6} {'Start':<10} {'Interval':<20} {'Successor'}")
    print("-" * 60)
    for i, entry in enumerate(finger_table):
        succ_id = generate_node_id(entry['successor'][0], entry['successor'][1], m)
        print(f"{i:<6} {entry['start']:<10} {entry['interval']} {entry['successor']} (ID: {succ_id})")
    print("-" * 60)

def in_range(value, start, end, m):
    """Check if a value falls within a range in a circular identifier space."""
    if start < end:
        return start < value <= end
    else:
        return start < value < (2**m) or 0 <= value <= end