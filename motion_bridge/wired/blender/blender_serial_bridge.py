"""
blender_serial_bridge.py
-------------------------
Run INSIDE Blender (Scripting tab -> Text Editor -> Run Script).

Reads CSV lines from the Arduino (MPU-6050) over the serial port:
    ax,ay,az,gx,gy,gz

Computes roll/pitch/yaw and applies them to the object named in OBJECT_NAME:
  - Accelerometer + gyroscope -> roll and pitch (complementary filter).
    These are ABSOLUTE and stable (gravity reference).
  - Integrated gyroscope -> yaw. The MPU-6050 has NO magnetometer, so yaw
    has NO absolute reference and DRIFTS slowly over time. It can be zeroed
    at any moment with recenter_yaw().

REQUIREMENTS:
  Blender ships its own Python interpreter, so pyserial must be installed
  into THAT python, not the system one. From a terminal:

      /Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial

  (find the path by running in Blender's Python console:
      import sys; print(sys.exec_prefix)
  )

QUICK USAGE (in Blender's Python console, after Run Script):
    start_bridge()      # start (calibrates the gyro bias ~1s while at rest)
    recenter_yaw()      # set current yaw to 0 (cancels accumulated drift)
    recenter_all()      # set roll/pitch/yaw to 0
    show_log()          # show this script's messages inside Blender
    stop_bridge()       # stop and close the port

WHERE THE MESSAGES GO:
  Everything is printed to the system console AND mirrored into a Text
  datablock ("wired_bridge_log" by default), so you do not need to have
  launched Blender from a terminal to see what the bridge is doing. Open a
  Text Editor and pick it from the datablock dropdown, or call show_log().

NOTE ON YAW DRIFT:
  It is inherent to the hardware (no magnetometer). To minimize it, the gyro
  bias is estimated at startup by keeping the sensor STILL for ~1 second.
  Even so, some drift remains; use recenter_yaw() when needed (for example,
  by mapping a key to that function).
"""

import bpy
import serial
import math
import time
import os

# ---------- CONFIGURATION LOADING (config.env) ----------
# Everything that usually changes between PCs/scenes lives in config.env,
# not here. The file is resolved, in order:
#   1) the WIRED_BRIDGE_CONFIG environment variable (absolute path), if set.
#   2) config.env next to this script (when __file__ is defined).
#   3) config.env in the current working directory.
# If none is found, the _DEFAULTS values below are used.

_DEFAULTS = {
    # Placeholder on purpose: the Nano's port depends on its USB-serial chip
    # (wchusbserial/usbserial on macOS, ttyUSB on Linux) and is not known
    # until the board is plugged in. Set the real one in config.env.
    "SERIAL_PORT": "/dev/cu.wchusbserial-CHANGE_ME",
    "BAUD_RATE": "115200",
    "OBJECT_NAME": "Cube",
    "ALPHA_ROLL_PITCH": "0.98",
    "GYRO_CALIB_SAMPLES": "50",
    "SIGN_ROLL": "1",
    "SIGN_PITCH": "1",
    "SIGN_YAW": "1",
    # Axis permutation: which source (roll/pitch/yaw) goes to each Blender
    # axis, in X,Y,Z order. Prefix '-' to invert. Identity =
    # "roll,pitch,yaw" (classic behavior). See _parse_axis_map().
    "AXIS_MAP": "pitch,roll,yaw",
    "LOG_TO_TEXT": "1",
    "LOG_TEXT_NAME": "wired_bridge_log",
    "LOG_MAX_LINES": "500",
}

# ---------- LOGGING ----------
# print() inside Blender goes to the SYSTEM CONSOLE, which on macOS/Linux
# means you only see it if you launched Blender from a terminal (on Windows:
# Window -> Toggle System Console). That is a poor place for the messages
# that matter most here — "the serial port failed to open", "keep the sensor
# still". So every message is ALSO mirrored into a Text datablock you can
# open in Blender's own Text Editor and watch live.
#
# In Blender: Text Editor -> the datablock dropdown -> pick LOG_TEXT_NAME
# (default "wired_bridge_log"), or just call show_log() from the console.

# Effective values until config.env is read (logging must work before that).
LOG_TO_TEXT = _DEFAULTS["LOG_TO_TEXT"] == "1"
LOG_TEXT_NAME = _DEFAULTS["LOG_TEXT_NAME"]
LOG_MAX_LINES = int(_DEFAULTS["LOG_MAX_LINES"])

_log_lines = []      # tail of this session's log, oldest first
_log_ready = False   # True once the real LOG_* values are known


def _log(msg):
    """Print a message to the console AND mirror it inside Blender."""
    print(f"[bridge] {msg}")
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
        print(f"[bridge] WARNING: could not write the log datablock: {e}")


