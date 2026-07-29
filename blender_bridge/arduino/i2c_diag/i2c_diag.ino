/*
  i2c_diag.ino
  ------------
  I2C communication diagnostics for the MPU9250 + AK8963 magnetometer.
  Moves nothing and sends no CSV: it only checks that the chips respond.

  Expected output (over Serial, 115200 baud) if everything is fine:
    - The scan finds a device at 0x68 (MPU9250).
    - MPU9250 WHO_AM_I (reg 0x75) = 0x71.
    - After enabling bypass, AK8963 WHO_AM_I (reg 0x00 @ 0x0C) = 0x48.

  If the AK8963 does NOT respond (0x0C missing / WHO_AM_I != 0x48), the
  problem is in bypass mode or the I2C wiring, not in the main sketch.
*/

#include <Wire.h>

const int MPU_ADDR    = 0x68;
const int AK8963_ADDR = 0x0C;

uint8_t readReg(int addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(addr, 1, true);
  if (Wire.available()) return Wire.read();
  return 0xFF;  // did not respond
}

void runDiagnostic() {
  Serial.println();
  Serial.println(F("=== I2C diagnostics MPU9250 / AK8963 ==="));

  // ---- 1) Bus scan ----
  Serial.println(F("[1] Scanning I2C bus..."));
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    uint8_t err = Wire.endTransmission();
    if (err == 0) {
      Serial.print(F("    - Device at 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("    !! NO I2C device. Check wiring (SDA=A4, SCL=A5, VCC, GND, pull-ups)."));
    Serial.println(F("       The rest of the diagnostics will probably fail."));
  } else {
    Serial.print(F("    Total devices: "));
    Serial.println(found);
  }

  // ---- 2) MPU9250 WHO_AM_I ----
  Serial.println(F("[2] Reading MPU9250 WHO_AM_I (reg 0x75, expecting 0x71)..."));
  uint8_t whoMpu = readReg(MPU_ADDR, 0x75);
  Serial.print(F("    WHO_AM_I MPU = 0x"));
  Serial.print(whoMpu, HEX);
  if (whoMpu == 0x71)      Serial.println(F("  -> OK: MPU9250"));
  else if (whoMpu == 0x73) Serial.println(F("  -> NOTE: 0x73 = MPU9255 (compatible)"));
  else if (whoMpu == 0x70) Serial.println(F("  -> NOTE: 0x70 = MPU6500 (NO magnetometer!)"));
  else if (whoMpu == 0x68) Serial.println(F("  -> NOTE: 0x68 = MPU6050 (NO magnetometer!)"));
  else                     Serial.println(F("  -> BAD: unexpected value (no response or different chip)"));

  // ---- 3) Wake MPU + enable bypass ----
  Serial.println(F("[3] Waking the MPU and enabling bypass mode..."));
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); Wire.write(0x00);  // PWR_MGMT_1 = 0 (wake up)
  Wire.endTransmission(true);
  delay(10);
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x37); Wire.write(0x02);  // INT_PIN_CFG: BYPASS_EN = 1
  Wire.endTransmission(true);
  delay(10);

  // ---- 4) AK8963 WHO_AM_I ----
  Serial.println(F("[4] Reading AK8963 WHO_AM_I (reg 0x00 @ 0x0C, expecting 0x48)..."));
  uint8_t whoMag = readReg(AK8963_ADDR, 0x00);
  Serial.print(F("    WHO_AM_I AK8963 = 0x"));
  Serial.print(whoMag, HEX);
  if (whoMag == 0x48) Serial.println(F("  -> OK: magnetometer responds after bypass"));
  else                Serial.println(F("  -> BAD: no response. Bypass or AK8963 wiring problem."));

  Serial.println(F("=== End of diagnostics ==="));
}

void setup() {
  Wire.begin();
  Serial.begin(115200);
  delay(200);
}

void loop() {
  runDiagnostic();  // Repeats so it can be captured by opening the monitor at any time.
  delay(3000);
}
