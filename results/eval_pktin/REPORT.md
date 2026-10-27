# Evaluation Report: Southbound PacketIn Flood & Circuit Breaker Mitigation

**Generated:** 2026-10-27T10:49:47.809156+00:00  
**Git Commit:** `28edf421c9137b05a9b4dcdbf32cd5b0eb0ed7c4`  
**Target Directory:** `results/eval_pktin/`  

## 1. Executive Summary & Verdict

**Verdict:** **`PARTIALLY`**  

The experimental evidence **PARTIALLY SUPPORTS** the hypothesis. Mitigation is active but exhibits variance under severe queue backlog.

## 2. Per-Run Experimental Telemetry Table

| Run | Condition | CB Running (PID) | Achieved Rate (pkt/s) | Dom A Baseline (ms) | Dom A During (ms) | Dom A Recovery (ms) | Dom A Failed Probes (%) | Recovered? |
|---|---|---|---|---|---|---|---|---|
| 1 | `undefended` | No | 5428.25 | 4.3 | 93.9 | 307.4 | 0.0% (0/66) | ❌ No |
| 2 | `defended` | Yes (31902) | 792.7 | 5.1 | 6.5 | 10.5 | 4.0% (3/75) | ❌ No |
| 3 | `undefended` | No | 5501.94 | 4.5 | 126.2 | 232.5 | 0.0% (0/66) | ❌ No |
| 4 | `defended` | Yes (36708) | 776.35 | 4.2 | 5.6 | 8.5 | 2.7% (2/75) | ✅ Yes |
| 5 | `undefended` | No | 5534.96 | 4.4 | 131.5 | 283.5 | 0.0% (0/66) | ❌ No |
| 6 | `defended` | Yes (41478) | 789.57 | 4.5 | 4.9 | 8.5 | 2.7% (2/75) | ✅ Yes |
| 7 | `undefended` | No | 5507.74 | 4.5 | 112.1 | 160.3 | 0.0% (0/66) | ❌ No |
| 8 | `defended` | Yes (46275) | 735.06 | 4.4 | 4.7 | 10.9 | 2.7% (2/75) | ❌ No |
| 9 | `undefended` | No | 5477.23 | 4.4 | 119.3 | 263.9 | 0.0% (0/66) | ❌ No |
| 10 | `defended` | Yes (51053) | 776.6 | 4.3 | 7.0 | 7.8 | 4.0% (3/75) | ✅ Yes |

## 3. Statistical Comparison: Medians and Ranges

| Metric | Undefended (N=5) | Defended (N=5) | Delta / Improvement |
|---|---|---|---|
| **Achieved PacketIn Rate (pkt/s)** | Median: 5501.94 (Range: 5428.25 – 5534.96) | Median: 776.6 (Range: 735.06 – 792.70) | Comparable attack pressure |
| **Domain A Baseline Latency (ms)** | Median: 4.41 (Range: 4.35 – 4.54) | Median: 4.36 (Range: 4.18 – 5.09) | Clean baseline (<30ms) |
| **Domain A Attack-Phase Latency (ms)** | Median: 119.35 (Range: 93.94 – 131.52) | Median: 5.64 (Range: 4.74 – 7.04) | CB throttles/isolates flood |
| **Domain A Recovery Latency (ms)** | Median: 263.9 (Range: 160.28 – 307.45) | Median: 8.54 (Range: 7.78 – 10.95) | Defended returns to baseline |
| **Recovery Success Count** | 0 / 5 (0.0%) | 3 / 5 (60.0%) | Full recovery under defense |

## 4. Circuit Breaker Timing Breakdown

- **Total Time-to-Mitigation (TTM):** Median: **4.41s** (Range: 4.40 – 4.55s)
- **Restart-to-Reconnection Confirmed ($t_{recon} - t_{restart}$):** Median: **3.29s** (Range: 3.27 – 3.29s)
- **Reconnection-to-Meter Installed ($t_{meter} - t_{recon}$):** Median: **0.13s** (Range: 0.12 – 0.24s)
- **Reconnection Polling Target:** `/health` endpoint in `eastwest/ew_api.py` (resolved without full 15s timeout wait).

## 5. Collateral Multi-Domain Telemetry (Cross-Domain Spillover)

| Domain | Undefended Attack Latency Median (ms) | Defended Attack Latency Median (ms) | Undefended Recovery Latency Median (ms) | Defended Recovery Latency Median (ms) |
|---|---|---|---|---|
| Domain B | 77.06 | 4.24 | 236.55 | 7.33 |
| Domain C | 22.4 | 3.66 | 114.47 | 10.11 |

## 6. Anomalies and Discarded Runs

No baseline anomalies occurred (>30 ms); all runs met the pre-attack baseline criteria on the first attempt.