import argparse
import time
import subprocess
import re
import psutil
import requests
import os
import sys

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
    
    if pid:
        log(f"MITIGATE: Killing affected controller PID {pid}")
        try:
            os.kill(pid, 9)
        except Exception as e:
            log(f"Failed to kill: {e}")
    
    time.sleep(1)
    
    # Restart controller using identical environment vars from testbed
    domain_dpids = args.switches.replace('s', '')
    cmd = f"DOMAIN_ID={args.domain} DOMAIN_DPIDS={domain_dpids} EW_API_PORT={args.api_port} TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port {args.port} > results/cb_restart.log 2>&1 &"
    subprocess.Popen(cmd, shell=True)
    
    t_restart = time.time()
    log(f"MITIGATE: Restart initiated. Time from detection to restart: {t_restart - t_detect:.2f}s")
    
    # Wait for switch reconnection
    log("MITIGATE: Waiting for controller to reconnect and API to come up...")
    connected = False
    while time.time() - t_restart < 15:
        try:
            r = requests.get(f"http://127.0.0.1:{args.api_port}/stats/switches", timeout=1)
            if r.status_code == 200:
                connected = True
                break
        except Exception:
            pass
        time.sleep(0.5)
        
    t_reconnect = time.time()
    if connected:
        log(f"MITIGATE: Reconnection confirmed! Time from restart to recon: {t_reconnect - t_restart:.2f}s")
    else:
        log(f"MITIGATE: Reconnection NOT confirmed after 15s (API unresponsive)")

    # Post-restart Prevent Stage
    log("PREVENT: Installing OpenFlow rate-limit meter on edge switch...")
    meter_cmd = ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-meter", switches[0], "meter=1,pktps,band=type=drop,rate=100"]
    ret = subprocess.run(meter_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    
    if ret.returncode != 0 and b"OFPMMFC_OUT_OF_METERS" in ret.stderr:
        log("PREVENT: Meter not supported by datapath. Falling back to targeted port drop.")
        # Fallback: drop PacketIn triggers from host 1 temporarily (60s)
        subprocess.run(["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-flow", switches[0], "priority=1,in_port=1,hard_timeout=60,actions=drop"], stderr=subprocess.DEVNULL)
    else:
        flow_cmd = ["sudo", "ovs-ofctl", "-O", "OpenFlow13", "add-flow", switches[0], "priority=1,hard_timeout=60,actions=meter:1,CONTROLLER:65535"]
        subprocess.run(flow_cmd, stderr=subprocess.DEVNULL)
        
    log("PREVENT: Rule installed. Expires in 60s.")
    log(f"PIPELINE COMPLETE: Total time-to-mitigation: {time.time() - t_detect:.2f}s")
    
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
