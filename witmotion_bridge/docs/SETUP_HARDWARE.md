# Setup del hardware — conectar el WT901WIFI y validar la recepción

Guía para retomar el trabajo **con el sensor delante**, pensada para
continuar desde el PC de trabajo (Fedora + VM de Windows para la tool
oficial de WitMotion). Complementa `CONTEXT.md` (decisiones y protocolo) y
`../CLAUDE.md` (orden de tareas).

> **Estado al escribir esto (2026-07-20):** la tubería de software está
> **validada de punta a punta** en la Mac de desarrollo con `fake_sensor.py`
> → `read_udp.py` (13 campos, DeviceID en índice 0, ángulos en 7/8/9,
> coherente con `config.env`). Lo único **pendiente con hardware real** es:
> confirmar el formato real del CSV del sensor y afinar el mapeo de ejes en
> Blender. Si al conectar el sensor real no llegan tramas, el problema es de
> **red o de configuración del sensor**, no del código.

---

## 0. Antes de nada: la IP es específica de cada equipo/red

Toda la config apunta el sensor a `IP_DEL_PC:PUERTO`. **La IP NO se
hardcodea** en el repo: depende del PC y de la red. En la Mac de desarrollo
era `192.168.1.22`, pero en el PC de Fedora será otra. Averíguala así:

```bash
# Fedora / Linux — IP en la LAN (la de la interfaz WiFi, típicamente wlan0/wlp*)
ip -4 addr show | grep -w inet          # lista todas; coge la de tu WiFi
# atajo:
hostname -I | awk '{print $1}'
# o, más explícito, con NetworkManager:
nmcli -t -f IP4.ADDRESS device show | head
```

El **puerto** sí está fijado en el repo: `LISTEN_PORT=1399` en
`blender/config.env`. Si lo cambias, cámbialo ahí (no en el código) y usa el
mismo valor en el sensor.

Comprueba que el puerto UDP está libre antes de escuchar:

```bash
# Fedora / Linux
ss -lunp | grep 1399 || echo "libre"
```

---

## 1. Validar la tubería de software (sin sensor)

Hazlo **primero** en el PC nuevo: confirma que Python + sockets + parseo
funcionan ahí, para aislar cualquier fallo posterior como "red/sensor".

```bash
cd witmotion_bridge
# Terminal 1 — escucha 4 s
python3 tools/read_udp.py 1399 4
# Terminal 2 — emite tramas falsas 3 s a localhost
python3 tools/fake_sensor.py 1399 3 50 127.0.0.1 WT9AXTEST
```

Esperado: líneas `campos=13 | WT9AXTEST,...` y al final
`N líneas recibidas`. Si esto funciona, el software está OK.

---

## 2. Preparar la VM de Windows (para la tool oficial)

La tool de configuración oficial de WitMotion es de **Windows**. En Fedora,
córrela en una VM (VirtualBox / GNOME Boxes / virt-manager).

**Clave — red de la VM:** la VM tiene que poder **ver el sensor por WiFi**,
así que necesita estar en la misma red que él. Durante la configuración el
sensor está en **AP mode** (crea su propia WiFi):

1. Conecta el **host Fedora** a la WiFi del sensor (`WT901WIFI_xxxx` / `HC-xx`).
2. Pon la red de la VM en **modo puente (bridged)** sobre la interfaz WiFi
   del host (no NAT), para que la VM obtenga IP en la red del sensor y pueda
   hablar con él. (Con NAT normalmente **no** llegarás al sensor.)
3. Alternativa si el bridge sobre WiFi da problemas (algunos drivers WiFi no
   dejan bridgear): usa la **app móvil de WitMotion** para toda la
   configuración y olvídate de la VM para esta parte.

---

## 3. Configurar el sensor: AP mode → Station mode

El sensor sale en **AP mode** (crea su red). Lo queremos en **Station mode**
(unido a tu router, junto al PC). Pasos:

1. **Enciende** el sensor (botón ~2 s; carga por USB si el LED no enciende).
2. Conéctate a su red WiFi `WT901WIFI_xxxx` (contraseña del manual si pide;
   suele ser `1234567890` / `12345678` o ninguna).
