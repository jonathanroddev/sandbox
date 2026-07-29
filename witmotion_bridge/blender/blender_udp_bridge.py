"""
blender_udp_bridge.py
----------------------
Run INSIDE Blender (Scripting tab -> Text Editor -> Run Script).

Receives frames from the WitMotion WT901WIFI sensor(s) over UDP and applies
their orientation to scene objects. Unlike the MPU serial bridge (which
received raw data and did the fusion here), the WT901WIFI already delivers
angles fused by its own Kalman filter: here we only parse them, calibrate
against a reference pose, and apply them.

FLOW:
    sensor --(WiFi, UDP)--> socket on this machine --> parser by DeviceID
        --> calibration offset --> Blender object (rotation_quaternion)

DESIGN KEYS:
  - A SINGLE transport (UDP). There is no "UDP and then TCP": one is chosen.
    UDP fits motion capture better (less latency; a lost packet is dropped
    and the next one is used, without retransmitting stale poses).
  - NATIVE MULTI-SENSOR: each frame carries its DeviceID; DEVICE_MAP decides
    which object each sensor moves. A single socket serves all sensors.
  - POSE CALIBRATION (not per-sensor): at startup each sensor's orientation
    is captured as "zero" and its inverse is applied to every reading. Done
    with quaternions (mathutils) -> no gimbal lock, and it calibrates all
    three axes at once, not just yaw. We don't rely on the sensor's "Z-axis
    zero return" (which forces 6-axis mode and reintroduces yaw drift); we
    keep the absolute 9-axis yaw and "zero" it in software.

REQUIREMENTS:
  No pyserial needed. The UDP socket uses only the standard library, and
  mathutils ships with Blender. Nothing to install.

QUICK USAGE (in Blender's Python console, after Run Script):
    start_bridge()      # open the UDP socket and start listening
    calibrate()         # capture the reference pose NOW (strike the T-pose)
    recenter(device)    # recalibrate a specific sensor by its DeviceID
    list_devices()      # show the DeviceIDs seen and their assigned object
    stop_bridge()       # stop and close the socket

NOTE ON AXIS MAPPING:
  The sensor delivers angles in its own reference frame (and uses Z-Y-X
  Euler order). Blender is Z-up. The frame may not match the object
  depending on how you physically mount the sensor. We start with a direct
  mapping + configurable signs (SIGN_*), but this is the first thing to
  verify with the sensor in hand: move the sensor on one axis and check the
  object rotates on the correct axis and direction; adjust SIGN_* or the
  order in _angles_to_quat() if needed.
"""

import bpy
import socket
import time
import os
from mathutils import Euler, Quaternion

# ---------- CONFIGURATION LOADING (config.env) ----------
# Same pattern as blender_serial_bridge.py: everything that changes between
# PCs/networks/scenes lives in config.env, not here.

_DEFAULTS = {
    "LISTEN_HOST": "0.0.0.0",
    "LISTEN_PORT": "1399",
    "DEVICE_MAP": "*:Cube",
    "DEFAULT_OBJECT": "Cube",
    "AUTO_CALIBRATE": "1",
    "CALIB_COUNTDOWN": "3",
    "SIGN_ROLL": "1",
    "SIGN_PITCH": "1",
    "SIGN_YAW": "1",
    "IDX_DEVICE": "0",
    "IDX_ANGLE_X": "7",
    "IDX_ANGLE_Y": "8",
    "IDX_ANGLE_Z": "9",
    "MIN_FIELDS": "10",
}


