#!/usr/bin/env python3
"""
experiments/phase3_test.py
---------------------------
Phase 3 verification: East-West protocol + inter-domain connectivity.

Checks
──────
  [1] All 3 controller REST APIs reachable (GET /topology returns 200)
  [2] Switches connected to correct controller ports (inherited from Phase 2)
  [3] EW sync has converged: each controller's /topology lists switches from all
      3 domains (global view populated)
  [4] Intra-domain pings succeed (regression from Phase 2)
  [5] Inter-domain pings now SUCCEED (key Phase 3 milestone)
  [6] eastwest_traffic.log shows messages between all controller pairs
  [7] Global view switch count = 9, inter-link count = 3 (matches real topology)

Run:
    # Start all 3 EW controllers first (3 terminals), then:
    sudo python3 experiments/phase3_test.py

Controller launch commands (copy to separate terminals):
    DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 \\
        ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6633

    DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 EW_API_PORT=8081 \\
        ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6634

    DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 EW_API_PORT=8082 \\
        ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6653
"""

import os
import re
import sys
import json
import time
import logging
import socket
import threading
from datetime import datetime
from itertools import combinations

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(RESULTS_DIR, 'phase3_ew.log')

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

log = logging.getLogger('phase3_test')
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Mininet + topology imports ────────────────────────────────────────────────
from mininet.log import setLogLevel

from topology.multi_domain_topo import (
    build_network, assign_controllers, enable_rstp,
    DOMAIN_HOSTS, HOST_DOMAIN, SWITCH_CTRL_PORT,
    CTRL_A_PORT, CTRL_B_PORT, CTRL_C_PORT,
)

# ── EW API config ─────────────────────────────────────────────────────────────
EW_PORTS = {'A': 8080, 'B': 8081, 'C': 8082}
EW_HOST  = '127.0.0.1'
EW_LOG   = os.path.join(RESULTS_DIR, 'eastwest_traffic.log')

CONNECT_WAIT  = 20    # s: max wait for switch→controller connections
SYNC_WAIT     = 15    # s: time to allow at least 2 sync rounds after connect
PING_TIMEOUT  = 3     # s: per-ping timeout (longer than Phase 2 — inter-domain latency)
HTTP_TIMEOUT  = 4     # s: per REST call timeout

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


def ew_get(domain: str, endpoint: str) -> dict | None:
    url = f'http://{EW_HOST}:{EW_PORTS[domain]}{endpoint}'
    try:
        resp = requests.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        log.warning('  GET %s → HTTP %d', url, resp.status_code)
    except Exception as exc:
        log.warning('  GET %s → %s', url, exc)
    return None


def ping_pair(src_host, dst_host, timeout=PING_TIMEOUT) -> bool:
    """Returns True if at least one of 3 pings is received."""
    result = src_host.cmd(f'ping -c 3 -W {timeout} {dst_host.IP()}')
    match  = re.search(r'(\d+)\s+(?:packets\s+)?received', result)
    return bool(match and int(match.group(1)) > 0)


def wait_for_all_switches(net, timeout: int = CONNECT_WAIT) -> bool:
    log.info('Waiting for all 9 switches to connect (max %ds)...', timeout)
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


# ── Check 1: EW REST API reachability ─────────────────────────────────────────

def check_ew_apis():
    section('CHECK 1 — EW REST API reachability (GET /topology)')
    all_ok = True
    for domain, port in EW_PORTS.items():
        data = ew_get(domain, '/topology')
        ok   = data is not None
        log.info('  Domain %s  port=%d  %s', domain, port,
                 '✓' if ok else '✗ NOT REACHABLE')
        if not ok:
            all_ok = False
    results['ew_api'] = PASS if all_ok else FAIL
    log.info('Result: %s', results['ew_api'])
    return all_ok


# ── Check 2: Switch assignment (inherited from Phase 2) ───────────────────────

def check_switch_assignment(net):
    section('CHECK 2 — Switch→controller port assignment')
    all_ok = True
    for sw in net.switches:
        raw  = sw.cmd(f'ovs-vsctl get-controller {sw.name}').strip()
        port = SWITCH_CTRL_PORT[sw.name]
        ok   = str(port) in raw
        log.info('  %-4s  %s  %s', sw.name, raw[:40], '✓' if ok else '✗ WRONG')
        if not ok:
            all_ok = False
    results['switch_assignment'] = PASS if all_ok else FAIL
    log.info('Result: %s', results['switch_assignment'])


# ── Check 3: EW sync convergence ──────────────────────────────────────────────

