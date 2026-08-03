#!/usr/bin/env python3
"""
fake_sensor.py — Fake UDP emitter that mimics the project's WiFi sensors.

Used to VALIDATE the bridge's parsing, fusion and calibration WITHOUT any
hardware on the network (see "Testing without hardware" in ../CLAUDE.md).
It generates CSV frames identical to what a real sensor sends and streams
them to the port the bridge listens on, with the motion animated so the
Blender object visibly moves.

It can emit either profile of the shared protocol (../../docs/PROTOCOL.md):

    fused  13 fields — mimics the WitMotion WT901WIFI (angles already fused)
           0=DeviceID 1..3=Acc 4..6=Gyro 7..9=Angle 10..12=Mag
    raw6    7 fields — mimics Arduino/ESP + MPU-6050 (accel+gyro only, the
           bridge fuses it): 0=DeviceID 1..3=Acc 4..6=Gyro

In `raw6` the accel/gyro are generated to be PHYSICALLY CONSISTENT with the
animated angles (gravity projected onto the sensor frame, gyro = analytic
derivative of the angles), so the bridge's complementary filter has real
work to do and its output can be compared against the angles that generated
it. That is what makes this a test and not just a traffic generator.

No external dependencies: standard library only.

Usage:
    python3 tools/fake_sensor.py [PORT] [SECONDS] [HZ] [HOST] [DEVICES] [PROFILE]

Defaults:
    PORT    -> LISTEN_PORT from blender/config.env (if found), else 1399
    SECONDS -> 0 = indefinite (until Ctrl+C)
    HZ      -> 50 datagrams/second
    HOST    -> 127.0.0.1 (localhost; the bridge listens on 0.0.0.0)
    DEVICES -> WT9AXTEST (one). Several: comma-separate for multi-sensor,
               e.g.  WT53abc,ESP32_A  -> each moves its own object per
               DEVICE_MAP. Each device is animated with a different phase
               so they can be told apart.
    PROFILE -> fused (the WT901WIFI layout). Use `raw6` for the Arduino/ESP
               layout.

Examples:
    # One WT901WIFI-like sensor to the default port, indefinitely:
    python3 tools/fake_sensor.py
    # Two sensors at 100 Hz for 20 s (multi-sensor test):
    python3 tools/fake_sensor.py 1399 20 100 127.0.0.1 WT53abc,WT53def
    # An Arduino/ESP-like sensor at its realistic 20 Hz:
    python3 tools/fake_sensor.py 1399 0 20 127.0.0.1 ESP32_A raw6
    # One of each at once (the bridge must handle both profiles together):
    python3 tools/fake_sensor.py 1399 0 50 127.0.0.1 WT53abc fused &
    python3 tools/fake_sensor.py 1399 0 20 127.0.0.1 ESP32_A raw6
"""
import sys
import os
import socket
import time
from math import sin, cos, radians, degrees


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
profile = (sys.argv[6].strip().lower() if len(sys.argv) > 6 else "fused")

if profile not in ("fused", "raw6"):
    print(f"[fake_sensor] Unknown profile {profile!r}. Use 'fused' or 'raw6'.")
    sys.exit(1)

period = 1.0 / hz if hz > 0 else 0.02

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

mode = f"{secs:.0f}s" if secs > 0 else "indefinite (Ctrl+C to stop)"
print(f"[fake_sensor] Sending to {host}:{port} @ {hz:.0f} Hz, {mode}", flush=True)
print(f"[fake_sensor] Profile: {profile} | Devices: {', '.join(devices)}", flush=True)


# --- The motion being simulated (shared by both profiles) ---
# Different amplitudes and frequencies per axis so roll, pitch and yaw are
# easy to tell apart when watching the object in Blender.
_W_ROLL, _A_ROLL = 0.8, 30.0
_W_PITCH, _A_PITCH = 1.3, 20.0
_W_YAW, _A_YAW = 0.5, 45.0


def _attitude(t, phase):
    """Angles (deg) and their exact time derivatives (deg/s) at time t."""
    roll = _A_ROLL * sin(_W_ROLL * t + phase)
    pitch = _A_PITCH * sin(_W_PITCH * t + phase + 1.0)
    yaw = _A_YAW * sin(_W_YAW * t + phase + 2.0)
    d_roll = _A_ROLL * _W_ROLL * cos(_W_ROLL * t + phase)
    d_pitch = _A_PITCH * _W_PITCH * cos(_W_PITCH * t + phase + 1.0)
    d_yaw = _A_YAW * _W_YAW * cos(_W_YAW * t + phase + 2.0)
    return (roll, pitch, yaw), (d_roll, d_pitch, d_yaw)


def _imu(angles, rates):
    """Accel (g) and gyro (deg/s) a real MPU would report in that attitude.

    Accel is gravity projected onto the sensor frame — the inverse of what
    the bridge's filter does to recover roll/pitch from the accelerometer,
    so feeding this back through it must return the original angles.
    Gyro is the angle derivative (a small-angle approximation: good enough
    to exercise the filter, not a full body-rate transformation).
    """
    roll, pitch, _ = angles
    r, p = radians(roll), radians(pitch)
    ax = -sin(p)
    ay = sin(r) * cos(p)
    az = cos(r) * cos(p)
    return (ax, ay, az), rates


def _frame(device_id, t, phase):
    """Build one CSV frame for the selected profile."""
    angles, rates = _attitude(t, phase)
    (ax, ay, az), (gx, gy, gz) = _imu(angles, rates)

    fields = [
        device_id,
        f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
        f"{gx:.4f}", f"{gy:.4f}", f"{gz:.4f}",
    ]
    if profile == "fused":
        roll, pitch, yaw = angles
        fields += [f"{roll:.2f}", f"{pitch:.2f}", f"{yaw:.2f}"]
        fields += ["0.300", "-0.100", "0.450"]   # Mag: plausible fixed values
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
