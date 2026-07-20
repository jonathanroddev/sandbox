#!/usr/bin/env python3
"""
read_udp.py — Lector UDP de diagnóstico (fuera de Blender).

Escucha en un puerto UDP y vuelca las tramas que envía el WT901WIFI
durante N segundos. Es el equivalente de read_serial.py para el sensor
WiFi: sirve para VERIFICAR el formato real del CSV (orden de campos,
número de columnas, terminador) ANTES de meterlo en Blender.

No necesita pyserial ni dependencias externas: solo librería estándar.

Uso:
    python3 tools/read_udp.py [PUERTO] [SEGUNDOS] [HOST]

Por defecto: puerto 1399, 8 s, host 0.0.0.0 (todas las interfaces).

Qué mirar en la salida:
    - ¿Cada línea empieza por el DeviceID (algo tipo 'WT53...')?
    - ¿Cuántos campos hay separados por comas? (esperados: >=10)
    - ¿En qué posición están los ángulos X,Y,Z? (por defecto índices 7,8,9)
  Si el orden no coincide con lo esperado, ajusta los IDX_* en
  blender/config.env — no hay que tocar el código del bridge.
"""
import sys
import socket
import time

port = int(sys.argv[1]) if len(sys.argv) > 1 else 1399
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
host = sys.argv[3] if len(sys.argv) > 3 else "0.0.0.0"

print(f"[read_udp] Escuchando UDP en {host}:{port} durante {secs}s...", flush=True)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((host, port))
sock.settimeout(0.5)

t_end = time.time() + secs
count = 0
while time.time() < t_end:
    try:
        data, addr = sock.recvfrom(2048)
    except socket.timeout:
        continue
    text = data.decode("utf-8", errors="ignore").strip()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        count += 1
        n_fields = len(line.split(","))
        # Muestra origen, nº de campos y la línea cruda (útil para depurar).
        print(f"[{addr[0]}] campos={n_fields:2d} | {line}", flush=True)

sock.close()
print(f"[read_udp] Fin. {count} líneas recibidas.", flush=True)