def show_log():
    """Point an open Text Editor at the log datablock.

    Call it from Blender's Python console. If no Text Editor area is open,
    it says so instead of failing: split an area into a Text Editor first.
    """
    if not LOG_TO_TEXT:
        print("[bridge] LOG_TO_TEXT=0 in config.env: nothing is mirrored.")
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
        print(f"[bridge] Log shown in {shown} Text Editor area(s).")
    else:
        print(f"[bridge] No Text Editor open. Split an area into one and "
              f"pick '{LOG_TEXT_NAME}' from its datablock dropdown.")


def _blender_config_dirs():
    """Candidate directories inferable from Blender itself.

    Inside Blender's text editor, `__file__` often does NOT exist and
    `os.getcwd()` does not point to the script's folder, so config.env was
    not found even when sitting right "next to" it. Here we recover the
    folder from the open external text datablocks (a .py loaded from disk
    exposes its `filepath`) and from the location of the saved .blend file.
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
    env = os.environ.get("WIRED_BRIDGE_CONFIG")
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
    """Read config.env (KEY=value) and return a dict, based on _DEFAULTS."""
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


def _parse_axis_map(spec):
    """Turn an AXIS_MAP like "pitch,-roll,yaw" into a list of 3 tuples
    (source, sign) for Blender's X, Y, Z axes.

    - Exactly 3 comma-separated tokens.
    - Each token is roll/pitch/yaw, optionally prefixed with '+' or '-'.
    - '-' inverts that axis (equivalent to multiplying by -1); it combines
      with SIGN_ROLL/PITCH/YAW (which are applied to the source).

    Examples:
        "roll,pitch,yaw"    -> identity (classic): X=roll, Y=pitch, Z=yaw
        "pitch,roll,yaw"    -> swaps roll and pitch
        "roll,pitch,-yaw"   -> like identity but yaw inverted
    If the spec is invalid, it warns and falls back to identity.
    """
    valid = {"roll", "pitch", "yaw"}
    identity = [("roll", 1.0), ("pitch", 1.0), ("yaw", 1.0)]
    tokens = [t.strip().lower() for t in str(spec).split(",")]
    if len(tokens) != 3:
        _log(f"WARNING: AXIS_MAP must have 3 axes, not {len(tokens)} "
              f"({spec!r}). Using identity.")
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
    sources = [src for src, _ in result]
    if set(sources) != valid:
        _log(f"WARNING: AXIS_MAP does not use roll/pitch/yaw exactly "
              f"once each ({spec!r}). Applied anyway, but this is probably "
              f"not what you want.")
    return result


_cfg = _load_config()

# ---------- EFFECTIVE CONFIGURATION ----------
SERIAL_PORT = _cfg["SERIAL_PORT"]
BAUD_RATE = int(_cfg["BAUD_RATE"])
OBJECT_NAME = _cfg["OBJECT_NAME"]
ALPHA_ROLL_PITCH = float(_cfg["ALPHA_ROLL_PITCH"])   # Gyro weight in roll/pitch
GYRO_CALIB_SAMPLES = int(_cfg["GYRO_CALIB_SAMPLES"])  # Samples for the gyro bias
SIGN_ROLL = float(_cfg["SIGN_ROLL"])                 # Axis sign (+1 / -1) per mounting
SIGN_PITCH = float(_cfg["SIGN_PITCH"])
SIGN_YAW = float(_cfg["SIGN_YAW"])
AXIS_MAP = _parse_axis_map(_cfg["AXIS_MAP"])         # Source->Blender-axis permutation
LOG_TO_TEXT = _cfg["LOG_TO_TEXT"] == "1"
LOG_TEXT_NAME = _cfg["LOG_TEXT_NAME"]
LOG_MAX_LINES = int(_cfg["LOG_MAX_LINES"])

# From here on, everything logged so far can reach the Text datablock too.
_log_ready = True
if LOG_TO_TEXT:
    _log_flush()

_log(f"Effective AXIS_MAP (X,Y,Z): "
     f"{[(s if g > 0 else '-' + s) for s, g in AXIS_MAP]}")

# ---------- GLOBAL STATE ----------
_ser = None
_roll = 0.0
_pitch = 0.0
_yaw = 0.0
_last_time = None
_bias_gx = 0.0
_bias_gy = 0.0
_bias_gz = 0.0


def _open_serial():
    global _ser
    try:
        _ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2)  # Give the Arduino time to reset after opening the port
        _ser.reset_input_buffer()
        _log(f"Serial port opened: {SERIAL_PORT}")
    except Exception as e:
        _log(f"ERROR opening serial port: {e}")
        _ser = None


def _parse_line(line):
    """Return (ax,ay,az,gx,gy,gz) or None if the line is not valid."""
    parts = line.split(",")
    if len(parts) != 6:
        return None
    try:
        return tuple(map(float, parts))
    except ValueError:
        return None


def _calibrate_gyro_bias():
    """Average several readings with the sensor STILL to estimate the gyro
    bias (an offset that, once integrated, would cause drift)."""
    global _bias_gx, _bias_gy, _bias_gz
    if _ser is None:
        return
    _log("Calibrating gyro bias: KEEP THE SENSOR STILL...")
    sx = sy = sz = 0.0
    n = 0
    t_end = time.time() + 3.0  # at most 3s looking for samples
    while n < GYRO_CALIB_SAMPLES and time.time() < t_end:
        line = _ser.readline().decode("utf-8", errors="ignore").strip()
        vals = _parse_line(line)
        if vals is None:
            continue
        _, _, _, gx, gy, gz = vals
        sx += gx; sy += gy; sz += gz
        n += 1
    if n > 0:
        _bias_gx = sx / n
        _bias_gy = sy / n
        _bias_gz = sz / n
        _log(f"Gyro bias (deg/s): "
              f"gx={_bias_gx:.3f} gy={_bias_gy:.3f} gz={_bias_gz:.3f}  ({n} samples)")
    else:
        _log("WARNING: could not calibrate the bias (no data). Bias = 0.")


def _complementary_filter(ax, ay, az, gx, gy, gz, dt):
    global _roll, _pitch, _yaw

    # Subtract the estimated gyro bias
    gx -= _bias_gx
    gy -= _bias_gy
    gz -= _bias_gz

    # --- Roll/pitch: accelerometer (absolute) + gyroscope (smooth) ---
    accel_roll = math.degrees(math.atan2(ay, az))
    accel_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

    gyro_roll = _roll + gx * dt
    gyro_pitch = _pitch + gy * dt

    _roll = ALPHA_ROLL_PITCH * gyro_roll + (1 - ALPHA_ROLL_PITCH) * accel_roll
    _pitch = ALPHA_ROLL_PITCH * gyro_pitch + (1 - ALPHA_ROLL_PITCH) * accel_pitch

    # --- Yaw: ONLY integrated gyroscope (no magnetometer -> drift) ---
    _yaw += gz * dt

    return _roll, _pitch, _yaw


def _read_serial_and_update():
    """Runs periodically via bpy.app.timers without blocking the UI."""
    global _ser, _last_time

    if _ser is None:
        return 0.1  # retry in 0.1s

    line = _ser.readline().decode("utf-8", errors="ignore").strip()
    vals = _parse_line(line)
    if vals is None:
        return 0.001  # no new data or corrupt line, retry soon

    ax, ay, az, gx, gy, gz = vals

    now = time.time()
    dt = (now - _last_time) if _last_time is not None else 0.02
    _last_time = now

    roll, pitch, yaw = _complementary_filter(ax, ay, az, gx, gy, gz, dt)

    obj = bpy.data.objects.get(OBJECT_NAME)
    if obj:
        # 1) Per-source sign (per mounting). 2) Permutation to Blender axes.
        sources = {
            "roll": SIGN_ROLL * roll,
            "pitch": SIGN_PITCH * pitch,
            "yaw": SIGN_YAW * yaw,
        }
        (src_x, sg_x), (src_y, sg_y), (src_z, sg_z) = AXIS_MAP
        obj.rotation_euler = (
            math.radians(sg_x * sources[src_x]),
            math.radians(sg_y * sources[src_y]),
            math.radians(sg_z * sources[src_z]),
        )

    return 0.001  # continuous polling


# ---------- CONTROL / UTILITIES ----------
def recenter_yaw():
    """Set the current yaw to 0 (cancels accumulated gyro drift)."""
    global _yaw
    _yaw = 0.0
    _log("Yaw recentered to 0.")


def recenter_all():
    """Set roll/pitch/yaw to 0."""
    global _roll, _pitch, _yaw
    _roll = _pitch = _yaw = 0.0
    _log("Roll/pitch/yaw recentered to 0.")


def start_bridge():
    _open_serial()
    if _ser is not None:
        _calibrate_gyro_bias()
    if not bpy.app.timers.is_registered(_read_serial_and_update):
        bpy.app.timers.register(_read_serial_and_update)
    _log("Bridge started. Move the sensor to see the object react.")
    _log("If yaw drifts, call recenter_yaw().")
    if LOG_TO_TEXT:
        _log(f"These messages are also in the '{LOG_TEXT_NAME}' text "
             f"datablock — open a Text Editor or call show_log().")


def stop_bridge():
    global _ser, _last_time
    if bpy.app.timers.is_registered(_read_serial_and_update):
        bpy.app.timers.unregister(_read_serial_and_update)
    if _ser is not None:
        _ser.close()
        _ser = None
    _last_time = None
    _log("Bridge stopped.")


# When running the script directly in Blender, start the bridge.
if __name__ == "__main__":
    start_bridge()

# To stop it manually from Blender's Python console:
#   stop_bridge()
