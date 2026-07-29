#!/usr/bin/env python3
"""
fake_sensor.py — Fake UDP emitter that mimics the WitMotion WT901WIFI.

Used to VALIDATE the bridge's parsing and calibration WITHOUT the real
sensor on the network (see "Testing without hardware" in ../CLAUDE.md).
It generates CSV frames with the same layout as the sensor and sends them
over UDP to the port where the bridge listens, with the angles animated
(oscillating) so the Blender object moves visibly.

No external dependencies: standard library only.

FRAME FORMAT (same one config.env expects, 0-based index):
    0=DeviceID  1..3=Acc(x,y,z)  4..6=Gyro(x,y,z)  7..9=Angle(x,y,z)
    10..12=Mag(x,y,z)      -> 13 fields, terminated by \\r\\n
If the order differs in your real firmware, adjust it in config.env
(IDX_*), not here: this emitter reproduces the documented DEFAULT layout.

Usage:
    python3 tools/fake_sensor.py [PORT] [SECONDS] [HZ] [HOST] [DEVICES]

Defaults:
    PORT    -> LISTEN_PORT from blender/config.env (if found), else 1399
    SECONDS -> 0 = indefinite (until Ctrl+C)
    HZ      -> 50 datagrams/second
    HOST    -> 127.0.0.1 (localhost; the bridge listens on 0.0.0.0)
    DEVICES -> WT9AXTEST (one). Several: comma-separate for multi-sensor,
               e.g.  WT53abc,WT53def  -> each moves its own object per
               DEVICE_MAP. Each device is animated with a different phase
               so they can be told apart.

Examples:
    # One test sensor to the default port, indefinitely:
    python3 tools/fake_sensor.py
    # Two sensors at 100 Hz for 20 s (multi-sensor test):
    python3 tools/fake_sensor.py 1399 20 100 127.0.0.1 WT53abc,WT53def
"""
import sys
import os
import socket
import time
from math import sin, radians, degrees


def _port_from_config(default=1399):
    """Read LISTEN_PORT from blender/config.env so the port stays in sync
    between the emitter and the bridge. If not found, use the default."""
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = os.path.join(here, "..", "blender", "config.env")
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("LISTEN_PORT="):
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return default


port = int(sys.argv[1]) if len(sys.argv) > 1 else _port_from_config()
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0   # 0 = indefinite
hz = float(sys.argv[3]) if len(sys.argv) > 3 else 50.0
host = sys.argv[4] if len(sys.argv) > 4 else "127.0.0.1"
devices = sys.argv[5].split(",") if len(sys.argv) > 5 else ["WT9AXTEST"]
devices = [d.strip() for d in devices if d.strip()]

period = 1.0 / hz if hz > 0 else 0.02

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

mode = f"{secs:.0f}s" if secs > 0 else "indefinite (Ctrl+C to stop)"
print(f"[fake_sensor] Sending to {host}:{port} @ {hz:.0f} Hz, {mode}", flush=True)
print(f"[fake_sensor] Devices: {', '.join(devices)}", flush=True)


def _frame(device_id, t, phase):
    """Build a CSV frame mimicking the WT901WIFI for time t.

    The angles oscillate on each axis (different amplitudes so roll, pitch
    and yaw are easy to tell apart in Blender). Accel/Gyro/Mag are filled
    with plausible values: the bridge doesn't use them (it only reads
    Angle), but they keep the field count and the look of a real frame."""
    roll = 30.0 * sin(0.8 * t + phase)          # X axis
    pitch = 20.0 * sin(1.3 * t + phase + 1.0)   # Y axis
    yaw = 45.0 * sin(0.5 * t + phase + 2.0)     # Z axis

    # Accel: ~1g distributed by the tilt (rough approximation).
    ax = sin(radians(pitch))
    ay = -sin(radians(roll))
    az = 1.0
    # Gyro: rough derivative of the angles (deg/s), purely cosmetic.
    gx, gy, gz = 0.0, 0.0, 0.0
    # Mag: fixed plausible values.
    mx, my, mz = 0.30, -0.10, 0.45

    fields = [
        device_id,
        f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
        f"{gx:.2f}", f"{gy:.2f}", f"{gz:.2f}",
        f"{roll:.2f}", f"{pitch:.2f}", f"{yaw:.2f}",
        f"{mx:.3f}", f"{my:.3f}", f"{mz:.3f}",
    ]
    return ",".join(fields) + "\r\n"


t0 = time.time()
n = 0
try:
    while True:
        now = time.time()
        t = now - t0
        if secs > 0 and t >= secs:
            break
        for i, dev in enumerate(devices):
            phase = i * 2.094  # ~120° phase offset between devices
            sock.sendto(_frame(dev, t, phase).encode("utf-8"), (host, port))
            n += 1
        time.sleep(period)
except KeyboardInterrupt:
    print("\n[fake_sensor] Interrupted by the user.", flush=True)
finally:
    sock.close()
    print(f"[fake_sensor] Done. {n} datagrams sent.", flush=True)
