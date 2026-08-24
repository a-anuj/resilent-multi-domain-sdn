#!/usr/bin/env python3
"""
eastwest/ew_api.py
-------------------
Lightweight Flask REST API that exposes this controller's view to peers.

Endpoints
─────────
  GET  /topology   → local topology (switches, links, inter_links, seq)
  GET  /linkstate  → current per-port utilization stats
  POST /update     → receive topology/linkstate from a peer controller

Run mode
────────
This module is imported by sync_agent.py and ew_controller.py — it is
NOT a standalone script.  The Flask app is started in a daemon thread
so it does not block the Ryu event loop.

Security note
─────────────
# ── DELIBERATE BASELINE VULNERABILITY ────────────────────────────────────────
# This REST API has NO authentication (no API keys, no TLS, no HMAC signing).
# POST /update blindly merges whatever JSON payload a caller supplies.
# This is intentional: Phase 4 of the research will mount a topology
# poisoning attack by sending crafted /update payloads, and Phase 5 will
# add HMAC + schema validation to mitigate it.
# DO NOT add auth/validation here until the attack experiments are complete.
# ─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
from datetime import datetime

from flask import Flask, request, jsonify

# Shared state modules (populated by ew_controller.py / sync_agent.py)
from eastwest import global_topology as gt

log = logging.getLogger('ew_api')

_app   = Flask(__name__)
_local = threading.local()   # per-thread Flask ctx

# ── Module-level config (set by start_api()) ─────────────────────────────────
_domain_id    : str  = 'UNKNOWN'
_api_port     : int  = 8080
_ew_log_path  : str  = 'results/eastwest_traffic.log'
_local_topo_fn       = None    # callable() → dict with switches/links/inter_links
_flow_install_fn     = None    # callable(data: dict) → str  — registered by ew_controller
_seq          : int  = 0
_seq_lock             = threading.Lock()


def _next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def _ew_log(direction: str, peer_domain: str, endpoint: str,
            payload_bytes: int, status: str = 'OK'):
    """Append one line to the East-West traffic log."""
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    line = (f'{ts}  {direction:4s}  src={_domain_id:<3}  dst={peer_domain:<3}'
            f'  endpoint={endpoint:<12}  bytes={payload_bytes:>8}  status={status}\n')
    try:
        os.makedirs(os.path.dirname(_ew_log_path), exist_ok=True)
        with open(_ew_log_path, 'a') as f:
            f.write(line)
    except Exception as exc:
        log.warning('EW log write failed: %s', exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@_app.route('/topology', methods=['GET'])
def get_topology():
    """Return this controller's local topology view."""
    if _local_topo_fn is None:
        return jsonify({'error': 'topology not ready'}), 503

    topo = _local_topo_fn()
    topo['seq']       = _next_seq()
    topo['domain_id'] = _domain_id

    body = json.dumps(topo)
    # Log self-serve for tracing (direction='SEND', dst='*' means broadcast)
    _ew_log('SEND', '*', '/topology', len(body))
    return body, 200, {'Content-Type': 'application/json'}


@_app.route('/linkstate', methods=['GET'])
def get_linkstate():
    """Return current per-port utilization stats including live bytes/sec rates."""
    data = {
        'domain_id':   _domain_id,
        'link_state':  gt.get_link_state(),
        'util_rates':  gt.get_utilization_rates(),  # NEW: live bps + ratio
        'timestamp':   datetime.utcnow().isoformat() + 'Z',
    }
    body = json.dumps(data)
    _ew_log('SEND', '*', '/linkstate', len(body))
    return body, 200, {'Content-Type': 'application/json'}


@_app.route('/update', methods=['POST'])
def post_update():
    """
    Accept topology or linkstate update from a peer controller.

    NOTE ─ DELIBERATE BASELINE VULNERABILITY (see module docstring)
    The received JSON is merged into global_topology WITHOUT any
    validation or authentication.  A malicious peer (or MITM) can inject
    arbitrary switch/link data here.
    """
    body      = request.get_data()
    peer_domain = request.headers.get('X-Domain-Id', 'UNKNOWN')
    payload_sz  = len(body)

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        _ew_log('RECV', peer_domain, '/update', payload_sz, status='ERR_JSON')
        return jsonify({'error': str(exc)}), 400

    _ew_log('RECV', peer_domain, '/update', payload_sz)
    log.info('[EW-API] /update from domain=%s  bytes=%d', peer_domain, payload_sz)

    update_type = data.get('type', 'topology')
    if update_type == 'topology':
        gt.merge_peer_topology(peer_domain, data)
    elif update_type == 'linkstate':
        gt.merge_peer_link_state(peer_domain, data)
        # Also merge util_rates if present
        if 'util_rates' in data:
            with gt._LOCK:
                for dpid, ports in data['util_rates'].items():
                    if dpid not in gt._state['util_rates']:
                        gt._state['util_rates'][dpid] = {}
                    gt._state['util_rates'][dpid].update(ports)
    else:
        log.warning('[EW-API] Unknown update type: %s', update_type)

    return jsonify({'status': 'accepted', 'domain': _domain_id}), 200


