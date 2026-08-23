#!/usr/bin/env python3
"""
controllers/baseline_l2.py
--------------------------
Phase 1 – Baseline L2 Learning Switch (OpenFlow 1.3)

Behaviour
---------
1. On switch connect  → install a table-miss flow that sends everything to
                        the controller (priority 0, output=CONTROLLER).
2. On PacketIn        → learn src_mac → in_port mapping for this datapath.
3. If dst_mac known   → install a proactive flow rule and unicast the buffered
                        packet; otherwise flood.

Run with:
    ryu-manager controllers/baseline_l2.py [--ofp-tcp-listen-port 6653]
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

import logging

LOG = logging.getLogger('baseline_l2')


class BaselineL2Switch(app_manager.RyuApp):
    """Single-controller L2 learning switch — Phase 1 baseline."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Flow priorities
    PRIORITY_TABLE_MISS = 0
    PRIORITY_LEARNED    = 10

    # Flow timeouts (seconds)
    IDLE_TIMEOUT  = 30   # remove flow after 30 s of inactivity
    HARD_TIMEOUT  = 300  # remove flow after 5 min regardless

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # mac_to_port[dpid][mac] = port_no
        self.mac_to_port: dict[int, dict[str, int]] = {}

    # ------------------------------------------------------------------
    # Helper: add a flow entry to a datapath
    # ------------------------------------------------------------------
    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0, buffer_id=None):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        kwargs = dict(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        )
        if buffer_id is not None:
            kwargs['buffer_id'] = buffer_id

        mod = parser.OFPFlowMod(**kwargs)
        datapath.send_msg(mod)

    # ------------------------------------------------------------------
    # Switch handshake complete → install table-miss entry
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser

        LOG.info("Switch connected: dpid=%016x", datapath.id)

        # Table-miss: match everything, send to controller, no timeout
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(
            ofproto.OFPP_CONTROLLER,
            ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, self.PRIORITY_TABLE_MISS, match, actions)

    # ------------------------------------------------------------------
    # PacketIn handler — learn + (optionally) install flow + forward
    # ------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match['in_port']
        dpid     = datapath.id

        # Parse Ethernet header
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore LLDP (and other non-IP/ARP traffic we don't need to learn)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src

        # ── Learn ──────────────────────────────────────────────────────
        self.mac_to_port.setdefault(dpid, {})
        if self.mac_to_port[dpid].get(src) != in_port:
            self.mac_to_port[dpid][src] = in_port
            LOG.info("Learned: dpid=%016x  src=%s  port=%s", dpid, src, in_port)

        # ── Decide output port ──────────────────────────────────────────
        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        actions = [parser.OFPActionOutput(out_port)]

        # ── Install flow rule when destination is known ─────────────────
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)

            # Avoid installing if packet is still in switch buffer
            buf_id = msg.buffer_id if msg.buffer_id != ofproto.OFP_NO_BUFFER \
                     else None

            self._add_flow(
                datapath,
                self.PRIORITY_LEARNED,
                match,
                actions,
                idle_timeout=self.IDLE_TIMEOUT,
                hard_timeout=self.HARD_TIMEOUT,
                buffer_id=buf_id,
            )

            # If buffer_id was valid, the switch already sent the packet;
            # no need to emit an explicit PacketOut.
            if buf_id is not None:
                return

        # ── Send PacketOut (flood or first unicast before flow install) ──
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)
