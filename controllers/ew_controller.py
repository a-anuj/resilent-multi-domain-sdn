#!/usr/bin/env python3
"""
controllers/ew_controller.py
------------------------------
Phase 3+4: East-West aware + Traffic Engineering domain controller.

New in Phase 4 (TE):
  • Static intra-domain links now seeded properly into global_topology
  • PacketIn for inter-domain flows consults te.path_selector for the
    least-congested path (Dijkstra, weight = utilization ratio)
  • Installs flow rule segments on THIS domain's switches; calls
    POST /install_path on peer controllers for their segments
  • Periodic congestion monitor re-checks active inter-domain flows
    every REEVAL_INTERVAL seconds; if utilization > CONGESTION_THRESHOLD
    on the current path, recomputes and redirects new flows
  • TE disabled mode (TE_ENABLED=0 env var) falls back to hop-count
    shortest path — used for the TE-off baseline experiment
  • All TE decisions logged to results/te_decisions.log

Launch (one process per domain):
──────────────────────────────────
  DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 [TE_ENABLED=1] \
      ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6633

  DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 EW_API_PORT=8081 [TE_ENABLED=1] \
      ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6634

  DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 EW_API_PORT=8082 [TE_ENABLED=1] \
      ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6653
"""

import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                    set_ev_cls)
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, arp
from ryu.ofproto import ofproto_v1_3

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from eastwest import global_topology as gt
from eastwest.ew_api import start_api
from eastwest.sync_agent import start_sync_agent, DOMAIN_API_PORTS
from te.path_selector import (
    compute_path, summarize_path, is_congested,
    CONGESTION_THRESHOLD, DPID_DOMAIN, STATIC_LINKS,
)

# ── Domain configuration ──────────────────────────────────────────────────────
DOMAIN_ID    = os.environ.get('DOMAIN_ID', 'UNKNOWN')
_raw         = os.environ.get('DOMAIN_DPIDS', '')
DOMAIN_DPIDS = frozenset(int(d) for d in _raw.split(',') if d.strip().isdigit())
EW_API_PORT  = int(os.environ.get('EW_API_PORT', 8080))
TE_ENABLED   = os.environ.get('TE_ENABLED', '1') != '0'

# Flow priorities
PRI_MISS         = 0
PRI_LEARNED      = 10
PRI_INTER_DOMAIN = 50
PRI_DROP         = 100

IDLE_TO  = 30
HARD_TO  = 300

STATS_INTERVAL  = 5     # seconds between PortStats polls (5s for responsive util tracking)
REEVAL_INTERVAL = 15    # seconds between congestion re-evaluation

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR    = os.path.join(PROJECT_ROOT, 'results')
TE_DECISIONS_LOG = os.path.join(RESULTS_DIR, 'te_decisions.log')
EW_TRAFFIC_LOG   = os.path.join(RESULTS_DIR, 'eastwest_traffic.log')
os.makedirs(RESULTS_DIR, exist_ok=True)

import logging as _std_log
_te_log = _std_log.getLogger('te_decisions')
_te_log.setLevel(_std_log.DEBUG)
if not _te_log.handlers:
    _fh = _std_log.FileHandler(TE_DECISIONS_LOG, mode='a', encoding='utf-8')
    _fh.setFormatter(_std_log.Formatter('%(asctime)s  %(message)s',
                                        datefmt='%Y-%m-%dT%H:%M:%S'))
    _te_log.addHandler(_fh)


def _log_te_decision(flow_id: str, src_dpid: int, dst_dpid: int,
                     path: list, summary: dict, trigger: str = 'new_flow'):
    """Append one TE decision record to te_decisions.log."""
    record = {
        'ts':       datetime.utcnow().isoformat() + 'Z',
        'flow_id':  flow_id,
        'src_dpid': src_dpid,
        'dst_dpid': dst_dpid,
        'te':       TE_ENABLED,
        'trigger':  trigger,
        'path':     summary.get('hops', []),
        'utils':    summary.get('utilizations', []),
        'max_util': summary.get('max_util', 0),
        'congested': summary.get('congested', False),
    }
    _te_log.info(json.dumps(record))


# ── Peer domain determination ─────────────────────────────────────────────────
_ALL_DOMAINS  = {'A', 'B', 'C'}
_PEER_DOMAINS = sorted(_ALL_DOMAINS - {DOMAIN_ID})

