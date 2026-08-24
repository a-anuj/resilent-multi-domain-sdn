#!/usr/bin/env python3
"""
experiments/te_test.py
-----------------------
Phase 4: Traffic Engineering experiment.

Two-trial experiment:
  Trial A — TE ENABLED  (TE_ENABLED=1 on all controllers)
  Trial B — TE DISABLED (TE_ENABLED=0, shortest-hop-count path only)

Procedure per trial
───────────────────
  1. Start iperf3 servers on h9 and h11 (Domain C)
  2. Saturate the DIRECT path (s3→s7, A↔C diagonal) with iperf3 from h1 to h9
     for 35s  (background traffic)
  3. Start a NEW iperf3 flow from h3 to h11 for 20s
  4. Record:
     - Which path the new flow took (from te_decisions.log)
     - Achieved throughput (from iperf3 JSON output)
     - Link utilizations at decision time
  5. Repeat with TE disabled, record same metrics on the congested path

Expected results
────────────────
  TE ON  → new flow avoids s3-s7 (diagonal), takes A→B→C instead
           → higher throughput than TE OFF
  TE OFF → new flow also uses s3-s7 (congested) → lower throughput

Run:
    # With TE ENABLED controllers already running:
    sudo python3 experiments/te_test.py --mode te

    # With TE DISABLED controllers:
    sudo python3 experiments/te_test.py --mode baseline

    # Run both sequentially (requires restarting controllers between):
    sudo python3 experiments/te_test.py --mode both
"""

import argparse
import json
import os
import re
import sys
import time
import logging
import subprocess
import threading
from datetime import datetime
from itertools import combinations

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(RESULTS_DIR, 'te_test.log')

import pwd
_suser = os.environ.get('SUDO_USER')
if _suser:
    try:
        _uid = pwd.getpwnam(_suser).pw_uid
        _gid = pwd.getpwnam(_suser).pw_gid
        open(LOG_FILE, 'a').close()
        os.chown(LOG_FILE, _uid, _gid)
    except Exception:
        pass

_fmt = logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s',
                         datefmt='%Y-%m-%d %H:%M:%S')
_fh  = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
_sh  = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger('te_test')
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Mininet + topology ────────────────────────────────────────────────────────
from mininet.log import setLogLevel
from topology.multi_domain_topo import (
    build_network, assign_controllers, enable_rstp,
    DOMAIN_HOSTS, HOST_DOMAIN, SWITCH_CTRL_PORT,
    CTRL_A_PORT, CTRL_B_PORT, CTRL_C_PORT,
)

# ── Test configuration ────────────────────────────────────────────────────────
EW_PORTS   = {'A': 8080, 'B': 8081, 'C': 8082}
EW_HOST    = '127.0.0.1'
TE_DEC_LOG = os.path.join(RESULTS_DIR, 'te_decisions.log')
EW_LOG     = os.path.join(RESULTS_DIR, 'eastwest_traffic.log')

CONNECT_WAIT      = 20    # s: switch→controller connection wait
SYNC_WAIT         = 15    # s: EW sync convergence wait
PRE_WARM_WAIT     = 15    # s: after ping pre-warm, wait for EW sync to propagate host info (3 cycles)
STATS_WARMUP      = 15    # s: wait for 3x PortStats cycles (interval=5s) before reading utils
SATURATE_DURATION = 35    # s: background iperf3 duration — long enough for util to be measured
NEW_FLOW_DURATION = 20    # s: new flow iperf3 duration
IPERF_PORT_SAT    = 5201  # saturation flow server port
IPERF_PORT_NEW    = 5202  # new flow server port (separate, avoids "server busy" error)
HTTP_TIMEOUT      = 4

# Minimum saturation wait before starting new flow:
# Must be > 2 x STATS_INTERVAL (5s) + 1 x EW_SYNC_INTERVAL (5s) = 15s
MIN_SAT_WAIT      = 20    # s: wait for at least 4 PortStats + 2 EW sync cycles

# Topology: h1, h2 in Domain A; h12 in Domain C
# Direct A↔C path:  s1→s3→s7→s9→h12     (via s3-s7 diagonal)
# Alt A→B→C path:   s1→s3→s4→s6→s7→s9→h12 (via s3-s4 and s6-s7)
CONGESTED_LINK = 'A↔C diagonal (s3-s7, dpid 3→7)'
ALTERNATE_PATH = 'A→B→C (s3→s4→s6→s7)'

