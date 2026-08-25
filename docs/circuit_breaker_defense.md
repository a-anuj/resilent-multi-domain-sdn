# Automated Circuit Breaker: Defending SDN Control Planes Against Saturation Attacks

This document details the complete methodology, root-cause discovery, and automated defense mechanism (the "Circuit Breaker") developed to protect a Multi-Domain SDN architecture against catastrophic Control Plane Saturation (PacketIn) attacks.

## 1. The Threat: PacketIn Flooding
In a Software-Defined Network (SDN), when a switch receives a packet that does not match any existing flow rules, it encapsulates the packet in an OpenFlow `PacketIn` message and sends it to the controller for a routing decision. 

A **PacketIn Flood Attack** exploits this mechanism. By generating thousands of spoofed packets per second (with randomized source IP/MAC addresses to evade simple flow-matching), the attacker forces the edge switch to continuously blast the controller with `PacketIn` events. 

During our experiments, we ramped a North-South attack to **5,000 packets per second (pkt/s)** targeting Domain A.

## 2. Root Cause Analysis: Why Traditional Defenses Fail
Our Phase 5 diagnostic experiments revealed a critical vulnerability in the standard Ryu controller architecture:

1. **The Single-Threaded Bottleneck:** Ryu processes OpenFlow events using a single-threaded `eventlet` loop. When hit with 5,000 pkt/s, the controller's CPU pins to 100% and it simply cannot process events fast enough.
2. **Unbounded Queue Saturation:** Because the incoming rate exceeds the processing rate, the internal event queue grows infinitely. Legitimate East-West Traffic Engineering (TE) routing requests get stuck behind tens of thousands of attacker packets.
3. **The "Poisoned Queue" Phenomenon:** We attempted to mitigate the attack by actively flushing the datapath flow tables (`ovs-ofctl del-flows`). **This had zero effect.** Once the controller's internal memory queue is deeply saturated (poisoned), manipulating the external switch does not clear the controller's backlog. The controller continues to process stale packets from minutes ago, leading to unbounded latency degradation (spiking from a baseline of ~14ms up to >3,000ms).

**Conclusion:** The only definitive way to clear a poisoned, single-threaded event queue is to physically kill and restart the controller process.

## 3. The Circuit Breaker Defense Architecture
Based on the root cause, we built an automated "Circuit Breaker" (`defense/circuit_breaker.py`) that operates entirely out-of-band to detect and instantly resolve the saturation state. It consists of three stages:

### Stage 1: Dual-Signal Detection
To avoid false positives from normal bursty traffic, the monitor daemon triggers only when two independent signals remain critically elevated for 3 consecutive seconds:
* **Datapath Signal:** OpenFlow `PacketIn` generation rate at the edge switch exceeds **1,500 pkt/s** (polled via `ovs-ofctl`).
* **Compute Signal:** The specific Ryu Controller process CPU utilization exceeds **70%** (polled via `psutil`).

### Stage 2: Targeted Mitigation (Restart)
Upon detection, the Circuit Breaker executes a surgical strike:
1. It identifies the exact PID of the saturated controller (Domain A).
2. It sends a `SIGKILL` to immediately terminate the poisoned queue.
3. It instantly re-spawns the controller with the exact environment variables needed (`DOMAIN_ID`, `DOMAIN_DPIDS`, `TE_ENABLED`) so it can seamlessly reconnect to the multi-domain fabric.

### Stage 3: Immediate Prevention (Edge Metering)
If we only restarted the controller, the ongoing 5,000 pkt/s flood would instantly poison the new queue. 
To prevent "Controller Flapping", the Circuit Breaker injects a strict OpenFlow **Meter** at the edge switch (e.g., `s1`) the moment mitigation triggers. 
* **Action:** `band=type=drop, rate=100`
* **Effect:** The switch physically drops attacker packets exceeding 100 pkt/s in hardware. This allows the newly restarted controller to boot safely and process legitimate traffic without being immediately overwhelmed.

## 4. Experimental Results (The "Before & After")
We validated the Circuit Breaker using an automated evaluation harness (`experiments/circuit_breaker_eval.py`). The results definitively prove the success of the defense mechanism:

| Metric | Undefended (Phase 5) | Defended (Phase 6 Circuit Breaker) |
| :--- | :--- | :--- |
| **Detection Time** | *Never detected* | **~3 Seconds** |
| **Peak Latency (Domain A)** | **> 1,350 ms** (trending to 3000ms+) | **14.02 ms** (Attack rendered invisible) |
| **System State** | Complete Queue Saturation | Normal Operation |
| **Recovery Window** | **10+ Minutes** (Failed to recover) | **0 Minutes** (Mitigated instantly) |
| **Collateral Impact** | Domains B & C degraded severely | Domains B & C remained perfectly stable |

## 5. Conclusion
By identifying that the true bottleneck lies within the controller's internal application queue rather than the datapath, we successfully designed a defense that treats the controller as an immutable, replaceable component. 

The combination of **Out-of-Band Detection**, **Queue Destruction (Restart)**, and **Datapath Hardware Throttling (Metering)** provides an incredibly resilient architecture capable of neutralizing massive Control Plane saturation attacks in real-time, with zero visible impact to legitimate application latency.
