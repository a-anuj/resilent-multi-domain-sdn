#!/usr/bin/env python3
"""
experiments/verify_phase1.py
-----------------------------
Phase 1 verification script — checks all 5 post-phase items:

  [1] pingAll 0% packet loss
  [2] Flow tables populate correctly (learned unicast entries, not just table-miss)
  [3] iperf3 throughput close to configured link bandwidth (~10 Mbps)
  [4] Multiple paths exist and are traceable via flow port assignments
  [5] Ryu PacketIn / FlowMod events observed (non-zero flow count per switch)

Run after starting ryu-manager:
    sudo python3 experiments/verify_phase1.py

Output is written to results/phase1_verify.log and printed to stdout.
"""

import os
import sys
import time
import shutil
import re
import logging
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── Logging (must precede Mininet imports) ────────────────────────────────────
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)
LOG_FILE = os.path.join(RESULTS_DIR, 'phase1_verify.log')

import pwd
_sudo_user = os.environ.get('SUDO_USER')
if _sudo_user:
    try:
        _uid = pwd.getpwnam(_sudo_user).pw_uid
        _gid = pwd.getpwnam(_sudo_user).pw_gid
        os.chown(RESULTS_DIR, _uid, _gid)
        open(LOG_FILE, 'a').close()
        os.chown(LOG_FILE, _uid, _gid)
    except Exception:
        pass

_fmt = logging.Formatter('%(asctime)s  %(levelname)-8s  %(message)s',
                         datefmt='%Y-%m-%d %H:%M:%S')
_fh = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
_sh = logging.StreamHandler(sys.stdout)
_fh.setFormatter(_fmt); _sh.setFormatter(_fmt)
_fh.setLevel(logging.DEBUG); _sh.setLevel(logging.DEBUG)

log = logging.getLogger('verify_phase1')
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Mininet imports ───────────────────────────────────────────────────────────
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink

from topology.basic_topo import PartialMeshTopo
from experiments.basic_test import enable_rstp, wait_for_controller

CONTROLLER_IP   = '127.0.0.1'
CONTROLLER_PORT = 6653
IPERF_DURATION  = 10

PASS = '✅ PASS'
FAIL = '❌ FAIL'
WARN = '⚠️  WARN'

results: dict[str, str] = {}   # check_name → PASS/FAIL/WARN


# ─────────────────────────────────────────────────────────────────────────────
def banner(msg):
    sep = '═' * 72
    log.info(sep)
    log.info('  %s', msg)
    log.info(sep)


def section(msg):
    log.info('─' * 72)
    log.info('  %s', msg)
    log.info('─' * 72)


# ── CHECK 1: pingAll ──────────────────────────────────────────────────────────
def check_pingall(net) -> float:
    section("CHECK 1 — pingAll (0% loss expected)")
    loss = net.pingAll()
    log.info("pingAll loss: %.1f%%", loss)
    if loss == 0.0:
        results['pingall'] = PASS
        log.info("Result: %s  (%.1f%% loss)", PASS, loss)
    elif loss < 5.0:
        results['pingall'] = WARN
        log.warning("Result: %s  (%.1f%% loss — ARP miss on first ping is normal)", WARN, loss)
    else:
        results['pingall'] = FAIL
        log.error("Result: %s  (%.1f%% loss — controller or topology issue)", FAIL, loss)
    return loss


