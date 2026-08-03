"""
blender_udp_bridge.py
----------------------
Run INSIDE Blender (Scripting tab -> Text Editor -> Run Script).

Receives frames from one or MORE sensors over WiFi (UDP) and applies their
orientation to scene objects. It serves every WiFi sensor in this project,
whatever it sends (see ../../docs/PROTOCOL.md):

  - `fused` profile (WitMotion WT901WIFI, 13 fields): the sensor already
    fused accel+gyro+mag with its own Kalman filter. We use its angles.
  - `raw6` profile (Arduino/ESP + MPU-6050, 7 fields): the board only reads
    and sends. The fusion (complementary filter) happens HERE, per device,
    exactly like the wired bridge does.

Both end up as a quaternion, so everything downstream — calibration,
mapping, applying to the object — is shared.

FLOW:
    sensor(s) --(WiFi, UDP)--> socket --> parse by DeviceID --> [fuse if raw6]
        --> axis map --> calibration offset --> Blender object (quaternion)

DESIGN KEYS:
  - A SINGLE transport (UDP). UDP fits motion capture better than TCP: a
    lost packet is dropped and the next one used, instead of retransmitting
    an already-stale pose.
  - NATIVE MULTI-SENSOR: each frame carries its DeviceID; DEVICE_MAP decides
    which object each sensor moves. One socket serves all of them, and each
    keeps its own fusion state and its own calibration offset.
  - POSE CALIBRATION: at startup each sensor's orientation is captured as
    "zero" and its inverse applied to every reading. With quaternions -> no
    gimbal lock, and all three axes are calibrated at once, not just yaw.

REQUIREMENTS:
  Nothing to install. The UDP socket is standard library and mathutils
  ships with Blender. (Unlike the wired bridge, no pyserial.)

QUICK USAGE (in Blender's Python console, after Run Script):
    start_bridge()      # open the UDP socket and start listening
    calibrate()         # capture the reference pose NOW (strike the T-pose)
    recenter(device)    # recalibrate one sensor by its DeviceID
    list_devices()      # DeviceIDs seen, their object and their profile
    show_log()          # show this script's messages inside Blender
    stop_bridge()       # stop and close the socket

WHERE THE MESSAGES GO:
  Everything is printed to the system console AND mirrored into a Text
  datablock ("wifi_bridge_log" by default), so you do not need to have
  launched Blender from a terminal to see what the bridge is doing. Open a
  Text Editor and pick it from the datablock dropdown, or call show_log().

NOTE ON AXIS MAPPING:
  A sensor's frame does not match Blender's until you account for how it is
  physically mounted. Fix it in config.env: SIGN_* inverts a direction,
  AXIS_MAP permutes which source drives which Blender axis. Do not patch
  this file for a mounting difference.

NOTE ON YAW (raw6 only):
  An MPU-6050 has no magnetometer, so its yaw is integrated gyro and drifts.
  Call recenter(device) to re-zero it. The WT901WIFI does not have this
  problem (9-axis, absolute heading).
"""

import bpy
import socket
import time
import math
import os
from mathutils import Euler

# ---------- CONFIGURATION LOADING (config.env) ----------
# Same pattern as the wired bridge: everything that changes between
# PCs/networks/scenes lives in config.env, not here.

_DEFAULTS = {
    "LISTEN_HOST": "0.0.0.0",
    "LISTEN_PORT": "1399",
    "DEVICE_MAP": "*:Cube",
    "DEFAULT_OBJECT": "_UNASSIGNED",
    "AUTO_CALIBRATE": "1",
    "CALIB_COUNTDOWN": "3",
    "SIGN_ROLL": "1",
    "SIGN_PITCH": "1",
    "SIGN_YAW": "1",
    "AXIS_MAP": "roll,pitch,yaw",
    "FRAME_FORMAT": "auto",
    "IDX_DEVICE": "0",
    "IDX_ACC_X": "1",
    "IDX_ACC_Y": "2",
    "IDX_ACC_Z": "3",
    "IDX_GYRO_X": "4",
    "IDX_GYRO_Y": "5",
    "IDX_GYRO_Z": "6",
    "IDX_ANGLE_X": "7",
    "IDX_ANGLE_Y": "8",
    "IDX_ANGLE_Z": "9",
    "MIN_FIELDS": "7",
    "ALPHA_ROLL_PITCH": "0.98",
    "GYRO_CALIB_SAMPLES": "50",
    "LOG_TO_TEXT": "1",
    "LOG_TEXT_NAME": "wifi_bridge_log",
    "LOG_MAX_LINES": "500",
}

