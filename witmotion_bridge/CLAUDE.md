# Guía para Claude Code — witmotion_bridge

Contexto rápido para trabajar en este proyecto con el hardware conectado.
Lee también `docs/CONTEXT.md` para el detalle de decisiones y protocolo.

## Qué es esto
Puente WiFi de sensor(es) **WitMotion WT901WIFI** a **Blender**. El sensor
entrega ángulos ya fusionados (Kalman interno) por UDP; el receptor los
parsea por DeviceID, los calibra contra una pose de referencia (en
cuaterniones) y mueve objetos de la escena. Hermano de `../blender_bridge/`
(versión Arduino+MPU por serial).

## Reglas del repo (heredadas de sandbox)
- Cada proyecto es una carpeta autocontenida de nivel superior.
- **Toda la configuración va en `blender/config.env`** (formato CLAVE=valor,
  sin comillas, se lee sin dependencias externas). No hardcodear rutas,
  puertos ni nombres de objeto en el código.
- Comentarios y mensajes al usuario **en español**.
- El código de Blender no debe bloquear la UI: usar `bpy.app.timers`.
- El bridge usa **solo librería estándar + `mathutils`** (viene con
  Blender). No añadir dependencias sin justificarlo.

## Estado actual
- `blender/blender_udp_bridge.py` — receptor UDP funcional: parseo por
  DeviceID, calibración por pose con cuaterniones, mapeo sensor→objeto,
  utilidades (`calibrate`, `recenter`, `list_devices`, `start/stop_bridge`).
- `blender/config.env` — puerto, `DEVICE_MAP`, autocalibración, signos de
  eje, e índices de campo del CSV (`IDX_*`).
- `tools/read_udp.py` — diagnóstico UDP fuera de Blender.

## Incertidumbre conocida (resolver primero, con el sensor delante)
1. **Formato exacto del CSV.** Los índices de campo (`IDX_ANGLE_X/Y/Z=7,8,9`
   y `IDX_DEVICE=0`) vienen de la documentación del producto, pero pueden
   variar con el firmware. Ejecuta `python3 tools/read_udp.py 1399 10`,
   mira las líneas reales, y ajusta los `IDX_*` en `config.env` si hace
   falta. NO cambies el código para esto: cambia la config.
2. **Marco de ejes sensor vs Blender.** El sensor usa orden de Euler Z-Y-X
   y su propio marco; Blender es Z-up. El mapeo inicial es directo con
   signos configurables. Verifica moviendo el sensor un eje cada vez y
   ajusta `SIGN_ROLL/PITCH/YAW` o el orden en `_angles_to_quat()`.

## Tareas sugeridas (en orden)
1. **Validar recepción**: `tools/read_udp.py`; confirmar DeviceID, nº de
   campos y posición de los ángulos. Ajustar `config.env` si procede.
2. **Un sensor en Blender**: `DEFAULT_OBJECT` al objeto de la escena, Run
   Script, autocalibrar en pose de referencia, comprobar ejes/sentidos.
3. **Afinar mapeo de ejes** hasta que el objeto siga fielmente al sensor.
4. **Multi-sensor**: con varios sensores emitiendo, `list_devices()` para
   ver los DeviceIDs y rellenar `DEVICE_MAP` (DeviceID:Objeto).
5. **Mapear a un armature**: evolucionar de objetos sueltos a
   `pose.bones[...]`, resolviendo orientación de cada hueso relativa a su
   padre. Este es el corazón del traje.
6. **Opcional**: si el firmware incluye cuaternión nativo en la trama,
   usarlo en lugar de convertir desde Euler (evita ambigüedad de orden).

## Cómo probar sin hardware
`tools/fake_sensor.py` es un emisor UDP falso que imita al WT901WIFI:
envía tramas CSV con el layout por defecto (13 campos, ángulos animados) al
puerto de `config.env`. Sirve para validar parseo y calibración antes de
tener el sensor en red, y como referencia contra la que contrastar el
sensor real cuando se conecte.

    # Terminal 1: comprobar que llegan tramas y su formato
    python3 tools/read_udp.py 1399 3
    # Terminal 2: emitir (un sensor, indefinido)
    python3 tools/fake_sensor.py
    # Multi-sensor de prueba (dos DeviceID, 100 Hz):
    python3 tools/fake_sensor.py 1399 0 100 127.0.0.1 WT53abc,WT53def

En Blender: Run Script del bridge y, en paralelo, lanzar `fake_sensor.py`
-> el objeto de `DEFAULT_OBJECT`/`DEVICE_MAP` debe oscilar. Verificado
extremo a extremo (fake_sensor -> read_udp): 13 campos, DeviceID en índice
0, ángulos en 7/8/9, coherente con los `IDX_*`.

Nota: el emisor reproduce el layout POR DEFECTO documentado. Cuando llegue
el sensor REAL, si `read_udp.py` muestra otro orden/nº de campos, se ajusta
en `config.env` (`IDX_*`), no en el código.
