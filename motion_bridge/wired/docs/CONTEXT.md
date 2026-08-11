# Context: Arduino (MPU-6050) → Blender bridge

## Goal
Capture orientation (roll/pitch/yaw) from an Arduino motion sensor and apply
it in real time to an object in Blender, over serial USB.

## Real hardware
- **Board: Arduino Nano** (ATmega328P @ 16 MHz, 5V), FQBN
  `arduino:avr:nano`. Identified from the build photos, 2026-08-10.
  > Clones normally ship the old bootloader: if `upload` fails with
  > `not in sync`, use `arduino:avr:nano:cpu=atmega328old`.
  >
  > **The port is not `/dev/cu.usbmodem*`.** That name belongs to a board
  > with native USB; the Nano goes through a USB-serial chip, so it shows up
  > as `/dev/cu.wchusbserial*` (CH340) or `/dev/cu.usbserial-*` (FTDI).
  > Find it with `ls /dev/cu.*` with the board unplugged and plugged in, and
  > put it in `blender/config.env`. **Not yet known** — nothing has been
  > connected since the board was identified.
  >
  > The 2026-07-13 diagnostics below were logged against an **Arduino Uno**
  > at `/dev/cu.usbmodem11201`, which is also what `backups/` was dumped
  > from. Same MCU, same 5V I2C, so the sketch carries over untouched — but
  > nothing has been re-run on the Nano yet.
- **Sensor: MPU-6050** on a GY-521 breakout (6 axes: accel + gyro), wired
  over I2C with 4 leads (VCC, GND, SDA→A4, SCL→A5). Confirmed by WHO_AM_I
  = `0x68` (`0x71` would be an MPU9250), I2C diagnostics 2026-07-13.
  **It has NO magnetometer.**
  > Note: the initial plan assumed an MPU9250 with an AK8963 magnetometer.
  > The I2C diagnostics proved the real chip is an MPU-6050 (very common:
  > cheap "MPU9250" modules that are relabeled 6050s).
- **Clone quirk**: the accelerometer did NOT start in the default ±2g range
  (magnitude at rest ~0.27g instead of ~1g). Fixed by explicitly writing
  `ACCEL_CONFIG` (0x1C) and `GYRO_CONFIG` (0x1B) in the sketch. After the
  fix, |accel| ≈ 1.0g.
- Connection: USB cable, serial at 115200 baud, CSV ~50 Hz.

## Enclosure
Both boards live in a 3D-printed box, screwed down, with the USB cable
coming out of one end. The box has **space reserved for two things that are
not there yet**: a Bluetooth module and a battery. Neither is bought,
wired or accounted for in this code — see "Going untethered" below for what
each would cost in changes.

## Going untethered (not built)
Nothing here is required for the current USB setup. Written down so the
reserved space is designed against something real.

### Bluetooth (the reserved slot)
An **HC-05/HC-06** is a transparent UART: the Blender side does not change
at all, it is a new `SERIAL_PORT` in `config.env` pointing at the port
macOS creates when the module is paired. What changes is on the board:

- **Where it hangs.** On USB power the hardware UART (D0/D1) is taken by
  the USB-serial chip, so the module needs `SoftwareSerial` on two free
  pins (D2/D3, as in `wifi/firmware/mpu_wifi_avr_esp01/`). On battery there
  is no USB, so D0/D1 are free and `Serial` can drive the module directly
  at 115200 — **but the module must be unplugged from D0/D1 to flash**.
- **Baud is the rate ceiling.** A CSV line here is ~45 bytes, so 9600 baud
  (the HC-05 factory default) caps the stream at ~20 Hz, below the current
  ~50 Hz. Raise the module to 38400 with `AT+UART` and the `delay(20)` in
  the sketch stays honest.
- **Levels.** The module's RX is 3.3V and the Nano's TX is 5V: series
  1 kΩ + 2 kΩ to GND, same divider the ESP-01 notes describe.

A **BLE** module (HM-10, AT-09) is a different problem: macOS creates no
serial port for it, so `pyserial` cannot see it. That path needs a small
external relay (`bleak`) forwarding into `wifi/`'s UDP bridge, not this one.

### Battery (the other reserved slot)
The trap is the Nano's regulator, not the current draw (board + MPU is
~40 mA, a BT module adds ~30 mA):

