#!/bin/bash
PID=$(ps aux | grep ew_controller | grep 6633 | grep -v grep | awk '{print $2}' | head -n 1)
if [ -z "$PID" ]; then
    echo "Could not find Domain A controller PID"
    exit 1
fi
echo "Monitoring PID $PID for 8 minutes (480 seconds)"

mkdir -p results
LOG="results/part1_diagnostic.csv"
echo "Timestamp,CPU%,RSS_KB,Threads,FDs,s1_flows,s3_flows,LoadAvg1m,FreeMemMB" | tee $LOG

# 8 minutes = 60s baseline + 120s attack + 300s recovery = 480s / 5s = 96 iterations
for i in {1..96}; do
    TS=$(date +"%H:%M:%S")
    
    # CPU and RSS
    read -r cpu rss <<< $(ps -p $PID -o %cpu,rss | tail -n 1)
    
    # Threads
    threads=$(ls /proc/$PID/task 2>/dev/null | wc -l)
    
    # FDs
    fds=$(sudo lsof -w -p $PID 2>/dev/null | wc -l)
    
    # Flow counts
    s1_flows=$(sudo ovs-ofctl -O OpenFlow13 dump-flows s1 2>/dev/null | wc -l)
    s3_flows=$(sudo ovs-ofctl -O OpenFlow13 dump-flows s3 2>/dev/null | wc -l)
    
    # Load and Free Mem
    load=$(uptime | awk -F'load average:' '{ print $2 }' | cut -d, -f1 | xargs)
    freemem=$(free -m | awk '/^Mem:/{print $7}') # Available memory
    
    line="$TS,$cpu,$rss,$threads,$fds,$s1_flows,$s3_flows,$load,$freemem"
    echo "$line" | tee -a $LOG
    sleep 5
done
echo "Monitoring completed. Results saved to $LOG"
