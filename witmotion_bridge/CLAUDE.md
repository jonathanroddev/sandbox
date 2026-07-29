# Guide for Claude Code — witmotion_bridge

Quick context to work on this project with the hardware connected. Also read
`docs/CONTEXT.md` for the detail of decisions and protocol.

## What this is
WiFi bridge from **WitMotion WT901WIFI** sensor(s) to **Blender**. The sensor
delivers already-fused angles (internal Kalman) over UDP; the receiver parses
them by DeviceID, calibrates them against a reference pose (in quaternions)
and moves scene objects. Sibling of `../blender_bridge/` (the Arduino+MPU
serial version).

## Repo rules (inherited from sandbox)
- Each project is a self-contained top-level folder.
- **All configuration lives in `blender/config.env`** (KEY=value format, no
  quotes, read without external dependencies). Do not hardcode paths, ports
  or object names in the code.
- Comments and user-facing messages **in English**.
- Blender code must not block the UI: use `bpy.app.timers`.
- The bridge uses **only the standard library + `mathutils`** (ships with
  Blender). Do not add dependencies without justifying it.

## Current status
- `blender/blender_udp_bridge.py` — working UDP receiver: parsing by
  DeviceID, pose calibration with quaternions, sensor→object mapping,
  utilities (`calibrate`, `recenter`, `list_devices`, `start/stop_bridge`).
- `blender/config.env` — port, `DEVICE_MAP`, auto-calibration, axis signs,
  and the CSV field indices (`IDX_*`).
- `tools/read_udp.py` — UDP diagnostics outside Blender.

## Known uncertainty (resolve first, with the sensor in hand)
1. **Exact CSV format.** The field indices (`IDX_ANGLE_X/Y/Z=7,8,9` and
   `IDX_DEVICE=0`) come from the product documentation, but may vary with the
   firmware. Run `python3 tools/read_udp.py 1399 10`, look at the real lines,
   and adjust the `IDX_*` in `config.env` if needed. Do NOT change the code
   for this: change the config.
2. **Sensor vs Blender axis frame.** The sensor uses Z-Y-X Euler order and
   its own frame; Blender is Z-up. The initial mapping is direct with
   configurable signs. Verify by moving the sensor one axis at a time and
   adjust `SIGN_ROLL/PITCH/YAW` or the order in `_angles_to_quat()`.

## Suggested tasks (in order)
1. **Validate reception**: `tools/read_udp.py`; confirm DeviceID, field count
   and angle positions. Adjust `config.env` if appropriate.
2. **One sensor in Blender**: point `DEFAULT_OBJECT` at the scene object, Run
   Script, auto-calibrate in the reference pose, check axes/directions.
3. **Fine-tune the axis mapping** until the object faithfully follows the
   sensor.
4. **Multi-sensor**: with several sensors emitting, `list_devices()` to see
   the DeviceIDs and fill `DEVICE_MAP` (DeviceID:Object).
5. **Map to an armature**: evolve from loose objects to `pose.bones[...]`,
   resolving each bone's orientation relative to its parent. This is the
   heart of the suit.
6. **Optional**: if the firmware includes a native quaternion in the frame,
   use it instead of converting from Euler (avoids order ambiguity).

## Testing without hardware
`tools/fake_sensor.py` is a fake UDP emitter that mimics the WT901WIFI: it
sends CSV frames with the default layout (13 fields, animated angles) to the
port in `config.env`. Use it to validate parsing and calibration before
having the sensor on the network, and as a reference to compare the real
sensor against when it connects.

    # Terminal 1: check frames arrive and their format
    python3 tools/read_udp.py 1399 3
    # Terminal 2: emit (one sensor, indefinite)
    python3 tools/fake_sensor.py
    # Multi-sensor test (two DeviceIDs, 100 Hz):
    python3 tools/fake_sensor.py 1399 0 100 127.0.0.1 WT53abc,WT53def

In Blender: Run Script the bridge and, in parallel, launch `fake_sensor.py`
-> the `DEFAULT_OBJECT`/`DEVICE_MAP` object should oscillate. Verified
end-to-end (fake_sensor -> read_udp): 13 fields, DeviceID at index 0, angles
at 7/8/9, consistent with the `IDX_*`.

Note: the emitter reproduces the documented DEFAULT layout. When the REAL
sensor arrives, if `read_udp.py` shows a different order/field count, it is
adjusted in `config.env` (`IDX_*`), not in the code.
