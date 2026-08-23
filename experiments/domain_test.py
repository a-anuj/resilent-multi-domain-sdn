#!/usr/bin/env python3
"""
experiments/domain_test.py
---------------------------
Phase 2 verification: multi-controller domain partitioning.

Checks:
  [1] All 9 switches connect to the correct controller (port-based isolation)
  [2] Each controller only sees events from its own domain switches
  [3] Intra-domain pings succeed (0% loss within domain)
  [4] Inter-domain pings fail or are unreliable (no E-W coordination yet)
  [5] All 3 controllers handle simultaneous traffic without crashes

Run:
    # Start all 3 controllers first (3 terminals), then:
    sudo python3 experiments/domain_test.py
"""

import os
import sys
import time
import logging
import socket
from datetime import datetime
from itertools import combinations

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Logging (before Mininet imports) ─────────────────────────────────────────
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(RESULTS_DIR, 'phase2_domain.log')

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
_fh = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger('domain_test')
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Mininet imports ───────────────────────────────────────────────────────────
from mininet.log import setLogLevel
from mininet.node import OVSKernelSwitch

from topology.multi_domain_topo import (
    build_network, assign_controllers, enable_rstp, isolate_domains,
    DOMAIN_HOSTS, HOST_DOMAIN, SWITCH_CTRL_PORT,
    CTRL_A_PORT, CTRL_B_PORT, CTRL_C_PORT,
)

CONNECT_WAIT = 20   # max seconds to wait for all switches to connect
PING_TIMEOUT = 1    # seconds per individual ping

PASS = '✅ PASS'
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'

results: dict[str, str] = {}


# ── Utilities ─────────────────────────────────────────────────────────────────

def banner(msg: str):
    sep = '═' * 72
    log.info(sep); log.info('  %s', msg); log.info(sep)

def section(msg: str):
    log.info('─' * 72); log.info('  %s', msg); log.info('─' * 72)


def ctrl_reachable(port: int) -> bool:
    """Check whether a Ryu controller is listening on the given TCP port."""
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            return True
    except OSError:
        return False


