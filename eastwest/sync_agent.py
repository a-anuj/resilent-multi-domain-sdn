#!/usr/bin/env python3
"""
eastwest/sync_agent.py
-----------------------
Periodic East-West synchronisation loop.

Every SYNC_INTERVAL seconds this agent:
  1. GETs /topology  from each peer controller's REST API
  2. GETs /linkstate from each peer controller's REST API
  3. POSTs our own topology + linkstate to each peer's /update endpoint
  4. Logs every message (timestamp, src, dst, bytes) to eastwest_traffic.log

Design rationale
────────────────
Sync interval is 5 seconds — fast enough for convergence within a
handful of sync rounds after topology change (~10s worst case), but
well below the 100 Mbps link capacity (a typical payload is ~2–4 KB,
so 5s gives <1 kbps overhead per peer pair).  This value will be
reported in the paper's experimental setup section.

# ── DELIBERATE BASELINE VULNERABILITY ────────────────────────────────────────
# Peer responses are merged into global_topology WITHOUT authentication or
# validation.  A peer that has been compromised (or a network-level MITM)
# can inject false topology data.  This is the attack surface for Phase 4.
# DO NOT add validation here until Phase 4 experiments are complete.
# ─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import threading
import time
from datetime import datetime

import requests

from eastwest import global_topology as gt

log = logging.getLogger('sync_agent')

# ── Tunable parameters ────────────────────────────────────────────────────────
SYNC_INTERVAL  = 5    # seconds between sync rounds
REQUEST_TIMEOUT = 3   # seconds per HTTP request before giving up

# ── Per-controller REST API port map ─────────────────────────────────────────
# Must match the values passed to start_api() in ew_controller.py.
DOMAIN_API_PORTS = {
    'A': 8080,
    'B': 8081,
    'C': 8082,
}
CTRL_HOST = '127.0.0.1'   # all controllers on localhost for this testbed


def _peer_url(domain: str, endpoint: str) -> str:
    port = DOMAIN_API_PORTS[domain]
    return f'http://{CTRL_HOST}:{port}{endpoint}'


def _ew_log(direction: str, src_domain: str, dst_domain: str,
            endpoint: str, payload_bytes: int, status: str = 'OK',
            log_path: str = 'results/eastwest_traffic.log'):
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    line = (f'{ts}  {direction:4s}  src={src_domain:<3}  dst={dst_domain:<3}'
            f'  endpoint={endpoint:<12}  bytes={payload_bytes:>8}  status={status}\n')
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a') as f:
            f.write(line)
    except Exception as exc:
        log.warning('EW log write failed: %s', exc)


class SyncAgent:
    """
    Runs as a background thread; polls all peer controllers and pushes
    local topology/linkstate updates every SYNC_INTERVAL seconds.
    """

    def __init__(self, domain_id: str, peer_domains: list[str],
                 local_topo_fn,
                 ew_log_path: str = 'results/eastwest_traffic.log'):
        """
        Parameters
        ──────────
        domain_id      : 'A', 'B', or 'C' — this controller's ID
        peer_domains   : list of peer domain IDs, e.g. ['B', 'C']
        local_topo_fn  : callable() → dict with switches/links/inter_links
        ew_log_path    : path for the East-West traffic log
        """
        self.domain_id    = domain_id
        self.peer_domains = peer_domains
        self.local_topo_fn = local_topo_fn
        self.ew_log_path  = ew_log_path
        self._stop        = threading.Event()
        self._thread      = threading.Thread(
            target=self._loop, name=f'sync-agent-{domain_id}', daemon=True)

    def start(self):
        log.info('[SyncAgent-%s] Starting (interval=%ds, peers=%s)',
                 self.domain_id, SYNC_INTERVAL, self.peer_domains)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _loop(self):
        # Wait a bit for controllers to finish startup before first sync
        time.sleep(3)
        while not self._stop.is_set():
            start = time.time()
            for peer in self.peer_domains:
                self._pull_from_peer(peer)
                self._push_to_peer(peer)
            elapsed = time.time() - start
            sleep_for = max(0.0, SYNC_INTERVAL - elapsed)
            log.debug('[SyncAgent-%s] round done in %.1fs, sleeping %.1fs',
                      self.domain_id, elapsed, sleep_for)
            self._stop.wait(timeout=sleep_for)

    def _pull_from_peer(self, peer: str):
        """Pull /topology and /linkstate from a peer, merge into global view."""
        # ── /topology ──────────────────────────────────────────────────────
        url = _peer_url(peer, '/topology')
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            body = resp.content
            self._ew_log('RECV', peer, self.domain_id, '/topology',
                         len(body), status=str(resp.status_code))

            if resp.status_code == 200:
                data = resp.json()
                gt.merge_peer_topology(peer, data)
                log.info('[SyncAgent-%s] Merged topology from domain %s '
                         '(%d switches, %d links)',
                         self.domain_id, peer,
                         len(data.get('switches', {})),
                         len(data.get('links', [])))
            else:
                log.warning('[SyncAgent-%s] /topology from %s returned %d',
                            self.domain_id, peer, resp.status_code)

        except requests.exceptions.ConnectionError:
            log.warning('[SyncAgent-%s] Peer %s unreachable at %s '
                        '(controller may be down — stale data retained)',
                        self.domain_id, peer, url)
            self._ew_log('RECV', peer, self.domain_id, '/topology',
                         0, status='ERR_CONN')
        except Exception as exc:
            log.error('[SyncAgent-%s] /topology pull from %s failed: %s',
                      self.domain_id, peer, exc)
            self._ew_log('RECV', peer, self.domain_id, '/topology',
                         0, status='ERR')

        # ── /linkstate ─────────────────────────────────────────────────────
        url = _peer_url(peer, '/linkstate')
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            body = resp.content
            self._ew_log('RECV', peer, self.domain_id, '/linkstate',
                         len(body), status=str(resp.status_code))

            if resp.status_code == 200:
                data = resp.json()
                gt.merge_peer_link_state(peer, data)
            else:
                log.warning('[SyncAgent-%s] /linkstate from %s returned %d',
                            self.domain_id, peer, resp.status_code)

        except requests.exceptions.ConnectionError:
            log.warning('[SyncAgent-%s] Peer %s unreachable for /linkstate',
                        self.domain_id, peer)
            self._ew_log('RECV', peer, self.domain_id, '/linkstate',
                         0, status='ERR_CONN')
        except Exception as exc:
            log.error('[SyncAgent-%s] /linkstate pull from %s failed: %s',
                      self.domain_id, peer, exc)

    def _push_to_peer(self, peer: str):
        """Push our own topology + linkstate to a peer's /update endpoint."""
        # ── topology push ──────────────────────────────────────────────────
        url = _peer_url(peer, '/update')
        try:
            topo = self.local_topo_fn()
            topo['type']      = 'topology'
            topo['domain_id'] = self.domain_id
            body = json.dumps(topo).encode()
            resp = requests.post(
                url, data=body,
                headers={'Content-Type': 'application/json',
                         'X-Domain-Id': self.domain_id},
                timeout=REQUEST_TIMEOUT)
            self._ew_log('SEND', self.domain_id, peer, '/update',
                         len(body), status=str(resp.status_code))

        except requests.exceptions.ConnectionError:
            log.warning('[SyncAgent-%s] Cannot push topology to peer %s '
                        '(controller may be down)', self.domain_id, peer)
            self._ew_log('SEND', self.domain_id, peer, '/update',
                         0, status='ERR_CONN')
        except Exception as exc:
            log.error('[SyncAgent-%s] topology push to %s failed: %s',
                      self.domain_id, peer, exc)

        # ── linkstate push ─────────────────────────────────────────────────
        try:
            ls_data = {
                'type':       'linkstate',
                'domain_id':  self.domain_id,
                'link_state': gt.get_link_state(),
            }
            body = json.dumps(ls_data).encode()
            resp = requests.post(
                url, data=body,
                headers={'Content-Type': 'application/json',
                         'X-Domain-Id': self.domain_id},
                timeout=REQUEST_TIMEOUT)
            self._ew_log('SEND', self.domain_id, peer, '/update(ls)',
                         len(body), status=str(resp.status_code))

        except requests.exceptions.ConnectionError:
            pass   # already warned above
        except Exception as exc:
            log.error('[SyncAgent-%s] linkstate push to %s failed: %s',
                      self.domain_id, peer, exc)

    def _ew_log(self, direction, src, dst, endpoint, payload_bytes, status='OK'):
        _ew_log(direction, src, dst, endpoint, payload_bytes,
                status=status, log_path=self.ew_log_path)


def start_sync_agent(domain_id: str, peer_domains: list[str],
                     local_topo_fn,
                     ew_log_path: str = 'results/eastwest_traffic.log') -> SyncAgent:
    """Convenience factory: create and start a SyncAgent, return it."""
    agent = SyncAgent(domain_id, peer_domains, local_topo_fn, ew_log_path)
    agent.start()
    return agent
