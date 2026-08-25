#!/bin/bash
echo "Stopping existing Ryu controllers..."
pkill -9 -f ryu-manager
sleep 2

echo "Starting Domain A (6633)..."
/home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6633 > results/ryu_A.log 2>&1 &

echo "Starting Domain B (6634)..."
/home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6634 > results/ryu_B.log 2>&1 &

echo "Starting Domain C (6653)..."
/home/a-anuj/ryu311/bin/python /home/a-anuj/ryu311/bin/ryu-manager controllers/ew_controller.py --ofp-tcp-listen-port 6653 > results/ryu_C.log 2>&1 &

echo "Waiting for controllers to initialize..."
sleep 5

echo "Running full attack suite (PacketIn is now ordered last)..."
python3 experiments/attack_test.py --with-mininet

echo "Done."
