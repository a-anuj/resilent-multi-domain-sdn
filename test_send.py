import socket
try:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind(('lo', 0))
    s.send(b'\xff'*14 + b'test')
    print("Sent with proto=0")
except Exception as e:
    print("Error with proto=0:", e)
