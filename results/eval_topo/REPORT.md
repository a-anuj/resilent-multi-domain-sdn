# Evaluation Report: Attack 3 - Topology & Link-State Poisoning Guard

**Generated:** 2026-10-28T07:33:12.876957+00:00  
**Evaluation Target:** `http://127.0.0.1:8080/update` (East-West REST Interface)  
**Target Directory:** `results/eval_topo/`  

## 1. Executive Summary & Verdict

**Verdict:** **`SUPPORTED`**  

The experimental evidence **SUPPORTS** the multi-layer Topology Guard defense. In the undefended baseline, 100% of rogue topology poisoning payloads (unsigned lies, forged signatures, phantom links, and anomalous congestion jumps) are admitted directly into global_topology. Under the Topology Guard defense, all 5 poisoning attacks (100.0%) are surgically intercepted and blocked with HTTP 403 across HMAC, Schema, and Semantic validation layers, while legitimate peer updates from Domain B maintain 100.0% admission with zero degradation.

## 2. Comparative Telemetry Table

| Test Case Vector | Attack Vector Description | Undefended Run | Defended Run (Topology Guard) | Defense Validation Layer |
|---|---|---|---|---|
| **Test 1: Unsigned Congestion Lie** | Rogue linkstate claiming 0.95 ratio | Allowed (HTTP 200) | **BLOCKED (HTTP 403)** | Layer 1: Missing HMAC Signature |
| **Test 2: Forged HMAC Attack** | Rogue update with fake HMAC hash | Allowed (HTTP 200) | **BLOCKED (HTTP 403)** | Layer 1: Constant-time HMAC Mismatch |
| **Test 3: Unsigned Phantom Link** | Bogus link with invalid port 99 | Allowed (HTTP 200) | **BLOCKED (HTTP 403)** | Layer 1 & 2: Missing HMAC / Schema |
| **Test 4: Signed Phantom Link** | Insider/compromised key declaring port 99 | Allowed (HTTP 200) | **BLOCKED (HTTP 403)** | Layer 2: Port range threshold (>=50) |
| **Test 5: Signed Congestion Lie** | Insider/compromised key jumping 0.0->0.95 | Allowed (HTTP 200) | **BLOCKED (HTTP 403)** | Layer 3: Semantic ratio delta (>0.60) |
| **Test 6: Legitimate Peer Sync** | Domain B genuine signed linkstate update | **Admitted (HTTP 200)** | **Admitted (HTTP 200)** | Verified (All 3 layers passed) |
| **Overall Attack Poisoning Block Rate** | 5 distinct attack vectors | **0.0% (0 / 5 blocked)** | **100.0% (5 / 5 blocked)** | **Complete Control Plane Immunity** |
| **Legitimate Sync Admission** | Genuine Domain B signed sync | 100.0% Admitted | **100.0% Admitted** | Zero Collateral False Positives |
