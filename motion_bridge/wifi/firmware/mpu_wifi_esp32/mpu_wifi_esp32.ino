/*
  mpu_wifi_esp32.ino
  -------------------
  Reads accelerometer + gyroscope from an MPU-6050 over I2C and sends them
  over WiFi as UDP datagrams, in the `raw6` profile of the shared frame
  protocol (see ../../../docs/PROTOCOL.md):

      deviceId,ax,ay,az,gx,gy,gz\r\n

  - ax,ay,az in "g"            (±2g range, set explicitly)
  - gx,gy,gz in degrees/second (±250°/s range, set explicitly)

  The sensor fusion is NOT done here: it is done in Blender, exactly like
  the wired bridge does. The board only reads and sends, so the filter can
  be iterated without reflashing.

  WHY AN ESP32 AND NOT THE UNO + ESP-01:
    Native WiFi, 3.3V logic (the MPU-6050 is a 3.3V part — no level
    shifting), and no AT-command bottleneck. 100 Hz is comfortable here
    while the UNO + ESP-01 tops out around 20 Hz. If you are buying
    hardware for the multi-sensor suit, buy these.

  I2C WIRING (ESP32 dev board <-> GY-521 / MPU-6050):
    VCC -> 3V3        (NOT 5V: the ESP32 has no 5V-tolerant pins)
    GND -> GND
    SDA -> GPIO21
    SCL -> GPIO22
    AD0 -> GND        (I2C address 0x68; to 3V3 it becomes 0x69)

  BUILD (arduino-cli, esp32 core installed):
    cp secrets.example.h secrets.h        # then edit secrets.h
    arduino-cli compile --fqbn esp32:esp32:esp32 .
    arduino-cli upload -p /dev/cu.usbserial-XXXX --fqbn esp32:esp32:esp32 .

  Board core, if you don't have it yet:
    arduino-cli config add board_manager.additional_urls \
      https://espressif.github.io/arduino-esp32/package_esp32_index.json
    arduino-cli core update-index && arduino-cli core install esp32:esp32
*/

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASS, DEST_IP, DEST_PORT, DEVICE_ID

// ---- Sensor / rate ----
const int MPU_ADDR = 0x68;        // AD0 to GND
const float ACCEL_SENS = 16384.0; // LSB/g for ±2g
const float GYRO_SENS  = 131.0;   // LSB/(°/s) for ±250°/s
const unsigned long SEND_PERIOD_MS = 10;  // 10 ms -> 100 Hz

// ---- Diagnostics over USB serial (does not affect the UDP stream) ----
const long DEBUG_BAUD = 115200;
const unsigned long STATUS_PERIOD_MS = 5000;

WiFiUDP udp;
unsigned long lastSend = 0;
unsigned long lastStatus = 0;
unsigned long framesSent = 0;

void mpuWriteReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission(true);
}

void setupMpu() {
  Wire.begin();          // ESP32 defaults: SDA=21, SCL=22
  Wire.setClock(400000); // fast mode; the MPU-6050 handles it fine
  mpuWriteReg(0x6B, 0x00);  // PWR_MGMT_1 = 0 -> wake up (it boots asleep)
  mpuWriteReg(0x1B, 0x00);  // GYRO_CONFIG  FS_SEL=0  -> ±250°/s
  mpuWriteReg(0x1C, 0x00);  // ACCEL_CONFIG AFS_SEL=0 -> ±2g
  // The ranges are written EXPLICITLY on purpose: some MPU-6050 clones do
  // not honour the ±2g default and report ~0.27g at rest instead of ~1g.
  delay(100);

  // Confirm the chip answers (WHO_AM_I should read 0x68).
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x75);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 1, true);
  uint8_t who = Wire.available() ? Wire.read() : 0xFF;
  Serial.printf("[mpu] WHO_AM_I = 0x%02X %s\n", who,
                who == 0x68 ? "(MPU-6050 OK)" : "(UNEXPECTED - check wiring)");
}

void connectWifi() {
  Serial.printf("[wifi] Connecting to '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("[wifi] Connected. Local IP: ");
  Serial.println(WiFi.localIP());
  Serial.printf("[udp] Streaming '%s' to %s:%d\n", DEVICE_ID, DEST_IP, DEST_PORT);
  udp.begin(WiFi.localIP(), 0);  // any local port; we only send
}

void setup() {
  Serial.begin(DEBUG_BAUD);
  delay(200);
  setupMpu();
  connectWifi();
}

void loop() {
  // WiFi can drop; reconnect instead of silently going quiet.
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] Connection lost, reconnecting...");
    connectWifi();
  }

  unsigned long now = millis();
  if (now - lastSend < SEND_PERIOD_MS) {
    delay(1);   // yield: a tight spin here starves the WiFi task and trips
    return;     // the task watchdog. 1 ms is well under SEND_PERIOD_MS.
  }
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
  char frame[128];
  snprintf(frame, sizeof(frame),
           "%s,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\r\n",
           DEVICE_ID,
           ax_raw / ACCEL_SENS, ay_raw / ACCEL_SENS, az_raw / ACCEL_SENS,
           gx_raw / GYRO_SENS,  gy_raw / GYRO_SENS,  gz_raw / GYRO_SENS);

  udp.beginPacket(DEST_IP, DEST_PORT);
  udp.print(frame);
  udp.endPacket();
  framesSent++;

  if (now - lastStatus >= STATUS_PERIOD_MS) {
    lastStatus = now;
    Serial.printf("[udp] %lu frames sent | RSSI %d dBm | last: %s",
                  framesSent, WiFi.RSSI(), frame);
  }
}