@_app.route('/install_path', methods=['POST'])
def install_path():
    """
    Instruct this controller to install a flow rule segment for TE routing.

    Expected JSON body:
    {
      "eth_dst"    : "aa:bb:cc:dd:ee:ff",
      "eth_src"    : "11:22:33:44:55:66",   (optional — for exact match)
      "dpid"       : 3,                       (which switch to program)
      "in_port"    : 2,                       (match in_port)
      "out_port"   : 4,                       (output action)
      "priority"   : 50,
      "idle_to"    : 30,
      "hard_to"    : 300,
      "flow_id"    : "abc123"                 (opaque ID for TE log correlation)
    }

    # ── DELIBERATE BASELINE VULNERABILITY ──────────────────────────────────
    # Flow installation is accepted without authentication.  A compromised
    # peer can inject arbitrary flow rules into this domain's switches.
    # This is intentional for Phase 4 attack experiments.
    # ─────────────────────────────────────────────────────────────────────
    """
    body       = request.get_data()
    peer_domain = request.headers.get('X-Domain-Id', 'UNKNOWN')
    _ew_log('RECV', peer_domain, '/install_path', len(body))

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return jsonify({'error': str(exc)}), 400

    # Delegate to the flow-install callback registered by the controller
    if _flow_install_fn is None:
        return jsonify({'error': 'flow_install_fn not registered'}), 503

    try:
        result = _flow_install_fn(data)
        return jsonify({'status': 'ok', 'result': result}), 200
    except Exception as exc:
        log.error('[EW-API] /install_path error: %s', exc)
        return jsonify({'error': str(exc)}), 500


@_app.route('/te_path', methods=['GET'])
def get_te_path():
    """
    Diagnostic: compute and return the TE-selected path between two DPIDs.
    Query params: src_dpid=<int>&dst_dpid=<int>&te=<0|1>
    """
    try:
        from te.path_selector import compute_path, summarize_path
        src  = int(request.args.get('src_dpid', 0))
        dst  = int(request.args.get('dst_dpid', 0))
        te   = request.args.get('te', '1') != '0'
        ls   = gt.get_link_state()
        path = compute_path(src, dst, ls, te_enabled=te)
        summary = summarize_path(path, ls)
        return jsonify({'path': path, 'summary': summary, 'te_enabled': te}), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@_app.route('/peers', methods=['GET'])
def get_peers():
    """Diagnostic: show known peers and their last-seen timestamps."""
    return jsonify(gt.get_peer_meta()), 200


@_app.route('/globalview', methods=['GET'])
def get_globalview():
    """Diagnostic: dump the full merged global view as JSON."""
    return jsonify(gt.snapshot()), 200


@_app.route('/hosts', methods=['GET'])
def get_hosts():
    """Return all host MACs known to this controller (from global_topology)."""
    return jsonify(gt.get_hosts()), 200


# ── Server startup ─────────────────────────────────────────────────────────────

def start_api(domain_id: str, api_port: int, local_topo_fn,
              ew_log_path: str = 'results/eastwest_traffic.log',
              flow_install_fn=None):
    """
    Start the Flask REST API in a background daemon thread.

    Parameters
    ──────────
    domain_id      : 'A', 'B', or 'C'
    api_port       : TCP port (8080 / 8081 / 8082)
    local_topo_fn  : callable() → dict with 'switches', 'links', 'inter_links'
    ew_log_path    : path for the East-West traffic log
    flow_install_fn: optional callable(data: dict) called by POST /install_path
    """
    global _domain_id, _api_port, _ew_log_path, _local_topo_fn, _flow_install_fn

    _domain_id       = domain_id
    _api_port        = api_port
    _ew_log_path     = ew_log_path
    _local_topo_fn   = local_topo_fn
    _flow_install_fn = flow_install_fn

    # Suppress Flask's noisy startup banner and request logs
    import logging as _lg
    _lg.getLogger('werkzeug').setLevel(_lg.WARNING)

    def _run():
        log.info('[EW-API] Starting Flask on 0.0.0.0:%d (domain=%s)',
                 api_port, domain_id)
        from ryu.lib import hub
        import eventlet
        import eventlet.wsgi
        # Run Flask using eventlet's WSGI server so it runs in the same thread
        # and event loop as Ryu datapath. This is CRITICAL because incoming
        # /install_path requests call dp.send_msg(), which pushes to an
        # eventlet queue. If called from a separate OS thread, the eventlet
        # hub never wakes up, and the flows never get installed!
        eventlet.wsgi.server(eventlet.listen(('0.0.0.0', api_port)), _app, log_output=False)

    from ryu.lib import hub
    t = hub.spawn(_run)
    log.info('[EW-API] GreenThread launched.')
    return t
