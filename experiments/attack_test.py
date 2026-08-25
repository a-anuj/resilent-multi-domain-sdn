#!/usr/bin/env python3
"""
experiments/attack_test.py
---------------------------
Phase 5: Attack experiment orchestrator.

For each of the 3 attack modules:
  1. Run experiments/preflight_check.py  →  abort if it fails
  2. Baseline logging window (60 s, TE running normally)
  3. Launch the attack (watchdog-enforced, fixed duration)
  4. Continue logging throughout and for 60 s after attack stops (recovery)
  5. Save results/attack_<name>_<timestamp>.log

Metrics captured every POLL_INTERVAL seconds:
  - Controller REST API response latency (proxy for CPU / responsiveness)
  - EW sync convergence state (/peers endpoint)
  - Link utilisation ratios (/linkstate)
  - TE decision count delta (te_decisions.log line count)

Run (must be root — Mininet requires it):
    sudo python3 experiments/attack_test.py [--attacks packetin eastwest poison]

Requires:
    - All 3 EW controllers already running (ports 8080/8081/8082)
    - Mininet topology NOT yet started (this script starts it)
    - iperf3 installed inside host namespaces
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Project path ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Constants ─────────────────────────────────────────────────────────────────
EW_PORTS       = {"A": 8080, "B": 8081, "C": 8082}
EW_HOST        = "127.0.0.1"
HTTP_TIMEOUT   = 3
POLL_INTERVAL  = 5        # seconds between metric snapshots
BASELINE_DUR   = 60       # seconds
RECOVERY_DUR   = 60       # seconds

# Attack durations (watchdog-enforced in the attack scripts themselves)
#
# PacketIn rates: raised to 500→5000 pkt/s to find the controller's saturation point.
# Earlier runs at 50→300 showed no measurable effect; these higher rates are needed
# to produce data worth reporting (either a real effect, or a resilience finding).
ATTACK_CONFIGS = {
    "packetin": {
        "script":   str(_ROOT / "attacks" / "packetin_flood.py"),
        "args":     ["--target", "10.0.0.9",
                     "--iface", "h1-eth0",
                     "--start-rate", "500",
                     "--max-rate", "5000",
                     "--step", "500",
                     "--duration", "120"],
        "duration": 120,
        "label":    "PacketIn Flood (North-South)",
    },
    "eastwest": {
        "script":   str(_ROOT / "attacks" / "eastwest_flood.py"),
        "args":     ["--target-port", "8080",
                     "--start-rate", "10",
                     "--max-rate", "150",
                     "--duration", "90"],
        "duration": 90,
        "label":    "East-West REST Flood (Novel)",
    },
    "poison": {
        "script":   str(_ROOT / "attacks" / "topology_poison.py"),
        "args":     ["--target-port", "8081",
                     "--lie-type", "congestion_lie",
                     "--src-dpid", "3",
                     "--dst-dpid", "4",
                     "--fake-ratio", "0.95",
                     "--repeat", "3"],
        "duration": 30,
        "label":    "Topology Poisoning (Novel)",
    },
}

RESULTS_DIR = _ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)
TE_DEC_LOG  = RESULTS_DIR / "te_decisions.log"
EMERGENCY   = _HERE / "emergency_reset.sh"
PREFLIGHT   = _HERE / "preflight_check.py"


# ── Logging helpers ───────────────────────────────────────────────────────────

def _make_logger(name: str, logfile: Path) -> logging.Logger:
    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fh = logging.FileHandler(logfile, mode="w", encoding="utf-8")
    sh = logging.StreamHandler(sys.stdout)
    for h in (fh, sh):
        h.setFormatter(fmt)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ── Metric collectors ─────────────────────────────────────────────────────────

def _ctrl_latency(domain: str) -> float | None:
    """Return REST API response latency in milliseconds (None on failure)."""
    url = f"http://{EW_HOST}:{EW_PORTS[domain]}/topology"
    t0 = time.monotonic()
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            return (time.monotonic() - t0) * 1000.0
    except Exception:
        pass
    return None


def _link_utils() -> dict:
    """Fetch utilisation ratios from all 3 controllers; return merged dict."""
    merged = {}
    for domain, port in EW_PORTS.items():
        try:
            r = requests.get(
                f"http://{EW_HOST}:{port}/linkstate", timeout=HTTP_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                merged[domain] = data.get("util_rates", {})
        except Exception:
            pass
    return merged


def _te_decision_count() -> int:
    """Return the number of lines currently in te_decisions.log.

    This reads the live file on every call — it is NOT cached.
    If the count stays static across an entire experiment, that means no new
    inter-domain TE decisions were triggered (expected when no iperf/new flows
    are active during the attack suite).  Document this explicitly in results.
    """
    try:
        with open(TE_DEC_LOG) as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def _sync_peer_ages(domain: str) -> dict:
    """Return peer last-seen ages from /peers for a given controller."""
    try:
        r = requests.get(
            f"http://{EW_HOST}:{EW_PORTS[domain]}/peers", timeout=HTTP_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def collect_snapshot(log: logging.Logger, label: str = "") -> dict:
    """Collect one metric snapshot and log it; return the dict."""
    snap: dict = {
        "ts":          datetime.now(timezone.utc).isoformat(),
        "label":       label,
        "latency_ms":  {},
        "te_decisions": _te_decision_count(),
        "util":        _link_utils(),
        "peer_ages":   {},
    }
    for domain in EW_PORTS:
        lat = _ctrl_latency(domain)
        snap["latency_ms"][domain] = lat
        snap["peer_ages"][domain]  = _sync_peer_ages(domain)

    lat_str = {d: (f"{v:.1f}" if v else "TIMEOUT")
               for d, v in snap["latency_ms"].items()}
    log.info("[METRIC%s] lat_ms=%s  te_decisions=%d",
             f"/{label}" if label else "",
             lat_str, snap["te_decisions"])
    return snap


# ── Metric logging loop ───────────────────────────────────────────────────────

def _metric_loop(log: logging.Logger, snapshots: list[dict],
                 stop_evt: threading.Event, label: str) -> None:
    while not stop_evt.is_set():
        snap = collect_snapshot(log, label=label)
        snapshots.append(snap)
        stop_evt.wait(timeout=POLL_INTERVAL)


def start_metric_logger(log: logging.Logger, snapshots: list[dict],
                         label: str) -> tuple[threading.Thread, threading.Event]:
    stop_evt = threading.Event()
    t = threading.Thread(
        target=_metric_loop,
        args=(log, snapshots, stop_evt, label),
        daemon=True,
        name=f"metrics-{label}",
    )
    t.start()
    return t, stop_evt


# ── Preflight ─────────────────────────────────────────────────────────────────

def run_preflight(log: logging.Logger) -> bool:
    log.info("Running preflight_check.py ...")
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT)],
        capture_output=True, text=True,
    )
    (log.info if result.returncode == 0 else log.error)(
        "preflight stdout: %s", result.stdout.strip()
    )
    if result.stderr.strip():
        log.error("preflight stderr: %s", result.stderr.strip())
    return result.returncode == 0


def _check_ew_connectivity(port: int, log: logging.Logger) -> bool:
    """Return True if the EW REST API at localhost:port is reachable.

    This is a pre-launch guard for the East-West flood: if the /update
    endpoint is not reachable, the flood will run but produce only
    'Connection refused' errors and give meaningless latency data.
    """
    url = f"http://127.0.0.1:{port}/topology"
    try:
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            log.info("EW connectivity OK: %s → HTTP %d", url, r.status_code)
            return True
        log.warning("EW connectivity check: unexpected status %d at %s", r.status_code, url)
        return False
    except Exception as exc:
        log.error("EW connectivity FAILED for %s: %s", url, exc)
        return False


def _drain_subprocess_output(proc: subprocess.Popen,
                              timeout: float) -> tuple[int, str]:
    """Wait for subprocess to complete, drain its stdout pipe, return (returncode, output).

    Using communicate() instead of wait() avoids the Popen deadlock that can occur
    when stdout=PIPE is used and the pipe buffer fills before the process exits.
    The timeout triggers if the attack overruns its expected window.
    """
    try:
        out_bytes, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out_bytes.decode(errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        out_bytes, _ = proc.communicate()
        return proc.returncode, out_bytes.decode(errors="replace")


# ── Emergency reset ───────────────────────────────────────────────────────────

def run_emergency_reset(log: logging.Logger) -> None:
    log.error("Running emergency_reset.sh ...")
    try:
        subprocess.run(["sudo", "bash", str(EMERGENCY)], timeout=60)
    except Exception as exc:
        log.error("emergency_reset.sh failed: %s", exc)


# ── TE ground-truth path helper ───────────────────────────────────────────────

def fetch_te_path(src_dpid: int, dst_dpid: int) -> dict | None:
    """Ask Domain-A controller for the current TE-selected path."""
    try:
        r = requests.get(
            f"http://{EW_HOST}:{EW_PORTS['A']}/te_path",
            params={"src_dpid": src_dpid, "dst_dpid": dst_dpid, "te": "1"},
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── Single attack experiment ──────────────────────────────────────────────────

def run_attack_experiment(attack_key: str, cfg: dict,
                          net=None) -> dict:
    """
    Run one full attack experiment cycle:
      preflight → baseline → attack → recovery → save results.
    Returns a summary dict.
    """
    ts    = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = attack_key
    log_path = RESULTS_DIR / f"attack_{label}_{ts}.log"
    log = _make_logger(f"atk_{label}", log_path)

    log.info("=" * 70)
    log.info("EXPERIMENT: %s", cfg["label"])
    log.info("  Attack key  : %s", attack_key)
    log.info("  Log file    : %s", log_path)
    log.info("=" * 70)

    snapshots: dict[str, list[dict]] = {
        "baseline": [], "during": [], "recovery": []
    }

    try:
        # ── 1. Preflight ─────────────────────────────────────────────────────
        if not run_preflight(log):
            log.error("PREFLIGHT FAILED — aborting experiment for '%s'.", label)
            return {"attack": label, "result": "PREFLIGHT_FAIL", "log": str(log_path)}

        # ── 2. Baseline window (60 s) ─────────────────────────────────────────
        log.info("─" * 70)
        log.info("PHASE: BASELINE (60 s) — TE running normally")
        log.info("─" * 70)

        # Snapshot TE path before attack for ground-truth comparison (poison attack)
        te_before = fetch_te_path(src_dpid=1, dst_dpid=9)
        log.info("TE path before attack (s1→s9): %s", te_before)

        bl_thread, bl_stop = start_metric_logger(log, snapshots["baseline"], "baseline")
        time.sleep(BASELINE_DUR)
        bl_stop.set()
        bl_thread.join(timeout=10)

        log.info("Baseline complete: %d snapshots collected.", len(snapshots["baseline"]))

        # ── 3. Launch attack ──────────────────────────────────────────────────
        log.info("─" * 70)
        log.info("PHASE: ATTACK — %s", cfg["label"])
        log.info("─" * 70)

        atk_proc = None
        attack_pid: str | int = "N/A"
        atk_exit_early = False   # set True if proc exits significantly before duration

        # Pre-launch connectivity check for East-West flood
        if attack_key == "eastwest":
            ew_port = int(next(
                a for i, a in enumerate(cfg["args"])
                if cfg["args"][i - 1] == "--target-port"
            ))
            if not _check_ew_connectivity(ew_port, log):
                log.error(
                    "EASTWEST ABORT: controller REST API not reachable on port %d. "
                    "The flood would produce only connection-refused errors. "
                    "Ensure all three Ryu controllers are running before re-running.",
                    ew_port,
                )
                return {
                    "attack": label,
                    "result": "CONNECTIVITY_FAIL",
                    "log": str(log_path),
                    "detail": f"Controller REST port {ew_port} not reachable",
                }

        # PacketIn flood must run inside h1's namespace via Mininet
        if attack_key == "packetin" and net is not None:
            h1 = net.get("h1")
            cmd = " ".join(
                [sys.executable, cfg["script"]] + cfg["args"] + ["--yes"]
            )
            log.info("Launching packetin flood inside h1 namespace: %s", cmd)
            # Run non-blocking inside h1's namespace via popen
            h1.cmd(f"nohup {cmd} > /tmp/atk_packetin.log 2>&1 &")
            attack_pid = h1.cmd("echo $!").strip()
            log.info("Attack PID in h1 namespace: %s", attack_pid)
        else:
            # eastwest_flood and topology_poison run from host Python directly
            # (they target 127.0.0.1 controller ports, not Mininet NICs)
            cmd = [sys.executable, cfg["script"]] + cfg["args"] + ["--yes"]
            log.info("Launching attack subprocess: %s", " ".join(cmd))
            atk_proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            attack_pid = atk_proc.pid
            log.info("Attack process PID: %d", attack_pid)

        atk_start = time.time()

        # ── 4. Metric logging during attack ───────────────────────────────────
        dur_thread, dur_stop = start_metric_logger(log, snapshots["during"], "during")

        # Wait for attack to complete (or watchdog to kill it).
        # Use _drain_subprocess_output() instead of bare wait() to avoid pipe deadlocks
        # and to capture the subprocess's stdout/stderr for failure diagnosis.
        atk_returncode: int | None = None
        atk_output: str = ""
        if attack_key == "packetin" and net is not None:
            time.sleep(cfg["duration"] + 10)
        elif atk_proc is not None:
            atk_returncode, atk_output = _drain_subprocess_output(
                atk_proc, timeout=cfg["duration"] + 30
            )

        dur_stop.set()
        dur_thread.join(timeout=10)

        atk_elapsed = time.time() - atk_start

        # ── Evaluate whether the attack actually ran its full duration ─────────
        EARLY_EXIT_THRESHOLD = 0.5   # fraction of configured duration
        expected_min = cfg["duration"] * EARLY_EXIT_THRESHOLD
        if atk_elapsed < expected_min:
            atk_exit_early = True
            log.error(
                "EARLY EXIT DETECTED: attack ran %.1f s but expected ≥ %.0f s "
                "(%.0f%% of configured %d s duration). "
                "This invalidates 'during' phase metrics. "
                "Return code: %s",
                atk_elapsed, expected_min,
                100.0 * atk_elapsed / cfg["duration"],
                cfg["duration"],
                atk_returncode,
            )
        else:
            log.info(
                "Attack phase done. Elapsed: %.1f s  (returncode=%s)",
                atk_elapsed, atk_returncode,
            )

        # Log subprocess output regardless of exit status — essential for debugging
        if atk_output:
            tail = atk_output[-4000:]   # last 4KB is most relevant for crashes
            log.info(
                "Attack subprocess stdout/stderr (last 4KB):\n%s",
                tail,
            )
        if atk_returncode not in (None, 0):
            log.error(
                "Attack subprocess exited with non-zero returncode=%d",
                atk_returncode,
            )

        # Snapshot count sanity check
        expected_snaps = cfg["duration"] // POLL_INTERVAL
        actual_snaps = len(snapshots["during"])
        if actual_snaps < expected_snaps // 2:
            log.warning(
                "INSUFFICIENT SNAPSHOTS during attack: got %d, expected ~%d "
                "(at %ds poll interval for %ds attack). "
                "Statistical comparison will be unreliable.",
                actual_snaps, expected_snaps, POLL_INTERVAL, cfg["duration"],
            )

        # Snapshot TE path immediately after attack to check poison effect
        te_during = fetch_te_path(src_dpid=1, dst_dpid=9)
        log.info("TE path DURING/AFTER attack (s1→s9): %s", te_during)

        # ── 5. Recovery window (60 s) ─────────────────────────────────────────
        log.info("─" * 70)
        log.info("PHASE: RECOVERY (60 s)")
        log.info("─" * 70)

        rec_thread, rec_stop = start_metric_logger(log, snapshots["recovery"], "recovery")
        time.sleep(RECOVERY_DUR)
        rec_stop.set()
        rec_thread.join(timeout=10)

        te_after = fetch_te_path(src_dpid=1, dst_dpid=9)
        log.info("TE path AFTER recovery (s1→s9): %s", te_after)

        # ── 6. Analyse and summarise ──────────────────────────────────────────
        def _avg_lat(snaps: list[dict], domain: str) -> float | None:
            vals = [s["latency_ms"].get(domain) for s in snaps
                    if s["latency_ms"].get(domain) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        def _timeout_pct(snaps: list[dict], domain: str) -> float:
            total = len(snaps)
            if total == 0:
                return 0.0
            timeouts = sum(1 for s in snaps
                           if s["latency_ms"].get(domain) is None)
            return round(100.0 * timeouts / total, 1)

        def _te_delta(phase_snaps: list[dict], baseline_snaps: list[dict]) -> int | None:
            """Return net new TE decisions during this phase vs baseline start.

            te_decisions is a cumulative log-line count. A static value across all
            phases means zero new TE decisions were triggered — expected when no
            inter-domain flows are active (no iperf during this suite).
            'te_path: None' is also expected for the same reason: /te_path returns
            None when no active flow for the queried s1→s9 pair exists.
            """
            if not phase_snaps or not baseline_snaps:
                return None
            return phase_snaps[-1]["te_decisions"] - baseline_snaps[0]["te_decisions"]

        # Determine overall experiment status
        if atk_exit_early:
            exp_result = "EARLY_EXIT"
        elif atk_returncode is not None and atk_returncode != 0:
            exp_result = "SUBPROCESS_ERROR"
        elif len(snapshots["during"]) < (cfg["duration"] // POLL_INTERVAL) // 2:
            exp_result = "INSUFFICIENT_DATA"
        else:
            exp_result = "OK"

        summary = {
            "attack":   label,
            "result":   exp_result,
            "ts":       ts,
            "log":      str(log_path),
            "atk_elapsed_s":   round(atk_elapsed, 1),
            "atk_returncode":  atk_returncode,
            "baseline": {
                "n_snaps": len(snapshots["baseline"]),
                "avg_lat": {d: _avg_lat(snapshots["baseline"], d) for d in EW_PORTS},
                "timeout_pct": {d: _timeout_pct(snapshots["baseline"], d) for d in EW_PORTS},
                "te_decisions_abs": snapshots["baseline"][-1]["te_decisions"] if snapshots["baseline"] else 0,
            },
            "during": {
                "n_snaps":  len(snapshots["during"]),
                "avg_lat":  {d: _avg_lat(snapshots["during"], d) for d in EW_PORTS},
                "timeout_pct": {d: _timeout_pct(snapshots["during"], d) for d in EW_PORTS},
                "te_decisions_abs":   snapshots["during"][-1]["te_decisions"] if snapshots["during"] else 0,
                "te_decisions_delta": _te_delta(snapshots["during"], snapshots["baseline"]),
            },
            "recovery": {
                "n_snaps": len(snapshots["recovery"]),
                "avg_lat": {d: _avg_lat(snapshots["recovery"], d) for d in EW_PORTS},
                "timeout_pct": {d: _timeout_pct(snapshots["recovery"], d) for d in EW_PORTS},
                "te_decisions_delta": _te_delta(snapshots["recovery"], snapshots["baseline"]),
            },
            "te_path_before": te_before,
            "te_path_during": te_during,
            "te_path_after":  te_after,
            # NOTE: te_path=None and static te_decisions are EXPECTED when the
            # attack suite runs without active iperf flows. /te_path queries the
            # live flow table; with no s1→s9 flow active, it correctly returns None.
            # If te_decisions_delta stays 0 across all phases, no new inter-domain
            # paths were computed — consistent with this test design.
            "te_note": (
                "te_decisions is read live from te_decisions.log on every poll. "
                "A static value indicates zero new TE decisions during the suite — "
                "expected when no inter-domain iperf flows are active. "
                "te_path=None is correct when no s1→s9 flow is currently active."
            ),
        }

        # Did topology poison cause a path change?
        if attack_key == "poison" and te_before and te_during:
            path_before = te_before.get("path", [])
            path_during = te_during.get("path", [])
            summary["poison_caused_reroute"] = (path_before != path_during)
            log.info("Poison caused TE reroute: %s  (before=%s, during=%s)",
                     summary["poison_caused_reroute"], path_before, path_during)

        # Log latency degradation
        for domain in EW_PORTS:
            bl  = summary["baseline"]["avg_lat"].get(domain)
            dur = summary["during"]["avg_lat"].get(domain)
            if bl and dur:
                pct = (dur - bl) / bl * 100
                log.info("  [%s] REST latency: baseline=%.1fms  during=%.1fms  "
                         "delta=%+.1f%%", domain, bl, dur, pct)
            log.info("  [%s] Timeout rate: baseline=%.1f%%  during=%.1f%%",
                     domain,
                     summary["baseline"]["timeout_pct"].get(domain, 0),
                     summary["during"]["timeout_pct"].get(domain, 0))

        # Save JSON summary alongside log
        json_path = RESULTS_DIR / f"attack_{label}_{ts}_summary.json"
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        log.info("JSON summary saved: %s", json_path)

        log.info("=" * 70)
        log.info("EXPERIMENT DONE: %s  [result=%s]", cfg["label"], exp_result)
        log.info("=" * 70)
        return summary

    except Exception as exc:
        log.exception("Unexpected exception in experiment '%s': %s", label, exc)
        run_emergency_reset(log)
        return {"attack": label, "result": "EXCEPTION", "error": str(exc),
                "log": str(log_path)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5 attack experiment orchestrator"
    )
    parser.add_argument(
        "--attacks",
        nargs="+",
        choices=list(ATTACK_CONFIGS.keys()),
        default=list(ATTACK_CONFIGS.keys()),
        help="Which attacks to run (default: all three)"
    )
    parser.add_argument(
        "--with-mininet",
        action="store_true",
        help="Start Mininet internally (needed for PacketIn flood namespace injection). "
             "If omitted, assumes Mininet is already running externally."
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Run with sudo.", file=sys.stderr)
        return 1

    # Root-level log
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root_log_path = RESULTS_DIR / f"attack_suite_{ts}.log"
    root_log = _make_logger("attack_suite", root_log_path)

    root_log.info("=" * 70)
    root_log.info("PHASE 5 ATTACK SUITE  —  %s", ts)
    root_log.info("Attacks to run: %s", args.attacks)
    root_log.info("=" * 70)

    # Optionally start Mininet
    net = None
    if args.with_mininet:
        from mininet.log import setLogLevel
        from topology.multi_domain_topo import (
            build_network, assign_controllers, enable_rstp,
        )
        setLogLevel("warning")
        root_log.info("Starting Mininet network...")
        net = build_network()
        net.start()
        enable_rstp(net, wait=0)
        assign_controllers(net)
        root_log.info("Waiting 20s for switch↔controller connections...")
        time.sleep(20)

    summaries = []
    try:
        for atk_key in args.attacks:
            cfg = ATTACK_CONFIGS[atk_key]
            root_log.info("\n>>> Starting experiment: %s\n", cfg["label"])
            summary = run_attack_experiment(atk_key, cfg, net=net)
            summaries.append(summary)

            # Brief cool-down between attacks
            if atk_key != args.attacks[-1]:
                root_log.info("Cool-down 30 s before next experiment...")
                time.sleep(30)

    finally:
        if net is not None:
            root_log.info("Stopping Mininet.")
            net.stop()

    # Print final summary table
    root_log.info("\n" + "=" * 70)
    root_log.info("ALL EXPERIMENTS COMPLETE")
    root_log.info("=" * 70)
    for s in summaries:
        result = s.get("result", "OK")
        root_log.info("  %-12s  result=%-20s  log=%s",
                      s.get("attack", "?"), result, s.get("log", "?"))

    suite_json = RESULTS_DIR / f"attack_suite_{ts}_summary.json"
    with open(suite_json, "w") as f:
        json.dump(summaries, f, indent=2, default=str)
    root_log.info("Suite summary saved: %s", suite_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