def check_ew_convergence():
    section('CHECK 3 — EW sync convergence (global view populated)')
    all_ok = True
    for domain in EW_PORTS:
        data = ew_get(domain, '/globalview')
        if data is None:
            log.error('  Domain %s: /globalview unreachable', domain)
            all_ok = False
            continue

        sw_count    = len(data.get('switches', {}))
        inter_count = len(data.get('inter_links', []))
        peer_meta   = data.get('peer_meta', {})
        peers_seen  = list(peer_meta.keys())

        ok = sw_count >= 9 and inter_count >= 3
        log.info('  Domain %s  switches=%d  inter_links=%d  peers_seen=%s  %s',
                 domain, sw_count, inter_count, peers_seen,
                 '✓' if ok else '✗ INCOMPLETE')

        # Dump global view to log for manual verification
        log.debug('  [Domain %s] global_view=%s', domain,
                  json.dumps(data, indent=2)[:800])

        if not ok:
            all_ok = False

    results['ew_convergence'] = PASS if all_ok else WARN
    log.info('Result: %s', results['ew_convergence'])


# ── Check 4: Intra-domain pings (regression) ──────────────────────────────────

def check_intra_pings(net):
    section('CHECK 4 — Intra-domain pings (regression from Phase 2)')
    passed = failed = 0
    for domain, hosts in DOMAIN_HOSTS.items():
        host_objs = [net.get(h) for h in hosts]
        for h_src, h_dst in combinations(host_objs, 2):
            ok = ping_pair(h_src, h_dst)
            log.info('  [Domain %s] %-5s → %-5s  %s',
                     domain, h_src.name, h_dst.name, '✓' if ok else '✗')
            if ok:
                passed += 1
            else:
                failed += 1

    log.info('  Intra: %d passed, %d failed', passed, failed)
    results['intra_ping'] = PASS if failed == 0 else (WARN if passed > failed else FAIL)
    log.info('Result: %s', results['intra_ping'])


# ── Check 5: Inter-domain pings (KEY MILESTONE) ───────────────────────────────

def check_inter_pings(net):
    section('CHECK 5 — Inter-domain pings (KEY Phase 3 MILESTONE)')
    log.info('  (waiting 2s for flow installation to settle...)')
    time.sleep(2)

    all_hosts = [net.get(h) for domain in DOMAIN_HOSTS.values() for h in domain]
    passed = failed = 0
    failures = []

    for h_src, h_dst in combinations(all_hosts, 2):
        if HOST_DOMAIN[h_src.name] == HOST_DOMAIN[h_dst.name]:
            continue   # skip intra-domain pairs

        ok = ping_pair(h_src, h_dst)
        d_src = HOST_DOMAIN[h_src.name]
        d_dst = HOST_DOMAIN[h_dst.name]
        log.info('  [%s↔%s] %-5s → %-5s  %s',
                 d_src, d_dst, h_src.name, h_dst.name, '✓ OK' if ok else '✗ FAIL')
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append(f'{h_src.name}→{h_dst.name}')

    log.info('')
    log.info('  Inter-domain: %d passed, %d failed', passed, failed)

    if failed == 0:
        results['inter_ping'] = PASS
        log.info('  🎉 ALL inter-domain pings succeeded — E-W forwarding WORKS!')
    elif passed > failed:
        results['inter_ping'] = WARN
        log.warning('  Partial success. Failures: %s', failures)
    else:
        results['inter_ping'] = FAIL
        log.error('  Most inter-domain pings FAILED. E-W sync may not have converged.')
        log.error('  Failed pairs: %s', failures)

    log.info('Result: %s', results['inter_ping'])


# ── Check 6: EW traffic log ───────────────────────────────────────────────────

def check_ew_traffic_log():
    section('CHECK 6 — eastwest_traffic.log integrity')
    if not os.path.exists(EW_LOG):
        log.error('  %s not found', EW_LOG)
        results['ew_log'] = FAIL
        return

    with open(EW_LOG) as f:
        lines = [l for l in f if l.strip()]

    send_count = sum(1 for l in lines if 'SEND' in l)
    recv_count = sum(1 for l in lines if 'RECV' in l)
    err_count  = sum(1 for l in lines if 'ERR' in l)

    # Check all 3 domain pairs appear
    pairs_seen = set()
    for l in lines:
        if 'src=' in l and 'dst=' in l:
            try:
                src = l.split('src=')[1].split()[0].strip()
                dst = l.split('dst=')[1].split()[0].strip()
                if src != '*' and dst != '*':
                    pairs_seen.add(frozenset([src, dst]))
            except IndexError:
                pass

    expected_pairs = {frozenset(['A', 'B']), frozenset(['B', 'C']), frozenset(['A', 'C'])}
    missing_pairs  = expected_pairs - pairs_seen

    log.info('  Total lines: %d  (SEND=%d, RECV=%d, ERR=%d)',
             len(lines), send_count, recv_count, err_count)
    log.info('  Controller pairs in log: %s',
             [sorted(p) for p in pairs_seen])

    if missing_pairs:
        log.warning('  Missing pairs: %s', [sorted(p) for p in missing_pairs])
        results['ew_log'] = WARN
    else:
        results['ew_log'] = PASS

    # Show last 10 lines
    log.info('  Last 10 EW log entries:')
    for l in lines[-10:]:
        log.info('    %s', l.rstrip())

    log.info('Result: %s', results['ew_log'])


