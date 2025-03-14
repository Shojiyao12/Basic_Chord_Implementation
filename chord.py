import socket
import threading
import time
from utils import get_local_ip, generate_node_id, generate_key_id, display_finger_table, in_range

# Global flag for background logging
DEBUG = False

def debug_print(*args, **kwargs):
    """Print debug messages only if DEBUG is True, with a timestamp."""
    if DEBUG:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DEBUG:", *args, **kwargs)

class ChordNode:
    def __init__(self, port=5000, known_node=None, m=3):
        self.m = m
        self.ip = get_local_ip()
        self.port = port
        self.node_id = generate_node_id(self.ip, self.port, self.m)
        self.successor = (self.ip, self.port)
        self.predecessor = (self.ip, self.port)
        self.finger_table = []  # Initialize the finger table
        self.lock = threading.RLock()
        self.running = True
        self.data = {}  # Local key/value store for the DHT

        # Setup UDP socket for asynchronous messaging
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.ip, self.port))

        debug_print(f"Initializing node with ID {self.node_id} at {self.ip}:{self.port}")
        # Initialize the finger table
        self.initialize_finger_table()

        # If a known node is provided, join the network
        if known_node:
            debug_print(f"Known node provided: {known_node}. Initiating join.")
            self.join(known_node)
        else:
            debug_print("No known node provided. This node is starting a new network.")

    def initialize_finger_table(self):
        for i in range(1, self.m + 1):
            start = (self.node_id + 2**(i - 1)) % (2**self.m)
            interval = (start, (self.node_id + 2**i) % (2**self.m))
            successor = (self.ip, self.port)  # Initially assume self
            self.finger_table.append({'start': start, 'interval': interval, 'successor': successor})
        debug_print("Initial finger table created:")
        display_finger_table(self.node_id, self.finger_table, self.m)

    def start(self):
        debug_print(f"Node {self.node_id} starting background threads.")
        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.stabilize, daemon=True).start()
        threading.Thread(target=self.fix_fingers, daemon=True).start()
        threading.Thread(target=self.check_predecessor, daemon=True).start()
        debug_print(f"Node {self.node_id} is up at {self.ip}:{self.port}.")

    def listen(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                message = data.decode()
                debug_print(f"Received message from {addr}: {message}")
                self.handle_message(message, addr)
            except Exception as e:
                if self.running:
                    debug_print(f"Listen error: {e}")
                    raise

    def handle_message(self, message, addr):
        parts = message.split()
        if not parts:
            return
        cmd = parts[0]
        if cmd == 'PING':
            debug_print("Received PING; replying with PONG.")
            self.send_message('PONG', addr)
        elif cmd == 'PONG':
            debug_print(f"Received PONG from {addr}.")
        elif cmd == 'FIND_SUCCESSOR':
            start_value = int(parts[1])
            index = int(parts[2]) if len(parts) > 2 else None
            successor = self.find_successor_recursive(start_value)
            if successor is None:
                debug_print("FIND_SUCCESSOR: No successor found for", start_value)
                return
            response = (f"SUCCESSOR {successor[0]} {successor[1]} {index}"
                        if index is not None else
                        f"SUCCESSOR {successor[0]} {successor[1]}")
            debug_print(f"FIND_SUCCESSOR: Responding with successor {successor} for start {start_value}")
            self.send_message(response, addr)
        elif cmd == 'SUCCESSOR':
            index = int(parts[3]) if len(parts) > 3 else 0
            with self.lock:
                self.finger_table[index]['successor'] = (parts[1], int(parts[2]))
                if index == 0:
                    self.successor = (parts[1], int(parts[2]))
                    debug_print(f"SUCCESSOR: Updated primary successor to {self.successor}")
                    self.request_predecessor(self.successor)
        elif cmd == 'GET_PREDECESSOR':
            debug_print("GET_PREDECESSOR requested; replying with", self.predecessor)
            self.send_message(f"PREDECESSOR {self.predecessor[0]} {self.predecessor[1]}", addr)
        elif cmd == 'PREDECESSOR':
            with self.lock:
                self.predecessor = (parts[1], int(parts[2]))
            debug_print("Updated predecessor to", self.predecessor)
        elif cmd == 'SET_PREDECESSOR':
            with self.lock:
                self.predecessor = (parts[1], int(parts[2]))
            debug_print("SET_PREDECESSOR: Set predecessor to", self.predecessor)
        elif cmd == 'UPDATE_FINGER_TABLE':
            node_ip, node_port, i = parts[1], int(parts[2]), int(parts[3])
            debug_print(f"UPDATE_FINGER_TABLE: Updating finger table index {i} with node {(node_ip, node_port)}")
            self.update_finger_table((node_ip, node_port), i)
        elif cmd == "GET_SUCCESSOR":
            debug_print("GET_SUCCESSOR: Sending successor info", self.successor)
            self.send_message(f"SUCCESSOR_INFO {self.successor[0]} {self.successor[1]}", addr)
        elif cmd == "RPC_CLOSEST_PRECEDING":
            query_id = int(parts[1])
            node = self.closest_preceding_finger(query_id)
            debug_print(f"RPC_CLOSEST_PRECEDING: For query {query_id}, returning {node}")
            self.send_message(f"CLOSEST_PRECEDING {node[0]} {node[1]}", addr)
        elif cmd == 'UPDATE_SUCCESSOR':
            new_successor = (parts[1], int(parts[2]))
            with self.lock:
                self.successor = new_successor
                self.finger_table[0]['successor'] = new_successor
            debug_print("UPDATE_SUCCESSOR: Updated successor to", new_successor)
        elif cmd == 'UPDATE_PREDECESSOR':
            new_predecessor = (parts[1], int(parts[2]))
            with self.lock:
                self.predecessor = new_predecessor
            debug_print("UPDATE_PREDECESSOR: Updated predecessor to", new_predecessor)
        # --- DHT Operations ---
        elif cmd == 'PUT':
            key = parts[1]
            value = " ".join(parts[2:]) if len(parts) > 2 else ""
            key_id = generate_key_id(key, self.m)
            if self.is_responsible_for(key_id):
                with self.lock:
                    self.data[key] = value
                debug_print(f"PUT: Stored key '{key}' locally with value: {value}")
                self.send_message("PUT_ACK", addr)
            else:
                successor = self.find_successor_recursive(key_id)
                debug_print(f"PUT: Forwarding key '{key}' to successor {successor}")
                self.send_message(f"PUT {key} {value}", successor)
        elif cmd == 'PUT_ACK':
            debug_print("PUT_ACK received from", addr)
        elif cmd == 'GET':
            key = parts[1]
            key_id = generate_key_id(key, self.m)
            if self.is_responsible_for(key_id):
                with self.lock:
                    value = self.data.get(key, "None")
                debug_print(f"GET: Found key '{key}' locally with value: {value}")
                self.send_message(f"GET_REPLY {key} {value}", addr)
            else:
                successor = self.find_successor_recursive(key_id)
                debug_print(f"GET: Forwarding request for key '{key}' to successor {successor}")
                response = self.rpc(f"GET {key}", successor)
                if response:
                    self.send_message(response, addr)
        elif cmd == 'GET_REPLY':
            debug_print("GET_REPLY received; forwarding reply.")
            self.send_message(message, addr)
        elif cmd == 'DELETE':
            key = parts[1]
            key_id = generate_key_id(key, self.m)
            if self.is_responsible_for(key_id):
                with self.lock:
                    if key in self.data:
                        del self.data[key]
                        debug_print(f"DELETE: Key '{key}' deleted locally.")
                        self.send_message(f"DELETE_ACK {key} deleted", addr)
                    else:
                        debug_print(f"DELETE: Key '{key}' not found locally.")
                        self.send_message(f"DELETE_ACK {key} not_found", addr)
            else:
                successor = self.find_successor_recursive(key_id)
                debug_print(f"DELETE: Forwarding deletion request for key '{key}' to successor {successor}")
                response = self.rpc(f"DELETE {key}", successor)
                if response:
                    self.send_message(response, addr)
        elif cmd == 'DELETE_ACK':
            debug_print("DELETE_ACK received:", message)
        elif cmd == "TRANSFER_KEYS_REQUEST":
            new_node_ip = parts[1]
            new_node_port = int(parts[2])
            new_node_id = int(parts[3])
            new_node_pred_id = int(parts[4])
            keys_to_transfer = []
            with self.lock:
                for key, value in list(self.data.items()):
                    key_id = generate_key_id(key, self.m)
                    if in_range(key_id, new_node_pred_id, new_node_id, self.m):
                        keys_to_transfer.append((key, value))
                        del self.data[key]
            if keys_to_transfer:
                data_str = ";;".join([f"{k}|{v}" for k, v in keys_to_transfer])
            else:
                data_str = ""
            debug_print(f"TRANSFER_KEYS_REQUEST: Transferring keys {keys_to_transfer} to new node {(new_node_ip, new_node_port)}")
            self.send_message(f"TRANSFER_KEYS_REPLY {data_str}", (new_node_ip, new_node_port))
        elif cmd == "TRANSFER_KEYS_REPLY":
            data_str = " ".join(parts[1:])
            if data_str:
                pairs = data_str.split(";;")
                with self.lock:
                    for pair in pairs:
                        if pair:
                            k, v = pair.split("|", 1)
                            self.data[k] = v
                debug_print("TRANSFER_KEYS_REPLY: Received transferred keys:", self.data)
        else:
            debug_print("Unknown command received:", message)

    def send_message(self, message, target):
        try:
            self.sock.sendto(message.encode(), target)
            debug_print(f"Sent message to {target}: {message}")
        except Exception as e:
            debug_print(f"Failed to send message to {target}: {e}")

    def rpc(self, message, target, timeout=2, retries=3):
        for attempt in range(retries):
            temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            temp_sock.settimeout(timeout)
            try:
                temp_sock.sendto(message.encode(), target)
                data, _ = temp_sock.recvfrom(4096)
                temp_sock.close()
                debug_print(f"RPC: Received reply from {target} for message '{message}'")
                return data.decode()
            except Exception as e:
                debug_print(f"RPC error on attempt {attempt+1} to {target} for message '{message}': {e}")
                temp_sock.close()
                continue
        return None

    def join(self, known_node):
        start_value = self.finger_table[0]['start']
        debug_print(f"Join: Sending FIND_SUCCESSOR for {start_value} to known node {known_node}")
        self.send_message(f'FIND_SUCCESSOR {start_value} 0', known_node)
        threading.Thread(target=self.delayed_retrieve_keys, daemon=True).start()
        threading.Thread(target=self.update_others, daemon=True).start()

    def delayed_retrieve_keys(self):
        time.sleep(2)
        with self.lock:
            pred_id = generate_node_id(self.predecessor[0], self.predecessor[1], self.m)
            self_id = self.node_id
            successor = self.successor
        debug_print(f"Delayed retrieve keys: Requesting keys from successor {successor} for range ({pred_id}, {self_id}]")
        self.send_message(f"TRANSFER_KEYS_REQUEST {self.ip} {self.port} {self_id} {pred_id}", successor)

    def find_successor_recursive(self, id):
        current = (self.ip, self.port)
        while True:
            if current == (self.ip, self.port):
                with self.lock:
                    successor = self.successor
            else:
                response = self.rpc("GET_SUCCESSOR", current)
                if response is None:
                    debug_print("find_successor_recursive: No response from", current)
                    return None
                parts = response.split()
                if parts[0] != "SUCCESSOR_INFO":
                    return None
                successor = (parts[1], int(parts[2]))
            current_node_id = generate_node_id(current[0], current[1], self.m)
            successor_node_id = generate_node_id(successor[0], successor[1], self.m)
            if in_range(id, current_node_id, successor_node_id, self.m):
                debug_print(f"find_successor_recursive: Found successor {successor} for id {id}")
                return successor
            else:
                if current == (self.ip, self.port):
                    next_node = self.closest_preceding_finger(id)
                else:
                    response = self.rpc(f"RPC_CLOSEST_PRECEDING {id}", current)
                    if response is None:
                        return None
                    parts = response.split()
                    if parts[0] != "CLOSEST_PRECEDING":
                        return None
                    next_node = (parts[1], int(parts[2]))
                if next_node == current:
                    debug_print(f"find_successor_recursive: Closest preceding finger equals current; returning successor {successor}")
                    return successor
                debug_print(f"find_successor_recursive: Moving from {current} to next node {next_node} for id {id}")
                current = next_node

    def closest_preceding_finger(self, id):
        with self.lock:
            for i in range(self.m-1, -1, -1):
                finger_node = self.finger_table[i]['successor']
                finger_node_id = generate_node_id(finger_node[0], finger_node[1], self.m)
                if in_range(finger_node_id, self.node_id, id, self.m):
                    debug_print(f"closest_preceding_finger: For id {id}, finger index {i} with node {finger_node} qualifies.")
                    return finger_node
            debug_print(f"closest_preceding_finger: No finger found for id {id}, returning self.")
            return (self.ip, self.port)

    def request_predecessor(self, successor):
        debug_print(f"Requesting predecessor from successor {successor}.")
        self.send_message('GET_PREDECESSOR', successor)

    def update_finger_table(self, node, i):
        node_id = generate_node_id(node[0], node[1], self.m)
        with self.lock:
            current_successor_id = generate_node_id(self.finger_table[i]['successor'][0],
                                                      self.finger_table[i]['successor'][1], self.m)
            if in_range(node_id, self.node_id, current_successor_id, self.m):
                debug_print(f"update_finger_table: Updating finger table at index {i} with node {node}.")
                self.finger_table[i]['successor'] = node
                if self.predecessor != node:
                    self.send_message(f'UPDATE_FINGER_TABLE {node[0]} {node[1]} {i}', self.predecessor)

    # --- Immediate Update Propagation Methods ---
    def find_predecessor(self, id):
        p = (self.ip, self.port)
        while True:
            if p == (self.ip, self.port):
                with self.lock:
                    p_successor = self.successor
            else:
                response = self.rpc("GET_SUCCESSOR", p)
                if response:
                    parts = response.split()
                    if parts[0] == "SUCCESSOR_INFO":
                        p_successor = (parts[1], int(parts[2]))
                    else:
                        p_successor = (self.ip, self.port)
                else:
                    p_successor = (self.ip, self.port)
            p_id = generate_node_id(p[0], p[1], self.m)
            ps_id = generate_node_id(p_successor[0], p_successor[1], self.m)
            if in_range(id, p_id, ps_id, self.m):
                debug_print(f"find_predecessor: Found predecessor {p} for id {id}")
                return p
            else:
                if p == (self.ip, self.port):
                    p = self.closest_preceding_finger(id)
                else:
                    response = self.rpc(f"RPC_CLOSEST_PRECEDING {id}", p)
                    if response:
                        parts = response.split()
                        if parts[0] == "CLOSEST_PRECEDING":
                            p = (parts[1], int(parts[2]))
                        else:
                            break
                    else:
                        break
        debug_print(f"find_predecessor: Returning node {p} as predecessor for id {id}")
        return p

    def update_others(self):
        for i in range(1, self.m + 1):
            pred_index = (self.node_id - 2**(i - 1) + 2**self.m) % (2**self.m)
            p = self.find_predecessor(pred_index)
            debug_print(f"update_others: For finger index {i-1}, found node {p} to update.")
            if p != (self.ip, self.port):
                self.rpc(f"UPDATE_FINGER_TABLE {self.ip} {self.port} {i - 1}", p)
            time.sleep(0.1)

    # --- Stabilization Protocols with Timeouts and Fallbacks ---
    def stabilize(self):
        while self.running:
            try:
                with self.lock:
                    successor = self.successor
                response = self.rpc("GET_PREDECESSOR", successor, timeout=1)
                if response:
                    parts = response.split()
                    if parts[0] == "PREDECESSOR":
                        x = (parts[1], int(parts[2]))
                        x_id = generate_node_id(x[0], x[1], self.m)
                        succ_id = generate_node_id(successor[0], successor[1], self.m)
                        if x != (self.ip, self.port) and in_range(x_id, self.node_id, succ_id, self.m):
                            with self.lock:
                                self.successor = x
                                self.finger_table[0]['successor'] = x
                            debug_print(f"stabilize: Found a better successor {x}.")
                else:
                    debug_print(f"stabilize: Successor {successor} did not respond; checking alternate fingers.")
                    alternate = None
                    with self.lock:
                        for entry in self.finger_table:
                            candidate = entry['successor']
                            if candidate != (self.ip, self.port) and candidate != successor:
                                ping_response = self.rpc("PING", candidate, timeout=1)
                                if ping_response:
                                    alternate = candidate
                                    break
                    if alternate:
                        with self.lock:
                            self.successor = alternate
                            self.finger_table[0]['successor'] = alternate
                        debug_print(f"stabilize: Switched to alternate successor {alternate}.")
                    else:
                        with self.lock:
                            self.successor = (self.ip, self.port)
                            self.finger_table[0]['successor'] = (self.ip, self.port)
                        debug_print("stabilize: No alternate candidate found; setting successor to self.")
                with self.lock:
                    self.send_message(f"SET_PREDECESSOR {self.ip} {self.port}", self.successor)
            except Exception as e:
                debug_print("stabilize error:", e)
            time.sleep(1)

    def fix_fingers(self):
        i = 1
        while self.running:
            try:
                with self.lock:
                    next_start = self.finger_table[i]['start']
                successor = self.find_successor_recursive(next_start)
                if successor:
                    with self.lock:
                        self.finger_table[i]['successor'] = successor
                    debug_print(f"fix_fingers: Updated finger index {i} with successor {successor}.")
                i = (i + 1) % self.m
            except Exception as e:
                debug_print("fix_fingers error:", e)
            time.sleep(1)

    def check_predecessor(self):
        while self.running:
            try:
                with self.lock:
                    predecessor = self.predecessor
                if predecessor != (self.ip, self.port):
                    response = self.rpc("PING", predecessor, timeout=1)
                    if response is None:
                        debug_print("check_predecessor: Predecessor", predecessor, "not responding. Resetting to self.")
                        with self.lock:
                            self.predecessor = (self.ip, self.port)
            except Exception as e:
                debug_print("check_predecessor error:", e)
                with self.lock:
                    self.predecessor = (self.ip, self.port)
            time.sleep(1)

    def is_responsible_for(self, key_id):
        if self.predecessor == (self.ip, self.port):
            return True
        pred_id = generate_node_id(self.predecessor[0], self.predecessor[1], self.m)
        return in_range(key_id, pred_id, self.node_id, self.m)

    # --- DHT Operations for Clients ---
    def put(self, key, value):
        key_id = generate_key_id(key, self.m)
        if self.is_responsible_for(key_id):
            with self.lock:
                self.data[key] = value
            print(f"Key '{key}' stored locally.")
            debug_print(f"put: Key '{key}' stored locally with value '{value}'.")
        else:
            successor = self.find_successor_recursive(key_id)
            debug_print(f"put: Forwarding key '{key}' to node {successor}.")
            response = self.rpc(f"PUT {key} {value}", successor)
            if response and response.startswith("PUT_ACK"):
                print(f"Key '{key}' stored on remote node.")
            else:
                print(f"Failed to store key '{key}'.")

    def get(self, key):
        key_id = generate_key_id(key, self.m)
        if self.is_responsible_for(key_id):
            with self.lock:
                value = self.data.get(key)
            if value is not None:
                print(f"Value for key '{key}': {value}")
                debug_print(f"get: Found key '{key}' locally with value '{value}'.")
            else:
                print(f"Key '{key}' not found.")
                debug_print(f"get: Key '{key}' not found locally.")
        else:
            successor = self.find_successor_recursive(key_id)
            debug_print(f"get: Forwarding request for key '{key}' to node {successor}.")
            response = self.rpc(f"GET {key}", successor)
            if response and response.startswith("GET_REPLY"):
                parts = response.split(maxsplit=2)
                if len(parts) >= 3:
                    print(f"Value for key '{key}': {parts[2]}")
                    debug_print(f"get: Received value for key '{key}': {parts[2]}.")
                else:
                    print(f"Key '{key}' not found on remote node.")
            else:
                print(f"Failed to retrieve key '{key}'.")

    def delete(self, key):
        key_id = generate_node_id(key, self.m)
        if self.is_responsible_for(key_id):
            with self.lock:
                if key in self.data:
                    del self.data[key]
                    print(f"Key '{key}' deleted locally.")
                    debug_print(f"delete: Key '{key}' deleted locally.")
                else:
                    print(f"Key '{key}' not found.")
                    debug_print(f"delete: Key '{key}' not found locally.")
        else:
            successor = self.find_successor_recursive(key_id)
            debug_print(f"delete: Forwarding delete request for key '{key}' to node {successor}.")
            response = self.rpc(f"DELETE {key}", successor)
            if response and response.startswith("DELETE_ACK"):
                print(f"Key '{key}' deleted on remote node.")
            else:
                print(f"Failed to delete key '{key}'.")

    def leave_gracefully(self):
        with self.lock:
            pred = self.predecessor
            succ = self.successor
        debug_print("leave_gracefully: Initiating graceful leave.")
        if succ != (self.ip, self.port) and self.data:
            data_str = ";;".join([f"{k}|{v}" for k, v in self.data.items()])
            self.send_message(f"TRANSFER_KEYS_REPLY {data_str}", succ)
            debug_print(f"leave_gracefully: Transferred keys to successor {succ}.")
        if pred != (self.ip, self.port):
            self.send_message(f"UPDATE_SUCCESSOR {succ[0]} {succ[1]}", pred)
        if succ != (self.ip, self.port):
            self.send_message(f"UPDATE_PREDECESSOR {pred[0]} {pred[1]}", succ)
        self.running = False
        self.sock.close()
        debug_print("leave_gracefully: Node has left the network.")

def cli(node):
    help_text = (
        "Commands:\n"
        "  ft           - Display the current finger table\n"
        "  state        - Show current node state\n"
        "  put <k> <v>  - Store key/value pair in the DHT\n"
        "  get <k>      - Retrieve value for key from the DHT\n"
        "  delete <k>   - Delete key from the DHT\n"
        "  debug        - Toggle debug messages\n"
        "  leave        - Gracefully leave the network\n"
        "  help         - Show this help message\n"
        "  quit         - Exit the CLI and terminate the node"
    )
    print(help_text)
    while True:
        cmd = input("ChordCLI> ").strip()
        if not cmd:
            continue
        tokens = cmd.split()
        command = tokens[0].lower()
        if command in ["ft", "finger", "fingers"]:
            display_finger_table(node.node_id, node.finger_table, node.m)
        elif command == "help":
            print(help_text)
        elif command == "debug":
            global DEBUG
            DEBUG = not DEBUG
            print(f"Debug mode {'enabled' if DEBUG else 'disabled'}.")
        elif command == "state":
            with node.lock:
                print(f"Node ID: {node.node_id}")
                print(f"Predecessor: {node.predecessor}")
                print(f"Successor: {node.successor}")
                display_finger_table(node.node_id, node.finger_table, node.m)
                print("Stored Data:", node.data)
        elif command == "put":
            if len(tokens) < 3:
                print("Usage: put <key> <value>")
            else:
                key = tokens[1]
                value = " ".join(tokens[2:])
                node.put(key, value)
        elif command == "get":
            if len(tokens) < 2:
                print("Usage: get <key>")
            else:
                key = tokens[1]
                node.get(key)
        elif command == "delete":
            if len(tokens) < 2:
                print("Usage: delete <key>")
            else:
                key = tokens[1]
                node.delete(key)
        elif command == "leave":
            node.leave_gracefully()
            print("Node is leaving the network. Goodbye!")
            exit(0)
        elif command == "quit":
            print("Exiting CLI and terminating node.")
            exit(0)
        else:
            print("Unknown command. Type 'help' for available commands.")

if __name__ == "__main__":
    m = int(input("Enter the number of bits for the identifier space (m, up to 32): "))
    while m < 1 or m > 32:
        m = int(input("Invalid m. Enter a value between 1 and 32: "))
    port = int(input("Enter Port: "))
    known_ip = input("Enter known node IP (or press Enter if none): ")
    known_port = None
    if known_ip:
        known_port = input("Enter known node Port (or press Enter if none): ")
    known_node = (known_ip, int(known_port)) if known_ip and known_port else None
    node = ChordNode(port=port, known_node=known_node, m=m)
    node.start()
    threading.Thread(target=cli, args=(node,), daemon=False).start()