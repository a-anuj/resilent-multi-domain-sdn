#!/usr/bin/env python3
r"""
topology/basic_topo.py
----------------------
Phase 1 – Partial-mesh topology for the SDN multi-controller testbed.

Layout
------

    h1  h2           h5  h6
     \  /             \  /
      s1 ─────────── s4
      │ ╲           ╱ │
      │  s2 ─────s5   │      h3
      │ ╱           ╲ │      │
      s3 ─────────── s6      s2 (s2 also connects h3)
      │               │
      h4              h8

Switch interconnect (all 10 Mbps unless noted):
    s1 ↔ s2   s1 ↔ s4   s1 ↔ s5  ← diagonal (extra path for TE)
    s2 ↔ s3   s2 ↔ s5
    s3 ↔ s6
    s4 ↔ s5   s5 ↔ s6

Multiple paths h1→h8 (good for Traffic Engineering later):
    A: s1→s2→s3→s6      B: s1→s4→s5→s6      C: s1→s5→s6

Host placements:
    s1: h1, h2    s2: h3    s3: h4
    s4: h5, h6    s5: h7    s6: h8

Run standalone:
    sudo python3 topology/basic_topo.py
or via Mininet:
    sudo mn --custom topology/basic_topo.py --topo partial_mesh \
            --controller remote,ip=127.0.0.1,port=6653 --link tc
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info


# ── Bandwidth parameters (Mbps) ──────────────────────────────────────────────
BW_CORE  = 10   # switch-to-switch links  (inducing congestion is easy here)
BW_EDGE  = 10   # host-to-switch access links
DELAY    = '5ms'
MAX_QUEUE= 1000  # packets — small queues so congestion is visible quickly


class PartialMeshTopo(Topo):
    """6-switch partial mesh with 8 hosts and explicit bandwidth."""

    def build(self, bw_core=BW_CORE, bw_edge=BW_EDGE, **kwargs):
        # ── Switches ─────────────────────────────────────────────────────
        switches = {}
        for i in range(1, 7):          # s1 … s6
            switches[i] = self.addSwitch(
                f's{i}',
                cls=OVSKernelSwitch,
                protocols='OpenFlow13',
            )

        # ── Core (switch-to-switch) links ─────────────────────────────────
        core_links = [
            (1, 2), (1, 4), (1, 5),   # s1 fanout + diagonal
            (2, 3), (2, 5),            # s2 connections
            (3, 6),                    # s3 → s6
            (4, 5),                    # s4 → s5
            (5, 6),                    # s5 → s6
        ]
        core_opts = dict(
            bw=bw_core,
            delay=DELAY,
            max_queue_size=MAX_QUEUE,
            use_htb=True,
        )
        for a, b in core_links:
            self.addLink(switches[a], switches[b], **core_opts)

        # ── Hosts + access links ───────────────────────────────────────────
        edge_opts = dict(
            bw=bw_edge,
            delay=DELAY,
            max_queue_size=MAX_QUEUE,
            use_htb=True,
        )
        host_map = {
            # ALL hosts share 10.0.0.0/24 — required for an L2 switch.
            # If hosts are on different /24 subnets, the OS kernel returns
            # "Network is unreachable" before ARP/ping even leaves the host.
            1: [('h1', '10.0.0.1/24'), ('h2', '10.0.0.2/24')],
            2: [('h3', '10.0.0.3/24')],
            3: [('h4', '10.0.0.4/24')],
            4: [('h5', '10.0.0.5/24'), ('h6', '10.0.0.6/24')],
            5: [('h7', '10.0.0.7/24')],
            6: [('h8', '10.0.0.8/24')],
        }
        for sw_id, hosts in host_map.items():
            for name, ip in hosts:
                host = self.addHost(name, ip=ip)
                self.addLink(host, switches[sw_id], **edge_opts)


# ── Standalone entry point ────────────────────────────────────────────────────
def run():
    setLogLevel('info')
    topo = PartialMeshTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip='127.0.0.1', port=6653),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=False,
    )
    net.start()

    # Enable RSTP to prevent broadcast storms in the looped mesh topology
    info('*** Enabling RSTP on all bridges (wait ~8s for convergence)\n')
    for sw in net.switches:
        sw.cmd(f'ovs-vsctl set bridge {sw.name} rstp_enable=true')
    import time; time.sleep(8)

    info('\n*** Network started — dropping into Mininet CLI\n')
    info('*** Use "exit" or Ctrl-D to stop.\n\n')
    CLI(net)
    net.stop()


# Allow `mn --custom ... --topo partial_mesh` to find the class
topos = {'partial_mesh': PartialMeshTopo}

if __name__ == '__main__':
    run()
