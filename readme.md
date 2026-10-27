# Resilient Multi-Domain SDN: Automated Circuit Breaker Testbed

A comprehensive research platform for studying **multi-controller SDN architectures**, East-West (E-W) communication protocols, and defending against coordinated control-plane saturation attacks using an automated Circuit Breaker.

---

## The Problem

As Software-Defined Networks (SDNs) scale, relying on a single centralized controller becomes a bottleneck and a single point of failure. To address this, **multi-controller architectures** have become the standard for large-scale deployments, where the network is partitioned into distinct domains managed by separate controllers. 

To maintain a cohesive global view of the network, these controllers must communicate using **East-West (E-W) protocols**. 

### The Vulnerability
When a multi-domain SDN is subjected to a **PacketIn Flood attack** (where an attacker spoofs random MAC/IPs to continuously trigger flow-table misses), the controller's single-threaded event loop becomes catastrophically saturated. 
*   Because the controller cannot process packets fast enough, an unbounded backlog forms in the event queue.
*   Legitimate traffic gets stuck behind malicious traffic.
*   **The Result:** Latency spikes from ~14ms to over 1,350ms, inter-domain E-W synchronization breaks down, and the entire network experiences a cascading failure. Traditional mitigation (like flushing flow tables) fails because the controller process itself is poisoned by the internal queue backlog.

---

## What We Are Trying to Solve

The primary objective of this project is to build an **Automated Circuit Breaker** capable of detecting and mitigating control-plane saturation in real-time, restoring network functionality without requiring manual admin intervention.

Specifically, we aim to:
1. **Replicate a realistic multi-domain SDN environment** using Mininet and Ryu controllers.
2. **Implement Traffic Engineering (TE)** capabilities that react to network congestion and automatically reroute flows using an East-West protocol.
3. **Execute offensive security modules (Attacks)** to measure how effectively they degrade network convergence and controller CPU/latency.
4. **Develop a resilient defense mechanism** that can detect, isolate, and recover a saturated controller in under 20 seconds.

---

## How We Are Solving It (The Architecture)

We built the environment and the solution through a phased architectural approach:

### 1. Infrastructure (Phases 1-4)
- **Multi-Controller Topology**: Created a 9-switch, 3-domain topology in Mininet. Each domain (A, B, C) is managed by an independent Ryu OpenFlow controller.
- **East-West Synchronization**: Developed a REST-based E-W protocol running on ports 8080-8082. Controllers exchange `/topology` and `/linkstate` data, maintaining a consistent `global_topology` registry.
- **Traffic Engineering (TE)**: Implemented a Dijkstra-based path selector that avoids congested links based on real-time port statistics. When a link exceeds 70% utilization, new flows are rerouted automatically via alternative domains.

### 2. Offensive Attack Suite (Phase 5)
We engineered three custom attack modules to test resilience:
1. **PacketIn Flood (North-South):** Saturates the controller's OpenFlow channels by exploiting table-miss behaviors. (This is the primary attack causing unbounded degradation).
2. **East-West REST Flood:** Simulates a rogue peer overwhelming the `/update` REST API.
3. **Topology Poisoning:** Manipulates the TE path selector into making malicious routing decisions via crafted JSON payloads.

### 3. Defense Suite (Phase 6)
We designed three defense modules — one per attack vector:

#### 3a. Automated Circuit Breaker (`defense/circuit_breaker.py`) — PacketIn Flood
An out-of-band daemon that implements a three-stage pipeline to save the network from PacketIn saturation:
1. **Detect**: Uses a dual-signal threshold (Edge switch `PacketIn > 1500 pkt/s` **AND** Controller `CPU > 70%` for 3 consecutive seconds) to guarantee zero false positives.
2. **Mitigate**: Performs a surgical `SIGKILL` on the poisoned controller process and immediately respawns it, instantly clearing the unrecoverable event-queue backlog.
3. **Prevent**: Installs a temporary (60s) OpenFlow rate-limiting Meter (`band=type=drop, rate=100`) directly on the edge switch port.

#### 3b. E-W Flood Mitigator (`defense/ew_flood_mitigator.py`) — East-West REST Flood
A three-layer Flask middleware that wraps the `/update` REST endpoint:
1. **Per-peer Token Bucket** (Layer 1): Each source IP is assigned a token bucket limited to 30 req/s with a burst of 50. Excessive requests receive HTTP 429 immediately, before reaching any topology-merge code path.
2. **Global Rate Guard** (Layer 2): A sliding-window counter caps total `/update` throughput at 60 req/s across all peers, defending against distributed / IP-rotating floods.
3. **Anomaly Detector** (Layer 3): A background thread monitors aggregate rate over a 10-second window. If it exceeds 25 req/s for 10 consecutive seconds, the mitigator activates a **quarantine** (tightening all peer limits to 5 req/s for 60 seconds) and logs a DETECT alert.

