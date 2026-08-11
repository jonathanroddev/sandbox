# wired — Arduino (MPU-6050) → Blender, over USB serial

Real-time bridge that reads orientation from an **MPU-6050** motion sensor
wired to an **Arduino Nano** over USB and applies it to an object in a
**Blender** scene (roll/pitch/yaw).

- **Roll and pitch**: absolute and stable (accelerometer + gyroscope with a
  complementary filter; gravity reference).
- **Yaw**: integrated gyroscope only → drifts slowly (the MPU-6050 has no
  magnetometer). Reset manually with `recenter_yaw()`.
- **Position**: out of scope.

Full technical context and architecture decisions: [`docs/CONTEXT.md`](docs/CONTEXT.md).
The shared frame protocol and how this bridge relates to the WiFi one:
[`../docs/CONTEXT.md`](../docs/CONTEXT.md).

## Layout

```
wired/
├── firmware/
│   ├── mpu_serial_bridge/   Main sketch: reads accel+gyro and emits CSV
│   └── i2c_diag/            I2C diagnostics (WHO_AM_I, bus scan)
├── blender/
│   ├── blender_serial_bridge.py   Script to run INSIDE Blender
│   └── config.env                 The ONLY file you usually touch
├── tools/
│   └── read_serial.py       Serial diagnostic dump (system Python)
├── backups/                 The Uno's original flash/EEPROM (see docs)
└── docs/                    Context and hardware setup
```

The sensor sends one CSV line per reading over serial (115200 baud, ~50 Hz):

```
ax,ay,az,gx,gy,gz        # accel in g, gyro in deg/s
```

## Setup

### 1. Flash the Arduino

With `arduino-cli` (the `arduino:avr` core installed):

```bash
arduino-cli compile --fqbn arduino:avr:nano firmware/mpu_serial_bridge
arduino-cli upload -p $PORT --fqbn arduino:avr:nano firmware/mpu_serial_bridge
```

If the upload fails with `not in sync` / `stk500_recv`, the clone has the
old bootloader: use `arduino:avr:nano:cpu=atmega328old` in **both** lines.

Find `$PORT` on your system. The Nano talks through a USB-serial chip, so
it is **not** a `usbmodem` name:
- macOS: `ls /dev/cu.*` → `/dev/cu.wchusbserial*` (CH340) or
  `/dev/cu.usbserial-*` (FTDI). List it unplugged and plugged in to be sure.
- Linux: `ls /dev/ttyUSB*` → e.g. `/dev/ttyUSB0`
- Windows: Device Manager → e.g. `COM3`

### 2. Verify the raw CSV (without Blender)

With the **system Python** (needs `pyserial`):

```bash
python3 tools/read_serial.py $PORT 6 115200
```

You should see 6 values per line and, with the sensor still, `|accel| ≈ 1.0 g`.

### 3. Install `pyserial` into BLENDER's Python

Blender ships its **own** Python interpreter; `pyserial` must be installed
there, not into the system one. Find its path from Blender's Python console:

```python
import sys; print(sys.exec_prefix)
```

then, from a terminal:

```bash
/Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial
```

(On Linux/Windows the path differs, inside the Blender installation.)

### 4. Configure `blender/config.env`

**No need to edit the `.py`.** Touch only `config.env`:

- `SERIAL_PORT` → your system's port (see step 1).
- `OBJECT_NAME` → EXACT name of the scene object that will be moved.
- The rest (filter, axis mapping): see below.

### 5. Run in Blender

1. **Scripting** tab → **Text Editor** → open
   `blender/blender_serial_bridge.py` from disk (**Open**, don't paste the
   text: that way the script can find the `config.env` sitting next to it,
   see below).
2. **Run Script**.
3. Keep the sensor **still for ~1 s** at startup (it calibrates the gyro bias).
4. Move the sensor and check that the object reacts.

Control from Blender's **Python console**:

```python
start_bridge()    # start (calibrates the gyro bias at rest)
recenter_yaw()    # set the current yaw to 0 (cancels accumulated drift)
recenter_all()    # set roll/pitch/yaw to 0
show_log()        # show the bridge's messages inside Blender
stop_bridge()     # stop and close the port
```

