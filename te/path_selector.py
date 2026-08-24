#!/usr/bin/env python3
"""
te/path_selector.py
--------------------
Load-aware path computation for multi-domain SDN traffic engineering.

Algorithm
─────────
Uses Dijkstra's weighted shortest path on the global topology graph
where each edge weight = current utilization ratio (0.0–1.0) of the
link, derived from OpenFlow PortStats (bytes/sec since last poll).

A utilization ratio of 0.0 means idle; 1.0 means at full link capacity
(LINK_BW_BPS configured below).  Edges above CONGESTION_THRESHOLD are
penalized with weight=PENALTY so they are only chosen as a last resort.

Path structure returned
───────────────────────
A path is a list of (dpid, out_port) tuples representing the sequence
of switch-port hops from the source domain boundary to the destination
domain boundary.  The controller on each domain installs the segment
that falls within its own DPID set.

Static topology wiring (Phase 2 topology/multi_domain_topo.py)
──────────────────────────────────────────────────────────────
Switches/DPIDs:
  Domain A: s1(1), s2(2), s3(3)
  Domain B: s4(4), s5(5), s6(6)
  Domain C: s7(7), s8(8), s9(9)

Intra-domain links (triangles):
  A: 1-2, 2-3, 1-3
  B: 4-5, 5-6, 4-6
  C: 7-8, 8-9, 7-9

Inter-domain links:
  s3(3) ↔ s4(4)  [A↔B]
  s6(6) ↔ s7(7)  [B↔C]
  s3(3) ↔ s7(7)  [A↔C diagonal]

This gives 3 distinct inter-domain paths between A and C:
  1. A→B→C  via s3-s4, s6-s7
  2. A→C     via s3-s7 direct (diagonal)
"""

import logging
import time
from typing import Any

import networkx as nx

log = logging.getLogger('te.path_selector')

# ── Configuration ─────────────────────────────────────────────────────────────

LINK_BW_BPS         = 10 * 1_000_000   # 10 Mbps (matches LINK_BW in topo)
CONGESTION_THRESHOLD = 0.70             # 70% utilization triggers reroute
PENALTY              = 1_000.0          # edge weight when congested
STATS_WINDOW_SEC     = 10.0             # interval between PortStats polls (must
                                        # match STATS_INTERVAL in ew_controller)

# ── Static topology definition ────────────────────────────────────────────────
# (src_dpid, src_port, dst_dpid, dst_port, capacity_bps)
# Port numbers here match the Mininet build order in multi_domain_topo.py.
# Each link appears once; the graph builder adds both directions.

STATIC_LINKS: list[tuple[int, int, int, int]] = [
    # Domain A triangle
    (1, 1, 2, 1),   # s1-p1 ↔ s2-p1
    (2, 2, 3, 1),   # s2-p2 ↔ s3-p1
    (1, 2, 3, 2),   # s1-p2 ↔ s3-p2
    # Domain B triangle
    (4, 1, 5, 1),   # s4-p1 ↔ s5-p1
    (5, 2, 6, 1),   # s5-p2 ↔ s6-p1
    (4, 2, 6, 2),   # s4-p2 ↔ s6-p2
    # Domain C triangle
    (7, 1, 8, 1),   # s7-p1 ↔ s8-p1
    (8, 2, 9, 1),   # s8-p2 ↔ s9-p1
    (7, 2, 9, 2),   # s7-p2 ↔ s9-p2
    # Inter-domain links
    (3, 3, 4, 3),   # s3-p3 ↔ s4-p3   A↔B
    (6, 3, 7, 3),   # s6-p3 ↔ s7-p4   B↔C
    (3, 4, 7, 4),   # s3-p4 ↔ s7-p5   A↔C diagonal
]

# Domain membership
DPID_DOMAIN = {
    1: 'A', 2: 'A', 3: 'A',
    4: 'B', 5: 'B', 6: 'B',
    7: 'C', 8: 'C', 9: 'C',
}


