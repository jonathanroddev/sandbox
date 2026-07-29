# Context: WitMotion WT901WIFI → Blender bridge

## Goal
Receive orientation from one or more WitMotion WT901WIFI sensors over WiFi
and apply it in real time to Blender objects. It is the step toward a
multi-sensor motion capture suit.

## Relationship with `blender_bridge/`
This project is a sibling of `blender_bridge/` (the Arduino+MPU bridge over
USB serial). It shares conventions (dependency-free config.env, non-blocking
`bpy.app.timers` pattern, recentering utilities), but changes the transport
and the division of work:

| | blender_bridge (MPU serial) | witmotion_bridge (WT901WIFI) |
|---|---|---|
| Sensor fusion | Done by the script (complementary filter) | Internal to the sensor (Kalman) |
| Transport | USB serial (`pyserial`) | WiFi, UDP socket (stdlib) |
| Data received | Raw accel+gyro | Already-fused angles + DeviceID |
| Multi-sensor | Awkward | Native (one socket, several DeviceIDs) |
| Zeroing | `recenter_yaw()` (yaw only) | `calibrate()` (full pose, quaternion) |

## The sensor: WT901WIFI
- Built on an MPU9250 (accel+gyro+magnetometer) with its own MCU running
  WitMotion's Kalman filter; delivers low-drift attitude.
- Transmits over 2.4 GHz WiFi, up to 200 Hz, via UDP or TCP (pick ONE).
- Supports multiple devices on the same network -> ideal for the suit.
- Internal battery (~3 h of runtime depending on data rate).

## Architecture decisions made
1. **UDP, not TCP.** Lower latency; if a packet is lost it is dropped and
   the next one is used, instead of retransmitting an already-stale pose.
   For motion capture streaming this is standard. (There is no "UDP and then
   TCP" chain: it's a single transport; the manual's "configure in UDP
   first" is only to avoid losing the connection on the AP→Station switch.)
2. **Fusion is already done by the sensor.** No filtering here: we parse,
   calibrate and apply. The script is substantially simpler than the MPU's.
3. **Reference-POSE calibration, in software, with quaternions.** At startup
   (or when calling `calibrate()`) each sensor's orientation is captured as
   "zero" and its inverse is applied to the readings. Advantages over the
   sensor's "Z-axis zero return":
   - Calibrates all three axes, not just yaw.
   - Uniform for all sensors in the suit.
   - Does not force 6-axis mode (which reintroduces yaw drift); the absolute
     9-axis yaw is preserved.
   - Quaternions -> no gimbal lock; "zero" is a multiplication.
4. **Sensor→object mapping by DeviceID** (config.env `DEVICE_MAP`), with a
   `*` wildcard for the single-test-sensor case.

## Files
- `blender/blender_udp_bridge.py` — UDP receiver to run inside Blender.
  Parses by DeviceID, calibrates against a reference pose and moves the
  objects via `rotation_quaternion`.
- `blender/config.env` — All configuration (port, sensor mapping,
  calibration, axis signs, CSV field indices).
- `tools/read_udp.py` — UDP diagnostic reader (outside Blender), to validate
  the real frame format before touching Blender.
- `tools/fake_sensor.py` — Fake UDP emitter mimicking the WT901WIFI (default
  layout, animated angles). Lets you test parsing/calibration and the whole
  flow in Blender WITHOUT the sensor on the network, and serves as a
  reference to compare the real sensor against once it connects.

## Sensor setup (one-off)
1. With the WitMotion app/PC tool, configure the WT901WIFI in **Station
   mode** so it joins your router. Manual recommendation: when migrating
   from AP mode, switch to **UDP** first (not straight to TCP), or you may
   lose the connection and have to reset (2 s button) or reconfigure over
   serial.
2. Set the **user server IP** = your Mac's IP on the LAN, and the **port** =
   the same `LISTEN_PORT` from config.env (1399 by default).
3. Make sure the Mac and the sensor are on the SAME WiFi network.

## How to test (recommended order)
1. **Validate frames WITHOUT Blender:**
       python3 tools/read_udp.py 1399 10
   Check that lines arrive, that they start with the DeviceID and how many
   fields they have. If the angle order is not 7,8,9, adjust the
   `IDX_ANGLE_*` in config.env.
2. **Install nothing** (the bridge uses only stdlib + Blender's mathutils).
3. **In Blender:** set `DEVICE_MAP`/`DEFAULT_OBJECT` to the scene object,
   open `blender/blender_udp_bridge.py` in Scripting and Run Script. With
   `AUTO_CALIBRATE=1`, place the sensor in the reference pose during the
   initial countdown.
4. Move the sensor and verify the object rotates on the correct axis and
   direction. If some axis is inverted or crossed, adjust `SIGN_*` (or the
   Euler order in `_angles_to_quat`).

## Pending / next steps
> Step-by-step operational guide for the hardware: `SETUP_HARDWARE.md`.
> Software validated end-to-end (fake_sensor → read_udp) on 2026-07-20;
> what remains is everything with the real sensor and in Blender.
- [ ] **Verify the real CSV format** with `read_udp.py` and confirm the
      field indices (the layout may vary with the firmware).
- [ ] **Calibrate the axis mapping** sensor→Blender with the sensor mounted
      as it will sit on the suit (sensor frame vs Blender's Z-up).
- [ ] **Multi-sensor jump:** list the real DeviceIDs (`list_devices()`) and
      fill `DEVICE_MAP` with the assignment to bones/objects. The receiver
      already supports several sensors unchanged.
- [ ] **Map to an armature:** instead of loose objects, apply each
      quaternion to the corresponding `pose.bones[...]`, resolving the
      hierarchy (bone orientation relative to the parent).
- [ ] Evaluate using the sensor's **native quaternion** if the firmware
      includes it in the frame (avoids the Euler→quat conversion and its
      order).
- [ ] Review performance with several sensors at 100–200 Hz (the 200
      datagrams/tick cap in `_pump` is adjustable).

## Notes for Claude Code
See `../CLAUDE.md` at the project root for the task list and the suggested
order of work with the hardware connected.
