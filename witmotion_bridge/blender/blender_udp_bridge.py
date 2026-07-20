"""
blender_udp_bridge.py
----------------------
Ejecutar DENTRO de Blender (pestaña Scripting -> Text Editor -> Run Script).

Recibe por UDP las tramas del/los sensor(es) WitMotion WT901WIFI y aplica
su orientación a objetos de la escena. A diferencia del bridge serial del
MPU (que recibía datos crudos y hacía la fusión aquí), el WT901WIFI ya
entrega ángulos fusionados por su propio filtro de Kalman: aquí solo se
parsean, se calibran contra una pose de referencia y se aplican.

FLUJO:
    sensor --(WiFi, UDP)--> socket en esta máquina --> parser por DeviceID
        --> offset de calibración --> objeto de Blender (rotation_quaternion)

CLAVES DE DISEÑO:
  - Un ÚNICO transporte (UDP). No hay "UDP y luego TCP": se elige uno.
    UDP encaja mejor en captura de movimiento (menos latencia; un paquete
    perdido se descarta y se usa el siguiente, sin retransmitir poses viejas).
  - MULTI-SENSOR nativo: cada trama trae su DeviceID; DEVICE_MAP decide qué
    objeto mueve cada sensor. Un solo socket sirve a todos los sensores.
  - CALIBRACIÓN POR POSE (no por sensor): al arrancar se captura la
    orientación de cada sensor como "cero" y se aplica su inverso a cada
    lectura. Se hace con cuaterniones (mathutils) -> sin gimbal lock, y
    calibra los tres ejes a la vez, no solo el yaw. No dependemos del
    "Z-axis zero return" del sensor (que obliga a modo 6 ejes y reintroduce
    deriva de yaw); mantenemos el yaw absoluto de 9 ejes y lo "ponemos a
    cero" en software.

REQUISITOS:
  No hace falta pyserial. El socket UDP usa solo la librería estándar, y
  mathutils viene incluido en Blender. Nada que instalar.

USO RÁPIDO (en la consola Python de Blender, tras Run Script):
    start_bridge()      # abre el socket UDP y empieza a escuchar
    calibrate()         # captura la pose de referencia AHORA (pon la T-pose)
    recenter(device)    # recalibra un sensor concreto por su DeviceID
    list_devices()      # muestra los DeviceIDs vistos y su objeto asignado
    stop_bridge()       # detiene y cierra el socket

NOTA SOBRE EL MAPEO DE EJES:
  El sensor entrega los ángulos en su propio marco de referencia (y usa
  orden de Euler Z-Y-X). Blender es Z-up. El marco puede no coincidir con
  el objeto según cómo montes físicamente el sensor. Empezamos con un mapeo
  directo + signos configurables (SIGN_*), pero es lo primero a verificar
  con el sensor en la mano: mueve el sensor en un eje y comprueba que el
  objeto gira en el eje y sentido correctos; ajusta SIGN_* o el orden en
  _angles_to_quat() si hiciera falta.
"""

import bpy
import socket
import time
import os
from mathutils import Euler, Quaternion

# ---------- CARGA DE CONFIGURACIÓN (config.env) ----------
# Mismo patrón que blender_serial_bridge.py: todo lo que cambia entre
# PCs/redes/escenas vive en config.env, no aquí.

_DEFAULTS = {
    "LISTEN_HOST": "0.0.0.0",
    "LISTEN_PORT": "1399",
    "DEVICE_MAP": "*:Cube",
    "DEFAULT_OBJECT": "Cube",
    "AUTO_CALIBRATE": "1",
    "CALIB_COUNTDOWN": "3",
    "SIGN_ROLL": "1",
    "SIGN_PITCH": "1",
    "SIGN_YAW": "1",
    "IDX_DEVICE": "0",
    "IDX_ANGLE_X": "7",
    "IDX_ANGLE_Y": "8",
    "IDX_ANGLE_Z": "9",
    "MIN_FIELDS": "10",
}


