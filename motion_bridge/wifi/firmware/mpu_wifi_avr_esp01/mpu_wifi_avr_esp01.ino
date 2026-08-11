/*
  mpu_wifi_avr_esp01.ino
  ------------------------
  A 5V ATmega328P Arduino + MPU-6050 (I2C) + ESP-01/ESP-01S (ESP8266)
  driven by AT commands over SoftwareSerial. Sends the `raw6` profile of the
  shared frame protocol (see ../../../docs/PROTOCOL.md) as UDP datagrams:

      deviceId,ax,ay,az,gx,gy,gz\r\n

  BOARD-AGNOSTIC ON PURPOSE. Nothing below depends on which 328P board this
  is: D2/D3, A4/A5 and Serial are the same on a Nano and on an Uno, and the
  board is chosen by the FQBN at build time, not by the code. The project's
  board is a **Nano**; an Uno works with `arduino:avr:uno` and no edits. The
  one place they really differ is POWER, flagged below.

  This is the "keep the 328P board we already have" path. It works, but read
  the limits before wiring anything:

    * RATE ~20 Hz. Every frame costs an `AT+CIPSEND=<n>` round trip at 9600
      baud over SoftwareSerial. The ESP32 sketch next door does 100 Hz.
    * LOGIC LEVELS. The ESP-01 is 3.3V and is NOT 5V tolerant. The board's
      TX (pin 3 here) MUST go through a level shifter or a divider before
      reaching the ESP-01 RX. Wiring it directly will damage the module.
    * POWER — the one real Nano/Uno difference. The ESP-01 draws ~300 mA
      peaks on transmit, and neither board's 3.3V rail can feed it:
        - Uno: a real 3.3V regulator, but rated ~50 mA.
        - Nano: NO regulator at all. Its 3V3 pin hangs off the USB-serial
          chip (~50 mA on an FT232RL; many CH340 clones barely drive it).
      Either way the module browns out (random resets, "no AT response"),
      but on the Nano there is nothing to brown out in the first place. A
      separate 3.3V supply is mandatory, not a precaution: an AMS1117 module
      off the board's 5V with a 100 uF cap near the ESP-01, GND common.
    * SoftwareSerial cannot keep up with the ESP-01's factory 115200 baud.
      You MUST drop the module to 9600 first — see PREPARATION below.

  WIRING
    MPU-6050 (GY-521)        ESP-01S
      VCC -> 5V                VCC   -> 3.3V (separate supply, see above)
      GND -> GND               GND   -> GND (common with the board)
      SCL -> A5                CH_PD -> 3.3V (enable; without it, nothing works)
      SDA -> A4                RST   -> not connected
                               TX    -> board pin 2  (3.3V out, safe for a 5V in)
                               RX    <- board pin 3 THROUGH a level shifter
                                        (or divider: 1k in series + 2k to GND)

  PREPARATION (once per module, before using this sketch)
    Talk to the ESP-01 at its factory baud with a USB-TTL adapter (or the
    board running a passthrough sketch) and set it to 9600 permanently:
        AT                      -> OK          (module alive)
        AT+GMR                  -> firmware version
        AT+UART_DEF=9600,8,1,0,0  -> OK        (persists across reboots)
    From then on it answers at 9600 and this sketch can drive it.

  BUILD  (pick the FQBN for the board you actually have)
    cp secrets.example.h secrets.h        # then edit secrets.h
    arduino-cli compile --fqbn arduino:avr:nano .     # or arduino:avr:uno
    arduino-cli upload -p $PORT --fqbn arduino:avr:nano .
    # Nano: $PORT is /dev/cu.wchusbserial* or /dev/cu.usbserial-*
    #       (ls /dev/cu.*), NOT a usbmodem name. If the upload fails with
    #       "not in sync", the clone has the old bootloader: use
    #       arduino:avr:nano:cpu=atmega328old.
    # Uno:  $PORT is /dev/cu.usbmodem* (native USB).

  DEBUG
    Open the USB serial monitor at 115200: the sketch prints every AT
    exchange, so a failure tells you which step broke (join, UDP start, or
    send).
*/

#include <Wire.h>
#include <SoftwareSerial.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASS, DEST_IP, DEST_PORT, DEVICE_ID

// ---- ESP-01 link ----
const uint8_t ESP_RX_PIN = 2;   // Nano pin 2  <- ESP-01 TX
const uint8_t ESP_TX_PIN = 3;   // Nano pin 3  -> ESP-01 RX (VIA LEVEL SHIFTER)
const long ESP_BAUD = 9600;     // set with AT+UART_DEF, see PREPARATION
SoftwareSerial esp(ESP_RX_PIN, ESP_TX_PIN);

// ---- Sensor / rate ----
const int MPU_ADDR = 0x68;        // AD0 to GND
const float ACCEL_SENS = 16384.0; // LSB/g for ±2g
const float GYRO_SENS  = 131.0;   // LSB/(°/s) for ±250°/s
const unsigned long SEND_PERIOD_MS = 50;  // 50 ms -> ~20 Hz (the AT ceiling)

const long DEBUG_BAUD = 115200;

unsigned long lastSend = 0;
unsigned int consecutiveFailures = 0;

// ---------------- ESP-01 AT helpers ----------------

/* Read from the ESP-01 until `expect` is seen or `timeoutMs` elapses.
   Echoes everything to the USB monitor so a failure is diagnosable. */
bool waitFor(const char *expect, unsigned long timeoutMs) {
  unsigned long deadline = millis() + timeoutMs;
  size_t matched = 0;
  size_t len = strlen(expect);
  while (millis() < deadline) {
    while (esp.available()) {
      char c = esp.read();
      Serial.write(c);
      matched = (c == expect[matched]) ? matched + 1 : (c == expect[0] ? 1 : 0);
      if (matched == len) return true;
    }
  }
  return false;
}

