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
  1. Start iperf3 server on h12 (Domain C)
  2. Saturate the DIRECT path (s3→s7, A↔C diagonal) with iperf3 from h1
     for 30s  (background traffic)
  3. Start a NEW iperf3 flow from h2 → h12 for 20s
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
STATS_WARMUP      = 12    # s: wait for 2x PortStats cycles (interval=5s) before reading utils
SATURATE_DURATION = 30    # s: background iperf3 duration (saturates congested path)
NEW_FLOW_DURATION = 20    # s: new flow iperf3 duration
IPERF_PORT_SAT    = 5201  # saturation flow server port
IPERF_PORT_NEW    = 5202  # new flow server port (separate, avoids "server busy" error)
HTTP_TIMEOUT      = 4

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


def read_last_te_decisions(n: int = 5) -> list[dict]:
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
    host.cmd(f'pkill -f "iperf3 -s -p {port}" 2>/dev/null; sleep 0.3')
    host.cmd(f'iperf3 -s -p {port} -D --logfile /tmp/iperf_server_{port}.log')
    time.sleep(0.3)
    log.info('  iperf3 server started on %s (%s) port=%d', host.name, host.IP(), port)


def run_iperf_client(src_host, dst_host, duration: int,
                     output_file: str, port: int = IPERF_PORT_SAT,
                     bitrate: str = '0') -> None:
    """
    Run iperf3 client from src to dst for `duration` seconds.
    Results written to output_file as JSON.
    """
    dst_ip = dst_host.IP()
    cmd = (f'iperf3 -c {dst_ip} -p {port} -t {duration} '
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
        bps = data['end']['sum_received']['bits_per_second']
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

    h1  = net.get('h1')    # Domain A — saturation source
    h2  = net.get('h2')    # Domain A — new flow source
    h12 = net.get('h12')   # Domain C — destination

    # Start TWO iperf3 server instances on h12 (different ports to avoid
    # "server busy" rejection when both h1 and h2 connect simultaneously)
    run_iperf_server(h12, IPERF_PORT_SAT)
    run_iperf_server(h12, IPERF_PORT_NEW)

    # ── Step 1: Wait for PortStats warmup then snapshot baseline ──────────
    log.info('Waiting %ds for PortStats warmup (2 x %ds interval)...',
             STATS_WARMUP, 5)
    time.sleep(STATS_WARMUP)
    log.info('Snapshotting baseline link utilizations...')
    utils_before = snapshot_link_utils('before')

    # ── Step 2: Saturate direct A↔C path with h1→h12 background traffic ──
    section(f'Saturating {CONGESTED_LINK} for {SATURATE_DURATION}s')
    sat_file = f'/tmp/iperf_sat_{mode}.json'

    def _saturate():
        run_iperf_client(h1, h12, SATURATE_DURATION, sat_file,
                         port=IPERF_PORT_SAT, bitrate='8M')

    sat_thread = threading.Thread(target=_saturate, daemon=True)
    sat_thread.start()

    # Wait for saturation to take effect + at least one PortStats cycle (5s)
    wait_sat = max(SATURATE_DURATION // 2, 10)
    log.info('  Waiting %ds for saturation to take effect...', wait_sat)
    time.sleep(wait_sat)

    # ── Step 3: Snapshot utilization under load ───────────────────────────
    utils_during = snapshot_link_utils('during saturation')

    # ── Step 4: Start new flow h2 → h12 on SEPARATE port ─────────────────
    section(f'Starting NEW flow h2→h12 ({NEW_FLOW_DURATION}s)')
    te_decisions_before = len(read_last_te_decisions(100))

    new_flow_file = f'/tmp/iperf_new_{mode}.json'
    run_iperf_client(h2, h12, NEW_FLOW_DURATION, new_flow_file,
                     port=IPERF_PORT_NEW)

    # ── Step 5: Wait for saturation to finish ────────────────────────────
    sat_thread.join(timeout=SATURATE_DURATION + 5)

    # ── Step 6: Collect results ───────────────────────────────────────────
    throughput = parse_iperf_throughput(new_flow_file)
    log.info('  New flow throughput: %s Mbps', throughput)

    # Get TE decision records
    all_decisions = read_last_te_decisions(100)
    new_decisions = all_decisions[te_decisions_before:]
    log.info('  TE decisions during trial: %d', len(new_decisions))
    for d in new_decisions[-3:]:
        log.info('    flow=%s  path=%s  max_util=%.1f%%  trigger=%s',
                 d.get('flow_id', '?'),
                 '→'.join(d.get('path', [])),
                 d.get('max_util', 0) * 100,
                 d.get('trigger', '?'))

    # ── Step 7: Dump flow tables on boundary switches ─────────────────────
    section('Flow table dump (s3, s4, s6, s7)')
    flows = dump_switch_flows(net, ['s3', 's4', 's6', 's7'])
    for sw, table in flows.items():
        log.info('[%s flows]\n%s', sw, table[:600])

    # ── Step 8: Check if new flow avoided congested path (TE case) ────────
    path_used = None
    for d in reversed(new_decisions):
        if d.get('src_dpid') in (1, 2):  # h2 connects to s1 or s2
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
    h12.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_SAT}" 2>/dev/null')
    h12.cmd(f'pkill -f "iperf3 -s -p {IPERF_PORT_NEW}" 2>/dev/null')
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

    # Verdict
    if te_avoided and te_tp > bl_tp:
        log.info('  🎉 TE VERIFIED — rerouted AND achieved higher throughput')
        results['te_experiment'] = PASS
    elif te_avoided:
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

    log.info('Enabling RSTP (30s)...')
    enable_rstp(net, wait=30)

    log.info('Assigning controllers...')
    assign_controllers(net)

    if not wait_for_switches(net, timeout=60):
        log.warning('Proceeding despite some disconnected switches.')

    if not check_iperf3_available(net):
        net.stop()
        sys.exit(1)

    log.info('Waiting %ds for EW sync convergence...', SYNC_WAIT)
    time.sleep(SYNC_WAIT)

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
            results['te_experiment'] = (
                PASS if not te_m.get('used_direct') else WARN)
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
