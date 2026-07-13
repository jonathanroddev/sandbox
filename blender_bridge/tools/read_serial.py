#!/usr/bin/env python3
"""
read_serial.py — Lector serial de diagnóstico (fuera de Blender).

Abre el puerto, opcionalmente resetea la placa por DTR, y vuelca las
líneas que llegan durante N segundos. Sirve para validar el diagnóstico
I2C y, más tarde, la salida CSV cruda del sensor.

Uso:
    python3 tools/read_serial.py [PUERTO] [SEGUNDOS] [BAUD]

Por defecto: /dev/cu.usbmodem11201, 8 s, 115200 baudios.
"""
import sys
import time
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbmodem11201"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
baud = int(sys.argv[3]) if len(sys.argv) > 3 else 115200

print(f"[read_serial] Abriendo {port} @ {baud} durante {secs}s...", flush=True)
ser = serial.Serial(port, baud, timeout=0.2)

# Reset por DTR (en el Uno, un pulso de DTR reinicia el micro -> re-ejecuta setup())
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
print("[read_serial] Fin.", flush=True)
