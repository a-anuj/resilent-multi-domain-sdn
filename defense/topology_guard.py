#!/usr/bin/env python3
"""
defense/topology_guard.py
--------------------------
Defense Module 3: Topology Poisoning Guard

Attack it defends against
─────────────────────────
attacks/topology_poison.py — A compromised controller sends a single crafted
POST /update payload containing:
  • congestion_lie:  A valid-looking linkstate update that reports a low-util
    link as heavily congested (ratio=0.95), forcing the TE path-selector to
    avoid it — degrading routing efficiency without flooding anything.
  • phantom_link:    A topology update that introduces a non-existent link
    between two DPIDs, potentially causing the Dijkstra path-selector to
    route traffic to a black hole.

Because the current /update endpoint is deliberately unauthenticated (see
eastwest/ew_api.py), any caller can inject arbitrary topology data.

Defence strategy (three-layer validation pipeline)
───────────────────────────────────────────────────
Layer 1 — HMAC-SHA256 Payload Authentication
    Every trusted controller signs its JSON payload with a shared secret
    using HMAC-SHA256.  The signature is carried in the X-EW-Signature header.
    Unsigned or incorrectly-signed requests are rejected (HTTP 401).

Layer 2 — Schema Validation
    Incoming JSON is validated against a minimal schema:
      • Required fields present (type, domain_id, seq)
      • domain_id must be in the known trusted domain set {A, B, C}
      • Numeric fields (dpid, port, ratio) must be sane (e.g. 0 ≤ ratio ≤ 1)
      • Port numbers must be realistic (1 ≤ port ≤ 64)
    Payloads that fail schema validation are rejected (HTTP 400).

Layer 3 — Semantic Cross-check
    Even authenticated and schema-valid payloads are cross-checked against the
    controller's own ground-truth knowledge:
      • Reported DPIDs must belong to the claimed domain_id.
      • Reported utilization ratios (util_rates) must not jump more than
        MAX_RATIO_DELTA (default: 0.60) from the last known value in a single
        update — smoothing out sudden "96% congestion" injections.
      • Phantom links (inter_links with port ≥ PHANTOM_PORT_THRESHOLD) are
        rejected outright.

Integration
───────────
    Install as a Flask middleware wrapper around the /update endpoint:

        from defense.topology_guard import install_topology_guard
        install_topology_guard(_app, shared_secret="your-secret-key",
                               trusted_domains={"A", "B", "C"})

    Alternatively run as an out-of-band detector (no secret enforcement):
        python3 defense/topology_guard.py --api-port 8080

Key Design Decision — shared_secret
    The shared secret is a symmetric pre-shared key.  In a real deployment
    it would be provisioned to every controller via a secure channel (e.g.,
    a secrets manager).  For the Mininet testbed it can be passed as an
    environment variable: EW_SHARED_SECRET=...

Logging
───────
    Writes rejection events to results/topology_guard_<ts>.log and stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

# ── Project path ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOG_FILE = os.path.join(RESULTS_DIR, f"topology_guard_{_ts}.log")

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger("topology_guard")
log.setLevel(logging.INFO)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)


# ── Default configuration ─────────────────────────────────────────────────────

DEFAULT_TRUSTED_DOMAINS     = {"A", "B", "C"}
DEFAULT_MAX_RATIO_DELTA     = 0.60   # max allowed single-update jump in util ratio
DEFAULT_MAX_PORT_NUMBER     = 64     # ports above this are suspect (phantom_link uses 99)
DEFAULT_PHANTOM_PORT_THRESHOLD = 50  # inter_links with src/dst port ≥ this are rejected
DEFAULT_SHARED_SECRET_ENV   = "EW_SHARED_SECRET"
DEFAULT_SHARED_SECRET       = "mininet-testbed-ew-secret-do-not-use-in-production"


# ── HMAC helpers ──────────────────────────────────────────────────────────────

def compute_hmac(payload_bytes: bytes, secret: str) -> str:
    """Return hex-encoded HMAC-SHA256 of payload_bytes using secret."""
    return hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()


def verify_hmac(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Constant-time comparison to avoid timing oracle attacks."""
    expected = compute_hmac(payload_bytes, secret)
    return hmac.compare_digest(expected, signature.lower())


