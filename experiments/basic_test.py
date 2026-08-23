#!/usr/bin/env python3
"""
experiments/basic_test.py
--------------------------
Phase 1 – Baseline connectivity & throughput test.

What it does
------------
1. Instantiates the PartialMeshTopo and starts a Mininet network.
2. Waits for all OVS switches to connect to the Ryu controller.
3. Runs net.pingAll() — logs drop percentage.
4. Runs an iperf3 bandwidth test (h1 → h8, 15 s).
5. Falls back to built-in net.iperf() if iperf3 is absent.
6. Writes a timestamped summary to results/phase1_baseline.log.

Prerequisites
-------------
- Ryu controller already running:
      source ~/ryu311/bin/activate
      ryu-manager controllers/baseline_l2.py

Run this script with sudo (Mininet needs root):
      sudo python3 experiments/basic_test.py

All paths are resolved relative to the project root (sdn-multictrl/).

─── WHY LOGGING IS SET UP BEFORE MININET IMPORTS ────────────────────────────
Python's logging.basicConfig() is a no-op if the root logger already has
handlers.  Mininet's own import chain (mininet.log) configures the root logger
as a side-effect, so any basicConfig() call AFTER a Mininet import is silently
ignored and the FileHandler is never registered.

Fix: build the named logger and attach handlers BEFORE importing anything from
mininet, and attach them directly to the named logger (not the root), so
Mininet's root-logger configuration cannot interfere.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import time
import shutil
import logging
import pwd
import grp
from datetime import datetime

# ── Project root (one level up from experiments/) ────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING — must be configured BEFORE any mininet import
#
#  IMPORTANT: This script runs under sudo, so files created here are owned by
#  root.  We detect the real (pre-sudo) user via SUDO_USER and chown the log
#  file after creation so it remains readable without sudo.
# ═══════════════════════════════════════════════════════════════════════════════
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(RESULTS_DIR, 'phase1_baseline.log')

# Fix ownership: if running under sudo, chown results/ and log to the real user
_sudo_user = os.environ.get('SUDO_USER')
if _sudo_user:
    try:
        _uid = pwd.getpwnam(_sudo_user).pw_uid
        _gid = pwd.getpwnam(_sudo_user).pw_gid
        os.chown(RESULTS_DIR, _uid, _gid)
        # Touch the log file first so we can chown it before the FileHandler opens
        open(LOG_FILE, 'a').close()
        os.chown(LOG_FILE, _uid, _gid)
    except Exception:
        pass   # non-fatal; file will just be root-owned

_fmt = logging.Formatter(
    fmt='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

_file_handler   = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
_stream_handler = logging.StreamHandler(sys.stdout)
_file_handler.setFormatter(_fmt)
_stream_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.DEBUG)
_stream_handler.setLevel(logging.DEBUG)

# Attach handlers directly to OUR named logger — never touch basicConfig
log = logging.getLogger('basic_test')
log.setLevel(logging.DEBUG)
log.propagate = False          # prevent Mininet's root handler from duplicating
log.addHandler(_file_handler)
log.addHandler(_stream_handler)

# ══════════════════════════════════════════════════════════════════════════════
#  Mininet imports (after logging is fully configured)
# ══════════════════════════════════════════════════════════════════════════════
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink

from topology.basic_topo import PartialMeshTopo

# ── Constants ─────────────────────────────────────────────────────────────────
CONTROLLER_IP   = '127.0.0.1'
CONTROLLER_PORT = 6653
CONNECT_WAIT    = 6    # seconds to wait after net.start() for flows to settle
IPERF_DURATION  = 15   # seconds


# ─────────────────────────────────────────────────────────────────────────────
def banner(msg: str) -> None:
    """Print a visible section header to the log."""
    sep = '─' * 72
    log.info(sep)
    log.info('  %s', msg)
    log.info(sep)


def wait_for_controller(net, timeout=30):
    """
    Poll until every OVS switch reports `is_connected: true` to its controller.
    This verifies the actual OpenFlow handshake completed — not just that a
    controller URI is configured in OVS.
    Returns True if all switches connected within timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        all_connected = True
        for sw in net.switches:
            # ovs-vsctl show includes 'is_connected: true' when OF session is up
            output = sw.cmd('ovs-vsctl show')
            if 'is_connected: true' not in output:
                all_connected = False
                break
        if all_connected:
            log.info("All %d switches have active OF connection (is_connected: true).",
                     len(net.switches))
            return True
        time.sleep(1)
    log.warning("Timed out waiting for OF connections after %ds.", timeout)
    log.warning("Check: is ryu-manager running on port %d?", CONTROLLER_PORT)
    return False


