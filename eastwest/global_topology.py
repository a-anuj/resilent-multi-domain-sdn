#!/usr/bin/env python3
"""
eastwest/global_topology.py
----------------------------
Thread-safe in-process store for the merged global view of the full
multi-domain network graph.

Each controller process maintains its own instance.  The sync agent
populates it by merging data received from peer controllers' REST APIs.

Data model
──────────
  switches  : {dpid_str: {domain, datapath_id, ports: [...]}}
  links     : [{src_dpid, src_port, dst_dpid, dst_port, domain}]
  inter_links : [{src_dpid, src_port, dst_dpid, dst_port}]   ← cross-domain
  hosts     : {mac: {dpid, port, ip}}
  link_state: {dpid_str: {port_no: {tx_bytes, rx_bytes, tx_pkts, rx_pkts,
                                    timestamp}}}
  peer_meta : {domain_id: {last_seen_ts, seq}}

NOTE ─ DELIBERATE BASELINE VULNERABILITY
─────────────────────────────────────────
All data merged into this structure is accepted as-is from peer
controllers over an unauthenticated, unvalidated REST channel.  There
is NO signature checking, NO schema validation, and NO sanity-checking
of received topology data (e.g., we do not verify that claimed DPIDs
match what OVS actually reports).

This is intentional design for the Phase 3 baseline: later phases will
exploit this exact weakness (topology poisoning / link-state injection
attacks) and then patch it with HMAC signing + field validation.
Do NOT add validation here until the attack phase is complete.
"""

import threading
import time
from typing import Any

_LOCK = threading.RLock()

# ── In-memory global view ─────────────────────────────────────────────────────

_state: dict[str, Any] = {
    'switches':    {},   # dpid_str -> switch info
    'links':       [],   # intra-domain edges (from all peers)
    'inter_links': [],   # cross-domain boundary edges
    'hosts':       {},   # mac -> {dpid, port, ip}
    'link_state':  {},   # dpid_str -> {port_no -> cumulative stats dict}
    'util_rates':  {},   # dpid_str -> {port_no -> bytes/sec utilization ratio}
    'peer_meta':   {},   # domain_id -> {last_seen_ts, seq}
}

# ── Route cache: dst_mac -> (next_hop_dpid, out_port) ────────────────────────
# Populated lazily by inter-domain forwarding logic.  Cleared on topology update.
_route_cache: dict[str, tuple[int, int]] = {}

# ── Previous sample cache for rate computation ───────────────────────────────
_prev_stats: dict[str, dict[str, dict]] = {}  # dpid_str -> {port_str -> prev sample}


# ── Public accessors ──────────────────────────────────────────────────────────

def snapshot() -> dict:
    """Return a deep-copy snapshot of the full global state (safe for JSON serialisation)."""
    import copy
    with _LOCK:
        return copy.deepcopy(_state)


def get_switches() -> dict:
    with _LOCK:
        return dict(_state['switches'])


def get_links() -> list:
    with _LOCK:
        return list(_state['links'])


def get_inter_links() -> list:
    with _LOCK:
        return list(_state['inter_links'])


def get_link_state() -> dict:
    """Returns raw cumulative byte/packet counters per port."""
    with _LOCK:
        return dict(_state['link_state'])


def get_utilization_rates() -> dict:
    """
    Returns per-port utilization ratios (0.0–1.0, bytes/sec basis).
    Updated every time update_link_state_local() is called.
    """
    with _LOCK:
        import copy
        return copy.deepcopy(_state['util_rates'])


def get_port_utilization(dpid: int, port: int) -> float:
    """Convenience: get a single port's utilization ratio (0.0 if unknown)."""
    with _LOCK:
        return _state['util_rates'].get(str(dpid), {}).get(str(port), 0.0)


def get_host(mac: str) -> dict | None:
    with _LOCK:
        return _state['hosts'].get(mac)


def get_peer_meta() -> dict:
    with _LOCK:
        return dict(_state['peer_meta'])


# ── Merging helpers ───────────────────────────────────────────────────────────

def merge_local_topology(domain_id: str, switches: dict, links: list,
                         inter_links: list):
    """
    Called once at controller start-up to populate the local domain's view.
    switches  : {dpid_str: {ports: [...], ...}}
    links     : [{src_dpid, src_port, dst_dpid, dst_port}]
    inter_links: [{src_dpid, src_port, dst_dpid, dst_port}]
    """
    with _LOCK:
        for dpid, info in switches.items():
            info['domain'] = domain_id
            _state['switches'][dpid] = info

        # Replace all links that were previously from this domain
        _state['links'] = [l for l in _state['links']
                           if l.get('domain') != domain_id]
        for l in links:
            l['domain'] = domain_id
            _state['links'].append(l)

        # Inter-links: store by src/dst pair (dedup)
        existing = {(il['src_dpid'], il['src_port'], il['dst_dpid'], il['dst_port'])
                    for il in _state['inter_links']}
        for il in inter_links:
            key = (il['src_dpid'], il['src_port'], il['dst_dpid'], il['dst_port'])
            if key not in existing:
                _state['inter_links'].append(il)
                existing.add(key)

        _route_cache.clear()


