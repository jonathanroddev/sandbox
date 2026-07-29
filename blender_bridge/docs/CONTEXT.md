# Context: Arduino (MPU-6050) → Blender bridge

## Goal
Capture orientation (roll/pitch/yaw) from an Arduino motion sensor and apply
it in real time to an object in Blender, over serial USB.

## Real hardware (VALIDATED by diagnostics, 2026-07-13)
- **Board: Arduino Uno**, detected at `/dev/cu.usbmodem11201`,
  FQBN `arduino:avr:uno`.
- **Sensor: MPU-6050** (6 axes: accel + gyro). Confirmed by WHO_AM_I
  = `0x68` (`0x71` would be an MPU9250). **It has NO magnetometer.**
  > Note: the initial plan assumed an MPU9250 with an AK8963 magnetometer.
  > The I2C diagnostics proved the real chip is an MPU-6050 (very common:
  > cheap "MPU9250" modules that are relabeled 6050s).
- **Clone quirk**: the accelerometer did NOT start in the default ±2g range
  (magnitude at rest ~0.27g instead of ~1g). Fixed by explicitly writing
  `ACCEL_CONFIG` (0x1C) and `GYRO_CONFIG` (0x1B) in the sketch. After the
  fix, |accel| ≈ 1.0g.
- Connection: USB cable, serial at 115200 baud, CSV ~50 Hz.

## Scope
- **Roll and pitch**: absolute and stable (gravity reference via
  accelerometer + gyroscope, complementary filter). Work well.
- **Yaw**: integrated gyroscope ONLY → **drifts** over time (no magnetometer
  to correct it). Mitigated by calibrating the gyro bias at startup + the
  `recenter_yaw()` function to zero it.
- **Position**: out of scope (would require double integration of
  acceleration, with unacceptable drift without an external reference).

## Files
- `arduino/mpu_serial_bridge/mpu_serial_bridge.ino` — Main sketch. Reads
  accel+gyro from the MPU-6050 over I2C and sends them over Serial as CSV:
  `ax,ay,az,gx,gy,gz` (accel in g, gyro in deg/s). Sets the ranges
  explicitly (±2g / ±250°/s).
- `arduino/i2c_diag/i2c_diag.ino` — Diagnostic sketch (moves nothing). Scans
  the I2C bus and reads the WHO_AM_I registers. Useful to re-validate the
  hardware if something stops working. Repeats in loop() every 3s.
- `blender/blender_serial_bridge.py` — Script to run inside Blender. Reads
  the 6-value CSV, fuses accel+gyro for roll/pitch and integrates the
  gyroscope for yaw, and updates the object's rotation.
- `blender/config.env` — **The only file to touch when changing PC/scene.**
  `KEY=value` format (.env style) read with no external dependencies
  (Blender's Python has no python-dotenv). Contains `SERIAL_PORT`,
  `OBJECT_NAME`, `ALPHA_ROLL_PITCH`, axis signs, etc. The script looks it up
  via the `BLENDER_BRIDGE_CONFIG` env var, then next to the script, then in
  the cwd; if not found it uses internal default values.
- `tools/read_serial.py` — Diagnostic serial reader (system Python, with
  pyserial). Resets the board via DTR and dumps N seconds of lines. To
  validate raw data without depending on Blender.
- `backups/` — Backup of the Uno's original flash and EEPROM
  (`flash_backup_*.hex`, `eeprom_backup_*.hex`), in case the program the
  board originally shipped with needs restoring.

## Architecture decisions made
1. **Sensor fusion in Python (Blender), not on the Arduino.** The algorithm
   can be iterated without reflashing; the Arduino only reads and sends raw.
2. **Complementary filter** (not Madgwick/Mahony) for roll/pitch in this
   first version: simpler to understand/debug. Can be swapped later for a
   6-axis Madgwick (the `ahrs` library) if needed.
3. **Yaw from the gyroscope, accepting the drift** (explicit user choice).
   Alternatives dropped for now: roll/pitch only, or yaw with auto-recenter
   (high-pass). Without a magnetometer no absolute heading is possible with
   this hardware.
4. **Sensor ranges set explicitly** in the sketch, after discovering the
   clone did not honor the ±2g default.
5. **Flat CSV over serial**, one line per reading, ~50 Hz.

## How to test (validated through step 2)
Toolchain: `arduino-cli` (no IDE), `arduino:avr` core installed.

1. Compile/flash the sketch:
   ```
   arduino-cli compile --fqbn arduino:avr:uno arduino/mpu_serial_bridge
   arduino-cli upload -p /dev/cu.usbmodem11201 --fqbn arduino:avr:uno arduino/mpu_serial_bridge
   ```
2. Verify the raw CSV (6 values, |accel|≈1g at rest):
   ```
   /usr/bin/python3 tools/read_serial.py /dev/cu.usbmodem11201 6 115200
   ```
3. Install `pyserial` into **Blender's** Python:
   ```
   /Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial
   ```
4. Adjust `blender/config.env` (NO need to touch the .py):
   - `SERIAL_PORT` (on Linux/Windows it differs: `/dev/ttyACM0`, `COM3`...).
   - `OBJECT_NAME` (the scene object to move).
5. Open the script in Blender's Scripting tab and Run Script. Keep the
   sensor still ~1s at startup (gyro bias calibration).

## Status / next steps
- [x] arduino-cli toolchain + AVR core installed.
- [x] Hardware identified (MPU-6050) and I2C communication validated.
- [x] 6-value CSV streaming, accelerometer scaled correctly.
- [x] Sketch and Blender bridge adapted to 6 axes.
- [ ] Test the bridge end-to-end inside Blender (move the object).
- [ ] Axis calibration: map the sensor axes to Blender's according to the
      physical mounting (adjust `SIGN_ROLL/PITCH/YAW` or the axis order via
      `AXIS_MAP`).
- [ ] Tune `ALPHA_ROLL_PITCH` if it looks jittery (lower) or slow (raise).
- [ ] (Optional) Evaluate 6-axis Madgwick (the `ahrs` library) if the motion
      looks unstable on fast turns.
- [ ] (Optional) Map a Blender key to `recenter_yaw()`.
- [ ] (Optional, hardware) If absolute heading ever matters, an external
      magnetometer would be needed (e.g. HMC5883L/QMC5883L over I2C) — the
      MPU-6050 doesn't have one.

## Notes for Claude Code
The hardware pipeline is validated end-to-end up to the raw CSV. What
remains is testing it inside Blender and calibrating the axis mapping, which
depends on how the sensor is physically mounted.
