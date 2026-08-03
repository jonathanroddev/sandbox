/*
  secrets.example.h — per-board configuration template.

  Copy it to `secrets.h` (which is gitignored) and edit the values:

      cp secrets.example.h secrets.h

  ONE secrets.h PER BOARD. For the multi-sensor suit, every board shares the
  network settings but MUST have a distinct DEVICE_ID: that is what
  DEVICE_MAP in ../../blender/config.env maps to a Blender object.
*/

#pragma once

// ---- WiFi network (2.4 GHz; the ESP32 does not see 5 GHz networks) ----
#define WIFI_SSID "your-2.4GHz-ssid"
#define WIFI_PASS "your-wifi-password"

// ---- Where to stream ----
// The IP of the PC running Blender, on the LAN. NOT fixed in the repo: it
// depends on your machine/network. Find it with:
//   macOS:  ipconfig getifaddr en0
//   Linux:  hostname -I | awk '{print $1}'
#define DEST_IP   "192.168.1.22"
// Must match LISTEN_PORT in ../../blender/config.env.
#define DEST_PORT 1399

// ---- Identity of THIS board ----
// No commas, no spaces (it is the first CSV field). Use something you will
// recognise when it shows up in list_devices(), e.g. ARM_L, ARM_R, SPINE.
#define DEVICE_ID "ESP32_A"