Install with one line in `eastwest/ew_api.py`:
```python
from defense.ew_flood_mitigator import install_ew_flood_mitigator
mitigator = install_ew_flood_mitigator(_app)
```

Or run as a standalone out-of-band monitor:
```bash
python3 defense/ew_flood_mitigator.py --api-port 8080
```

#### 3c. Topology Guard (`defense/topology_guard.py`) — Topology Poisoning
A three-layer validation pipeline that intercepts incoming `/update` payloads before they reach `global_topology`:
1. **HMAC-SHA256 Authentication** (Layer 1): Every trusted controller signs its payload with a shared secret. Unsigned or incorrectly-signed requests are rejected with HTTP 401, completely blocking unauthenticated rogue peers.
2. **Schema Validation** (Layer 2): Validates required fields (`type`, `domain_id`, `seq`), enforces a domain whitelist (`{A, B, C}`), checks that port numbers are realistic (≤ 64), and rejects phantom inter-links with port numbers ≥ 50 — the exact signature of the `phantom_link` attack.
3. **Semantic Cross-check** (Layer 3): Tracks last-known utilization ratios per port and rejects any single update that increases a ratio by more than 0.60 in one step — blocking the `congestion_lie` attack's sudden 0.95 injection.

Install with one line in `eastwest/ew_api.py`:
```python
from defense.topology_guard import install_topology_guard
install_topology_guard(_app, shared_secret=os.environ.get("EW_SHARED_SECRET"))
```

Or run as a standalone read-only detector:
```bash
python3 defense/topology_guard.py --api-port 8080
```

---

## Key Challenges Faced & How We Resolved Them

Building a robust, distributed SDN testbed and an automated defense system presented several complex challenges:

### 1. OVS Handshake & STP Timing Issues
*   **Challenge:** Controllers would frequently disconnect or experience Open vSwitch connection backoffs during startup due to rapid STP tree reconfigurations.
*   **Resolution:** We reordered the startup sequence. We now enable RSTP globally first, wait for the network to stabilize, and *then* assign controllers to their respective switches.

### 2. Inter-Domain Link Utilization Visibility
*   **Challenge:** Controllers were only tracking OpenFlow PortStats for their *own* switches. Boundary links connecting two different domains were not correctly monitored, breaking the TE engine.
*   **Resolution:** Upgraded the E-W protocol to explicitly exchange boundary port statistics. The TE engine's `compute_path` function was refactored to consume pre-computed utilization rates across all domains.

### 3. Controller Flapping During Circuit Breaker Recovery
*   **Challenge:** The Circuit Breaker successfully killed and restarted the controller. However, the moment the controller reconnected to the switches, the ongoing PacketIn flood instantly saturated the fresh controller's queue again, causing a continuous "kill/restart" loop (flapping).
*   **Resolution:** We engineered the **Prevention Stage**. Before the controller is allowed to fully recover, the Circuit Breaker issues an out-of-band `ovs-ofctl` command to inject a hardware Meter at the ingress switch. This rate-limits the attacker to 100 pkt/s, breaking the saturation cycle long enough for the control plane to stabilize.

### 4. API Dependency on the Poisoned Controller
*   **Challenge:** The Circuit Breaker initially relied on querying the controller's REST API (`/te_path`) to confirm it had successfully restarted. However, during recovery, complex routing modules take time to load, causing the API check to timeout and fail the mitigation pipeline.
*   **Resolution:** Shifted the health-check dependency to a lightweight, core endpoint (`/stats/switches` or `/health`). This allowed the Circuit Breaker to confirm reconnection instantly and proceed to the Prevention stage without delay.

### 5. Broadcast Storm Elimination & Single Surgical Trigger (`commit 28edf42`)
*   **Challenge:** The Circuit Breaker exhibited false triggers every 18 seconds in baseline (causing 22.67% probe loss), and re-triggered during attacks. Root causes:
    1. Mininet's `set-controller` reset datapath flows, allowing circular broadcast loops around the Domain A triangle (`s1` $\leftrightarrow$ `s2` $\leftrightarrow$ `s3`) which saturated the controller in baseline (~3,500 pkt/s, 100% CPU).
    2. During attack mitigation, the fallback drop flow targeted `in_port=1` (inter-switch trunk) instead of `in_port=3` (attacker `h1`), failing to block the flood and causing continuous re-saturation.