def _find_config_path():
    env = os.environ.get("WITMOTION_BRIDGE_CONFIG")
    if env and os.path.isfile(env):
        return env
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "config.env"))
    except NameError:
        pass  # __file__ not defined (unsaved text in Blender's editor)
    candidates.append(os.path.join(os.getcwd(), "config.env"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _load_config():
    cfg = dict(_DEFAULTS)
    path = _find_config_path()
    if path is None:
        print("[wifi-bridge] WARNING: config.env not found; using default values.")
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip()
        print(f"[wifi-bridge] Config loaded from: {path}")
    except Exception as e:
        print(f"[wifi-bridge] WARNING: error reading {path}: {e}. Using defaults.")
    return cfg


def _parse_device_map(raw, default_object):
    """DEVICE_MAP 'A:Obj1,B:Obj2,*:Cube' -> dict {DeviceID: object}.
    The '*' key is the wildcard for sensors not listed."""
    mapping = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        dev, _, obj = pair.partition(":")
        mapping[dev.strip()] = obj.strip()
    if "*" not in mapping:
        mapping["*"] = default_object
    return mapping


_cfg = _load_config()

# ---------- EFFECTIVE CONFIGURATION ----------
LISTEN_HOST = _cfg["LISTEN_HOST"]
LISTEN_PORT = int(_cfg["LISTEN_PORT"])
DEFAULT_OBJECT = _cfg["DEFAULT_OBJECT"]
DEVICE_MAP = _parse_device_map(_cfg["DEVICE_MAP"], DEFAULT_OBJECT)
AUTO_CALIBRATE = _cfg["AUTO_CALIBRATE"] == "1"
CALIB_COUNTDOWN = float(_cfg["CALIB_COUNTDOWN"])
SIGN_ROLL = float(_cfg["SIGN_ROLL"])
SIGN_PITCH = float(_cfg["SIGN_PITCH"])
SIGN_YAW = float(_cfg["SIGN_YAW"])
IDX_DEVICE = int(_cfg["IDX_DEVICE"])
IDX_ANGLE_X = int(_cfg["IDX_ANGLE_X"])
IDX_ANGLE_Y = int(_cfg["IDX_ANGLE_Y"])
IDX_ANGLE_Z = int(_cfg["IDX_ANGLE_Z"])
MIN_FIELDS = int(_cfg["MIN_FIELDS"])

# ---------- GLOBAL STATE ----------
_sock = None
_offsets = {}          # DeviceID -> inverse reference Quaternion (zero)
_last_quat = {}        # DeviceID -> last measured quaternion (for on-demand calibration)
_seen_devices = set()  # DeviceIDs seen in this session
_calib_deadline = None  # time until which auto-calibration is deferred


def _object_for_device(device_id):
    """Resolve the Blender object assigned to a DeviceID (or the wildcard)."""
    name = DEVICE_MAP.get(device_id, DEVICE_MAP.get("*", DEFAULT_OBJECT))
    return bpy.data.objects.get(name)


def _angles_to_quat(ax_deg, ay_deg, az_deg):
    """Convert the sensor's angles (degrees) to a quaternion.

    WitMotion defines attitude with Z-Y-X Euler order (Z first, then Y,
    then X). In mathutils, Euler((rx,ry,rz), 'XYZ') applies X,Y,Z; to
    replicate Z-Y-X we use the 'ZYX' order with the angles in radians.
    The SIGN_* signs allow inverting an axis per the physical mounting.

    If some rotation comes out inverted or crossed when testing for real,
    this is the point to adjust (Euler order and/or SIGN_*).
    """
    from math import radians
    e = Euler(
        (
            radians(SIGN_ROLL * ax_deg),
            radians(SIGN_PITCH * ay_deg),
            radians(SIGN_YAW * az_deg),
        ),
        "ZYX",
    )
    return e.to_quaternion()


def _parse_datagram(data):
    """Parse a UDP datagram into (device_id, quat) or None if invalid.

    The WT901WIFI emits ASCII CSV terminated by \\r\\n. A datagram may
    contain one or several lines; we process the last complete line. The
    field indices are configurable (IDX_*) because the exact layout may
    vary with the firmware.
    """
    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not text:
        return None
    line = text.splitlines()[-1].strip()  # last complete line of the datagram
    parts = line.split(",")
    if len(parts) < MIN_FIELDS:
        return None
    try:
        device_id = parts[IDX_DEVICE].strip()
        ax = float(parts[IDX_ANGLE_X])
        ay = float(parts[IDX_ANGLE_Y])
        az = float(parts[IDX_ANGLE_Z])
    except (ValueError, IndexError):
        return None
    return device_id, _angles_to_quat(ax, ay, az)


def _apply(device_id, quat):
    """Apply the orientation (with calibration offset) to the assigned object."""
    _last_quat[device_id] = quat
    if device_id not in _seen_devices:
        _seen_devices.add(device_id)
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(no object assigned)"
        print(f"[wifi-bridge] New sensor: {device_id} -> {target}")

    obj = _object_for_device(device_id)
    if obj is None:
        return

    offset = _offsets.get(device_id)
    corrected = (offset @ quat) if offset is not None else quat

    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = corrected


def _pump():
    """Runs periodically via bpy.app.timers without blocking the UI.
    Drains all pending datagrams on each tick."""
    global _sock, _calib_deadline
    if _sock is None:
        return 0.1

    # Deferred auto-calibration: when the countdown expires, capture the pose.
    if _calib_deadline is not None and time.time() >= _calib_deadline:
        _calib_deadline = None
        calibrate()

    # Drain the socket buffer (non-blocking)
    for _ in range(200):  # per-tick cap so the UI doesn't hang on a flood
        try:
            data, _addr = _sock.recvfrom(2048)
        except BlockingIOError:
            break
        except Exception:
            break
        parsed = _parse_datagram(data)
        if parsed is not None:
            _apply(parsed[0], parsed[1])

    return 0.001  # continuous polling


# ---------- CONTROL / UTILITIES ----------
def calibrate():
    """Capture the CURRENT orientation of every seen sensor as the reference
    pose (zero). Applies the inverse to subsequent readings. Call this with
    the person/object in the reference pose (T-pose)."""
    n = 0
    for device_id, quat in _last_quat.items():
        _offsets[device_id] = quat.inverted()
        n += 1
    if n:
        print(f"[wifi-bridge] Reference pose captured for {n} sensor(s).")
    else:
        print("[wifi-bridge] WARNING: no sensor data yet to calibrate against.")


def recenter(device_id):
    """Recalibrate a specific sensor by its DeviceID (set its current pose to 0)."""
    quat = _last_quat.get(device_id)
    if quat is None:
        print(f"[wifi-bridge] No data from sensor '{device_id}' yet.")
        return
    _offsets[device_id] = quat.inverted()
    print(f"[wifi-bridge] Sensor '{device_id}' recentered.")


def list_devices():
    """Show the DeviceIDs seen in this session and their assigned object."""
    if not _seen_devices:
        print("[wifi-bridge] No sensor received yet.")
        return
    print("[wifi-bridge] Sensors seen:")
    for device_id in sorted(_seen_devices):
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(no object)"
        calib = "yes" if device_id in _offsets else "no"
        print(f"    {device_id} -> {target}   [calibrated: {calib}]")


def start_bridge():
    global _sock, _calib_deadline
    try:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _sock.bind((LISTEN_HOST, LISTEN_PORT))
        _sock.setblocking(False)
        print(f"[wifi-bridge] Listening on UDP {LISTEN_HOST}:{LISTEN_PORT}")
    except Exception as e:
        print(f"[wifi-bridge] ERROR opening UDP socket: {e}")
        _sock = None
        return

    if AUTO_CALIBRATE:
        _calib_deadline = time.time() + CALIB_COUNTDOWN
        print(f"[wifi-bridge] Auto-calibration in {CALIB_COUNTDOWN:.0f}s: "
              f"place the sensor(s) in the reference pose (T-pose).")

    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump)
    print("[wifi-bridge] Bridge started. Move the sensor to see the object react.")
    print("[wifi-bridge] Use calibrate() to set zero, list_devices() to see sensors.")


def stop_bridge():
    global _sock
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _sock is not None:
        _sock.close()
        _sock = None
    print("[wifi-bridge] Bridge stopped.")


# When running the script directly in Blender, start the bridge.
if __name__ == "__main__":
    start_bridge()

# To stop it manually from Blender's Python console:
#   stop_bridge()