def enable_rstp(net, converge_wait=8):
    """
    Enable RSTP (Rapid Spanning Tree) on every OVS bridge.

    Why this is necessary
    ---------------------
    Our partial-mesh topology contains loops (e.g. s1→s2→s5→s1).
    The Ryu L2 switch uses OFPP_FLOOD for unknown destinations (ARP).
    In a looped topology, flooded packets re-enter the switch on another
    port, get flooded again, and create a broadcast storm that saturates
    the network and blocks Mininet's stdout pipe — causing pingAll() to
    hang forever.

    RSTP runs *below* OpenFlow inside OVS.  It detects loops and sets
    some ports to 'blocking' state.  OFPP_FLOOD skips blocking ports, so
    floods can no longer loop.  Once a unicast flow is installed by the
    controller, traffic takes the full mesh path (not limited by RSTP).
    """
    log.info("Enabling RSTP on all bridges to prevent broadcast storms...")
    for sw in net.switches:
        # rstp_enable takes immediate effect; no daemon restart needed
        sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=true')
        # Set RSTP priority (lower = preferred root); use default 0x8000
        sw.cmd(f'ovs-vsctl set bridge {sw.name} other_config:rstp-priority=32768')
    log.info("RSTP enabled on %d switches. Waiting %ds for convergence...",
             len(net.switches), converge_wait)
    time.sleep(converge_wait)
    # Log final RSTP port states for visibility
    for sw in net.switches:
        state = sw.cmd(f'ovs-appctl rstp/show {sw.name} 2>/dev/null || echo "(rstp/show N/A)"')
        log.info("RSTP state [%s]: %s", sw.name, state.strip()[:120])


def run_pingall(net) -> float:
    """Run pingAll and return packet-loss percentage."""
    banner("PING ALL")
    result = net.pingAll()   # returns % loss (float 0–100)
    log.info("pingAll packet-loss: %.1f%%", result)
    return result


def run_iperf3(src, dst, duration=IPERF_DURATION):
    """
    iperf3 bandwidth test from src to dst host.
    Returns raw output string.
    """
    banner(f"IPERF3  {src.name} → {dst.name}  ({duration}s)")

    dst_ip = dst.IP()
    log.info("Starting iperf3 server on %s (%s)", dst.name, dst_ip)

    # Start server in background; --one-off exits after one client
    server_proc = dst.popen(['iperf3', '-s', '--one-off'])
    time.sleep(1)   # let server bind

    log.info("Running iperf3 client on %s → %s for %ds", src.name, dst_ip, duration)
    client_out = src.cmd(f'iperf3 -c {dst_ip} -t {duration} --format m')
    server_proc.terminate()
    server_proc.wait()

    log.info("iperf3 output:\n%s", client_out.strip())
    return client_out


def run_iperf_builtin(net, src, dst):
    """Fallback: use Mininet's built-in iperf (v2) wrapper."""
    banner(f"IPERF (built-in)  {src.name} → {dst.name}")
    result = net.iperf([src, dst], l4Type='TCP', seconds=IPERF_DURATION)
    log.info("iperf result: %s", result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
def main():
    run_start = datetime.now()
    banner(f"Phase 1 Baseline Test  —  started {run_start.isoformat()}")

    log.info("Topology  : PartialMeshTopo  (6 switches, 8 hosts)")
    log.info("Controller: %s:%d", CONTROLLER_IP, CONTROLLER_PORT)
    log.info("Log file  : %s", LOG_FILE)

    setLogLevel('warning')   # suppress Mininet's own stdout chatter

    # ── Build + start network ─────────────────────────────────────────────
    banner("STARTING MININET")
    topo = PartialMeshTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip=CONTROLLER_IP, port=CONTROLLER_PORT),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False,
    )
    net.start()

    # ── Enable RSTP FIRST — before controller wait ───────────────────────
    # This prevents broadcast storms during the initial flood phase.
    enable_rstp(net, converge_wait=8)

    log.info("Waiting for OF controller handshake + flow settle (%ds)...",
             CONNECT_WAIT)
    wait_for_controller(net)
    time.sleep(CONNECT_WAIT)

    # ── Reference hosts (topologically far apart) ──────────────────────────
    h1 = net.get('h1')
    h8 = net.get('h8')
    log.info("h1 IP: %s   h8 IP: %s", h1.IP(), h8.IP())

    # ── Tests ─────────────────────────────────────────────────────────────
    ping_loss = run_pingall(net)
    time.sleep(3)   # let all flows settle before iperf

    if shutil.which('iperf3'):
        iperf_out = run_iperf3(h1, h8, IPERF_DURATION)
    else:
        log.warning("iperf3 not found — using Mininet built-in iperf (v2)")
        iperf_out = run_iperf_builtin(net, h1, h8)

    # ── Summary ───────────────────────────────────────────────────────────
    run_end = datetime.now()
    elapsed = (run_end - run_start).total_seconds()
    banner("TEST SUMMARY")
    log.info("Start time      : %s", run_start.isoformat())
    log.info("End time        : %s", run_end.isoformat())
    log.info("Duration        : %.1f s", elapsed)
    log.info("pingAll loss    : %.1f%%", ping_loss)
    log.info("iperf pair      : h1 (%s) → h8 (%s)", h1.IP(), h8.IP())
    log.info("Results saved to: %s", LOG_FILE)

    # ── Teardown ──────────────────────────────────────────────────────────
    banner("STOPPING MININET")
    net.stop()

    # Flush and close file handler explicitly before exit
    for h in log.handlers:
        h.flush()
        h.close()

    print(f"\n[OK] Results written to: {LOG_FILE}")


if __name__ == '__main__':
    if os.geteuid() != 0:
        print("[ERROR] This script must be run as root (sudo).", file=sys.stderr)
        sys.exit(1)
    main()
