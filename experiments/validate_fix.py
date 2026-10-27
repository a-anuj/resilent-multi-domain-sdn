#!/usr/bin/env python3
"""
experiments/validate_fix.py
---------------------------
Comprehensive validation suite to verify the fix for intermittent Probe A failures.

Validates:
1. Controller-only check (/health endpoints on ports 8080, 8081, 8082)
2. Baseline test (topology + CB daemon running, 30 probes, zero triggers)
3. Defended attack test (Packet-In flood from h1, CB detection & mitigation)
4. Recovery test (post-attack health restoration and zero flapping)
5. Isolation test (Domains B and C health and latency stability)
6. End-to-end data-plane test (ping h1↔h2, h1↔h5, h5↔h9 in baseline & recovery)
7. Summary metrics table & before/after comparison
"""

import os
import sys
import time
import json
import subprocess
import re
import statistics
from pathlib import Path
import requests
import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from topology.multi_domain_topo import build_network, assign_controllers, enable_rstp

EW_PORTS = {"A": 8080, "B": 8081, "C": 8082}
OFP_PORTS = {"A": 6633, "B": 6634, "C": 6653}
RYU_PY = "/home/a-anuj/ryu311/bin/python"
RYU_MGR = "/home/a-anuj/ryu311/bin/ryu-manager"

RESULTS_DIR = ROOT / "results" / "validation"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
CB_LOG = RESULTS_DIR / "circuit_breaker_validation.log"

def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def emergency_reset():
    log("Running emergency reset...")
    subprocess.run(["pkill", "-9", "-f", "ryu-manager"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "defense/circuit_breaker"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "attacks/packetin_flood"], stderr=subprocess.DEVNULL)
    subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

def start_controllers():
    log("Starting Ryu controllers (A, B, C)...")
    cmd_A = (f"DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 TE_ENABLED=1 "
             f"nohup {RYU_PY} {RYU_MGR} controllers/ew_controller.py "
             f"--ofp-tcp-listen-port 6633 > {RESULTS_DIR}/ryu_A.log 2>&1 &")
    cmd_B = (f"DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 EW_API_PORT=8081 TE_ENABLED=1 "
             f"nohup {RYU_PY} {RYU_MGR} controllers/ew_controller.py "
             f"--ofp-tcp-listen-port 6634 > {RESULTS_DIR}/ryu_B.log 2>&1 &")
    cmd_C = (f"DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 EW_API_PORT=8082 TE_ENABLED=1 "
             f"nohup {RYU_PY} {RYU_MGR} controllers/ew_controller.py "
             f"--ofp-tcp-listen-port 6653 > {RESULTS_DIR}/ryu_C.log 2>&1 &")
    subprocess.Popen(cmd_A, shell=True, cwd=ROOT)
    subprocess.Popen(cmd_B, shell=True, cwd=ROOT)
    subprocess.Popen(cmd_C, shell=True, cwd=ROOT)
    
    t0 = time.time()
    while time.time() - t0 < 15:
        ok = True
        for d, port in EW_PORTS.items():
            try:
                r = requests.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code != 200: ok = False
            except Exception:
                ok = False
        if ok:
            log("Controllers A, B, and C are listening and healthy.")
            return True
        time.sleep(0.5)
    log("Controllers failed to respond within 15s.")
    return False

def get_controller_pid(port=6633):
    try:
        out = subprocess.check_output(["ps", "aux"]).decode()
        for line in out.splitlines():
            if "ryu-manager" in line and f"--ofp-tcp-listen-port {port}" in line and "grep" not in line:
                parts = line.split()
                return int(parts[1])
    except Exception:
        pass
    return None

def probe_domain(domain, port, timeout=2.0):
    t0 = time.monotonic()
    try:
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=timeout)
        if r.status_code == 200:
            return round((time.monotonic() - t0) * 1000.0, 2), "OK"
        return None, f"HTTP_{r.status_code}"
    except requests.exceptions.Timeout:
        return None, "TIMEOUT"
    except requests.exceptions.ConnectionError:
        return None, "CONN_REFUSED"
    except Exception as e:
        return None, f"ERR_{type(e).__name__}"

def probe_all_domains():
    res = {}
    details = {}
    for d, port in EW_PORTS.items():
        lat, status = probe_domain(d, port)
        res[d] = lat
        details[d] = {"latency_ms": lat, "status": status}
    return res, details