# ── Runtime registries ────────────────────────────────────────────────────────
_switch_registry: dict[int, dict] = {}   # dpid → {'ports': {no: name}}
_dp_map: dict[int, object]        = {}   # dpid → datapath object
_dp_map_lock = threading.Lock()

# Active inter-domain flow table:
# flow_id → {src_dpid, dst_dpid, dst_mac, path, installed_at}
_active_flows: dict[str, dict] = {}
_flow_lock = threading.Lock()

# Thread pool for parallel cross-domain /install_path calls.
# Max 8 workers: up to 4 remote hops × 2 concurrent TE flows.
# Using a pool (not bare threads) gives us Future.result() to wait on.
_peer_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='ew-peer')

# Static inter-domain links (subset owned by this domain)
_inter_links: list[dict] = []

# ── Static intra-domain link definitions ─────────────────────────────────────
# Keyed by domain ID — used to populate global_topology links correctly.
_DOMAIN_INTRA_LINKS = {
    'A': [
        {'src_dpid': 1, 'src_port': 1, 'dst_dpid': 2, 'dst_port': 1},
        {'src_dpid': 2, 'src_port': 2, 'dst_dpid': 3, 'dst_port': 1},
        {'src_dpid': 1, 'src_port': 2, 'dst_dpid': 3, 'dst_port': 2},
    ],
    'B': [
        {'src_dpid': 4, 'src_port': 1, 'dst_dpid': 5, 'dst_port': 1},
        {'src_dpid': 5, 'src_port': 2, 'dst_dpid': 6, 'dst_port': 1},
        {'src_dpid': 4, 'src_port': 2, 'dst_dpid': 6, 'dst_port': 2},
    ],
    'C': [
        {'src_dpid': 7, 'src_port': 1, 'dst_dpid': 8, 'dst_port': 1},
        {'src_dpid': 8, 'src_port': 2, 'dst_dpid': 9, 'dst_port': 1},
        {'src_dpid': 7, 'src_port': 2, 'dst_dpid': 9, 'dst_port': 2},
    ],
}


def _local_topology_snapshot() -> dict:
    """Build the topology dict served via GET /topology."""
    switches = {}
    for dpid, info in _switch_registry.items():
        switches[str(dpid)] = {
            'dpid':   dpid,
            'domain': DOMAIN_ID,
            'ports':  list(info.get('ports', {}).keys()),
        }
    return {
        'domain_id':   DOMAIN_ID,
        'switches':    switches,
        'links':       _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, []),
        'inter_links': [il for il in _inter_links
                        if il.get('src_port') is not None],
        'hosts':       {mac: info for mac, info in gt.get_hosts().items()
                        if info['dpid'] in DOMAIN_DPIDS},
    }


def _peer_url(domain: str, endpoint: str) -> str:
    port = DOMAIN_API_PORTS[domain]
    return f'http://127.0.0.1:{port}{endpoint}'


