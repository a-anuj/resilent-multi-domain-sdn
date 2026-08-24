#!/usr/bin/env python3
"""
topology/multi_domain_topo.py
------------------------------
3-domain, 9-switch, 12-host Mininet topology for multi-controller research.

Domain layout
─────────────
  Domain A  (Controller port 6633)  DPIDs 1-3
    s1 ── s2 ── s3          (triangle intra-domain)
    │       │    │
    h1,h2  h3  h4

  Domain B  (Controller port 6634)  DPIDs 4-6
    s4 ── s5 ── s6
    │       │    │
    h5,h6  h7  h8

  Domain C  (Controller port 6653)  DPIDs 7-9
    s7 ── s8 ── s9
    │       │    │
    h9     h10  h11,h12

Inter-domain links (East-West boundary, no coordination yet):
  s3 ── s4   (A ↔ B)
  s6 ── s7   (B ↔ C)
  s3 ── s7   (A ↔ C  diagonal)

Run (standalone):
    sudo python3 topology/multi_domain_topo.py
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from mininet.net import Mininet
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# ── Constants ─────────────────────────────────────────────────────────────────

CTRL_A_PORT = 6633
CTRL_B_PORT = 6634
CTRL_C_PORT = 6653
CTRL_IP     = '127.0.0.1'
LINK_BW     = 10   # Mbps

# Which switches belong to which domain
DOMAIN_A = ['s1', 's2', 's3']
DOMAIN_B = ['s4', 's5', 's6']
DOMAIN_C = ['s7', 's8', 's9']

SWITCH_CTRL_PORT = {
    **{sw: CTRL_A_PORT for sw in DOMAIN_A},
    **{sw: CTRL_B_PORT for sw in DOMAIN_B},
    **{sw: CTRL_C_PORT for sw in DOMAIN_C},
}

# For external import (used by domain_test.py)
DOMAIN_HOSTS = {
    'A': ['h1',  'h2',  'h3',  'h4'],
    'B': ['h5',  'h6',  'h7',  'h8'],
    'C': ['h9',  'h10', 'h11', 'h12'],
}
HOST_DOMAIN = {h: d for d, hosts in DOMAIN_HOSTS.items() for h in hosts}


def build_network() -> Mininet:
    """
    Build and return the multi-domain Mininet network.
    Controllers are NOT added to Mininet's controller list;
    each switch is assigned via ovs-vsctl after start().
    """
    net = Mininet(
        controller=None,        # Manual controller assignment below
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False,
    )

    info('*** Adding switches\n')
    for i in range(1, 10):
        net.addSwitch(f's{i}',
                      dpid=f'{i:016x}',
                      protocols='OpenFlow13',
                      failMode='secure')   # 'secure': drop unknown frames when controller slow, not flood

    info('*** Adding hosts\n')
    # All hosts in the same /24 for pure L2; controller partitioning is the
    # variable of interest, not IP routing.
    host_ip = 1
    for host_name in [f'h{i}' for i in range(1, 13)]:
        net.addHost(host_name, ip=f'10.0.0.{host_ip}/24')
        host_ip += 1

    info('*** Adding intra-domain links\n')
    lp = dict(bw=LINK_BW)
    # Domain A triangle
    net.addLink('s1', 's2', port1=1, port2=1, **lp)
    net.addLink('s2', 's3', port1=2, port2=1, **lp)
    net.addLink('s1', 's3', port1=2, port2=2, **lp)
    # Domain B triangle
    net.addLink('s4', 's5', port1=1, port2=1, **lp)
    net.addLink('s5', 's6', port1=2, port2=1, **lp)
    net.addLink('s4', 's6', port1=2, port2=2, **lp)
    # Domain C triangle
    net.addLink('s7', 's8', port1=1, port2=1, **lp)
    net.addLink('s8', 's9', port1=2, port2=1, **lp)
    net.addLink('s7', 's9', port1=2, port2=2, **lp)

    info('*** Adding inter-domain links (East-West boundaries)\n')
    inter_links = []
    inter_links.append(net.addLink('s3', 's4', port1=3, port2=3, **lp))   # A ↔ B
    inter_links.append(net.addLink('s6', 's7', port1=3, port2=3, **lp))   # B ↔ C
    inter_links.append(net.addLink('s3', 's7', port1=4, port2=4, **lp))   # A ↔ C  (diagonal)

    # Store inter_links in the net object so we can use it later
    net.inter_links = inter_links

    info('*** Attaching hosts to switches\n')
    # Domain A
    net.addLink('h1',  's1', port2=3, **lp)
    net.addLink('h2',  's1', port2=4, **lp)
    net.addLink('h3',  's2', port2=3, **lp)
    net.addLink('h4',  's3', port2=5, **lp)
    # Domain B
    net.addLink('h5',  's4', port2=4, **lp)
    net.addLink('h6',  's4', port2=5, **lp)
    net.addLink('h7',  's5', port2=3, **lp)
    net.addLink('h8',  's6', port2=4, **lp)
    # Domain C
    net.addLink('h9',  's7', port2=5, **lp)
    net.addLink('h10', 's8', port2=3, **lp)
    net.addLink('h11', 's9', port2=3, **lp)
    net.addLink('h12', 's9', port2=4, **lp)

    return net


def assign_controllers(net: Mininet):
    """Assign each OVS switch to exactly one remote controller via ovs-vsctl."""
    info('*** Assigning switches to domain controllers\n')
    for sw in net.switches:
        port = SWITCH_CTRL_PORT[sw.name]
        sw.cmd(f'ovs-vsctl set-controller {sw.name} tcp:{CTRL_IP}:{port}')
        info(f'  {sw.name} → controller port {port}\n')


def enable_rstp(net: Mininet, wait: int = 8):
    """
    Software-defined spanning tree (no RSTP kernel blocking).

    Instead of relying on RSTP — which non-deterministically blocks inter-domain
    ports along with intra-domain redundant links — we:

      1. Explicitly DISABLE RSTP on every bridge (all ports stay forwarding).
      2. Install low-priority OpenFlow DROP rules on exactly the REDUNDANT
         back-links of each intra-domain triangle to prevent broadcast storms:

           Domain A triangle: s1-s2-s3  →  block s1↔s3 (the hypotenuse)
           Domain B triangle: s4-s5-s6  →  block s4↔s6
           Domain C triangle: s7-s8-s9  →  block s7↔s9

    This leaves ALL inter-domain links (s3-s4, s6-s7, s3-s7) permanently
    forwarding, so the TE controller can always route through them.
    The controller's per-flow rules (priority ≥ 10) override these drops
    for known unicast flows.

    This is the same approach used in the working single-controller TE
    implementation (final_year/qos_controller.py _get_tree_ports).
    """
    info('*** Disabling RSTP (using software spanning tree via OpenFlow drops)\n')
    for sw in net.switches:
        sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=false')
        sw.cmd(f'ovs-vsctl set bridge {sw.name} stp_enable=false')

    # Redundant triangle back-links to block — ALL frame types, matching real RSTP behaviour.
    # Root cause of loop storm: the previous rule only blocked dl_dst=ff:ff:ff:ff:ff:ff
    # (Ethernet broadcast). Unknown unicast, ARP, LLDP, and IPv4 multicast still passed
    # through the hypotenuse, creating a triangle forwarding loop that sent 236k+ packets
    # to CONTROLLER, CPU-starved the PortStats greenlet, and diluted utilization readings.
    #
    # Fix: priority=2 catch-all DROP on in_port (no dl_dst match) blocks ALL frames.
    # TE unicast rules (priority ≥ 10) override this for known flows, so TE routing
    # through the hypotenuse still works when the controller explicitly installs rules.
    BLOCK_LINKS = [
        ('s1', 's3'),   # Domain A triangle hypotenuse
        ('s4', 's6'),   # Domain B triangle hypotenuse
        ('s7', 's9'),   # Domain C triangle hypotenuse
    ]

    for sw_a_name, sw_b_name in BLOCK_LINKS:
        sw_a = net.get(sw_a_name)
        sw_b = net.get(sw_b_name)
        if sw_a is None or sw_b is None:
            continue
        # Find the port numbers on each side of the link
        for intf_a in sw_a.intfList():
            peer = intf_a.link.intf2 if intf_a.link and intf_a.link.intf1 == intf_a else (
                   intf_a.link.intf1 if intf_a.link else None)
            if peer and peer.node.name == sw_b_name:
                port_a = sw_a.ports[intf_a]
                port_b = sw_b.ports[peer]
                # Block ALL frames on hypotenuse port (catch-all, no dl_dst filter).
                # priority=2 so any controller-installed unicast rule (priority≥10) overrides.
                sw_a.cmd(f'ovs-ofctl add-flow {sw_a_name} '
                         f'priority=2,in_port={port_a},actions=drop '
                         f'-O OpenFlow13')
                sw_b.cmd(f'ovs-ofctl add-flow {sw_b_name} '
                         f'priority=2,in_port={port_b},actions=drop '
                         f'-O OpenFlow13')
                info(f'  [STP] Blocked ALL traffic on {sw_a_name}:p{port_a} ↔ {sw_b_name}:p{port_b}\n')
                break

    info(f'    Software spanning tree ready (no RSTP wait needed).\n')


def isolate_domains(net: Mininet):
    """Install drop rules on inter-domain ports so baseline controllers remain isolated."""
    info('*** Isolating domains by installing high-priority DROP rules on inter-domain ports\n')
    if hasattr(net, 'inter_links'):
        for link in net.inter_links:
            s1_node = link.intf1.node
            s1_port_no = s1_node.ports[link.intf1]
            s2_node = link.intf2.node
            s2_port_no = s2_node.ports[link.intf2]
            
            cmd1 = f'ovs-ofctl add-flow {s1_node.name} priority=100,in_port={s1_port_no},actions=drop -O OpenFlow13'
            cmd2 = f'ovs-ofctl add-flow {s2_node.name} priority=100,in_port={s2_port_no},actions=drop -O OpenFlow13'
            out1 = s1_node.cmd(cmd1)
            out2 = s2_node.cmd(cmd2)
            info(f'  [ISOLATE] Executed: {cmd1} (out: {out1.strip()})\n')
            info(f'  [ISOLATE] Executed: {cmd2} (out: {out2.strip()})\n')


def run():
    setLogLevel('info')
    net = build_network()

    info('*** Starting network\n')
    net.start()

    enable_rstp(net, wait=30)
    assign_controllers(net)
    isolate_domains(net)

    info('\n*** Multi-domain topology running.\n')
    info('    Domain A (port 6633): s1, s2, s3  | h1-h4\n')
    info('    Domain B (port 6634): s4, s5, s6  | h5-h8\n')
    info('    Domain C (port 6635): s7, s8, s9  | h9-h12\n')
    info('    Inter-domain: s3-s4, s6-s7, s3-s7\n')
    info('    Use "exit" or Ctrl-D to stop.\n\n')

    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