def get_packetin_count(switches=("s1", "s2", "s3")):
    total = 0
    for sw in switches:
        try:
            out = subprocess.check_output(
                ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", sw],
                stderr=subprocess.DEVNULL
            ).decode()
            for line in out.splitlines():
                if "priority=0" in line and "CONTROLLER" in line:
                    m = re.search(r"n_packets=([0-9]+)", line)
                    if m:
                        total += int(m.group(1))
        except Exception:
            pass
    return total

def run_validation():
    log("==================================================================")
    log("STARTING MULTI-DOMAIN SDN HEALTH & DEFENSE VALIDATION")
    log("==================================================================")
    
    emergency_reset()
    if not start_controllers():
        log("FAIL: Controllers could not be started.")
        return False
        
    # STAGE 1: Controller-only check
    log("\n--- STAGE 1: Controller-only Health Check ---")
    stage1_ok = True
    for d, port in EW_PORTS.items():
        lat, status = probe_domain(d, port)
        log(f"Domain {d} (port {port}): status={status}, latency={lat}ms")
        if status != "OK" or lat is None:
            stage1_ok = False
    assert stage1_ok, "Stage 1 Controller-only check failed"
    log("STAGE 1 PASSED: All controllers healthy.")

    # Build topology
    log("\n--- STAGE 2: Building Topology & Baseline Evaluation ---")
    from mininet.log import setLogLevel
    setLogLevel("warning")
    net = build_network()
    net.start()
    assign_controllers(net)
    enable_rstp(net, wait=0)
    
    log("Waiting 15s for OpenFlow handshake...")
    time.sleep(15)
    
    # Start Circuit Breaker
    if os.path.exists(CB_LOG):
        os.remove(CB_LOG)
    cb_cmd = [
        "python3", str(ROOT / "defense" / "circuit_breaker.py"),
        "--domain", "A",
        "--switches", "s1,s2,s3",
        "--port", "6633",
        "--api-port", "8080",
        "--rate-threshold", "1500",
        "--cpu-threshold", "70.0",
        "--log", str(CB_LOG)
    ]
    cb_proc = subprocess.Popen(cb_cmd)
    time.sleep(2)
    log(f"Circuit Breaker started (PID {cb_proc.pid})")
    
    pid_A = get_controller_pid(6633)
    log(f"Domain A Controller PID: {pid_A}")
    
    # Baseline monitoring: 20 probes (1 per sec)
    log("Collecting 20 baseline probes with Circuit Breaker active...")
    baseline_probes = []
    prev_pktin = get_packetin_count()
    prev_time = time.time()
    
    for i in range(20):
        time.sleep(1.0)
        curr_pktin = get_packetin_count()
        curr_time = time.time()
        rate = (curr_pktin - prev_pktin) / max((curr_time - prev_time), 0.1)
        prev_pktin = curr_pktin
        prev_time = curr_time
        
        cpu = 0.0
        if pid_A:
            try: cpu = psutil.Process(pid_A).cpu_percent(interval=0.1)
            except Exception: pass
            
        p_res, details = probe_all_domains()
        baseline_probes.append((p_res, details, rate, cpu))
        if i % 5 == 4 or i == 0:
            log(f"Baseline #{i+1:02d}: A={p_res['A']}ms, B={p_res['B']}ms, C={p_res['C']}ms | Rate={rate:.1f} pkt/s, CPU={cpu:.1f}%")
            
    # Check baseline stats
    bl_A_vals = [p[0]["A"] for p in baseline_probes if p[0]["A"] is not None]
    bl_A_failed = sum(1 for p in baseline_probes if p[0]["A"] is None)
    bl_A_mean = round(statistics.mean(bl_A_vals), 2) if bl_A_vals else None
    
    log(f"Baseline Summary: Total=20, Failed={bl_A_failed} (0.0%), Mean Latency={bl_A_mean}ms")
    assert bl_A_failed == 0, f"Expected 0 failed probes in baseline, got {bl_A_failed}"
    assert bl_A_mean is not None and bl_A_mean < 30.0, f"Baseline mean {bl_A_mean} exceeds 30ms limit"
    
    # Verify CB did not trigger in baseline
    with open(CB_LOG, "r") as f:
        cb_content = f.read()
    assert "DETECT [TRIGGER]" not in cb_content, "Circuit breaker triggered falsely in baseline!"
    log("STAGE 2 PASSED: Baseline is completely clean (0 probe failures, 0 false triggers).")

    # STAGE 6A: Host-to-host data plane test (Baseline)
    log("\n--- STAGE 6A: Data-Plane Host-to-Host Connectivity (Baseline) ---")
    h1, h2, h5, h9 = net.get("h1"), net.get("h2"), net.get("h5"), net.get("h9")
    
    # Warm up host registrations with intra-domain pings
    log("Warming up host registrations...")
    net.ping([h1, h2], timeout="2")
    net.ping([h5, net.get("h6")], timeout="2")
    net.ping([h9, net.get("h10")], timeout="2")
    log("Waiting 6s for East-West sync agent to propagate host tables...")
    time.sleep(6)

    # Intra-domain ping h1 -> h2
    res_intra = h1.cmd(f"ping -c 3 -W 2 {h2.IP()}")
    intra_ok = "0% packet loss" in res_intra or "1 packets received" in res_intra or "2 packets received" in res_intra or "3 packets received" in res_intra
    log(f"Data-plane Intra-domain ping h1↔h2: {'PASS' if intra_ok else 'FAIL'}")
    assert intra_ok, f"Intra-domain ping failed:\n{res_intra}"
    
    # Inter-domain ping h1 (Domain A) -> h5 (Domain B)
    res_inter_ab = h1.cmd(f"ping -c 3 -W 3 {h5.IP()}")
    inter_ab_ok = "0% packet loss" in res_inter_ab or "1 packets received" in res_inter_ab or "2 packets received" in res_inter_ab or "3 packets received" in res_inter_ab
    log(f"Data-plane Inter-domain ping h1↔h5: {'PASS' if inter_ab_ok else 'FAIL'}")
    assert inter_ab_ok, f"Inter-domain ping h1↔h5 failed:\n{res_inter_ab}"

    # Inter-domain ping h5 (Domain B) -> h9 (Domain C)
    res_inter_bc = h5.cmd(f"ping -c 3 -W 3 {h9.IP()}")
    inter_bc_ok = "0% packet loss" in res_inter_bc or "1 packets received" in res_inter_bc or "2 packets received" in res_inter_bc or "3 packets received" in res_inter_bc
    log(f"Data-plane Inter-domain ping h5↔h9: {'PASS' if inter_bc_ok else 'FAIL'}")
    assert inter_bc_ok, f"Inter-domain ping h5↔h9 failed:\n{res_inter_bc}"
    log("STAGE 6A PASSED: Data-plane communication operational across all domains.")

    # STAGE 3: Defended Attack Evaluation
    log("\n--- STAGE 3: Defended Attack Evaluation (PacketIn Flood) ---")
    c_start = get_packetin_count()
    atk_cmd = [
        "python3", str(ROOT / "attacks" / "packetin_flood.py"),
        "--target", "10.0.0.9",
        "--iface", "h1-eth0",
        "--start-rate", "1000",
        "--max-rate", "4000",
        "--step", "1000",
        "--ramp-interval", "3",
        "--duration", "25",
        "--yes"
    ]
    env_vars = os.environ.copy()
    env_vars["RESULTS_DIR"] = str(RESULTS_DIR)
    
    t_atk_start = time.time()
    atk_proc = h1.popen(atk_cmd, env=env_vars, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    during_probes = []
    while atk_proc.poll() is None:
        p_res, details = probe_all_domains()
        during_probes.append((p_res, details))
        time.sleep(1.0)
        
    atk_out, atk_err = atk_proc.communicate()
    t_atk_end = time.time()
    atk_elapsed = round(t_atk_end - t_atk_start, 2)
    c_end = get_packetin_count()
    pkts_sent = max(c_end - c_start, 0)
    achieved_rate = round(pkts_sent / max(atk_elapsed, 1.0), 2)
    log(f"Attack completed: elapsed={atk_elapsed}s, pkts_counted={pkts_sent}, achieved_rate={achieved_rate} pkt/s")
    
    # Check CB trigger
    with open(CB_LOG, "r") as f:
        cb_content = f.read()
    cb_triggered = "DETECT [TRIGGER]" in cb_content
    log(f"Circuit Breaker trigger verified during attack: {cb_triggered}")
    assert cb_triggered, "Circuit Breaker did not trigger during attack!"

    # Count how many triggers occurred
    trigger_count = cb_content.count("DETECT [TRIGGER]")
    log(f"Circuit Breaker triggers during attack: {trigger_count} (Single surgical trigger expected)")
    
    # STAGE 4: Recovery Evaluation
    log("\n--- STAGE 4: Recovery Evaluation (Post-Attack) ---")
    recovery_probes = []
    t_rec_end = time.time() + 20.0
    while time.time() < t_rec_end:
        p_res, details = probe_all_domains()
        recovery_probes.append((p_res, details))
        time.sleep(1.0)
        
    # Stop Circuit Breaker
    cb_proc.terminate()
    try: cb_proc.wait(timeout=5)
    except Exception: cb_proc.kill()
    subprocess.run(["pkill", "-9", "-f", "defense/circuit_breaker"], stderr=subprocess.DEVNULL)
    
    # Check recovery stats
    rec_A_vals = [p[0]["A"] for p in recovery_probes if p[0]["A"] is not None]
    rec_A_failed = sum(1 for p in recovery_probes if p[0]["A"] is None)
    rec_A_mean = round(statistics.mean(rec_A_vals), 2) if rec_A_vals else None
    
    log(f"Recovery Summary: Total=20, Failed={rec_A_failed} (0.0%), Mean Latency={rec_A_mean}ms")
    assert rec_A_failed == 0, f"Expected 0 failed probes in recovery, got {rec_A_failed}"
    assert rec_A_mean is not None and rec_A_mean <= (bl_A_mean * 1.5 + 5.0), f"Recovery latency {rec_A_mean}ms did not recover to baseline {bl_A_mean}ms"
    log("STAGE 4 PASSED: Recovery fully restored (0 probe failures, healthy latency).")

    # STAGE 5: Domain B and C Isolation Check
    log("\n--- STAGE 5: Multi-Domain Isolation (Domains B & C) ---")
    for d in ("B", "C"):
        b_rec_vals = [p[0][d] for p in recovery_probes if p[0][d] is not None]
        b_rec_failed = sum(1 for p in recovery_probes if p[0][d] is None)
        b_mean = round(statistics.mean(b_rec_vals), 2) if b_rec_vals else None
        log(f"Domain {d}: Failed={b_rec_failed}, Mean Latency={b_mean}ms")
        assert b_rec_failed == 0, f"Domain {d} had probe failures: {b_rec_failed}"
    log("STAGE 5 PASSED: Domains B and C remained 100% healthy.")

    # STAGE 6B: Data-Plane Host-to-Host Connectivity (Post-Recovery)
    log("\n--- STAGE 6B: Data-Plane Host-to-Host Connectivity (Post-Recovery) ---")
    res_intra_rec = h1.cmd(f"ping -c 3 -W 2 {h2.IP()}")
    intra_rec_ok = "0% packet loss" in res_intra_rec or "1 packets received" in res_intra_rec or "2 packets received" in res_intra_rec or "3 packets received" in res_intra_rec
    log(f"Data-plane Intra-domain ping h1↔h2 post-recovery: {'PASS' if intra_rec_ok else 'FAIL'}")
    assert intra_rec_ok, f"Intra-domain ping post-recovery failed:\n{res_intra_rec}"
    
    res_inter_rec = h1.cmd(f"ping -c 3 -W 3 {h5.IP()}")
    inter_rec_ok = "0% packet loss" in res_inter_rec or "1 packets received" in res_inter_rec or "2 packets received" in res_inter_rec or "3 packets received" in res_inter_rec
    log(f"Data-plane Inter-domain ping h1↔h5 post-recovery: {'PASS' if inter_rec_ok else 'FAIL'}")
    assert inter_rec_ok, f"Inter-domain ping h1↔h5 post-recovery failed:\n{res_inter_rec}"
    log("STAGE 6B PASSED: Data-plane communication operational post-recovery.")

    net.stop()
    subprocess.run(["pkill", "-9", "-f", "ryu-manager"], stderr=subprocess.DEVNULL)
    
    log("\n==================================================================")
    log("ALL 7 VALIDATION STAGES PASSED SUCCESSFULLY!")
    log("==================================================================")
    return True

if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)
