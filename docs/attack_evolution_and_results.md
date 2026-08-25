# Phase 5: SDN Attack Development and Characterization

This document outlines the development, optimization, and characterization of the attacks against the multi-domain SDN testbed, with a specific focus on the `PacketIn` flood vulnerability and its impact on the controller's event queue.

## 1. Overview of Attack Vectors

The testbed was subjected to three primary attack vectors:
1. **East-West API Flood**: Targets the REST API synchronization ports of the controllers to disrupt inter-domain state sharing.
2. **Topology Poisoning**: Injects malformed LLDP/BDDP packets to create fake inter-switch links, tricking the Traffic Engineering (TE) orchestrator into making suboptimal routing decisions.
3. **PacketIn Flood**: Injects continuous streams of unmatched packets from a compromised host (h1) to overwhelm the OpenFlow control channel and exhaust the controller's processing capacity.

---

## 2. The PacketIn Flood: Initial Stage & Bottleneck

### The Initial Implementation
In the early stages, the `PacketIn` flood was built using Python's **Scapy** library and standard socket interfaces. The script was designed to generate randomized packets and push them through the Mininet host interface.

### The Problem
The initial implementation suffered from a severe performance bottleneck on the attacker's side. Because Scapy dynamically constructs packet headers (Ethernet, IP, UDP) in Python for every single transmission, the worker threads became CPU-bound. 
Despite configuring the attack for 5,000 pkt/s, the generator could barely push **~800-1,000 pkt/s**. This meant we were stressing the attacker's CPU rather than the SDN controller, preventing us from capturing the true failure state of the network.

---

## 3. The Evolution: AF_PACKET Raw Socket Optimization

### The Solution
To bypass the Scapy overhead and standard socket limitations, we fundamentally rewrote the `packetin_flood.py` script:
1. **Raw Sockets**: Replaced Scapy's `sendp()` with raw `AF_PACKET` sockets (`socket.socket(socket.AF_PACKET, socket.SOCK_RAW)`).
2. **Pre-computed Buffers**: Instead of building packets dynamically, the script now pre-computes the raw byte-arrays for the Ethernet, IP, and UDP headers once at startup.
3. **Optimized Batching**: We implemented a microsecond-aware spin-wait loop that bursts packets in batches to meet precise rate targets without CPU exhaustion.

### The Result
The optimization was a complete success. The script can now accurately and reliably hit the exact **5,000 pkt/s** configuration limit, pushing over 300,000 packets during a standard attack window with virtually zero CPU bottleneck on the generator.

---

## 4. Characterizing the Failure State

With the throughput bottleneck resolved, the 5,000 pkt/s attack successfully induced a severe failure state in the Domain-A Ryu controller.
- **Baseline Latency**: ~17 ms
- **During Attack**: 300 ms - 600 ms
- **Post-Attack Recovery**: **> 1,500 ms to 3,000 ms**

Crucially, the degradation was **unbounded**. Even 10 minutes after the attack generator had stopped completely, the latency remained extraordinarily high, and the controller did not gracefully recover on its own.

---

## 5. Diagnosing the Root Cause (The Intervention Tests)

To pinpoint the exact bottleneck, we ran a two-part diagnostic suite.

### Part 1: Resource Monitoring
We monitored the controller's OS resources every 5 seconds during the attack cycle:
- **Memory (RSS)**: Hovered around ~200MB. No memory leak detected.
- **Threads/FDs**: Remained completely static at 1 thread and ~80 File Descriptors. No socket leak detected.
- **OVS Flow Tables**: Switch flow rules did not explode out of control.

### Part 2: Manual Interventions
Since the OS resources were stable, we tested manual interventions to see what would cure the network:
1. **Flow Table Flush (`ovs-ofctl del-flows`)**: Flushing the OVS switch flow tables did **nothing**. Latency remained trapped at ~1350ms.
2. **Controller Restart (`ryu-manager` restart)**: Hard-killing and restarting the Domain-A controller **instantly cured the network**, dropping latency back to ~95ms in under 2 seconds.

### Conclusion: Event Queue Saturation
The root cause of the unbounded failure is **Controller Event Queue Saturation**.
At 5,000 pkt/s, the single-threaded Ryu event loop (`gevent`/`eventlet`) gets completely overwhelmed. It builds a massive internal backlog of `PacketIn` events in memory. When the attack stops, Ryu spends the next several minutes processing tens of thousands of stale, useless attacker packets. Legitimate control packets (like ARP/ping resolutions) get stuck at the back of this massive queue, causing the >1,500ms latency. 

Restarting the controller instantly destroys this stale queue in memory, providing a fresh start.

---

## 6. Log Files to Review for Results

To verify the empirical data and results of these tests, review the following log files generated in the `results/` directory:

### Validating Attack Throughput Optimization
- **File**: `results/attack_packetin_<timestamp>.log`
- **What to look for**: Search for `Step 5000 pkt/s achieved`. You will see the script accurately hitting ~4990-5000 pkt/s, proving the `AF_PACKET` optimization succeeded.

### Validating Resource Stability (Part 1)
- **File**: `results/part1_diagnostic.csv`
- **What to look for**: Review the CSV data to see that `Threads` stayed at 1, `FDs` stayed at ~80, and `RSS_KB` capped at roughly 220,000 KB, proving no infinite leaks occurred.

### Validating Queue Saturation (Part 2 Interventions)
- **Failed Flush Test**: `results/attack_packetin_20260825T091714Z_summary.json`
  - *Observe*: `"recovery": { "avg_lat": { "A": 1350.08 } }` (Proves flushing the switch did not fix the latency).
- **Successful Restart Test**: `results/attack_packetin_20260825T092548Z_summary.json`
  - *Observe*: `"recovery": { "avg_lat": { "A": 95.05 } }` (Proves restarting the controller instantly fixed the latency).
- **Both Test**: `results/attack_packetin_20260825T093510Z_summary.json`
  - *Observe*: `"recovery": { "avg_lat": { "A": 54.82 } }` (Confirms the restart intervention works reliably).
