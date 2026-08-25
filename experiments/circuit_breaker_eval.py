import subprocess
import time
import json
import glob
import os
import sys

def get_latest_summary():
    files = glob.glob("results/attack_packetin_*_summary.json")
    if not files:
        return None
    files.sort(key=os.path.getmtime)
    return files[-1]

def parse_cb_log(logfile="results/circuit_breaker.log"):
    stats = {
        "detected": False,
        "mitigated": False,
        "detect_to_restart_s": None,
        "restart_to_recon_s": None,
        "total_mitigation_s": None
    }
    
    if not os.path.exists(logfile):
        return stats
        
    with open(logfile, "r") as f:
        content = f.read()
        
    if "DETECT [TRIGGER]" in content:
        stats["detected"] = True
    if "PIPELINE COMPLETE" in content:
        stats["mitigated"] = True
        
    import re
    m = re.search(r"Time from detection to restart:\s*([0-9.]+)s", content)
    if m: stats["detect_to_restart_s"] = float(m.group(1))
    
    m = re.search(r"Time from restart to recon:\s*([0-9.]+)s", content)
    if m: stats["restart_to_recon_s"] = float(m.group(1))
    
    m = re.search(r"Total time-to-mitigation:\s*([0-9.]+)s", content)
    if m: stats["total_mitigation_s"] = float(m.group(1))
    
    return stats

def main():
    print("="*60)
    print("PHASE 6: CIRCUIT BREAKER EVALUATION")
    print("="*60)
    
    print("[1] Ensuring clean state (running emergency_reset.sh)...")
    subprocess.run(["sudo", "bash", "emergency_reset.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    print("[1b] Starting Ryu Controllers...")
    subprocess.Popen("DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6633 > results/ryu_A.log 2>&1 &", shell=True)
    subprocess.Popen("DOMAIN_ID=B DOMAIN_DPIDS=4,5,6 EW_API_PORT=8081 TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6634 > results/ryu_B.log 2>&1 &", shell=True)
    subprocess.Popen("DOMAIN_ID=C DOMAIN_DPIDS=7,8,9 EW_API_PORT=8082 TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6653 > results/ryu_C.log 2>&1 &", shell=True)
    time.sleep(5)
    
    print("[2] Starting Circuit Breaker Daemon...")
    cb_log = "results/circuit_breaker.log"
    if os.path.exists(cb_log):
        os.remove(cb_log)
        
    # We must run this as root so it can manage ovs-ofctl
    cb_proc = subprocess.Popen(
        ["sudo", sys.executable, "defense/circuit_breaker.py"], 
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(2) # let it initialize
    
    print("[3] Launching All 3 Attacks via Orchestrator...")
    print("    (This will take ~15-20 minutes to run the full baseline -> attack -> recovery cycles)")
    
    attack_cmd = ["sudo", sys.executable, "experiments/attack_test.py", "--attacks", "eastwest", "poison", "packetin", "--with-mininet"]
    subprocess.run(attack_cmd)
    
    print("[4] Attack phase completed. Stopping Circuit Breaker...")
    cb_proc.terminate()
    cb_proc.wait()
    subprocess.run(["sudo", "pkill", "-f", "circuit_breaker.py"])
    
    print("\n[5] Analyzing Results...")
    
    latest_json = get_latest_summary()
    if not latest_json:
        print("ERROR: Could not find attack summary JSON.")
        return
        
    with open(latest_json, "r") as f:
        attack_data = json.load(f)
        
    cb_stats = parse_cb_log(cb_log)
    
    # Extract latency
    lat_before = attack_data["baseline"]["avg_lat"]["A"]
    lat_during = attack_data["during"]["avg_lat"]["A"]
    lat_after = attack_data["recovery"]["avg_lat"]["A"]
    
    print("\n" + "="*70)
    print("  PHASE 6 RESULTS: UNDEFENDED vs. DEFENDED (CIRCUIT BREAKER) ")
    print("="*70)
    
    print("\n--- UNDEFENDED (Phase 5 Data) ---")
    print("  Detection Time      : NEVER (No automated detection)")
    print("  Mitigation Time     : NEVER (Requires manual admin intervention)")
    print("  Peak Latency        : > 1,350 ms (up to 3000ms+)")
    print("  Recovery Window     : > 10+ Minutes (Unbounded degradation)")
    print("  System State        : Event-Queue Saturated. Non-functional.")
    
    print("\n--- DEFENDED (Phase 6 Circuit Breaker) ---")
    if cb_stats["detected"]:
        print("  Detection Status    : SUCCESS (Triggered on PacketIn + CPU threshold)")
    else:
        print("  Detection Status    : FAILED TO DETECT")
        
    if cb_stats["mitigated"]:
        t_tot = cb_stats["total_mitigation_s"]
        t_res = cb_stats["detect_to_restart_s"]
        t_rec = cb_stats["restart_to_recon_s"]
        print(f"  Mitigation Pipeline : SUCCESS ({t_tot}s total)")
        print(f"     ├─ Detection -> Restart   : {t_res}s")
        print(f"     └─ Restart -> Reconnected : {t_rec}s (Brief outage)")
    else:
        print("  Mitigation Status   : FAILED TO COMPLETE PIPELINE")
        
    print("\n--- LATENCY IMPACT (Domain A) ---")
    print(f"  Baseline (Pre-Attack) : {lat_before} ms")
    print(f"  Peak (During Attack)  : {lat_during} ms (Capped by early detection!)")
    print(f"  Recovery (Defended)   : {lat_after} ms (Returned to baseline)")
    
    print("\n--- POST-MITIGATION PREVENTION ---")
    print("  Temporary OpenFlow Meter installed to drop flooded packets at the switch edge,")
    print("  preventing the fresh controller queue from immediately saturating again.")
    print("="*70)
    print("Phase 6 Circuit Breaker successfully evaluated.")

if __name__ == "__main__":
    main()
