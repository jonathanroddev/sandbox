# Blender Bridge — Arduino (MPU-6050) → Blender

Puente en tiempo real que lee la orientación de un sensor de movimiento
**MPU-6050** conectado a un **Arduino Uno** por USB y la aplica a un objeto
de una escena de **Blender** (roll/pitch/yaw).

- **Roll y pitch**: absolutos y estables (acelerómetro + giroscopio con
  filtro complementario; referencia de gravedad).
- **Yaw**: solo giroscopio integrado → **deriva** lentamente (el MPU-6050
  no tiene magnetómetro). Se corrige a mano con `recenter_yaw()`.
- **Posición**: fuera de alcance.

Contexto técnico completo y decisiones de arquitectura: [`docs/CONTEXT.md`](docs/CONTEXT.md).
Hardware y su puesta a punto: [`docs/SETUP_HARDWARE.md`](docs/SETUP_HARDWARE.md).

## Estructura

```
blender_bridge/
├── arduino/
│   ├── mpu_serial_bridge/   Sketch principal: lee accel+gyro y emite CSV
│   └── i2c_diag/            Diagnóstico I2C (WHO_AM_I, escaneo de bus)
├── blender/
│   ├── blender_serial_bridge.py   Script a ejecutar DENTRO de Blender
│   └── config.env                 ÚNICO fichero que sueles tocar
├── tools/
│   └── read_serial.py       Volcado serial de diagnóstico (Python del sistema)
├── backups/                 Respaldo de flash/EEPROM originales del Uno
└── docs/                    Contexto y setup de hardware
```

El sensor envía por serial (115200 baudios, ~50 Hz) una línea CSV por lectura:

```
ax,ay,az,gx,gy,gz        # accel en g, gyro en °/s
```

## Puesta a punto

### 1. Flashear el Arduino

Con `arduino-cli` (core `arduino:avr` instalado):

```bash
arduino-cli compile --fqbn arduino:avr:uno arduino/mpu_serial_bridge
arduino-cli upload -p /dev/cu.usbmodem11201 --fqbn arduino:avr:uno arduino/mpu_serial_bridge
```

Ajusta el puerto a tu sistema:
- macOS: `ls /dev/cu.*` → p.ej. `/dev/cu.usbmodem11201`
- Linux: `ls /dev/ttyACM* /dev/ttyUSB*` → p.ej. `/dev/ttyACM0`
- Windows: Administrador de dispositivos → p.ej. `COM3`

### 2. Verificar el CSV crudo (sin Blender)

Con el **Python del sistema** (necesita `pyserial`):

```bash
python3 tools/read_serial.py /dev/cu.usbmodem11201 6 115200
```

Debes ver 6 valores por línea y, con el sensor quieto, `|accel| ≈ 1.0 g`.

### 3. Instalar `pyserial` en el Python DE BLENDER

Blender trae su **propio** intérprete de Python; `pyserial` hay que
instalarlo ahí, no en el del sistema. Averigua su ruta desde la consola
Python de Blender:

```python
import sys; print(sys.exec_prefix)
```

y luego, desde una terminal:

```bash
/Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial
```

(En Linux/Windows la ruta será distinta, dentro de la instalación de Blender.)

### 4. Configurar `blender/config.env`

**No hace falta editar el `.py`.** Toca solo `config.env`:

- `SERIAL_PORT` → el puerto de tu sistema (ver paso 1).
- `OBJECT_NAME` → nombre EXACTO del objeto de la escena que se moverá.
- Resto de parámetros (filtro, mapeo de ejes): ver más abajo.

### 5. Ejecutar en Blender

1. Pestaña **Scripting** → **Text Editor** → abre
   `blender/blender_serial_bridge.py` desde disco (**Open**, no pegar el
   texto: así el script encuentra el `config.env` que tiene al lado, ver
   más abajo).
2. **Run Script**.
3. Mantén el sensor **quieto ~1 s** al arrancar (calibra el bias del giro).
4. Mueve el sensor y comprueba que el objeto reacciona.

Control desde la **consola Python** de Blender:

```python
start_bridge()    # arranca (calibra el bias del giroscopio en reposo)
recenter_yaw()    # pone el yaw actual a 0 (corrige la deriva acumulada)
recenter_all()    # pone roll/pitch/yaw a 0
stop_bridge()     # detiene y cierra el puerto
```

