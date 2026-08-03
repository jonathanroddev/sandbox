# wifi — one or many sensors → Blender, over UDP

Real-time bridge from **one or several** WiFi IMU sensors to **Blender**.
It is the path toward a multi-sensor motion capture suit, and the sibling
of [`../wired/`](../wired/) (a single MPU-6050 over USB serial).

One Blender script serves every sensor, whatever it sends:

| Sensor | Frame | Fusion | Rate |
|---|---|---|---|
| **ESP32 + MPU-6050** | `raw6`, 7 fields | Done here (complementary filter) | 100 Hz |
| **Arduino Uno + ESP-01** | `raw6`, 7 fields | Done here | ~20 Hz |
| **WitMotion WT901WIFI** | `fused`, 13 fields | Internal (its own Kalman) | up to 200 Hz |

The receiver tells them apart by field count, keeps per-device fusion state
and per-device calibration, and routes each DeviceID to its own object.
Mixing sensor types on one socket is normal, not a special case. The format
is documented in [`../docs/PROTOCOL.md`](../docs/PROTOCOL.md).

## Layout

```
wifi/
├── blender/
│   ├── blender_udp_bridge.py   # UDP receiver to run inside Blender
│   └── config.env              # all configuration (port, mapping, axes, indices)
├── firmware/
│   ├── mpu_wifi_esp32/         # ESP32 + MPU-6050 (recommended)
│   └── mpu_wifi_uno_esp01/     # Arduino Uno + ESP-01 via AT commands
├── tools/
│   ├── read_udp.py             # UDP diagnostic reader (outside Blender)
│   └── fake_sensor.py          # fake emitter, both profiles (test without hardware)
└── docs/
    ├── CONTEXT.md              # decisions specific to this bridge
    ├── SETUP_ARDUINO_WIFI.md   # wiring and flashing the Arduino/ESP boards
    └── SETUP_WT901WIFI.md      # configuring the WitMotion sensor
```

## Requirements

- Sensors and PC on the **same 2.4 GHz** network (none of this hardware
  sees 5 GHz).
- **Blender**. The receiver uses only Python's standard library plus
  `mathutils`, which ships with Blender: **nothing to install**.

## Quick start

1. **Try it with no hardware at all** — validate the whole flow first:
   ```bash
   python3 tools/read_udp.py 1399 3        # terminal 1
   python3 tools/fake_sensor.py            # terminal 2
   ```
   Lines with `fields=13` mean the pipeline works on this machine. Anything
   that fails later is then network or sensor, not code.
2. **Set up a sensor**: [`docs/SETUP_ARDUINO_WIFI.md`](docs/SETUP_ARDUINO_WIFI.md)
   for the Arduino/ESP boards, [`docs/SETUP_WT901WIFI.md`](docs/SETUP_WT901WIFI.md)
   for the WitMotion. Both must point at `YOUR_PC_IP:1399`.
3. **Confirm the real frames**: `python3 tools/read_udp.py 1399 10`. Note
   the DeviceID and the field count; adjust `IDX_*` in `blender/config.env`
   only if the layout differs from the protocol document.
4. **Set `DEFAULT_OBJECT`** (and later `DEVICE_MAP`) in `blender/config.env`.
5. **In Blender**: Scripting tab → **Open** `blender/blender_udp_bridge.py`
   from disk (do not paste it — opening it from disk is how the script
   finds `config.env`) → **Run Script**. Hold the sensor in the reference
   pose during the auto-calibration countdown.

Functions available in Blender's Python console:

```python
start_bridge()      # open the socket and start listening
calibrate()         # capture the reference pose NOW (strike the T-pose)
recenter(device_id) # re-zero one sensor (also cancels raw6 yaw drift)
list_devices()      # DeviceIDs seen, their profile and their object
show_log()          # show the bridge's messages inside Blender
stop_bridge()       # stop and close the socket
```

### Seeing the bridge's messages

`print()` inside Blender goes to the **system console**, which you only see
if you launched Blender from a terminal (on Windows: Window → Toggle System
Console). Since the messages that matter most arrive exactly when you are
holding a sensor and not watching a terminal, everything is **also mirrored
into a Text datablock**: open a Text Editor and pick `wifi_bridge_log` from
its datablock dropdown, or call `show_log()` to point an already-open one at
it. Configurable with `LOG_TO_TEXT` / `LOG_TEXT_NAME` / `LOG_MAX_LINES` in
`config.env` (it keeps the last 500 lines).

## Multi-sensor

The receiver is multi-sensor from the start; going from one to several is
configuration only:

1. Give each board a distinct `DEVICE_ID` in its `secrets.h` (the WT901WIFI
   brings its own, something like `WT53xxxx`).
2. Run them all, then `list_devices()` in Blender to see who showed up.
3. Fill `DEVICE_MAP` in `config.env`:
   `DEVICE_MAP=WT53abc:Arm_L,ESP32_A:Arm_R,SPINE:Torso`

Each device gets its own calibration offset, so `calibrate()` zeroes the
whole set at once against a single reference pose.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Nothing arrives at `read_udp.py` | Sensor pointed at the wrong IP or port, 5 GHz network, or the firewall is dropping UDP 1399. Check with `sudo tcpdump -n -i any udp port 1399`. |
| Frames arrive but the object never moves | `DEFAULT_OBJECT`/`DEVICE_MAP` does not match the exact object name in the scene — `list_devices()` shows `(no object)`. |
| A `raw6` sensor appears but nothing moves for ~3 s | Normal: it is estimating its gyro bias. Keep it still. |
| The object drifts slowly in yaw | Inherent to the MPU-6050 (no magnetometer): `recenter(device_id)`. Does not apply to the WT901WIFI. |
| I move one axis and **another** responds | Axis permutation: adjust `AXIS_MAP` in `config.env`. |
| An axis rotates **backwards** | Adjust the matching `SIGN_*` (or the `-` prefix in `AXIS_MAP`). |
| Ignored `config.env`, used `_DEFAULTS` | The script was pasted instead of opened from disk. Open it from disk, or `export WIFI_BRIDGE_CONFIG=/absolute/path/to/config.env`. |
| Jittery motion on a `raw6` sensor | Raise `ALPHA_ROLL_PITCH`; if it is sluggish instead, lower it. |

## Status

Receiver and tooling **validated end to end in software** — both profiles,
two devices on one socket, fusion accurate to 0.3° against the attitude
that generated the frames, pose calibration, malformed-input resilience
(details in `../docs/CONTEXT.md`). **No WiFi hardware has been connected
yet**: the firmware is written but unflashed, and the axis mappings are
untuned because no mounting has been decided. Mapping sensors to an
armature's bones is the next real step (see `../CLAUDE.md`).
