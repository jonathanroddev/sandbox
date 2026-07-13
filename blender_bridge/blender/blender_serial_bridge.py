"""
blender_serial_bridge.py
-------------------------
Ejecutar DENTRO de Blender (pestaña Scripting -> Text Editor -> Run Script).

Lee líneas CSV del Arduino (MPU-6050) por el puerto serial:
    ax,ay,az,gx,gy,gz

Calcula roll/pitch/yaw y los aplica al objeto indicado en OBJECT_NAME:
  - Acelerómetro + giroscopio -> roll y pitch (filtro complementario).
    Son ABSOLUTOS y estables (referencia de gravedad).
  - Giroscopio integrado -> yaw. NO hay magnetómetro en el MPU-6050, así
    que el yaw NO tiene referencia absoluta y DERIVA lentamente con el
    tiempo. Se puede poner a cero cuando se quiera con recenter_yaw().

REQUISITOS:
  Blender trae su propio intérprete de Python, así que hay que instalar
  pyserial dentro de ESE python, no en el del sistema. Desde terminal:

      /Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial

  (encuentra la ruta ejecutando en la consola Python de Blender:
      import sys; print(sys.exec_prefix)
  )

USO RÁPIDO (en la consola Python de Blender, tras Run Script):
    start_bridge()      # arranca (calibra el bias del giroscopio ~1s en reposo)
    recenter_yaw()      # pone el yaw actual a 0 (corrige la deriva acumulada)
    recenter_all()      # pone roll/pitch/yaw a 0
    stop_bridge()       # detiene y cierra el puerto

NOTA SOBRE LA DERIVA DEL YAW:
  Es inherente al hardware (sin magnetómetro). Para minimizarla, al
  arrancar se estima el bias del giroscopio dejando el sensor QUIETO
  durante ~1 segundo. Aun así, algo de deriva quedará; usa recenter_yaw()
  cuando lo necesites (por ejemplo, mapeando una tecla a esa función).
"""

import bpy
import serial
import math
import time
import os

# ---------- CARGA DE CONFIGURACIÓN (config.env) ----------
# Todo lo que suele cambiar entre PCs/escenas vive en config.env, no aquí.
# El fichero se resuelve, en orden:
#   1) variable de entorno BLENDER_BRIDGE_CONFIG (ruta absoluta), si existe.
#   2) config.env junto a este script (cuando __file__ está definido).
#   3) config.env en el directorio de trabajo actual.
# Si no se encuentra, se usan los valores por defecto de _DEFAULTS.

_DEFAULTS = {
    "SERIAL_PORT": "/dev/cu.usbmodem11201",
    "BAUD_RATE": "115200",
    "OBJECT_NAME": "Cube",
    "ALPHA_ROLL_PITCH": "0.98",
    "GYRO_CALIB_SAMPLES": "50",
    "SIGN_ROLL": "1",
    "SIGN_PITCH": "1",
    "SIGN_YAW": "1",
}


def _find_config_path():
    env = os.environ.get("BLENDER_BRIDGE_CONFIG")
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
    """Lee config.env (CLAVE=valor) y devuelve un dict, con _DEFAULTS de base."""
    cfg = dict(_DEFAULTS)
    path = _find_config_path()
    if path is None:
        print("[bridge] AVISO: no se encontró config.env; usando valores por defecto.")
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip()
        print(f"[bridge] Config cargada de: {path}")
    except Exception as e:
        print(f"[bridge] AVISO: error leyendo {path}: {e}. Usando valores por defecto.")
    return cfg


_cfg = _load_config()

# ---------- CONFIGURACIÓN EFECTIVA ----------
SERIAL_PORT = _cfg["SERIAL_PORT"]
BAUD_RATE = int(_cfg["BAUD_RATE"])
OBJECT_NAME = _cfg["OBJECT_NAME"]
ALPHA_ROLL_PITCH = float(_cfg["ALPHA_ROLL_PITCH"])   # Peso del giroscopio en roll/pitch
GYRO_CALIB_SAMPLES = int(_cfg["GYRO_CALIB_SAMPLES"])  # Muestras para el bias del giroscopio
SIGN_ROLL = float(_cfg["SIGN_ROLL"])                 # Signo de eje (+1 / -1) según montaje
SIGN_PITCH = float(_cfg["SIGN_PITCH"])
SIGN_YAW = float(_cfg["SIGN_YAW"])

# ---------- ESTADO GLOBAL ----------
_ser = None
_roll = 0.0
_pitch = 0.0
_yaw = 0.0
_last_time = None
_bias_gx = 0.0
_bias_gy = 0.0
_bias_gz = 0.0


def _open_serial():
    global _ser
    try:
        _ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2)  # Dar tiempo a que el Arduino reinicie tras abrir el puerto
        _ser.reset_input_buffer()
        print(f"[bridge] Puerto serial abierto: {SERIAL_PORT}")
    except Exception as e:
        print(f"[bridge] ERROR abriendo puerto serial: {e}")
        _ser = None