def _find_config_path():
    env = os.environ.get("WITMOTION_BRIDGE_CONFIG")
    if env and os.path.isfile(env):
        return env
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "config.env"))
    except NameError:
        pass  # __file__ no definido (texto sin guardar en el editor de Blender)
    candidates.append(os.path.join(os.getcwd(), "config.env"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _load_config():
    cfg = dict(_DEFAULTS)
    path = _find_config_path()
    if path is None:
        print("[wifi-bridge] AVISO: no se encontró config.env; usando valores por defecto.")
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip()
        print(f"[wifi-bridge] Config cargada de: {path}")
    except Exception as e:
        print(f"[wifi-bridge] AVISO: error leyendo {path}: {e}. Usando valores por defecto.")
    return cfg


def _parse_device_map(raw, default_object):
    """DEVICE_MAP 'A:Obj1,B:Obj2,*:Cube' -> dict {DeviceID: objeto}.
    La clave '*' es el comodín para sensores no listados."""
    mapping = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        dev, _, obj = pair.partition(":")
        mapping[dev.strip()] = obj.strip()
    if "*" not in mapping:
        mapping["*"] = default_object
    return mapping


_cfg = _load_config()

# ---------- CONFIGURACIÓN EFECTIVA ----------
LISTEN_HOST = _cfg["LISTEN_HOST"]
LISTEN_PORT = int(_cfg["LISTEN_PORT"])
DEFAULT_OBJECT = _cfg["DEFAULT_OBJECT"]
DEVICE_MAP = _parse_device_map(_cfg["DEVICE_MAP"], DEFAULT_OBJECT)
AUTO_CALIBRATE = _cfg["AUTO_CALIBRATE"] == "1"
CALIB_COUNTDOWN = float(_cfg["CALIB_COUNTDOWN"])
SIGN_ROLL = float(_cfg["SIGN_ROLL"])
SIGN_PITCH = float(_cfg["SIGN_PITCH"])
SIGN_YAW = float(_cfg["SIGN_YAW"])
IDX_DEVICE = int(_cfg["IDX_DEVICE"])
IDX_ANGLE_X = int(_cfg["IDX_ANGLE_X"])
IDX_ANGLE_Y = int(_cfg["IDX_ANGLE_Y"])
IDX_ANGLE_Z = int(_cfg["IDX_ANGLE_Z"])
MIN_FIELDS = int(_cfg["MIN_FIELDS"])

# ---------- ESTADO GLOBAL ----------
_sock = None
_offsets = {}          # DeviceID -> Quaternion de referencia inversa (cero)
_last_quat = {}        # DeviceID -> último cuaternión medido (para calibrar bajo demanda)
_seen_devices = set()  # DeviceIDs vistos en esta sesión
_calib_deadline = None  # instante hasta el que se pospone la autocalibración


def _object_for_device(device_id):
    """Resuelve el objeto de Blender asignado a un DeviceID (o el comodín)."""
    name = DEVICE_MAP.get(device_id, DEVICE_MAP.get("*", DEFAULT_OBJECT))
    return bpy.data.objects.get(name)


def _angles_to_quat(ax_deg, ay_deg, az_deg):
    """Convierte los ángulos (grados) del sensor a un cuaternión.

    WitMotion define la actitud con orden de Euler Z-Y-X (primero Z, luego
    Y, luego X). En mathutils, Euler((rx,ry,rz), 'XYZ') aplica X,Y,Z; para
    replicar Z-Y-X usamos el orden 'ZYX' con los ángulos en radianes.
    Los signos SIGN_* permiten invertir un eje según el montaje físico.

    Si al probar en real algún giro sale invertido o cruzado, este es el
    punto a ajustar (orden de Euler y/o SIGN_*).
    """
    from math import radians
    e = Euler(
        (
            radians(SIGN_ROLL * ax_deg),
            radians(SIGN_PITCH * ay_deg),
            radians(SIGN_YAW * az_deg),
        ),
        "ZYX",
    )
    return e.to_quaternion()


def _parse_datagram(data):
    """Parsea un datagrama UDP a (device_id, quat) o None si no es válido.

    El WT901WIFI emite CSV ASCII terminado en \\r\\n. Un datagrama puede
    contener una o varias líneas; procesamos la última línea completa.
    Los índices de campo son configurables (IDX_*) porque el layout exacto
    puede variar con el firmware.
    """
    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not text:
        return None
    line = text.splitlines()[-1].strip()  # última línea completa del datagrama
    parts = line.split(",")
    if len(parts) < MIN_FIELDS:
        return None
    try:
        device_id = parts[IDX_DEVICE].strip()
        ax = float(parts[IDX_ANGLE_X])
        ay = float(parts[IDX_ANGLE_Y])
        az = float(parts[IDX_ANGLE_Z])
    except (ValueError, IndexError):
        return None
    return device_id, _angles_to_quat(ax, ay, az)


def _apply(device_id, quat):
    """Aplica la orientación (con offset de calibración) al objeto asignado."""
    _last_quat[device_id] = quat
    if device_id not in _seen_devices:
        _seen_devices.add(device_id)
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(sin objeto asignado)"
        print(f"[wifi-bridge] Nuevo sensor: {device_id} -> {target}")

    obj = _object_for_device(device_id)
    if obj is None:
        return

    offset = _offsets.get(device_id)
    corrected = (offset @ quat) if offset is not None else quat

    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = corrected


def _pump():
    """Se ejecuta periódicamente vía bpy.app.timers sin bloquear la UI.
    Drena todos los datagramas pendientes en cada tick."""
    global _sock, _calib_deadline
    if _sock is None:
        return 0.1

    # Autocalibración diferida: al vencer el countdown, capturar la pose.
    if _calib_deadline is not None and time.time() >= _calib_deadline:
        _calib_deadline = None
        calibrate()

    # Drenar el buffer del socket (no bloqueante)
    for _ in range(200):  # tope por tick para no colgar la UI si hay avalancha
        try:
            data, _addr = _sock.recvfrom(2048)
        except BlockingIOError:
            break
        except Exception:
            break
        parsed = _parse_datagram(data)
        if parsed is not None:
            _apply(parsed[0], parsed[1])

    return 0.001  # polling continuo


# ---------- CONTROL / UTILIDADES ----------
def calibrate():
    """Captura la orientación ACTUAL de cada sensor visto como pose de
    referencia (cero). Aplica el inverso a las lecturas siguientes.
    Llama a esto con la persona/objeto en la pose de referencia (T-pose)."""
    n = 0
    for device_id, quat in _last_quat.items():
        _offsets[device_id] = quat.inverted()
        n += 1
    if n:
        print(f"[wifi-bridge] Pose de referencia capturada para {n} sensor(es).")
    else:
        print("[wifi-bridge] AVISO: aún no hay datos de ningún sensor para calibrar.")


def recenter(device_id):
    """Recalibra un sensor concreto por su DeviceID (pone su pose actual a 0)."""
    quat = _last_quat.get(device_id)
    if quat is None:
        print(f"[wifi-bridge] No hay datos del sensor '{device_id}' todavía.")
        return
    _offsets[device_id] = quat.inverted()
    print(f"[wifi-bridge] Sensor '{device_id}' recentrado.")


def list_devices():
    """Muestra los DeviceIDs vistos en esta sesión y su objeto asignado."""
    if not _seen_devices:
        print("[wifi-bridge] Aún no se ha recibido ningún sensor.")
        return
    print("[wifi-bridge] Sensores vistos:")
    for device_id in sorted(_seen_devices):
        obj = _object_for_device(device_id)
        target = obj.name if obj else "(sin objeto)"
        calib = "sí" if device_id in _offsets else "no"
        print(f"    {device_id} -> {target}   [calibrado: {calib}]")


def start_bridge():
    global _sock, _calib_deadline
    try:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _sock.bind((LISTEN_HOST, LISTEN_PORT))
        _sock.setblocking(False)
        print(f"[wifi-bridge] Escuchando UDP en {LISTEN_HOST}:{LISTEN_PORT}")
    except Exception as e:
        print(f"[wifi-bridge] ERROR abriendo socket UDP: {e}")
        _sock = None
        return

    if AUTO_CALIBRATE:
        _calib_deadline = time.time() + CALIB_COUNTDOWN
        print(f"[wifi-bridge] Autocalibración en {CALIB_COUNTDOWN:.0f}s: "
              f"coloca el/los sensor(es) en la pose de referencia (T-pose).")

    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump)
    print("[wifi-bridge] Bridge iniciado. Mueve el sensor para ver el objeto reaccionar.")
    print("[wifi-bridge] Usa calibrate() para fijar el cero, list_devices() para ver sensores.")


def stop_bridge():
    global _sock
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _sock is not None:
        _sock.close()
        _sock = None
    print("[wifi-bridge] Bridge detenido.")


# Al ejecutar el script directamente en Blender, arranca el bridge.
if __name__ == "__main__":
    start_bridge()

# Para detenerlo manualmente desde la consola Python de Blender:
#   stop_bridge()
