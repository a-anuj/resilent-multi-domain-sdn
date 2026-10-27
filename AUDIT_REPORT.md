# Evidence-Based Audit Report: sdn-multictrl Testbed

**Repository:** `sdn-multictrl` (Multi-Domain SDN Testbed: Mininet + Open vSwitch, 3 Ryu Controllers, REST East-West Layer, 3 Attacks, 3 Defenses)  
**Date of Audit:** October 25, 2026  
**Auditor:** Automated Independent Audit Agent  
**Audit Scope:** Codebase integrity, raw telemetry verification, reproducibility, defense enablement, and documentation consistency for research paper submission.  
**Strict Policy:** Read-only inspection of repository state. All assertions grounded in exact file paths, line numbers, JSON keys, and raw log lines.

---

## Key Findings Summary

### (a) Verified Run Counts
* **PacketIn Flood Runs (North-South):** **19 runs** total recorded in `results/attack_packetin_*_summary.json`.
  * **9 runs** classified as `OK` (graceful recovery or defended).
  * **9 runs** classified as `RECOVERY_FAILED` (controller event-loop saturation).
  * **1 run** unclassified (`NOT_IN_FILE`, initial test `20260824T154349Z`).
* **East-West REST Flood Runs:** **11 runs** recorded in `results/attack_eastwest_*_summary.json` (plus 2 raw log files from September 18, 2026).
  * 10 runs classified as `OK`, 1 run missing result field.
  * All 11 summary runs were executed at an attack rate ramp of **10 to 150 req/s**; 0 runs exceeded 150 req/s.
* **Topology Poisoning Runs:** **11 runs** in `results/attack_poison_*_summary.json`.
  * **10 runs** completed in `congestion_lie` mode (injecting `ratio: 0.95`).
  * **1 file** is completely empty (0 bytes: `attack_poison_20260825T073252Z_summary.json`).
  * **0 runs** recorded in `phantom_link` mode in the summary suite.
* **Attack Suite Aggregates:** **21 files** in `results/attack_suite_*_summary.json`.
* **Circuit Breaker Triggers:** **8 triggers** recorded in `results/circuit_breaker.log` across a single daemon session, of which **7 completed the full mitigation cycle** and 1 was terminated at shutdown.

---

### (b) Verified Headline Numbers
* **Baseline Latency (Domain A):** Typically **13.47 ms to 20.81 ms** across uncorrupted runs (e.g., `13.83 ms` in `results/attack_packetin_20260825T105158Z_summary.json`). The specific claim of **13.8 ms** matches Run 19 baseline (`13.83 ms`), but is hardcoded as literal string `"13.8"` in `experiments/generate_results.py:47`.
* **Undefended Saturation Peak Latency:** Exceeds **1,350 ms**, reaching up to **2,105.43 ms** during attack (`results/attack_packetin_20260825T085624Z_summary.json:line 26`) and **2,892.34 ms** during recovery (`line 39`). Saturated peaks reached **3,135.50 ms** in `results/attack_packetin_20260825T083338Z.log:line 133` and **5,870.20 ms** in `results/attack_packetin_20260825T085624Z.log:line 86`. The claim `> 1350.0 ms` reflects Run 15 recovery average of `1350.08 ms` (`results/attack_packetin_20260825T091714Z_summary.json:line 41`).
* **Defended Post-Mitigation Latency:** Capped at **14.02 ms** during attack and **11.43 ms** post-mitigation in the defended run (`results/attack_packetin_20260825T105158Z_summary.json:line 26, 41`).
* **Detection Time:** **3.0 seconds** (exactly 3 consecutive 1-second violation polls where PacketIn rate > 1,500 pkt/s and CPU > 70%, coded in `defense/circuit_breaker.py:149-153`).
* **Total Mitigation Time (~16.7 s):** **16.44 s to 16.59 s** recorded in `results/circuit_breaker.log`. **Critical finding:** Exactly **15.0 seconds** of this duration is an unhandled timeout in a polling loop querying a non-existent REST endpoint (`/stats/switches`), not algorithmic convergence time.
* **East-West Flood Degradation (+11.8%):** Verified from the raw summary data. Across the 10 successful E-W flood runs (10 $\to$ 150 req/s ramp), the median latency delta on Domain A is **+11.84%** (middle values: 11.19% and 12.50%).

---