# ---------- LOGGING ----------
# print() inside Blender goes to the SYSTEM CONSOLE, which on macOS/Linux
# means you only see it if you launched Blender from a terminal (on Windows:
# Window -> Toggle System Console). That is a poor place for the messages
# that matter most here — "your sensor arrived and it maps to no object",
# "keep it still, estimating bias". So every message is ALSO mirrored into a
# Text datablock you can open in Blender's own Text Editor and watch live.
#
# In Blender: Text Editor -> the datablock dropdown -> pick LOG_TEXT_NAME
# (default "wifi_bridge_log"), or just call show_log() from the console.

# Effective values until config.env is read (logging must work before that).
LOG_TO_TEXT = _DEFAULTS["LOG_TO_TEXT"] == "1"
LOG_TEXT_NAME = _DEFAULTS["LOG_TEXT_NAME"]
LOG_MAX_LINES = int(_DEFAULTS["LOG_MAX_LINES"])

_log_lines = []      # tail of this session's log, oldest first
_log_ready = False   # True once the real LOG_* values are known


def _log(msg):
    """Print a message to the console AND mirror it inside Blender."""
    print(f"[wifi-bridge] {msg}")
    _log_lines.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(_log_lines) > LOG_MAX_LINES:
        del _log_lines[:-LOG_MAX_LINES]
    if _log_ready and LOG_TO_TEXT:
        _log_flush()


def _log_flush():
    """Rewrite the Text datablock with the current log tail.

    Rewriting rather than appending is deliberate: Text.write() inserts at
    the CURSOR, so once you click anywhere inside the log in the editor,
    appended lines would land wherever you left it. Rewriting is immune to
    that, and at a few dozen messages per session the cost is irrelevant.
    Never raises: a logging problem must not take the bridge down.
    """
    try:
        txt = bpy.data.texts.get(LOG_TEXT_NAME)
        if txt is None:
            txt = bpy.data.texts.new(LOG_TEXT_NAME)
        txt.clear()
        txt.write("\n".join(_log_lines) + "\n")
        txt.current_line_index = max(0, len(txt.lines) - 1)  # follow the tail
    except Exception as e:
        print(f"[wifi-bridge] WARNING: could not write the log datablock: {e}")


def show_log():
    """Point an open Text Editor at the log datablock.

    Call it from Blender's Python console. If no Text Editor area is open,
    it says so instead of failing: split an area into a Text Editor first.
    """
    if not LOG_TO_TEXT:
        print("[wifi-bridge] LOG_TO_TEXT=0 in config.env: nothing is mirrored.")
        return
    _log_flush()
    txt = bpy.data.texts.get(LOG_TEXT_NAME)
    shown = 0
    try:
        for area in bpy.context.screen.areas:
            if area.type == "TEXT_EDITOR":
                area.spaces.active.text = txt
                shown += 1
    except Exception:
        pass
    if shown:
        print(f"[wifi-bridge] Log shown in {shown} Text Editor area(s).")
    else:
        print(f"[wifi-bridge] No Text Editor open. Split an area into one and "
              f"pick '{LOG_TEXT_NAME}' from its datablock dropdown.")


def _blender_config_dirs():
    """Candidate directories inferable from Blender itself.

    Inside Blender's text editor `__file__` often does NOT exist and
    os.getcwd() does not point at the script's folder, so config.env is not
    found even when sitting right next to it. Here we recover the folder
    from the open external text datablocks (a .py loaded from disk exposes
    its `filepath`) and from the location of the saved .blend.
    """
    dirs = []
    try:
        for t in bpy.data.texts:
            fp = getattr(t, "filepath", "") or ""
            if fp:
                d = os.path.dirname(bpy.path.abspath(fp))
                if d and d not in dirs:
                    dirs.append(d)
        if bpy.data.filepath:
            d = os.path.dirname(bpy.path.abspath(bpy.data.filepath))
            if d and d not in dirs:
                dirs.append(d)
    except Exception:
        pass  # bpy unavailable or different API; ignored without breaking
    return dirs