# ── Utilization rate cache ─────────────────────────────────────────────────────
# {dpid_str: {port_str: {prev_tx, prev_rx, prev_ts, bps_tx, bps_rx}}}
_rate_cache: dict[str, dict[str, dict]] = {}


def compute_utilization_rates(link_state: dict) -> dict[str, dict[str, float]]:
    """
    Given the raw cumulative link_state from global_topology, compute
    instantaneous TX utilization ratios (0.0–1.0) per port.

    Returns: {dpid_str: {port_str: utilization_ratio}}
    """
    global _rate_cache
    now  = time.time()
    rates: dict[str, dict[str, float]] = {}

    for dpid_str, ports in link_state.items():
        rates[dpid_str] = {}
        if dpid_str not in _rate_cache:
            _rate_cache[dpid_str] = {}

        for port_str, stats in ports.items():
            tx_bytes = stats.get('tx_bytes', 0)
            rx_bytes = stats.get('rx_bytes', 0)
            ts       = stats.get('timestamp', now)

            prev = _rate_cache[dpid_str].get(port_str)
            if prev is None:
                # First sample — store and assume idle
                _rate_cache[dpid_str][port_str] = {
                    'prev_tx': tx_bytes, 'prev_rx': rx_bytes, 'prev_ts': ts,
                    'bps_tx': 0.0, 'bps_rx': 0.0,
                }
                rates[dpid_str][port_str] = 0.0
                continue

            dt = ts - prev['prev_ts']
            if dt <= 0:
                rates[dpid_str][port_str] = prev.get('bps_tx', 0.0) / LINK_BW_BPS
                continue

            bps_tx = (tx_bytes - prev['prev_tx']) * 8.0 / dt
            bps_rx = (rx_bytes - prev['prev_rx']) * 8.0 / dt

            _rate_cache[dpid_str][port_str].update({
                'prev_tx': tx_bytes, 'prev_rx': rx_bytes, 'prev_ts': ts,
                'bps_tx': bps_tx, 'bps_rx': bps_rx,
            })

            # Utilization = max(TX, RX) / link capacity (half-duplex equivalent)
            ratio = max(bps_tx, bps_rx) / LINK_BW_BPS
            rates[dpid_str][port_str] = min(ratio, 1.0)

    return rates


def build_graph(utilization: dict[str, dict[str, float]]) -> nx.DiGraph:
    """
    Build a directed weighted NetworkX graph from the static topology.
    utilization: {dpid_str: {port_str: ratio}}  (0.0-1.0, pre-computed)
    """
    G = nx.DiGraph()


    for dpid in DPID_DOMAIN:
        G.add_node(dpid, domain=DPID_DOMAIN[dpid])

    for src_dpid, src_port, dst_dpid, dst_port in STATIC_LINKS:
        # Get utilization for the TX direction on src_port
        util = utilization.get(str(src_dpid), {}).get(str(src_port), 0.0)

        if util >= CONGESTION_THRESHOLD:
            weight = PENALTY
        else:
            # Weight = utilization ratio; idle links have weight near 0
            weight = max(util, 0.001)   # avoid zero-weight (Dijkstra ties)

        G.add_edge(src_dpid, dst_dpid,
                   weight=weight, util=util,
                   src_port=src_port, dst_port=dst_port)
        # Reverse direction: use the dst→src port utilization
        util_rev = utilization.get(str(dst_dpid), {}).get(str(dst_port), 0.0)
        weight_rev = PENALTY if util_rev >= CONGESTION_THRESHOLD else max(util_rev, 0.001)
        G.add_edge(dst_dpid, src_dpid,
                   weight=weight_rev, util=util_rev,
                   src_port=dst_port, dst_port=src_port)

    return G


