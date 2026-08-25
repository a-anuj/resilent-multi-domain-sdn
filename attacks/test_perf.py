import time
from scapy.all import Ether, IP, UDP, Raw, sendp, sendpfast
import sys

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
    return pkt

def test_build():
    start = time.time()
    for _ in range(5000):
        _build_packet("10.0.0.9")
    elapsed = time.time() - start
    print(f"Build only: 5000 pkts in {elapsed:.3f}s ({5000/elapsed:.1f} pkt/s)")

def test_sendp():
    import socket
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind(('lo', 0))
    start = time.time()
    for _ in range(500):
        pkt = _build_packet("10.0.0.9")
        s.send(bytes(pkt))
    elapsed = time.time() - start
    print(f"socket.send(bytes(pkt)): 500 pkts in {elapsed:.3f}s ({500/elapsed:.1f} pkt/s)")

test_build()
test_sendp()