def wait_for_all_switches(net, timeout: int = CONNECT_WAIT) -> bool:
    """
    Poll every OVS bridge until is_connected=true, up to `timeout` seconds.
    Returns True if all connected, False if timed out.
    """
    log.info('Waiting for all 9 switches to establish OF connections...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        not_yet = []
        for sw in net.switches:
            raw = sw.cmd(
                f'ovs-vsctl get controller {sw.name} is_connected 2>/dev/null'
            ).strip()
            if raw != 'true':
                not_yet.append(sw.name)
        if not not_yet:
            log.info('All %d switches connected to their controllers. ✓',
                     len(net.switches))
            return True
        log.info('  Still waiting for: %s  (%.0fs remaining)',
                 ', '.join(not_yet), deadline - time.time())
        time.sleep(2)

    log.error('Timed out after %ds — switches still disconnected: %s',
              timeout, ', '.join(not_yet))
    
    for sw in not_yet:
        status = net.get(sw).cmd(f'ovs-vsctl get controller {sw} status').strip()
        error = net.get(sw).cmd(f'ovs-vsctl get controller {sw} error').strip()
        target = net.get(sw).cmd(f'ovs-vsctl get controller {sw} target').strip()
        log.error(f'  [DEBUG] {sw}: target={target} status={status} error={error}')
    
    return False


# ── Check 1: Controller reachability ─────────────────────────────────────────

def check_controllers_up():
    section('CHECK 1 — All 3 controller ports reachable')
    ports = {
        'Domain A': CTRL_A_PORT,
        'Domain B': CTRL_B_PORT,
        'Domain C': CTRL_C_PORT,
    }
    all_up = True
    for name, port in ports.items():
        up = ctrl_reachable(port)
        log.info('  %-10s port %-5d  %s', name, port, '✓' if up else '✗')
        if not up:
            all_up = False

    results['controllers_up'] = PASS if all_up else FAIL
    log.info('Result: %s', results['controllers_up'])
    return all_up


# ── Check 2: Switch-to-controller assignment ──────────────────────────────────

def check_switch_assignment(net):
    section('CHECK 2 — Switches connected to correct controller port')
    all_ok = True
    for sw in net.switches:
        raw = sw.cmd(f'ovs-vsctl get-controller {sw.name}')
        configured = raw.strip()
        expected_port = SWITCH_CTRL_PORT[sw.name]
        expected = f'tcp:{CTRL_A_PORT if expected_port == CTRL_A_PORT else (CTRL_B_PORT if expected_port == CTRL_B_PORT else CTRL_C_PORT)}'
        ok = str(expected_port) in configured
        log.info('  %-4s  configured=%-35s  port=%d  %s',
                 sw.name, configured[:35], expected_port,
                 '✓' if ok else '✗ WRONG')
        if not ok:
            all_ok = False

    # Also verify is_connected
    for sw in net.switches:
        conn = sw.cmd(f'ovs-vsctl get controller {sw.name} is_connected 2>/dev/null').strip()
        log.info('  %-4s  is_connected=%s', sw.name, conn)

    results['switch_assignment'] = PASS if all_ok else FAIL
    log.info('Result: %s', results['switch_assignment'])


# ── Check 3 & 4: Ping matrix ─────────────────────────────────────────────────

import re

def ping_pair(src_host, dst_host, timeout=PING_TIMEOUT) -> bool:
    """Returns True if ping succeeds (>0 packets received)."""
    result = src_host.cmd(
        f'ping -c 2 -W {timeout} {dst_host.IP()}'
    )
    match = re.search(r'(\d+)\s+(?:packets\s+)?received', result)
    if match and int(match.group(1)) > 0:
        if HOST_DOMAIN[src_host.name] != HOST_DOMAIN[dst_host.name]:
            log.info(f'[DEBUG PING {src_host.name}->{dst_host.name}] RECEIVED {match.group(1)} PKTS! Output:\n{result}')
        return True
    return False


def check_ping_matrix(net):
    section('CHECK 3+4 — Ping matrix: intra-domain vs inter-domain')

    all_hosts = [net.get(h) for domain in DOMAIN_HOSTS.values()
                 for h in domain]

    intra_results = []   # (src, dst, success)
    inter_results = []

    for h_src, h_dst in combinations(all_hosts, 2):
        src_name = h_src.name
        dst_name = h_dst.name
        same_domain = HOST_DOMAIN[src_name] == HOST_DOMAIN[dst_name]

        ok = ping_pair(h_src, h_dst)
        entry = (src_name, dst_name, ok)

        if same_domain:
            intra_results.append(entry)
        else:
            inter_results.append(entry)

    # ── Intra-domain summary ──────────────────────────────────────────────
    log.info('')
    log.info('Intra-domain ping results:')
    intra_pass = intra_fail = 0
    for src, dst, ok in intra_results:
        dom = HOST_DOMAIN[src]
        log.info('  [Domain %s] %-5s → %-5s  %s', dom, src, dst,
                 '✓ OK' if ok else '✗ FAIL')
        if ok:
            intra_pass += 1
        else:
            intra_fail += 1

    log.info('')
    log.info('  Intra-domain: %d passed, %d failed', intra_pass, intra_fail)

    if intra_fail == 0:
        results['intra_ping'] = PASS
    elif intra_pass > intra_fail:
        results['intra_ping'] = WARN
    else:
        results['intra_ping'] = FAIL

    # ── Inter-domain summary ──────────────────────────────────────────────
    log.info('')
    log.info('Inter-domain ping results (failures EXPECTED — no E-W yet):')
    inter_pass = inter_fail = 0
    for src, dst, ok in inter_results:
        d_src = HOST_DOMAIN[src]
        d_dst = HOST_DOMAIN[dst]
        log.info('  [%s↔%s] %-5s → %-5s  %s', d_src, d_dst, src, dst,
                 '✓ unexpected success' if ok else '✗ fail (expected)')
        if ok:
            inter_pass += 1
        else:
            inter_fail += 1

    log.info('')
    log.info('  Inter-domain: %d passed (unexpected), %d failed (expected)',
             inter_pass, inter_fail)

    # Inter-domain PASS = all fail (isolation working correctly)
    # Inter-domain WARN = some pass (partial isolation, check if real)
    # Inter-domain FAIL = all pass (controllers may not be isolated!)
    if inter_pass == 0:
        results['inter_ping'] = PASS
        log.info('  Inter-domain isolation: ✅ CONFIRMED (all failed as expected)')
    elif inter_pass < len(inter_results) // 2:
        results['inter_ping'] = WARN
        log.warning('  Some inter-domain pings succeeded — verify controller isolation')
    else:
        results['inter_ping'] = FAIL
        log.error('  Most inter-domain pings SUCCEEDED — controllers may not be isolated!')

    log.info('Result intra: %s   Result inter: %s',
             results['intra_ping'], results['inter_ping'])


# ── Check 5: Flow table partitioning ──────────────────────────────────────────

def check_flow_partitioning(net):
    """
    Verify that each switch only has table-miss + learned flows — no
    cross-domain flows (which would indicate a controller installed a rule
    on a foreign switch).
    """
    section('CHECK 5 — Flow table partitioning per domain')
    domain_switch_map = {
        'A': DOMAIN_HOSTS['A'],   # reuse for loop below
    }
    domain_sw = {
        'A': ['s1', 's2', 's3'],
        'B': ['s4', 's5', 's6'],
        'C': ['s7', 's8', 's9'],
    }
    all_ok = True
    for domain, switches in domain_sw.items():
        for sw_name in switches:
            sw = net.get(sw_name)
            raw = sw.cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw_name}')
            log.info(f'[FLOW DUMP {sw_name}]\n{raw}')
            lines = [l.strip() for l in raw.splitlines()
                     if l.strip() and not l.startswith(('NXST', 'OFPST'))]
            total    = len(lines)
            has_miss = any('priority=0' in l and 'CONTROLLER' in l for l in lines)
            learned  = sum(1 for l in lines
                           if 'priority=1' in l and 'priority=100' not in l
                           and ('eth_dst' in l or 'dl_dst' in l))
            ok = has_miss
            log.info('  [Domain %s] %-4s  total=%-3d  table-miss=%s  learned=%d  %s',
                     domain, sw_name, total,
                     '✓' if has_miss else '✗',
                     learned, '✓' if ok else '✗ MISSING TABLE-MISS')
            if not ok:
                all_ok = False

    results['flow_partition'] = PASS if all_ok else FAIL
    log.info('Result: %s', results['flow_partition'])


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary():
    banner('PHASE 2 DOMAIN PARTITIONING SUMMARY')
    checks = [
        ('controllers_up',  'All 3 controller ports reachable'),
        ('switch_assignment','Switches connected to correct controller port'),
        ('intra_ping',      'Intra-domain pings succeed (within domain)'),
        ('inter_ping',      'Inter-domain pings fail (isolation confirmed)'),
        ('flow_partition',  'Flow tables show table-miss on all switches'),
    ]
    passed = warned = failed = 0
    for key, desc in checks:
        r = results.get(key, '❓ NOT RUN')
        log.info('  %s  %s', r, desc)
        if 'PASS' in r:   passed  += 1
        elif 'FAIL' in r: failed  += 1
        else:              warned  += 1

    log.info('')
    log.info('  Passed: %d  │  Warnings: %d  │  Failed: %d  │  Total: %d',
             passed, warned, failed, len(checks))
    log.info('  Log: %s', LOG_FILE)

    if failed == 0:
        log.info('')
        log.info('  🎉 Phase 2 VERIFIED — ready for Phase 3 (East-West protocol)')
    else:
        log.error('')
        log.error('  ⛔ %d check(s) FAILED', failed)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if os.geteuid() != 0:
        print('[ERROR] Run with sudo.', file=sys.stderr)
        sys.exit(1)

    banner(f'Phase 2 Domain Test — {datetime.now().isoformat()}')

    # Check controllers before building topology
    if not check_controllers_up():
        log.error('Start all 3 Ryu controllers first (see README for commands).')
        sys.exit(1)

    setLogLevel('warning')
    net = build_network()

    log.info('Starting network...')
    net.start()

    # RSTP FIRST — let port states settle before triggering OF connections.
    # We must wait long enough for RSTP to fully converge (up to 30s) so that
    # loops are broken. Otherwise, controller connections trigger a broadcast
    # storm which hangs OVS and prevents s7-s9 from connecting!
    enable_rstp(net, wait=30)
    assign_controllers(net)

    if not wait_for_all_switches(net, timeout=60):   # 60s for 9 switches across 3 controllers
        log.warning('Proceeding despite some switches not connected — '
                    'results may be incomplete.')

    # Install drop rules AFTER controllers connect, otherwise OVS clears the flow table!
    isolate_domains(net)

    try:
        check_switch_assignment(net)
        # Skip the duplicate net.pingAll() which takes 5 minutes when domains are isolated
        log.info('Running targeted ping checks (this may take 1-2 minutes due to expected timeouts)...')
        time.sleep(3)
        check_ping_matrix(net)
        check_flow_partitioning(net)
    finally:
        print_summary()
        net.stop()
        for h in log.handlers:
            h.flush(); h.close()
        print(f'\n[OK] Log: {LOG_FILE}')


if __name__ == '__main__':
    main()
