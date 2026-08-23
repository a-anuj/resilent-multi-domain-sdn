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
    """Return current per-port utilization stats."""
    data = {
        'domain_id':  _domain_id,
        'link_state': gt.get_link_state(),
        'timestamp':  datetime.utcnow().isoformat() + 'Z',
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
    else:
        log.warning('[EW-API] Unknown update type: %s', update_type)

    return jsonify({'status': 'accepted', 'domain': _domain_id}), 200


@_app.route('/peers', methods=['GET'])
def get_peers():
    """Diagnostic: show known peers and their last-seen timestamps."""
    return jsonify(gt.get_peer_meta()), 200


@_app.route('/globalview', methods=['GET'])
def get_globalview():
    """Diagnostic: dump the full merged global view as JSON."""
    return jsonify(gt.snapshot()), 200


# ── Server startup ─────────────────────────────────────────────────────────────

def start_api(domain_id: str, api_port: int, local_topo_fn,
              ew_log_path: str = 'results/eastwest_traffic.log'):
    """
    Start the Flask REST API in a background daemon thread.

    Parameters
    ──────────
    domain_id    : 'A', 'B', or 'C'
    api_port     : TCP port (8080 / 8081 / 8082)
    local_topo_fn: callable() → dict with 'switches', 'links', 'inter_links'
    ew_log_path  : path for the East-West traffic log
    """
    global _domain_id, _api_port, _ew_log_path, _local_topo_fn

    _domain_id    = domain_id
    _api_port     = api_port
    _ew_log_path  = ew_log_path
    _local_topo_fn = local_topo_fn

    # Suppress Flask's noisy startup banner and request logs
    import logging as _lg
    _lg.getLogger('werkzeug').setLevel(_lg.WARNING)

    def _run():
        log.info('[EW-API] Starting Flask on 0.0.0.0:%d (domain=%s)',
                 api_port, domain_id)
        _app.run(host='0.0.0.0', port=api_port, threaded=True, use_reloader=False)

    t = threading.Thread(target=_run, name='ew-api', daemon=True)
    t.start()
    log.info('[EW-API] Thread launched.')
    return t
