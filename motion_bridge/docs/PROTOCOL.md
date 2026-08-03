# Frame protocol — the contract between sensors and bridges

Every sensor in this project emits **ASCII CSV, one line per reading**,
terminated by `\r\n`. There is a single field layout, shared by all
transports and all hardware. A sensor may emit a **prefix** of it: the
receiver decides what it can do from the number of fields it gets.

```
index   0         1   2   3    4   5   6     7      8      9      10  11  12
field   deviceId  ax  ay  az   gx  gy  gz    angX   angY   angZ   mx  my  mz
unit    string    g   g   g    °/s °/s °/s   deg    deg    deg    (raw)
```

## Profiles

| Profile | Fields | Who emits it | What the receiver does |
|---|---|---|---|
| `raw6` | 7 (`0..6`) | `mpu_wifi_uno_esp01`, `mpu_wifi_esp32` | Sensor fusion **here** (complementary filter), per device |
| `fused` | 13 (`0..12`) | WitMotion WT901WIFI | Uses `angX/Y/Z` directly (fused by the sensor's Kalman) |

`raw6` is deliberately a **prefix** of the WitMotion layout: the same
`IDX_*` config keys address both, and adding a profile later (e.g. a native
quaternion appended at 13..16) does not break existing sensors.

### The wired bridge is the exception

`wired/` predates this contract and streams **6 fields with no deviceId**
(`ax,ay,az,gx,gy,gz`) over USB serial. That is fine and stays as is: a cable
carries exactly one sensor, so there is nothing to disambiguate. Do not add
a deviceId there — the transport already identifies the device.

## deviceId

- Free-form string, no commas, no spaces. It is the **identity of a board**,
  not of a model: it is what `DEVICE_MAP` in `wifi/blender/config.env` maps
  to a Blender object or (later) an armature bone.
- WT901WIFI: assigned by its firmware, looks like `WT53xxxx`. Discover it
  with `list_devices()` in Blender or `tools/read_udp.py`.
- Arduino/ESP boards: **you** choose it, in each board's `secrets.h`
  (`DEVICE_ID`). Give each board of the suit a distinct one, e.g. `ARM_L`,
  `ARM_R`, `SPINE`.

## Transport

- **UDP**, one datagram per frame, no ACK, no reconnection logic. A lost
  frame is a lost frame: the next one carries a fresher pose, which is what
  you want for motion capture. Never TCP — a retransmit delivers a stale
  pose late, which is worse than not delivering it.
- A datagram **may** contain more than one line (some firmwares batch). The
  receiver processes the **last complete line** of each datagram.
- Default port `1399` (`LISTEN_PORT` in `wifi/blender/config.env`). It must
  match what is configured on every sensor.

## Rate

| Source | Realistic rate | Why |
|---|---|---|
| `mpu_wifi_uno_esp01` | ~20 Hz | SoftwareSerial + AT commands is the bottleneck (see its README) |
| `mpu_wifi_esp32` | 100–200 Hz | Native WiFi, no intermediary |
| WT901WIFI | up to 200 Hz | Configured from WitMotion's tool |
| `wired` (serial) | ~50 Hz | `delay(20)` in the sketch, 115200 baud |

The receiver drains up to 200 datagrams per Blender timer tick, so several
sensors at 100 Hz are fine. If you saturate that, raise the cap in `_pump()`
rather than lowering the sensor rate.

## Adding a new sensor type

1. Make it emit this layout (a prefix is fine); pick a `deviceId`.
2. Point it at `PC_IP:1399`.
3. Verify with `python3 wifi/tools/read_udp.py 1399 10` — check the field
   count and that the values sit where this document says.
4. If the layout differs and you cannot change the firmware, adjust the
   `IDX_*` in `wifi/blender/config.env`. **Never** patch the parser for a
   field-order difference; that is what the indices are for.