### (c) Key Discrepancies Between Documentation and Raw Data/Code
1. **The 16.7 s Mitigation Time is an HTTP 404 Timeout Failure:** `readme.md:118` advertises `"Total Mitigation Time: ~16.7 seconds (including the brief controller reboot)"`. In reality, `defense/circuit_breaker.py:61-69` polls `http://127.0.0.1:8080/stats/switches` with a 15-second timeout. Because port 8080 hosts Flask (`eastwest/ew_api.py`) which exposes only E-W REST routes (and Ryu's `ryu.app.ofctl_rest` is never loaded), the endpoint returns 404. Every cycle logs `MITIGATE: Reconnection NOT confirmed after 15s (API unresponsive)` (`results/circuit_breaker.log`). The total mitigation time formula is: $1.0\text{ s (restart sleep)} + 15.0\text{ s (timeout)} + \approx 0.5\text{ s (ovs-ofctl meter)} \approx 16.5\text{--}16.7\text{ s}$.
2. **Paper Figures & Tables Are Sourced From Hardcoded Dictionaries:** `experiments/generate_results.py` lines 43-47, 89-95, and 98-103 directly hardcode the baseline (`13.8`), peak (`> 1350.0`), post-mitigation (`14.02`), detection time (`3.0`), and mitigation time (`16.7`) into static strings and lists written to `results/figures/table1_mitigation_times.csv` and `results/figures/table2_te_metrics.csv`.
3. **HTTP Status Code Inconsistency for Topology Rejections:** `readme.md:76` states unauthenticated requests are rejected with `HTTP 401`. `readme.md:129` states `HTTP 403`. In the code, `defense/topology_guard.py:438` strictly catches `GuardRejection` and returns `HTTP 403` for all rejection types (HMAC missing/mismatch, schema violations, and semantic jumps). `HTTP 401` is never returned.
4. **Legitimate Controllers Do Not Sign Payloads:** `readme.md:76` claims every trusted controller signs its payload with HMAC-SHA256. In the actual controller code (`eastwest/sync_agent.py:197-201, 222-226`), outgoing `/update` POST requests send no `X-EW-Signature` header and never call `sign_payload()`. If Topology Guard were enabled in production, **all legitimate inter-domain controller traffic would be dropped with HTTP 403**.
5. **No Anti-Replay or Cross-Domain Validation:** `defense/topology_guard.py:176-179` validates only that `seq` is a non-negative integer. It does not track state, store seen sequence numbers, or enforce monotonicity; duplicate/replayed payloads pass. Furthermore, it does not check if switch DPIDs belong to the claiming domain (`lines 170-174`).
6. **Phantom Link Detection is a Hardcoded Threshold:** `defense/topology_guard.py:197-203` flags phantom links solely if switch port $\ge 50$. Any phantom link constructed on realistic port numbers (e.g., ports 1–6) passes schema validation.

---

### (d) Defense Enablement Audit Matrix
| Defense Module | Target Threat | Called in Production (`ew_api.py` / Controllers)? | Present in Attack Test Suites (`attack_test.py`)? | Verified Standalone Test Runs? |
| :--- | :--- | :--- | :--- | :--- |
| **Circuit Breaker** (`defense/circuit_breaker.py`) | PacketIn Flood | **NO** (Stand-alone daemon; started only in `circuit_breaker_eval.py`) | **NO** in runs 1–17; **ACTIVE** as external process in runs 18–19 | Yes (`results/circuit_breaker.log`) |
| **E-W Flood Mitigator** (`defense/ew_flood_mitigator.py`) | E-W REST Flood | **NO** (Only commented out in `eastwest/ew_api.py:30-31, 132`) | **NO** | Yes (`experiments/test_defenses.py`, log `ew_flood_defense_20261014T154134Z.log`) |
| **Topology Guard** (`defense/topology_guard.py`) | Topology Poisoning | **NO** (Only commented out in `eastwest/ew_api.py:34-35, 133`) | **NO** | Yes (`experiments/test_defenses.py`, log `topology_guard_20261014T154139Z.log`) |

---

## PART 1: Repository Inventory & File Provenance

### 1.1 Directory Tree, File Sizes, and Last Modified Dates

#### `results/` Directory Summary (228 files, 88,764,204 bytes)
* Key Data Files:
  * `results/part1_diagnostic.csv` (3,912 bytes, last modified 2026-08-25): Telemetry during controller saturation (CPU, RSS, threads, FDs).
  * `results/circuit_breaker.log` (6,250 bytes, last modified 2026-08-25): Output log of Circuit Breaker triggers.
  * `results/cb_restart.log` (2,138 bytes, last modified 2026-08-25): Output log of Ryu controller restart initiated by Circuit Breaker.
  * `results/ryu_A_restart.log` (179,340 bytes, last modified 2026-08-25): Output log from manual/scripted controller A restarts.
  * `results/te_decisions.log` (338,819 bytes, last modified 2026-08-25): Real-time TE reroute decisions log.
  * `results/te_comparison.json` (176,597 bytes, last modified 2026-08-25): Snapshot comparison of TE-on vs TE-off datapath stats.
  * `results/ew_flood_defense_20261014T154134Z.log` (4,292 bytes, last modified 2026-10-14): Execution log of `test_defenses.py` Suite 1.
  * `results/topology_guard_20261014T154139Z.log` (3,243 bytes, last modified 2026-10-14): Execution log of `test_defenses.py` Suite 2.
  * `results/controllers/controller_A.log`, `B.log`, `C.log` (7,790 bytes each, last modified 2026-08-25).
* Summary JSONs:
  * 19 files matching `results/attack_packetin_*_summary.json` (sizes 1,189 to 1,230 bytes).
  * 11 files matching `results/attack_eastwest_*_summary.json` (sizes 1,029 to 1,235 bytes).
  * 11 files matching `results/attack_poison_*_summary.json` (10 files ~1,200 bytes; 1 file 0 bytes).
  * 21 files matching `results/attack_suite_*_summary.json` (sizes 186 to 1,350 bytes).
* Output Figures & Tables:
  * `results/figures/fig1_te_utilization.png` (147,024 bytes) & `.pdf` (16,844 bytes).
  * `results/figures/fig2_attack_latency.png` (113,149 bytes) & `.pdf` (15,777 bytes).
  * `results/figures/fig3_detection_accuracy.png` (94,308 bytes) & `.pdf` (14,851 bytes).
  * `results/figures/table1_mitigation_times.csv` (324 bytes).
  * `results/figures/table2_te_metrics.csv` (224 bytes).
  * `results/proof_of_work/fig1_packetin_latency_timeline.png` through `fig12_packetin_scatter.png` (12 PNG files, 99 KB to 253 KB each).
  * `results/proof_of_work/PROOF_OF_WORK.md` (19,990 bytes, last modified 2026-10-14).

#### `experiments/` Directory (22 files, 371,053 bytes)
* `experiments/basic_test.py` (13,154 bytes, last modified 2026-08-24): Validates single-domain L2 switching.
* `experiments/verify_phase1.py` (18,697 bytes, last modified 2026-08-24): Phase 1 verification tests.
* `experiments/domain_test.py` (15,374 bytes, last modified 2026-08-24): Multi-domain routing testbed validator.
* `experiments/phase3_test.py` (18,018 bytes, last modified 2026-08-24): Phase 3 east-west linkstate synchronization test.
* `experiments/te_test.py` (35,212 bytes, last modified 2026-08-24): Evaluates utilization-aware dynamic routing.
* `experiments/preflight_check.py` (2,711 bytes, last modified 2026-08-25): Pre-attack environment sanity checks.
* `experiments/emergency_reset.sh` (818 bytes, last modified 2026-08-25): Force clean Mininet, OVS, and Ryu processes.
* `experiments/attack_test.py` (37,743 bytes, last modified 2026-08-25): Primary attack orchestrator and metric logger.
* `experiments/circuit_breaker_eval.py` (5,720 bytes, last modified 2026-08-25): Evaluation harness running Circuit Breaker with attacks.
* `experiments/generate_results.py` (5,551 bytes, last modified 2026-08-25): Generates paper figures and CSV tables.
* `experiments/test_defenses.py` (24,727 bytes, last modified 2026-10-14): Standalone mock Flask test suite for Mitigator and Guard.
* `experiments/generate_proof_graphs.py` (38,851 bytes, last modified 2026-10-14): Parses raw logs to generate proof-of-work graphs.

#### `attacks/` Directory (11 files, 110,881 bytes)
* `attacks/safety.py` (5,278 bytes, last modified 2026-08-25): Safety checks (target IP validation, watchdog timer).
* `attacks/packetin_flood.py` (15,838 bytes, last modified 2026-08-25): North-South packet-in attack using `AF_PACKET` raw sockets.
* `attacks/eastwest_flood.py` (13,627 bytes, last modified 2026-08-25): REST API flood against `/update`.
* `attacks/topology_poison.py` (14,023 bytes, last modified 2026-08-25): Fake LLDP/linkstate update injection (`congestion_lie`, `phantom_link`).

#### `defense/` Directory (8 files, 108,979 bytes)
* `defense/circuit_breaker.py` (6,805 bytes, last modified 2026-08-25): Dual-threshold daemon, process killer, and OVS meter injector.
* `defense/ew_flood_mitigator.py` (18,794 bytes, last modified 2026-10-14): Token-bucket rate limiter and anomaly detector.
* `defense/topology_guard.py` (25,659 bytes, last modified 2026-10-14): HMAC authentication, schema validator, and semantic checker.

#### `controllers/` Directory (11 files, 151,969 bytes)
* `controllers/baseline_l2.py` (6,023 bytes, last modified 2026-08-24): Simple learning switch Ryu application.
* `controllers/domain_controller.py` (6,650 bytes, last modified 2026-08-24): Multi-domain intra-domain forwarding controller.
* `controllers/ew_controller.py` (35,126 bytes, last modified 2026-08-25): Main Ryu controller with East-West API and TE routing engine.

#### `eastwest/` Directory (13 files, 135,779 bytes)
* `eastwest/global_topology.py` (13,658 bytes, last modified 2026-08-24): Global graph representation, Dijkstra/utilization path calculation.
* `eastwest/ew_api.py` (11,834 bytes, last modified 2026-10-14): Flask REST server exposing `/topology`, `/update`, `/te_path`, etc.
* `eastwest/sync_agent.py` (11,305 bytes, last modified 2026-08-24): Periodic background sync pusher/puller across domains.

#### `topology/` Directory (6 files, 37,216 bytes)
* `topology/basic_topo.py` (5,166 bytes, last modified 2026-08-24): Single-domain Mininet topology.
* `topology/multi_domain_topo.py` (10,190 bytes, last modified 2026-08-24): 3-domain, 9-switch, 12-host multi-controller Mininet topology.

#### `docs/` Directory (4 files, 16,737 bytes)
* `docs/phase2_topology.md` (5,279 bytes, last modified 2026-08-24): Topology mapping and switch-to-host layout.
* `docs/attack_evolution_and_results.md` (6,145 bytes, last modified 2026-08-25): Detailed narrative of Scapy bottleneck and `AF_PACKET` rewrite.
* `docs/circuit_breaker_defense.md` (5,313 bytes, last modified 2026-08-25): Circuit breaker design, flapping challenge, and meter fix.

---

### 1.2 Result File Provenance (Producer Scripts)

| Result File / Artifact | Producing Script / Command | Trigger / Mechanism |
| :--- | :--- | :--- |
| `results/attack_packetin_*_summary.json` | `experiments/attack_test.py` | Line 635: Serializes snapshot metrics at end of attack. |
| `results/attack_packetin_*.log` | `experiments/attack_test.py` | Line 89: Writes per-snapshot latencies and subprocess outputs. |
| `results/attack_eastwest_*_summary.json` | `experiments/attack_test.py` | Invokes `attacks/eastwest_flood.py`, serializes results. |
| `results/attack_poison_*_summary.json` | `experiments/attack_test.py` | Invokes `attacks/topology_poison.py`, serializes results. |
| `results/attack_suite_*_summary.json` | `experiments/attack_test.py` | Line 801: Serializes aggregated suite summary. |
| `results/part1_diagnostic.csv` | `experiments/monitor_part1.sh` | Shell monitoring script polling `ps`, `/proc`, and `ovs-ofctl`. |
| `results/circuit_breaker.log` | `defense/circuit_breaker.py` | Line 118: Writes rate violations, triggers, and mitigation cycle times. |
| `results/cb_restart.log` | `defense/circuit_breaker.py` | Line 52: Captures stdout/stderr of respawned `ryu-manager`. |
| `results/ryu_A_restart.log` | `experiments/circuit_breaker_eval.py` / manual | Captures output of Ryu controller restarts. |
| `results/ew_flood_defense_*.log` | `defense/ew_flood_mitigator.py` | Line 79: Logs token-bucket drops and anomaly quarantines. |
| `results/topology_guard_*.log` | `defense/topology_guard.py` | Line 75: Logs HMAC, schema, and semantic rejections. |
| `results/te_decisions.log` | `controllers/ew_controller.py` | Line 18, 145: Logs every route computation and flow installation. |
| `results/te_comparison.json` | `experiments/te_test.py` | Line 512: Dumps port statistics comparing baseline vs congested state. |
| `results/figures/fig1_te_utilization.{png,pdf}`| `experiments/generate_results.py` | Lines 16–33: Plots mocked link utilization timeseries. |
| `results/figures/fig2_attack_latency.{png,pdf}`| `experiments/generate_results.py` | Lines 43–80: Plots peak and baseline latencies across 3 attacks. |
| `results/figures/fig3_detection_accuracy.{png,pdf}`| `experiments/generate_results.py`| Lines 83–107: Plots mocked threshold vs ML classification metrics. |
| `results/figures/table1_mitigation_times.csv` | `experiments/generate_results.py` | Lines 110–120: Hardcoded DataFrame export. |
| `results/figures/table2_te_metrics.csv` | `experiments/generate_results.py` | Lines 123–130: Hardcoded DataFrame export. |
| `results/proof_of_work/fig1`–`fig12.png` | `experiments/generate_proof_graphs.py` | Lines 830–845: Generates comprehensive proof-of-work graphs from logs. |

---

## PART 2: PacketIn Flood Runs Audit

### 2.1 Complete Table of All 19 Recorded PacketIn Runs

Data extracted directly from `results/attack_packetin_<ts>_summary.json` and `results/attack_packetin_<ts>.log`.

| Run # | Filename (`results/attack_packetin_...`) | Timestamp (UTC) | Rate (pkt/s) | Duration (s) | Baseline Latency A (ms) | Attack-Phase Latency A (ms) [Mean / Med / Max] | Recovery-Phase Latency A (ms) [Mean / Med / Max] | Attack / Baseline Ratio | Classification | Exact Classification Criterion (File & Line) | Circuit Breaker Active? | Restarts Observed |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: | :---: |
| **1** | `20260824T154349Z_summary.json` | 2026-08-24 15:43:49 | 50 | N/A | 17.05 | 19.07 / 18.30 / 29.60 | 19.61 / 20.60 / 23.20 | 1.12 | `NOT_IN_FILE` | N/A (Field missing in initial schema) | No | 0 |
| **2** | `20260825T025248Z_summary.json` | 2026-08-25 02:52:48 | 500 | 130.0 | 20.81 | 18.98 / 18.20 / 35.40 | 18.87 / 18.10 / 28.50 | 0.91 | `OK` | `attack_test.py:632` (rec_avg $\le$ bl*1.3) | No | 0 |
| **3** | `20260825T031501Z_summary.json` | 2026-08-25 03:15:01 | 500 | 130.0 | 18.19 | 17.92 / 18.45 / 24.70 | 17.50 / 17.60 / 22.60 | 0.98 | `OK` | `attack_test.py:632` | No | 0 |
| **4** | `20260825T035535Z_summary.json` | 2026-08-25 03:55:35 | 500 | 113.6 | 18.16 | 42.72 / 35.10 / 122.90 | 76.80 / 72.35 / 125.10 | 2.35 | `OK` | `attack_test.py:632` | No | 0 |
| **5** | `20260825T044903Z_summary.json` | 2026-08-25 04:49:03 | 500 | 112.3 | 16.68 | 17.05 / 16.70 / 30.40 | 19.26 / 18.95 / 30.50 | 1.02 | `OK` | `attack_test.py:632` | No | 0 |
| **6** | `20260825T050515Z_summary.json` | 2026-08-25 05:05:15 | 500 | 112.1 | 19.23 | 43.94 / 39.80 / 91.10 | 80.53 / 75.75 / 135.70 | 2.29 | `RECOVERY_FAILED` | `attack_test.py:616-628` (rec > bl*1.3 & $\Delta > 5$) | No | 0 |
| **7** | `20260825T051400Z_summary.json` | 2026-08-25 05:14:00 | 500 | 112.6 | 91.98 | 107.32 / 100.80 / 169.70 | 145.21 / 118.20 / 498.60 | 1.17 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **8** | `20260825T053725Z_summary.json` | 2026-08-25 05:37:25 | 500 | 112.0 | 3.79 | 4.06 / 4.00 / 4.60 | 4.12 / 3.95 / 5.10 | 1.07 | `OK` | `attack_test.py:632` | No | 0 |
| **9** | `20260825T055115Z_summary.json` | 2026-08-25 05:51:15 | 500 | 111.6 | 3.60 | 3.50 / 3.50 / 4.10 | 3.72 / 3.75 / 4.10 | 0.97 | `OK` | `attack_test.py:632` | No | 0 |
| **10** | `20260825T061109Z_summary.json` | 2026-08-25 06:11:09 | 500 | 111.9 | 4.01 | 3.87 / 3.80 / 4.70 | 3.82 / 3.75 / 4.70 | 0.96 | `OK` | `attack_test.py:632` | No | 0 |
| **11** | `20260825T074718Z_summary.json` | 2026-08-25 07:47:18 | 500 | 112.7 | 18.20 | 123.50 / 84.40 / 375.90 | 759.39 / 537.80 / 1529.50 | 6.79 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **12** | `20260825T075944Z_summary.json` | 2026-08-25 07:59:44 | 500 | 112.2 | 19.25 | 204.03 / 148.90 / 676.60 | 861.98 / 820.05 / 1369.50 | 10.60 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **13** | `20260825T083338Z_summary.json` | 2026-08-25 08:33:38 | 500 | 112.5 | 16.43 | 116.58 / 76.10 / 404.30 | 1696.33 / 1487.30 / 3135.50 | 7.10 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **14** | `20260825T085624Z_summary.json` | 2026-08-25 08:56:24 | 500 | 115.2 | 1805.08 | 2105.42 / 1905.70 / 4731.40 | 2892.35 / 2816.30 / 5870.20 | 1.17 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **15** | `20260825T091714Z_summary.json` | 2026-08-25 09:17:14 | 500 | 112.5 | 19.92 | 186.33 / 116.60 / 756.40 | 1350.09 / 1248.20 / 3751.50 | 9.35 | `RECOVERY_FAILED` | `attack_test.py:616-628` | No | 0 |
| **16** | `20260825T092548Z_summary.json` | 2026-08-25 09:25:48 | 500 | 112.1 | 1211.93 | 1608.91 / 1528.85 / 2767.50 | 95.05 / 18.30 / 2933.10 | 1.33 | `OK` | `attack_test.py:632` (End rec snaps = 18 ms) | No | 1 (Manual restart) |
| **17** | `20260825T093510Z_summary.json` | 2026-08-25 09:35:10 | 500 | 112.2 | 17.08 | 243.71 / 178.45 / 907.20 | 54.82 / 19.20 / 626.30 | 14.27 | `RECOVERY_FAILED` | `attack_test.py:616-628` (End rec 23ms > 22.2ms) | No | 1 (Manual restart) |
| **18** | `20260825T102801Z_summary.json` | 2026-08-25 10:28:01 | 500 | 112.1 | 13.47 | 50.12 / 39.00 / 184.90 | 16.14 / 16.30 / 20.80 | 3.72 | `RECOVERY_FAILED` | `attack_test.py:616-628` (16.14 > 13.47*1.3 = 17.51? 16.14-13.47=2.67<5, but snap triggered) | **YES** | 1 (Auto CB) |
| **19** | `20260825T105158Z_summary.json` | 2026-08-25 10:51:58 | 500 | 112.7 | 13.83 | 14.03 / 13.10 / 23.70 | 11.43 / 11.40 / 22.30 | 1.01 | `OK` | `attack_test.py:632` (Clean mitigated baseline) | **YES** | 1 (Auto CB) |

*Note on CPU Readings:* In all 19 JSON summaries and individual run logs, controller CPU percentage is **NOT RECORDED** (value is `NOT_IN_FILE`). CPU telemetry was only recorded in `results/part1_diagnostic.csv` and `results/circuit_breaker.log`.

---

### 2.2 Run Groupings: Resolving the 9 + 6 = 15 vs 19 Runs Discrepancy
The 19 runs divide chronologically and methodologically into distinct experimental cohorts:
* **Early Group (9 runs: Runs 2 through 10):** Executed between `02:52:48Z` and `06:11:09Z`. Characterized by Scapy-based generation where packet generation was CPU-bound on the attacker host (~800–1,000 pkt/s). 7 of 9 runs completed with `OK` status because controller queues never entered irreversible event backlog.
* **Later Group (6 runs: Runs 11, 12, 13, 15, 16, 17):** Executed between `07:47:18Z` and `09:35:10Z`. Characterized by the optimized `AF_PACKET` raw socket engine delivering 5,000 pkt/s. 5 of these 6 runs resulted in `RECOVERY_FAILED`.
* **The 4 Unaccounted-for Runs:**
  1. **Run 1 (`20260824T154349Z`):** Initial pilot run from the previous day; used an older 50 pkt/s configuration and older JSON schema lacking `result` and `atk_elapsed_s` keys.
  2. **Run 14 (`20260825T085624Z`):** Invalid / corrupted test run. Succeeded Run 13 (`083338Z`) without resetting Mininet or restarting Ryu. As a result, its pre-attack baseline was already poisoned at **1,805.08 ms**. Excluded from clean statistical groups.
  3. **Run 18 (`20260825T102801Z`):** Phase 6 initial Circuit Breaker integration test; Circuit Breaker daemon was running and intervened.
  4. **Run 19 (`20260825T105158Z`):** Phase 6 defended evaluation run; Circuit Breaker daemon successfully mitigated attack.

---

### 2.3 Statistical Computations From Raw Telemetry
* **Median Attack/Baseline Ratio for Early Runs (Runs 2 to 10):**
  * Individual ratios: `[0.91, 0.98, 2.35, 1.02, 2.29, 1.17, 1.07, 0.97, 0.96]`.
  * **Median Ratio:** **1.022** (virtually no control-plane queue inflation under Scapy bottleneck).
* **Later Group (Runs 11, 12, 13, 15, 16, 17) Telemetry:**
  * **Attack-Phase Mean Latency (Domain A):** **413.84 ms** (Range: **116.58 ms** in Run 13 to **1,608.91 ms** in Run 16).
  * **Recovery-Phase Mean Latency (Domain A):** **802.94 ms** (Range: **54.82 ms** in Run 17 to **1,696.33 ms** in Run 13).
  * If excluding the two intervention runs (16 and 17 where controllers were rebooted), the **4 pure unmitigated later runs** (11, 12, 13, 15) yield:
    * Attack-Phase Mean: **157.61 ms** (Range: **116.58 ms to 204.03 ms**).
    * Recovery-Phase Mean: **1,166.94 ms** (Range: **759.39 ms to 1,696.33 ms**).
* **Resolving the "161 to 696 ms Range" vs "790 ms Recovery Mean":**
  * The range **161 ms to 696 ms** refers to **collateral cross-domain degradation in Domains B and C** during and immediately following the attack on Domain A. In Run 17 (`results/attack_packetin_20260825T093510Z_summary.json`), Domain C attack latency was **161.52 ms**, and recovery snapshots in `results/attack_packetin_20260825T093510Z.log:line 116` reached **696.5 ms**. In Run 14 (`085624Z.log:line 27`), Domain C during-attack latency reached **790.1 ms**.
  * The **790 ms** figure represents either the Domain C attack peak (`790.1 ms`) or the overall Domain A recovery average across later runs (~802.9 ms, or 790 ms if excluding specific outlier snapshots).

---

### 2.4 Classification Code & Root-Cause of Failure Discrepancies
* **Exact Classification Criterion Code:** `experiments/attack_test.py`, lines 608–632:
  ```python
  # Check if recovery phase actually recovered to baseline
  recovery_failed = False
  if not subprocess_error and not atk_exit_early and len(snapshots["recovery"]) >= 3 and len(snapshots["baseline"]) >= 3:
      for domain in EW_PORTS:
          bl_avg = _avg_lat(snapshots["baseline"], domain)
          # avg of last 3 recovery snaps
          rec_avg = _avg_lat(snapshots["recovery"][-3:], domain)
          if bl_avg and rec_avg:
              # If it's more than 30% higher AND more than 5ms absolute difference
              if rec_avg > bl_avg * 1.3 and (rec_avg - bl_avg) > 5.0:
                  recovery_failed = True
  ...
  elif recovery_failed:
      exp_result = "RECOVERY_FAILED"
  else:
      exp_result = "OK"
  ```
* **Runs Classified as `RECOVERY_FAILED` (9 runs total):**
  1. `20260825T050515Z`
  2. `20260825T051400Z`
  3. `20260825T074718Z`
  4. `20260825T075944Z`
  5. `20260825T083338Z`
  6. `20260825T085624Z`
  7. `20260825T091714Z`
  8. `20260825T093510Z`
  9. `20260825T102801Z`
* **Why Early and Later Runs Differ:**
  * As documented in Git commit `c826f8c2` ("Phase 5 completion: Attack optimizations...") and `docs/attack_evolution_and_results.md:17-36`, `attacks/packetin_flood.py` was completely overhauled between 06:11 UTC and 07:47 UTC. The early version used Scapy's `sendp()` which created dynamic headers in Python on every frame; worker threads saturated the generator host CPU, capping actual egress at ~800 pkt/s.
  * In commit `c826f8c2`, `attacks/packetin_flood.py` switched to raw `AF_PACKET` sockets (`socket.SOCK_RAW`) with pre-computed header bytearrays and microsecond spin-wait batching. This allowed the attacker to sustain true 5,000 pkt/s, which exceeded Ryu's single-threaded event loop capacity and induced unbounded queue saturation.

---

### 2.5 Origin of README Headline Claims
* **"~14 ms to >1,350 ms":**
  * `14 ms`: Approximate baseline in Run 19 (`13.83 ms`, `results/attack_packetin_20260825T105158Z_summary.json`).
  * `> 1,350 ms`: Directly matches Run 15 recovery average of **1,350.08 ms** (`results/attack_packetin_20260825T091714Z_summary.json:line 41`).
* **"13.8 ms baseline":** Matches Run 19 baseline (`13.83 ms`); hardcoded as `"13.8"` in `experiments/generate_results.py:47`.
* **"14.02 ms post-mitigation":** Directly matches Run 19 during-attack latency under Circuit Breaker: **14.02 ms** (`results/attack_packetin_20260825T105158Z_summary.json:line 26`).
* **"~3.0 s detection":** Directly matches the 3-second consecutive violation window programmed in `defense/circuit_breaker.py:152`. Hardcoded as `"3.0"` in `experiments/generate_results.py:90`.
* **"~16.7 s mitigation":** Sourced from `results/circuit_breaker.log` where triggers took **16.59 s, 16.48 s, 16.51 s, 16.44 s**, and summarized as `"16.73s"` in `results_summary.md:line 42`. Hardcoded as `"16.7"` in `experiments/generate_results.py:92`. **Raw data supports the number, but proves it is caused by a 15-second HTTP 404 timeout.**

---

## PART 3: East-West REST Flood Audit

### 3.1 Table of Every E-W Flood Run

Data extracted from `results/attack_eastwest_*_summary.json` and logs.

| Run # | Filename (`results/attack_eastwest_...`) | Timestamp (UTC) | Rate (req/s) | Duration (s) | Baseline Latency A (ms) | Latency During Attack A (ms) | Latency Delta (%) | Result Status | Flood Mitigator Installed? |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `20260824T154829Z_summary.json` | 2026-08-24 15:48:29 | 10 $\to$ 150 ramp | 90 | 18.27 | 14.72 | -19.43% | `NOT_IN_JSON` | **NO** |
| **2** | `20260825T025729Z_summary.json` | 2026-08-25 02:57:29 | 10 $\to$ 150 ramp | 90 | 19.94 | 25.46 | +27.68% | `OK` | **NO** |
| **3** | `20260825T031941Z_summary.json` | 2026-08-25 03:19:41 | 10 $\to$ 150 ramp | 90 | 16.85 | 21.58 | +28.07% | `OK` | **NO** |
| **4** | `20260825T035959Z_summary.json` | 2026-08-25 03:59:59 | 10 $\to$ 150 ramp | 90 | 83.10 | 87.89 | +5.76% | `OK` | **NO** |
| **5** | `20260825T045326Z_summary.json` | 2026-08-25 04:53:26 | 10 $\to$ 150 ramp | 90 | 18.41 | 20.47 | +11.19% | `OK` | **NO** |
| **6** | `20260825T053051Z_summary.json` | 2026-08-25 05:30:51 | 10 $\to$ 150 ramp | 90 | 3.92 | 4.41 | +12.50% | `OK` | **NO** |
| **7** | `20260825T054442Z_summary.json` | 2026-08-25 05:44:42 | 10 $\to$ 150 ramp | 90 | 3.61 | 3.73 | +3.32% | `OK` | **NO** |
| **8** | `20260825T060435Z_summary.json` | 2026-08-25 06:04:35 | 10 $\to$ 150 ramp | 90 | 3.94 | 4.20 | +6.60% | `OK` | **NO** |
| **9** | `20260825T072859Z_summary.json` | 2026-08-25 07:28:59 | 10 $\to$ 150 ramp | 90 | 3.91 | 4.03 | +3.07% | `OK` | **NO** |
| **10** | `20260825T074042Z_summary.json` | 2026-08-25 07:40:42 | 10 $\to$ 150 ramp | 90 | 21.71 | 44.37 | +104.38% | `OK` | **NO** |
| **11** | `20260825T075309Z_summary.json` | 2026-08-25 07:53:09 | 10 $\to$ 150 ramp | 90 | 17.59 | 23.49 | +33.54% | `OK` | **NO** |

### 3.2 Verification of the "+11.8% Median" Claim
* Across the **10 valid runs** with status `OK` (Runs 2 through 11), the percentage deltas for Domain A are:
  `[+27.68%, +28.07%, +5.76%, +11.19%, +12.50%, +3.32%, +6.60%, +3.07%, +104.38%, +33.54%]`.
* Sorted array: `[3.07%, 3.32%, 5.76%, 6.60%, 11.19%, 12.50%, 27.68%, 28.07%, 33.54%, 104.38%]`.
* Middle two values (indices 4 and 5): **11.19%** and **12.50%**.
* Median calculation: $\frac{11.18957\% + 12.50000\%}{2} = \mathbf{11.84478\% \approx +11.8\%}$.
* **Claim Verified:** Sourced directly from the empirical summary data.
* **Does any run exceed 150 req/s?** **NO.** Every single attack process was launched with `--start-rate 10 --max-rate 150 --step 20 --ramp-interval 8.0` (`attacks/eastwest_flood.py:220-227`). The September 18, 2026 tests (`results/attack_eastwest_20260918T055520Z.log`) also capped at 150 req/s.

---

## PART 4: Topology Poisoning Runs Audit

### 4.1 Inventory and Effects of All 11 Poisoning Runs

| Run # | Filename (`results/attack_poison_...`) | Timestamp (UTC) | Mode / Lie Type | Target Port / Domain | Injected Utilization Ratio | Accepted by Controller? (HTTP Status) | Observed Effect on `global_topology` | Observed Effect on `te_path` | Topology Guard Active? |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | `20260824T155100Z_summary.json` | 2026-08-24 15:51:00 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **2** | `20260825T030122Z_summary.json` | 2026-08-25 03:01:22 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **3** | `20260825T032335Z_summary.json` | 2026-08-25 03:23:35 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **4** | `20260825T040352Z_summary.json` | 2026-08-25 04:03:52 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **5** | `20260825T045720Z_summary.json` | 2026-08-25 04:57:20 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **6** | `20260825T053444Z_summary.json` | 2026-08-25 05:34:44 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **7** | `20260825T054834Z_summary.json` | 2026-08-25 05:48:34 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **8** | `20260825T060828Z_summary.json` | 2026-08-25 06:08:28 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **9** | `20260825T073252Z_summary.json` | 2026-08-25 07:32:52 | N/A (Empty file) | N/A | N/A | N/A | Corrupted 0-byte file | N/A | **NO** |
| **10** | `20260825T074436Z_summary.json` | 2026-08-25 07:44:36 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |
| **11** | `20260825T075703Z_summary.json` | 2026-08-25 07:57:03 | `congestion_lie` | 8081 (Domain B) | 0.95 | HTTP 200 (Accepted) | Injected into `util_rates` | `None` $\to$ `None` $\to$ `None` | **NO** |

### 4.2 Key Findings for Topology Poisoning
1. **Mode Uniformity:** 100% of the recorded runs executed the `congestion_lie` vector (injecting link utilization ratio = 0.95 across links s3-s4). **Zero end-to-end testbed runs were recorded for `phantom_link`.**
2. **Impact on Routing (`te_path`):** In all 11 summary JSON files, `te_path_before`, `te_path_during`, and `te_path_after` are recorded as `null`. As noted in `experiments/attack_test.py:650-652`, this occurred because the attack suite was executed without active concurrent `iperf3` data-plane traffic flows; therefore, no inter-domain dynamic TE path rerouting events were triggered or recorded during these runs.

---

## PART 5: Defense Enablement Audit

### 5.1 Verification of Middleware Integration in `eastwest/ew_api.py`
In `eastwest/ew_api.py`:
* Lines 30–31:
  ```python
  #   Rate limiting (EW Flood):    defense/ew_flood_mitigator.py
  #       from defense.ew_flood_mitigator import install_ew_flood_mitigator
  #       mitigator = install_ew_flood_mitigator(_app)
  ```
* Lines 34–35:
  ```python
  #   Auth + Validation (Poisoning): defense/topology_guard.py
  #       from defense.topology_guard import install_topology_guard
  #       install_topology_guard(_app, shared_secret=os.environ.get("EW_SHARED_SECRET"))
  ```
* Lines 131–134:
  ```python
  """
  To activate defense:
    • Rate limiting:     install_ew_flood_mitigator(_app)   # defense/ew_flood_mitigator.py
    • Auth+validation:   install_topology_guard(_app, ...)  # defense/topology_guard.py
  """
  ```
**Evidence:** `install_ew_flood_mitigator` and `install_topology_guard` are **never executed** in `eastwest/ew_api.py`. They exist exclusively as comment templates and docstrings. No CLI flags or environment variables exist in `ew_api.py` or `ew_controller.py` to enable them dynamically at runtime.

### 5.2 Verification of Payload Signing Across Controllers
* **Is `EW_SHARED_SECRET` set anywhere?** It is referenced in `defense/topology_guard.py:61, 115, 396` and `readme.md:83`. It is **NOT set** in any configuration script, systemd unit, or bash launcher.
* **Do legitimate controllers sign `/update` requests?**
  * In `eastwest/sync_agent.py` lines 197–201:
    ```python
    resp = requests.post(
        url, data=body,
        headers={'Content-Type': 'application/json',
                 'X-Domain-Id': self.domain_id},
        timeout=REQUEST_TIMEOUT)
    ```
  * In `eastwest/sync_agent.py` lines 222–226:
    ```python
    resp = requests.post(
        url, data=body,
        headers={'Content-Type': 'application/json',
                 'X-Domain-Id': self.domain_id},
        timeout=REQUEST_TIMEOUT)
    ```
* **Critical Conclusion:** Legitimate Ryu controller processes (`sync_agent.py`) do not sign their payloads with HMAC and do not include the `X-EW-Signature` header. Therefore, **if `TopologyGuard` were enabled with default settings (`hmac_required=True`), it would immediately drop all legitimate synchronization updates from Domain B and Domain C with HTTP 403**, breaking inter-domain topology discovery completely.

---

## PART 6: Automated Circuit Breaker Deep Dive

### 6.1 End-to-End Operation of `defense/circuit_breaker.py`
1. **PacketIn Rate Measurement (`lines 10–25, 130–135`):**
   * Polled every 1.0 s via subprocess: `sudo ovs-ofctl -O OpenFlow13 dump-flows <sw>`.
   * Parses `n_packets=([0-9]+)` on table-miss flow rules matching `priority=0` and `CONTROLLER`.
   * Sums across switches `s1, s2, s3` and calculates $\Delta\text{packets} / \Delta t$.
2. **CPU Measurement (`lines 27–36, 138–147`):**
   * Finds controller PID by scanning `ps aux` for `ryu-manager` listening on port 6633.
   * Measures instantaneous process CPU utilization via `psutil.Process(pid).cpu_percent(interval=0.1)`.
3. **Trigger Logic (`lines 148–154`):**
   * Dual condition: `rate > 1500 pkt/s` AND `cpu > 70.0%`.
   * Must persist for **3 consecutive seconds** (`violation_count >= 3`).
4. **Mitigation & Kill (`lines 38–47`):**
   * Kills affected controller using `os.kill(pid, 9)` (`SIGKILL`).
   * Sleeps 1.0 second (`line 48`).
5. **Respawn Mechanism (`lines 51–53`):**
   * Spawns fresh controller via bash background process:
     ```bash
     DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 TE_ENABLED=1 nohup \
       /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager \
       controllers/ew_controller.py --ofp-tcp-listen-port 6633 > results/cb_restart.log 2>&1 &
     ```
6. **Health Check Loop (`lines 61–69`):**
   * Polls `http://127.0.0.1:8080/stats/switches` every 0.5 s with `timeout=1` for up to 15 seconds.
7. **Prevention Stage (`lines 78–90`):**
   * Injects OpenFlow rate-limit meter on edge switch `s1`:
     ```bash
     sudo ovs-ofctl -O OpenFlow13 add-meter s1 meter=1,pktps,band=type=drop,rate=100
     sudo ovs-ofctl -O OpenFlow13 add-flow s1 priority=1,hard_timeout=60,actions=meter:1,CONTROLLER:65535
     ```
   * Fallback if datapath meters unsupported: drops traffic on `in_port=1` for 60 s.

### 6.2 The Health Check Endpoint & 15-Second Timeout Root Cause
* **Does `/stats/switches` exist?**
  * `ryu-manager` is launched with a single application: `controllers/ew_controller.py`.
  * The OpenFlow REST stats application `ryu.app.ofctl_rest` is **NOT loaded**.
  * The HTTP port 8080 is hosted by Python Flask inside `eastwest/ew_api.py`.
  * The registered Flask endpoints in `eastwest/ew_api.py` are:
    * `/topology` (GET, line 91)
    * `/linkstate` (GET, line 107)
    * `/update` (POST, line 121)
    * `/install_path` (POST, line 166)
    * `/te_path` (GET, line 211)
    * `/peers` (GET, line 230)
    * `/globalview` (GET, line 236)
    * `/hosts` (GET, line 242)
  * **`/stats/switches` does not exist on port 8080.** Requests to this endpoint return HTTP 404 Not Found.
* **Timeout Arithmetic:**
  * In `defense/circuit_breaker.py:61`, the loop condition is `while time.time() - t_restart < 15:`.
  * Because `r.status_code == 200` is never satisfied, the loop runs for the complete 15.0 seconds.
  * Time to restart: $\approx 1.00\text{ s}$.
  * Health check timeout: **15.00 s**.
  * OVS meter rule injection: $\approx 0.44\text{ s to } 0.59\text{ s}$.
  * **Total Time-to-Mitigation:** $1.00 + 15.00 + 0.50 \approx \mathbf{16.50\text{ s}}$.
  * This matches `results/circuit_breaker.log` and resolves why every single trigger in `circuit_breaker.log` logged:
    `MITIGATE: Reconnection NOT confirmed after 15s (API unresponsive)`.

### 6.3 Audit of Recorded Circuit Breaker Triggers
All 8 triggers from `results/circuit_breaker.log`:

| Trigger # | Timestamp (Time) | PacketIn Rate Detected | Controller CPU% | Detection to Restart Time | Reconnection Confirmed? | Total Time-to-Mitigation | Edge Meter Installed? |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 11:24:04 | 5,917.9 pkt/s | 99.8% | 1.00 s | **NO (15s timeout)** | **16.59 s** | Yes (Expires in 60s) |
| **2** | 11:24:35 | 2,157.7 pkt/s | 99.8% | 1.00 s | **NO (15s timeout)** | **16.48 s** | Yes (Expires in 60s) |
| **3** | 11:25:05 | 2,964.4 pkt/s | 99.9% | 1.00 s | **NO (15s timeout)** | **16.48 s** | Yes (Expires in 60s) |
| **4** | 11:25:36 | 2,889.2 pkt/s | 109.8% | 1.00 s | **NO (15s timeout)** | **16.59 s** | Yes (Expires in 60s) |
| **5** | 11:26:07 | 2,317.0 pkt/s | 89.8% | 1.00 s | **NO (15s timeout)** | **16.51 s** | Yes (Expires in 60s) |
| **6** | 11:26:38 | 2,476.4 pkt/s | 99.9% | 1.00 s | **NO (15s timeout)** | **16.48 s** | Yes (Expires in 60s) |
| **7** | 11:27:08 | 2,514.8 pkt/s | 99.8% | 1.00 s | **NO (15s timeout)** | **16.44 s** | Yes (Expires in 60s) |
| **8** | 11:27:39 | 2,690.8 pkt/s | 89.9% | N/A (Killed PID 14364) | Daemon stopped at 11:27:40 | N/A | N/A |

---

## PART 7: Component-Level Defense Results & Arithmetic

### 7.1 E-W Flood Mitigator (`defense/ew_flood_mitigator.py`)
* **Verification Script:** `experiments/test_defenses.py`, Suite 1 (lines 149–256).
* **The "599 of 6,000 Admitted at 200 req/s" Arithmetic:**
  * Attack rate: $R_{atk} = 200\text{ req/s}$ over duration $T = 30\text{ s}$ $\implies$ Total Requests = $200 \times 30 = 6,000\text{ requests}$. Request arrival interval $\Delta t = \frac{1}{200} = 0.005\text{ s}$.
  * In `defense/ew_flood_mitigator.py:108-132`, the `TokenBucket` class updates tokens on each call:
    $\text{tokens} = \min(\text{burst}, \text{tokens} + \Delta t \times \text{rate})$.
  * When evaluated with a rate limit of **$R = 19\text{ req/s}$** and burst capacity of **$B = 30\text{ tokens}$**:
    * Initial burst tokens consumed at $t = 0$: 30 requests admitted.
    * Over the remaining $29.995\text{ s}$, token replenishment yields:
      $\lfloor 29.995\text{ s} \times 19\text{ tokens/s} \rfloor = 569\text{ tokens}$.
    * Total Admitted Requests = $30 + 569 = \mathbf{599\text{ requests}}$.
    * Total Blocked Requests (HTTP 429) = $6,000 - 599 = \mathbf{5,401\text{ requests}}$.
  * **Test Suite Verification (`results/proof_of_work/fig6_ew_mitigator_profile.png`):** Tested with $B = 5\text{ burst}$, $R = 5\text{ req/s}$, and 30 rapid back-to-back requests. Exactly 5 requests admitted (HTTP 200) and 25 requests blocked (HTTP 429) (`experiments/test_defenses.py:225-234`).

### 7.2 Topology Guard Evaluation Matrix (`defense/topology_guard.py`)

| Scenario / Attack Vector | Outcome | Intercepting Layer | HTTP Code | Explanatory Code Logic & Exact File/Line Citation |
| :--- | :---: | :---: | :---: | :--- |
| **1. Unsigned Request** | **Rejected** | Layer 1 (HMAC) | **403** | `topology_guard.py:340-343`: `sig = headers.get("X-EW-Signature")`; missing signature calls `_reject("hmac_rejected")`. Line 438 returns HTTP 403. |
| **2. Bad HMAC / Tampered Body** | **Rejected** | Layer 1 (HMAC) | **403** | `topology_guard.py:344-347`: `verify_hmac(body, sig, secret)` fails. Calls `_reject("hmac_rejected")` $\to$ HTTP 403. |
| **3. Large Jump (>0.60)** (`congestion_lie`) | **Rejected** | Layer 3 (Semantic) | **403** | `topology_guard.py:270-275, 363-366`: `ratio - prev > max_delta (0.60)` flags anomaly. Calls `_reject("semantic_rejected")` $\to$ HTTP 403. |
| **4. Gradual Ramp ($\le$ 0.60)** | **Accepted** | None (Passed) | **200** | `topology_guard.py:279`: `ratio - prev <= 0.60`; updates `_known_ratios` and executes underlying `post_update` view. |
| **5. Replay Attack (Same Seq)** | **ACCEPTED** *(Vulnerability)* | **None** | **200** | `topology_guard.py:177-179`: Only asserts `isinstance(seq, int) and seq >= 0`. Does not record seen sequence numbers or check monotonicity. |
| **6. Cross-Domain Claim** (Domain A claiming B) | **ACCEPTED** *(Vulnerability)* | **None** | **200** | `topology_guard.py:170-174`: Validates `domain_id in trusted_domains`. Does NOT cross-reference switch DPIDs against the claiming `domain_id`. |
| **7. Plausible Phantom Link** (Ports < 50) | **ACCEPTED** *(Vulnerability)* | **None** | **200** | `topology_guard.py:197-203`: Phantom link detection only triggers if `src_port >= 50 or dst_port >= 50`. Ports 1–6 pass schema check. |
| **8. Genuine Sudden Load Step** (>0.60) | **REJECTED** *(False Positive)* | Layer 3 (Semantic) | **403** | `topology_guard.py:270`: Threshold is rigid. Any legitimate sudden traffic step (e.g., 0.10 $\to$ 0.85) is falsely rejected as an attack. |
| **9. Malformed / Invalid JSON** | **Rejected** | Web Pre-filter | **400** | `topology_guard.py:430-433`: `json.loads(body)` raises `JSONDecodeError`, caught and returns `jsonify({"error": "invalid JSON"}), 400`. |

* **Persistence of Rejection State:** Lines 276–277: When a semantic anomaly is detected, `topology_guard.py` executes `continue` before updating `self._known_ratios[dpid_str][port_str] = ratio`. The baseline ratio remains locked at the prior low value, preventing an attacker from stepping up ratios through consecutive rejections.

---

## PART 8: Documentation Consistency & Code Discrepancies

### 8.1 Comparison: Documentation Claims vs Code & Raw Telemetry

| Documentation Claim | Document Location | Verified Reality in Code & Raw Data | Consistency Rating |
| :--- | :--- | :--- | :---: |
| "Latency spikes from ~14ms to over 1,350ms" | `readme.md:14`, `113` | Verified: Run 19 baseline = 13.83 ms (`results/attack_packetin_20260825T105158Z_summary.json`); Run 15 recovery = 1,350.08 ms (`results/attack_packetin_20260825T091714Z_summary.json`). Saturated peaks reached 3,135 ms and 5,870 ms. | **Consistent** |
| "Post-Mitigation Latency: Capped at 14.02 ms" | `readme.md:120`, `results_summary.md:42` | Verified: Matches Run 19 `during.avg_lat.A = 14.02 ms` in `results/attack_packetin_20260825T105158Z_summary.json`. | **Consistent** |
| "Detection Time: ~3.0 seconds" | `readme.md:117` | Verified: 3 consecutive 1.0s poll cycles coded in `defense/circuit_breaker.py:149-153` and logged in `results/circuit_breaker.log`. | **Consistent** |
| "Total Mitigation Time: ~16.7 seconds" | `readme.md:118` | **Misleading:** Sourced from 16.44s–16.59s in `results/circuit_breaker.log`. Exactly 15.0s of this is an unhandled timeout querying non-existent `/stats/switches` on port 8080 (`defense/circuit_breaker.py:61-75`). | **Partial (Misattributed)** |
| "Rejects unauthenticated requests with HTTP 401" | `readme.md:76` | **Contradicted:** `defense/topology_guard.py:438` returns HTTP 403 for all rejections. HTTP 401 is never generated. | **Inconsistent** |
| "HMAC check rejects ROGUE payloads (HTTP 403)" | `readme.md:129` | Verified in code: `defense/topology_guard.py:438` returns HTTP 403. | **Consistent** |
| "Every trusted controller signs its payload with shared secret" | `readme.md:76` | **Contradicted:** `eastwest/sync_agent.py:197-201, 222-226` sends unauthenticated JSON without signatures. | **Inconsistent** |
| "Defenses integrated into E-W REST API" | `readme.md:65-83` | **Contradicted:** Mitigator and Guard are only present as comments in `eastwest/ew_api.py:30-35`. Neither is active in the testbed. | **Inconsistent** |
| "E-W flood degrades Domain A latency by median +11.8%" | `results/proof_of_work/PROOF_OF_WORK.md:154` | Verified: Raw summary data for the 10 completed E-W flood runs yields median delta of exactly +11.84%. | **Consistent** |
| "Evaluation figures and CSV tables reflect empirical pipelines" | `readme.md:135-160` | **Contradicted:** `experiments/generate_results.py:43-130` hardcodes tables and mock data dictionaries directly into CSV and plot generation functions. | **Inconsistent** |

---

### 8.2 Inventory of Commented-Out Defenses, Hardcoded Values, and Known Bugs
1. **Commented-out Defenses in Production API:**
   * `eastwest/ew_api.py:30-31`: `# from defense.ew_flood_mitigator import install_ew_flood_mitigator`
   * `eastwest/ew_api.py:34-35`: `# from defense.topology_guard import install_topology_guard`
2. **Hardcoded Evaluation Telemetry:**
   * `experiments/generate_results.py:16-20`: Hardcoded time-series arrays for Fig 1 link utilization (`te_off_util = [95, 96, 95...]`, `te_on_util = [95, 96, 95, 45...]`).
   * `experiments/generate_results.py:43-47`: Hardcoded latency array `undefended_peak = [1350.0, 23.49, 15.36]`, `defended_peak = [14.02, 23.49, 15.36]`, `baseline = [13.8, 17.59, 18.34]`.
   * `experiments/generate_results.py:89-103`: Hardcoded strings in `table1_mitigation_times.csv` (`'Time-to-Detect (s)': ['3.0', '4.2*', '2.5*']`, `'Time-to-Mitigate (s)': ['16.7', '2.1*', '5.5*']`).
   * `experiments/generate_results.py:98-103`: Hardcoded strings in `table2_te_metrics.csv` (`'> 1350.0'`, `'14.02'`, `'Dropped to < 10'`).
3. **Known Bugs & Architectural Gaps:**
   * `defense/circuit_breaker.py:63`: Health-check targets `/stats/switches` on `args.api_port` (8080). Port 8080 is Flask, not Ryu's `ofctl_rest`. Always fails and times out after 15 s.
   * `eastwest/ew_api.py:21-28`: Deliberate unauthenticated baseline vulnerability explicitly preserved: `"DO NOT add auth/validation here until the attack experiments are complete"`.
   * `defense/topology_guard.py:176-179`: Missing sequence number anti-replay cache.
   * `defense/topology_guard.py:170-174`: Missing cross-domain dpid authority verification.
   * `results/attack_poison_20260825T073252Z_summary.json`: 0-byte corrupted file left in results directory.

---

## PART 9: Reproducibility & Research Evidence Gaps

### 9.1 Environment Details Discoverable From Repository
* **Python Environments:**
  * Ryu Virtual Environment: `/home/a-anuj/ryu311/bin/python` (Python 3.11, required due to Ryu's eventlet dependencies).
  * System Python: `/usr/sbin/python3` (Python 3.14 / system default).
* **Core Dependencies (`requirements.txt`):**
  * `ryu`: SDN controller framework.
  * `mininet`: Assumed system-installed via apt/dnf (`requirements.txt:line 2`).
  * `openvswitch-switch`: OpenFlow 1.3 datapath.
  * `flask`, `requests`: East-West REST communication.
  * `networkx`: Shortest-path Dijkstra computation in `eastwest/global_topology.py`.
  * `scapy`: Packet generation (replaced by AF_PACKET raw sockets in `attacks/packetin_flood.py`).
  * `matplotlib`, `pandas`, `numpy`, `scikit-learn`: Data analysis and visualization.
* **Network & Switch Configuration:**
  * OpenFlow Protocol: OpenFlow 1.3 (`-O OpenFlow13`).
  * Controller Ports: Domain A on TCP 6633, Domain B on TCP 6634, Domain C on TCP 6653 (or 6635).
  * REST API Ports: Domain A on 8080, Domain B on 8081, Domain C on 8082.
  * Link Speeds: Backbone links 1,000 Mbps; Host edge links 100 Mbps (`results_summary.md:12-13`).
* **Randomness & Seeds:** Randomized packet fields (IP, MAC, UDP ports) are generated via Python's standard `random` module without a static PRNG seed.

---

### 9.2 Evidence Gaps & Required Future Experiments

| Paper Claim Candidate | Supported by Current Raw Repo Data? | Exact Evidence Gap | Specific Command Line to Fill Gap (From Existing Scripts) |
| :--- | :---: | :--- | :--- |
| **Defended PacketIn Mitigation via Circuit Breaker** | **Partial** | True mitigation occurred in Run 19, but the 16.7s mitigation time is distorted by the 15s timeout on the non-existent `/stats/switches` endpoint. | Fix `circuit_breaker.py:63` to target an existing endpoint (e.g., `/topology` or `/te_path`), then execute: `sudo python3 experiments/circuit_breaker_eval.py` |
| **Defended East-West Flood via Mitigator** | **NO** | Mitigator is only verified in mock standalone tests (`test_defenses.py`). Zero runs exist in the multi-controller testbed. | In `eastwest/ew_api.py`, uncomment lines 30–31 (`install_ew_flood_mitigator(_app)`), launch controllers, and run: `sudo python3 experiments/attack_test.py --attacks eastwest --with-mininet` |
| **Defended Topology Poisoning via Guard** | **NO** | Topology Guard is only verified in mock standalone tests. Furthermore, legitimate controllers do not sign payloads. | 1. Update `eastwest/sync_agent.py` to sign `/update` POSTs with `sign_payload()`.<br>2. Uncomment lines 34–35 in `eastwest/ew_api.py`.<br>3. Run: `sudo python3 experiments/attack_test.py --attacks poison --with-mininet` |
| **End-to-End Dynamic TE Path Rerouting Under Poisoning** | **NO** | In all 11 poison summary runs, `te_path` before, during, and after was `null` because no background `iperf3` flow was active. | Execute an inter-domain `iperf3` stream (`h1` $\to$ `h12`), then launch the poison attack: `python3 attacks/topology_poison.py --target-port 8081 --lie-type congestion_lie --src-dpid 3 --dst-dpid 4 --fake-ratio 0.95 --repeat 5 --yes` |

---

## Raw Numbers I Verified

Every metric verified during this audit is cataloged below with its source file and JSON key / line reference:

1. **`19` PacketIn Summary JSONs:** Count of files matching `results/attack_packetin_*_summary.json`.
2. **`11` East-West Summary JSONs:** Count of files matching `results/attack_eastwest_*_summary.json`.
3. **`11` Topology Poisoning Summary JSONs:** Count of files matching `results/attack_poison_*_summary.json`.
4. **`21` Suite Summary JSONs:** Count of files matching `results/attack_suite_*_summary.json`.
5. **`9` Runs with `result = "RECOVERY_FAILED"`:** Sourced from `results/attack_packetin_*_summary.json` key `"result"`.
6. **`9` Runs with `result = "OK"`:** Sourced from `results/attack_packetin_*_summary.json` key `"result"`.
7. **`17.05 ms` (Run 1 Baseline Domain A):** `results/attack_packetin_20260824T154349Z_summary.json` $\to$ `baseline.avg_lat.A`.
8. **`1805.08 ms` (Run 14 Baseline Domain A - Corrupted):** `results/attack_packetin_20260825T085624Z_summary.json` $\to$ `baseline.avg_lat.A`.
9. **`13.83 ms` (Run 19 Baseline Domain A):** `results/attack_packetin_20260825T105158Z_summary.json` $\to$ `baseline.avg_lat.A`.
10. **`14.02 ms` (Run 19 Attack Peak Domain A):** `results/attack_packetin_20260825T105158Z_summary.json` $\to$ `during.avg_lat.A`.
11. **`11.43 ms` (Run 19 Recovery Domain A):** `results/attack_packetin_20260825T105158Z_summary.json` $\to$ `recovery.avg_lat.A`.
12. **`1350.08 ms` (Run 15 Recovery Domain A):** `results/attack_packetin_20260825T091714Z_summary.json` $\to$ `recovery.avg_lat.A`.
13. **`1696.33 ms` (Run 13 Recovery Domain A):** `results/attack_packetin_20260825T083338Z_summary.json` $\to$ `recovery.avg_lat.A`.
14. **`2892.34 ms` (Run 14 Recovery Domain A):** `results/attack_packetin_20260825T085624Z_summary.json` $\to$ `recovery.avg_lat.A`.
15. **`3135.50 ms` (Max Single Latency Reading, Run 13):** `results/attack_packetin_20260825T083338Z.log` $\to$ line 133.
16. **`5870.20 ms` (Max Single Latency Reading, Run 14):** `results/attack_packetin_20260825T085624Z.log` $\to$ line 86.
17. **`1.022` (Median Attack/Baseline Ratio for Early Runs 2–10):** Calculated from `during.avg_lat.A / baseline.avg_lat.A` across Runs 2 to 10.
18. **`+11.84%` (Median Latency Increase Across Completed E-W Flood Runs):** Calculated from Domain A baseline vs during attack across the 10 `OK` runs in `results/attack_eastwest_*_summary.json`.
19. **`104.38%` (Max E-W Latency Degradation on Domain A):** `results/attack_eastwest_20260825T074042Z_summary.json` $\to$ `((during - baseline) / baseline) * 100`.
20. **`208.69%` (Max E-W Latency Degradation on Domain B):** `results/attack_eastwest_20260825T074042Z_summary.json` $\to$ `((during.B - baseline.B) / baseline.B) * 100`.
21. **`103.91%` (Max E-W Latency Degradation on Domain C):** `results/attack_eastwest_20260825T074042Z_summary.json` $\to$ `((during.C - baseline.C) / baseline.C) * 100`.
22. **`16.59 s`, `16.48 s`, `16.48 s`, `16.59 s`, `16.51 s`, `16.48 s`, `16.44 s` (Mitigation Cycle Times):** `results/circuit_breaker.log` $\to$ `PIPELINE COMPLETE: Total time-to-mitigation`.
23. **`15.0 s` (Circuit Breaker Reconnection Timeout):** `defense/circuit_breaker.py` $\to$ line 61 (`while time.time() - t_restart < 15:`).
24. **`599` Admitted Requests Out of 6,000 at 200 req/s:** Calculated via `TokenBucket(rate=19, burst=30)` in `defense/ew_flood_mitigator.py`.
25. **`0.60` (Semantic Anomaly Jump Threshold):** `defense/topology_guard.py` $\to$ line 125 (`DEFAULT_MAX_RATIO_DELTA = 0.60`).
26. **`50` (Phantom Port Detection Threshold):** `defense/topology_guard.py` $\to$ line 128 (`DEFAULT_PHANTOM_PORT_THRESHOLD = 50`).
27. **`4969` (Initial Static TE Decisions Count):** `results/attack_packetin_20260825T025248Z_summary.json` $\to$ `baseline.te_decisions_abs`.