# ── Check 7: Global view accuracy ─────────────────────────────────────────────

def check_global_view_accuracy():
    section('CHECK 7 — Global view accuracy (switch count, inter-link count)')
    # Authoritative counts from the topology definition
    EXPECTED_SWITCHES    = 9
    EXPECTED_INTER_LINKS = 3

    all_ok = True
    for domain in EW_PORTS:
        data = ew_get(domain, '/globalview')
        if data is None:
            log.error('  Domain %s: unreachable', domain)
            all_ok = False
            continue

        sw_count    = len(data.get('switches', {}))
        inter_count = len(data.get('inter_links', []))

        sw_ok    = sw_count >= EXPECTED_SWITCHES
        il_ok    = inter_count >= EXPECTED_INTER_LINKS

        log.info('  Domain %s  switches=%d/%d %s  inter_links=%d/%d %s',
                 domain,
                 sw_count, EXPECTED_SWITCHES, '✓' if sw_ok else '✗',
                 inter_count, EXPECTED_INTER_LINKS, '✓' if il_ok else '✗')

        if not (sw_ok and il_ok):
            all_ok = False

    results['global_view'] = PASS if all_ok else WARN
    log.info('Result: %s', results['global_view'])


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary():
    banner('PHASE 3 EAST-WEST PROTOCOL SUMMARY')
    checks = [
        ('ew_api',           'EW REST API reachable on all 3 controllers'),
        ('switch_assignment','Switches connected to correct controller ports'),
        ('ew_convergence',   'EW sync converged — global view populated'),
        ('intra_ping',       'Intra-domain pings succeed (regression check)'),
        ('inter_ping',       'Inter-domain pings succeed (KEY MILESTONE)'),
        ('ew_log',           'eastwest_traffic.log shows all controller pairs'),
        ('global_view',      'Global view matches real topology (9sw, 3 inter-links)'),
    ]
    passed = warned = failed = 0
    for key, desc in checks:
        r = results.get(key, '❓ NOT RUN')
        log.info('  %s  %s', r, desc)
        if 'PASS'  in r: passed += 1
        elif 'FAIL' in r: failed += 1
        else:              warned += 1

    log.info('')
    log.info('  Passed: %d  │  Warnings: %d  │  Failed: %d  │  Total: %d',
             passed, warned, failed, len(checks))
    log.info('  Phase 3 log: %s', LOG_FILE)
    log.info('  EW traffic:  %s', EW_LOG)

    if failed == 0 and results.get('inter_ping') == PASS:
        log.info('')
        log.info('  🎉 Phase 3 VERIFIED — E-W protocol working, ready for Phase 4 (attacks)')
    elif failed == 0:
        log.info('')
        log.info('  ⚠️  Phase 3 mostly done — inter-domain ping not fully passing yet')
    else:
        log.error('')
        log.error('  ⛔ %d check(s) FAILED — review logs above', failed)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if os.geteuid() != 0:
        print('[ERROR] Run with sudo.', file=sys.stderr)
        sys.exit(1)

    banner(f'Phase 3 East-West Test — {datetime.now().isoformat()}')

    # ── Pre-flight: check EW APIs are up ────────────────────────────────────
    if not check_ew_apis():
        log.error('Start all 3 EW controllers first (see docstring for commands).')
        sys.exit(1)

    # ── Build and start Mininet ──────────────────────────────────────────────
    setLogLevel('warning')
    net = build_network()

    log.info('Starting network...')
    net.start()

    log.info('Enabling RSTP (30s convergence wait)...')
    enable_rstp(net, wait=30)

    log.info('Assigning switches to controllers...')
    assign_controllers(net)

    if not wait_for_all_switches(net, timeout=60):
        log.warning('Proceeding despite some switches not connected.')

    # NOTE: Do NOT call isolate_domains() here — Phase 3 uses EW forwarding
    # instead of hard drops.  The EW controller itself manages the inter-domain
    # boundary by consulting global_topology before installing flow rules.

    log.info('Waiting %ds for EW sync to converge across all peers...', SYNC_WAIT)
    time.sleep(SYNC_WAIT)

    try:
        check_switch_assignment(net)
        check_ew_convergence()

        # Warm-up: run intra-domain pings first to seed MAC tables
        log.info('Warming up MAC tables with intra-domain pings...')
        check_intra_pings(net)

        # Give EW agents time to propagate learned hosts across domains
        log.info('Waiting 10s for EW agents to propagate host MAC info...')
        time.sleep(10)

        # KEY CHECK: inter-domain connectivity
        check_inter_pings(net)

        # Diagnostic checks
        check_ew_traffic_log()
        check_global_view_accuracy()

    finally:
        print_summary()
        net.stop()
        for h in log.handlers:
            h.flush(); h.close()
        print(f'\n[OK] Log: {LOG_FILE}')
        print(f'[OK] EW traffic log: {EW_LOG}')


if __name__ == '__main__':
    main()
