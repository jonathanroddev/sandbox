# Contexto: Puente Arduino (MPU-6050) → Blender

## Objetivo
Capturar orientación (roll/pitch/yaw) de un sensor de movimiento Arduino
y aplicarla en tiempo real a un objeto en Blender, vía serial USB.

## Hardware real (VALIDADO por diagnóstico, 2026-07-13)
- **Placa: Arduino Uno**, detectada en `/dev/cu.usbmodem11201`,
  FQBN `arduino:avr:uno`.
- **Sensor: MPU-6050** (6 ejes: accel + gyro). Confirmado por WHO_AM_I
  = `0x68` (el `0x71` sería un MPU9250). **NO tiene magnetómetro.**
  > Nota: el planteamiento inicial asumía un MPU9250 con magnetómetro
  > AK8963. El diagnóstico I2C demostró que el chip real es un MPU-6050
  > (muy común: módulos "MPU9250" baratos que son 6050 reetiquetados).
- **Quirk del clon**: el acelerómetro NO arrancaba en el rango ±2g por
  defecto (magnitud en reposo ~0.27g en vez de ~1g). Se corrige
  escribiendo `ACCEL_CONFIG` (0x1C) y `GYRO_CONFIG` (0x1B)
  explícitamente en el sketch. Tras el fix, |accel| ≈ 1.0g.
- Conexión: cable USB, serial a 115200 baudios, CSV ~50 Hz.

## Alcance
- **Roll y pitch**: absolutos y estables (referencia de gravedad vía
  acelerómetro + giroscopio, filtro complementario). Funcionan bien.
- **Yaw**: SOLO giroscopio integrado → **deriva** con el tiempo (no hay
  magnetómetro que lo corrija). Mitigado con calibración del bias del
  giroscopio al arrancar + función `recenter_yaw()` para poner a cero.
- **Posición**: fuera de alcance (requeriría doble integración de la
  aceleración, con drift inasumible sin referencia externa).

## Archivos
- `arduino/mpu_serial_bridge/mpu_serial_bridge.ino` — Sketch principal.
  Lee accel+gyro del MPU-6050 por I2C y los envía por Serial como CSV:
  `ax,ay,az,gx,gy,gz` (accel en g, gyro en °/s). Fija los rangos
  explícitamente (±2g / ±250°/s).
- `arduino/i2c_diag/i2c_diag.ino` — Sketch de diagnóstico (no mueve
  nada). Escanea el bus I2C y lee los WHO_AM_I. Útil para revalidar el
  hardware si algo deja de funcionar. Se repite en loop() cada 3s.
- `blender/blender_serial_bridge.py` — Script para ejecutar dentro de
  Blender. Lee el CSV de 6 valores, fusiona accel+gyro para roll/pitch
  e integra el giroscopio para yaw, y actualiza la rotación del objeto.
- `blender/config.env` — **Único fichero a tocar al cambiar de PC/escena.**
  Formato `CLAVE=valor` (estilo .env) leído sin dependencias externas
  (el Python de Blender no trae python-dotenv). Contiene `SERIAL_PORT`,
  `OBJECT_NAME`, `ALPHA_ROLL_PITCH`, signos de eje, etc. El script lo
  busca por la env var `BLENDER_BRIDGE_CONFIG`, luego junto al script,
  luego en el cwd; si no lo encuentra usa valores por defecto internos.
- `tools/read_serial.py` — Lector serial de diagnóstico (Python del
  sistema, con pyserial). Resetea la placa por DTR y vuelca N segundos
  de líneas. Para validar datos crudos sin depender de Blender.
- `backups/` — Respaldo de la flash y EEPROM originales del Uno
  (`flash_backup_*.hex`, `eeprom_backup_*.hex`), por si hay que
  restaurar el programa que traía la placa antes de este proyecto.

## Decisiones de arquitectura tomadas
1. **Fusión de sensores en Python (Blender), no en Arduino.** Se puede
   iterar el algoritmo sin reflashear; Arduino solo lee y envía crudo.
2. **Filtro complementario** (no Madgwick/Mahony) para roll/pitch en
   esta primera versión: más simple de entender/depurar. Sustituible
   luego por Madgwick 6-ejes (librería `ahrs`) si se necesita.
3. **Yaw por giroscopio, aceptando la deriva** (elección explícita del
   usuario). Alternativas descartadas por ahora: solo roll/pitch, o
   yaw con auto-recentrado (high-pass). Sin magnetómetro no hay heading
   absoluto posible con este hardware.
4. **Rangos del sensor fijados explícitamente** en el sketch, tras
   descubrir que el clon no respetaba el default de ±2g.
5. **CSV plano por serial**, una línea por lectura, ~50 Hz.

## Cómo probar (validado hasta el paso 2)
Toolchain: `arduino-cli` (sin IDE), core `arduino:avr` instalado.

1. Compilar/flashear el sketch:
   ```
   arduino-cli compile --fqbn arduino:avr:uno arduino/mpu_serial_bridge
   arduino-cli upload -p /dev/cu.usbmodem11201 --fqbn arduino:avr:uno arduino/mpu_serial_bridge
   ```
2. Verificar el CSV crudo (6 valores, |accel|≈1g en reposo):
   ```
   /usr/bin/python3 tools/read_serial.py /dev/cu.usbmodem11201 6 115200
   ```
3. Instalar `pyserial` en el Python **de Blender**:
   ```
   /Applications/Blender.app/Contents/Resources/<version>/python/bin/python3.x -m pip install pyserial
   ```
4. Ajustar en `blender/config.env` (NO hace falta tocar el .py):
   - `SERIAL_PORT` (en Linux/Windows será distinto: `/dev/ttyACM0`, `COM3`...).
   - `OBJECT_NAME` (objeto de la escena a mover).
5. Abrir el script en la pestaña Scripting de Blender y Run Script.
   Mantener el sensor quieto ~1s al arrancar (calibración del bias).

## Estado / próximos pasos
- [x] Toolchain arduino-cli + core AVR instalados.
- [x] Hardware identificado (MPU-6050) y comunicación I2C validada.
- [x] CSV de 6 valores en streaming, acelerómetro escalado correcto.
- [x] Sketch y bridge de Blender adaptados a 6 ejes.
- [ ] Probar el bridge end-to-end dentro de Blender (mover objeto).
- [ ] Calibración de ejes: mapear ejes del sensor a los de Blender
      según el montaje físico (ajustar `SIGN_ROLL/PITCH/YAW` o el
      orden de ejes en `rotation_euler`).
- [ ] Ajustar `ALPHA_ROLL_PITCH` si se ve nervioso (bajar) o lento (subir).
- [ ] (Opcional) Evaluar Madgwick 6-ejes (librería `ahrs`) si el
      movimiento se ve inestable con giros rápidos.
- [ ] (Opcional) Mapear una tecla en Blender a `recenter_yaw()`.
- [ ] (Opcional, hardware) Si el heading absoluto llega a importar,
      haría falta un magnetómetro externo (p.ej. HMC5883L/QMC5883L por
      I2C) — no lo tiene el MPU-6050.

## Notas para Claude Code
El pipeline hardware está validado end-to-end hasta el CSV crudo. Lo
que falta es probarlo dentro de Blender y calibrar el mapeo de ejes,
que depende de cómo se monte físicamente el sensor.