def compute_path(src_dpid: int, dst_dpid: int,
                 utilization: dict,
                 src_in_port: int,
                 dst_out_port: int,
                 te_enabled: bool = True) -> list[tuple[int, int, int]]:
    """
    Compute the best path from src_dpid to dst_dpid.

    Parameters
    ──────────
    src_dpid    : source switch DPID
    dst_dpid    : destination switch DPID
    utilization : pre-computed {dpid_str: {port_str: ratio}} from gt.get_all_util_ratios()
    src_in_port : incoming port on the first switch
    dst_out_port: outgoing port on the last switch (to the destination host)
    te_enabled  : if False, uses hop-count shortest path (TE-off baseline)

    Returns
    ───────
    List of (dpid, in_port, out_port) tuples from src to dst (inclusive), or []
    if no path exists.
    """
    if src_dpid == dst_dpid:
        return []

    if te_enabled:
        # utilization is already a {dpid_str: {port_str: ratio}} dict —
        # pass directly to build_graph; no need to re-derive from raw bytes.
        G = build_graph(utilization)
        try:
            node_path = nx.dijkstra_path(G, src_dpid, dst_dpid, weight='weight')
        except nx.NetworkXNoPath:
            log.warning('[TE] No path from dpid=%d to dpid=%d', src_dpid, dst_dpid)
            return []
        except nx.NodeNotFound as e:
            log.warning('[TE] Node not found: %s', e)
            return []
    else:
        # TE disabled: hop-count shortest path
        G = nx.DiGraph()
        for dpid in DPID_DOMAIN:
            G.add_node(dpid)
        for src, sp, dst, dp in STATIC_LINKS:
            G.add_edge(src, dst, src_port=sp, dst_port=dp, weight=1)
            G.add_edge(dst, src, src_port=dp, dst_port=sp, weight=1)
        try:
            node_path = nx.shortest_path(G, src_dpid, dst_dpid, weight='weight')
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    # Convert node sequence → (dpid, in_port, out_port) sequence
    result: list[tuple[int, int, int]] = []
    current_in_port = src_in_port
    
    for i in range(len(node_path) - 1):
        u = node_path[i]
        v = node_path[i + 1]
        edge_data = G.get_edge_data(u, v)
        if edge_data is None:
            log.error('[TE] Missing edge %d→%d in graph', u, v)
            return []
        out_port = edge_data['src_port']
        result.append((u, current_in_port, out_port))
        current_in_port = edge_data['dst_port']
        
    # Add the final hop
    last_dpid = node_path[-1]
    result.append((last_dpid, current_in_port, dst_out_port))

    log.info('[TE] Path %d→%d: %s  (TE=%s)',
             src_dpid, dst_dpid,
             ' → '.join(f's{d}:in{i}->out{o}' for d, i, o in result),
             'ON' if te_enabled else 'OFF')
    return result



def path_utilizations(path: list[tuple[int, int, int]],
                      utilization: dict[str, dict[str, float]]) -> list[float]:
    """
    Return the utilization ratio for each hop in the path.
    utilization: pre-computed {dpid_str: {port_str: ratio}}
    """
    return [utilization.get(str(dpid), {}).get(str(out_port), 0.0)
            for dpid, in_port, out_port in path]


def is_congested(path: list[tuple[int, int, int]],
                 utilization: dict[str, dict[str, float]]) -> bool:
    """Return True if any link on the path exceeds CONGESTION_THRESHOLD."""
    return any(u >= CONGESTION_THRESHOLD
               for u in path_utilizations(path, utilization))


def summarize_path(path: list[tuple[int, int, int]],
                   utilization: dict[str, dict[str, float]]) -> dict[str, Any]:
    """
    Return a dict suitable for logging to te_decisions.log.
    utilization: pre-computed {dpid_str: {port_str: ratio}}
    """
    utils = path_utilizations(path, utilization)
    hop_strs = [f's{dpid}:p{out_port}' for dpid, in_port, out_port in path]
    return {
        'hops':          hop_strs,
        'utilizations':  [round(u, 4) for u in utils],
        'max_util':      round(max(utils, default=0.0), 4),
        'congested':     any(u >= CONGESTION_THRESHOLD for u in utils),
    }
