# Hardware setup — Arduino/ESP + MPU-6050 over WiFi

Step-by-step guide to get a board streaming `raw6` frames to the bridge.
Two boards are supported; **start with the ESP32 if you have one**, it has
far fewer ways to fail.

> Nothing here has been executed against real hardware yet: the sketches
> are written but unflashed. Treat the rates and the AT behaviour as
> informed expectations, and correct this document once you measure them.

---

## 0. First: which board?

| | **ESP32 + MPU-6050** | **Uno + ESP-01S + MPU-6050** |
|---|---|---|
| Rate | 100 Hz (200 possible) | ~20 Hz |
| Logic levels | 3.3V throughout, MPU wired directly | Uno is 5V, ESP-01 is 3.3V → **level shifter required** |
| Power | Single 3.3V rail on the board | ESP-01 peaks ~300 mA; the Uno's 3.3V regulator gives ~50 mA → **separate supply required** |
| Parts | 1 board | 1 board + module + shifter + regulator + capacitor |
| Cost | ~5–8 € | Uno (owned) + ~3 € + extras |
| Battery-powered for a suit | Straightforward | Awkward (two rails) |

The Uno + ESP-01 path exists because the Uno is already here. For anything
beyond a first test — and certainly for a suit of several sensors — the
ESP32 is both simpler and cheaper.

**Whatever you buy, check it is 2.4 GHz** (all of this hardware is) and that
your router exposes a 2.4 GHz SSID: none of these radios can see 5 GHz.

---

## 1. Find your PC's IP (it is not in the repo)

Every board points at `PC_IP:PORT`, and the IP depends on your machine and
network, so it is **never** committed. Find it:

```bash
# macOS (WiFi interface)
ipconfig getifaddr en0
# Linux
hostname -I | awk '{print $1}'
```

The **port** is fixed in the repo: `LISTEN_PORT=1399` in
`blender/config.env`. If you change it, change it there and in every
board's `secrets.h`.

> If your router hands out addresses by DHCP, your PC's IP can change and
> the boards will silently stream into the void. Consider a DHCP
> reservation for the PC once this stops being an experiment.

---

## 2. Validate the software pipeline first (no hardware)

Do this before wiring anything, so any later failure is isolated to
"network or board":

```bash
cd motion_bridge/wifi
python3 tools/read_udp.py 1399 4                             # terminal 1
python3 tools/fake_sensor.py 1399 3 20 127.0.0.1 ESP32_A raw6  # terminal 2
```

Expected: lines reading `fields= 7 | ESP32_A,...`. If this works, the
receiving side is fine.

---

## 3A. ESP32 + MPU-6050

### Wiring

| MPU-6050 (GY-521) | ESP32 |
|---|---|
| VCC | **3V3** (not 5V — no ESP32 pin is 5V tolerant) |
| GND | GND |
| SDA | GPIO21 |
| SCL | GPIO22 |
| AD0 | GND (I2C address 0x68) |

### Toolchain

