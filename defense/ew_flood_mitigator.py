#!/usr/bin/env python3
"""
defense/ew_flood_mitigator.py
------------------------------
Defense Module 2: East-West REST API Flood Mitigator

Attack it defends against
─────────────────────────
attacks/eastwest_flood.py — A rogue/compromised peer controller hammers the
victim controller's POST /update endpoint with valid-looking JSON at high
rates (up to 200 req/s).  Because /update is unauthenticated and immediately
merges payloads into global_topology, every request triggers internal locking
and topology-merge code paths — degrading legitimate E-W sync performance.

Defence strategy (three-layer middleware)
──────────────────────────────────────────
Layer 1 — Per-peer Token Bucket Rate Limiter
    Each peer IP is given a token bucket (default: 30 req/s, burst of 50).
    Requests that exceed the budget are rejected immediately with HTTP 429,
    never reaching the expensive merge code path.

Layer 2 — Global Request Rate Guard
    A sliding-window counter caps the TOTAL /update throughput seen by the
    Flask worker regardless of how many IP addresses the attacker uses
    (distributed flood / rotated source IPs).  Default: 60 req/s global.

Layer 3 — Slow-Rate Anomaly Detector (background thread)
    A 10-second sliding window tracks aggregate /update request rate.
    If the rate sustainedly exceeds ANOMALY_THRESHOLD (default: 25 req/s)
    for ANOMALY_WINDOW_SECONDS consecutive seconds the mitigator:
      1. Logs a DETECT alert.
      2. Temporarily tightens the per-peer bucket to QUARANTINE_RATE (5 req/s).
      3. After QUARANTINE_DURATION (60s) the limit reverts to normal.

Integration
───────────
    Call install_ew_flood_mitigator(app) after the Flask app is created
    but BEFORE start_api() launches it (in eastwest/ew_api.py):

        from defense.ew_flood_mitigator import install_ew_flood_mitigator
        mitigator = install_ew_flood_mitigator(_app)

    Alternatively, run as a standalone out-of-band daemon:
        python3 defense/ew_flood_mitigator.py --api-port 8080

Logging
───────
    Writes detection events to results/ew_flood_defense_<ts>.log and stdout.
"""

from __future__ import annotations

import argparse
import collections
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from functools import wraps

# ── Project path ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOG_FILE = os.path.join(RESULTS_DIR, f"ew_flood_defense_{_ts}.log")

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger("ew_flood_mitigator")
log.setLevel(logging.INFO)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)


# ── Default tuning parameters ─────────────────────────────────────────────────
# Chosen to accommodate 3 legitimate peers (~5 req/s each = 15 req/s total)
# while blocking the attack's 200 req/s maximum.

DEFAULT_PER_PEER_RATE     = 30    # req/s allowed per source IP
DEFAULT_PER_PEER_BURST    = 50    # burst tokens
DEFAULT_GLOBAL_RATE       = 60    # total req/s across all peers
DEFAULT_GLOBAL_BURST      = 100
DEFAULT_ANOMALY_THRESHOLD = 25    # sustained req/s to trigger quarantine
DEFAULT_ANOMALY_WINDOW    = 10    # seconds of sustained overload → quarantine
DEFAULT_QUARANTINE_RATE   = 5     # req/s during quarantine
DEFAULT_QUARANTINE_BURST  = 10
DEFAULT_QUARANTINE_DUR    = 60    # seconds before reverting to normal limits


# ── Token Bucket ──────────────────────────────────────────────────────────────

class TokenBucket:
    """Thread-safe token bucket for rate limiting.

    Tokens refill continuously at `rate` per second up to `burst` maximum.
    Each consume() call removes one token; returns True if allowed, False
    if the bucket is empty (rate limit exceeded).
    """

    def __init__(self, rate: float, burst: float) -> None:
        self._rate   = rate
        self._burst  = burst
        self._tokens = burst
        self._last   = time.monotonic()
        self._lock   = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def update_rate(self, rate: float, burst: float) -> None:
        with self._lock:
            self._rate  = rate
            self._burst = burst


# ── Sliding-window counter ────────────────────────────────────────────────────

