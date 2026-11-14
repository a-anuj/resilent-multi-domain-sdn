# Resilient Multi-Domain SDN: Multi-Controller Defense Testbed

Research testbed accompanying the paper **"Resilient Multi-Domain SDN: Automated High-Availability Circuit Breaking and Multi-Layer Defence Against Control-Plane Saturation and Poisoning Attacks"**.

The platform is built with **Mininet**, **Open vSwitch** and **Ryu**. It evaluates how three attacks on the North-South (OpenFlow) and East-West (REST) interfaces degrade a multi-domain Software-Defined Network, and how three attack-specific defences restore availability and protect state integrity.

> **Scope note:** All results come from a single-host emulation with a small number of runs (N=5 for Attack 1; one benchmark configuration each for Attacks 2 and 3). They are reported as medians and ranges, not confidence intervals. See [Limitations](#limitations).

---

## Authors

Dr. N Radhika, Anuj A, Hari Prasath K, Harish J, KVL Narasimha Kushal, Kirla Siva Sai Karthik
Department of Computer Science and Engineering, Amrita School of Computing, Amrita Vishwa Vidyapeetham, Coimbatore, India.

---

## Architecture at a Glance

* **Topology:** 9 Open vSwitch (OpenFlow 1.3) switches in 3 disjoint domains: **A** (s1-s3), **B** (s4-s6), **C** (s7-s9). Redundant intra-domain links are blocked by priority-2 drop rules to prevent broadcast storms. The attacker host `h1` attaches to `s1` port 3.
* **Control plane:** 3 Ryu controllers, one per domain, on OpenFlow ports 6633 (A), 6634 (B) and 6653 (C).
* **High availability:** every switch keeps two concurrent OpenFlow sessions: the domain controller as `MASTER` and a ring-neighbour as warm `SLAVE` (B is standby for s1-s3, C for s4-s6, A for s7-s9).
* **East-West REST protocol** (ports 8080-8082, served by the same eventlet process as the OpenFlow handlers):
  * `GET /topology`: local DPIDs, links, boundary ports
  * `GET /linkstate`: link utilisation ratios in [0, 1]
  * `POST /update`: ingest a peer update into the `GlobalTopology` graph
  * `POST /failover`: assume MASTER for given DPIDs
  * `POST /relinquish`: return mastership
* **Traffic engineering:** Dijkstra over link weights, where a link with utilisation >= 70% gets infinite weight, so traffic is diverted through an alternate transit domain.

```
[ Domain A: s1, s2, s3 ] <--- E-W REST (8080 <-> 8081) ---> [ Domain B: s4, s5, s6 ]
      (Primary: Ryu A)                                            (Primary: Ryu B)
      (Standby: Ryu B)                                            (Standby: Ryu C)
             \                                                           /
              \--- E-W REST ---> [ Domain C: s7, s8, s9 ] <-------------/
                                       (Primary: Ryu C)
                                       (Standby: Ryu A)
```

---

## Threat Model

| | Attack 1: PacketIn flood | Attack 2: E-W REST flood | Attack 3: Topology poison |
|---|---|---|---|
| Interface | OpenFlow (N-S) | E-W REST | E-W state (`GlobalTopology`) |
| Attacker | Untrusted edge host `h1` | Rogue/compromised peer | Insider / on-path peer |
| Vector | Table-misses with random spoofed IP/MAC | High-rate `POST /update` | Crafted semantic JSON |
| Rate | 5,000 pkt/s target | ~350 req/s, 8 workers | 1-5 requests |
| Failure mode | Event-queue backlog | Worker starvation, lock contention | Bad TE routes, black-holing |
| Root cause | Single-threaded handler loop | Parsing before rate limit | Unauthenticated state ingestion |

The attacker cannot read controller memory and does not tamper with the OpenFlow channel.

---

## Attacks and Defences

### Attack 1: North-South PacketIn Flood -> HA Circuit Breaker
**Threat.** `h1` sends raw frames (AF_PACKET) with a fresh random source MAC/IP per packet, ramping to 5,000 pkt/s. The resulting table-misses fill an unbounded event queue in Ryu's single-threaded loop.

**Root cause.** The backlog survives after the flood stops. Deleting datapath flows does not clear it; destroying the process does. Mitigation must therefore *replace* the controller rather than only filter traffic.

**Defence (`defense/circuit_breaker.py`)**, an external daemon monitoring domain A out of band:
1. **Dual-signal detection:** edge `PacketIn > 1,500 pkt/s` **and** controller `CPU > 70%`, holding continuously for a 3 s persistence window. (The 3 s is a persistence rule, not an onset-to-trigger latency.)
2. **Standby promotion:** `POST /failover` to Ryu B, which issues an OpenFlow 1.3 `OFPRoleRequest(MASTER)` for s1-s3.
3. **Process replacement:** `SIGKILL` the saturated Ryu A, then respawn it in slave mode (with a failback delay) so it does not process PacketIns.
4. **Anti-flapping meter:** drop meter (100 pkt/s) on ingress switch s1, with a flow matching `in_port=3` and `idle_timeout=30 s`. The rule persists while flood packets hit it and expires 30 s after the flood stops. (A fixed `hard_timeout` caused reboot loops in the cold-restart baseline.)
5. **Failback:** after 30 s of stable operation, Ryu B calls `POST /relinquish`.

**Results (median over N=5 undefended / N=5 defended runs, per-run phase means):**

| Metric | Undefended | Defended (HA) |
|---|---|---|
| Domain A baseline | 3.94 ms | 4.03 ms |
| Domain A attack | 93.62 ms (81.43-117.07) | **7.88 ms** (6.40-10.85) |
| Domain A recovery | 258.00 ms (220.58-356.54) | **6.00 ms** (4.14-8.82) |
| Domain B attack / recovery | 49.17 / 224.45 ms | 9.47 / 4.21 ms |
| Domain C attack / recovery | 28.27 / 152.59 ms | 6.63 / 3.83 ms |
| Failed domain-A probes | 0/331 | 0/375 |
| Counted PacketIn rate | 5,275 pkt/s | 440 pkt/s |
| Standby takeover + reconnection | n/a | **0.009 s** (0.009-0.024) |
| Time-to-mitigation (TTM) | n/a | **0.222 s** (0.186-0.239) |
| Full recovery to baseline | 0/5 | **5/5** |

Relative to undefended medians, attack-phase latency falls 91.6% and recovery latency 97.7%; peer-domain attack latency falls 80.7% (B) and 76.5% (C).

**Cold restart vs HA failover** (earlier revision, same detector, kills and restarts the controller in place, 60 s fixed-timeout meter):

| Metric | Cold restart | HA standby failover |
|---|---|---|
| Switch reconnection | 3.280 s | 0.009 s |
| Total TTM | 4.415 s (4.397-4.546) | 0.222 s (0.186-0.239) |
| Automated recovery | 3/5 | 5/5 |
| Attack-phase latency (defended) | 5.64 ms | 7.88 ms |

TTM drops by about 94% and reconnection is 99.7% shorter. Mean latency under defence is of the same order in both designs, so the advantage of HA lies in **availability, TTM and recovery reliability**, not mean latency.

**Where the time goes.** Takeover and reconnection are 9-24 ms (4-11% of TTM); the interval from reconnection to meter installation is 0.177-0.229 s (89-96%). The metering stage was not profiled and is the obvious target for further reduction.

**Observation (hypothesis).** In one defended run the topology update from domain A to its peers grew from 652 B to ~418 kB during the flood, consistent with spoofed hosts being registered and served to peers without ageing. This was not isolated from E-W coupling of stalled handlers or host CPU contention.

---

### Attack 2: East-West REST API Flood -> Token-Bucket Mitigator
**Threat.** ~350 req/s of `POST /update` from 8 parallel workers for 15 s starves WSGI workers and contends on the topology lock while domain B sends legitimate sync updates.

**Defence (`defense/ew_flood_mitigator.py`):**
* Flask/WSGI middleware applies a **per-peer token bucket** (fill 30 tokens/s, capacity 50) *before* JSON parsing or lock acquisition; excess requests get `HTTP 429` with an empty body.
* A **global limiter** caps aggregate E-W update throughput at 60 req/s across peers.

**Results (one flood run per condition):**

| Metric | Undefended | Defended |
|---|---|---|
| Flood requests dispatched | 4,155 | 4,274 |
| Flood admitted (HTTP 200) | 4,155 (100%) | 409 (9.6%) |
| Flood throttled (HTTP 429) | 0 | **3,865 (90.4%)** |
| Mean flood-request latency | 7.75 ms | 4.12 ms |
| Legit. sync baseline | 6.20 ms | 4.87 ms |
| Legit. sync under attack (p95) | 11.01 ms (18.54) | **6.71 ms** (10.69) |
| Surge over baseline | +77.6% | +37.8% |
| Legit. delivery / throttled | 100% (39/39) / 0 | 100% (40/40) / 0 |

Legitimate sync latency under attack is 39.1% lower than undefended, with no collateral 429 drops.

---

### Attack 3: East-West Topology and Link-State Poisoning -> Topology Guard
**Threat.** Low-volume crafted `/update` messages:
* `congestion_lie`: claims 95% utilisation on a link, forcing Dijkstra onto suboptimal paths.
* `phantom_link`: declares a non-existent switch port (e.g. port 99), black-holing inter-domain traffic.

**Defence (`defense/topology_guard.py`)**, three filters before any `GlobalTopology` change (failure -> `HTTP 403`):
1. **Layer 1, authentication:** HMAC-SHA256 over a canonical JSON serialisation (sorted keys, compact separators) in `X-EW-Signature`, verified with a constant-time comparison.
2. **Layer 2, schema and bounds:** field types enforced, domain in `{A, B, C}`, and every port must satisfy `1 <= p <= 64`.
3. **Layer 3, semantic delta:** stores last accepted utilisation per port and rejects updates where `|rho(t) - rho(t-1)| > 0.60`.

**Test vectors and outcome:**

| Vector | Undefended | With Guard | Intercepting layer |
|---|---|---|---|
| T1 unsigned congestion lie (0.95) | accepted | 403 | L1, missing HMAC |
| T2 forged HMAC | accepted | 403 | L1, HMAC mismatch |
| T3 unsigned phantom link | accepted | 403 | L1, missing HMAC |
| T4 signed phantom link (port 99) | accepted | 403 | L2, port > 64 |
| T5 signed lie, 0.08 -> 0.95 | accepted | 403 | L3, delta > 0.60 |
| T6 legitimate signed sync | accepted | accepted | all layers passed |

Rogue payloads blocked: **0/5 -> 5/5**. Phantom links / false ratios merged into the global graph: **2/2 -> 0/0**. Legitimate sync is admitted.

---

## Key Results Summary

| Attack | Metric | Undefended | Defended |
|---|---|---|---|
| **1: PacketIn flood** | Domain A attack latency | 93.62 ms | **7.88 ms** (-91.6%) |
| | Domain A recovery latency | 258.00 ms | **6.00 ms** (-97.7%) |
| | Standby takeover / reconnection | n/a (cold restart: 3.28 s) | **0.009 s** |
| | Time-to-mitigation | n/a (cold restart: 4.42 s) | **0.222 s** |
| | Failed domain-A probes | 0/331 | 0/375 |
| | Automated recovery | 0/5 (cold restart: 3/5) | **5/5** |
| **2: REST flood** | Flood blocked | 0% (0/4,155) | **90.4%** (3,865/4,274) |
| | Legit. sync latency | 11.01 ms | **6.71 ms** (-39.1%) |
| | Legit. delivery | 100% | 100% |
| **3: Topology poison** | Rogue payloads blocked | 0/5 | **5/5** |
| | Corrupting state merged | 2 phantom links, 2 false ratios | **0** |

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
│   └── topology_poison.py  # Attack 3: Topology/link-state poisoning
├── defense/              # Defense modules
│   ├── circuit_breaker.py    # Defense 1: Dual-signal detection, HA failover & metering
│   ├── ew_flood_mitigator.py # Defense 2: Token-bucket rate limiter middleware
│   └── topology_guard.py     # Defense 3: 3-layer HMAC, schema & semantic guard
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
├── research_paper_helper.md # Paper-drafting notes, math models, N=5 tables
└── requirements.txt      # Python package dependencies
```

---

## Experimental Methodology

* **Platform:** one Ubuntu 22.04 host running Mininet (>= 2.3), Open vSwitch (>= 2.17), three Ryu controllers (Python 3.11), the attacker, the telemetry sampler and the Circuit Breaker.
* **Attack 1 protocol:** every run starts from a clean state (all processes reset, fresh controllers and topology, 15 s for switch connections), then a 30 s baseline, 60 s attack and 60 s recovery. Each controller's REST endpoint is probed every 2 s. The metric is the response time of *successful* probes; failed probes are counted separately. A run is discarded if its baseline exceeds 30 ms (none were). Five undefended and five defended runs alternate at one code revision (commit `96c8af6`). The reported value is the median and min-max across runs of the per-run phase mean.
* **Attack 2 protocol:** 15 s flood from eight workers against `POST /update` of domain A while domain B sends legitimate sync updates, with and without the mitigator.
* **Attack 3 protocol:** six vectors (five rogue, one legitimate signed update) sent to `POST /update`; HTTP status, intercepting layer and resulting graph state recorded.
* **Metric scope:** control-plane responsiveness only, not data-plane latency, loss or throughput.

---

## Quick Start & Reproduction

### 1. Setup Environment
```bash
git clone https://github.com/a-anuj/sdn-multictrl.git
cd sdn-multictrl

source ~/ryu311/bin/activate
pip install -r requirements.txt
```

### 2. Run Evaluations
* **Attack 1 (PacketIn flood & HA Circuit Breaker):**
  ```bash
  sudo python3 experiments/eval_circuit_breaker.py
  ```
* **Attack 2 (East-West REST flood):**
  ```bash
  python3 experiments/eval_ew_flood.py --duration 15
  ```
* **Attack 3 (Topology & link-state poisoning):**
  ```bash
  python3 experiments/eval_topology_poison.py
  ```

### 3. Generate Evaluation Graphs
```bash
python3 experiments/plot_eval_figures.py
python3 experiments/plot_attack2_figures.py
python3 experiments/plot_attack3_figures.py
```
Generated PNG and PDF charts are stored in `results/figures/`.

### 4. Emergency Cleanup
Kill any remaining Mininet, Ryu or OVS processes:
```bash
sudo ./experiments/emergency_reset.sh
```

---

## Engineering Lessons

* Starting OpenFlow sessions while rapid spanning-tree convergence was still running caused socket drops and back-off loops; global RSTP is now stabilised before controllers are assigned.
* A fixed `hard_timeout` on the protective meter expired mid-flood and caused reboot loops; `idle_timeout` removed them.
* HMAC verification initially failed on legitimate updates because of differing JSON key order and whitespace; canonical serialisation on both sides fixed it.
* Triangular intra-domain loops caused broadcast storms before any attack; priority-2 drop flows on redundant links removed them.

---

## Limitations

* **Small sample, single host:** Attack 1 uses N=5 runs per condition on a host that also runs the attacker and sampler. No confidence intervals or significance tests are reported. Attacks 2 and 3 use one benchmark configuration each.
* **Bursty latency:** phase means are sensitive to which probes fall in a stall; undefended single probes reach 430-966 ms in attack and up to 1,814 ms in recovery.
* **Probe interval:** probes run every ~2 s, so an outage shorter than that could fall between probes. The reason the endpoint stayed reachable (0/375 failures) was not instrumented.
* **Cold-restart baseline** comes from an earlier revision (commit `28edf4`) and a separate campaign; two of its ten summaries were reconstructed from the orchestrator log. Earlier defence revisions did not always meet the recovery criterion, so the 5/5 rate applies to the final revision only.
* **Circuit Breaker** is an external process and a single point of failure; its thresholds (1,500 pkt/s, 70% CPU) were tuned for this testbed, and a fixed 30 s failback assumes a healthy replacement.
* **Topology Guard** uses a static shared HMAC key with no nonce or sequence number, so it does not stop replay of a valid signed update. The delta rule bounds a single jump but not a gradual ramp, a compromised domain with a valid key can sign false state about links it does not own, plausible-port phantom links pass the schema check, and the rule can reject a genuine abrupt load change. A shared key also gives no per-peer identity for the rate limiter.
* A 100% block rate on five hand-chosen vectors does not establish robustness against an adaptive adversary.
* No experimental comparison against related schemes (AVANT-GUARD, LineSwitch, DoSDefender and others) was performed.

## Future Work

1. Profile and shorten the metering stage that dominates TTM; keep the replaced controller's E-W service reachable.
2. More repetitions per condition with confidence intervals and recorded defence flags and code versions.
3. Data-plane throughput, loss and application-level measurements.
4. Ablations separating E-W coupling, CPU contention and state growth as causes of the cross-domain effect.
5. Per-peer identity, replay-resistant signing (nonces or monotonic sequence numbers), DPID-ownership checks and rate-aware delta smoothing.
6. Adaptive attackers, including ramped poisoning and replay.
7. A replicated or distributed Circuit Breaker; comparison with related schemes.
8. Hardware switches and multi-host deployment.

---

## Citation

```
N. Radhika, A. Anuj, K. Hari Prasath, J. Harish, K. V. L. Narasimha Kushal, and K. Siva Sai Karthik,
"Resilient Multi-Domain SDN: Automated High-Availability Circuit Breaking and Multi-Layer Defence
Against Control-Plane Saturation and Poisoning Attacks,"
Amrita School of Computing, Amrita Vishwa Vidyapeetham, Coimbatore, India.
Code and logs: https://github.com/a-anuj/sdn-multictrl
```

For the mathematical models, per-run tables and paper-section mappings, see [research_paper_helper.md](research_paper_helper.md).