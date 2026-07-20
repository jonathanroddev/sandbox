# witmotion_bridge

Puente en tiempo real de uno o varios sensores **WitMotion WT901WIFI** a
**Blender** por WiFi (UDP). Es el paso hacia un traje de captura de
movimiento multi-sensor, y hermano de [`blender_bridge/`](../blender_bridge/)
(la versión Arduino + MPU por USB serial).

A diferencia del MPU, el WT901WIFI ya entrega ángulos fusionados por su
propio filtro de Kalman: aquí solo se reciben por red, se calibran contra
una pose de referencia y se aplican al objeto.

## Estructura

```
witmotion_bridge/
├── blender/
│   ├── blender_udp_bridge.py   # receptor UDP para ejecutar dentro de Blender
│   └── config.env              # toda la configuración (puerto, mapeo, ejes)
├── tools/
│   ├── read_udp.py             # lector UDP de diagnóstico (fuera de Blender)
│   └── fake_sensor.py          # emisor UDP falso: imita al WT901WIFI (probar sin hardware)
├── docs/
│   ├── CONTEXT.md              # decisiones, protocolo y setup del sensor
│   └── SETUP_HARDWARE.md       # guía paso a paso para conectar el sensor real
└── CLAUDE.md                   # guía de tareas para Claude Code
```

## Requisitos

- Un **WT901WIFI** en la misma red WiFi que el ordenador (ver setup en
  [`docs/CONTEXT.md`](docs/CONTEXT.md)).
- **Blender** (el receptor usa solo la librería estándar de Python +
  `mathutils`, que ya viene con Blender: nada que instalar).

## Uso rápido

1. Configura el sensor en Station mode apuntando a la IP de tu equipo y al
   puerto de `config.env` (por defecto 1399). Detalles en `docs/CONTEXT.md`.
2. Valida las tramas sin Blender:
   ```
   python3 tools/read_udp.py 1399 10
   ```
   ¿Sin sensor todavía? Emite tramas falsas en otra terminal para probar el
   flujo completo:
   ```
   python3 tools/fake_sensor.py
   ```
3. Ajusta `DEFAULT_OBJECT` (y `DEVICE_MAP`) en `blender/config.env`.
4. En Blender: pestaña Scripting → abre `blender/blender_udp_bridge.py` →
   Run Script. Coloca el sensor en la pose de referencia durante el
   countdown de autocalibración.

Funciones útiles en la consola Python de Blender:
`start_bridge()`, `calibrate()`, `recenter(device_id)`, `list_devices()`,
`stop_bridge()`.

## Estado

MVP de recepción + calibración por pose, **validado de punta a punta en
software** (`fake_sensor.py` → `read_udp.py`: 13 campos, DeviceID en índice
0, ángulos en 7/8/9). Pendiente de probar con el sensor real: seguir
[`docs/SETUP_HARDWARE.md`](docs/SETUP_HARDWARE.md) para conectarlo, confirmar
el formato del CSV y afinar el mapeo de ejes. El receptor ya soporta
multi-sensor por DeviceID; el mapeo a un armature del traje es el siguiente
paso (ver `CLAUDE.md`).