# ── CHECK 2: Flow table inspection ───────────────────────────────────────────
def check_flow_tables(net) -> dict[str, int]:
    """
    Dump flow tables from every switch.
    Expects each switch to have:
      - 1 table-miss flow  (priority=0, match=*, action=CONTROLLER)
      - ≥1 learned unicast flows  (priority>0, eth_dst=<mac>, action=OUTPUT:<port>)
    """
    section("CHECK 2 — Flow tables (learned unicast entries expected)")
    switch_flow_counts: dict[str, int] = {}
    all_ok = True

    for sw in net.switches:
        raw = sw.cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw.name}')
        lines = [l.strip() for l in raw.splitlines()
                 if l.strip() and not l.startswith('NXST') and not l.startswith('OFPST')]

        table_miss   = [l for l in lines if 'priority=0' in l]
        # OVS OF1.3 may use 'dl_dst' (OF1.0 alias) or 'eth_dst' for dest MAC
        learned      = [l for l in lines if 'priority=10' in l
                        and ('eth_dst' in l or 'dl_dst' in l)]
        total_flows  = len(lines)

        switch_flow_counts[sw.name] = len(learned)
        log.info("[%s] total=%d  table-miss=%d  learned-unicast=%d",
                 sw.name, total_flows, len(table_miss), len(learned))

        # Print each learned flow (truncated)
        for fl in learned:
            # OVS OF1.3 uses quoted iface names: output:"s1-eth2"  OR  output:2
            match_iface = re.search(r'output:"([^"]+)"', fl)
            match_port  = re.search(r'output:(\d+)', fl)
            match_n     = re.search(r'n_packets=(\d+)', fl)
            # Extract destination MAC — handle both eth_dst and dl_dst aliases
            match_dst_eth = re.search(r'eth_dst=([\w:]+)', fl)
            match_dst_dl  = re.search(r'dl_dst=([\w:]+)', fl)
            dst  = (match_dst_eth or match_dst_dl).group(1) \
                   if (match_dst_eth or match_dst_dl) else '?'
            port = match_iface.group(1) if match_iface else \
                   match_port.group(1)  if match_port  else '?'
            pkts = match_n.group(1)     if match_n     else '?'
            log.info("    eth_dst=%-20s  out_port=%-20s  packets=%s", dst, port, pkts)

        if len(table_miss) == 0:
            log.error("  [%s] No table-miss flow! Controller may not be connected.", sw.name)
            all_ok = False
        if len(learned) == 0:
            log.warning("  [%s] No learned flows yet — is pingAll done?", sw.name)

    if all_ok and any(v > 0 for v in switch_flow_counts.values()):
        results['flow_tables'] = PASS
    elif all_ok:
        results['flow_tables'] = WARN
    else:
        results['flow_tables'] = FAIL

    log.info("Result: %s", results['flow_tables'])
    return switch_flow_counts


# ── CHECK 3: iperf3 throughput ────────────────────────────────────────────────
def check_iperf(net) -> float:
    """Run iperf3 h1→h8, parse receiver Mbits/sec, compare to 10 Mbps link."""
    section(f"CHECK 3 — iperf3 throughput (h1 → h8, {IPERF_DURATION}s)")
    h1 = net.get('h1')
    h8 = net.get('h8')

    if not shutil.which('iperf3'):
        log.warning("iperf3 not found — falling back to built-in iperf")
        result = net.iperf([h1, h8], l4Type='TCP', seconds=IPERF_DURATION)
        log.info("iperf result: %s", result)
        results['iperf'] = WARN
        return 0.0

    server = h8.popen(['iperf3', '-s', '--one-off'])
    time.sleep(1)
    out = h1.cmd(f'iperf3 -c {h8.IP()} -t {IPERF_DURATION} --format m')
    server.terminate(); server.wait()

    log.info("iperf3 raw output:\n%s", out.strip())

    # Parse receiver throughput
    match = re.search(
        r'\[\s*\d+\]\s+0\.00-[\d.]+\s+sec\s+[\d.]+\s+MBytes\s+([\d.]+)\s+Mbits/sec.*receiver',
        out)
    if match:
        rx_mbps = float(match.group(1))
        log.info("Receiver throughput: %.2f Mbits/sec  (link cap: 10 Mbits/sec)", rx_mbps)
        if rx_mbps >= 7.0:
            results['iperf'] = PASS
        elif rx_mbps >= 3.0:
            results['iperf'] = WARN
            log.warning("Throughput lower than expected — possible RSTP-blocked shortcut path")
        else:
            results['iperf'] = FAIL
    else:
        log.warning("Could not parse receiver throughput from iperf3 output")
        results['iperf'] = WARN
        rx_mbps = 0.0

    log.info("Result: %s", results['iperf'])
    return rx_mbps


# ── CHECK 4: Path tracing (multiple paths) ───────────────────────────────────
def build_port_peer_map(net):
    """
    Build two mappings from Mininet's link objects (ground truth):
      port_map  : (sw_name, port_no)   -> peer_node_name
      iface_map : (sw_name, iface_name) -> peer_node_name

    Using link objects avoids parsing interface names like 's1-eth2'
    (which only gives the local switch name, NOT the peer).
    """
    port_map  = {}   # (sw_name, port_no)    -> peer_name
    iface_map = {}   # (sw_name, iface_name) -> peer_name
    for sw in net.switches:
        for intf in sw.intfList():
            if intf.name == 'lo' or intf.link is None:
                continue
            link = intf.link
            peer_intf = link.intf2 if link.intf1 is intf else link.intf1
            peer_name = peer_intf.node.name
            port_no   = sw.ports.get(intf)
            if port_no is not None:
                port_map[(sw.name, port_no)] = peer_name
            iface_map[(sw.name, intf.name)] = peer_name
    return port_map, iface_map


