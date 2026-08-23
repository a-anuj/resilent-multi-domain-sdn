#!/usr/bin/env python3
"""
controllers/domain_controller.py
---------------------------------
Domain-scoped OpenFlow 1.3 L2 learning switch.

Launch (one process per domain):
    DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 \
        ryu-manager controllers/domain_controller.py \
        --ofp-tcp-listen-port 6633

    DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 \
        ryu-manager controllers/domain_controller.py \
        --ofp-tcp-listen-port 6634

    DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 \
        ryu-manager controllers/domain_controller.py \
        --ofp-tcp-listen-port 6635

Environment variables
---------------------
DOMAIN_ID    : Label for this controller (A / B / C)
DOMAIN_DPIDS : Comma-separated list of DPID integers owned by this domain
"""

import os
from collections import defaultdict

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                    set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

# ── Domain configuration from environment ────────────────────────────────────
DOMAIN_ID    = os.environ.get('DOMAIN_ID', 'UNKNOWN')
_raw         = os.environ.get('DOMAIN_DPIDS', '')
DOMAIN_DPIDS = frozenset(int(d) for d in _raw.split(',') if d.strip().isdigit())

# Flow priorities / timeouts  (identical to baseline)
PRI_MISS    = 0
PRI_LEARNED = 10
IDLE_TO     = 30
HARD_TO     = 300


class DomainController(app_manager.RyuApp):
    """
    One instance per domain.  Only installs rules on switches whose DPID is
    in DOMAIN_DPIDS.  PacketIn events from foreign switches are counted and
    logged as warnings (should never happen if topology is wired correctly).
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port   : dict[int, dict] = defaultdict(dict)
        self.foreign_events: dict[int, int]  = defaultdict(int)

        if not DOMAIN_DPIDS:
            self.logger.warning(
                '[Domain %s] DOMAIN_DPIDS not set — this controller will '
                'ignore ALL switches.', DOMAIN_ID)
        else:
            self.logger.info(
                '[Domain %s] started. Owned DPIDs: %s',
                DOMAIN_ID, sorted(DOMAIN_DPIDS))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _owned(self, dpid: int) -> bool:
        return dpid in DOMAIN_DPIDS

    def _add_flow(self, dp, priority, match, actions,
                  idle=IDLE_TO, hard=HARD_TO):
        ofp   = dp.ofproto
        parser= dp.ofproto_parser
        inst  = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod   = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst, idle_timeout=idle, hard_timeout=hard)
        dp.send_msg(mod)

    # ── Switch handshake ──────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp    = ev.msg.datapath
        dpid  = dp.id
        ofp   = dp.ofproto
        parser= dp.ofproto_parser

        if not self._owned(dpid):
            self.foreign_events[dpid] += 1
            self.logger.warning(
                '[Domain %s] SwitchFeatures from FOREIGN dpid=%d '
                '— ignoring. (Check topology wiring!)', DOMAIN_ID, dpid)
            return

        self.logger.info('[Domain %s] Switch connected: dpid=%d', DOMAIN_ID, dpid)

        # Install table-miss: send to controller
        match  = parser.OFPMatch()
        actions= [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, PRI_MISS, match, actions, idle=0, hard=0)

    # ── Packet-In handler ─────────────────────────────────────────────────────

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg   = ev.msg
        dp    = msg.datapath
        dpid  = dp.id
        ofp   = dp.ofproto
        parser= dp.ofproto_parser

        if not self._owned(dpid):
            self.foreign_events[dpid] += 1
            self.logger.warning(
                '[Domain %s] PacketIn from FOREIGN dpid=%d (total=%d). '
                'Dropping.', DOMAIN_ID, dpid, self.foreign_events[dpid])
            return

        in_port = msg.match['in_port']
        pkt     = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        if eth_pkt is None:
            return

        dst = eth_pkt.dst
        src = eth_pkt.src

        # ── Ignore LLDP / STP frames ──────────────────────────────────────
        if eth_pkt.ethertype in (ether_types.ETH_TYPE_LLDP,
                                  0x8809):   # LACP / Slow Protocols
            return

        # ── MAC learning ──────────────────────────────────────────────────
        table = self.mac_to_port[dpid]
        table[src] = in_port

        if dst in table:
            out_port = table[dst]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install unicast flow (skip for flood to avoid stale broadcast rules)
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofp.OFP_NO_BUFFER:
                self._add_flow(dp, PRI_LEARNED, match, actions,
                               idle=IDLE_TO, hard=HARD_TO)
                return
            self._add_flow(dp, PRI_LEARNED, match, actions,
                           idle=IDLE_TO, hard=HARD_TO)

        # Send the current packet out
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id,
            in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)
