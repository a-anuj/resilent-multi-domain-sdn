# Resilient Multi-Domain SDN: Multi-Controller Defense Testbed

A research testbed for evaluating control-plane resilience in **multi-domain Software-Defined Networks (SDNs)**. Built with **Mininet** and **Ryu**, this platform demonstrates how coordinated attacks on North-South and East-West interfaces cause control-plane failure, and implements automated, multi-layer defenses to maintain network availability and routing integrity.

> **Research Paper Authors:** For full mathematical models, statistical $N=5$ experimental tables, operational traces, and paper drafting mappings, see [research_paper_helper.md](research_paper_helper.md).

---

## Architecture at a Glance

* **Network Topology:** 9 Open vSwitch (OVS) switches partitioned into 3 independent domains (**Domain A**, **Domain B**, and **Domain C**).
* **Control Plane:** 3 autonomous Ryu OpenFlow 1.3 controllers (ports 6633, 6634, 6653) running on Linux.
* **High Availability (HA):** Switches maintain dual OpenFlow sessions (Primary as `MASTER`, adjacent controller as warm `SLAVE`).
* **East-West REST Protocol:** Inter-controller synchronization over HTTP REST (ports 8080–8082) for exchanging active links, port statistics, and topology updates.
* **Traffic Engineering (TE):** Dijkstra-based path computation with dynamic load balancing that automatically reroutes flows when link utilization exceeds 70%.

```
[ Domain A: s1, s2, s3 ] <--- E-W REST (8080 <-> 8081) ---> [ Domain B: s4, s5, s6 ]
      (Primary: Ryu A)                                            (Primary: Ryu B)
      (Standby: Ryu B)                                            (Standby: Ryu C)
             \                                                           /
              \--- E-W REST ---> [ Domain C: s7, s8, s9 ] <-------------/
                                       (Primary: Ryu C)
```

---

## The 3 Attacks & Their Defenses

### Attack 1: North-South PacketIn Flooding
* **The Threat:** An untrusted edge host floods the network with 5,000 pkt/s using spoofed random IPs/MACs. The resulting table-misses overwhelm Ryu's single-threaded `eventlet` loop, creating an unrecoverable queue backlog that spikes latency from ~4 ms to >320 ms and spills over to adjacent domains.
* **The Defense (`defense/circuit_breaker.py`):**
  * **Dual-Signal Detection:** Detects attack in ~3 seconds when edge `PacketIn > 1500 pkt/s` AND controller `CPU > 70%` for 3 consecutive seconds (zero false alarms).
  * **Zero-Downtime HA Failover:** Promotes the warm standby controller (Domain B) to `MASTER` via OpenFlow 1.3 in **0.010 seconds** (99.7% faster than cold restarts).
  * **Dynamic Datapath Metering:** Injects a drop meter on the ingress switch with `idle_timeout=30s`, preventing controller flapping during sustained floods.
* **Outcome:** Attack latency held at **5.02 ms** (vs 117 ms undefended), recovery latency restored to **4.44 ms**, with **0.70s total time-to-mitigation**.

---

### Attack 2: East-West REST API Flood
* **The Threat:** A rogue or compromised peer controller floods the East-West synchronization endpoint (`POST /update`) with ~350 req/s across 8 concurrent workers. This starves WSGI worker threads and locks the topology graph, causing legitimate peer sync latency to surge by +77.6% (p95 up to 18.5 ms).
* **The Defense (`defense/ew_flood_mitigator.py`):**
  * **Token-Bucket Pre-Filtering:** Flask middleware enforces per-peer token buckets (30 req/s, burst 50) and drops excess requests in <1 ms with `HTTP 429 Too Many Requests` *before* JSON parsing or locking.
  * **Global Rate Guard:** Caps aggregate East-West update throughput at 60 req/s across all peers.
* **Outcome:** **90.4% of flood requests blocked**, legitimate peer sync latency preserved at **6.71 ms** (39.1% lower than undefended), with **100% legitimate sync delivery** (0 false drops).

---

### Attack 3: East-West Topology & Link-State Poisoning
* **The Threat:** A stealthy semantic attack that sends low-volume, crafted updates:
  * `congestion_lie`: Falsely claims 95% link utilization, forcing the Dijkstra engine to reroute flows onto suboptimal paths.
  * `phantom_link`: Injects non-existent switch ports (e.g., port 99), black-holing inter-domain traffic.
* **The Defense (`defense/topology_guard.py`):**
  * **Layer 1 (HMAC-SHA256):** Verifies request signature `X-EW-Signature` using constant-time comparison. Unsigned or forged requests are rejected with HTTP 403.
  * **Layer 2 (Schema & Port Bounds):** Verifies schema types, domain whitelist (`{"A", "B", "C"}`), and blocks invalid port numbers (port $\ge 50$).
  * **Layer 3 (Semantic Delta Check):** Tracks utilization history per port and blocks sudden impossible utilization jumps exceeding $\Delta > 0.60$.
