# witmotion_bridge

Real-time bridge from one or more **WitMotion WT901WIFI** sensors to
**Blender** over WiFi (UDP). It is the step toward a multi-sensor motion
capture suit, and a sibling of [`blender_bridge/`](../blender_bridge/) (the
Arduino + MPU version over USB serial).

Unlike the MPU, the WT901WIFI already delivers angles fused by its own
Kalman filter: here we only receive them over the network, calibrate against
a reference pose, and apply them to the object.

## Layout

```
witmotion_bridge/
├── blender/
│   ├── blender_udp_bridge.py   # UDP receiver to run inside Blender
│   └── config.env              # all configuration (port, mapping, axes)
├── tools/
│   ├── read_udp.py             # UDP diagnostic reader (outside Blender)
│   └── fake_sensor.py          # fake UDP emitter: mimics the WT901WIFI (test without hardware)
├── docs/
│   ├── CONTEXT.md              # decisions, protocol and sensor setup
│   └── SETUP_HARDWARE.md       # step-by-step guide to connect the real sensor
└── CLAUDE.md                   # task guide for Claude Code
```

## Requirements

- A **WT901WIFI** on the same WiFi network as the computer (see setup in
  [`docs/CONTEXT.md`](docs/CONTEXT.md)).
- **Blender** (the receiver uses only Python's standard library +
  `mathutils`, which ships with Blender: nothing to install).

## Quick start

1. Configure the sensor in Station mode pointing to your machine's IP and
   the port in `config.env` (1399 by default). Details in `docs/CONTEXT.md`.
2. Validate the frames without Blender:
   ```
   python3 tools/read_udp.py 1399 10
   ```
   No sensor yet? Emit fake frames in another terminal to test the whole
   flow:
   ```
   python3 tools/fake_sensor.py
   ```
3. Adjust `DEFAULT_OBJECT` (and `DEVICE_MAP`) in `blender/config.env`.
4. In Blender: Scripting tab → open `blender/blender_udp_bridge.py` → Run
   Script. Place the sensor in the reference pose during the
   auto-calibration countdown.

Handy functions in Blender's Python console:
`start_bridge()`, `calibrate()`, `recenter(device_id)`, `list_devices()`,
`stop_bridge()`.

## Status

Reception + pose-calibration MVP, **validated end-to-end in software**
(`fake_sensor.py` → `read_udp.py`: 13 fields, DeviceID at index 0, angles at
7/8/9). Pending a test with the real sensor: follow
[`docs/SETUP_HARDWARE.md`](docs/SETUP_HARDWARE.md) to connect it, confirm the
CSV format and fine-tune the axis mapping. The receiver already supports
multi-sensor by DeviceID; mapping to a suit armature is the next step (see
`CLAUDE.md`).