def _parse_line(line):
    """Devuelve (ax,ay,az,gx,gy,gz) o None si la línea no es válida."""
    parts = line.split(",")
    if len(parts) != 6:
        return None
    try:
        return tuple(map(float, parts))
    except ValueError:
        return None


def _calibrate_gyro_bias():
    """Promedia varias lecturas con el sensor QUIETO para estimar el bias
    del giroscopio (offset que, integrado, causaría deriva)."""
    global _bias_gx, _bias_gy, _bias_gz
    if _ser is None:
        return
    print("[bridge] Calibrando bias del giroscopio: MANTÉN EL SENSOR QUIETO...")
    sx = sy = sz = 0.0
    n = 0
    t_end = time.time() + 3.0  # como máximo 3s buscando muestras
    while n < GYRO_CALIB_SAMPLES and time.time() < t_end:
        line = _ser.readline().decode("utf-8", errors="ignore").strip()
        vals = _parse_line(line)
        if vals is None:
            continue
        _, _, _, gx, gy, gz = vals
        sx += gx; sy += gy; sz += gz
        n += 1
    if n > 0:
        _bias_gx = sx / n
        _bias_gy = sy / n
        _bias_gz = sz / n
        print(f"[bridge] Bias giroscopio (°/s): "
              f"gx={_bias_gx:.3f} gy={_bias_gy:.3f} gz={_bias_gz:.3f}  ({n} muestras)")
    else:
        print("[bridge] AVISO: no se pudo calibrar el bias (sin datos). Bias = 0.")


def _complementary_filter(ax, ay, az, gx, gy, gz, dt):
    global _roll, _pitch, _yaw

    # Restar el bias estimado del giroscopio
    gx -= _bias_gx
    gy -= _bias_gy
    gz -= _bias_gz

    # --- Roll/pitch: acelerómetro (absoluto) + giroscopio (suave) ---
    accel_roll = math.degrees(math.atan2(ay, az))
    accel_pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))

    gyro_roll = _roll + gx * dt
    gyro_pitch = _pitch + gy * dt

    _roll = ALPHA_ROLL_PITCH * gyro_roll + (1 - ALPHA_ROLL_PITCH) * accel_roll
    _pitch = ALPHA_ROLL_PITCH * gyro_pitch + (1 - ALPHA_ROLL_PITCH) * accel_pitch

    # --- Yaw: SOLO giroscopio integrado (sin magnetómetro -> deriva) ---
    _yaw += gz * dt

    return _roll, _pitch, _yaw


def _read_serial_and_update():
    """Se ejecuta periódicamente vía bpy.app.timers sin bloquear la UI."""
    global _ser, _last_time

    if _ser is None:
        return 0.1  # reintentar en 0.1s

    line = _ser.readline().decode("utf-8", errors="ignore").strip()
    vals = _parse_line(line)
    if vals is None:
        return 0.001  # sin datos nuevos o línea corrupta, reintentar pronto

    ax, ay, az, gx, gy, gz = vals

    now = time.time()
    dt = (now - _last_time) if _last_time is not None else 0.02
    _last_time = now

    roll, pitch, yaw = _complementary_filter(ax, ay, az, gx, gy, gz, dt)

    obj = bpy.data.objects.get(OBJECT_NAME)
    if obj:
        obj.rotation_euler = (
            math.radians(SIGN_ROLL * roll),
            math.radians(SIGN_PITCH * pitch),
            math.radians(SIGN_YAW * yaw),
        )

    return 0.001  # polling continuo


# ---------- CONTROL / UTILIDADES ----------
def recenter_yaw():
    """Pone el yaw actual a 0 (corrige la deriva acumulada del giroscopio)."""
    global _yaw
    _yaw = 0.0
    print("[bridge] Yaw recentrado a 0.")


def recenter_all():
    """Pone roll/pitch/yaw a 0."""
    global _roll, _pitch, _yaw
    _roll = _pitch = _yaw = 0.0
    print("[bridge] Roll/pitch/yaw recentrados a 0.")


def start_bridge():
    _open_serial()
    if _ser is not None:
        _calibrate_gyro_bias()
    if not bpy.app.timers.is_registered(_read_serial_and_update):
        bpy.app.timers.register(_read_serial_and_update)
    print("[bridge] Bridge iniciado. Mueve el sensor para ver el objeto reaccionar.")
    print("[bridge] Si el yaw se desvía, llama a recenter_yaw().")


def stop_bridge():
    global _ser, _last_time
    if bpy.app.timers.is_registered(_read_serial_and_update):
        bpy.app.timers.unregister(_read_serial_and_update)
    if _ser is not None:
        _ser.close()
        _ser = None
    _last_time = None
    print("[bridge] Bridge detenido.")


# Al ejecutar el script directamente en Blender, arranca el bridge.
if __name__ == "__main__":
    start_bridge()

# Para detenerlo manualmente desde la consola Python de Blender:
#   stop_bridge()
