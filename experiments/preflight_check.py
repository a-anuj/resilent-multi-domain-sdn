#!/usr/bin/env python3
"""Fail-closed preflight checks required before any attack experiment."""

from __future__ import annotations

import subprocess
import sys
import urllib.error
import urllib.request

CONTROLLERS = {"A": 8080, "B": 8081, "C": 8082}
REQUIRED_BRIDGES = {f"s{number}" for number in range(1, 10)}
ATTACK_PROCESS_MARKERS = (
    "attacks/packetin_flood.py",
    "attacks/eastwest_flood.py",
    "attacks/topology_poison.py",
)


def check_mininet() -> list[str]:
    try:
        result = subprocess.run(
            ["ovs-vsctl", "list-br"], text=True, capture_output=True,
            timeout=5, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [f"Cannot inspect OVS bridges: {exc}"]
    if result.returncode != 0:
        return [f"ovs-vsctl list-br failed: {result.stderr.strip() or 'unknown error'}"]

    bridges = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    missing = sorted(REQUIRED_BRIDGES - bridges)
    return [] if not missing else [f"Mininet is not running; missing bridges: {', '.join(missing)}"]


def check_controllers() -> list[str]:
    failures: list[str] = []
    for domain, port in CONTROLLERS.items():
        url = f"http://127.0.0.1:{port}/topology"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status != 200:
                    failures.append(f"Controller {domain} returned HTTP {response.status} at {url}")
        except (urllib.error.URLError, TimeoutError) as exc:
            failures.append(f"Controller {domain} is unreachable at {url}: {exc}")
    return failures


def check_no_attack_processes() -> list[str]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="], text=True, capture_output=True,
            timeout=5, check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return [f"Cannot inspect running processes: {exc}"]

    matches = [line.strip() for line in result.stdout.splitlines()
               if any(marker in line for marker in ATTACK_PROCESS_MARKERS)]
    return [] if not matches else ["Attack process already running: " + " | ".join(matches)]


def main() -> int:
    failures = check_mininet() + check_controllers() + check_no_attack_processes()
    if failures:
        print("PREFLIGHT FAILED — do not start an attack:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("PREFLIGHT PASSED: Mininet, all three controllers, and attack process state are safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
