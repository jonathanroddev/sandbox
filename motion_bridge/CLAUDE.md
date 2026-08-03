# Guide for Claude Code — motion_bridge

Quick orientation for working here. Read [`docs/CONTEXT.md`](docs/CONTEXT.md)
for the decisions and [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the frame
format before changing anything that touches parsing or transport.

## What this is
Two Blender bridges for IMU sensors: `wired/` (one MPU-6050 over USB
serial) and `wifi/` (one or many sensors over UDP — Arduino/ESP boards and
WitMotion WT901WIFI). Same conventions, deliberately separate code.

## Rules
- **Configuration lives in `blender/config.env`.** Ports, object names,
  field indices, axis mappings. Never hardcode them in the `.py`.
- **A different CSV layout is a config change**, never a parser change:
  that is what `IDX_*` is for.
- **A wrong-looking axis is a config change**, never a code change: that is
  what `SIGN_*` and `AXIS_MAP` are for.
- **Network credentials go in `firmware/*/secrets.h`** (gitignored, one per
  board). Never commit an SSID, a password or a LAN IP.
- Code, comments and user-facing messages **in English**.
- Blender code must not block the UI: `bpy.app.timers`.
- **Standard library + `mathutils` only** (`pyserial` in `wired/` is the
  one exception). Justify any new dependency.
- Each Blender script stays **one self-contained file** — see
  `docs/CONTEXT.md` for why. Do not refactor them into a shared package.

## Current status
- `wired/` — works up to the raw CSV, validated against real hardware.
  Never yet driven an object inside Blender.
- `wifi/` — receiver handles both frame profiles, multi-device routing and
  pose calibration; validated in software (see `docs/CONTEXT.md`). No WiFi
  hardware has been connected yet.
- Firmware written but **never flashed**: `wifi/firmware/mpu_wifi_esp32/`
  and `wifi/firmware/mpu_wifi_uno_esp01/`. Both compile-untested — there is
  no ESP core installed on the dev machine yet.

## Known uncertainties (resolve with hardware in hand)
1. **The WT901WIFI's real CSV layout.** `IDX_ANGLE_X/Y/Z=7,8,9` and
   `IDX_DEVICE=0` come from the product documentation and may vary with
   firmware. Confirm with `wifi/tools/read_udp.py`, adjust `config.env`.
2. **Axis frames.** Every sensor's mapping to Blender depends on how it
   ends up mounted. Nothing here is validated against a real mounting yet;
   `wifi/`'s `AXIS_MAP` is identity precisely because it is unknown.
3. **The Uno + ESP-01 rate.** ~20 Hz is an estimate from the AT round trip
   at 9600 baud. Measure it with `read_udp.py` before designing around it.

## Task order
### wifi/, with hardware
1. Flash one board (ESP32 first if you have one — fewer failure modes).
2. `python3 wifi/tools/read_udp.py 1399 10` → confirm frames, field count,
   DeviceID.
3. One sensor in Blender: `DEFAULT_OBJECT`, Run Script, auto-calibrate in
   the reference pose, check the axes move as expected.
4. Fine-tune `AXIS_MAP` / `SIGN_*` until the object follows faithfully.
5. Multi-sensor: `list_devices()` → fill `DEVICE_MAP`.
6. **Armature**: move from loose objects to `pose.bones[...]`, resolving
   each bone's orientation relative to its parent. This is the heart of the
   suit and the real remaining work.

### wired/
1. Run the bridge inside Blender (never done yet).
2. Calibrate `AXIS_MAP` for the actual mounting.
3. Tune `ALPHA_ROLL_PITCH` if it looks jittery (lower) or sluggish (raise).

## Testing without hardware
`wifi/tools/fake_sensor.py` emits UDP frames in either profile, physically
consistent (gravity projected onto the simulated attitude, gyro = its
derivative), so the fusion can be checked against the attitude that
generated it.

```bash
cd motion_bridge/wifi
# Terminal 1 — see what arrives and in what format
python3 tools/read_udp.py 1399 3
# Terminal 2 — a WT901WIFI-like sensor
python3 tools/fake_sensor.py
# ...or an Arduino/ESP-like one at its realistic rate
python3 tools/fake_sensor.py 1399 0 20 127.0.0.1 ESP32_A raw6
# ...or several at once (multi-sensor)
python3 tools/fake_sensor.py 1399 0 100 127.0.0.1 WT53abc,WT53def
```

In Blender: Run Script the bridge, launch `fake_sensor.py` alongside, and
the object in `DEVICE_MAP`/`DEFAULT_OBJECT` should oscillate.

When the real sensor shows a different layout than the emitter, the
**emitter is not wrong** — it reproduces the documented default. Adjust
`IDX_*` in `config.env`.
