# Context: the WiFi (UDP) bridge

Decisions specific to this bridge. The shared architecture (fusion in
Python, UDP over TCP, axis mapping as configuration…) lives in
[`../../docs/CONTEXT.md`](../../docs/CONTEXT.md); the frame format in
[`../../docs/PROTOCOL.md`](../../docs/PROTOCOL.md).

## Goal
Receive orientation from one or more WiFi sensors and apply it in real time
to Blender objects. Multi-sensor is the design centre, not an add-on: the
target is a motion capture suit.

## The sensors

### WitMotion WT901WIFI
- MPU9250-based (accel + gyro + magnetometer) with its own MCU running
  WitMotion's Kalman filter; delivers low-drift attitude, **absolute
  heading included**.
- 2.4 GHz WiFi, up to 200 Hz, UDP or TCP (pick one — we use UDP).
- Several devices on one network, each with its own DeviceID.
- Internal battery, ~3 h depending on data rate.
- Emits the **`fused`** profile: 13 fields including angles.

### Arduino Uno + ESP-01 (ESP8266)
- The "use the Uno we already have" option. Works, but it is the weakest
  path: 3.3V logic needing level shifting, a module whose current peaks the
  Uno's regulator cannot supply, and AT commands over SoftwareSerial
  capping the rate at roughly 20 Hz.
- Emits the **`raw6`** profile: this board does no fusion.

### ESP32 (or ESP8266 D1 mini) + MPU-6050
- Native WiFi, 3.3V I2C straight to the MPU, no intermediary: 100 Hz is
  comfortable. For a suit — several boards, each battery-powered — this is
  the sane choice, and it is cheaper than an Uno plus a module.
- Also emits **`raw6`**.

## Decisions

1. **One receiver for every sensor type.** The alternative — a script per
   sensor — would have meant maintaining calibration, mapping and
   multi-device routing three times. Instead the frame's field count picks
   the profile, and everything downstream is shared. Adding a fourth sensor
   type means teaching the parser one profile, not writing a bridge.

2. **`raw6` is a prefix of the WitMotion layout.** Deliberate: one set of
   `IDX_*` config keys addresses both, and a longer future profile (a
   native quaternion appended at the end) will not disturb either.

3. **Fusion state is per device.** Each `raw6` sensor keeps its own gyro
   bias, its own integrated attitude and its own timestamps. Sharing them
   would have coupled sensors that are physically independent — with a
   suit, one arm's motion would pollute another's.

4. **Gyro bias is estimated per device at startup**, over
   `GYRO_CALIB_SAMPLES` frames, during which that sensor produces no
   output. An unremoved bias integrates directly into yaw drift, so this is
   worth the wait. Consequence: `CALIB_COUNTDOWN` must be long enough to
   outlast it (50 frames at 20 Hz = 2.5 s).

5. **Roll/pitch are seeded from the accelerometer** on the first fused
   frame rather than starting from zero, which otherwise gives a visible
   second of the object crawling from "flat" to the real attitude.

6. **Reference-POSE calibration in software, with quaternions.** Each
   sensor's orientation at calibration time is captured as "zero" and its
   inverse applied afterwards. Chosen over the WT901WIFI's own "Z-axis zero
   return" because it:
   - calibrates all three axes, not just yaw;
   - works identically for every sensor of the suit, whatever its type;
   - does not force the sensor into 6-axis mode (which would reintroduce
     yaw drift); the absolute 9-axis heading is preserved;
   - uses quaternions, so no gimbal lock and "zeroing" is a multiplication.

7. **Sensor→object mapping by DeviceID** (`DEVICE_MAP`), with a `*`
   wildcard so a single test sensor needs no configuration at all.

## Files
- `blender/blender_udp_bridge.py` — the receiver. Parses both profiles,
  fuses `raw6` per device, applies the axis map, the calibration offset and
  the resulting quaternion to the object.
- `blender/config.env` — everything configurable.
- `firmware/mpu_wifi_esp32/`, `firmware/mpu_wifi_uno_esp01/` — the two
  Arduino-family senders. Each needs a `secrets.h` (copy the example).
- `tools/read_udp.py` — dump raw frames outside Blender. Always the first
  thing to run when something is silent.
- `tools/fake_sensor.py` — emitter of physically consistent fake frames, in
  either profile, for testing with no hardware.

## Pending / next steps
- [ ] Flash and validate a real board (`docs/SETUP_ARDUINO_WIFI.md`).
- [ ] Connect the WT901WIFI and **confirm its real CSV layout**
      (`docs/SETUP_WT901WIFI.md`); the `IDX_*` come from documentation, not
      from observation.
- [ ] **Calibrate the axis mapping** with each sensor mounted the way it
      will sit on the suit.
- [ ] **Multi-sensor with real devices**: `list_devices()` → `DEVICE_MAP`.
- [ ] **Map to an armature**: apply each quaternion to the corresponding
      `pose.bones[...]`, resolving each bone's orientation relative to its
      parent. This is the heart of the suit.
- [ ] Measure the Uno + ESP-01's real rate; decide whether it is usable or
      whether the suit is ESP32-only.
- [ ] Use the WT901WIFI's **native quaternion** if its firmware includes one
      (removes the Euler-order ambiguity entirely).
- [ ] Review performance with several sensors at 100–200 Hz (the
      200-datagrams-per-tick cap in `_pump()` is the knob).
