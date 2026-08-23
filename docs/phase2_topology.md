# Phase 2 — Multi-Domain Topology

## Domain Map

```
╔══════════════════════════╗   ╔══════════════════════════╗   ╔══════════════════════════╗
║     DOMAIN A             ║   ║     DOMAIN B             ║   ║     DOMAIN C             ║
║  Controller port 6633    ║   ║  Controller port 6634    ║   ║  Controller port 6635    ║
║  DPIDs: 1, 2, 3          ║   ║  DPIDs: 4, 5, 6          ║   ║  DPIDs: 7, 8, 9          ║
║                          ║   ║                          ║   ║                          ║
║  h1,h2                   ║   ║  h5,h6                   ║   ║  h9                      ║
║    │                     ║   ║    │                     ║   ║   │                      ║
║   s1 ─────── s2 ─── h3  ║   ║   s4 ─────── s5 ─── h7  ║   ║  s7 ─────── s8 ─── h10  ║
║    │         │           ║   ║    │         │           ║   ║   │         │            ║
║    └──── s3 ─┘           ║   ║    └──── s6 ─┘           ║   ║   └──── s9 ─┘            ║
║          │               ║   ║          │               ║   ║         │                ║
║          h4              ║   ║          h8              ║   ║       h11,h12            ║
╚══════════╤═══════════════╝   ╚══════════╤═══════════════╝   ╚══════════╤═══════════════╝
           │  A↔B inter-domain            │  B↔C inter-domain            │
           └──────────── s3──s4 ──────────┘                              │
                                          s6──s7 ───────────────────────┘
           A↔C diagonal:  s3──────────────────────────────────────────s7
```

## Switch-to-Host Mapping

| Switch | Domain | Controller Port | Hosts attached |
|--------|--------|-----------------|----------------|
| s1     | A      | 6633            | h1, h2         |
| s2     | A      | 6633            | h3             |
| s3     | A      | 6633            | h4             |
| s4     | B      | 6634            | h5, h6         |
| s5     | B      | 6634            | h7             |
| s6     | B      | 6634            | h8             |
| s7     | C      | 6635            | h9             |
| s8     | C      | 6635            | h10            |
| s9     | C      | 6635            | h11, h12       |

## Links

| Type         | Link    | Notes                                |
|--------------|---------|--------------------------------------|
| Intra-domain | s1–s2   | Domain A                             |
| Intra-domain | s2–s3   | Domain A                             |
| Intra-domain | s1–s3   | Domain A (creates triangle)          |
| Intra-domain | s4–s5   | Domain B                             |
| Intra-domain | s5–s6   | Domain B                             |
| Intra-domain | s4–s6   | Domain B (creates triangle)          |
| Intra-domain | s7–s8   | Domain C                             |
| Intra-domain | s8–s9   | Domain C                             |
| Intra-domain | s7–s9   | Domain C (creates triangle)          |
| **Inter-domain** | **s3–s4** | **A ↔ B boundary (E-W needed)** |
| **Inter-domain** | **s6–s7** | **B ↔ C boundary (E-W needed)** |
| **Inter-domain** | **s3–s7** | **A ↔ C diagonal (E-W needed)** |

All links: 10 Mbps TCLink.  All hosts: 10.0.0.0/24 subnet.

## Expected Phase 2 Behaviour

| Ping pair type       | Expected result  | Reason                              |
|----------------------|------------------|-------------------------------------|
| Same-domain pair     | ✅ Success        | Controller handles ARP + unicast    |
| Cross-domain pair    | ❌ Fail           | No controller installs cross rules  |

Inter-domain pings fail because:
1. h1 ARPs for h5 → ARP flood hits s3 (Domain A border switch)
2. s3's controller (Domain A, port 6633) installs no rule pointing to s4
3. ARP never crosses into Domain B → h5 never replies

This is the **Phase 3 problem**: East-West MAC-table sharing.

## Launch Commands

```bash
# Clean up first
sudo mn -c

# Terminal 1 — Domain A controller
source ~/ryu311/bin/activate
cd sdn-multictrl
DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 ryu-manager controllers/domain_controller.py \
    --ofp-tcp-listen-port 6633

# Terminal 2 — Domain B controller
DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 ryu-manager controllers/domain_controller.py \
    --ofp-tcp-listen-port 6634

# Terminal 3 — Domain C controller
DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 ryu-manager controllers/domain_controller.py \
    --ofp-tcp-listen-port 6635

# Terminal 4 — topology + verification
sudo python3 experiments/domain_test.py
```