def merge_peer_topology(domain_id: str, data: dict):
    """
    Merge a /topology response from a peer controller.
    data keys: switches, links, inter_links   (same schema as merge_local_topology)
    """
    with _LOCK:
        switches   = data.get('switches', {})
        links      = data.get('links', [])
        inter_links = data.get('inter_links', [])

        for dpid, info in switches.items():
            info['domain'] = domain_id
            _state['switches'][dpid] = info

        _state['links'] = [l for l in _state['links']
                           if l.get('domain') != domain_id]
        for l in links:
            l['domain'] = domain_id
            _state['links'].append(l)

        existing = {(il['src_dpid'], il['src_port'], il['dst_dpid'], il['dst_port'])
                    for il in _state['inter_links']}
        for il in inter_links:
            key = (il['src_dpid'], il['src_port'], il['dst_dpid'], il['dst_port'])
            if key not in existing:
                _state['inter_links'].append(il)
                existing.add(key)

        _state['peer_meta'][domain_id] = {
            'last_seen_ts': time.time(),
            'seq': data.get('seq', -1),
        }
        _route_cache.clear()


def merge_peer_link_state(domain_id: str, data: dict):
    """
    Merge a /linkstate response from a peer.
    data keys: link_state -> {dpid_str: {port_no: stats_dict}}
    """
    with _LOCK:
        for dpid, ports in data.get('link_state', {}).items():
            if dpid not in _state['link_state']:
                _state['link_state'][dpid] = {}
            _state['link_state'][dpid].update(ports)

        if domain_id not in _state['peer_meta']:
            _state['peer_meta'][domain_id] = {}
        _state['peer_meta'][domain_id]['last_seen_ts'] = time.time()


def update_host(mac: str, dpid: int, port: int, ip: str = ''):
    """Called by packet-in handler to register a newly seen host."""
    with _LOCK:
        _state['hosts'][mac] = {
            'dpid': dpid,
            'port': port,
            'ip':   ip,
        }


# Link capacity in bits/sec (10 Mbps to match LINK_BW in topology)
_LINK_BW_BPS = 10 * 1_000_000


def update_link_state_local(dpid: int, port_stats: list):
    """
    Called by the Ryu PortStatsReply handler to update local link utilization.
    Computes instantaneous bytes/sec rates and utilization ratios alongside
    cumulative counters.
    port_stats : list of OFPPortStats objects.
    """
    ts = time.time()
    dpid_str = str(dpid)
    with _LOCK:
        if dpid_str not in _state['link_state']:
            _state['link_state'][dpid_str] = {}
        if dpid_str not in _state['util_rates']:
            _state['util_rates'][dpid_str] = {}
        if dpid_str not in _prev_stats:
            _prev_stats[dpid_str] = {}

        for stat in port_stats:
            pno     = stat.port_no
            pno_str = str(pno)
            tx_bytes = stat.tx_bytes
            rx_bytes = stat.rx_bytes

            # Store cumulative counters
            _state['link_state'][dpid_str][pno_str] = {
                'tx_bytes': tx_bytes,
                'rx_bytes': rx_bytes,
                'tx_pkts':  stat.tx_packets,
                'rx_pkts':  stat.rx_packets,
                'timestamp': ts,
            }

            # Compute instantaneous rate
            prev = _prev_stats[dpid_str].get(pno_str)
            if prev is not None:
                dt = ts - prev['ts']
                if dt > 0:
                    bps_tx = (tx_bytes - prev['tx_bytes']) * 8.0 / dt
                    bps_rx = (rx_bytes - prev['rx_bytes']) * 8.0 / dt
                    ratio  = min(max(bps_tx, bps_rx) / _LINK_BW_BPS, 1.0)
                    _state['util_rates'][dpid_str][pno_str] = {
                        'bps_tx':  round(bps_tx, 2),
                        'bps_rx':  round(bps_rx, 2),
                        'ratio':   round(ratio, 4),
                        'timestamp': ts,
                    }

            _prev_stats[dpid_str][pno_str] = {
                'tx_bytes': tx_bytes,
                'rx_bytes': rx_bytes,
                'ts': ts,
            }


# ── Route resolution ──────────────────────────────────────────────────────────

def find_inter_domain_nexthop(src_dpid: int, dst_mac: str) -> tuple[int, int] | None:
    """
    Given a source DPID and an unknown destination MAC, return (next_hop_dpid,
    out_port) toward the inter-domain boundary, or None if not reachable.

    Strategy (simple greedy):
      1. Find which domain the dst_mac belongs to (from hosts table).
      2. Find an inter-domain link connecting our domain to that domain.
      3. Return the local side of that link as the next hop.
    """
    with _LOCK:
        host_info = _state['hosts'].get(dst_mac)
        if host_info is None:
            return None   # destination not yet seen across any domain

        dst_dpid    = host_info['dpid']
        dst_dpid_str = str(dst_dpid)

        # Which domain owns dst_dpid?
        dst_domain = _state['switches'].get(dst_dpid_str, {}).get('domain')
        if dst_domain is None:
            return None

        # Which domain owns src_dpid?
        src_dpid_str = str(src_dpid)
        src_domain = _state['switches'].get(src_dpid_str, {}).get('domain')
        if src_domain is None or src_domain == dst_domain:
            return None   # same domain — not our job

        # Look for an inter-domain link from src_domain side toward dst_domain
        for il in _state['inter_links']:
            il_src_domain = _state['switches'].get(str(il['src_dpid']), {}).get('domain')
            il_dst_domain = _state['switches'].get(str(il['dst_dpid']), {}).get('domain')

            if il_src_domain == src_domain and il_dst_domain == dst_domain:
                # src switch must be src_dpid or reachable; for simplicity,
                # return the boundary switch+port on the src side.
                return (il['src_dpid'], il['src_port'])

            # Check reverse direction too
            if il_dst_domain == src_domain and il_src_domain == dst_domain:
                return (il['dst_dpid'], il['dst_port'])

        return None   # no direct inter-domain link found
