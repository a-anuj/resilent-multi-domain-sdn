import time
from scapy.all import Ether, IP, UDP, Raw, sendp, sendpfast
import sys
import threading

def _random_ip_in_subnet():
    import random
    return f"10.0.0.{random.randint(1, 254)}"

def _random_mac():
    import random
    mac = [ 0x02, 0x00, 0x00, random.randint(0x00, 0x7f), random.randint(0x00, 0xff), random.randint(0x00, 0xff) ]
    return ":".join(f"{b:02x}" for b in mac)

def _build_packet(dst_ip):
    src_mac = _random_mac()
    src_ip  = _random_ip_in_subnet()
    pkt = (
        Ether(src=src_mac, dst="ff:ff:ff:ff:ff:ff")
        / IP(src=src_ip, dst=dst_ip, ttl=64)
        / UDP(sport=12345, dport=9)
        / Raw(load=b"FLOOD")
    )
    return bytes(pkt)

def test_send_raw_socket():
    import socket
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind(('lo', 0))
    
    # Pre-build a pool of packets to avoid build overhead
    pkts = [_build_packet("10.0.0.9") for _ in range(1000)]
    
    start = time.time()
    count = 0
    while time.time() - start < 1.0:
        for p in pkts:
            s.send(p)
            count += 1
    
    elapsed = time.time() - start
    print(f"Prebuilt Raw Socket: {count} pkts in {elapsed:.3f}s ({count/elapsed:.1f} pkt/s)")

test_send_raw_socket()