* **Outcome:** **100% of attack payloads blocked (5/5)** across all 3 layers, **zero phantom links or false ratios merged**, with 100% legitimate peer sync admission.

---

## Key Results Summary

| Attack Scenario | Metric | Undefended | Defended | Defense Impact |
|---|---|---|---|---|
| **Attack 1 (PacketIn Flood)** | Attack Latency | 117.45 ms | **5.02 ms** | **-95.7% latency** |
| | Recovery Latency | 327.14 ms | **4.44 ms** | **-98.6% recovery delay** |
| | Switch Reconnection | 3.28 s (reboot) | **0.010 s** (HA) | **99.7% faster failover** |
| | Time-to-Mitigation ($TTM$) | Unmitigated failure | **0.70 s** | Sub-second mitigation |
| **Attack 2 (REST API Flood)** | Flood Drop Rate | 0.0% (0 / 4,155) | **90.4% (3,865 / 4,274)** | Sub-ms HTTP 429 throttle |
| | Legitimate Sync Latency | 11.01 ms (p95: 18.5) | **6.71 ms** (p95: 10.6) | **39.1% lower latency** |
| | Legitimate Delivery | 100% | **100%** | Zero collateral drops |
| **Attack 3 (Topology Poison)** | Rogue Payloads Blocked | 0 / 5 (0.0%) | **5 / 5 (100.0%)** | 100% poison interception |
| | Control Plane Corruption | 2 phantom links, 2 lies | **0 (Zero Corruption)** | Untainted global topology |
| | Legitimate Sync Delivery | 100% | **100%** | Zero false positives |

---

## Project Structure

```
sdn-multictrl/
├── controllers/          # Ryu OpenFlow 1.3 controller with HA role support & TE
│   └── ew_controller.py
├── topology/             # Mininet 9-switch, 3-domain topology
│   └── multi_domain_topo.py
├── eastwest/             # East-West REST API and Global Topology graph
│   ├── ew_api.py
│   └── global_topo.py
├── attacks/              # Attack simulation scripts
│   ├── packetin_flood.py   # Attack 1: North-South PacketIn flood
│   ├── eastwest_flood.py   # Attack 2: East-West REST API flood
│   └── topology_poison.py # Attack 3: Topology/link-state poisoning
├── defense/              # Defense modules
│   ├── circuit_breaker.py  # Defense 1: Dual-signal detection, HA failover & metering
│   ├── ew_flood_mitigator.py # Defense 2: Token-bucket rate limiter middleware
│   └── topology_guard.py  # Defense 3: 3-layer HMAC, schema & semantic guard
├── experiments/          # Test harnesses and plotting scripts
│   ├── eval_circuit_breaker.py  # Attack 1 evaluation harness
│   ├── eval_ew_flood.py         # Attack 2 evaluation harness
│   ├── eval_topology_poison.py  # Attack 3 evaluation harness
│   ├── plot_eval_figures.py     # Attack 1 plot generator
│   ├── plot_attack2_figures.py  # Attack 2 plot generator
│   ├── plot_attack3_figures.py  # Attack 3 plot generator
│   └── emergency_reset.sh       # Emergency cleanup script
├── results/              # Logs, telemetry summaries, and publication figures (PNG/PDF)
│   ├── figures/                 # All generated graphs
│   ├── eval_ew/                 # Attack 2 evaluation report
│   └── eval_topo/               # Attack 3 evaluation report
├── research_paper_helper.md # Full research paper guide, math models, and N=5 tables
└── requirements.txt      # Python package dependencies
```

---

## Quick Start & Reproduction

### 1. Setup Environment
```bash
# Clone the repository
git clone https://github.com/a-anuj/sdn-multictrl.git
cd sdn-multictrl

# Activate virtual environment
source ~/ryu311/bin/activate
pip install -r requirements.txt
```

### 2. Run Evaluations
* **Attack 1 (PacketIn Flood & HA Circuit Breaker):**
  ```bash
  sudo python3 experiments/eval_circuit_breaker.py
  ```
* **Attack 2 (East-West REST Flood):**
  ```bash
  python3 experiments/eval_ew_flood.py --duration 15
  ```
* **Attack 3 (Topology & Link-State Poisoning):**
  ```bash
  python3 experiments/eval_topology_poison.py
  ```

### 3. Generate Evaluation Graphs
```bash
python3 experiments/plot_eval_figures.py
python3 experiments/plot_attack2_figures.py
python3 experiments/plot_attack3_figures.py
```
*Generated PNG and PDF charts are stored in `results/figures/`.*

### 4. Emergency Cleanup
To cleanly kill any remaining Mininet, Ryu, or OVS processes:
```bash
sudo ./experiments/emergency_reset.sh
```

---

## Citation & Full Research Paper Reference

For the comprehensive mathematical formulations, operational logs, $N=5$ experimental telemetry, and IEEE/ACM paper section mappings, refer to:
* **[research_paper_helper.md](research_paper_helper.md)**