PASS = '✅ PASS'
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'

results = {}


# ── Utilities ─────────────────────────────────────────────────────────────────

def banner(msg: str):
    sep = '═' * 72
    log.info(sep); log.info('  %s', msg); log.info(sep)

def section(msg: str):
    log.info('─' * 72); log.info('  %s', msg); log.info('─' * 72)


def ew_get(domain: str, endpoint: str) -> dict | None:
    try:
        r = requests.get(f'http://{EW_HOST}:{EW_PORTS[domain]}{endpoint}',
                         timeout=HTTP_TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def wait_for_switches(net, timeout: int = CONNECT_WAIT) -> bool:
    log.info('Waiting for switches (max %ds)...', timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        not_yet = [sw.name for sw in net.switches
                   if sw.cmd(f'ovs-vsctl get controller {sw.name} '
                              'is_connected 2>/dev/null').strip() != 'true']
        if not not_yet:
            log.info('All switches connected ✓')
            return True
        log.info('  Waiting: %s (%.0fs left)', ', '.join(not_yet),
                 deadline - time.time())
        time.sleep(2)
    log.error('Timed out — disconnected: %s', ', '.join(not_yet))
    return False


def flush_te_flows(net):
    """
    Delete all priority=50 TE flow rules from every switch.

    This is critical: the pre-warm pings install flow rules with
    idle_timeout=30. Without flushing, the iperf flows reuse these
    cached rules and never trigger a new PacketIn/TE decision.
    Flushing forces a fresh TE decision at the start of each trial.
    """
    log.info('  Flushing stale priority=50 TE rules from all switches...')
    for sw in net.switches:
        sw.cmd(f'ovs-ofctl del-flows {sw.name} priority=50 -O OpenFlow13 2>/dev/null')
    time.sleep(0.5)   # brief pause for OF messages to propagate
    log.info('  TE flow rules flushed.')


def pin_saturation_path(net, h4, h9):
    """
    Install priority=55 OpenFlow rules pinning h4→h9 saturation traffic
    through the DIRECT A↔C diagonal link (s3-p4 ↔ s7-p4).

    From STATIC_LINKS: (3, 4, 7, 4) means s3-port4 ↔ s7-port4.
    So: h4→s3 via h4's port → s3 out via port 4 → s7 in via port 4 → h9 out via port 5.
    Return: h9→s7 via port 5 → s7 out via port 4 → s3 in via port 4 → s3 out to h4.

    Priority=55 > priority=50 (TE rules) so these override any pre-warm TE decisions.
    They also override the default idle_timeout=30 by setting idle=0 (permanent for trial).
    """
    log.info('  Pinning h4→h9 saturation through direct A↔C diagonal (s3:p4↔s7:p4)...')
    h4_mac = h4.MAC()
    h9_mac = h9.MAC()
    s3 = net.get('s3')
    s7 = net.get('s7')

    # s3: traffic from h4 (any in_port) destined h9 → out port 4 (→ s7)
    s3.cmd(f'ovs-ofctl add-flow s3 priority=55,dl_dst={h9_mac},actions=output:4 '
           f'-O OpenFlow13')
    # s3: return traffic from s7 (in port 4) destined h4 → out to h4
    # h4 is on s3 — we need to know h4's port. Use mac-based output via existing table rule.
    # Install a rule that covers in_port=4 dl_dst=h4_mac → flood local (will hit h4 via L2)
    s3.cmd(f'ovs-ofctl add-flow s3 priority=55,in_port=4,dl_dst={h4_mac},actions=output:5 '
           f'-O OpenFlow13')

    # s7: traffic from s3 (in port 4) destined h9 → out port 5 (→ h9)
    s7.cmd(f'ovs-ofctl add-flow s7 priority=55,in_port=4,dl_dst={h9_mac},actions=output:5 '
           f'-O OpenFlow13')
    # s7: return from h9 (in port 5) destined h4 → out port 4 (→ s3)
    s7.cmd(f'ovs-ofctl add-flow s7 priority=55,in_port=5,dl_dst={h4_mac},actions=output:4 '
           f'-O OpenFlow13')
    log.info('  Saturation path pinned: s3:p5(h4)→s3:p4→s7:p4→s7:p5(h9)')


def read_last_te_decisions(n: int = 999999) -> list[dict]:
    """Read the last n entries from te_decisions.log."""
    if not os.path.exists(TE_DEC_LOG):
        return []
    records = []
    with open(TE_DEC_LOG) as f:
        for line in f:
            try:
                # Each line: "timestamp  {json}"
                parts = line.strip().split('  ', 1)
                if len(parts) == 2:
                    records.append(json.loads(parts[1]))
            except Exception:
                pass
    return records[-n:]


def run_iperf_server(host, port: int) -> None:
    """Start iperf3 server on a Mininet host on the given port."""
    host.cmd(f'pkill -9 -f "iperf3 -s -p {port}" 2>/dev/null; sleep 0.2')
    host.cmd(f'rm -f /tmp/iperf_server_{port}.log')
    host.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf_server_{port}.log')
    time.sleep(0.5)
    log.info('  iperf3 server started on %s (%s) port=%d', host.name, host.IP(), port)


def run_iperf_client(src_host, dst_host, duration: int,
                     output_file: str, port: int = IPERF_PORT_SAT,
                     bitrate: str = '0', udp: bool = False) -> None:
    """
    Run iperf3 client from src to dst for `duration` seconds.
    Results written to output_file as JSON.
    """
    dst_ip = dst_host.IP()
    # ``-b`` has dependable offered-load semantics with UDP. TCP pacing is
    # host/kernel dependent and failed to generate the intended 8 Mbps load.
    protocol_arg = '-u ' if udp else ''
    cmd = (f'iperf3 -c {dst_ip} -p {port} -t {duration} {protocol_arg}'
           f'-b {bitrate} -J > {output_file} 2>&1')
    log.info('  iperf3: %s → %s  port=%d  dur=%ds  bitrate=%s',
             src_host.name, dst_host.name, port, duration,
             bitrate if bitrate != '0' else 'unlimited')
    src_host.cmd(cmd)


def parse_iperf_throughput(output_file: str) -> float | None:
    """Parse iperf3 JSON output and return achieved Mbps (or None on error)."""
    try:
        with open(output_file) as f:
            data = json.load(f)
        if 'error' in data:
            log.warning('  iperf3 error: %s', data['error'])
            return None
        end_data = data.get('end', {})
        if not end_data:
            log.warning('  iperf3 JSON missing "end" block. Full JSON keys: %s', list(data.keys()))
            return None
        if 'sum_received' in end_data:
            bps = end_data['sum_received']['bits_per_second']
        elif 'sum_sent' in end_data:
            bps = end_data['sum_sent']['bits_per_second']
        elif 'sum' in end_data:
            bps = end_data['sum']['bits_per_second']
        else:
            log.warning('  iperf3 JSON missing sum metrics in end dict: keys=%s', list(end_data.keys()))
            return None
        return round(bps / 1e6, 3)
    except Exception as exc:
        log.warning('  iperf3 parse error: %s', exc)
        return None


def dump_switch_flows(net, switch_names: list[str]) -> dict[str, str]:
    """Dump ovs-ofctl flow tables for given switches."""
    flows = {}
    for sw_name in switch_names:
        sw = net.get(sw_name)
        flows[sw_name] = sw.cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw_name}')
    return flows


def check_iperf3_available(net) -> bool:
    """Verify iperf3 is installed inside the Mininet hosts."""
    h = net.get('h1')
    out = h.cmd('which iperf3')
    if not out.strip():
        log.error('iperf3 not found — install with: sudo dnf/apt install iperf3')
        return False
    return True


# ── Linkstate snapshot ────────────────────────────────────────────────────────

def snapshot_link_utils(label: str = '') -> dict:
    """Fetch utilization rates from all 3 controllers and merge."""
    all_utils = {}
    for domain in ['A', 'B', 'C']:
        data = ew_get(domain, '/linkstate')
        if data and 'util_rates' in data:
            all_utils[domain] = data['util_rates']  # {dpid_str: {port_str: {ratio,...}}}

    # Build flat display: domain -> 'sX:pY: Z%'
    display = {}
    for d, dpid_map in all_utils.items():
        display[d] = {}
        for dpid_str, port_map in dpid_map.items():
            for port_str, pdata in port_map.items():
                key = f's{dpid_str}:p{port_str}'
                display[d][key] = f"{pdata.get('ratio', 0):.1%}"

    log.info('  [Utils%s] %s', f' {label}' if label else '', display)
    return all_utils


# ── Single trial ──────────────────────────────────────────────────────────────

def run_trial(net, mode: str) -> dict:
    """
    Run one TE trial.
    mode: 'te' | 'baseline'
    Returns metrics dict.
    """
    section(f'TRIAL: {mode.upper()}')
    log.info('  TE enabled: %s', mode == 'te')

    h4  = net.get('h4')    # Domain A — saturation source (s3)
    h1  = net.get('h1')    # Domain A — new flow source (s1)
    h9  = net.get('h9')    # Domain C — saturation destination (s7)
    h11 = net.get('h11')   # Domain C — new flow destination (s9)

    # Start TWO iperf3 server instances (different hosts/ports)
    run_iperf_server(h9, IPERF_PORT_SAT)
    run_iperf_server(h11, IPERF_PORT_NEW)

    # Flush stale TE flow rules so iperf triggers fresh PacketIn events
    flush_te_flows(net)

    # Pin saturation flow through the direct A↔C diagonal so the right link gets loaded
    pin_saturation_path(net, h4, h9)

    # ── PRE-WARM: bidirectional ping to trigger host registration + EW sync ──
    # IMPORTANT — two-sided warm-up is required:
    #
    #   h4→h9 fails on first attempt because Domain A controller hasn't learned
    #   h9's location yet (EW sync takes 1-2 cycles). However, if h9 pings h4
    #   first, Domain C's controller sees the flow → registers h4's MAC → EW
    #   sync propagates it → Domain A now knows h9 is in domain C → next
    #   h4→h9 PacketIn correctly triggers _handle_inter_domain → flow installed.
    #
    # Strategy:
    #   1. Fire reverse pings (C→A) so both controllers see EACH OTHER's hosts.
    #   2. Poll EW REST API to confirm host MACs are globally visible.
    #   3. Then forward ping (A→C) — now routes correctly on first try.

    log.info('Pre-warming: firing reverse pings (C→A) to seed global topology...')
    # Step 1: reverse pings in background — don't wait, just trigger PacketIn
    h9.cmd(f'ping -c 2 -W 2 {h4.IP()} 2>&1 &')
    h11.cmd(f'ping -c 2 -W 2 {h1.IP()} 2>&1 &')
    time.sleep(5)   # one full EW sync cycle (5s interval)

    # Step 2: poll EW APIs to confirm h4 and h9 are globally registered
    log.info('Pre-warming: verifying cross-domain host registration via EW APIs...')
    h4_mac  = h4.MAC()
    h9_mac  = h9.MAC()
    h1_mac  = h1.MAC()
    h11_mac = h11.MAC()

    for _wait_round in range(6):   # up to 30s (6 x 5s)
        reg = {}
        for domain in ['A', 'B', 'C']:
            data = ew_get(domain, '/hosts')
            if data:
                reg[domain] = set(data.keys()) if isinstance(data, dict) else set()
        all_macs = set().union(*reg.values()) if reg else set()
        needed = {h4_mac, h9_mac, h1_mac, h11_mac}
        missing = needed - all_macs
        if not missing:
            log.info('  All 4 test host MACs registered globally ✓')
            break
        log.info('  Waiting for EW sync... missing MACs: %s', missing)
        # Re-trigger with fresh reverse pings if still missing
        if _wait_round >= 2:
            h9.cmd(f'ping -c 1 -W 1 {h4.IP()} 2>&1 &')
            h11.cmd(f'ping -c 1 -W 1 {h1.IP()} 2>&1 &')
        time.sleep(5)
    else:
        log.warning('  EW host registration incomplete after 30s — proceeding anyway.')

    # Step 3: forward pings (A→C) — now both controllers know the hosts
    log.info('Pre-warming: forward pings h4→h9 and h1→h11...')
    for src, name, dst, dst_name in [(h4, 'h4', h9, 'h9'), (h1, 'h1', h11, 'h11')]:
        ok = False
        for attempt in range(1, 6):   # up to 5 attempts with growing wait
            result = src.cmd(f'ping -c 3 -W 3 {dst.IP()} 2>&1')
            if '0 received' not in result and 'unreachable' not in result:
                log.info('  Pre-warm ping %s→%s OK (attempt %d)', name, dst_name, attempt)
                ok = True
                break
            log.warning('  Pre-warm ping %s→%s attempt %d failed, retrying...', name, dst_name, attempt)
            time.sleep(min(5 * attempt, 20))   # 5s, 10s, 15s, 20s back-off
        if not ok:
            log.warning('  Pre-warm ping %s→%s FAILED — continuing (TE will install on first iperf packet).', name, dst_name)
    log.info('Waiting %ds for EW sync to propagate host locations...', PRE_WARM_WAIT)
    time.sleep(PRE_WARM_WAIT)


    # ── Step 1: Wait for PortStats warmup then snapshot baseline ──────────
    log.info('Waiting %ds for PortStats warmup (3 x %ds interval)...',
             STATS_WARMUP, 5)
    time.sleep(STATS_WARMUP)
    log.info('Snapshotting baseline link utilizations...')
    utils_before = snapshot_link_utils('before')

    # ── Step 2: Saturate direct A↔C path with h4→h9 background traffic ──
    section(f'Saturating {CONGESTED_LINK} for {SATURATE_DURATION}s')
    sat_file = f'/tmp/iperf_sat_{mode}.json'

    def _saturate():
        run_iperf_client(h4, h9, SATURATE_DURATION, sat_file,
                         port=IPERF_PORT_SAT, bitrate='8M', udp=True)

    sat_thread = threading.Thread(target=_saturate, daemon=True)
    sat_thread.start()

    # Wait for saturation to take effect + at least two full stats+EW cycles
    wait_sat = MIN_SAT_WAIT
    log.info('  Waiting %ds for saturation to take effect (4 PortStats + 2 EW cycles)...', wait_sat)
    time.sleep(wait_sat)

    # ── Step 3: Snapshot utilization under load + FAIL-FAST SANITY CHECK ────
    utils_during = snapshot_link_utils('during saturation')

    # ─ Saturation sanity check ───────────────────────────────────────────────
    # After MIN_SAT_WAIT the A↔C diagonal MUST show > 50% utilization at
    # either physical endpoint. OVS/TCLink can expose a one-way stream as RX
    # at only one endpoint during a polling window, so demanding both ports
    # independently creates a false failure.
    # If it doesn't, something is structurally wrong (wrong path, loop
    # corrupting PortStats, stale cache) and there is no point continuing.
    #
    # Historically this check would have caught:
    #   • The broadcast-only STP rule that allowed unicast loops (236k CTRL pkts)
    #   • failMode=standalone OVS fallback to L2 flooding
    #   • A pre-warm TE decision routing the saturation flow via A→B→C instead
    #     of the intended direct A↔C diagonal
    DIAGONAL_PORTS = {'s3:p4', 's7:p4'}
    SAT_MIN_PCT    = 50.0   # % — 8 Mbps on a 10 Mbps link = 80%; 50% is a conservative floor

    sat_pct_found = {}
    for domain, dpid_map in utils_during.items():
        if not isinstance(dpid_map, dict):
            continue
        for dpid_str, port_map in dpid_map.items():
            if not isinstance(port_map, dict):
                continue
            for port_str, pdata in port_map.items():
                port_key = f's{dpid_str}:p{port_str}'
                if port_key in DIAGONAL_PORTS:
                    try:
                        if isinstance(pdata, dict):
                            pct = pdata.get('ratio', 0) * 100
                        else:
                            pct = float(str(pdata).replace('%', ''))
                        sat_pct_found[port_key] = max(sat_pct_found.get(port_key, 0.0), pct)
                    except ValueError:
                        pass

    sat_ok = True
    missing_ports = []
    low_util_ports = []
    
    for req_port in DIAGONAL_PORTS:
        if req_port not in sat_pct_found:
            missing_ports.append(req_port)
        elif sat_pct_found[req_port] <= SAT_MIN_PCT:
            low_util_ports.append(f"{req_port} ({sat_pct_found[req_port]:.1f}%)")

    diagonal_peak_pct = max(sat_pct_found.values(), default=0.0)
    sat_ok = bool(sat_pct_found) and diagonal_peak_pct > SAT_MIN_PCT

    if not sat_ok:
        log.error('FAIL-FAST: Diagonal link saturation check failed.')
        if missing_ports:
            log.error('  -> MISSING DATA for ports: %s', missing_ports)
        if low_util_ports:
            log.error('  -> LOW UTILIZATION for ports: %s (Expected > %s%%)', low_util_ports, SAT_MIN_PCT)
        # Finish the client and expose its JSON result. Previously an iperf
        # failure (for example, connection refused) was hidden by this path.
        sat_thread.join(timeout=SATURATE_DURATION)
        sat_throughput = parse_iperf_throughput(sat_file)
        log.error('  Saturation iperf throughput: %s Mbps', sat_throughput)
        h9.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_SAT}" 2>/dev/null')
        h11.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_NEW}" 2>/dev/null')
        return {
            'mode': mode, 'throughput_mbps': None, 'te_decisions': 0,
            'path_used': None, 'used_direct': None,
            'utils_before': utils_before, 'utils_during': utils_during,
            'fail_fast': 'no_diagonal_portstats',
            'saturation_throughput_mbps': sat_throughput,
        }
    else:
        log.info('  Saturation sanity check PASSED: diagonal util = %s ✓',
                 {k: f'{v:.1f}%' for k, v in sat_pct_found.items()})
        if low_util_ports:
            log.warning('  Asymmetric port counters on diagonal: %s; using link peak %.1f%%.',
                        low_util_ports, diagonal_peak_pct)



    # ── Step 4: Start new flow h1 → h11 on SEPARATE port ─────────────────
    section(f'Starting NEW flow h1→h11 ({NEW_FLOW_DURATION}s)')
    te_decisions_before = len(read_last_te_decisions())

    new_flow_file = f'/tmp/iperf_new_{mode}.json'
    run_iperf_client(h1, h11, NEW_FLOW_DURATION, new_flow_file,
                     port=IPERF_PORT_NEW)

    # ── Step 5: Wait for saturation to finish ────────────────────────────
    sat_thread.join(timeout=SATURATE_DURATION + 5)

    # ── Step 6: Collect results ───────────────────────────────────────────
    throughput = parse_iperf_throughput(new_flow_file)
    log.info('  New flow throughput: %s Mbps', throughput)

    # Get TE decision records
    all_decisions = read_last_te_decisions()
    new_decisions = all_decisions[te_decisions_before:]
    log.info('  TE decisions during trial: %d', len(new_decisions))
    for d in new_decisions[-3:]:
        log.info('    flow=%s  path=%s  max_util=%.1f%%  trigger=%s',
                 d.get('flow_id', '?'),
                 '→'.join(d.get('path', [])),
                 d.get('max_util', 0) * 100,
                 d.get('trigger', '?'))

    # ── Step 7: Dump flow tables on boundary switches ─────────────────────
    section('Flow table dump (s1, s2, s3, s4, s6, s7)')
    flows = dump_switch_flows(net, ['s1', 's2', 's3', 's4', 's6', 's7'])
    for sw, table in flows.items():
        log.info('[%s flows]\n%s', sw, table[:600])

    # ── Step 8: Check if new flow avoided congested path (TE case) ────────
    path_used = None
    for d in reversed(new_decisions):
        if d.get('src_dpid') in (1, 2):  # h1/h2 connects to s1/s2
            path_used = d.get('path', [])
            break

    used_direct = False
    if path_used:
        # Direct path: goes s3→s7 directly (no s4 hop)
        hops = [h.split(':')[0] for h in path_used]
        used_direct = 's3' in hops and 's4' not in hops and 's7' in hops

    log.info('  Path used by new flow: %s', path_used)
    log.info('  Used direct (congested) A↔C path: %s', used_direct)

    metrics = {
        'mode':            mode,
        'throughput_mbps': throughput,
        'te_decisions':    len(new_decisions),
        'path_used':       path_used,
        'used_direct':     used_direct,
        'utils_before':    utils_before,
        'utils_during':    utils_during,
    }

    # Cleanup
    h9.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_SAT}" 2>/dev/null')
    h11.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_NEW}" 2>/dev/null')
    return metrics