class SlidingWindowCounter:
    """Count events in a rolling time window (deque-based, O(1) amortised)."""

    def __init__(self, window_seconds: float = 10.0) -> None:
        self._window = window_seconds
        self._times: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def record(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._times.append(now)
            cutoff = now - self._window
            while self._times and self._times[0] < cutoff:
                self._times.popleft()

    def rate(self) -> float:
        now = time.monotonic()
        with self._lock:
            cutoff = now - self._window
            while self._times and self._times[0] < cutoff:
                self._times.popleft()
            return len(self._times) / self._window


# ── EW Flood Mitigator ────────────────────────────────────────────────────────

class EWFloodMitigator:
    """Central state object for the East-West flood defence.

    Holds all per-peer token buckets, the global rate guard, the sliding-
    window counter, and runs the background anomaly-detection thread.
    """

    def __init__(
        self,
        per_peer_rate:      float = DEFAULT_PER_PEER_RATE,
        per_peer_burst:     float = DEFAULT_PER_PEER_BURST,
        global_rate:        float = DEFAULT_GLOBAL_RATE,
        global_burst:       float = DEFAULT_GLOBAL_BURST,
        anomaly_threshold:  float = DEFAULT_ANOMALY_THRESHOLD,
        anomaly_window:     int   = DEFAULT_ANOMALY_WINDOW,
        quarantine_rate:    float = DEFAULT_QUARANTINE_RATE,
        quarantine_burst:   float = DEFAULT_QUARANTINE_BURST,
        quarantine_dur:     int   = DEFAULT_QUARANTINE_DUR,
    ) -> None:
        self._per_peer_rate     = per_peer_rate
        self._per_peer_burst    = per_peer_burst
        self._global_rate       = global_rate
        self._global_burst      = global_burst
        self._anomaly_threshold = anomaly_threshold
        self._anomaly_window    = anomaly_window
        self._quarantine_rate   = quarantine_rate
        self._quarantine_burst  = quarantine_burst
        self._quarantine_dur    = quarantine_dur

        self._peer_buckets: dict[str, TokenBucket] = {}
        self._peer_lock = threading.Lock()

        self._global_bucket = TokenBucket(global_rate, global_burst)

        self._window = SlidingWindowCounter(window_seconds=float(anomaly_window))

        self._quarantine_active = False
        self._quarantine_end    = 0.0
        self._quarantine_lock   = threading.Lock()

        self._stats: dict[str, int] = {
            "allowed":           0,
            "per_peer_blocked":  0,
            "global_blocked":    0,
            "alerts":            0,
            "quarantines":       0,
        }
        self._stats_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._detector = threading.Thread(
            target=self._anomaly_loop, daemon=True, name="ew-anomaly-detector"
        )
        self._detector.start()
        log.info(
            "EWFloodMitigator started  per_peer=%.0f req/s  global=%.0f req/s  "
            "anomaly_threshold=%.0f req/s  quarantine=%ds",
            per_peer_rate, global_rate, anomaly_threshold, quarantine_dur,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def check_request(self, peer_ip: str) -> tuple[bool, str]:
        """Gate an incoming /update request from peer_ip.

        Returns (True, "") on allow, or (False, reason) on block.
        """
        bucket = self._get_bucket(peer_ip)
        if not bucket.consume():
            with self._stats_lock:
                self._stats["per_peer_blocked"] += 1
            return False, f"Per-peer rate limit exceeded for {peer_ip}"

        if not self._global_bucket.consume():
            with self._stats_lock:
                self._stats["global_blocked"] += 1
            return False, "Global /update rate limit exceeded"

        self._window.record()
        with self._stats_lock:
            self._stats["allowed"] += 1
        return True, ""

    def stop(self) -> None:
        self._stop_event.set()

    def stats_snapshot(self) -> dict:
        with self._stats_lock:
            snap = dict(self._stats)
        snap["current_rate_per_s"] = round(self._window.rate(), 2)
        snap["quarantine_active"]  = self._quarantine_active
        snap["peer_count"]         = len(self._peer_buckets)
        return snap

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_bucket(self, peer_ip: str) -> TokenBucket:
        with self._peer_lock:
            if peer_ip not in self._peer_buckets:
                self._peer_buckets[peer_ip] = TokenBucket(
                    self._per_peer_rate, self._per_peer_burst
                )
                log.info("New peer bucket: IP=%s", peer_ip)
            return self._peer_buckets[peer_ip]

    def _anomaly_loop(self) -> None:
        violation_secs = 0
        while not self._stop_event.is_set():
            time.sleep(1.0)
            rate = self._window.rate()

            with self._quarantine_lock:
                if self._quarantine_active and time.monotonic() > self._quarantine_end:
                    self._lift_quarantine()

            if rate > self._anomaly_threshold:
                violation_secs += 1
                log.warning(
                    "ANOMALY [%d/%ds]: /update rate=%.1f req/s (threshold=%.0f req/s)",
                    violation_secs, self._anomaly_window, rate, self._anomaly_threshold,
                )
                with self._stats_lock:
                    self._stats["alerts"] += 1

                if violation_secs >= self._anomaly_window:
                    with self._quarantine_lock:
                        if not self._quarantine_active:
                            self._activate_quarantine(rate)
                    violation_secs = 0
            else:
                if violation_secs > 0:
                    log.info("Rate normalised (%.1f req/s). Clearing counter.", rate)
                violation_secs = 0

    def _activate_quarantine(self, trigger_rate: float) -> None:
        self._quarantine_active = True
        self._quarantine_end    = time.monotonic() + self._quarantine_dur
        with self._stats_lock:
            self._stats["quarantines"] += 1
        log.warning(
            "QUARANTINE ACTIVATED — trigger_rate=%.1f req/s. "
            "All peers limited to %.0f req/s for %ds.",
            trigger_rate, self._quarantine_rate, self._quarantine_dur,
        )
        with self._peer_lock:
            for b in self._peer_buckets.values():
                b.update_rate(self._quarantine_rate, self._quarantine_burst)

    def _lift_quarantine(self) -> None:
        self._quarantine_active = False
        with self._peer_lock:
            for b in self._peer_buckets.values():
                b.update_rate(self._per_peer_rate, self._per_peer_burst)
        log.info("QUARANTINE LIFTED — restored %.0f req/s per peer.", self._per_peer_rate)


# ── Flask middleware installer ────────────────────────────────────────────────

def install_ew_flood_mitigator(app, mitigator: "EWFloodMitigator | None" = None,
                               **kwargs) -> "EWFloodMitigator":
    """
    Wrap Flask's POST /update view with rate-limiting middleware.

    Usage (in eastwest/ew_api.py, after route registration):
        from defense.ew_flood_mitigator import install_ew_flood_mitigator
        mitigator = install_ew_flood_mitigator(_app)

    Returns the active EWFloodMitigator (useful for /stats diagnostic queries).
    """
    try:
        from flask import request, jsonify
    except ImportError:
        raise RuntimeError("Flask is required to use install_ew_flood_mitigator()")

    if mitigator is None:
        mitigator = EWFloodMitigator(**kwargs)

    original_view = app.view_functions.get("post_update")
    if original_view is None:
        raise RuntimeError(
            "Flask route 'post_update' not registered — "
            "call install_ew_flood_mitigator() AFTER registering EW API routes."
        )

    @wraps(original_view)
    def _guarded_update():
        peer_key = request.headers.get("X-Domain-Id") or request.remote_addr or "unknown"
        allowed, reason = mitigator.check_request(peer_key)
        if not allowed:
            log.warning("BLOCKED /update from %s — %s", peer_key, reason)
            return jsonify({"error": "rate limit exceeded", "detail": reason}), 429
        return original_view()

    app.view_functions["post_update"] = _guarded_update
    log.info("EW flood mitigator middleware installed on POST /update.")
    return mitigator


# ── Standalone monitor mode ───────────────────────────────────────────────────

def monitor_ew_endpoint(api_port: int, anomaly_threshold: float) -> None:
    """
    Standalone out-of-band mode: poll /globalview to detect ROGUE domain
    injection activity.  Use when you cannot modify the Flask app directly.
    """
    import requests as _req

    url = f"http://127.0.0.1:{api_port}/globalview"
    log.info("Standalone EW monitor: watching %s", url)

    prev_ts     = time.monotonic()
    violation_s = 0.0

    while True:
        time.sleep(2.0)
        try:
            r = _req.get(url, timeout=2.0)
            if r.status_code != 200:
                log.warning("globalview HTTP %d", r.status_code)
                continue
            snap = r.json()
        except Exception as exc:
            log.warning("globalview fetch failed: %s", exc)
            continue

        now = time.monotonic()
        dt  = now - prev_ts
        prev_ts = now

        # Detect ROGUE domain injection in switches table
        switches = snap.get("switches", {})
        rogue = [k for k, v in switches.items() if v.get("domain") == "ROGUE"]
        if rogue:
            violation_s += dt
            log.warning("DETECT: ROGUE switches in global_topology: %s (%.0fs)", rogue, violation_s)
        else:
            if violation_s > 0:
                log.info("ROGUE entries cleared. Resetting counter.")
            violation_s = 0.0

        # Detect rogue peer_meta entries
        for domain, meta in snap.get("peer_meta", {}).items():
            if "ROGUE" in domain.upper():
                log.warning("DETECT: Rogue peer '%s' in peer_meta — seq=%s",
                            domain, meta.get("seq"))

        if violation_s > DEFAULT_ANOMALY_WINDOW:
            log.error(
                "SUSTAINED EW FLOOD DETECTED (%.0fs). "
                "Enable install_ew_flood_mitigator() or restart the controller.",
                violation_s,
            )


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "EW REST Flood Mitigator — standalone monitor/alerting daemon.\n"
            "For in-process rate limiting call install_ew_flood_mitigator(app) "
            "from within eastwest/ew_api.py."
        )
    )
    parser.add_argument("--api-port",          type=int,   default=8080)
    parser.add_argument("--per-peer-rate",     type=float, default=DEFAULT_PER_PEER_RATE)
    parser.add_argument("--global-rate",       type=float, default=DEFAULT_GLOBAL_RATE)
    parser.add_argument("--anomaly-threshold", type=float, default=DEFAULT_ANOMALY_THRESHOLD)
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("EW Flood Mitigator — Standalone Monitor Mode")
    log.info("  API port          : %d",    args.api_port)
    log.info("  Per-peer limit    : %.0f req/s", args.per_peer_rate)
    log.info("  Global limit      : %.0f req/s", args.global_rate)
    log.info("  Anomaly threshold : %.0f req/s", args.anomaly_threshold)
    log.info("  Log file          : %s",    LOG_FILE)
    log.info("=" * 60)

    try:
        monitor_ew_endpoint(args.api_port, args.anomaly_threshold)
    except KeyboardInterrupt:
        log.info("EW Flood Mitigator stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