```bash
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### Flash

```bash
cd motion_bridge/wifi/firmware/mpu_wifi_esp32
cp secrets.example.h secrets.h     # then edit: SSID, password, DEST_IP, DEVICE_ID
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli upload -p /dev/cu.usbserial-XXXX --fqbn esp32:esp32:esp32 .
```

### Verify
Open the USB serial monitor at 115200. You should see
`WHO_AM_I = 0x68 (MPU-6050 OK)`, the IP the router assigned, and a status
line every 5 s with the frame count and the last frame sent.

---

## 3B. Arduino Uno + ESP-01S

### Prepare the module first (once)

SoftwareSerial on an Uno cannot keep up with the ESP-01's factory 115200
baud. Talk to the module with a USB-TTL adapter and drop it to 9600
**before** using it with this sketch:

```
AT                          -> OK          (module alive)
AT+GMR                      -> firmware version
AT+UART_DEF=9600,8,1,0,0    -> OK          (persists across reboots)
```

If `AT` does not answer: check `CH_PD` is tied to 3.3V (the module does
nothing without it), and that your supply is not browning out.

### Wiring

| Signal | Connection |
|---|---|
| MPU VCC | Uno 5V (the GY-521 has its own regulator) |
| MPU GND / SCL / SDA | GND / A5 / A4 |
| ESP-01 VCC | **Separate 3.3V supply** (~300 mA peaks), 100 µF cap nearby |
| ESP-01 GND | GND, **common with the Uno** |
| ESP-01 CH_PD | 3.3V |
| ESP-01 TX | Uno pin 2 (3.3V out is safe for a 5V input) |
| ESP-01 RX | Uno pin 3 **through a level shifter** (or 1 kΩ series + 2 kΩ to GND) |

> Wiring the Uno's 5V TX straight into the ESP-01's RX is the classic way
> to kill the module. Do not skip the divider.

### Flash

```bash
cd motion_bridge/wifi/firmware/mpu_wifi_uno_esp01
cp secrets.example.h secrets.h     # then edit: SSID, password, DEST_IP, DEVICE_ID
arduino-cli compile --fqbn arduino:avr:uno .
arduino-cli upload -p /dev/cu.usbmodem11201 --fqbn arduino:avr:uno .
```

### Verify
Open the USB serial monitor at 115200: the sketch echoes every AT exchange,
so a failure names its own step — `AT` (module/power/baud), `AT+CWJAP`
(SSID/password/5 GHz), or `AT+CIPSTART` (destination).

---

## 4. Confirm the frames arrive

```bash
cd motion_bridge/wifi
python3 tools/read_udp.py 1399 10
```

Expected: `fields= 7 | YOUR_DEVICE_ID,ax,ay,az,gx,gy,gz`. Check that with
the sensor **still and flat**, `az ≈ 1.0` and `ax, ay ≈ 0` — that is the
accelerometer reading gravity, and it is the single best sanity check on
the whole chain. If |accel| is far from 1 g, the range registers did not
take (see `../../docs/CONTEXT.md`, decision 5).

Count the lines to measure the real rate: 10 s should give ~1000 lines from
an ESP32, ~200 from an Uno + ESP-01.

---

## 5. Into Blender

1. `blender/config.env`: set `DEFAULT_OBJECT` (and `DEVICE_MAP=*:<Object>`)
   to your scene object's exact name.
2. Blender → Scripting → **Open** `blender/blender_udp_bridge.py` from disk
   → **Run Script**.
3. Keep the sensor **still for the first ~3 s**: it is estimating the gyro
   bias, and it deliberately outputs nothing until that finishes. Watch for
   `gyro bias (deg/s)` in the console.
4. Then hold it in the reference pose for the auto-calibration countdown.
   With `raw6` sensors, raising `CALIB_COUNTDOWN` to 6 avoids calibrating
   before the bias estimate is done.
5. Move it one axis at a time and check the object follows on the right
   axis and in the right direction. Fix mismatches with `AXIS_MAP` /
   `SIGN_*` in `config.env` — never in the code.

---

## If there is silence (checklist)

1. PC and board on the **same 2.4 GHz** network?
2. Is `DEST_IP` in `secrets.h` still the PC's current IP? (DHCP moves it.)
3. Firewall: allow UDP 1399.
   ```bash
   # Fedora / Linux
   sudo firewall-cmd --add-port=1399/udp        # temporary, until reboot
   # macOS: System Settings -> Network -> Firewall (or disable for the test)
   ```
4. Does anything reach the machine at all?
   ```bash
   sudo tcpdump -n -i any udp port 1399
   ```
   Packets here but nothing in `read_udp.py` means a parsing/port problem;
   nothing here means network or board.
5. What does the board's own USB serial monitor say? It reports whether it
   joined and what it is sending — that splits "board is not sending" from
   "PC is not receiving" in one look.
6. ESP-01 only: random resets or `AT` timeouts mid-run are almost always
   **power**, not code. Give it its own supply and a capacitor.
