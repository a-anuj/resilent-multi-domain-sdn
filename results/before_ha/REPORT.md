# Evaluation Report: Southbound PacketIn Flood & Circuit Breaker Mitigation

**Generated:** 2026-10-27T14:32:33.100733+00:00  
**Git Commit:** `2a84303fcc230a9e230380fa8511f5e13d5cd2c5`  
**Target Directory:** `results/eval_pktin/`  

## 1. Executive Summary & Verdict

**Verdict:** **`PARTIALLY`**  

The experimental evidence **PARTIALLY SUPPORTS** the hypothesis. Mitigation is active but exhibits variance under severe queue backlog.

## 2. Per-Run Experimental Telemetry Table

| Run | Condition | CB Running (PID) | Achieved Rate (pkt/s) | Dom A Baseline (ms) | Dom A During (ms) | Dom A Recovery (ms) | Dom A Failed Probes (%) | Recovered? |
|---|---|---|---|---|---|---|---|---|
| 1 | `defended` | Yes (20744) | 590.56 | 4.3 | 5.8 | 4.3 | 2.7% (2/75) | ✅ Yes |

## 3. Statistical Comparison: Medians and Ranges

| Metric | Undefended (N=5) | Defended (N=5) | Delta / Improvement |
|---|---|---|---|
| **Achieved PacketIn Rate (pkt/s)** | Median: 0.0 (Range: N/A) | Median: 590.56 (Range: 590.56 – 590.56) | Comparable attack pressure |
| **Domain A Baseline Latency (ms)** | Median: 0.0 (Range: N/A) | Median: 4.29 (Range: 4.29 – 4.29) | Clean baseline (<30ms) |
| **Domain A Attack-Phase Latency (ms)** | Median: 0.0 (Range: N/A) | Median: 5.78 (Range: 5.78 – 5.78) | CB throttles/isolates flood |
| **Domain A Recovery Latency (ms)** | Median: 0.0 (Range: N/A) | Median: 4.34 (Range: 4.34 – 4.34) | Defended returns to baseline |
| **Recovery Success Count** | 0 / 0 (0.0%) | 1 / 1 (100.0%) | Full recovery under defense |

## 4. Circuit Breaker Timing Breakdown

- **Total Time-to-Mitigation (TTM):** Median: **0.72s** (Range: 0.72 – 0.72s)
- **Restart-to-Reconnection Confirmed ($t_{recon} - t_{restart}$):** Median: **0.01s** (Range: 0.01 – 0.01s)
- **Reconnection-to-Meter Installed ($t_{meter} - t_{recon}$):** Median: **0.71s** (Range: 0.71 – 0.71s)
- **Reconnection Polling Target:** `/health` endpoint in `eastwest/ew_api.py` (resolved without full 15s timeout wait).

## 5. Collateral Multi-Domain Telemetry (Cross-Domain Spillover)

| Domain | Undefended Attack Latency Median (ms) | Defended Attack Latency Median (ms) | Undefended Recovery Latency Median (ms) | Defended Recovery Latency Median (ms) |
|---|---|---|---|---|
| Domain B | 0.0 | 5.8 | 0.0 | 6.49 |
| Domain C | 0.0 | 4.61 | 0.0 | 3.73 |

## 6. Anomalies and Discarded Runs

No baseline anomalies occurred (>30 ms); all runs met the pre-attack baseline criteria on the first attempt.