## Calibración del mapeo de ejes

Depende de **cómo esté montado físicamente** el sensor. En `config.env`:

- **`SIGN_ROLL` / `SIGN_PITCH` / `SIGN_YAW`** (`+1` / `-1`): invierten el
  **sentido** de un eje que gira "al revés".
- **`AXIS_MAP`**: **permuta** qué fuente (roll/pitch/yaw) va a cada eje de
  Blender, en orden **X,Y,Z**. Esto arregla el síntoma *"muevo un eje y
  responde otro"*, que los signos NO pueden corregir. Cada token es
  `roll`/`pitch`/`yaw`, con prefijo `-` opcional para invertir.

  | AXIS_MAP | Efecto |
  |---|---|
  | `roll,pitch,yaw` | Identidad (clásico): X=roll, Y=pitch, Z=yaw |
  | `pitch,roll,yaw` | Intercambia roll y pitch |
  | `roll,pitch,-yaw` | Igual que identidad pero yaw invertido |

**Procedimiento** (con el bridge corriendo, aislando un eje cada vez):

| Giras físicamente… | Debería mover el eje… | ¿Cuál mueve? |
|---|---|---|
| roll (sobre X del sensor) | X de Blender | ? |
| pitch (sobre Y del sensor) | Y de Blender | ? |
| yaw (vertical) | Z de Blender | ? |

Si un giro aparece en otro eje, coloca esa fuente en la posición X/Y/Z que
corresponda dentro de `AXIS_MAP`. Si aparece invertido, añádele el `-`.

> El `config.env` incluido trae `AXIS_MAP=pitch,roll,yaw` como **ejemplo
> razonado sin hardware a mano** (el "roll" del sensor va sobre su eje X,
> pero el eje longitudinal en Blender suele ser +Y). Ajústalo con la tabla.

## Filtro / tuning

- `ALPHA_ROLL_PITCH` (0..1): peso del giroscopio en roll/pitch. Más alto =
  más suave pero lento a corregir; más bajo = más reactivo (más nervioso).
- `GYRO_CALIB_SAMPLES`: muestras en reposo para estimar el bias del
  giroscopio al arrancar.

## Cómo se localiza el `config.env`

El script busca el `config.env` en este orden:

1. Ruta absoluta en la variable de entorno `BLENDER_BRIDGE_CONFIG`, si existe.
2. Junto al `.py` (cuando `__file__` está definido).
3. **Carpetas deducidas de Blender**: la del `.py` abierto como texto
   externo y la del `.blend` guardado.
4. El directorio de trabajo actual.
5. Si no lo encuentra, usa los valores por defecto internos del script.

> **Nota (problema conocido):** dentro del Text Editor de Blender, `__file__`
> a menudo **no existe** y `os.getcwd()` no apunta a la carpeta del script,
> por lo que el `config.env` "de al lado" no se encontraba y había que editar
> los valores por defecto del `.py`. El paso 3 lo resuelve **si abres el
> script desde disco** (Open) en lugar de pegar el texto. Si aun así falla,
> exporta la ruta antes de abrir Blender:
>
> ```bash
> export BLENDER_BRIDGE_CONFIG=/ruta/absoluta/a/blender_bridge/blender/config.env
> ```

## Solución de problemas

| Síntoma | Causa probable / arreglo |
|---|---|
| `ERROR abriendo puerto serial` | Puerto mal en `config.env`, o ocupado por otra app (cierra el Monitor Serie / `read_serial.py`). |
| `ModuleNotFoundError: serial` en Blender | `pyserial` instalado en el Python del sistema, no en el de Blender (paso 3). |
| Se movía con `_DEFAULTS`, ignoraba `config.env` | No se encontró el fichero: abre el `.py` desde disco o usa `BLENDER_BRIDGE_CONFIG` (ver arriba). |
| Muevo un eje y responde **otro** | Permutación de ejes: ajusta `AXIS_MAP`. |
| Un eje gira **al revés** | Ajusta el `SIGN_*` correspondiente (o el prefijo `-` en `AXIS_MAP`). |
| El yaw se desvía solo con el tiempo | Deriva inherente (sin magnetómetro): llama a `recenter_yaw()`. |
| `|accel|` en reposo ≠ 1 g | Clon que no respeta ±2g por defecto; el sketch fija los rangos (ver `docs/CONTEXT.md`). |