def sign_payload(payload: dict, secret: str) -> str:
    """Serialize payload to canonical JSON bytes and return its HMAC signature.

    Callers (i.e. trusted controllers) must attach this as the
    X-EW-Signature request header when POSTing to /update.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return compute_hmac(body, secret)


# ── Schema validator ──────────────────────────────────────────────────────────

class SchemaError(ValueError):
    """Raised when a payload fails schema validation."""


def validate_topology_payload(data: dict, trusted_domains: set[str],
                               max_port: int = DEFAULT_MAX_PORT_NUMBER,
                               phantom_port_threshold: int = DEFAULT_PHANTOM_PORT_THRESHOLD) -> None:
    """
    Validate an incoming /update payload against the expected EW schema.

    Raises SchemaError with a descriptive message on the first violation found.
    """
    # ── Required top-level fields ─────────────────────────────────────────────
    for field in ("type", "domain_id", "seq"):
        if field not in data:
            raise SchemaError(f"Missing required field: '{field}'")

    update_type = data["type"]
    domain_id   = data["domain_id"]

    if update_type not in ("topology", "linkstate"):
        raise SchemaError(f"Unknown update type: '{update_type}'")

    # ── Domain whitelist check ────────────────────────────────────────────────
    if domain_id not in trusted_domains:
        raise SchemaError(
            f"Untrusted domain_id='{domain_id}'. "
            f"Accepted domains: {sorted(trusted_domains)}"
        )

    # ── seq must be a non-negative integer ────────────────────────────────────
    seq = data.get("seq")
    if not isinstance(seq, int) or seq < 0:
        raise SchemaError(f"Invalid seq: {seq!r} (must be a non-negative integer)")

    # ── topology-specific validation ──────────────────────────────────────────
    if update_type == "topology":
        # switches: dpid_str → {dpid: int, domain: str, ports: list}
        for dpid_str, sw_info in data.get("switches", {}).items():
            if not isinstance(sw_info, dict):
                raise SchemaError(f"Switch entry {dpid_str!r} is not a dict")
            if "dpid" in sw_info and not isinstance(sw_info["dpid"], int):
                raise SchemaError(f"Switch {dpid_str}: 'dpid' must be an integer")

        # links: list of {src_dpid, src_port, dst_dpid, dst_port}
        for link in data.get("links", []):
            _validate_link_dict(link, max_port)

        # inter_links: same schema — additionally check for phantom ports
        for il in data.get("inter_links", []):
            _validate_link_dict(il, max_port)
            if il.get("src_port", 0) >= phantom_port_threshold or \
               il.get("dst_port", 0) >= phantom_port_threshold:
                raise SchemaError(
                    f"Phantom link detected: inter_link port ≥ {phantom_port_threshold} "
                    f"(src_port={il.get('src_port')}, dst_port={il.get('dst_port')}). "
                    "Real topology only uses ports 1–6 in this testbed."
                )

    # ── linkstate-specific validation ─────────────────────────────────────────
    elif update_type == "linkstate":
        for dpid_str, ports in data.get("util_rates", {}).items():
            if not isinstance(ports, dict):
                raise SchemaError(f"util_rates[{dpid_str!r}] must be a dict")
            for port_str, pdata in ports.items():
                if not isinstance(pdata, dict):
                    raise SchemaError(
                        f"util_rates[{dpid_str!r}][{port_str!r}] must be a dict"
                    )
                ratio = pdata.get("ratio")
                if ratio is not None:
                    if not isinstance(ratio, (int, float)) or not (0.0 <= float(ratio) <= 1.0):
                        raise SchemaError(
                            f"util_rates[{dpid_str}][{port_str}].ratio={ratio!r} "
                            "is not in [0.0, 1.0]"
                        )


def _validate_link_dict(link: dict, max_port: int) -> None:
    for field in ("src_dpid", "src_port", "dst_dpid", "dst_port"):
        val = link.get(field)
        if val is None:
            raise SchemaError(f"Link entry missing field '{field}': {link}")
        if not isinstance(val, int):
            raise SchemaError(f"Link field '{field}' must be an integer, got {val!r}")

    if link["src_port"] > max_port or link["dst_port"] > max_port:
        raise SchemaError(
            f"Link port out of range (max={max_port}): "
            f"src_port={link['src_port']} dst_port={link['dst_port']}"
        )


# ── Semantic cross-checker ────────────────────────────────────────────────────

class SemanticChecker:
    """Track last-known utilization ratios for all (dpid, port) pairs.

    On each linkstate update, flags any ratio that jumps by more than
    max_ratio_delta compared to the previous known value.
    """

    def __init__(self, max_ratio_delta: float = DEFAULT_MAX_RATIO_DELTA) -> None:
        self._max_delta = max_ratio_delta
        # {dpid_str: {port_str: last_ratio}}
        self._known_ratios: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def check_util_rates(self, util_rates: dict) -> list[str]:
        """
        Return a list of anomaly description strings (empty = all OK).
        Also updates the stored known values for legitimate deltas.
        """
        anomalies: list[str] = []
        with self._lock:
            for dpid_str, ports in util_rates.items():
                if dpid_str not in self._known_ratios:
                    self._known_ratios[dpid_str] = {}
                for port_str, pdata in ports.items():
                    ratio = float(pdata.get("ratio", 0.0))
                    prev  = self._known_ratios[dpid_str].get(port_str)

                    if prev is not None:
                        delta = abs(ratio - prev)
                        if delta > self._max_delta:
                            anomalies.append(
                                f"Suspicious util_rate jump on dpid={dpid_str} "
                                f"port={port_str}: {prev:.2f} → {ratio:.2f} "
                                f"(delta={delta:.2f} > threshold={self._max_delta:.2f})"
                            )
                            # Do NOT update stored ratio when anomaly detected
                            continue

                    self._known_ratios[dpid_str][port_str] = ratio

        return anomalies


# ── TopologyGuard — main orchestrator ────────────────────────────────────────

class TopologyGuard:
    """
    Orchestrates all three validation layers for incoming /update payloads.

    Typical usage (middleware mode):
        guard = TopologyGuard(shared_secret="...", trusted_domains={"A","B","C"})
        guard.validate(request_body_bytes, headers, payload_dict)
        # raises GuardRejection on any violation
    """

    def __init__(
        self,
        shared_secret:          str        = DEFAULT_SHARED_SECRET,
        trusted_domains:        set[str]   = None,
        max_ratio_delta:        float      = DEFAULT_MAX_RATIO_DELTA,
        max_port:               int        = DEFAULT_MAX_PORT_NUMBER,
        phantom_port_threshold: int        = DEFAULT_PHANTOM_PORT_THRESHOLD,
        hmac_required:          bool       = True,
    ) -> None:
        self._secret           = shared_secret
        self._trusted          = trusted_domains or DEFAULT_TRUSTED_DOMAINS.copy()
        self._hmac_required    = hmac_required
        self._max_port         = max_port
        self._phantom_thresh   = phantom_port_threshold
        self._semantic         = SemanticChecker(max_ratio_delta)

        self._stats = {
            "allowed":           0,
            "hmac_rejected":     0,
            "schema_rejected":   0,
            "semantic_rejected": 0,
        }
        self._stats_lock = threading.Lock()

        log.info(
            "TopologyGuard started. hmac_required=%s  trusted_domains=%s  "
            "max_ratio_delta=%.2f  phantom_port_threshold=%d",
            hmac_required, sorted(self._trusted), max_ratio_delta, phantom_port_threshold,
        )

    def validate(self, body_bytes: bytes, headers: dict, data: dict) -> None:
        """
        Full three-layer validation.

        Parameters
        ──────────
        body_bytes : raw request body (used for HMAC verification)
        headers    : dict-like of HTTP request headers
        data       : already-parsed JSON payload

        Raises GuardRejection on any failure.
        """
        # Layer 1 — HMAC
        if self._hmac_required:
            sig = headers.get("X-EW-Signature", "")
            if not sig:
                self._reject("hmac_rejected",
                             "Missing X-EW-Signature header — payload rejected")
            if not verify_hmac(body_bytes, sig, self._secret):
                self._reject("hmac_rejected",
                             f"HMAC mismatch from domain={data.get('domain_id','?')} — "
                             "possible topology poisoning attempt")

        # Layer 2 — Schema
        try:
            validate_topology_payload(
                data,
                trusted_domains         = self._trusted,
                max_port                = self._max_port,
                phantom_port_threshold  = self._phantom_thresh,
            )
        except SchemaError as exc:
            self._reject("schema_rejected", f"Schema validation failed: {exc}")

        # Layer 3 — Semantic cross-check (linkstate only)
        if data.get("type") == "linkstate" and "util_rates" in data:
            anomalies = self._semantic.check_util_rates(data["util_rates"])
            if anomalies:
                self._reject("semantic_rejected",
                             f"Semantic anomaly detected: {'; '.join(anomalies)}")

        with self._stats_lock:
            self._stats["allowed"] += 1

    def stats_snapshot(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    def _reject(self, counter: str, reason: str) -> None:
        with self._stats_lock:
            self._stats[counter] += 1
        log.warning("GUARD REJECT [%s]: %s", counter, reason)
        raise GuardRejection(reason)


class GuardRejection(Exception):
    """Raised by TopologyGuard.validate() when a payload is rejected."""


# ── Flask middleware installer ────────────────────────────────────────────────

def install_topology_guard(app, shared_secret: str = DEFAULT_SHARED_SECRET,
                           trusted_domains: "set[str] | None" = None,
                           hmac_required: bool = True,
                           **kwargs) -> TopologyGuard:
    """
    Wrap Flask's POST /update view with topology validation middleware.

    Usage (in eastwest/ew_api.py, after route registration):
        from defense.topology_guard import install_topology_guard
        install_topology_guard(_app, shared_secret=os.environ.get("EW_SHARED_SECRET"))

    Returns the active TopologyGuard instance.

    Note: If both install_ew_flood_mitigator() and install_topology_guard()
    are used together, install rate-limiting first (outer) and topology guard
    second (inner) so that flooding is cut before schema validation overhead.
    """
    try:
        from flask import request, jsonify
    except ImportError:
        raise RuntimeError("Flask is required to use install_topology_guard()")

    guard = TopologyGuard(
        shared_secret  = shared_secret,
        trusted_domains= trusted_domains,
        hmac_required  = hmac_required,
        **kwargs,
    )

    original_view = app.view_functions.get("post_update")
    if original_view is None:
        raise RuntimeError(
            "Flask route 'post_update' not registered — "
            "call install_topology_guard() AFTER registering EW API routes."
        )

    from functools import wraps

    @wraps(original_view)
    def _guarded_update():
        body    = request.get_data()
        headers = request.headers
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            log.warning("JSON parse error: %s", exc)
            return jsonify({"error": "invalid JSON"}), 400

        try:
            guard.validate(body, headers, data)
        except GuardRejection as exc:
            return jsonify({"error": "payload rejected", "detail": str(exc)}), 403

        return original_view()

    app.view_functions["post_update"] = _guarded_update
    log.info("Topology guard middleware installed on POST /update.")
    return guard


# ── Standalone payload signer (helper for trusted controllers) ────────────────

def sign_and_post(url: str, payload: dict, secret: str, domain_id: str,
                  timeout: float = 5.0) -> "tuple[int, dict]":
    """
    Utility for trusted peer controllers to sign and send an /update payload.

    Usage in sync_agent.py or ew_controller.py:
        from defense.topology_guard import sign_and_post
        status, resp = sign_and_post(
            "http://127.0.0.1:8081/update", my_topology_dict,
            secret=os.environ["EW_SHARED_SECRET"], domain_id="A"
        )

    Returns (http_status_code, response_json_dict).
    """
    import requests as _req

    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig        = compute_hmac(body_bytes, secret)

    headers = {
        "Content-Type":    "application/json",
        "X-Domain-Id":     domain_id,
        "X-EW-Signature":  sig,
    }
    resp = _req.post(url, data=body_bytes, headers=headers, timeout=timeout)
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, {}


# ── Standalone detector (out-of-band, read-only) ──────────────────────────────

def detect_standalone(api_port: int, poll_interval: float = 5.0) -> None:
    """
    Out-of-band detector: poll /globalview periodically and look for
    topology-poisoning indicators without modifying the Flask app.

    Indicators checked:
      1. ROGUE domain switches in global_topology.switches
      2. Inter-links with unrealistic port numbers (≥ phantom_port_threshold)
      3. util_rates entries with ratio > 0.92 on known low-utilization links
    """
    import requests as _req

    url = f"http://127.0.0.1:{api_port}/globalview"
    log.info("Standalone topology guard watching %s (poll every %.0fs)", url, poll_interval)

    prev_inter_links: list = []

    while True:
        time.sleep(poll_interval)
        try:
            r = _req.get(url, timeout=3.0)
            if r.status_code != 200:
                log.warning("globalview HTTP %d", r.status_code)
                continue
            snap = r.json()
        except Exception as exc:
            log.warning("globalview fetch failed: %s", exc)
            continue

        # Check 1: ROGUE domain switches
        rogue_sw = [k for k, v in snap.get("switches", {}).items()
                    if v.get("domain") == "ROGUE"]
        if rogue_sw:
            log.warning("TOPO-POISON DETECT: ROGUE switches in global_topology: %s", rogue_sw)

        # Check 2: phantom inter_links (bogus port numbers)
        for il in snap.get("inter_links", []):
            if (il.get("src_port", 0) >= DEFAULT_PHANTOM_PORT_THRESHOLD or
                    il.get("dst_port", 0) >= DEFAULT_PHANTOM_PORT_THRESHOLD):
                log.warning(
                    "TOPO-POISON DETECT: Phantom inter_link detected — "
                    "src_dpid=%s src_port=%s dst_dpid=%s dst_port=%s",
                    il.get("src_dpid"), il.get("src_port"),
                    il.get("dst_dpid"), il.get("dst_port"),
                )

        # Check 3: suspiciously high utilization ratios on multiple ports simultaneously
        util = snap.get("util_rates", {})
        high_util_ports = [
            f"dpid={d} port={p} ratio={v.get('ratio', v):.2f}"
            for d, ports in util.items()
            for p, v in ports.items()
            if (isinstance(v, dict) and v.get("ratio", 0) > 0.92)
            or (isinstance(v, (int, float)) and float(v) > 0.92)
        ]
        if len(high_util_ports) >= 3:
            log.warning(
                "TOPO-POISON DETECT: Congestion lie suspected — "
                "≥3 ports simultaneously reporting >92%% util: %s",
                high_util_ports,
            )


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Topology Poisoning Guard — standalone detector daemon.\n"
            "Polls the controller's /globalview endpoint for topology poisoning "
            "indicators.  For active blocking (HMAC + schema validation), call "
            "install_topology_guard(app) from within eastwest/ew_api.py."
        )
    )
    parser.add_argument("--api-port",    type=int,   default=8080,
                        help="Controller REST port to monitor (default: 8080)")
    parser.add_argument("--poll",        type=float, default=5.0,
                        help="Poll interval in seconds (default: 5)")
    parser.add_argument("--sign-test",   action="store_true",
                        help="Self-test: sign a sample payload and print its HMAC signature")
    parser.add_argument("--secret",      default=os.environ.get(
                        DEFAULT_SHARED_SECRET_ENV, DEFAULT_SHARED_SECRET),
                        help=f"Shared HMAC secret (env: {DEFAULT_SHARED_SECRET_ENV})")
    args = parser.parse_args()

    if args.sign_test:
        sample = {"type": "topology", "domain_id": "A", "seq": 1,
                  "switches": {}, "links": [], "inter_links": [], "hosts": {}}
        sig = sign_payload(sample, args.secret)
        print(f"Sample payload HMAC-SHA256 signature: {sig}")
        print("Attach this as the X-EW-Signature header in POST /update requests.")
        return 0

    log.info("=" * 60)
    log.info("Topology Guard — Standalone Detector Mode")
    log.info("  API port     : %d",   args.api_port)
    log.info("  Poll interval: %.0fs", args.poll)
    log.info("  Log file     : %s",   LOG_FILE)
    log.info("=" * 60)

    try:
        detect_standalone(args.api_port, args.poll)
    except KeyboardInterrupt:
        log.info("Topology Guard stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