bool atCommand(const char *cmd, const char *expect, unsigned long timeoutMs) {
  Serial.print(F("\n[at] > "));
  Serial.println(cmd);
  esp.println(cmd);
  bool ok = waitFor(expect, timeoutMs);
  Serial.println(ok ? F("\n[at] OK") : F("\n[at] TIMEOUT"));
  return ok;
}

/* Join the WiFi network and open the UDP "connection".
   UDP has no real connection: AT+CIPSTART just fixes the destination so
   later sends are a single AT+CIPSEND. Returns false if any step fails. */
bool espConnect() {
  char cmd[128];

  if (!atCommand("AT", "OK", 2000)) {
    Serial.println(F("[esp] No response. Check baud (9600), CH_PD to 3.3V, and power."));
    return false;
  }
  atCommand("AT+RST", "ready", 8000);   // may answer garbage; not fatal
  delay(500);
  if (!atCommand("AT+CWMODE=1", "OK", 3000)) return false;   // station mode

  snprintf(cmd, sizeof(cmd), "AT+CWJAP=\"%s\",\"%s\"", WIFI_SSID, WIFI_PASS);
  if (!atCommand(cmd, "OK", 20000)) {                        // joining is slow
    Serial.println(F("[esp] Could not join. Check SSID/password and that it is 2.4 GHz."));
    return false;
  }
  if (!atCommand("AT+CIPMUX=0", "OK", 3000)) return false;    // single connection

  snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"UDP\",\"%s\",%d", DEST_IP, DEST_PORT);
  if (!atCommand(cmd, "OK", 8000)) return false;

  atCommand("AT+CIFSR", "OK", 3000);    // print the IP the router gave us
  Serial.println(F("[esp] UDP ready."));
  return true;
}

/* Send one frame: AT+CIPSEND=<len>, wait for the '>' prompt, write payload. */
bool espSend(const char *payload) {
  char cmd[24];
  snprintf(cmd, sizeof(cmd), "AT+CIPSEND=%u", (unsigned)strlen(payload));
  esp.println(cmd);
  if (!waitFor(">", 1000)) return false;
  esp.print(payload);
  return waitFor("SEND OK", 2000);
}

// ---------------- MPU-6050 ----------------

void mpuWriteReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission(true);
}

void setupMpu() {
  Wire.begin();
  mpuWriteReg(0x6B, 0x00);  // PWR_MGMT_1 = 0 -> wake up (it boots asleep)
  mpuWriteReg(0x1B, 0x00);  // GYRO_CONFIG  FS_SEL=0  -> ±250°/s
  mpuWriteReg(0x1C, 0x00);  // ACCEL_CONFIG AFS_SEL=0 -> ±2g
  // Ranges written EXPLICITLY: some clones ignore the ±2g default and read
  // ~0.27g at rest instead of ~1g (this exact board did — see wired/docs/CONTEXT.md).
  delay(100);
}

// ---------------- Sketch ----------------

void setup() {
  Serial.begin(DEBUG_BAUD);
  esp.begin(ESP_BAUD);
  delay(300);
  Serial.println(F("\n[bridge] MPU-6050 -> ESP-01 -> UDP"));
  setupMpu();
  while (!espConnect()) {
    Serial.println(F("[esp] Retrying in 5 s..."));
    delay(5000);
  }
  Serial.print(F("[udp] Streaming '"));
  Serial.print(DEVICE_ID);
  Serial.print(F("' to "));
  Serial.print(DEST_IP);
  Serial.print(':');
  Serial.println(DEST_PORT);
}

void loop() {
  unsigned long now = millis();
  if (now - lastSend < SEND_PERIOD_MS) return;
  lastSend = now;

  // ---- Read accel + gyro (14 bytes starting at 0x3B) ----
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 14, true);
  if (Wire.available() < 14) return;  // bad read, skip this frame

  int16_t ax_raw = (Wire.read() << 8) | Wire.read();
  int16_t ay_raw = (Wire.read() << 8) | Wire.read();
  int16_t az_raw = (Wire.read() << 8) | Wire.read();
  Wire.read(); Wire.read();           // discard temperature
  int16_t gx_raw = (Wire.read() << 8) | Wire.read();
  int16_t gy_raw = (Wire.read() << 8) | Wire.read();
  int16_t gz_raw = (Wire.read() << 8) | Wire.read();

  // ---- Build the CSV frame (raw6 profile) ----
  // AVR's snprintf has no %f, so each float is formatted with dtostrf.
  char ax[10], ay[10], az[10], gx[10], gy[10], gz[10];
  dtostrf(ax_raw / ACCEL_SENS, 0, 4, ax);
  dtostrf(ay_raw / ACCEL_SENS, 0, 4, ay);
  dtostrf(az_raw / ACCEL_SENS, 0, 4, az);
  dtostrf(gx_raw / GYRO_SENS,  0, 4, gx);
  dtostrf(gy_raw / GYRO_SENS,  0, 4, gy);
  dtostrf(gz_raw / GYRO_SENS,  0, 4, gz);

  char frame[96];
  snprintf(frame, sizeof(frame), "%s,%s,%s,%s,%s,%s,%s\r\n",
           DEVICE_ID, ax, ay, az, gx, gy, gz);

  if (espSend(frame)) {
    consecutiveFailures = 0;
  } else if (++consecutiveFailures >= 10) {
    // The link is gone (module reset, AP dropped). Rebuild it rather than
    // streaming into the void.
    Serial.println(F("\n[esp] 10 failed sends: reconnecting..."));
    consecutiveFailures = 0;
    while (!espConnect()) {
      Serial.println(F("[esp] Retrying in 5 s..."));
      delay(5000);
    }
  }
}
