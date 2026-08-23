# SDN Multi-Controller Research Testbed

A research platform for studying **multi-controller SDN architectures**, East-West communication protocols, and the impact of coordinated attacks (and defenses) on controller clusters.

---

## Prerequisites

| Tool | Version confirmed | Notes |
|------|------------------|-------|
| Python | 3.11 | Via `ryu311` venv |
| Ryu | 4.34 | Inside `~/ryu311` venv |
| Mininet | 2.3.1b4 | System-installed |
| Open vSwitch | system | Required by Mininet |

---

## Activating the Environment

> **You must be in your home directory (`~`) to source the venv.**

```bash
cd ~
source ryu311/bin/activate
```

To deactivate:

```bash
deactivate
```

---

## Installing / Updating Python Dependencies

```bash
cd ~
source ryu311/bin/activate
pip install -r /home/a-anuj/Desktop/multi-controller-attack/sdn-multictrl/requirements.txt
```

---

## Project Structure

```
sdn-multictrl/
│
├── controllers/        # Ryu OpenFlow controller applications
│   │                   #   e.g. primary_ctrl.py, backup_ctrl.py
│   └── __init__.py
│
├── topology/           # Mininet topology scripts
│                       #   e.g. multi_ctrl_topo.py, fat_tree.py
│
├── eastwest/           # Custom East-West (inter-controller) protocol code
│   │                   #   e.g. sync_agent.py, state_replication.py
│   └── __init__.py
│
├── attacks/            # Attack simulation scripts
│   │                   #   e.g. flow_table_overflow.py, ctrl_saturation.py
│   └── __init__.py
│
├── defense/            # Detection + mitigation modules
│   │                   #   e.g. anomaly_detector.py, rate_limiter.py
│   └── __init__.py
│
├── experiments/        # Traffic generation & data collection scripts
│   │                   #   e.g. run_experiment.py, collect_stats.py
│   └── __init__.py
│
├── results/            # Logs, CSVs, and plots (git-ignored large files)
│
├── docs/               # Architecture notes, diagrams, paper references
│
├── requirements.txt    # Python package dependencies
└── README.md           # This file
```

---

## Verified Setup Commands

```bash
# Check Ryu
source ~/ryu311/bin/activate
ryu-manager --version
# → ryu-manager 4.34

# Check Mininet (system-level)
mn --version
# → 2.3.1b4

# Run a minimal Mininet ping test (requires sudo)
sudo mn --test pingall
```

---

## Installed Python Packages (via pip)

| Package | Purpose |
|---------|---------|
| `ryu` | OpenFlow controller framework |
| `requests` | REST API calls to controller northbound |
| `flask` | Lightweight REST server for control plane APIs |
| `scapy` | Packet crafting for attack simulations |
| `matplotlib` | Plotting results |
| `pandas` | Data manipulation and CSV handling |
| `numpy` | Numerical computation |
| `scikit-learn` | ML-based anomaly detection |

---

## Development Phases

- [x] **Phase 0** — Environment setup & folder scaffolding ← *you are here*
- [ ] **Phase 1** — Multi-controller topology (Mininet + Ryu)
- [ ] **Phase 2** — East-West synchronization protocol
- [ ] **Phase 3** — Attack simulations
- [ ] **Phase 4** — Detection & mitigation
- [ ] **Phase 5** — Experiments, data collection & analysis

---

## Notes

- `mininet` is **not** in `requirements.txt` because it is system-installed (not a pip package).
- Always run Mininet commands with `sudo` — it needs root to configure network namespaces.
- Ryu controller apps are started with `ryu-manager <app.py>` from inside the activated venv.