# ── Comparison + summary ──────────────────────────────────────────────────────

def compare_trials(te_metrics: dict, baseline_metrics: dict):
    banner('TE vs BASELINE COMPARISON')

    te_tp  = te_metrics.get('throughput_mbps') or 0.0
    bl_tp  = baseline_metrics.get('throughput_mbps') or 0.0
    gain   = te_tp - bl_tp
    gain_pct = (gain / bl_tp * 100) if bl_tp > 0 else 0

    log.info('  %-25s  %7s Mbps', 'TE throughput:', te_tp)
    log.info('  %-25s  %7s Mbps', 'Baseline throughput:', bl_tp)
    log.info('  %-25s  %+.2f Mbps  (%+.1f%%)', 'TE gain:', gain, gain_pct)
    log.info('')

    te_failed = te_metrics.get('fail_fast')
    baseline_failed = baseline_metrics.get('fail_fast')
    te_avoided  = not te_metrics.get('used_direct', True)
    bl_congested = baseline_metrics.get('used_direct', False)

    log.info('  TE avoided congested path:    %s', '✓' if te_avoided else '✗')
    log.info('  Baseline used congested path: %s', '✓' if bl_congested else '✗')

    # Save comparison to JSON for paper Table 1
    comparison = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'te':        te_metrics,
        'baseline':  baseline_metrics,
        'gain_mbps': round(gain, 3),
        'gain_pct':  round(gain_pct, 1),
        'te_rerouted': te_avoided,
    }
    out_file = os.path.join(RESULTS_DIR, 'te_comparison.json')
    with open(out_file, 'w') as f:
        json.dump(comparison, f, indent=2, default=str)
    log.info('')
    log.info('  Comparison saved: %s', out_file)

    # A fail-fast result has no valid path or throughput measurement. Do not
    # report it as a successful reroute merely because ``used_direct`` is None.
    if te_failed or baseline_failed:
        log.error('  ⛔ Invalid comparison: saturation failed (TE=%s, baseline=%s).',
                  te_failed, baseline_failed)
        results['te_experiment'] = FAIL
    elif te_avoided and bl_congested and te_tp > bl_tp:
        log.info('  🎉 TE VERIFIED — rerouted AND achieved higher throughput')
        results['te_experiment'] = PASS
    elif te_avoided and bl_congested:
        log.info('  ⚠️  TE rerouted correctly but throughput difference marginal')
        results['te_experiment'] = WARN
    else:
        log.error('  ⛔ TE did not reroute — check controller logs and te_decisions.log')
        results['te_experiment'] = FAIL

    log.info('Result: %s', results['te_experiment'])


