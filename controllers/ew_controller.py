#!/usr/bin/env python3
"""
controllers/ew_controller.py
------------------------------
Phase 3: East-West aware domain controller.

Extends the Phase 2 DomainController with:
  • Flask REST API (eastwest/ew_api.py) in a daemon thread
  • SyncAgent (eastwest/sync_agent.py) polling peer controllers every 5s
  • Inter-domain forwarding: on PacketIn for unknown dst, query global
    topology → install a flow rule pointing toward the inter-domain port
  • PortStats polling every 10s → update local link-state in global_topology

Launch (one process per domain):
──────────────────────────────────
  DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 \
      ryu-manager controllers/ew_controller.py \
      --ofp-tcp-listen-port 6633

  DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 EW_API_PORT=8081 \
      ryu-manager controllers/ew_controller.py \
      --ofp-tcp-listen-port 6634

  DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 EW_API_PORT=8082 \
      ryu-manager controllers/ew_controller.py \
      --ofp-tcp-listen-port 6653

Environment variables
──────────────────────
  DOMAIN_ID    : 'A', 'B', or 'C'
  DOMAIN_DPIDS : comma-separated DPID integers owned by this domain
  EW_API_PORT  : TCP port for this controller's REST API (default: 8080)
"""

import os
import sys
import threading
import time
from collections import defaultdict

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                    set_ev_cls)
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, arp
from ryu.ofproto import ofproto_v1_3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from eastwest import global_topology as gt
from eastwest.ew_api import start_api
from eastwest.sync_agent import start_sync_agent, DOMAIN_API_PORTS

# ── Domain configuration ──────────────────────────────────────────────────────
DOMAIN_ID    = os.environ.get('DOMAIN_ID', 'UNKNOWN')
_raw         = os.environ.get('DOMAIN_DPIDS', '')
DOMAIN_DPIDS = frozenset(int(d) for d in _raw.split(',') if d.strip().isdigit())
EW_API_PORT  = int(os.environ.get('EW_API_PORT', 8080))

# Inter-domain port map loaded from topology constants
# Maps (boundary_dpid, peer_dpid) → local_port_no
# Populated during switch handshake when we detect inter-domain links.
_INTER_DOMAIN_PORT_MAP: dict[tuple[int, int], int] = {}

# Flow priorities
PRI_MISS         = 0
PRI_LEARNED      = 10
PRI_INTER_DOMAIN = 50   # inter-domain forwarding rules (below drop rules)
PRI_DROP         = 100  # boundary drop rules (installed by topology script)

IDLE_TO  = 30
HARD_TO  = 300

STATS_INTERVAL = 10   # seconds between PortStats requests

# ── Peer domain determination ─────────────────────────────────────────────────
_ALL_DOMAINS    = {'A', 'B', 'C'}
_PEER_DOMAINS   = sorted(_ALL_DOMAINS - {DOMAIN_ID})


# ─────────────────────────────────────────────────────────────────────────────
# Topology introspection helpers
# ─────────────────────────────────────────────────────────────────────────────

# Runtime registry: dpid → {port_no: {peer_dpid, ...}}
# Populated as switches connect.
_switch_registry: dict[int, dict] = {}   # dpid → {'ports': {no: desc}}
_dp_map: dict[int, object] = {}          # dpid → datapath object
_dp_map_lock = threading.Lock()

# Known inter-domain links (from topology constants):
# (src_dpid, src_port, dst_dpid, dst_port)
_inter_links: list[dict] = []


