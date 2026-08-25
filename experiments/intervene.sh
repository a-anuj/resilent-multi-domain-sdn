#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: $0 [flush|restart|both]"
    exit 1
fi

echo "--- Executing intervention: $1 ---"

if [ "$1" == "flush" ] || [ "$1" == "both" ]; then
    echo "Flushing flow tables on s1 and s3..."
    sudo ovs-ofctl -O OpenFlow13 del-flows s1
    sudo ovs-ofctl -O OpenFlow13 del-flows s3
    echo "Done."
fi

if [ "$1" == "restart" ] || [ "$1" == "both" ]; then
    echo "Restarting Domain A controller (port 6633)..."
    PID=$(ps aux | grep ew_controller | grep 6633 | grep -v grep | awk '{print $2}' | head -n 1)
    if [ ! -z "$PID" ]; then
        echo "Killing PID $PID..."
        kill -9 $PID
        sleep 2
    else
        echo "Could not find running Domain A controller!"
    fi
    echo "Starting new instance..."
    DOMAIN_ID=A DOMAIN_DPIDS=1,2,3 EW_API_PORT=8080 TE_ENABLED=1 nohup /home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6633 > results/ryu_A_restart.log 2>&1 &
    echo "Controller restarted (new PID: $!). See results/ryu_A_restart.log for output."
fi

echo "--- Intervention $1 complete ---"