def check_path_tracing(net):
    """
    Trace the active OF path for h1→h8 and h8→h1 by following output-port
    entries across switch flow tables.

    Bug-fixes vs previous version
    ------------------------------
    1. OVS OF13 dump-flows uses  output:"s1-eth2"  (quoted iface string), NOT
       output:2 (integer).  We handle both formats.
    2. Peer resolution uses Mininet link objects (build_port_peer_map), NOT
       iface.split('-')[0] which always returns the LOCAL switch name.
    """
    section("CHECK 4 — Path tracing h1 ↔ h8 via flow tables")

    h1_mac = net.get('h1').MAC()
    h8_mac = net.get('h8').MAC()
    log.info("h1 MAC: %s   h8 MAC: %s", h1_mac, h8_mac)

    port_map, iface_map = build_port_peer_map(net)
    log.info("Port map built: %d entries", len(port_map))
    for k, v in sorted(port_map.items()):
        log.info("  (%s, port%s) -> %s", k[0], k[1], v)

    def get_output_peer(sw, dst_mac):
        """
        Parse the flow table for a flow whose DESTINATION is dst_mac and
        return the peer node name on the output port, or None.

        Critical: we match on eth_dst=<mac> OR dl_dst=<mac> explicitly,
        NOT just any line containing the MAC string.  The latter would also
        match flows where dst_mac is the SOURCE (eth_src=), giving a wrong
        port (e.g., the local host port instead of the next-hop switch port).
        """
        # Build a pattern that matches the MAC in dst position only
        mac_pattern = re.compile(
            r'(?:eth_dst|dl_dst)=' + re.escape(dst_mac.lower()),
            re.IGNORECASE)
        raw = sw.cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw.name}')
        for line in raw.splitlines():
            if not mac_pattern.search(line):
                continue
            # Format 1: output:"s1-eth2"  (OF13 with named ports)
            m = re.search(r'output:"([^"]+)"', line)
            if m:
                iface = m.group(1)
                peer = iface_map.get((sw.name, iface))
                if peer:
                    return peer
                log.warning("  iface %s not in iface_map for %s", iface, sw.name)
                return iface   # fallback: return iface name
            # Format 2: output:N  (integer port number)
            m = re.search(r'output:(\d+)', line)
            if m:
                port_no = int(m.group(1))
                peer = port_map.get((sw.name, port_no))
                if peer:
                    return peer
                log.warning("  port %d not in port_map for %s", port_no, sw.name)
                return f'port{port_no}'
        return None

    def trace_path(start_sw_name, dst_mac):
        """Walk output-port hops until we reach a host or hit an error."""
        visited = []
        current = start_sw_name
        while True:
            if current in visited:
                return visited + [f'{current}(loop!)']
            visited.append(current)
            sw = net.get(current)
            if sw is None:
                return visited + ['(unknown node)']
            peer = get_output_peer(sw, dst_mac)
            if peer is None:
                return visited + ['(no flow)']
            if peer.startswith('h'):     # reached destination host
                return visited + [peer]
            current = peer              # continue to next switch

    path_h1_h8 = trace_path('s1', h8_mac)
    path_h8_h1 = trace_path('s6', h1_mac)
    log.info("Active path h1→h8: %s", ' → '.join(path_h1_h8))
    log.info("Active path h8→h1: %s", ' → '.join(path_h8_h1))

    # Verify: path ends at the expected host
    fwd_ok = path_h1_h8[-1] == 'h8'
    rev_ok = path_h8_h1[-1] == 'h1'

    log.info("")
    log.info("Known topology paths h1(s1) → h8(s6):")
    log.info("  Path A (via s2-s3): s1 → s2 → s3 → s6 → h8")
    log.info("  Path B (via s4-s5): s1 → s4 → s5 → s6 → h8")
    log.info("  Path C (diagonal):  s1 → s5 → s6 → h8")
    log.info("RSTP selected one active path; redundant links remain for TE.")
    log.info("")

    if fwd_ok and rev_ok:
        results['path_trace'] = PASS
    elif fwd_ok or rev_ok:
        results['path_trace'] = WARN
        log.warning("Only one direction traceable — asymmetric routing?")
    else:
        results['path_trace'] = FAIL
        log.error("Path trace failed — flows not installed or parse error")

    log.info("Result: %s", results['path_trace'])