*   **Resolution:**
    1. Proactively installed OpenFlow drop flows (`priority=2, actions=drop`) on triangle hypotenuses upon switch connection in `controllers/ew_controller.py`, queried port descriptions via `OFPPortDescStatsRequest`, and filtered non-IPv4/ARP storm amplification.
    2. Corrected the Circuit Breaker datapath rule in `defense/circuit_breaker.py` to `in_port=3, actions=drop` to surgically cut off the attacker at the edge switch datapath.
    3. Reordered initialization in `experiments/eval_circuit_breaker.py` (`assign_controllers` before `enable_rstp`) and updated cleanup in `experiments/emergency_reset.sh`.
    4. **Result:** Baseline Packet-In rate dropped to 0 pkt/s (0% baseline probe failures), and the Circuit Breaker triggers **exactly once** per attack.

### 6. Controller Flapping on Sustained Floods (Fixed Timer vs. Dynamic Idle Timeout)
*   **Challenge:** The Circuit Breaker initially installed datapath mitigation rules (meter / port drop) with a fixed `hard_timeout=60`. If an attacker sustained the PacketIn flood past 60 seconds (e.g., a 100s+ sustained attack), the rule expired automatically while the attack was still active. The unthrottled flood immediately re-saturated the fresh controller's queue, forcing the Circuit Breaker to trigger another reboot in a repeating cycle (controller flapping).
*   **Resolution:** Replaced the fixed `hard_timeout=60` with dynamic `idle_timeout=30` in `defense/circuit_breaker.py`. The switch datapath rule now dynamically persists for the entire duration of active attack traffic, only self-clearing after the flow goes idle for 30 consecutive seconds.
*   **Verification:** Evaluated under a sustained 100-second attack flood (5,532 pkt/s, 565k packets). The Circuit Breaker triggered **exactly once** at onset ($TTM = 4.65\text{s}$), kept Domain A attack latency at **5.76 ms** throughout the remaining 85 seconds, and recorded **zero repeated restarts**—proving controller flapping is eliminated.

---

## Results & Evaluation

We executed a comprehensive 10-run evaluation suite (`experiments/eval_circuit_breaker.py`) systematically comparing the undefended network against the defended network (5 undefended runs and 5 defended runs alternating):

*   **Undefended System:** A 5,000 pkt/s PacketIn flood pushes Domain A median attack latency to **117.45 ms** (peaks >177 ms) and unrecoverable event queue backlog keeps recovery latency at a median of **327.14 ms** (spilling over to Domain B at 78.26 ms and Domain C at 23.59 ms). Control plane queue saturation is unmitigated and cascading (0/5 recovered).
*   **Defended System (HA Circuit Breaker):**
    *   **Average Detection Time:** ~3.0 seconds (dual-signal: PacketIn > 1,500 pkt/s + CPU > 70% for 3s).
    *   **Standby Failover Time:** **0.010 – 0.019 seconds** (instantaneous OpenFlow `OFPCR_ROLE_MASTER` promotion of backup controller via E-W REST `/failover`).
    *   **Total Time-to-Mitigation (TTM):** **0.70 seconds median** (0.68 – 0.72s, down from 4.44s before HA).
    *   **Attack-Phase Latency:** Held at a median of **5.02 ms** (near baseline).
    *   **Recovery-Phase Latency:** Restored to a median of **4.44 ms** (exact baseline, **100% recovery** across 5/5 runs).
    *   **Dynamic Rule Persistence:** Datapath meter installed with `idle_timeout=30s` preventing rule expiry and flapping during sustained floods.

---

### Comparative Evaluation Graphs

The two charts below illustrate the empirical contrast between the undefended network and the defended High Availability Circuit Breaker network:

#### 1. Latency by Operational Phase: Defended vs. Undefended
[![Domain-A Controller Latency by Phase](results/figures/fig4_defended_vs_undefended_latency.png)](results/figures/fig4_defended_vs_undefended_latency.pdf)
**Figure 1:** Controller REST latency across Baseline (30s), Attack (60s), and Recovery (60s). Under defense, latency stays pinned to baseline (<5.5 ms), whereas undefended runs remain paralyzed (>320 ms).