- **`VIN` needs ≥ 7V** to give a stable 5V through the on-board regulator.
  A single 3.7V LiPo into `VIN` does **not** work; 4×AA (6V) is marginal.
- The working options are a 9V battery into `VIN` (simple, wasteful), or a
  3.7V LiPo plus a boost module feeding the **`5V` pin directly**,
  bypassing the regulator. The second is what a wearable wants.
- Never feed both USB and `VIN` while experimenting.

## Scope
- **Roll and pitch**: absolute and stable (gravity reference via
  accelerometer + gyroscope, complementary filter). Work well.
- **Yaw**: integrated gyroscope ONLY → **drifts** over time (no magnetometer
  to correct it). Mitigated by calibrating the gyro bias at startup + the
  `recenter_yaw()` function to zero it.
- **Position**: out of scope (would require double integration of
  acceleration, with unacceptable drift without an external reference).

## Files
- `firmware/mpu_serial_bridge/mpu_serial_bridge.ino` — Main sketch. Reads
  accel+gyro from the MPU-6050 over I2C and sends them over Serial as CSV:
  `ax,ay,az,gx,gy,gz` (accel in g, gyro in deg/s). Sets the ranges
  explicitly (±2g / ±250°/s).
- `firmware/i2c_diag/i2c_diag.ino` — Diagnostic sketch (moves nothing). Scans
  the I2C bus and reads the WHO_AM_I registers. Useful to re-validate the
  hardware if something stops working. Repeats in loop() every 3s.
- `blender/blender_serial_bridge.py` — Script to run inside Blender. Reads
  the 6-value CSV, fuses accel+gyro for roll/pitch and integrates the
  gyroscope for yaw, and updates the object's rotation.
- `blender/config.env` — **The only file to touch when changing PC/scene.**
  `KEY=value` format (.env style) read with no external dependencies
  (Blender's Python has no python-dotenv). Contains `SERIAL_PORT`,
  `OBJECT_NAME`, `ALPHA_ROLL_PITCH`, axis signs, etc. The script looks it up
  via the `WIRED_BRIDGE_CONFIG` env var, then next to the script, then in
  the cwd; if not found it uses internal default values.
- `tools/read_serial.py` — Diagnostic serial reader (system Python, with
  pyserial). Resets the board via DTR and dumps N seconds of lines. To
  validate raw data without depending on Blender.
- `backups/` — Flash and EEPROM dumped from the **Uno** on 2026-07-13
  (`flash_backup_*.hex`, `eeprom_backup_*.hex`), in case the program that
  board originally shipped with needs restoring. They are not the Nano's:
  do not flash them onto it.

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

## How to test (steps 1-2 validated on the Uno, not yet re-run on the Nano)
Toolchain: `arduino-cli` (no IDE), `arduino:avr` core installed.

0. Find the port. With the board unplugged and then plugged in:
   ```
   ls /dev/cu.*        # look for wchusbserial* (CH340) or usbserial-* (FTDI)
   ```
   Everything below uses `$PORT` for whatever that turns out to be.
1. Compile/flash the sketch:
   ```
   arduino-cli compile --fqbn arduino:avr:nano firmware/mpu_serial_bridge
   arduino-cli upload -p $PORT --fqbn arduino:avr:nano firmware/mpu_serial_bridge
   ```
   If the upload fails with `not in sync` / `stk500_recv`, the clone has the
   old bootloader: append `:cpu=atmega328old` to **both** FQBNs.
2. Verify the raw CSV (6 values, |accel|≈1g at rest):
   ```
   /usr/bin/python3 tools/read_serial.py $PORT 6 115200
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
- [ ] **Re-run steps 0-2 on the Nano**: find the port, flash with the `nano`
      FQBN, confirm the CSV. Nothing else should need touching — the sketch
      is plain ATmega328P.
- [ ] Put the real port in `blender/config.env` (`SERIAL_PORT`), which holds
      a `CHANGE_ME` placeholder until the board is plugged in once.
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
The hardware pipeline is validated end-to-end up to the raw CSV, **on the
Uno**. The board in the enclosure is a Nano; same MCU, so the change is
confined to the FQBN and the port name, but it has not been run yet. What
remains after that is testing inside Blender and calibrating the axis
mapping, which depends on how the sensor is physically mounted.
