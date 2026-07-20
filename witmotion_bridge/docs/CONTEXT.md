# Contexto: Puente WitMotion WT901WIFI → Blender

## Objetivo
Recibir la orientación de uno o varios sensores WitMotion WT901WIFI por
WiFi y aplicarla en tiempo real a objetos de Blender. Es el paso hacia un
traje de captura de movimiento multi-sensor.

## Relación con `blender_bridge/`
Este proyecto es hermano de `blender_bridge/` (el puente Arduino+MPU por
USB serial). Comparte convenciones (config.env sin dependencias, patrón
`bpy.app.timers` no bloqueante, utilidades de recentrado), pero cambia el
transporte y el reparto de trabajo:

| | blender_bridge (MPU serial) | witmotion_bridge (WT901WIFI) |
|---|---|---|
| Fusión de sensores | La hace el script (filtro complementario) | Interna del sensor (Kalman) |
| Transporte | USB serial (`pyserial`) | WiFi, socket UDP (stdlib) |
| Datos recibidos | Raw accel+gyro | Ángulos ya fusionados + DeviceID |
| Multi-sensor | Complicado | Nativo (un socket, varios DeviceID) |
| Poner a cero | `recenter_yaw()` (solo yaw) | `calibrate()` (pose completa, cuaternión) |

## El sensor: WT901WIFI
- Construido sobre un MPU9250 (accel+gyro+magnetómetro) con un MCU propio
  que corre el filtro de Kalman de WitMotion; entrega actitud de bajo drift.
- Transmite por WiFi 2.4 GHz, hasta 200 Hz, vía UDP o TCP (se elige UNO).
- Soporta múltiples dispositivos en la misma red -> ideal para el traje.
- Batería interna (~3 h de autonomía según tasa de datos).

## Decisiones de arquitectura tomadas
1. **UDP, no TCP.** Menor latencia; si se pierde un paquete se descarta y
   se usa el siguiente, en vez de retransmitir una pose ya obsoleta. Para
   streaming de captura de movimiento es lo habitual. (No hay cadena
   "UDP y luego TCP": es un único transporte; lo de "configura primero en
   UDP" del manual es solo para no perder la conexión al pasar AP→Station.)
2. **La fusión ya viene hecha por el sensor.** Aquí no se filtra: se parsea,
   se calibra y se aplica. El script es sustancialmente más simple que el
   del MPU.
3. **Calibración por POSE de referencia, en software, con cuaterniones.**
   Al arrancar (o al llamar a `calibrate()`) se captura la orientación de
   cada sensor como "cero" y se aplica su inverso a las lecturas. Ventajas
   frente al "Z-axis zero return" del sensor:
   - Calibra los tres ejes, no solo el yaw.
   - Uniforme para todos los sensores del traje.
   - No obliga a pasar a modo 6 ejes (que reintroduce deriva de yaw); se
     conserva el yaw absoluto de 9 ejes.
   - Cuaterniones -> sin gimbal lock; el "cero" es una multiplicación.
4. **Mapeo sensor→objeto por DeviceID** (config.env `DEVICE_MAP`), con
   comodín `*` para el caso de un solo sensor de prueba.

## Archivos
- `blender/blender_udp_bridge.py` — Receptor UDP para ejecutar dentro de
  Blender. Parsea por DeviceID, calibra contra pose de referencia y mueve
  los objetos vía `rotation_quaternion`.
- `blender/config.env` — Toda la configuración (puerto, mapeo de sensores,
  calibración, signos de eje, índices de campo del CSV).
- `tools/read_udp.py` — Lector UDP de diagnóstico (fuera de Blender), para
  validar el formato real de las tramas antes de tocar Blender.
- `tools/fake_sensor.py` — Emisor UDP falso que imita al WT901WIFI (layout
  por defecto, ángulos animados). Permite probar parseo/calibración y el
  flujo completo en Blender SIN el sensor en red, y sirve de referencia
  contra la que contrastar el sensor real cuando se conecte.

## Puesta a punto del sensor (una vez)
1. Con la app/PC de WitMotion, configura el WT901WIFI en **Station mode**
   para que se una a tu router. Recomendación del manual: al migrar desde
   AP mode, cambia primero a **UDP** (no directo a TCP), o puedes perder la
   conexión y tener que resetear (botón 2 s) o reconfigurar por serie.
2. Fija el **user server IP** = IP de tu Mac en la LAN, y el **port** =
   el mismo `LISTEN_PORT` de config.env (por defecto 1399).
3. Asegúrate de que Mac y sensor están en la MISMA red WiFi.

## Cómo probar (orden recomendado)
1. **Validar tramas SIN Blender:**
       python3 tools/read_udp.py 1399 10
   Comprobar que llegan líneas, que empiezan por el DeviceID y cuántos
   campos tienen. Si el orden de los ángulos no es 7,8,9, ajustar los
   `IDX_ANGLE_*` en config.env.
2. **Instalar nada** (el bridge usa solo stdlib + mathutils de Blender).
3. **En Blender:** ajustar `DEVICE_MAP`/`DEFAULT_OBJECT` al objeto de la
   escena, abrir `blender/blender_udp_bridge.py` en Scripting y Run Script.
   Con `AUTO_CALIBRATE=1`, colocar el sensor en la pose de referencia
   durante el countdown inicial.
4. Mover el sensor y verificar que el objeto gira en el eje/sentido
   correctos. Si algún eje va invertido o cruzado, ajustar `SIGN_*` (o el
   orden de Euler en `_angles_to_quat`).

## Pendiente / próximos pasos
> Guía operativa paso a paso para el hardware: `SETUP_HARDWARE.md`.
> Software validado de punta a punta (fake_sensor → read_udp) el 2026-07-20;
> lo pendiente es todo con el sensor real y en Blender.
- [ ] **Verificar el formato real del CSV** con `read_udp.py` y confirmar
      los índices de campo (el layout puede variar con el firmware).
- [ ] **Calibrar el mapeo de ejes** sensor→Blender con el sensor montado
      como irá en el traje (marco del sensor vs Z-up de Blender).
- [ ] **Salto a multi-sensor:** listar los DeviceIDs reales (`list_devices()`)
      y rellenar `DEVICE_MAP` con la asignación a huesos/objetos. El
      receptor ya soporta varios sensores sin cambios.
- [ ] **Mapear a un armature:** en vez de objetos sueltos, aplicar cada
      cuaternión al `pose.bones[...]` correspondiente, resolviendo la
      jerarquía (orientación de hueso relativa al padre).
- [ ] Evaluar usar el **cuaternión nativo** del sensor si el firmware lo
      incluye en la trama (evita la conversión Euler→quat y su orden).
- [ ] Revisar rendimiento con varios sensores a 100–200 Hz (el tope de
      200 datagramas/tick del `_pump` es ajustable).

## Notas para Claude Code
Ver `../CLAUDE.md` en la raíz del proyecto para la lista de tareas y el
orden sugerido de trabajo con el hardware conectado.
