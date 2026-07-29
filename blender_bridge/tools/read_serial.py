#!/usr/bin/env python3
"""
read_serial.py — Serial diagnostic reader (outside Blender).

Opens the port, optionally resets the board via DTR, and dumps the lines
received over N seconds. Useful to validate the I2C diagnostics and, later,
the raw CSV output from the sensor.

Usage:
    python3 tools/read_serial.py [PORT] [SECONDS] [BAUD]

Defaults: /dev/cu.usbmodem11201, 8 s, 115200 baud.
"""
import sys
import time
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem11201"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
baud = int(sys.argv[3]) if len(sys.argv) > 3 else 115200

print(f"[read_serial] Opening {port} @ {baud} for {secs}s...", flush=True)
ser = serial.Serial(port, baud, timeout=0.2)

# Reset via DTR (on the Uno, a DTR pulse resets the MCU -> re-runs setup())
ser.setDTR(False)
time.sleep(0.1)
ser.setDTR(True)
time.sleep(0.2)
ser.reset_input_buffer()

t_end = time.time() + secs
while time.time() < t_end:
    line = ser.readline().decode("utf-8", errors="ignore").rstrip("\r\n")
    if line:
        print(line, flush=True)

ser.close()
print("[read_serial] Done.", flush=True)