#### 2. End-to-End Latency Dynamics Timeline
[![End-to-End Latency Dynamics Timeline](results/figures/fig7_attack_timeline_profile.png)](results/figures/fig7_attack_timeline_profile.pdf)
**Figure 2:** Continuous 150-second timeline comparing an undefended run (persistent event queue saturation) against a defended HA run. Detection occurs at onset, followed by sub-second standby failover and meter installation (TTM = 0.70s), completely neutralizing the flood.

---

### Architectural Evolution: Before HA (Cold Restart) vs. After HA (Standby Failover)

#### Operational Log Comparison

**1. Before HA (`results/before_ha/circuit_breaker_run_4.log` — Cold Restart):**
```text
Circuit Breaker Started
[15:58:56] Monitoring Domain A (Switches: ['s1', 's2', 's3'])
[15:59:38] DETECT [TRIGGER]: Thresholds exceeded for 3 consecutive seconds.
[15:59:38] TIMING: t_detect=1793096978.4904
[15:59:38] MITIGATE: Killing affected controller PID 35742
[15:59:39] MITIGATE: Restart initiated. Time from detection to restart: 1.00s
[15:59:39] MITIGATE: Waiting for controller to reconnect and API to come up...
[15:59:42] MITIGATE: Reconnection confirmed! Time from restart to recon: 3.27s
[15:59:42] TIMING: t_reconnect_confirmed=1793096982.7608 (elapsed=4.270s)
[15:59:42] PREVENT: Installing OpenFlow rate-limit meter on edge switch...
[15:59:42] PREVENT: Rule installed. Expires in 60s.
[15:59:42] PIPELINE COMPLETE: Total time-to-mitigation: 4.40s
```

**2. After HA (`results/after_ha/circuit_breaker_run_4.log` — Standby Failover):**
```text
Circuit Breaker Started
[20:15:32] Monitoring Domain A (Switches: ['s1', 's2', 's3'])
[20:16:14] DETECT [TRIGGER]: Thresholds exceeded for 3 consecutive seconds.
[20:16:14] TIMING: t_detect=1793112374.8748
[20:16:14] MITIGATE [HA]: Attempting fast failover to Standby Controller (API port 8081)...
[20:16:14] MITIGATE [HA SUCCESS]: Standby controller promoted to MASTER for DPIDs [1, 2, 3] in 0.010s (Zero-Downtime HA)!
[20:16:15] MITIGATE [HA]: Respawned Controller A in background (SLAVE mode, 30s stability delay before failback)
[20:16:15] TIMING: t_reconnect_confirmed=1793112374.8853 (elapsed=0.010s)
[20:16:15] PREVENT: Installing OpenFlow rate-limit meter on edge switch...
[20:16:15] PREVENT: Rule installed with idle_timeout=30s (persists while attack active, clears 30s after idle).
[20:16:15] PIPELINE COMPLETE: Total time-to-mitigation: 0.71s
```

**3. Standby Controller Promotion Log (`results/after_ha/ryu_B.log`):**
```text
[Domain B] HA FAILOVER TAKEOVER: Promoted DPIDs [1, 2, 3] to MASTER
```

---

### Architectural & Telemetry Comparison Table

| Metric / Dimension | Before HA (`before_ha` — Cold Restart) | After HA (`after_ha` — Fast Standby Failover) | Impact / Delta |
|---|---|---|---|
| **Mitigation Architecture** | Surgical SIGKILL + local controller respawn | Dual-controller OVS primary/backup + REST `/failover` | Zero-downtime control plane migration |
| **Switch Reconnection Mechanism** | Reconnection polling via `/health` API (cold reboot) | Standby switch promoted to `MASTER` via OpenFlow role request | **0.01s vs 3.28s (99.7% faster)** |
| **Total Time-to-Mitigation (TTM)** | **4.40 s – 4.44 s** | **0.68 s – 0.72 s** (median **0.70 s**) | **84% reduction in total mitigation time** |
| **Domain A Attack Latency** | 5.76 ms (mean) | **5.02 ms** (median) | Near baseline under active attack |
| **Domain A Recovery Latency** | 9.25 ms (mean) | **4.44 ms** (median) | Clean return to exact baseline (<5 ms) |
| **Domain B Cross-Domain Spillover** | 74.06 ms (undefended) / 4.66 ms (defended) | 78.26 ms (undefended) / **4.15 ms** (defended) | Complete cross-domain isolation |
| **Datapath Meter Rule Timeout** | Fixed `hard_timeout=60s` (risks flapping on long attacks) | Dynamic `idle_timeout=30s` (persists for attack duration) | Zero controller flapping verified |
| **Recovery Success Rate** | 3 / 5 (60%) | **5 / 5 (100.0%)** | 100% reliable automated recovery |

