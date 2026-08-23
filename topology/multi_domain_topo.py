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

  Domain C  (Controller port 6635)  DPIDs 7-9
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
CTRL_C_PORT = 6635
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
                      failMode='secure')

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
    net.addLink('s1', 's2', **lp)
    net.addLink('s2', 's3', **lp)
    net.addLink('s1', 's3', **lp)
    # Domain B triangle
    net.addLink('s4', 's5', **lp)
    net.addLink('s5', 's6', **lp)
    net.addLink('s4', 's6', **lp)
    # Domain C triangle
    net.addLink('s7', 's8', **lp)
    net.addLink('s8', 's9', **lp)
    net.addLink('s7', 's9', **lp)

    info('*** Adding inter-domain links (East-West boundaries)\n')
    net.addLink('s3', 's4', **lp)   # A ↔ B
    net.addLink('s6', 's7', **lp)   # B ↔ C
    net.addLink('s3', 's7', **lp)   # A ↔ C  (diagonal)

    info('*** Attaching hosts to switches\n')
    # Domain A
    net.addLink('h1',  's1', **lp)
    net.addLink('h2',  's1', **lp)
    net.addLink('h3',  's2', **lp)
    net.addLink('h4',  's3', **lp)
    # Domain B
    net.addLink('h5',  's4', **lp)
    net.addLink('h6',  's4', **lp)
    net.addLink('h7',  's5', **lp)
    net.addLink('h8',  's6', **lp)
    # Domain C
    net.addLink('h9',  's7', **lp)
    net.addLink('h10', 's8', **lp)
    net.addLink('h11', 's9', **lp)
    net.addLink('h12', 's9', **lp)

    return net


def assign_controllers(net: Mininet):
    """Assign each OVS switch to exactly one remote controller via ovs-vsctl."""
    info('*** Assigning switches to domain controllers\n')
    for sw in net.switches:
        port = SWITCH_CTRL_PORT[sw.name]
        sw.cmd(f'ovs-vsctl set-controller {sw.name} tcp:{CTRL_IP}:{port}')
        info(f'  {sw.name} → controller port {port}\n')


def enable_rstp(net: Mininet, wait: int = 8):
    """Enable RSTP to prevent broadcast storms in intra-domain triangles."""
    info('*** Enabling RSTP on all bridges\n')
    for sw in net.switches:
        sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=true')
    info(f'    Waiting {wait}s for RSTP convergence...\n')
    time.sleep(wait)


def run():
    setLogLevel('info')
    net = build_network()

    info('*** Starting network\n')
    net.start()

    assign_controllers(net)
    enable_rstp(net, wait=8)

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
