#!/usr/bin/env python3
"""Minimal scapy smoke test — must be run as root (for raw socket).

Usage:
    sudo python3 smoke_test_scapy.py

Confirms that:
  1. scapy imports succeed (including the exact symbols used by packetin_flood.py)
  2. Packet construction works
  3. sendp() can transmit at least 5 packets on the loopback interface
     without raising an exception
"""
import sys
import os

sys.path.insert(0, "/home/a-anuj/.local/lib/python3.14/site-packages")

if os.geteuid() != 0:
    print("[ERROR] Run with sudo — raw sockets require root.", file=sys.stderr)
    sys.exit(1)

print("1. Importing scapy symbols...")
from scapy.all import Ether, IP, UDP, Raw, sendp  # noqa: E402
print("   OK — Ether, IP, UDP, Raw, sendp all imported successfully")

print("2. Building a test packet...")
pkt = (
    Ether(src="aa:bb:cc:dd:ee:ff", dst="ff:ff:ff:ff:ff:ff")
    / IP(src="10.0.0.1", dst="10.0.0.9", ttl=64)
    / UDP(sport=12345, dport=9)
    / Raw(load=b"SMOKE_TEST")
)
print(f"   OK — {pkt.summary()}")

print("3. Sending 5 packets via sendp() on 'lo'...")
errors = 0
for i in range(5):
    try:
        sendp(pkt, iface="lo", verbose=False)
        print(f"   Packet {i+1} sent OK")
    except Exception as exc:
        print(f"   [ERROR] Packet {i+1} failed: {exc}")
        errors += 1

if errors == 0:
    print("\n[PASS] All 5 packets sent successfully. scapy sendp is working correctly.")
    sys.exit(0)
else:
    print(f"\n[FAIL] {errors}/5 packets failed to send.")
    sys.exit(1)
