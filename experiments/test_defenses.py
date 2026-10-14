#!/usr/bin/env python3
"""
experiments/test_defenses.py
-----------------------------
Self-contained verification suite for the two Phase 6 defense modules:

  • defense/ew_flood_mitigator.py   — East-West REST API Flood defense
  • defense/topology_guard.py       — Topology Poisoning defense

No Mininet, no running controller, no root needed.

The script spins up a lightweight Flask mock server (a stripped-down clone
of the real /update endpoint) on a random free port, installs each defense
middleware, then fires realistic attack payloads at it and asserts the
correct HTTP responses.

Exit codes:
  0  — all tests passed
  1  — one or more tests failed

Run:
    python3 experiments/test_defenses.py [-v]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

# ── Project root on path ──────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    import requests
    from flask import Flask, request, jsonify
except ImportError as exc:
    sys.exit(f"[ERROR] Missing dependency: {exc}\n"
             "Install with:  pip install flask requests")

# ── Color helpers (ANSI) ──────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

VERBOSE = False

def _log(msg: str) -> None:
    if VERBOSE:
        print(msg)

def _pass(name: str) -> None:
    print(f"  {_GREEN}✓{_RESET} {name}")

def _fail(name: str, detail: str) -> None:
    print(f"  {_RED}✗{_RESET} {name}")
    print(f"      {_YELLOW}→ {detail}{_RESET}")

def _section(title: str) -> None:
    print(f"\n{_BOLD}{'─'*60}{_RESET}")
    print(f"{_BOLD}  {title}{_RESET}")
    print(f"{_BOLD}{'─'*60}{_RESET}")


# ── Minimal Flask mock (mirrors real /update logic) ───────────────────────────

def _make_mock_app() -> Flask:
    """Return a bare-bones Flask app with just a POST /update route."""
    app = Flask("mock_ew_api")

    # Suppress Flask startup noise
    import logging as _lg
    _lg.getLogger("werkzeug").setLevel(_lg.ERROR)

    @app.route("/update", methods=["POST"])
    def post_update():
        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({"error": "bad json"}), 400
        return jsonify({"status": "accepted", "domain": "TEST"}), 200

    @app.route("/globalview", methods=["GET"])
    def globalview():
        return jsonify({"switches": {}, "inter_links": [], "util_rates": {},
                        "peer_meta": {}}), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True}), 200

    return app


def _start_server(app: Flask) -> tuple[int, threading.Thread]:
    """Start Flask on a random free port; return (port, thread)."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    t = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True
    )
    t.start()
    # Wait for server to accept connections
    for _ in range(40):
        try:
            requests.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            return port, t
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Mock Flask server failed to start within 4 seconds")


# ── Test counters ─────────────────────────────────────────────────────────────
_passed = 0
_failed = 0


