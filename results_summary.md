# Experimental Setup and Parameter Summary

This document serves as the master reference for all experimental parameters, thresholds, and hyperparameters used across Phases 4 through 6. This information can be directly ported into the "Experimental Setup" and "Evaluation" sections of the research paper.

## 1. Testbed Infrastructure & Topology
*   **Emulation Environment**: Mininet (Python API) running on Linux.
*   **SDN Architecture**: Multi-Domain (3 controllers, 3 domains).
    *   **Domain A**: Switches `s1`, `s2`, `s3` (Controller: Ryu A on TCP 6633)
    *   **Domain B**: Switches `s4`, `s5`, `s6` (Controller: Ryu B on TCP 6634)
    *   **Domain C**: Switches `s7`, `s8`, `s9` (Controller: Ryu C on TCP 6653)
*   **Link Bandwidths (TCLink)**:
    *   Inter-switch backbone links: **1000 Mbps**
    *   Host-to-switch edge links: **100 Mbps**
*   **Traffic Generation**: `iperf3` for TE background traffic, `Scapy` (AF_PACKET raw sockets) for malicious packet floods.

## 2. Experimental Scenarios (Phases 4-6)

### Phase 4: Traffic Engineering (East-West Load Balancing)
*   **Congestion Flow**: Continuous UDP flood (`h4` to `h9`) pinning the A-C diagonal (`s1-s2-s3-s5-s8-s9`).
*   **Test Flow**: New flow from `h1` to `h11` attempting to use Domain A.
*   **TE Threshold**: Controller initiates reroute when any link in the shortest path exceeds **70% utilization** (i.e., > 700 Mbps on 1000 Mbps links).
*   **Result**: TE successfully reroutes the test flow via the alternate low-utilization path (`s1-s4-s7-s8`) keeping latency near 15ms.

### Phase 5: Root Cause Vulnerability Assessment (Undefended)
*   **Attack Profile**: North-South `PacketIn` flood originating from `h1`, targeting Domain A's controller.
*   **Attack Mechanism**: Randomized Source IP and Source MAC addresses to ensure zero OpenFlow rule matching, forcing 100% of packets to the controller.
*   **Ramp Profile**: 
    *   Start Rate: **500 pkt/s**
    *   Step Rate: **+500 pkt/s** every 10 seconds.
    *   Max Rate: **5,000 pkt/s**
    *   Duration at Max Rate: **20 seconds**
*   **Result**: Unbounded degradation. Domain A latency peaked over **1,350 ms**, breaking inter-domain TE synchronization and dragging down Domains B and C. Flow-table flushes (`del-flows`) proved completely ineffective due to internal queue poisoning.

### Phase 6: Circuit Breaker Mitigation (Defended)
*   **Detection Mechanism**: Out-of-band dual-signal daemon.
*   **Detection Thresholds**:
    1.  **Datapath Signal**: Edge switch (`s1`) `PacketIn` generation rate > **1,500 pkt/s**.
    2.  **Compute Signal**: Controller (`ryu-manager` A) CPU utilization > **70%**.
    3.  **Time Threshold**: Both signals must remain elevated for **3 consecutive seconds** to avoid false positives.
*   **Mitigation Strategy**: Surgical `SIGKILL` and restart of the isolated controller process.
*   **Prevention Strategy**: Injection of OpenFlow Meter `band=type=drop, rate=100` on the edge switch port to throttle the attacker during recovery.
*   **Result**: Instantaneous recovery. Total time-to-mitigate was **16.73s** (including the 15s API timeout window). Peak latency capped at **14.02 ms** (virtually identical to baseline).

## 3. Future Enhancements & ML Model Parameters (Pipeline Placeholder)
*(Note: These parameters reflect the placeholders used in `generate_results.py` to construct the comparison charts. Adjust these once the actual ML models are trained and evaluated in Phase 7).*

*   **Detector Baseline (Phase 6)**: Static dual-threshold (CPU > 70%, Rate > 1500 pkt/s).
*   **Proposed ML Detector**: Random Forest Classifier.
*   **Features**: Rolling 5-second averages of `PacketIn` rate, CPU variance, Context Switch rate, and East-West synchronization message frequency.
*   **Expected Advantage**: Detection of slow-rate (Low and Slow) saturation attacks that sit just below the static 70% CPU threshold.
