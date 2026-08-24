# SDN Multi-Controller Research Testbed

A comprehensive research platform for studying **multi-controller SDN architectures**, East-West (E-W) communication protocols, and the impact of coordinated attacks on controller clusters.

---

## 📖 The Problem

As Software-Defined Networks (SDNs) scale, relying on a single centralized controller becomes a bottleneck and a single point of failure. To address this, **multi-controller architectures** have become the standard for large-scale deployments, where the network is partitioned into distinct domains managed by separate controllers. 

To maintain a cohesive global view of the network, these controllers must communicate using **East-West (E-W) protocols**. However, these protocols often lack robust authentication, assume a fully trusted inter-controller environment, and are susceptible to various exploits. When E-W channels are compromised or overwhelmed, the entire network's routing, Traffic Engineering (TE), and overall stability are jeopardized.

---

## 🎯 What We Are Trying to Solve

The goal of this research project is to expose and study the vulnerabilities inherent in multi-controller SDNs. Specifically, we aim to:
1. **Replicate a realistic multi-domain SDN environment** using Mininet and Ryu controllers.
2. **Implement a functional East-West synchronization protocol** that shares topology, link states, and coordinates path installation across domains.
3. **Establish baseline Traffic Engineering (TE)** capabilities that react to network congestion and automatically reroute flows.
4. **Develop and execute offensive security modules (Attacks)**—including control plane saturation and E-W topology poisoning—to measure how effectively they degrade network convergence, controller CPU/latency, and TE accuracy.

---

## 🛠️ How We Are Solving It

We built the environment through a phased approach:

- **Phase 1: Multi-Controller Topology**: Created a 9-switch, 3-domain topology in Mininet. Each domain (A, B, C) is managed by an independent Ryu OpenFlow controller.
- **Phase 2 & 3: East-West Synchronization**: Developed a REST-based E-W protocol (using Flask) running on ports 8080-8082. Controllers exchange `/topology` and `/linkstate` data, maintaining a eventually consistent `global_topology` registry.
- **Phase 4: Traffic Engineering (TE)**: Implemented a Dijkstra-based path selector that avoids congested links based on real-time port statistics exchanged over the E-W API. When a link exceeds a utilization threshold, new flows are rerouted automatically.
- **Phase 5: Attack Implementations**: We engineered three custom attack modules targeting the SDN infrastructure:
  1. **PacketIn Flood (North-South):** Exploits switch table-miss behaviors by injecting spoofed packets from a compromised host, saturating the controller's OpenFlow channels.
  2. **East-West REST Flood:** Simulates a rogue peer overwhelming the `/update` REST API with high-frequency valid JSON payloads, stalling legitimate E-W syncs.
  3. **Topology Poisoning (Novel):** A low-volume attack where a single crafted JSON payload injects a "congestion lie" (e.g., claiming a link is 95% congested) or a "phantom link" into the E-W mesh, manipulating the TE path selector into making malicious routing decisions.

---

## 🚧 Key Problems Faced & Solutions

During development, we encountered several complex architectural and timing challenges:

1. **OVS Handshake & STP Timing Issues**
   - **Problem:** Controllers would frequently disconnect or experience Open vSwitch connection backoffs during startup due to rapid STP tree reconfigurations.
   - **Solution:** We reordered the startup sequence. We now enable RSTP (Rapid Spanning Tree Protocol) globally first, wait for the network to stabilize, and *then* assign controllers to their respective switches.

2. **Inter-Domain Link Utilization Visibility**
   - **Problem:** Controllers were only tracking OpenFlow PortStats for their *own* switches. Boundary links connecting two different domains were not correctly monitored, preventing the TE engine from detecting congestion on critical inter-domain trunks.
   - **Solution:** Upgraded the E-W protocol to explicitly exchange boundary port statistics. The TE engine's `compute_path` function was refactored to consume these pre-computed utilization rates across all domains directly.

3. **TE False-Positive Triggers & Race Conditions**
   - **Problem:** The TE engine would try to reroute traffic too aggressively, or it would dispatch `PacketOut` messages before the peer controllers had fully installed the OpenFlow rules in other domains (leading to dropped packets and "FAIL-FAST" test abortions).
   - **Solution:** 
     - Added a blocking wait for the `POST /install_path` API across peers before the ingress controller allows the packet to flow.
     - Adjusted hard timeouts, idle timeouts, and added "pre-warm" margins to allow utilization metrics to propagate correctly before reacting.

---

## 📊 Results Obtained

- **Baseline Stability:** The E-W protocol handles hundreds of thousands of sync updates seamlessly. (e.g., logs confirm over 368,000 successful E-W exchanges).
- **Traffic Engineering (TE) Validation:** The TE engine successfully detects congestion on primary paths (like the `s3-s7` diagonal link) and consistently reroutes new incoming flows to secondary paths. We observed TE recovering up to **6.75 Mbps** of throughput on a heavily loaded network that would otherwise drop packets.
- **Attack Readiness:** 
  - The safety harness strictly validates target IPs (confining attacks to `10.0.0.0/24` or `127.0.0.1`), enforces rate limits via `safe_rate_ramp`, and utilizes a watchdog.
  - Initial tests confirm that **Topology Poisoning** easily bypasses normal TE logic, successfully forcing the controller to avoid perfectly viable paths with a single unauthenticated HTTP request.

---

## ⚙️ Prerequisites

| Tool | Version confirmed | Notes |
|------|------------------|-------|
| Python | 3.11 | Via `ryu311` venv |
| Ryu | 4.34 | Inside `~/ryu311` venv |
| Mininet | 2.3.1b4 | System-installed |
| Open vSwitch | system | Required by Mininet |

## 🚀 Usage & Quick Start

**1. Activate the environment:**
```bash
cd ~
source ryu311/bin/activate
cd ~/Desktop/multi-controller-attack/sdn-multictrl
```

**2. Emergency Reset:**
If a Mininet run behaves unexpectedly or an attack leaves the network in a bad state, clean it up with:
```bash
sudo ./experiments/emergency_reset.sh
```

**3. Run Preflight Checks:**
Ensures no dangling controllers are active and the testbed is healthy.
```bash
sudo python3 experiments/preflight_check.py
```

---

## 📁 Project Structure

```
sdn-multictrl/
│
├── controllers/        # Ryu OpenFlow controller applications (ew_controller.py)
├── topology/           # Mininet multi-domain topology scripts
├── eastwest/           # Custom E-W protocol APIs (ew_api.py, global_topo.py)
├── attacks/            # Attack simulation scripts (Floods, Topology Poisoning)
├── experiments/        # Test harnesses, preflight checks, emergency resets
├── results/            # Logs, TE metrics, and analysis JSONs
└── requirements.txt    # Python package dependencies
```