### Seeing the bridge's messages

`print()` inside Blender goes to the **system console**, which you only see
if you launched Blender from a terminal (on Windows: Window → Toggle System
Console). Everything is therefore **also mirrored into a Text datablock**:
open a Text Editor and pick `wired_bridge_log` from its datablock dropdown,
or call `show_log()` to point an already-open one at it. Configurable with
`LOG_TO_TEXT` / `LOG_TEXT_NAME` / `LOG_MAX_LINES` in `config.env` (it keeps
the last 500 lines).

## Axis mapping calibration

It depends on **how the sensor is physically mounted**. In `config.env`:

- **`SIGN_ROLL` / `SIGN_PITCH` / `SIGN_YAW`** (`+1` / `-1`): invert the
  **direction** of an axis that rotates "backwards".
- **`AXIS_MAP`**: **permutes** which source (roll/pitch/yaw) goes to each
  Blender axis, in **X,Y,Z** order. This fixes the *"I move one axis and
  another one responds"* symptom, which signs CANNOT fix. Each token is
  `roll`/`pitch`/`yaw`, with an optional `-` prefix to invert.

  | AXIS_MAP | Effect |
  |---|---|
  | `roll,pitch,yaw` | Identity (classic): X=roll, Y=pitch, Z=yaw |
  | `pitch,roll,yaw` | Swaps roll and pitch |
  | `roll,pitch,-yaw` | Like identity but yaw inverted |

**Procedure** (with the bridge running, isolating one axis at a time):

| You physically rotate… | Should move the axis… | Which one moves? |
|---|---|---|
| roll (about sensor X) | Blender X | ? |
| pitch (about sensor Y) | Blender Y | ? |
| yaw (vertical) | Blender Z | ? |

If a rotation shows up on another axis, place that source in the matching
X/Y/Z slot of `AXIS_MAP`. If it shows up inverted, add the `-`.

> The bundled `config.env` ships `AXIS_MAP=pitch,roll,yaw` as an **educated
> guess without hardware on hand** (the sensor's "roll" is about its X axis,
> but the longitudinal axis in Blender is usually +Y). Adjust it with the table.

## Filter / tuning

- `ALPHA_ROLL_PITCH` (0..1): gyro weight in roll/pitch. Higher = smoother but
  slower to correct; lower = more reactive (more jittery).
- `GYRO_CALIB_SAMPLES`: samples at rest to estimate the gyro bias at startup.

## How `config.env` is located

The script looks for `config.env` in this order:

1. Absolute path in the `WIRED_BRIDGE_CONFIG` environment variable, if set.
2. Next to the `.py` (when `__file__` is defined).
3. **Folders inferred from Blender**: that of the `.py` opened as an external
   text and that of the saved `.blend`.
4. The current working directory.
5. If not found, the script's internal default values are used.

> **Note (known issue):** inside Blender's Text Editor, `__file__` often does
> **not** exist and `os.getcwd()` does not point to the script's folder, so
> the `config.env` "right next to it" was not found and you had to edit the
> defaults in the `.py`. Step 3 solves this **if you open the script from
> disk** (Open) instead of pasting the text. If it still fails, export the
> path before launching Blender:
>
> ```bash
> export WIRED_BRIDGE_CONFIG=/absolute/path/to/motion_bridge/wired/blender/config.env
> ```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ERROR opening serial port` | Wrong port in `config.env`, or busy in another app (close the Serial Monitor / `read_serial.py`). |
| `ModuleNotFoundError: serial` in Blender | `pyserial` installed into the system Python, not Blender's (step 3). |
| Moved with `_DEFAULTS`, ignored `config.env` | File not found: open the `.py` from disk or use `WIRED_BRIDGE_CONFIG` (see above). |
| I move one axis and **another** responds | Axis permutation: adjust `AXIS_MAP`. |
| An axis rotates **backwards** | Adjust the matching `SIGN_*` (or the `-` prefix in `AXIS_MAP`). |
| Yaw drifts on its own over time | Inherent drift (no magnetometer): call `recenter_yaw()`. |
| `|accel|` at rest ≠ 1 g | Clone that ignores the ±2g default; the sketch fixes the ranges (see `docs/CONTEXT.md`). |
