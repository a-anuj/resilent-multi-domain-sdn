"""Shared, fail-closed safety controls for all Phase 5 attack experiments.

Attack code must call :func:`validate_target` and
:func:`confirm_before_run` before transmitting traffic.  Flooding code must
iterate through :func:`safe_rate_ramp` and protect itself with
:func:`start_watchdog`.
"""

from __future__ import annotations

import ipaddress
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Iterator
from numbers import Real

# Confirmed in topology/multi_domain_topo.py: hosts use 10.0.0.1/24 through
# 10.0.0.12/24.  This deliberately excludes localhost and every real NIC.
ALLOWED_SUBNET = "10.0.0.0/24"
_ALLOWED_NETWORK = ipaddress.ip_network(ALLOWED_SUBNET)

# Mininet creates switch/host port names in this form.  Do not broaden this
# pattern without a specific topology change and a safety review.
_MININET_INTERFACE = re.compile(r"(?:s|h)[1-9][0-9]*-eth[0-9]+$")
MAX_WATCHDOG_SECONDS = 600


class UnsafeTargetError(ValueError):
    """Raised when a target is outside the isolated Mininet testbed."""


def validate_target(ip_or_iface: str) -> None:
    """Accept only a Mininet host IP or a Mininet-style port interface.

    The function is intentionally fail-closed: malformed strings, real host
    interfaces, loopback, controller REST addresses, and every address outside
    ``ALLOWED_SUBNET`` raise :class:`UnsafeTargetError`.
    """
    if not isinstance(ip_or_iface, str) or not ip_or_iface.strip():
        raise UnsafeTargetError("Target must be a non-empty IP address or interface name.")

    target = ip_or_iface.strip()
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        if _MININET_INTERFACE.fullmatch(target):
            return
        raise UnsafeTargetError(
            f"Refusing unsafe interface {target!r}. Only Mininet interfaces "
            "such as s1-eth1 or h1-eth0 are allowed."
        )

    if address not in _ALLOWED_NETWORK:
        raise UnsafeTargetError(
            f"Refusing target {address}: it is outside the isolated "
            f"Mininet subnet {ALLOWED_SUBNET}."
        )


def confirm_before_run(attack_name: str, target: str, rate: str,
                       duration: int) -> bool:
    """Show the exact action and require an interactive ``yes`` confirmation.

    ``False`` means the caller must abort without transmitting traffic.
    Ctrl-C and a closed stdin are treated as explicit rejection.
    """
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise ValueError("duration must be a positive whole number of seconds")

    print("\n=== ATTACK SAFETY CONFIRMATION ===")
    print(f"Attack:   {attack_name}")
    print(f"Target:   {target}")
    print(f"Rate:     {rate}")
    print(f"Duration: {duration} seconds (watchdog required)")
    print("Only proceed if this target is inside the Mininet testbed.")
    try:
        return input("Type 'yes' to continue: ").strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print("\nConfirmation cancelled; no traffic will be sent.")
        return False


def safe_rate_ramp(start_rate: Real, max_rate: Real, step: Real,
                   interval: Real) -> Iterator[Real]:
    """Yield a bounded low-to-high rate ramp, pausing between each step.

    Values must be positive, with ``start_rate <= max_rate``.  The maximum is
    always yielded exactly once, including when it is not a multiple of step.
    """
    values = (start_rate, max_rate, step, interval)
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
        raise TypeError("rate ramp values must be numeric")
    if start_rate <= 0 or max_rate <= 0 or step <= 0 or interval <= 0:
        raise ValueError("rate ramp values must be greater than zero")
    if start_rate > max_rate:
        raise ValueError("start_rate cannot exceed max_rate")

    rate = start_rate
    while True:
        yield rate
        if rate >= max_rate:
            return
        time.sleep(interval)
        rate = min(rate + step, max_rate)


def start_watchdog(max_duration_seconds: int) -> threading.Timer:
    """Terminate this process if an attack outlives its approved duration.

    The returned timer must be cancelled in a ``finally`` block after a normal
    completion.  A hard 10-minute ceiling prevents a caller from disabling the
    safety mechanism with an unbounded duration.
    """
    if (not isinstance(max_duration_seconds, int)
            or isinstance(max_duration_seconds, bool)
            or not 0 < max_duration_seconds <= MAX_WATCHDOG_SECONDS):
        raise ValueError(
            f"watchdog duration must be an integer from 1 to {MAX_WATCHDOG_SECONDS} seconds"
        )

    def _terminate() -> None:
        print("\nSAFETY WATCHDOG EXPIRED: terminating attack process.", file=sys.stderr)
        # SIGKILL cannot be intercepted or ignored by an accidentally hung
        # attack process.
        os.kill(os.getpid(), signal.SIGKILL)

    timer = threading.Timer(max_duration_seconds, _terminate)
    timer.daemon = True
    timer.start()
    return timer