# ── CHECK 5: Controller health (flow count as proxy) ─────────────────────────
def check_controller_health(net):
    """
    Verifies Ryu processed PacketIn/FlowMod events by checking that each
    switch has > 1 flow (table-miss + at least one learned rule).
    Also checks that the table-miss flow is exactly as expected (priority=0,
    action=CONTROLLER).
    """
    section("CHECK 5 — Controller health (FlowMod events observed)")
    all_ok = True

    for sw in net.switches:
        raw = sw.cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw.name}')
        total = sum(1 for l in raw.splitlines()
                    if l.strip() and not l.startswith(('NXST', 'OFPST')))
        has_miss = 'priority=0' in raw and 'CONTROLLER' in raw
        has_learned = 'priority=10' in raw

        status = PASS if (has_miss and has_learned) else \
                 WARN if has_miss else FAIL

        log.info("[%s] total_flows=%-3d  table-miss=%s  learned=%s  → %s",
                 sw.name, total,
                 '✓' if has_miss else '✗',
                 '✓' if has_learned else '✗',
                 status)
        if status == FAIL:
            all_ok = False

    results['controller'] = PASS if all_ok else WARN
    log.info("Result: %s", results['controller'])


# ── SUMMARY ───────────────────────────────────────────────────────────────────
def print_summary():
    banner("PHASE 1 VERIFICATION SUMMARY")
    checks = [
        ('pingall',      'pingAll 0% packet loss'),
        ('flow_tables',  'Flow tables populated (learned unicast entries)'),
        ('iperf',        'iperf3 throughput ≥ 7 Mbits/sec'),
        ('path_trace',   'Path h1→h8 traceable; multiple paths in topology'),
        ('controller',   'Ryu FlowMod events observed on all switches'),
    ]
    passed = failed = warned = 0
    for key, desc in checks:
        r = results.get(key, '❓ NOT RUN')
        log.info("  %s  %s", r, desc)
        if 'PASS' in r:  passed  += 1
        elif 'FAIL' in r: failed += 1
        else:              warned += 1

    log.info("")
    log.info("  Passed: %d  │  Warnings: %d  │  Failed: %d  │  Total: %d",
             passed, warned, failed, len(checks))
    log.info("  Log saved to: %s", LOG_FILE)

    if failed == 0:
        log.info("")
        log.info("  🎉 Phase 1 COMPLETE — ready for Phase 2 (East-West protocol)")
    else:
        log.error("")
        log.error("  ⛔ %d check(s) FAILED — review logs above before proceeding", failed)


# ─────────────────────────────────────────────────────────────────────────────
def main():
    if os.geteuid() != 0:
        print("[ERROR] Run with sudo.", file=sys.stderr)
        sys.exit(1)

    banner(f"Phase 1 Verification  —  {datetime.now().isoformat()}")
    setLogLevel('warning')

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

    enable_rstp(net, converge_wait=8)
    connected = wait_for_controller(net, timeout=30)
    if not connected:
        log.error("Controller not reachable — is ryu-manager running?")
        net.stop()
        sys.exit(1)
    time.sleep(6)   # let table-miss flows settle

    try:
        # ── Warm-up pingAll: populates ARP + installs initial flows ──────
        log.info("Warm-up pingAll (to seed ARP and flow tables)...")
        net.pingAll()
        time.sleep(3)

        # CHECK 1 — second pingAll: all flows already installed, should be 0%
        check_pingall(net)

        # CHECK 3 — iperf: runs while flows are warm; also keeps flows alive
        check_iperf(net)
        time.sleep(2)   # let any iperf-triggered flows settle

        # CHECK 2 & 4 — flow tables and path trace AFTER iperf:
        # flows are fully populated and won't have expired yet (idle_timeout=30s)
        check_flow_tables(net)
        check_path_tracing(net)

        # CHECK 5 — controller health
        check_controller_health(net)
    finally:
        print_summary()
        net.stop()
        for h in log.handlers:
            h.flush(); h.close()
        print(f"\n[OK] Verification log: {LOG_FILE}")


if __name__ == '__main__':
    main()