def _assert(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _pass(name)
        _passed += 1
    else:
        _fail(name, detail or "Assertion failed")
        _failed += 1


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 1 — EW Flood Mitigator
# ══════════════════════════════════════════════════════════════════════════════

def test_ew_flood_mitigator() -> None:
    _section("Suite 1 · EW Flood Mitigator  (defense/ew_flood_mitigator.py)")

    # ── Import ────────────────────────────────────────────────────────────────
    try:
        from defense.ew_flood_mitigator import EWFloodMitigator, install_ew_flood_mitigator
    except ImportError as exc:
        print(f"  {_RED}IMPORT ERROR{_RESET}: {exc}")
        global _failed
        _failed += 6
        return

    # ── Test 1: Unit — token bucket allows up to burst ────────────────────────
    print("\n  [Unit] Token bucket behaviour")
    from defense.ew_flood_mitigator import TokenBucket
    bucket = TokenBucket(rate=10.0, burst=5.0)
    allowed = sum(1 for _ in range(10) if bucket.consume())
    _assert("Token bucket allows up to burst (5 of 10 immediate calls)",
            allowed == 5,
            f"Expected 5 allowed, got {allowed}")

    # ── Test 2: Unit — sliding window counter rate ────────────────────────────
    print("\n  [Unit] Sliding window counter")
    from defense.ew_flood_mitigator import SlidingWindowCounter
    sw = SlidingWindowCounter(window_seconds=1.0)
    for _ in range(20):
        sw.record()
    rate = sw.rate()
    _assert("Sliding window rate ≈ 20 req/s after 20 records in 1s window",
            15.0 <= rate <= 25.0,
            f"Got rate={rate:.1f} req/s (expected ~20)")

    # ── Test 3: Unit — check_request respects per-peer limit ─────────────────
    print("\n  [Unit] EWFloodMitigator.check_request")
    m = EWFloodMitigator(per_peer_rate=5, per_peer_burst=3,
                         global_rate=1000, global_burst=1000,
                         anomaly_threshold=9999)
    allowed_count = sum(1 for _ in range(10) if m.check_request("1.2.3.4")[0])
    _assert("check_request blocks excess over per-peer burst (3 of 10)",
            allowed_count == 3,
            f"Expected 3 allowed, got {allowed_count}")
    m.stop()

    # ── Test 4: Flask middleware — normal request is 200 ──────────────────────
    print("\n  [Middleware] Flask integration")
    app4 = _make_mock_app()
    from defense.ew_flood_mitigator import install_ew_flood_mitigator
    install_ew_flood_mitigator(
        app4,
        per_peer_rate=100, per_peer_burst=200,
        global_rate=200,   global_burst=400,
        anomaly_threshold=9999,
    )
    port4, _ = _start_server(app4)
    url4 = f"http://127.0.0.1:{port4}/update"

    good_payload = {"type": "topology", "domain_id": "B", "seq": 1,
                    "switches": {}, "links": [], "inter_links": [], "hosts": {}}
    r = requests.post(url4, json=good_payload, headers={"X-Domain-Id": "B"}, timeout=3)
    _assert("Normal /update request returns HTTP 200",
            r.status_code == 200,
            f"Got HTTP {r.status_code}")

    # ── Test 5: Flask middleware — flood is throttled to 429 ──────────────────
    app5 = _make_mock_app()
    install_ew_flood_mitigator(
        app5,
        per_peer_rate=5, per_peer_burst=5,
        global_rate=1000, global_burst=1000,
        anomaly_threshold=9999,
    )
    port5, _ = _start_server(app5)
    url5 = f"http://127.0.0.1:{port5}/update"

    _log(f"  Firing 30 rapid /update requests at port {port5}...")
    results = []
    for i in range(30):
        rr = requests.post(url5, json={**good_payload, "seq": i},
                           headers={"X-Domain-Id": "ROGUE"}, timeout=3)
        results.append(rr.status_code)

    rate_limited = results.count(429)
    _assert("Rapid flood (30 req) produces ≥10 HTTP 429 responses",
            rate_limited >= 10,
            f"Got only {rate_limited} throttled responses (expected ≥10)")
    _log(f"    → {results.count(200)} allowed, {rate_limited} throttled")

    # ── Test 6: Quarantine activates under sustained overload ─────────────────
    print("\n  [Integration] Anomaly detector quarantine")
    m6 = EWFloodMitigator(per_peer_rate=1000, per_peer_burst=10000,
                          global_rate=1000, global_burst=10000,
                          anomaly_threshold=10,  # very low threshold
                          anomaly_window=2,
                          quarantine_rate=2, quarantine_burst=2,
                          quarantine_dur=30)
    # Fire 50 rapid requests to push the sliding window over threshold
    for _ in range(50):
        m6.check_request("10.0.0.1")
    # Give detector thread time to fire (window=2s, poll=1s → max 3s)
    _log("  Waiting 4s for anomaly detector to trigger quarantine...")
    time.sleep(4)
    snap = m6.stats_snapshot()
    _assert("Quarantine activates after sustained rate > anomaly_threshold",
            snap.get("quarantines", 0) >= 1,
            f"quarantines={snap.get('quarantines')}, alerts={snap.get('alerts')}, "
            f"rate={snap.get('current_rate_per_s')}")
    m6.stop()


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 2 — Topology Guard
# ══════════════════════════════════════════════════════════════════════════════

def test_topology_guard() -> None:
    _section("Suite 2 · Topology Guard  (defense/topology_guard.py)")

    try:
        from defense.topology_guard import (
            TopologyGuard, GuardRejection,
            validate_topology_payload, SchemaError,
            compute_hmac, verify_hmac, sign_payload,
            install_topology_guard, SemanticChecker,
        )
    except ImportError as exc:
        print(f"  {_RED}IMPORT ERROR{_RESET}: {exc}")
        global _failed
        _failed += 9
        return

    SECRET = "test-secret-key"

    # ── Test 1: HMAC sign/verify round-trip ───────────────────────────────────
    print("\n  [Unit] HMAC-SHA256 authentication")
    sample = {"type": "topology", "domain_id": "A", "seq": 42,
              "switches": {}, "links": [], "inter_links": [], "hosts": {}}
    sig  = sign_payload(sample, SECRET)
    body = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    _assert("sign_payload() produces a 64-char hex signature",
            len(sig) == 64 and all(c in "0123456789abcdef" for c in sig),
            f"Got: {sig!r}")
    _assert("verify_hmac() accepts correctly signed payload",
            verify_hmac(body, sig, SECRET),
            "HMAC verification failed on own signature")
    _assert("verify_hmac() rejects tampered payload",
            not verify_hmac(body + b"x", sig, SECRET),
            "HMAC accepted tampered payload — timing/comparison bug")
    _assert("verify_hmac() rejects wrong secret",
            not verify_hmac(body, sig, "wrong-secret"),
            "HMAC accepted wrong secret")

    # ── Test 2: Schema validation — valid payload passes ─────────────────────
    print("\n  [Unit] Schema validation")
    valid_topo = {"type": "topology", "domain_id": "A", "seq": 1,
                  "switches": {"1": {"dpid": 1, "domain": "A", "ports": [1, 2]}},
                  "links": [{"src_dpid": 1, "src_port": 1, "dst_dpid": 2, "dst_port": 2}],
                  "inter_links": [{"src_dpid": 3, "src_port": 3, "dst_dpid": 4, "dst_port": 3}],
                  "hosts": {}}
    try:
        validate_topology_payload(valid_topo, {"A", "B", "C"})
        _assert("Valid topology payload passes schema validation", True)
    except SchemaError as e:
        _assert("Valid topology payload passes schema validation", False, str(e))

    # ── Test 3: Schema validation — ROGUE domain rejected ────────────────────
    rogue_topo = {**valid_topo, "domain_id": "ROGUE"}
    try:
        validate_topology_payload(rogue_topo, {"A", "B", "C"})
        _assert("ROGUE domain_id rejected by schema", False, "Should have raised SchemaError")
    except SchemaError:
        _assert("ROGUE domain_id rejected by schema", True)

    # ── Test 4: Schema validation — phantom link (port=99) rejected ───────────
    phantom_payload = {
        "type": "topology", "domain_id": "B", "seq": 9999,
        "switches": {"2": {"dpid": 2, "domain": "ROGUE", "ports": [1,2,3,4,5]},
                     "8": {"dpid": 8, "domain": "ROGUE", "ports": [1,2,3,4,5]}},
        "links": [],
        "inter_links": [{"src_dpid": 2, "src_port": 99, "dst_dpid": 8, "dst_port": 99}],
        "hosts": {}
    }
    try:
        validate_topology_payload(phantom_payload, {"A", "B", "C"}, phantom_port_threshold=50)
        _assert("Phantom link (port=99) rejected by schema", False, "Should have raised SchemaError")
    except SchemaError as e:
        _assert("Phantom link (port=99) rejected by schema", True)
        _log(f"    Rejection reason: {e}")

    # ── Test 5: Schema validation — congestion_lie ratio=0.95 field check ─────
    congestion_payload = {
        "type": "linkstate", "domain_id": "A", "seq": 9999,
        "link_state": {},
        "util_rates": {"3": {"3": {"ratio": 0.95, "bps_tx": 9500000, "bps_rx": 9500000}}}
    }
    try:
        validate_topology_payload(congestion_payload, {"A", "B", "C"})
        # Schema alone allows ratio=0.95 (it's syntactically valid);
        # the semantic checker handles the jump detection
        _assert("Congestion_lie payload (ratio=0.95) passes schema (semantic blocks it)", True)
    except SchemaError as e:
        _assert("Congestion_lie payload (ratio=0.95) passes schema (semantic blocks it)",
                False, f"Unexpected schema error: {e}")

    # ── Test 6: Semantic checker — catches ratio jump ─────────────────────────
    print("\n  [Unit] Semantic cross-checker")
    sc = SemanticChecker(max_ratio_delta=0.60)
    # Seed a known-good low ratio
    sc.check_util_rates({"3": {"3": {"ratio": 0.05}}})
    # Now inject a congestion lie: jump from 0.05 → 0.95 (delta=0.90 > 0.60)
    anomalies = sc.check_util_rates({"3": {"3": {"ratio": 0.95}}})
    _assert("Semantic checker detects congestion_lie ratio jump (0.05 → 0.95)",
            len(anomalies) >= 1,
            f"Expected ≥1 anomaly, got {anomalies}")
    _log(f"    Anomaly: {anomalies[0] if anomalies else 'none'}")

    # Verify a legitimate gradual increase is NOT flagged
    sc2 = SemanticChecker(max_ratio_delta=0.60)
    sc2.check_util_rates({"3": {"3": {"ratio": 0.20}}})
    no_anomalies = sc2.check_util_rates({"3": {"3": {"ratio": 0.50}}})
    _assert("Semantic checker allows legitimate gradual utilization increase (0.20→0.50)",
            len(no_anomalies) == 0,
            f"Flagged legitimate traffic: {no_anomalies}")

    # ── Test 7: TopologyGuard full pipeline — unsigned request rejected ────────
    print("\n  [Integration] TopologyGuard full pipeline")
    guard = TopologyGuard(shared_secret=SECRET, trusted_domains={"A","B","C"},
                          hmac_required=True)
    body = json.dumps(valid_topo, sort_keys=True, separators=(",", ":")).encode()

    try:
        guard.validate(body, {}, valid_topo)  # no X-EW-Signature header
        _assert("Unsigned request rejected by full pipeline", False, "Should have raised GuardRejection")
    except GuardRejection:
        _assert("Unsigned request rejected by full pipeline", True)

    # ── Test 8: TopologyGuard — correctly signed trusted request passes ───────
    sig2 = sign_payload(valid_topo, SECRET)
    headers2 = {"X-EW-Signature": sig2}
    try:
        guard.validate(body, headers2, valid_topo)
        _assert("Correctly signed trusted request accepted by full pipeline", True)
    except GuardRejection as e:
        _assert("Correctly signed trusted request accepted by full pipeline", False, str(e))

    # ── Test 9: Flask middleware — end-to-end with real HTTP ─────────────────
    print("\n  [Middleware] Flask end-to-end")
    app9 = _make_mock_app()
    install_topology_guard(app9, shared_secret=SECRET,
                           trusted_domains={"A","B","C"}, hmac_required=True)
    port9, _ = _start_server(app9)
    url9 = f"http://127.0.0.1:{port9}/update"

    # 9a: Signed trusted request → 200
    sig3  = sign_payload(valid_topo, SECRET)
    body3 = json.dumps(valid_topo, sort_keys=True, separators=(",", ":")).encode()
    r3 = requests.post(url9, data=body3,
                       headers={"Content-Type": "application/json",
                                "X-Domain-Id": "A",
                                "X-EW-Signature": sig3}, timeout=3)
    _assert("Flask middleware: signed trusted request → HTTP 200",
            r3.status_code == 200,
            f"Got HTTP {r3.status_code}: {r3.text[:100]}")

    # 9b: Unsigned ROGUE request → 403
    rogue_body = json.dumps(phantom_payload, sort_keys=True, separators=(",", ":")).encode()
    r4 = requests.post(url9, data=rogue_body,
                       headers={"Content-Type": "application/json",
                                "X-Domain-Id": "ROGUE"}, timeout=3)
    _assert("Flask middleware: unsigned ROGUE topology poison request → HTTP 403",
            r4.status_code == 403,
            f"Got HTTP {r4.status_code}: {r4.text[:100]}")

    # 9c: Signed but schema-invalid (phantom link) → 403
    phantom_signed = sign_payload(phantom_payload, SECRET)
    phantom_body   = json.dumps(phantom_payload, sort_keys=True, separators=(",", ":")).encode()
    r5 = requests.post(url9, data=phantom_body,
                       headers={"Content-Type": "application/json",
                                "X-Domain-Id": "B",
                                "X-EW-Signature": phantom_signed}, timeout=3)
    _assert("Flask middleware: signed phantom_link payload (port=99) → HTTP 403",
            r5.status_code == 403,
            f"Got HTTP {r5.status_code}: {r5.text[:100]}")
    _log(f"    Rejection: {r5.json()}")


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 3 — Dual-module integration (both middlewares stacked)
# ══════════════════════════════════════════════════════════════════════════════

def test_stacked_middlewares() -> None:
    _section("Suite 3 · Stacked defenses  (rate-limit outer + topology guard inner)")

    try:
        from defense.ew_flood_mitigator import install_ew_flood_mitigator
        from defense.topology_guard import install_topology_guard, sign_payload
    except ImportError as exc:
        print(f"  {_RED}IMPORT ERROR{_RESET}: {exc}")
        global _failed
        _failed += 2
        return

    SECRET = "stack-test-secret"
    app = _make_mock_app()

    # Install rate-limiter first (outer), topology guard second (inner)
    install_ew_flood_mitigator(
        app,
        per_peer_rate=100, per_peer_burst=200,
        global_rate=200,   global_burst=400,
        anomaly_threshold=9999,
    )
    install_topology_guard(app, shared_secret=SECRET,
                           trusted_domains={"A","B","C"}, hmac_required=True)

    port, _ = _start_server(app)
    url = f"http://127.0.0.1:{port}/update"

    valid_topo = {"type": "topology", "domain_id": "A", "seq": 1,
                  "switches": {}, "links": [], "inter_links": [], "hosts": {}}
    sig  = sign_payload(valid_topo, SECRET)
    body = json.dumps(valid_topo, sort_keys=True, separators=(",", ":")).encode()

    # Test 1: Signed good request passes both layers
    r = requests.post(url, data=body,
                      headers={"Content-Type": "application/json",
                               "X-Domain-Id": "A",
                               "X-EW-Signature": sig}, timeout=3)
    _assert("Stacked: signed, valid request passes both layers → HTTP 200",
            r.status_code == 200,
            f"Got HTTP {r.status_code}")

    # Test 2: Unsigned flood is caught at rate-limiter OR guard (either 429 or 403)
    bad_results = []
    for i in range(20):
        rr = requests.post(url,
                           json={"type": "topology", "domain_id": "ROGUE", "seq": i,
                                 "switches": {}, "links": [], "inter_links": [], "hosts": {}},
                           headers={"X-Domain-Id": "ROGUE"}, timeout=3)
        bad_results.append(rr.status_code)

    blocked = sum(1 for s in bad_results if s in (403, 429))
    _assert("Stacked: 20 unsigned ROGUE requests are all blocked (403 or 429)",
            blocked == 20,
            f"Only {blocked}/20 blocked. Status codes: {set(bad_results)}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    global VERBOSE

    parser = argparse.ArgumentParser(
        description="Verify ew_flood_mitigator.py and topology_guard.py defenses"
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show extra detail for each test")
    args = parser.parse_args()
    VERBOSE = args.verbose

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\n{_BOLD}╔══════════════════════════════════════════════════╗{_RESET}")
    print(f"{_BOLD}║   Phase 6 Defense Verification Suite             ║{_RESET}")
    print(f"{_BOLD}║   {ts}                    ║{_RESET}")
    print(f"{_BOLD}╚══════════════════════════════════════════════════╝{_RESET}")

    test_ew_flood_mitigator()
    test_topology_guard()
    test_stacked_middlewares()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = _passed + _failed
    print(f"\n{'═'*60}")
    if _failed == 0:
        print(f"{_GREEN}{_BOLD}  ALL {total} TESTS PASSED{_RESET}")
    else:
        print(f"{_RED}{_BOLD}  {_failed}/{total} TESTS FAILED{_RESET}  "
              f"({_passed} passed)")
    print(f"{'═'*60}\n")

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
