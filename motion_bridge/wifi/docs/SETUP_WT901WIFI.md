# Hardware setup — connect the WT901WIFI and validate reception

Guide to resume work **with the sensor in hand**, meant to continue from the
work PC (Fedora + a Windows VM for WitMotion's official tool). It complements
`CONTEXT.md` (decisions and protocol) and `../../CLAUDE.md` (task order).

> **Status at time of writing (2026-07-20):** the software pipeline is
> **validated end-to-end** on the development Mac with `fake_sensor.py` →
> `read_udp.py` (13 fields, DeviceID at index 0, angles at 7/8/9, consistent
> with `config.env`). The only thing **pending with real hardware** is:
> confirming the sensor's real CSV format and fine-tuning the axis mapping in
> Blender. If no frames arrive when you connect the real sensor, the problem
> is **network or sensor configuration**, not the code.

---

## 0. First of all: the IP is specific to each machine/network

All the config points the sensor at `PC_IP:PORT`. **The IP is NOT hardcoded**
in the repo: it depends on the PC and the network. On the development Mac it
was `192.168.1.22`, but on the Fedora PC it will be different. Find it like
this:

```bash
# Fedora / Linux — LAN IP (the WiFi interface one, typically wlan0/wlp*)
ip -4 addr show | grep -w inet          # lists them all; take your WiFi one
# shortcut:
hostname -I | awk '{print $1}'
# or, more explicit, with NetworkManager:
nmcli -t -f IP4.ADDRESS device show | head
```

The **port** IS fixed in the repo: `LISTEN_PORT=1399` in
`blender/config.env`. If you change it, change it there (not in the code) and
use the same value on the sensor.

Check the UDP port is free before listening:

```bash
# Fedora / Linux
ss -lunp | grep 1399 || echo "free"
```

---

## 1. Validate the software pipeline (no sensor)

Do this **first** on the new PC: confirm that Python + sockets + parsing work
there, to isolate any later failure as "network/sensor".

```bash
cd motion_bridge/wifi
# Terminal 1 — listen for 4 s
python3 tools/read_udp.py 1399 4
# Terminal 2 — emit fake frames for 3 s to localhost
python3 tools/fake_sensor.py 1399 3 50 127.0.0.1 WT9AXTEST
```

Expected: `fields=13 | WT9AXTEST,...` lines and, at the end,
`N lines received`. If this works, the software is OK.

---

## 2. Prepare the Windows VM (for the official tool)

WitMotion's official configuration tool is **Windows**-only. On Fedora, run
it in a VM (VirtualBox / GNOME Boxes / virt-manager).

**Key — the VM's network:** the VM has to be able to **see the sensor over
WiFi**, so it needs to be on the same network as it. During configuration the
sensor is in **AP mode** (it creates its own WiFi):

1. Connect the **Fedora host** to the sensor's WiFi (`WT901WIFI_xxxx` / `HC-xx`).
2. Set the VM's network to **bridged mode** over the host's WiFi interface
   (not NAT), so the VM gets an IP on the sensor's network and can talk to
   it. (With NAT you usually **won't** reach the sensor.)
3. Alternative if bridging over WiFi is troublesome (some WiFi drivers won't
   bridge): use the **WitMotion mobile app** for all the configuration and
   skip the VM for this part.

---

## 3. Configure the sensor: AP mode → Station mode

The sensor ships in **AP mode** (creates its network). We want it in
**Station mode** (joined to your router, alongside the PC). Steps:

1. **Power on** the sensor (button ~2 s; charge over USB if the LED doesn't
   light).
2. Connect to its WiFi `WT901WIFI_xxxx` (password from the manual if asked;
   usually `1234567890` / `12345678` or none).
3. Open the official tool (in the VM) or the mobile app and go into the
   sensor's network settings. Configure:

   | Field | Value |
   |---|---|
   | Mode | **Station (STA)** |
   | Router SSID | your WiFi (**2.4 GHz**, the sensor can't see 5 GHz) |
   | Password | your WiFi password |
   | Protocol | **UDP** |
   | Target / Server IP | **the PC's IP** (from step 0) |
   | Target / Server Port | **1399** (or the `LISTEN_PORT` in `config.env`) |

   > ⚠️ **Order matters (manual):** when migrating AP → Station leave the
   > protocol on **UDP first**, never straight to TCP, or you may lose the
   > connection and need a reset. We use UDP anyway (lower latency; decision
   > in `CONTEXT.md`).

4. **Apply/save.** The sensor reboots and tries to join your router.
5. Reconnect the **PC to your home WiFi** (you'll have lost the network while
   on the sensor's).

---

## 4. Capture the REAL frame and lock down the CSV format

With the sensor on your network and transmitting:

```bash
cd motion_bridge/wifi
python3 tools/read_udp.py 1399 10
```

What to look for in the output (this is pending item #1 in `CLAUDE.md`):

- Do lines arrive and start with the real **DeviceID** (something like
  `WT53...`)? Note the DeviceID: you'll need it for `DEVICE_MAP` in
  `config.env`.
- **How many fields?** We assume 13.
- **Which indices hold the X/Y/Z angles?** We assume 7, 8, 9.

If the order/count does **not** match the assumptions, adjust in
`blender/config.env` (**not** in the code):
`IDX_DEVICE`, `IDX_ANGLE_X/Y/Z`, `MIN_FIELDS`.

---

## 5. One sensor in Blender

1. In `blender/config.env`: set `DEFAULT_OBJECT` (and `DEVICE_MAP=*:<Object>`)
   to your scene object's name.
2. Blender → **Scripting** tab → open `blender/blender_udp_bridge.py` →
   **Run Script**.
3. With `AUTO_CALIBRATE=1`, place the sensor in the **reference pose** during
   the initial countdown (`CALIB_COUNTDOWN` s).
4. Move the sensor **one axis at a time** and verify the object rotates on
   the correct axis and direction. If some axis is inverted/crossed, adjust
   `SIGN_ROLL/PITCH/YAW` (or the Euler order in `_angles_to_quat()`).

Utilities in Blender's Python console: `start_bridge()`, `calibrate()`,
`recenter(device_id)`, `list_devices()`, `stop_bridge()`.

---

## If there's silence (diagnostic checklist)

1. Are the PC and sensor on the **same** network and on **2.4 GHz**? (the
   sensor can't see 5 GHz).
2. Is the **IP** configured on the sensor the PC's current one? (re-check
   step 0; if the router assigns IPs via DHCP, it may have changed — consider
   fixing it).
3. **Fedora firewall** (firewalld): allow the UDP port for the test.
   ```bash
   sudo firewall-cmd --add-port=1399/udp            # temporary (until reboot)
   # permanent:  sudo firewall-cmd --permanent --add-port=1399/udp && sudo firewall-cmd --reload
   ```
4. Did the sensor stay in **AP mode**? (if it's still broadcasting its own
   network, it didn't enter Station: repeat step 3).
5. Confirm something arrives at the network level even if parsing fails:
   ```bash
   sudo tcpdump -n -i any udp port 1399
   ```
6. Last resort: **reset** the sensor (button per the manual) and repeat from
   step 3.

---

## Summary of what's left to do with the hardware

- [ ] Run step 1 (pipeline) on the Fedora PC.
- [ ] Set up the Windows VM + official tool (or use the mobile app) — step 2.
- [ ] Configure the sensor to Station/UDP/`PC_IP`:1399 — step 3.
- [ ] Capture the real frame and **confirm/adjust the `IDX_*`** — step 4.
- [ ] One sensor in Blender and **fine-tune the axis mapping** — step 5.
- [ ] Then: multi-sensor (`list_devices()` → `DEVICE_MAP`) and armature (see
      `CONTEXT.md` → "Pending / next steps").
