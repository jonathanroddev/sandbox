/*
  i2c_diag.ino
  ------------
  Diagnóstico de comunicación I2C para el MPU9250 + magnetómetro AK8963.
  NO mueve nada ni envía CSV: solo comprueba que los chips responden.

  Salida esperada (por Serial, 115200 baudios) si todo está bien:
    - El escaneo encuentra un dispositivo en 0x68 (MPU9250).
    - WHO_AM_I del MPU9250 (reg 0x75) = 0x71.
    - Tras activar bypass, WHO_AM_I del AK8963 (reg 0x00 @ 0x0C) = 0x48.

  Si el AK8963 NO responde (0x0C ausente / WHO_AM_I != 0x48), el problema
  está en el modo bypass o en el cableado I2C, no en el sketch principal.
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
  return 0xFF;  // no respondió
}

void runDiagnostic() {
  Serial.println();
  Serial.println(F("=== Diagnostico I2C MPU9250 / AK8963 ==="));

  // ---- 1) Escaneo del bus ----
  Serial.println(F("[1] Escaneando bus I2C..."));
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    uint8_t err = Wire.endTransmission();
    if (err == 0) {
      Serial.print(F("    - Dispositivo en 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("    !! NINGUN dispositivo I2C. Revisa cableado (SDA=A4, SCL=A5, VCC, GND, pull-ups)."));
    Serial.println(F("       El resto del diagnostico probablemente fallara."));
  } else {
    Serial.print(F("    Total dispositivos: "));
    Serial.println(found);
  }

  // ---- 2) WHO_AM_I del MPU9250 ----
  Serial.println(F("[2] Leyendo WHO_AM_I del MPU9250 (reg 0x75, se espera 0x71)..."));
  uint8_t whoMpu = readReg(MPU_ADDR, 0x75);
  Serial.print(F("    WHO_AM_I MPU = 0x"));
  Serial.print(whoMpu, HEX);
  if (whoMpu == 0x71)      Serial.println(F("  -> OK: MPU9250"));
  else if (whoMpu == 0x73) Serial.println(F("  -> OJO: 0x73 = MPU9255 (compatible)"));
  else if (whoMpu == 0x70) Serial.println(F("  -> OJO: 0x70 = MPU6500 (SIN magnetometro!)"));
  else if (whoMpu == 0x68) Serial.println(F("  -> OJO: 0x68 = MPU6050 (SIN magnetometro!)"));
  else                     Serial.println(F("  -> MAL: valor inesperado (no responde o chip distinto)"));

  // ---- 3) Despertar MPU + activar bypass ----
  Serial.println(F("[3] Despertando MPU y activando modo bypass..."));
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); Wire.write(0x00);  // PWR_MGMT_1 = 0 (despierta)
  Wire.endTransmission(true);
  delay(10);
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x37); Wire.write(0x02);  // INT_PIN_CFG: BYPASS_EN = 1
  Wire.endTransmission(true);
  delay(10);

  // ---- 4) WHO_AM_I del AK8963 ----
  Serial.println(F("[4] Leyendo WHO_AM_I del AK8963 (reg 0x00 @ 0x0C, se espera 0x48)..."));
  uint8_t whoMag = readReg(AK8963_ADDR, 0x00);
  Serial.print(F("    WHO_AM_I AK8963 = 0x"));
  Serial.print(whoMag, HEX);
  if (whoMag == 0x48) Serial.println(F("  -> OK: magnetometro responde tras bypass"));
  else                Serial.println(F("  -> MAL: no responde. Problema de bypass o cableado del AK8963."));

  Serial.println(F("=== Fin del diagnostico ==="));
}

void setup() {
  Wire.begin();
  Serial.begin(115200);
  delay(200);
}

void loop() {
  runDiagnostic();  // Se repite para poder capturarlo abriendo el monitor en cualquier momento.
  delay(3000);
}
