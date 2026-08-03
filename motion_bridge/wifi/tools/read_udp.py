#!/usr/bin/env python3
"""
read_udp.py — UDP diagnostic reader (outside Blender).

Listens on a UDP port and dumps the frames sent by the WT901WIFI over N
seconds. It is the read_serial.py equivalent for the WiFi sensor: use it to
VERIFY the real CSV format (field order, column count, terminator) BEFORE
feeding it into Blender.

No pyserial or external dependencies needed: standard library only.

Usage:
    python3 tools/read_udp.py [PORT] [SECONDS] [HOST]

Defaults: port 1399, 8 s, host 0.0.0.0 (all interfaces).

What to look for in the output:
    - Does each line start with the DeviceID (something like 'WT53...')?
    - How many comma-separated fields are there? (expected: >=10)
    - Which positions hold the X,Y,Z angles? (default indices 7,8,9)
  If the order doesn't match what's expected, adjust the IDX_* in
  blender/config.env — no need to touch the bridge code.
"""
import sys
import socket
import time

port = int(sys.argv[1]) if len(sys.argv) > 1 else 1399
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
host = sys.argv[3] if len(sys.argv) > 3 else "0.0.0.0"

print(f"[read_udp] Listening on UDP {host}:{port} for {secs}s...", flush=True)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((host, port))
sock.settimeout(0.5)

t_end = time.time() + secs
count = 0
while time.time() < t_end:
    try:
        data, addr = sock.recvfrom(2048)
    except socket.timeout:
        continue
    text = data.decode("utf-8", errors="ignore").strip()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        count += 1
        n_fields = len(line.split(","))
        # Show source, field count and the raw line (useful for debugging).
        print(f"[{addr[0]}] fields={n_fields:2d} | {line}", flush=True)

sock.close()
print(f"[read_udp] Done. {count} lines received.", flush=True)