---

### Detailed Defended vs. Undefended Experimental Telemetry ($N=5$ Pairs)

| Telemetry Metric | Undefended Runs ($N=5$) | Defended Runs ($N=5$) | Delta / Defense Impact |
|---|---|---|---|
| **Achieved PacketIn Rate (pkt/s)** | Median: 5,469.26 (5,399.79 – 5,517.68) | Median: 572.79 (392.52 – 580.11) | Throttled at edge datapath after TTM |
| **Domain A Baseline Latency (ms)** | Median: 4.58 (Range: 4.35 – 5.27) | Median: 4.18 (Range: 4.10 – 4.62) | Clean, storm-free baseline (<5 ms) |
| **Domain A Attack-Phase Latency (ms)**| Median: 117.45 (Range: 73.92 – 177.50) | Median: 5.02 (Range: 4.49 – 9.59) | **-95.7% latency reduction** |
| **Domain A Recovery-Phase Latency (ms)**| Median: 327.14 (Range: 226.74 – 383.58) | Median: 4.44 (Range: 4.37 – 4.77) | **-98.6% queue recovery restoration** |
| **Domain B Attack-Phase Latency (ms)**| Median: 78.26 (Range: 74.15 – 82.50) | Median: 4.15 (Range: 3.82 – 5.12) | **-94.7% cross-domain isolation** |
| **Domain C Attack-Phase Latency (ms)**| Median: 23.59 (Range: 19.80 – 28.10) | Median: 4.04 (Range: 3.65 – 4.80) | Transit path protected |
| **Total Time-to-Mitigation (TTM)** | N/A (unmitigated failure) | Median: **0.70 s** (Range: 0.68 – 0.71 s) | Sub-second zero-downtime mitigation |
| **Restart-to-Reconnection Time** | N/A | Median: **0.01 s** (Range: 0.01 – 0.02 s) | Instantaneous standby role promotion |
| **Reconnection-to-Meter Time** | N/A | Median: **0.68 s** (Range: 0.66 – 0.70 s) | Rapid OpenFlow meter installation |
| **Recovery Verdict** | **0 / 5 (0.0% recovered)** | **5 / 5 (100.0% recovered)** | Clean event loop and queue clearance |

---

## Project Structure

```
sdn-multictrl/
│
├── controllers/        # Ryu OpenFlow controller apps (ew_controller.py)
├── topology/           # Mininet multi-domain topology builder scripts
├── eastwest/           # Custom E-W protocol APIs (ew_api.py, global_topo.py)
├── attacks/            # Attack simulation scripts
│   ├── packetin_flood.py     # Attack 1: North-South PacketIn flood
│   ├── eastwest_flood.py     # Attack 2: East-West REST API flood
│   └── topology_poison.py   # Attack 3: Topology/linkstate poisoning
├── defense/            # Defense modules (one per attack vector)
│   ├── circuit_breaker.py    # Defense 1: Automated circuit breaker (PacketIn flood)
│   ├── ew_flood_mitigator.py # Defense 2: Token-bucket rate limiter (E-W flood)
│   └── topology_guard.py    # Defense 3: HMAC + schema + semantic guard (Topo poisoning)
├── experiments/        # Test harnesses, evaluation orchestrators, plot generators
├── results/            # Logs, TE metrics, evaluation JSONs, and PDF figures
├── docs/               # In-depth architectural write-ups and paper drafts
├── results_summary.md  # Master reference for all experimental parameters
└── requirements.txt    # Python package dependencies
```

## Usage & Quick Start

**1. Activate the environment:**
```bash
source ~/ryu311/bin/activate
cd ~/Desktop/multi-controller-attack/sdn-multictrl
```

**2. Run the End-to-End Circuit Breaker Evaluation:**
This script sets up the network, starts the controllers and Circuit Breaker, launches all three attacks, and measures the recovery metrics.
```bash
sudo python3 experiments/circuit_breaker_eval.py
```

**3. Generate High-Resolution Figures:**
Processes the JSON results into PDF/PNG charts and CSV tables suitable for research paper insertion (saved to `results/figures/`).
```bash
python3 experiments/generate_results.py
```

**4. Emergency Reset:**
If a Mininet run behaves unexpectedly, clean up the environment with:
```bash
sudo ./experiments/emergency_reset.sh
```
