# Context: the two Blender motion bridges

Shared architecture and the decisions behind it. Hardware specifics live in
each subproject's `docs/CONTEXT.md`; the frame format lives in
[`PROTOCOL.md`](PROTOCOL.md).

## Goal
Capture orientation (roll/pitch/yaw) from IMU sensors and apply it in real
time to Blender objects. Position is **out of scope**: recovering it would
mean double-integrating acceleration, whose drift is unacceptable without
an external reference.

The long-term target is a **multi-sensor motion capture suit**, which is why
`wifi/` treats "several sensors" as the normal case rather than an
extension.

## The two paths

| | `wired/` | `wifi/` |
|---|---|---|
| Transport | USB serial, 115200 baud | UDP over 2.4 GHz WiFi |
| Frame | `ax,ay,az,gx,gy,gz` (no id — the cable *is* the id) | `deviceId,...` (see PROTOCOL.md) |
| Sensor fusion | Here, complementary filter | Here for `raw6`; in the sensor for the WT901WIFI |
| Multi-sensor | No | Native: one socket, routed by DeviceID |
| Zeroing | `recenter_yaw()` / `recenter_all()` (Euler) | `calibrate()` / `recenter(id)` (quaternion) |
| Dependencies | `pyserial` in Blender's Python | None |

## Decisions

### 1. Fusion in Python, not on the board
The boards only read the IMU and send raw values; roll/pitch/yaw are
computed in Blender. The filter can then be iterated without reflashing
anything — and with a suit, without reflashing *N* boards. The WT901WIFI is
the exception: it fuses internally with its own Kalman filter and there is
no way to get raw-only from it, so we take its angles as given.

### 2. Complementary filter, not Madgwick/Mahony
Simpler to understand and debug, which matters more than optimality in a
first version. It can be swapped for a 6-axis Madgwick (the `ahrs` library)
if fast turns turn out to look unstable.

### 3. Yaw drift is accepted on MPU-6050 hardware
The MPU-6050 has **no magnetometer**, so yaw has no absolute reference: it
is integrated gyro and drifts. Mitigated by estimating the gyro bias at
startup (the sensor must be still) and by re-zeroing on demand. The
WT901WIFI does not have this problem (9 axes, absolute heading).

### 4. UDP, never TCP
Lower latency, and a lost packet is simply dropped in favour of the next
one. TCP would retransmit an already-stale pose and deliver it late, which
is worse than not delivering it. (The WT901WIFI manual's advice to
"configure UDP first" is unrelated — it is about not losing the connection
during the AP→Station switch.)

### 5. Sensor ranges written explicitly in every sketch
The MPU-6050 clone in this project did **not** boot in the default ±2g
range (it read ~0.27g at rest instead of ~1g). Every sketch writes
`ACCEL_CONFIG` (0x1C) and `GYRO_CONFIG` (0x1B) explicitly rather than
trusting defaults.

### 6. Axis mapping is configuration, not code
How a sensor is physically mounted decides which of its axes drives which
Blender axis. Two knobs in `config.env`, applied in order:

- `SIGN_ROLL/PITCH/YAW` — invert the **direction** of a source.
- `AXIS_MAP` — **permute** which source drives Blender's X, Y, Z.

Signs cannot fix a permutation, which is why both exist. The symptom "I
move one axis and *another* one responds" is always `AXIS_MAP`. Same
mechanism, same syntax, in both projects.

### 7. Calibration: Euler zeroing when wired, quaternion pose when WiFi
`wired/` zeroes accumulated angles (`recenter_yaw`). `wifi/` captures each
sensor's current orientation as a reference pose and applies its inverse —
quaternions, so no gimbal lock, all three axes at once, and one uniform
procedure for every sensor of a suit (strike the T-pose, `calibrate()`).

### 8. Frame indices are configuration
Firmware revisions shuffle CSV layouts. The receiver addresses fields
through `IDX_*` in `config.env`. A layout difference is **never** fixed by
patching the parser.

## Why two scripts and not one shared package
A Blender script that imports a sibling package needs `sys.path` surgery,
and inside Blender's Text Editor `__file__` frequently does not exist —
the same reason `config.env` was once not found even when sitting right
next to the script. Every extra import is another way for that to break on
a machine you are not sitting at. So each bridge is **one self-contained
file** that you open and run, and the shared pieces (config loader,
`_parse_axis_map`, the complementary filter) are deliberately duplicated.

The duplication is bounded and it is the price of a script that always
runs. If it ever stops being bounded, the answer is a proper Blender
add-on, not a loose package next to the script.

## How the pieces are validated without hardware
`wifi/tools/fake_sensor.py` emits UDP frames that are physically consistent:
the accelerometer carries gravity projected onto the simulated attitude and
the gyro carries its derivative. Feeding them back through the bridge's
filter therefore has to return the attitude they were generated from — that
makes it a test, not just a traffic generator.

Verified this way (2026-08-03), outside Blender with `bpy`/`mathutils`
stubbed: profile detection, axis mapping, `raw6` fusion (roll/pitch recover
the source attitude to within 0.3°), routing two devices with different
profiles through one socket, pose calibration, and resilience to malformed
datagrams.

## Status
- `wired/`: hardware validated end to end up to the raw CSV. Pending: the
  end-to-end test **inside Blender** and calibrating the axis mapping.
- `wifi/`: software validated end to end. Pending: everything with real
  hardware — see `wifi/docs/SETUP_WT901WIFI.md` and
  `wifi/docs/SETUP_ARDUINO_WIFI.md`.