3. Abre la tool oficial (en la VM) o la app móvil y entra en los ajustes de
   red del sensor. Configura:

   | Campo | Valor |
   |---|---|
   | Modo | **Station (STA)** |
   | SSID del router | tu WiFi (**2.4 GHz**, el sensor no ve 5 GHz) |
   | Password | la de tu WiFi |
   | Protocolo | **UDP** |
   | Target / Server IP | **la IP del PC** (la del paso 0) |
   | Target / Server Port | **1399** (o el `LISTEN_PORT` de `config.env`) |

   > ⚠️ **El orden importa (manual):** al migrar AP → Station deja el
   > protocolo en **UDP primero**, nunca TCP directo, o puedes perder la
   > conexión y tocará reset. Nosotros usamos UDP de todas formas (menor
   > latencia; decisión en `CONTEXT.md`).

4. **Aplica/guarda.** El sensor se reinicia e intenta unirse a tu router.
5. Vuelve a conectar el **PC a tu WiFi de casa** (habrás perdido la red al
   estar en la del sensor).

---

## 4. Capturar la trama REAL y cerrar el formato del CSV

Con el sensor en tu red y transmitiendo:

```bash
cd witmotion_bridge
python3 tools/read_udp.py 1399 10
```

Qué mirar en la salida (esto es el punto pendiente #1 de `CLAUDE.md`):

- ¿Llegan líneas y empiezan por el **DeviceID** real (algo tipo `WT53...`)?
  Apunta el DeviceID: lo necesitarás para `DEVICE_MAP` en `config.env`.
- **¿Cuántos campos?** Asumimos 13.
- **¿En qué índices están los ángulos X/Y/Z?** Asumimos 7, 8, 9.

Si el orden/número **no** coincide con lo asumido, ajusta en
`blender/config.env` (**no** en el código):
`IDX_DEVICE`, `IDX_ANGLE_X/Y/Z`, `MIN_FIELDS`.

---

## 5. Un sensor en Blender

1. En `blender/config.env`: pon `DEFAULT_OBJECT` (y `DEVICE_MAP=*:<Objeto>`)
   al nombre del objeto de tu escena.
2. Blender → pestaña **Scripting** → abre `blender/blender_udp_bridge.py` →
   **Run Script**.
3. Con `AUTO_CALIBRATE=1`, coloca el sensor en la **pose de referencia**
   durante el countdown inicial (`CALIB_COUNTDOWN` s).
4. Mueve el sensor **un eje cada vez** y verifica que el objeto gira en el
   eje y sentido correctos. Si algún eje va invertido/cruzado, ajusta
   `SIGN_ROLL/PITCH/YAW` (o el orden de Euler en `_angles_to_quat()`).

Utilidades en la consola Python de Blender: `start_bridge()`, `calibrate()`,
`recenter(device_id)`, `list_devices()`, `stop_bridge()`.

---

## Si hay silencio (checklist de diagnóstico)

1. ¿PC y sensor en la **misma** red y en **2.4 GHz**? (el sensor no ve 5 GHz).
2. ¿La **IP** configurada en el sensor es la actual del PC? (re-mira el paso 0;
   si el router da IP por DHCP, puede haber cambiado — considera fijarla).
3. **Firewall de Fedora** (firewalld): permite el puerto UDP para la prueba.
   ```bash
   sudo firewall-cmd --add-port=1399/udp            # temporal (hasta reboot)
   # permanente:  sudo firewall-cmd --permanent --add-port=1399/udp && sudo firewall-cmd --reload
   ```
4. ¿El sensor se quedó en **AP mode**? (si sigue emitiendo su propia red, no
   entró en Station: repite el paso 3).
5. Confirma que algo llega a nivel de red aunque el parseo falle:
   ```bash
   sudo tcpdump -n -i any udp port 1399
   ```
6. Último recurso: **reset** del sensor (botón según manual) y repetir desde
   el paso 3.

---

## Resumen de lo que queda por hacer con el hardware

- [ ] Ejecutar el paso 1 (tubería) en el PC de Fedora.
- [ ] Montar VM de Windows + tool oficial (o usar app móvil) — paso 2.
- [ ] Configurar el sensor a Station/UDP/`IP_DEL_PC`:1399 — paso 3.
- [ ] Capturar trama real y **confirmar/ajustar los `IDX_*`** — paso 4.
- [ ] Un sensor en Blender y **afinar el mapeo de ejes** — paso 5.
- [ ] Luego: multi-sensor (`list_devices()` → `DEVICE_MAP`) y armature
      (ver `CONTEXT.md` → "Pendiente / próximos pasos").
</content>
</invoke>