def _install_flow_on_peer(peer_domain: str, dpid: int, in_port: int,
                          out_port: int, eth_dst: str, priority: int,
                          idle_to: int, hard_to: int, flow_id: str):
    """POST /install_path to a peer controller to install a flow segment."""
    url = _peer_url(peer_domain, '/install_path')
    body = json.dumps({
        'dpid':     dpid,
        'in_port':  in_port,
        'out_port': out_port,
        'eth_dst':  eth_dst,
        'priority': priority,
        'idle_to':  idle_to,
        'hard_to':  hard_to,
        'flow_id':  flow_id,
    }).encode()
    try:
        resp = requests.post(url, data=body,
                             headers={'Content-Type': 'application/json',
                                      'X-Domain-Id': DOMAIN_ID},
                             timeout=3)
        _std_log.getLogger('ew_ctrl').info('[DEBUG-TE-HYPOTHESIS] /install_path to %s URL=%s STATUS=%s RESP=%s', peer_domain, url, resp.status_code, resp.text)
        return resp.status_code == 200
    except Exception as exc:
        _std_log.getLogger('ew_ctrl').warning(
            '[DEBUG-TE-HYPOTHESIS-FAIL] /install_path to %s URL=%s failed: %s', peer_domain, url, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Ryu App
# ─────────────────────────────────────────────────────────────────────────────

class EWController(app_manager.RyuApp):
    """
    East-West + Traffic Engineering domain controller (Phase 3+4).
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port: dict[int, dict] = defaultdict(dict)
        self.foreign_events: dict[int, int] = defaultdict(int)

        if not DOMAIN_DPIDS:
            self.logger.warning('[Domain %s] DOMAIN_DPIDS not set.', DOMAIN_ID)
        else:
            self.logger.info('[Domain %s] EW+TE Controller started. DPIDs=%s  TE=%s',
                             DOMAIN_ID, sorted(DOMAIN_DPIDS), TE_ENABLED)

        self._seed_static_topology()
        self._start_ew_infrastructure()

    # ── Startup helpers ───────────────────────────────────────────────────────

    def _seed_static_topology(self):
        """Seed global_topology with static intra + inter domain link info."""
        # Inter-domain links (this controller only exposes its side)
        _static_inter = [
            (3, 4),   # A ↔ B
            (6, 7),   # B ↔ C
            (3, 7),   # A ↔ C diagonal
        ]
        for src, dst in _static_inter:
            if src in DOMAIN_DPIDS or dst in DOMAIN_DPIDS:
                _inter_links.append({
                    'src_dpid': src,
                    'src_port': None,
                    'dst_dpid': dst,
                    'dst_port': None,
                })

        # Pre-populate port numbers from STATIC_LINKS definition in path_selector
        for src_dpid, src_port, dst_dpid, dst_port in STATIC_LINKS:
            for il in _inter_links:
                if il['src_dpid'] == src_dpid and il['dst_dpid'] == dst_dpid:
                    il['src_port'] = src_port
                    il['dst_port'] = dst_port
                elif il['src_dpid'] == dst_dpid and il['dst_dpid'] == src_dpid:
                    il['src_port'] = dst_port
                    il['dst_port'] = src_port

        # Seed intra-domain links into global topology immediately
        local_switches = {str(d): {'dpid': d, 'domain': DOMAIN_ID, 'ports': []}
                          for d in DOMAIN_DPIDS}
        local_links = _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, [])
        local_inter = [il for il in _inter_links if il.get('src_port') is not None]

        gt.merge_local_topology(DOMAIN_ID, local_switches, local_links, local_inter)
        self.logger.info('[Domain %s] Seeded %d switches, %d intra links, %d inter links',
                         DOMAIN_ID, len(local_switches), len(local_links), len(local_inter))

    def _flow_install_callback(self, data: dict) -> str:
        """
        Called by POST /install_path from a peer controller.
        Installs a flow rule on a switch in this domain.
        """
        dpid     = int(data['dpid'])
        in_port  = int(data['in_port'])
        out_port = int(data['out_port'])
        eth_dst  = data['eth_dst']
        priority = int(data.get('priority', PRI_INTER_DOMAIN))
        idle_to  = int(data.get('idle_to', IDLE_TO))
        hard_to  = int(data.get('hard_to', HARD_TO))
        flow_id  = data.get('flow_id', 'unknown')

        if dpid not in DOMAIN_DPIDS:
            raise ValueError(f'dpid={dpid} not in this domain ({DOMAIN_ID})')

        with _dp_map_lock:
            dp = _dp_map.get(dpid)
        if dp is None:
            raise RuntimeError(f'dpid={dpid} not connected yet')

        parser = dp.ofproto_parser
        match  = parser.OFPMatch(in_port=in_port, eth_dst=eth_dst)
        actions = [parser.OFPActionOutput(out_port)]

        self.logger.info('[DEBUG] _flow_install_callback: dpid=%d in_port=%d out_port=%d eth_dst=%s',
                         dpid, in_port, out_port, eth_dst)

        self._add_flow(dp, priority, match, actions, idle=idle_to, hard=hard_to)
        self.logger.info(
            '[Domain %s] /install_path: dpid=%d  in=%d→out=%d  dst=%s  flow=%s',
            DOMAIN_ID, dpid, in_port, out_port, eth_dst, flow_id)
        return f'installed dpid={dpid}'

    def _start_ew_infrastructure(self):
        """Launch Flask API and SyncAgent in background threads."""
        def _deferred():
            time.sleep(2)
            self._api_thread = start_api(
                domain_id=DOMAIN_ID,
                api_port=EW_API_PORT,
                local_topo_fn=_local_topology_snapshot,
                ew_log_path=EW_TRAFFIC_LOG,
                flow_install_fn=self._flow_install_callback,
            )
            self._sync_agent = start_sync_agent(
                domain_id=DOMAIN_ID,
                peer_domains=_PEER_DOMAINS,
                local_topo_fn=_local_topology_snapshot,
                ew_log_path=EW_TRAFFIC_LOG,
            )
            self.logger.info('[Domain %s] EW infra up: API=%d, TE=%s, peers=%s',
                             DOMAIN_ID, EW_API_PORT, TE_ENABLED, _PEER_DOMAINS)

        threading.Thread(target=_deferred, daemon=True, name='ew-init').start()

    # ── PortStats polling ──────────────────────────────────────────────────────

    def _start_stats_polling(self):
        """Start periodic PortStats + congestion re-evaluation greenlets."""
        def _stats_poll():
            while True:
                hub.sleep(STATS_INTERVAL)
                try:
                    with _dp_map_lock:
                        dps = list(_dp_map.values())
                    for dp in dps:
                        if dp.id in DOMAIN_DPIDS:
                            try:
                                self._request_port_stats(dp)
                            except Exception as exc:
                                self.logger.warning('[Domain %s] Failed to request PortStats for dpid=%d: %s', DOMAIN_ID, dp.id, exc)
                except Exception as exc:
                    self.logger.error('[Domain %s] Critical error in _stats_poll: %s', DOMAIN_ID, exc)

        def _congestion_monitor():
            while True:
                hub.sleep(REEVAL_INTERVAL)
                self._reeval_congested_flows()

        hub.spawn(_stats_poll)
        hub.spawn(_congestion_monitor)

    def _request_port_stats(self, dp):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dp   = ev.msg.datapath
        dpid = dp.id
        if dpid not in DOMAIN_DPIDS:
            return
        gt.update_link_state_local(dpid, ev.msg.body)

    # ── Congestion re-evaluation ───────────────────────────────────────────────

    def _reeval_congested_flows(self):
        """
        Check if any active inter-domain flow's path has become congested.
        If so, log it as a trigger for new-flow rerouting.
        (Live flow migration is out of scope — only new flows get rerouted.)
        """
        util = gt.get_all_util_ratios()
        with _flow_lock:
            flows = dict(_active_flows)

        for flow_id, info in flows.items():
            path = info.get('path', [])
            if not path:
                continue
                
            # Exclude saturation flow (h4 <-> h9) from reactive TE
            src_mac = info.get('src_mac', '')
            dst_mac = info.get('dst_mac', '')
            if {src_mac, dst_mac} == {'00:00:00:00:00:04', '00:00:00:00:00:09'}:
                continue

            if is_congested(path, util):
                summary = summarize_path(path, util)
                self.logger.info(
                    '[Domain %s][TE] Congestion detected on flow %s: max_util=%.1f%%',
                    DOMAIN_ID, flow_id, summary['max_util'] * 100)
                _log_te_decision(
                    flow_id, info['src_dpid'], info['dst_dpid'],
                    path, summary, trigger='congestion_detected')

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
        dp.send_msg(parser.OFPPacketOut(
            datapath=dp, buffer_id=buffer_id,
            in_port=in_port, actions=actions, data=data))

    def _tree_flood_ports(self, dpid: int, in_port: int) -> list[int]:
        """
        Compute the set of output ports for a broadcast/unknown-unicast flood
        on switch `dpid` arriving from `in_port`.

        Like final_year/qos_controller.py _get_tree_ports(), this:
          • Includes ALL host-side ports (anything not a switch-to-switch link)
          • Includes ONLY intra-domain spanning-tree switch ports (never the
            inter-domain boundary ports — those stay blocked for broadcasts)
          • Excludes in_port itself

        The intra-domain spanning tree is the simple chain (not the triangle):
          Domain A: s1—s2—s3   (s1↔s3 back-link is excluded = already DROP-ruled)
          Domain B: s4—s5—s6
          Domain C: s7—s8—s9
        """
        # Intra-domain tree neighbors (DPID -> [neighbor DPIDs in spanning tree])
        # This is the chain, not the full triangle.
        TREE_NEIGHBORS: dict[int, list[int]] = {
            1: [2],        # s1: only to s2 (not s3, that's the hypotenuse)
            2: [1, 3],     # s2: to s1 and s3
            3: [2],        # s3: only to s2 (not s1 hypotenuse; inter-domain s4,s7 via TE only)
            4: [5],        # s4: only to s5
            5: [4, 6],     # s5: to s4 and s6
            6: [5],        # s6: only to s5
            7: [8],        # s7: only to s8
            8: [7, 9],     # s8: to s7 and s9
            9: [8],        # s9: only to s8
        }

        # All switch-to-switch ports for this dpid (intra + inter domain)
        all_sw_ports: set[int] = set()
        for link in _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, []):
            if link['src_dpid'] == dpid:
                all_sw_ports.add(link['src_port'])
            elif link['dst_dpid'] == dpid:
                all_sw_ports.add(link['dst_port'])
        for il in _inter_links:
            if il.get('src_port') and il['src_dpid'] == dpid:
                all_sw_ports.add(il['src_port'])
            if il.get('dst_port') and il['dst_dpid'] == dpid:
                all_sw_ports.add(il['dst_port'])

        known_ports = set(_switch_registry.get(dpid, {}).get('ports', {}).keys())
        if not known_ports:
            # Fall back to all registered ports minus in_port
            return [p for p in range(1, 10) if p != in_port]

        output_ports: list[int] = []

        # 1. Add host-side ports (all ports that are NOT switch-to-switch)
        for port in known_ports:
            if port != in_port and port not in all_sw_ports:
                output_ports.append(port)

        # 2. Add spanning-tree switch ports (intra-domain chain only, never inter-domain)
        for neighbor_dpid in TREE_NEIGHBORS.get(dpid, []):
            # Find the port on this switch that connects to neighbor_dpid
            for link in _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, []):
                if link['src_dpid'] == dpid and link['dst_dpid'] == neighbor_dpid:
                    p = link['src_port']
                    if p and p != in_port:
                        output_ports.append(p)
                elif link['dst_dpid'] == dpid and link['src_dpid'] == neighbor_dpid:
                    p = link['dst_port']
                    if p and p != in_port:
                        output_ports.append(p)

        return output_ports

    # ── Switch handshake ──────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp    = ev.msg.datapath
        dpid  = dp.id
        ofp   = dp.ofproto
        parser = dp.ofproto_parser

        if not self._owned(dpid):
            self.foreign_events[dpid] += 1
            self.logger.warning('[Domain %s] SwitchFeatures from FOREIGN dpid=%d',
                                DOMAIN_ID, dpid)
            return

        self.logger.info('[Domain %s] Switch connected: dpid=%d', DOMAIN_ID, dpid)

        with _dp_map_lock:
            _dp_map[dpid] = dp

        _switch_registry.setdefault(dpid, {'ports': {}})

        # Table-miss → CONTROLLER
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, PRI_MISS, match, actions, idle=0, hard=0)

        # Update global topology with this switch
        gt.merge_local_topology(
            DOMAIN_ID,
            {str(dpid): {'dpid': dpid, 'domain': DOMAIN_ID,
                         'ports': list(_switch_registry[dpid]['ports'].keys())}},
            links=_DOMAIN_INTRA_LINKS.get(DOMAIN_ID, []),
            inter_links=[il for il in _inter_links if il.get('src_port') is not None],
        )

        if len(_dp_map) == 1:
            self._start_stats_polling()

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, ev):
        dp   = ev.msg.datapath
        dpid = dp.id
        if dpid not in DOMAIN_DPIDS:
            return
        ports = {p.port_no: p.name.decode('utf-8', errors='replace')
                 for p in ev.msg.body}
        _switch_registry.setdefault(dpid, {})['ports'] = ports

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
            self.logger.warning('[Domain %s] PacketIn FOREIGN dpid=%d', DOMAIN_ID, dpid)
            return

        in_port = msg.match['in_port']
        pkt     = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return

        dst = eth_pkt.dst
        src = eth_pkt.src

        if eth_pkt.ethertype in (ether_types.ETH_TYPE_LLDP, 0x8809):
            return

        # Extract IP for host registration
        ip_src = ''
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            ip_src = ip_pkt.src

        # MAC learning + host registration
        # IMPORTANT: Do NOT learn MACs arriving on inter-domain (boundary) ports.
        # If we did, L2 forwarding would short-circuit TE on subsequent packets
        # (after ARP floods, s3 would "know" h12 is on port 4 and bypass TE).
        _inter_in_ports = {
            il['src_port'] for il in _inter_links
            if il.get('src_port') and il['src_dpid'] == dpid
        } | {
            il['dst_port'] for il in _inter_links
            if il.get('dst_port') and il['dst_dpid'] == dpid
        }
        
        _intra_in_ports = {
            l['src_port'] for l in _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, [])
            if l['src_dpid'] == dpid
        } | {
            l['dst_port'] for l in _DOMAIN_INTRA_LINKS.get(DOMAIN_ID, [])
            if l['dst_dpid'] == dpid
        }

        if src != 'ff:ff:ff:ff:ff:ff':
            if in_port not in _inter_in_ports:
                self.mac_to_port[dpid][src] = in_port
            if in_port not in _inter_in_ports and in_port not in _intra_in_ports:
                gt.update_host(src, dpid, in_port, ip=ip_src)

        table = self.mac_to_port[dpid]

        # ── Inter-domain check FIRST — before L2 table lookup ─────────────
        # If the destination MAC is known in the global topology as belonging
        # to a different domain, ALWAYS route via TE — never via the local
        # L2 table.  This guarantees TE intercepts even if a stale L2 entry
        # from earlier flooding exists on an inter-domain port.
        host_info = gt.get_host(dst)
        if host_info is not None:
            dst_dpid   = host_info['dpid']
            dst_domain = gt.get_switches().get(str(dst_dpid), {}).get('domain')
            src_domain = DPID_DOMAIN.get(dpid)
            if dst_domain is not None and dst_domain != src_domain:
                self._handle_inter_domain(dp, msg, dpid, in_port, src, dst,
                                          dst_dpid, dst_domain)
                return

        # ── Known LOCAL destination → L2 forwarding ───────────────────────
        if dst in table:
            out_port = table[dst]
            actions  = [parser.OFPActionOutput(out_port)]
            match    = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(dp, PRI_LEARNED, match, actions)
            data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
            self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)
            return

        # ── Fallback: domain-scoped spanning tree flood ────────────────────
        # Use explicit port list instead of OFPP_FLOOD to avoid sending
        # broadcasts out inter-domain ports (which would either cause
        # loops or be dropped by the TE drop rules installed there).
        flood_ports = self._tree_flood_ports(dpid, in_port)
        if flood_ports:
            actions = [parser.OFPActionOutput(p) for p in flood_ports]
        else:
            actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)


    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error_msg_handler(self, ev):
        msg = ev.msg
        self.logger.error(
            '[Domain %s] OFPErrorMsg received: type=0x%02x code=0x%02x message=%s',
            DOMAIN_ID, msg.type, msg.code, repr(msg.data))

    # ── Inter-domain TE forwarding ─────────────────────────────────────────────

    def _handle_inter_domain(self, dp, msg, src_dpid: int, in_port: int,
                             src_mac: str, dst_mac: str,
                             dst_dpid: int, dst_domain: str):
        """
        Select a TE path from src_dpid to dst_dpid, install flow rules
        on every switch along the path, log the decision.
        """
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        # Use pre-computed utilization ratios (merged from all 3 domains via EW sync).
        # This avoids the stale-cache problem of re-deriving rates from raw byte counts.
        util = gt.get_all_util_ratios()

        # Look up the destination host's actual switch port for the final-hop rule.
        _dst_host_info = gt.get_host(dst_mac)
        dst_out_port = _dst_host_info['port'] if _dst_host_info else 1

        # Look up the source host's true attachment switch.
        # This is critical: the PacketIn may arrive at an INTERMEDIATE switch (e.g. s3)
        # after being flooded from the edge switch (s1). If we compute the path starting
        # from s3 instead of s1, the rule at s1 is never installed and traffic loops.
        _src_host_info = gt.get_host(src_mac)
        if _src_host_info is not None:
            true_src_dpid    = _src_host_info['dpid']
            true_src_in_port = _src_host_info['port']
        else:
            # GT doesn't know the source yet (race during pre-warm); use the current switch.
            true_src_dpid    = src_dpid
            true_src_in_port = in_port

        # Compute path from the true source host attachment switch.
        path = compute_path(true_src_dpid, dst_dpid, util,
                            src_in_port=true_src_in_port,
                            dst_out_port=dst_out_port,
                            te_enabled=TE_ENABLED)
        if not path:
            self.logger.warning('[Domain %s][TE] No path from dpid=%d to %d — flooding',
                                DOMAIN_ID, true_src_dpid, dst_dpid)
            actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
            data    = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
            self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)
            return


        flow_id = str(uuid.uuid4())[:8]
        summary = summarize_path(path, util)
        _log_te_decision(flow_id, true_src_dpid, dst_dpid, path, summary)

        self.logger.info(
            '[Domain %s][TE] flow=%s  %d→%d  path=%s  max_util=%.1f%%  TE=%s',
            DOMAIN_ID, flow_id, true_src_dpid, dst_dpid,
            '→'.join(f's{d}:p{p}' for d, _, p in path),
            summary['max_util'] * 100, TE_ENABLED)

        # ── Install flow rules hop by hop ─────────────────────────────────────
        # CRITICAL: remote /install_path calls MUST complete before we send
        # packet_out, otherwise the forwarded packet arrives at a downstream
        # switch before its flow rule is in place → table-miss → TCP SYN loop.
        #
        # Strategy:
        #   1. Install ALL local-domain rules immediately (fast, in-process).
        #   2. Fire ALL remote /install_path calls in parallel threads.
        #   3. Wait (with timeout) for ALL remote installs to complete.
        #   4. THEN send packet_out.
        #
        # This adds ~10-50ms latency to the first packet of each new TE flow,
        # which is acceptable for cross-domain path setup.

        peer_futures = []  # (future, peer_domain, dpid) for logging

        for hop_dpid, in_p, out_port in path:
            hop_domain = DPID_DOMAIN.get(hop_dpid)

            if hop_domain == DOMAIN_ID:
                # Install locally — synchronous, fast
                with _dp_map_lock:
                    hop_dp = _dp_map.get(hop_dpid)
                if hop_dp is not None:
                    match   = parser.OFPMatch(in_port=in_p, eth_dst=dst_mac)
                    actions_local = [parser.OFPActionOutput(out_port)]
                    self._add_flow(hop_dp, PRI_INTER_DOMAIN, match, actions_local,
                                   idle=IDLE_TO, hard=HARD_TO)
                    self.logger.debug(
                        '[Domain %s][TE] Local rule: dpid=%d in=%d→out=%d dst=%s',
                        DOMAIN_ID, hop_dpid, in_p, out_port, dst_mac)
            else:
                # Queue remote install — fire in parallel, wait before packet_out
                fut = _peer_executor.submit(
                    _install_flow_on_peer,
                    hop_domain, hop_dpid, in_p, out_port,
                    dst_mac, PRI_INTER_DOMAIN, IDLE_TO, HARD_TO, flow_id)
                peer_futures.append((fut, hop_domain, hop_dpid))

        # Wait for all remote installs (max 2s total — 3s per call timeout already set)
        for fut, peer_domain, hop_dpid in peer_futures:
            try:
                ok = fut.result(timeout=2.0)
                self.logger.debug(
                    '[Domain %s][TE] Remote rule installed: domain=%s dpid=%d ok=%s',
                    DOMAIN_ID, peer_domain, hop_dpid, ok)
            except Exception as exc:
                self.logger.error(
                    '[Domain %s][TE] Remote /install_path FAILED: domain=%s dpid=%d err=%s',
                    DOMAIN_ID, peer_domain, hop_dpid, exc)

        # Record active flow
        with _flow_lock:
            _active_flows[flow_id] = {
                'src_dpid': true_src_dpid,
                'dst_dpid': dst_dpid,
                'src_mac':  src_mac,
                'dst_mac':  dst_mac,
                'path':     path,
                'installed_at': time.time(),
            }

        # Send the initial packet out via the CURRENT switch's hop in the path.
        # path may start from true_src_dpid (e.g. s1) while the PacketIn arrived
        # at src_dpid (e.g. s3). Find the current switch's position in the path.
        current_hop = next(
            ((d, ip, op) for d, ip, op in path if d == src_dpid), None)
        cur_out_port = current_hop[2] if current_hop is not None else path[0][2]
        actions = [parser.OFPActionOutput(cur_out_port)]
        data    = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        self._send_packet_out(dp, msg.buffer_id, in_port, actions, data)


