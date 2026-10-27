import argparse
import time
import subprocess
import re
import psutil
import requests
import os
import sys
import json

def get_packetin_count(switches):
    total = 0
    for sw in switches:
        try:
            out = subprocess.check_output(
                ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "dump-flows", sw],
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

def mitigate(args, pid, trigger_rate, trigger_cpu, log, switches):
    t_detect = time.time()
    log(f"TIMING: t_detect={t_detect:.4f}")
    
    t_kill = None
    if pid:
        log(f"MITIGATE: Killing affected controller PID {pid}")
        try:
            os.kill(pid, 9)
            t_kill = time.time()
        except Exception as e:
            log(f"Failed to kill: {e}")
            t_kill = time.time()
    else:
        t_kill = time.time()
    log(f"TIMING: t_kill={t_kill:.4f} (elapsed={t_kill - t_detect:.3f}s)")
    
    time.sleep(1)
    
    # Restart controller using identical environment vars from testbed
    domain_dpids = args.switches.replace('s', '')
    cb_restart_log = os.path.join(os.path.dirname(args.log) or '.', "cb_restart.log")
    cmd = (f"DOMAIN_ID={args.domain} DOMAIN_DPIDS={domain_dpids} EW_API_PORT={args.api_port} "
           f"TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager "
           f"controllers/ew_controller.py --ofp-tcp-listen-port {args.port} > {cb_restart_log} 2>&1 &")
    subprocess.Popen(cmd, shell=True)
    
    t_restart = time.time()
    log(f"MITIGATE: Restart initiated. Time from detection to restart: {t_restart - t_detect:.2f}s")
    
    # Wait for switch reconnection - poll /health or /topology, exit on first HTTP 200
    log("MITIGATE: Waiting for controller to reconnect and API to come up...")
    connected = False
    t_reconnect_confirmed = None
    while time.time() - t_restart < 15:
        try:
            r = requests.get(f"http://127.0.0.1:{args.api_port}/health", timeout=1)
            if r.status_code == 200:
                connected = True
                t_reconnect_confirmed = time.time()
                break
        except Exception:
            try:
                r2 = requests.get(f"http://127.0.0.1:{args.api_port}/topology", timeout=1)
                if r2.status_code == 200:
                    connected = True
                    t_reconnect_confirmed = time.time()
                    break
            except Exception:
                pass
        time.sleep(0.2)
        
    if not connected:
        t_reconnect_confirmed = time.time()
        log(f"MITIGATE: Reconnection NOT confirmed after 15s (API unresponsive)")
    else:
        log(f"MITIGATE: Reconnection confirmed! Time from restart to recon: {t_reconnect_confirmed - t_restart:.2f}s")
    log(f"TIMING: t_reconnect_confirmed={t_reconnect_confirmed:.4f} (elapsed={t_reconnect_confirmed - t_detect:.3f}s)")

    # Post-restart Prevent Stage
    log("PREVENT: Installing OpenFlow rate-limit meter on edge switch...")
    meter_cmd = ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-meter", switches[0], "meter=1,pktps,band=type=drop,rate=100"]
    ret = subprocess.run(meter_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    
    if ret.returncode != 0:
        log("PREVENT: Meter not supported by datapath. Falling back to targeted port drop.")
        # Fallback: drop PacketIn triggers from host 1 temporarily (60s) (h1 is on s1 port 3)
        subprocess.run(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-flow", switches[0], "priority=1,in_port=3,idle_timeout=30,actions=drop"], stderr=subprocess.DEVNULL)
    else:
        flow_cmd = ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-flow", switches[0], "priority=1,idle_timeout=30,actions=meter:1,CONTROLLER:65535"]
        subprocess.run(flow_cmd, stderr=subprocess.DEVNULL)
        
    t_meter_installed = time.time()
    log(f"TIMING: t_meter_installed={t_meter_installed:.4f} (elapsed={t_meter_installed - t_detect:.3f}s)")
    log("PREVENT: Rule installed with idle_timeout=30s (persists while attack active, clears 30s after idle).")
    log(f"PIPELINE COMPLETE: Total time-to-mitigation: {time.time() - t_detect:.2f}s")
    
    timings_file = os.path.join(os.path.dirname(args.log) or '.', "circuit_breaker_timings.json")
    try:
        events = []
        if os.path.exists(timings_file):
            with open(timings_file, "r") as f:
                events = json.load(f)
        events.append({
            "t_detect": t_detect,
            "t_kill": t_kill,
            "t_restart": t_restart,
            "t_reconnect_confirmed": t_reconnect_confirmed,
            "t_meter_installed": t_meter_installed,
            "connected": connected,
            "dt_detect_to_kill_s": round(t_kill - t_detect, 3),
            "dt_kill_to_restart_s": round(t_restart - t_kill, 3),
            "dt_restart_to_recon_s": round(t_reconnect_confirmed - t_restart, 3),
            "dt_recon_to_meter_s": round(t_meter_installed - t_reconnect_confirmed, 3),
            "total_ttm_s": round(t_meter_installed - t_detect, 3),
        })
        with open(timings_file, "w") as f:
            json.dump(events, f, indent=2)
    except Exception as e:
        log(f"Failed to record timings json: {e}")

    # Sleep to allow the attack to finish or system to stabilize before re-detecting
    time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description="Phase 6 Automated Circuit Breaker")
    parser.add_argument("--domain", default="A")
    parser.add_argument("--switches", default="s1,s2,s3")
    parser.add_argument("--port", type=int, default=6633)
    parser.add_argument("--api-port", type=int, default=8080)
    parser.add_argument("--rate-threshold", type=int, default=1500, help="PacketIn per second threshold")
    parser.add_argument("--cpu-threshold", type=float, default=70.0, help="Sustained CPU percent threshold")
    parser.add_argument("--log", default="results/circuit_breaker.log")
    args = parser.parse_args()

    switches = args.switches.split(",")
    os.makedirs(os.path.dirname(args.log) or '.', exist_ok=True)
    
    with open(args.log, "w") as f:
        f.write("Circuit Breaker Started\n")

    def log(msg):
        t = time.strftime("%H:%M:%S")
        s = f"[{t}] {msg}"
        print(s)
        with open(args.log, "a") as f:
            f.write(s + "\n")

    log(f"Monitoring Domain {args.domain} (Switches: {switches})")
    log(f"Thresholds -> PacketIn: >{args.rate_threshold} pkt/s | CPU: >{args.cpu_threshold}%")
    
    prev_count = get_packetin_count(switches)
    prev_time = time.time()
    violation_count = 0
    
    try:
        while True:
            time.sleep(1.0)
            curr_count = get_packetin_count(switches)
            curr_time = time.time()
            
            rate = (curr_count - prev_count) / max((curr_time - prev_time), 0.1)
            prev_count = curr_count
            prev_time = curr_time
            
            if rate > args.rate_threshold:
                pid = get_controller_pid(args.port)
                cpu = 0.0
                if pid:
                    try:
                        p = psutil.Process(pid)
                        # We use 0.1 interval to get instantaneous CPU in this poll cycle
                        cpu = p.cpu_percent(interval=0.1)
                    except Exception:
                        pass
                
                if cpu > args.cpu_threshold:
                    violation_count += 1
                    log(f"DETECT [WARNING]: PacketIn Rate={rate:.1f} pkt/s | CPU={cpu:.1f}% (Violation {violation_count}/3)")
                    
                    if violation_count >= 3:
                        log(f"DETECT [TRIGGER]: Thresholds exceeded for 3 consecutive seconds.")
                        mitigate(args, pid, rate, cpu, log, switches)
                        violation_count = 0
                        # Reset tracking after mitigation
                        prev_count = get_packetin_count(switches)
                        prev_time = time.time()
                else:
                    violation_count = 0
            else:
                violation_count = 0
                
    except KeyboardInterrupt:
        log("Circuit Breaker stopped.")

if __name__ == "__main__":
    main()