def _local_topology_snapshot() -> dict:
    """
    Build the topology dict to serve via GET /topology.
    Called by both ew_api and sync_agent.
    """
    switches = {}
    links    = []
    for dpid, info in _switch_registry.items():
        switches[str(dpid)] = {
            'dpid':   dpid,
            'domain': DOMAIN_ID,
            'ports':  list(info.get('ports', {}).keys()),
        }

    # Intra-domain link state: we do not enumerate physical links here
    # (Ryu doesn't provide automatic topology discovery in OF1.3 without LLDP).
    # We rely on the static topology definition for link structure.
    # The global_topology is seeded from the topology script via merge_local_topology().

    return {
        'domain_id':   DOMAIN_ID,
        'switches':    switches,
        'links':       links,
        'inter_links': list(_inter_links),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ryu App
# ─────────────────────────────────────────────────────────────────────────────

class EWController(app_manager.RyuApp):
    """
    East-West capable domain controller.
    Runs alongside a Flask API server and a SyncAgent background thread.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port: dict[int, dict] = defaultdict(dict)
        self.foreign_events: dict[int, int] = defaultdict(int)
        self._sync_agent = None
        self._api_thread = None
        self._stats_thread = None

        if not DOMAIN_DPIDS:
            self.logger.warning(
                '[Domain %s] DOMAIN_DPIDS not set — controller will ignore all switches.',
                DOMAIN_ID)
        else:
            self.logger.info('[Domain %s] EW Controller started. DPIDs: %s',
                             DOMAIN_ID, sorted(DOMAIN_DPIDS))

        # Seed global topology with static inter-domain link info from the
        # topology module (if available).  This runs before any switch connects.
        self._seed_static_inter_links()

        # Start REST API + sync agent
        self._start_ew_infrastructure()

    # ── Startup helpers ───────────────────────────────────────────────────────

    def _seed_static_inter_links(self):
        """
        Import known inter-domain link topology from multi_domain_topo constants.
        Because the topology module uses Mininet (not available in controller
        process), we hard-code the inter-domain adjacency here.  The sync
        agent will override this with live data once switches connect.

        Inter-domain links (from topology/multi_domain_topo.py):
          s3 (dpid=3) ↔ s4 (dpid=4)   A ↔ B
          s6 (dpid=6) ↔ s7 (dpid=7)   B ↔ C
          s3 (dpid=3) ↔ s7 (dpid=7)   A ↔ C  diagonal

        Port numbers are determined dynamically when switches connect and
        report their port list.  We pre-populate with known adjacency data
        and fill port numbers in _register_inter_domain_port().
        """
        _static_inter = [
            # (src_dpid, dst_dpid) — ports filled in at handshake time
            (3, 4),   # A ↔ B
            (6, 7),   # B ↔ C
            (3, 7),   # A ↔ C
        ]
        for src, dst in _static_inter:
            # Only add if this domain owns one side
            if src in DOMAIN_DPIDS or dst in DOMAIN_DPIDS:
                _inter_links.append({
                    'src_dpid': src,
                    'src_port': None,   # filled in at handshake
                    'dst_dpid': dst,
                    'dst_port': None,
                })

    def _start_ew_infrastructure(self):
        """Launch the Flask API and SyncAgent in background threads."""
        # Use a short delay to let the Ryu hub start properly first
        def _deferred():
            time.sleep(2)
            self._api_thread = start_api(
                domain_id=DOMAIN_ID,
                api_port=EW_API_PORT,
                local_topo_fn=_local_topology_snapshot,
                ew_log_path=os.path.join(PROJECT_ROOT,
                                         'results', 'eastwest_traffic.log'),
            )
            self._sync_agent = start_sync_agent(
                domain_id=DOMAIN_ID,
                peer_domains=_PEER_DOMAINS,
                local_topo_fn=_local_topology_snapshot,
                ew_log_path=os.path.join(PROJECT_ROOT,
                                         'results', 'eastwest_traffic.log'),
            )
            self.logger.info('[Domain %s] EW infrastructure up. API port=%d, peers=%s',
                             DOMAIN_ID, EW_API_PORT, _PEER_DOMAINS)

        t = threading.Thread(target=_deferred, daemon=True, name='ew-init')
        t.start()

    # ── Per-port stats polling ─────────────────────────────────────────────────

    def _start_stats_polling(self):
        """Kick off periodic PortStats requests on a Ryu hub greenlet."""
        def _poll():
            while True:
                hub.sleep(STATS_INTERVAL)
                with _dp_map_lock:
                    dps = list(_dp_map.values())
                for dp in dps:
                    if dp.id in DOMAIN_DPIDS:
                        self._request_port_stats(dp)

        hub.spawn(_poll)

    def _request_port_stats(self, dp):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        req = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dp   = ev.msg.datapath
        dpid = dp.id
        if dpid not in DOMAIN_DPIDS:
            return
        gt.update_link_state_local(dpid, ev.msg.body)

    # ── OpenFlow helpers ──────────────────────────────────────────────────────

    def _owned(self, dpid: int) -> bool:
        return dpid in DOMAIN_DPIDS

    def _add_flow(self, dp, priority, match, actions,
                  idle=IDLE_TO, hard=HARD_TO):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst, idle_timeout=idle, hard_timeout=hard)
        dp.send_msg(mod)

    def _send_packet_out(self, dp, buffer_id, in_port, actions, data=None):
        parser = dp.ofproto_parser
        ofp    = dp.ofproto
        out    = parser.OFPPacketOut(
            datapath=dp, buffer_id=buffer_id,
            in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

    # ── Switch features / handshake ───────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp    = ev.msg.datapath
        dpid  = dp.id
        ofp   = dp.ofproto
        parser = dp.ofproto_parser

        if not self._owned(dpid):
            self.foreign_events[dpid] += 1
            self.logger.warning(
                '[Domain %s] SwitchFeatures from FOREIGN dpid=%d — ignoring.',
                DOMAIN_ID, dpid)
            return

        self.logger.info('[Domain %s] Switch connected: dpid=%d', DOMAIN_ID, dpid)

        with _dp_map_lock:
            _dp_map[dpid] = dp

        # Register switch
        _switch_registry.setdefault(dpid, {'ports': {}})

        # Install table-miss → CONTROLLER
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, PRI_MISS, match, actions, idle=0, hard=0)

        # Seed global topology with this switch
        gt.merge_local_topology(
            DOMAIN_ID,
            {str(dpid): {'dpid': dpid, 'domain': DOMAIN_ID, 'ports': []}},
            links=[],
            inter_links=[il for il in _inter_links if None not in (il['src_port'], il['dst_port'])],
        )

        # Kick off stats polling (safe to call multiple times — hub.spawn is idempotent here)
        if len(_dp_map) == 1:   # only start once
            self._start_stats_polling()

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        """Populate port registry once OVS sends back port descriptions."""
        dp   = ev.msg.datapath
        dpid = dp.id
        if dpid not in DOMAIN_DPIDS:
            return

        ports = {}
        for p in ev.msg.body:
            ports[p.port_no] = p.name.decode('utf-8', errors='replace')

        _switch_registry.setdefault(dpid, {})['ports'] = ports
        self.logger.debug('[Domain %s] dpid=%d ports: %s', DOMAIN_ID, dpid, ports)

    # ── Packet-In handler ─────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg    = ev.msg
        dp     = msg.datapath
        dpid   = dp.id
        ofp    = dp.ofproto
        parser = dp.ofproto_parser

        if not self._owned(dpid):
            self.foreign_events[dpid] += 1
            self.logger.warning(
                '[Domain %s] PacketIn from FOREIGN dpid=%d (%d total). Dropping.',
                DOMAIN_ID, dpid, self.foreign_events[dpid])
            return

        in_port  = msg.match['in_port']
        pkt      = packet.Packet(msg.data)
        eth_pkt  = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return

        dst = eth_pkt.dst
        src = eth_pkt.src

        # Ignore LLDP / STP / LACP
        if eth_pkt.ethertype in (ether_types.ETH_TYPE_LLDP, 0x8809):
            return

        # ── Extract IP for host registration ──────────────────────────────
        ip_src = ''
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            ip_src = ip_pkt.src

        # Broadcast MACs: skip host learning
        if src != 'ff:ff:ff:ff:ff:ff':
            table = self.mac_to_port[dpid]
            table[src] = in_port
            gt.update_host(src, dpid, in_port, ip=ip_src)

        # ── Resolve destination ────────────────────────────────────────────
        table = self.mac_to_port[dpid]

        if dst in table:
            # Known local destination — standard L2 forwarding
            out_port = table[dst]
            actions  = [parser.OFPActionOutput(out_port)]
            match    = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(dp, PRI_LEARNED, match, actions)
            data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
            self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)
            return

        # ── Check global topology for inter-domain routing ─────────────────
        nexthop = gt.find_inter_domain_nexthop(dpid, dst)
        if nexthop is not None:
            nexthop_dpid, nexthop_port = nexthop
            if nexthop_dpid == dpid:
                # The inter-domain boundary is on THIS switch — forward to its port
                out_port = nexthop_port
                actions  = [parser.OFPActionOutput(out_port)]
                match    = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                self.logger.info(
                    '[Domain %s] Inter-domain forward: dpid=%d dst=%s → port=%d',
                    DOMAIN_ID, dpid, dst, out_port)
                # Install a short-lived flow (idle=10s) — will refresh on use
                self._add_flow(dp, PRI_INTER_DOMAIN, match, actions,
                               idle=10, hard=60)
                data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
                self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)
                return
            # Else: dst reachable but via a different switch in our domain;
            # fall through to flood so ARP can proceed.

        # ── Unknown / inter-domain not yet resolved → flood ───────────────
        out_port = ofp.OFPP_FLOOD
        actions  = [parser.OFPActionOutput(out_port)]
        data     = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)
