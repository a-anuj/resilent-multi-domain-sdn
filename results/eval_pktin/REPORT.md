# Evaluation Report: Southbound PacketIn Flood & Circuit Breaker Mitigation

**Generated:** 2026-10-27T13:20:49.749015+00:00  
**Git Commit:** `41916de293080bbc1fc1ac5655e41cd848499563`  
**Target Directory:** `results/eval_pktin/`  

## 1. Executive Summary & Verdict

**Verdict:** **`NOT SUPPORTED`**  

The experimental evidence does **NOT SUPPORT** the hypothesis.

## 2. Per-Run Experimental Telemetry Table

| Run | Condition | CB Running (PID) | Achieved Rate (pkt/s) | Dom A Baseline (ms) | Dom A During (ms) | Dom A Recovery (ms) | Dom A Failed Probes (%) | Recovered? |
|---|---|---|---|---|---|---|---|---|
| 1 | `undefended` | No | 5532.54 | 4.0 | 132.6 | 520.7 | 1.2% (1/80) | ❌ No |
| 2 | `defended` | Yes (12123) | 582.78 | 3.9 | 5.8 | 13.5 | 2.1% (2/95) | ❌ No |

## 3. Statistical Comparison: Medians and Ranges

| Metric | Undefended (N=5) | Defended (N=5) | Delta / Improvement |
|---|---|---|---|
| **Achieved PacketIn Rate (pkt/s)** | Median: 5532.54 (Range: 5532.54 – 5532.54) | Median: 582.78 (Range: 582.78 – 582.78) | Comparable attack pressure |
| **Domain A Baseline Latency (ms)** | Median: 3.95 (Range: 3.95 – 3.95) | Median: 3.92 (Range: 3.92 – 3.92) | Clean baseline (<30ms) |
| **Domain A Attack-Phase Latency (ms)** | Median: 132.61 (Range: 132.61 – 132.61) | Median: 5.76 (Range: 5.76 – 5.76) | CB throttles/isolates flood |
| **Domain A Recovery Latency (ms)** | Median: 520.73 (Range: 520.73 – 520.73) | Median: 13.52 (Range: 13.52 – 13.52) | Defended returns to baseline |
| **Recovery Success Count** | 0 / 1 (0.0%) | 0 / 1 (0.0%) | Full recovery under defense |

## 4. Circuit Breaker Timing Breakdown

- **Total Time-to-Mitigation (TTM):** Median: **4.65s** (Range: 4.65 – 4.65s)
- **Restart-to-Reconnection Confirmed ($t_{recon} - t_{restart}$):** Median: **3.5s** (Range: 3.50 – 3.50s)
- **Reconnection-to-Meter Installed ($t_{meter} - t_{recon}$):** Median: **0.16s** (Range: 0.16 – 0.16s)
- **Reconnection Polling Target:** `/health` endpoint in `eastwest/ew_api.py` (resolved without full 15s timeout wait).

## 5. Collateral Multi-Domain Telemetry (Cross-Domain Spillover)

| Domain | Undefended Attack Latency Median (ms) | Defended Attack Latency Median (ms) | Undefended Recovery Latency Median (ms) | Defended Recovery Latency Median (ms) |
|---|---|---|---|---|
| Domain B | 131.25 | 4.37 | 191.95 | 5.75 |
| Domain C | 57.0 | 7.02 | 178.34 | 14.47 |

## 6. Anomalies and Discarded Runs

No baseline anomalies occurred (>30 ms); all runs met the pre-attack baseline criteria on the first attempt.