def print_summary(mode: str):
    banner(f'PHASE 4 TE TEST SUMMARY ({mode.upper()})')
    log.info('  te_decisions.log : %s', TE_DEC_LOG)
    log.info('  te_comparison    : %s', os.path.join(RESULTS_DIR, 'te_comparison.json'))
    log.info('  test log         : %s', LOG_FILE)
    if 'te_experiment' in results:
        log.info('  Experiment result: %s', results['te_experiment'])


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Phase 4 TE experiment')
    parser.add_argument('--mode', choices=['te', 'baseline', 'both'],
                        default='te',
                        help='te = TE-enabled trial; baseline = TE-off; '
                             'both = run both (controllers must be restarted between)')
    args = parser.parse_args()

    if os.geteuid() != 0:
        print('[ERROR] Run with sudo.', file=sys.stderr)
        sys.exit(1)

    banner(f'Phase 4 TE Test — {datetime.now().isoformat()}  mode={args.mode}')

    # Pre-flight: check controllers
    for domain, port in EW_PORTS.items():
        data = ew_get(domain, '/topology')
        if data is None:
            log.error('Domain %s REST API not reachable on port %d — '
                      'start all 3 ew_controller instances first.', domain, port)
            sys.exit(1)
    log.info('All 3 controller REST APIs reachable ✓')

    setLogLevel('warning')
    net = build_network()
    log.info('Starting network...')
    net.start()

    log.info('Installing software spanning tree (no RSTP, instant)...')
    enable_rstp(net, wait=0)

    log.info('Assigning controllers...')
    assign_controllers(net)

    if not wait_for_switches(net, timeout=60):
        log.warning('Proceeding despite some disconnected switches.')

    if not check_iperf3_available(net):
        net.stop()
        sys.exit(1)

    log.info('Waiting %ds for EW sync convergence...', SYNC_WAIT)
    time.sleep(SYNC_WAIT)

    log.info('Pre-warming Global Topology via local pings...')
    h4 = net.get('h4')
    h3 = net.get('h3')
    h9 = net.get('h9')
    h10 = net.get('h10')
    h1 = net.get('h1')
    h2 = net.get('h2')
    h11 = net.get('h11')
    
    # Local pings to register MACs in respective domain controllers
    h4.cmd(f'ping -c 1 -W 1 {h3.IP()}')
    h9.cmd(f'ping -c 1 -W 1 {h10.IP()}')
    h1.cmd(f'ping -c 1 -W 1 {h2.IP()}')
    h11.cmd(f'ping -c 1 -W 1 {h10.IP()}')
    
    log.info('Configuring static ARP for test hosts...')
    h4.cmd(f'arp -s {h9.IP()} {h9.MAC()}')
    h9.cmd(f'arp -s {h4.IP()} {h4.MAC()}')
    h1.cmd(f'arp -s {h11.IP()} {h11.MAC()}')
    h11.cmd(f'arp -s {h1.IP()} {h1.MAC()}')

    log.info('Waiting 10s for EW sync of pre-warmed hosts...')
    time.sleep(10)

    try:
        if args.mode == 'both':
            # Note: TE mode is determined by the controller's TE_ENABLED env var.
            # The test script just records which path was taken.
            log.info('Running TE trial (ensure controllers have TE_ENABLED=1)...')
            te_m = run_trial(net, 'te')
            log.info('')
            log.info('NOTE: Restart controllers with TE_ENABLED=0, then press Enter.')
            input()
            log.info('Running baseline trial...')
            bl_m = run_trial(net, 'baseline')
            compare_trials(te_m, bl_m)
            print_summary('both')

        elif args.mode == 'te':
            te_m = run_trial(net, 'te')
            log.info('  TE throughput: %s Mbps', te_m.get('throughput_mbps'))
            log.info('  Path taken:    %s', te_m.get('path_used'))
            log.info('  Used direct:   %s', te_m.get('used_direct'))

            # Fail-fast: run_trial may return early if the saturation sanity check failed.
            if te_m.get('fail_fast'):
                results['te_experiment'] = FAIL
                log.error('  FAIL: Aborted early — %s', te_m['fail_fast'])
                print_summary('te')
            else:
                throughput  = te_m.get('throughput_mbps')
                decisions   = te_m.get('te_decisions', 0)
                used_direct = te_m.get('used_direct')
                utils_during = te_m.get('utils_during', {})

                # Congestion check: util_rates from /linkstate are dicts
                # {dpid_str: {port_str: {ratio, bps_tx, bps_rx}}}
                CONGESTED_PORTS = {'s3:p4', 's7:p4'}
                congested = False
                for domain, dpid_map in utils_during.items():
                    if not isinstance(dpid_map, dict):
                        continue
                    for dpid_str, port_map in dpid_map.items():
                        if not isinstance(port_map, dict):
                            continue
                        for port_str, pdata in port_map.items():
                            port_key = f's{dpid_str}:p{port_str}'
                            if port_key in CONGESTED_PORTS:
                                try:
                                    if isinstance(pdata, dict):
                                        pct = pdata.get('ratio', 0) * 100
                                    else:
                                        pct = float(str(pdata).replace('%', ''))
                                    if pct > 50.0:
                                        congested = True
                                        log.info('  Congested link verification: %s = %.1f%%', port_key, pct)
                                except (ValueError, TypeError):
                                    pass

                if throughput is None or throughput == 0.0:
                    results['te_experiment'] = FAIL
                    log.error('  FAIL: No throughput measured.')
                elif not congested:
                    results['te_experiment'] = FAIL
                    log.error('  FAIL: End-of-trial validation detected NO congestion on diagonal links.')
                elif decisions == 0:
                    results['te_experiment'] = FAIL
                    log.error('  FAIL: Harness detected 0 TE decisions in te_decisions.log. Check path selector.')
                elif used_direct is None or used_direct:
                    results['te_experiment'] = FAIL
                    log.error('  FAIL: TE did not divert the flow; expected alternate path was not used (used direct).')
                else:
                    results['te_experiment'] = PASS
                    log.info('  PASS: Successfully rerouted congested flow.')

                print_summary('te')


        else:  # baseline
            bl_m = run_trial(net, 'baseline')
            log.info('  Baseline throughput: %s Mbps', bl_m.get('throughput_mbps'))
            log.info('  Path taken:          %s', bl_m.get('path_used'))
            results['te_experiment'] = PASS  # baseline always "passes"
            print_summary('baseline')

    finally:
        net.stop()
        for h in log.handlers:
            h.flush(); h.close()
        print(f'\n[OK] Log: {LOG_FILE}')
        print(f'[OK] TE decisions: {TE_DEC_LOG}')


if __name__ == '__main__':
    main()
