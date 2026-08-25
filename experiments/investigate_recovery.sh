#!/bin/bash
PID=$(ps aux | grep ew_controller | grep 6633 | awk '{print $2}' | head -n 1)
if [ -z "$PID" ]; then
    echo "Could not find Domain A controller PID"
    exit 1
fi
echo "Monitoring PID $PID for 15 minutes (900 seconds)"

mkdir -p results
LOG="results/recovery_investigation.log"
echo "Starting monitoring at $(date)" > $LOG

for i in {1..180}; do
    echo "=== $(date) ===" >> $LOG
    echo "--- CPU/MEM ---" >> $LOG
    ps -p $PID -o %cpu,%mem,cmd | tail -n 1 >> $LOG
    echo "--- FD COUNT ---" >> $LOG
    sudo lsof -w -p $PID 2>/dev/null | wc -l >> $LOG
    echo "--- LOAD AVERAGE ---" >> $LOG
    uptime >> $LOG
    echo "--- OVS DATAPATH (s1,s2,s3) flows ---" >> $LOG
    for sw in s1 s2 s3; do
        count=$(sudo ovs-ofctl dump-flows $sw 2>/dev/null | wc -l)
        echo "$sw: $count" >> $LOG
    done
    sleep 5
done
echo "Monitoring completed" >> $LOG