def _find_config_path():
    env = os.environ.get("WIFI_BRIDGE_CONFIG")
    if env and os.path.isfile(env):
        return env
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "config.env"))
    except NameError:
        pass  # __file__ not defined (unsaved text in Blender's editor)
    # Folders inferred from Blender (the reliable path inside the text editor).
    for d in _blender_config_dirs():
        candidates.append(os.path.join(d, "config.env"))
    candidates.append(os.path.join(os.getcwd(), "config.env"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _load_config():
    cfg = dict(_DEFAULTS)
    path = _find_config_path()
    if path is None:
        _log("WARNING: config.env not found; using default values.")
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip()
        _log(f"Config loaded from: {path}")
    except Exception as e:
        _log(f"WARNING: error reading {path}: {e}. Using defaults.")
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


def _parse_axis_map(spec):
    """Turn an AXIS_MAP like "pitch,-roll,yaw" into a list of 3 tuples
    (source, sign) for Blender's X, Y, Z axes.

    - Exactly 3 comma-separated tokens, each roll/pitch/yaw, optionally
      prefixed with '+' or '-' ('-' inverts that axis).
    - Combines with SIGN_ROLL/PITCH/YAW, which are applied to the source.

    Examples:
        "roll,pitch,yaw"    -> identity: X=roll, Y=pitch, Z=yaw
        "pitch,roll,yaw"    -> swaps roll and pitch
        "roll,pitch,-yaw"   -> like identity but yaw inverted
    Invalid specs warn and fall back to identity.
    """
    valid = {"roll", "pitch", "yaw"}
    identity = [("roll", 1.0), ("pitch", 1.0), ("yaw", 1.0)]
    tokens = [t.strip().lower() for t in str(spec).split(",")]
    if len(tokens) != 3:
        _log(f"WARNING: AXIS_MAP must have 3 axes, not "
              f"{len(tokens)} ({spec!r}). Using identity.")
        return identity
    result = []
    for tok in tokens:
        sign = 1.0
        if tok.startswith("-"):
            sign, tok = -1.0, tok[1:].strip()
        elif tok.startswith("+"):
            tok = tok[1:].strip()
        if tok not in valid:
            _log(f"WARNING: invalid axis source in AXIS_MAP: "
                  f"{tok!r} ({spec!r}). Using identity.")
            return identity
        result.append((tok, sign))
    if set(src for src, _ in result) != valid:
        _log(f"WARNING: AXIS_MAP does not use roll/pitch/yaw "
              f"exactly once each ({spec!r}). Applied anyway, but this is "
              f"probably not what you want.")
    return result


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
AXIS_MAP = _parse_axis_map(_cfg["AXIS_MAP"])
FRAME_FORMAT = _cfg["FRAME_FORMAT"].strip().lower()   # auto | fused | raw6
IDX_DEVICE = int(_cfg["IDX_DEVICE"])
IDX_ACC = (int(_cfg["IDX_ACC_X"]), int(_cfg["IDX_ACC_Y"]), int(_cfg["IDX_ACC_Z"]))
IDX_GYRO = (int(_cfg["IDX_GYRO_X"]), int(_cfg["IDX_GYRO_Y"]), int(_cfg["IDX_GYRO_Z"]))
IDX_ANGLE = (int(_cfg["IDX_ANGLE_X"]), int(_cfg["IDX_ANGLE_Y"]), int(_cfg["IDX_ANGLE_Z"]))
MIN_FIELDS = int(_cfg["MIN_FIELDS"])
ALPHA_ROLL_PITCH = float(_cfg["ALPHA_ROLL_PITCH"])
GYRO_CALIB_SAMPLES = int(_cfg["GYRO_CALIB_SAMPLES"])
LOG_TO_TEXT = _cfg["LOG_TO_TEXT"] == "1"
LOG_TEXT_NAME = _cfg["LOG_TEXT_NAME"]
LOG_MAX_LINES = int(_cfg["LOG_MAX_LINES"])

# From here on, everything logged so far can reach the Text datablock too.
_log_ready = True
if LOG_TO_TEXT:
    _log_flush()

# Field count each profile needs, derived from the indices: no second place
# to keep in sync when someone adjusts an IDX_*.
_NEED_FUSED = max(IDX_ANGLE) + 1
_NEED_RAW6 = max(max(IDX_ACC), max(IDX_GYRO)) + 1

_log(f"Effective AXIS_MAP (X,Y,Z): "
      f"{[(s if g > 0 else '-' + s) for s, g in AXIS_MAP]}")
_log(f"Frame format: {FRAME_FORMAT} "
      f"(fused needs >={_NEED_FUSED} fields, raw6 >={_NEED_RAW6})")

# ---------- GLOBAL STATE ----------
_sock = None
_offsets = {}          # DeviceID -> inverse reference Quaternion (zero)
_last_quat = {}        # DeviceID -> last measured quaternion (for on-demand calibration)
_seen_devices = {}     # DeviceID -> profile seen ("fused" / "raw6")
_fusion = {}           # DeviceID -> complementary filter state (raw6 only)
_calib_deadline = None  # time until which auto-calibration is deferred


def _object_for_device(device_id):
    """Resolve the Blender object assigned to a DeviceID (or the wildcard)."""
    name = DEVICE_MAP.get(device_id, DEVICE_MAP.get("*", DEFAULT_OBJECT))
    return bpy.data.objects.get(name)


def _angles_to_quat(roll_deg, pitch_deg, yaw_deg):
    """Convert roll/pitch/yaw (degrees, sensor frame) to a Blender quaternion.

    Two stages, same as the wired bridge:
      1) SIGN_*: invert the direction of a source that reads "backwards".
      2) AXIS_MAP: permute which source drives Blender's X, Y and Z. Signs
         cannot fix a permutation, which is why both exist.

    The Euler order is 'ZYX' because that is how WitMotion defines attitude
    (Z first, then Y, then X). The raw6 angles come out of our own filter
    with the same convention, so both share this path.
    """
    sources = {
        "roll": SIGN_ROLL * roll_deg,
        "pitch": SIGN_PITCH * pitch_deg,
        "yaw": SIGN_YAW * yaw_deg,
    }
    (src_x, sg_x), (src_y, sg_y), (src_z, sg_z) = AXIS_MAP
    e = Euler(
        (
            math.radians(sg_x * sources[src_x]),
            math.radians(sg_y * sources[src_y]),
            math.radians(sg_z * sources[src_z]),
        ),
        "ZYX",
    )
    return e.to_quaternion()


def _fuse_raw6(device_id, ax, ay, az, gx, gy, gz):
    """Complementary filter for a `raw6` sensor, with per-device state.

    Returns (roll, pitch, yaw) in degrees, or None while the device is still
    estimating its gyro bias (KEEP IT STILL for the first
    GYRO_CALIB_SAMPLES frames — an unremoved bias integrates into drift).

    Roll/pitch are absolute (gravity reference from the accelerometer);
    yaw is integrated gyro only and WILL drift: the MPU-6050 has no
    magnetometer. Re-zero it with recenter(device_id).
    """
    st = _fusion.get(device_id)
    if st is None:
        st = _fusion[device_id] = {
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "last_t": None,
            "bias": [0.0, 0.0, 0.0],
            "bias_sum": [0.0, 0.0, 0.0],
            "bias_n": 0,
            "ready": False,
        }

    # --- Startup: estimate the gyro bias while the sensor rests ---
    if not st["ready"]:
        if st["bias_n"] == 0:
            _log(f"'{device_id}': estimating gyro bias, "
                  f"KEEP IT STILL ({GYRO_CALIB_SAMPLES} samples)...")
        st["bias_sum"][0] += gx
        st["bias_sum"][1] += gy
        st["bias_sum"][2] += gz
        st["bias_n"] += 1
        if st["bias_n"] >= GYRO_CALIB_SAMPLES:
            n = float(st["bias_n"])
            st["bias"] = [s / n for s in st["bias_sum"]]
            st["ready"] = True
            _log(f"'{device_id}' gyro bias (deg/s): "
                  f"gx={st['bias'][0]:.3f} gy={st['bias'][1]:.3f} "
                  f"gz={st['bias'][2]:.3f}")
        return None

    gx -= st["bias"][0]
    gy -= st["bias"][1]
    gz -= st["bias"][2]

    now = time.time()
    first = st["last_t"] is None
    dt = 0.02 if first else (now - st["last_t"])
    st["last_t"] = now

    # --- Roll/pitch: accelerometer (absolute) + gyroscope (smooth) ---
    accel_roll = math.degrees(math.atan2(ay, az))
    accel_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    if first:
        # Seed from the accelerometer instead of from 0, or the filter
        # spends its first second crawling from "flat" to the real attitude.
        st["roll"], st["pitch"] = accel_roll, accel_pitch
    gyro_roll = st["roll"] + gx * dt
    gyro_pitch = st["pitch"] + gy * dt
    st["roll"] = ALPHA_ROLL_PITCH * gyro_roll + (1 - ALPHA_ROLL_PITCH) * accel_roll
    st["pitch"] = ALPHA_ROLL_PITCH * gyro_pitch + (1 - ALPHA_ROLL_PITCH) * accel_pitch

    # --- Yaw: ONLY integrated gyroscope (no magnetometer -> drift) ---
    st["yaw"] += gz * dt

    return st["roll"], st["pitch"], st["yaw"]


def _profile_for(n_fields):
    """Decide which profile a frame follows, from FRAME_FORMAT and its size.

    'auto' prefers `fused` when the frame is long enough to carry angles: if
    a sensor already did the fusion, trust it over redoing it here.
    """
    if FRAME_FORMAT == "fused":
        return "fused" if n_fields >= _NEED_FUSED else None
    if FRAME_FORMAT == "raw6":
        return "raw6" if n_fields >= _NEED_RAW6 else None
    if n_fields >= _NEED_FUSED:
        return "fused"
    if n_fields >= _NEED_RAW6:
        return "raw6"
    return None


def _parse_datagram(data):
    """Parse a UDP datagram into (device_id, quat) or None if unusable.

    Frames are ASCII CSV terminated by \\r\\n. A datagram may hold several
    lines; we process the last complete one. Field positions are
    configurable (IDX_*) because layouts vary between firmwares.
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
    profile = _profile_for(len(parts))
    if profile is None:
        return None

    try:
        device_id = parts[IDX_DEVICE].strip()
        if profile == "fused":
            angles = tuple(float(parts[i]) for i in IDX_ANGLE)
        else:
            accel = tuple(float(parts[i]) for i in IDX_ACC)
            gyro = tuple(float(parts[i]) for i in IDX_GYRO)
    except (ValueError, IndexError):
        return None

    if device_id not in _seen_devices:
        _seen_devices[device_id] = profile
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(no object assigned)"
        _log(f"New sensor: {device_id} [{profile}] -> {target}")

    if profile == "raw6":
        angles = _fuse_raw6(device_id, accel[0], accel[1], accel[2],
                            gyro[0], gyro[1], gyro[2])
        if angles is None:
            return None  # still estimating the bias; nothing to apply yet

    return device_id, _angles_to_quat(angles[0], angles[1], angles[2])


def _apply(device_id, quat):
    """Apply the orientation (with calibration offset) to the assigned object."""
    _last_quat[device_id] = quat
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
        _log(f"Reference pose captured for {n} sensor(s).")
    else:
        _log("WARNING: no sensor data yet to calibrate against.")


def recenter(device_id):
    """Recalibrate one sensor by its DeviceID (set its current pose to 0).
    This is also how you cancel the yaw drift of a raw6 sensor."""
    quat = _last_quat.get(device_id)
    if quat is None:
        _log(f"No data from sensor '{device_id}' yet.")
        return
    _offsets[device_id] = quat.inverted()
    _log(f"Sensor '{device_id}' recentered.")


def list_devices():
    """Show the DeviceIDs seen in this session, their profile and object."""
    if not _seen_devices:
        _log("No sensor received yet.")
        return
    _log("Sensors seen:")
    for device_id in sorted(_seen_devices):
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(no object)"
        profile = _seen_devices[device_id]
        calib = "yes" if device_id in _offsets else "no"
        _log(f"    {device_id} [{profile}] -> {target}   [calibrated: {calib}]")


def start_bridge():
    global _sock, _calib_deadline
    try:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _sock.bind((LISTEN_HOST, LISTEN_PORT))
        _sock.setblocking(False)
        _log(f"Listening on UDP {LISTEN_HOST}:{LISTEN_PORT}")
    except Exception as e:
        _log(f"ERROR opening UDP socket: {e}")
        _sock = None
        return

    if AUTO_CALIBRATE:
        _calib_deadline = time.time() + CALIB_COUNTDOWN
        _log(f"Auto-calibration in {CALIB_COUNTDOWN:.0f}s: "
              f"place the sensor(s) in the reference pose (T-pose).")

    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump)
    _log("Bridge started. Move the sensor to see the object react.")
    _log("Use calibrate() to set zero, list_devices() to see sensors.")
    if LOG_TO_TEXT:
        _log(f"These messages are also in the '{LOG_TEXT_NAME}' text "
             f"datablock — open a Text Editor or call show_log().")


def stop_bridge():
    global _sock
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _sock is not None:
        _sock.close()
        _sock = None
    _log("Bridge stopped.")


# When running the script directly in Blender, start the bridge.
if __name__ == "__main__":
    start_bridge()

# To stop it manually from Blender's Python console:
#   stop_bridge()
