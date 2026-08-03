# motion_bridge — motion sensors → Blender

Real-time bridges that take orientation from IMU sensors and drive objects
in a **Blender** scene. Two of them, because a cable and a network are
genuinely different problems:

| | [`wired/`](wired/) | [`wifi/`](wifi/) |
|---|---|---|
| **Sensors** | Exactly **one** | **One or many** |
| **Hardware** | Arduino Uno + MPU-6050 | Arduino Uno + ESP-01, ESP32 + MPU-6050, WitMotion WT901WIFI |
| **Transport** | USB serial (`pyserial`) | WiFi / UDP (stdlib only) |
| **Rate** | ~50 Hz | 20 Hz (Uno+ESP-01) · 100–200 Hz (ESP32, WT901) |
| **Use it for** | Bench work: one sensor, no network, nothing to configure | Anything untethered, and the multi-sensor capture suit |

Both apply the same idea — read orientation, map the sensor's axes onto
Blender's, zero it against a reference pose, move the object — and share
the same conventions. What they do **not** share is code: each Blender
script is a single self-contained file, on purpose (see
[`docs/CONTEXT.md`](docs/CONTEXT.md#why-two-scripts-and-not-one-shared-package)).

## Which one do I use?

- **One sensor on the desk, connected by cable** → `wired/`. Fewest moving
  parts; no IP, no port, no firewall.
- **A sensor that must move freely, or more than one** → `wifi/`. This is
  the path toward the capture suit.

New here? Start with [`wired/README.md`](wired/README.md) — it is the
simpler of the two and the concepts carry over.

## Layout

```
motion_bridge/
├── docs/
│   ├── CONTEXT.md      Shared architecture and the decisions behind it
│   └── PROTOCOL.md     The frame format every WiFi sensor speaks
├── wired/              1 sensor · USB serial
│   ├── firmware/       Arduino sketches (bridge + I2C diagnostics)
│   ├── blender/        Script to run inside Blender + config.env
│   ├── tools/          read_serial.py (diagnostics outside Blender)
│   ├── docs/           Hardware notes and decisions
│   └── backups/        The Uno's original flash/EEPROM dumps
└── wifi/               1..N sensors · UDP
    ├── firmware/       mpu_wifi_uno_esp01/ · mpu_wifi_esp32/
    ├── blender/        Script to run inside Blender + config.env
    ├── tools/          read_udp.py · fake_sensor.py (test without hardware)
    └── docs/           Per-sensor setup guides and decisions
```

## Conventions (both projects)

- **All configuration lives in `blender/config.env`** (KEY=value, no
  quotes, read with no external dependencies — Blender's Python has no
  python-dotenv). Ports, object names and axis mappings never get hardcoded
  in the `.py`.
- **Network credentials live in `firmware/*/secrets.h`**, one per board,
  gitignored. Copy `secrets.example.h` to start.
- Code and documentation **in English**.
- Blender code must not block the UI: everything runs on `bpy.app.timers`.
- **Standard library only** (plus `mathutils`, which ships with Blender).
  The one exception is `pyserial` in `wired/`, which is unavoidable.
- Nothing in this folder needs the hardware to be developed: `wifi/` has
  `tools/fake_sensor.py`, which emits frames indistinguishable from a real
  sensor's.
