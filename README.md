# Chord Distributed Hash Table (DHT) Implementation

This project implements a **Chord Distributed Hash Table (DHT)** in Python. Chord is a decentralized **peer-to-peer (P2P) protocol** that provides efficient and scalable lookup services for distributed systems.

## Quickstart Guide

### Running a Chord Node
1. Copy all the contents from this repository.
2. Open a terminal and navigate to the folder containing `chord.py`.
3. Start a Chord node by running:
   ```bash
   python chord.py
   ```
4. You will be prompted to:
   - Enter the **number of bits** (`m`) for the identifier space (e.g., 3 for an 8-node system).
   - Enter the **port number** for the node.
   - Provide an **IP address and port of a known node** (or leave blank to start a new network).

### Interacting with the Chord Network
Once the node is running, you can enter commands:
- `ft` - Display the **finger table**.
- `state` - Show **node state**, including its **ID, successor, predecessor, and stored keys**.
- `put <key> <value>` - Store a key-value pair in the Chord network.
- `get <key>` - Retrieve a value from the Chord network.
- `delete <key>` - Remove a key from the Chord network.
- `leave` - Gracefully leave the network.
- `quit` - Exit the CLI and terminate the node.

## Core Concepts
- **Chord Routing & Lookups**: Chord efficiently locates a node responsible for a given key in **O(log N) hops**.
- **Finger Table**: Each node maintains a routing table to optimize lookups.
- **Successor & Predecessor Maintenance**: Nodes keep track of their neighbors for fault tolerance.
- **Consistent Hashing**: Nodes and keys are mapped to an identifier ring using **SHA-1 hashing**.

## Preview of Chord Network Behavior

### **Example Finger Table Output**
```bash
Finger Table for Node 5:
Index  Start      Interval            Successor
0      6         (6, 7)               (7, 5001)
1      7         (7, 1)               (1, 5002)
2      1         (1, 5)               (5, 5000)
```

### **Example Key Storage and Lookup**
```bash
ChordCLI> put apple 42
Key 'apple' stored on remote node.

ChordCLI> get apple
Value for key 'apple': 42
```

## Notes:
- Chord **self-stabilizes** by periodically updating finger tables and checking node health.
- **New nodes** can join dynamically without disrupting the network.
- **Keys are evenly distributed** across nodes using consistent hashing.

## Future Enhancements
- Implement **replication** for fault tolerance.
- Add **GUI visualization** for network topology.
- Improve **network partition recovery mechanisms**.


