#!/usr/bin/env python3
"""
fake_sensor.py — Emisor UDP falso que imita al WitMotion WT901WIFI.

Sirve para VALIDAR el parseo y la calibración del bridge SIN tener el
sensor real en la red (ver "Cómo probar sin hardware" en ../CLAUDE.md).
Genera tramas CSV con el mismo layout que el sensor y las envía por UDP al
puerto donde escucha el bridge, con los ángulos animados (oscilan) para
que el objeto de Blender se mueva de forma visible.

No necesita dependencias externas: solo librería estándar.

FORMATO DE TRAMA (mismo que espera config.env, índice basado en 0):
    0=DeviceID  1..3=Acc(x,y,z)  4..6=Gyro(x,y,z)  7..9=Angle(x,y,z)
    10..12=Mag(x,y,z)      -> 13 campos, terminado en \\r\\n
Si en tu firmware real el orden difiere, se ajusta en config.env (IDX_*),
no aquí: este emisor reproduce el layout POR DEFECTO documentado.

Uso:
    python3 tools/fake_sensor.py [PUERTO] [SEGUNDOS] [HZ] [HOST] [DEVICES]

Por defecto:
    PUERTO  -> LISTEN_PORT de blender/config.env (si se encuentra), o 1399
    SEGUNDOS-> 0 = indefinido (hasta Ctrl+C)
    HZ      -> 50 datagramas/segundo
    HOST    -> 127.0.0.1 (localhost; el bridge escucha en 0.0.0.0)
    DEVICES -> WT9AXTEST (uno). Varios: separa por comas para multi-sensor,
               p.ej.  WT53abc,WT53def  -> cada uno mueve su objeto según
               DEVICE_MAP. Cada dispositivo se anima con una fase distinta
               para poder distinguirlos.

Ejemplos:
    # Un sensor de prueba al puerto por defecto, indefinido:
    python3 tools/fake_sensor.py
    # Dos sensores a 100 Hz durante 20 s (test multi-sensor):
    python3 tools/fake_sensor.py 1399 20 100 127.0.0.1 WT53abc,WT53def
"""
import sys
import os
import socket
import time
from math import sin, radians, degrees


def _port_from_config(default=1399):
    """Lee LISTEN_PORT de blender/config.env para no desincronizar el puerto
    entre el emisor y el bridge. Si no lo encuentra, usa el valor por defecto."""
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = os.path.join(here, "..", "blender", "config.env")
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("LISTEN_PORT="):
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return default


port = int(sys.argv[1]) if len(sys.argv) > 1 else _port_from_config()
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0   # 0 = indefinido
hz = float(sys.argv[3]) if len(sys.argv) > 3 else 50.0
host = sys.argv[4] if len(sys.argv) > 4 else "127.0.0.1"
devices = sys.argv[5].split(",") if len(sys.argv) > 5 else ["WT9AXTEST"]
devices = [d.strip() for d in devices if d.strip()]

period = 1.0 / hz if hz > 0 else 0.02

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

modo = f"{secs:.0f}s" if secs > 0 else "indefinido (Ctrl+C para parar)"
print(f"[fake_sensor] Enviando a {host}:{port} @ {hz:.0f} Hz, {modo}", flush=True)
print(f"[fake_sensor] Dispositivos: {', '.join(devices)}", flush=True)


def _frame(device_id, t, phase):
    """Construye una trama CSV imitando al WT901WIFI para el instante t.

    Los ángulos oscilan en cada eje (amplitudes distintas para que roll,
    pitch y yaw sean fáciles de distinguir en Blender). Accel/Gyro/Mag se
    rellenan con valores plausibles: no los usa el bridge (solo lee Angle),
    pero mantienen el nº de campos y el aspecto de una trama real."""
    roll = 30.0 * sin(0.8 * t + phase)          # eje X
    pitch = 20.0 * sin(1.3 * t + phase + 1.0)   # eje Y
    yaw = 45.0 * sin(0.5 * t + phase + 2.0)     # eje Z

    # Accel: ~1g repartido según la inclinación (aproximación grosera).
    ax = sin(radians(pitch))
    ay = -sin(radians(roll))
    az = 1.0
    # Gyro: derivada aproximada de los ángulos (grados/s), meramente estético.
    gx, gy, gz = 0.0, 0.0, 0.0
    # Mag: valores fijos plausibles.
    mx, my, mz = 0.30, -0.10, 0.45

    campos = [
        device_id,
        f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
        f"{gx:.2f}", f"{gy:.2f}", f"{gz:.2f}",
        f"{roll:.2f}", f"{pitch:.2f}", f"{yaw:.2f}",
        f"{mx:.3f}", f"{my:.3f}", f"{mz:.3f}",
    ]
    return ",".join(campos) + "\r\n"


t0 = time.time()
n = 0
try:
    while True:
        now = time.time()
        t = now - t0
        if secs > 0 and t >= secs:
            break
        for i, dev in enumerate(devices):
            phase = i * 2.094  # ~120° de desfase entre dispositivos
            sock.sendto(_frame(dev, t, phase).encode("utf-8"), (host, port))
            n += 1
        time.sleep(period)
except KeyboardInterrupt:
    print("\n[fake_sensor] Interrumpido por el usuario.", flush=True)
finally:
    sock.close()
    print(f"[fake_sensor] Fin. {n} datagramas enviados.", flush=True)
