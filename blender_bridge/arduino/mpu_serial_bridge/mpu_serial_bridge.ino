/*
  mpu_serial_bridge.ino
  ----------------------
  Lee acelerómetro + giroscopio de un MPU-6050 vía I2C y envía los
  valores por Serial en formato CSV, una línea por lectura:

      ax,ay,az,gx,gy,gz

  - ax,ay,az en "g" (aceleración, ±2g por defecto)
  - gx,gy,gz en grados/segundo (velocidad angular, ±250°/s por defecto)

  HARDWARE (confirmado por diagnóstico WHO_AM_I=0x68):
    El sensor es un MPU-6050 (6 ejes, accel + gyro). NO tiene
    magnetómetro, así que no hay heading absoluto: el yaw solo se puede
    integrar del giroscopio y por tanto derivará con el tiempo. El
    roll y el pitch sí son absolutos (referencia de gravedad) y estables.

  Conexión I2C (Arduino Uno, módulo GY-521 / MPU-6050):
    VCC -> 5V (el GY-521 lleva regulador a 3.3V a bordo)
    GND -> GND
    SCL -> A5
    SDA -> A4
*/

#include <Wire.h>

const int MPU_ADDR = 0x68;   // Dirección I2C del MPU-6050 (AD0 a GND)
const long BAUD_RATE = 115200;

// Sensibilidades por defecto
const float ACCEL_SENS = 16384.0;  // LSB/g para rango ±2g
const float GYRO_SENS  = 131.0;    // LSB/(°/s) para rango ±250°/s

void setup() {
  Wire.begin();
  Serial.begin(BAUD_RATE);

  // Despertar el MPU-6050 (por defecto arranca en modo "sleep")
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);  // Registro PWR_MGMT_1
  Wire.write(0x00);  // Poner a 0 => despierta el sensor
  Wire.endTransmission(true);

  // Fijar EXPLÍCITAMENTE el rango del giroscopio a ±250°/s (FS_SEL=0)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);  // GYRO_CONFIG
  Wire.write(0x00);  // FS_SEL=0 => ±250°/s => 131 LSB/(°/s)
  Wire.endTransmission(true);

  // Fijar EXPLÍCITAMENTE el rango del acelerómetro a ±2g (AFS_SEL=0)
  // (no confiar en el default: algunos clones no arrancan en ±2g)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);  // ACCEL_CONFIG
  Wire.write(0x00);  // AFS_SEL=0 => ±2g => 16384 LSB/g
  Wire.endTransmission(true);

  delay(100);
}

void loop() {
  int16_t ax_raw, ay_raw, az_raw;
  int16_t gx_raw, gy_raw, gz_raw;

  // ---- Leer accel + gyro (14 bytes desde 0x3B) ----
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 14, true);

  ax_raw = (Wire.read() << 8) | Wire.read();
  ay_raw = (Wire.read() << 8) | Wire.read();
  az_raw = (Wire.read() << 8) | Wire.read();
  Wire.read(); Wire.read();  // Descartamos temperatura
  gx_raw = (Wire.read() << 8) | Wire.read();
  gy_raw = (Wire.read() << 8) | Wire.read();
  gz_raw = (Wire.read() << 8) | Wire.read();

  // Convertir a unidades físicas
  float ax = ax_raw / ACCEL_SENS;
  float ay = ay_raw / ACCEL_SENS;
  float az = az_raw / ACCEL_SENS;
  float gx = gx_raw / GYRO_SENS;
  float gy = gy_raw / GYRO_SENS;
  float gz = gz_raw / GYRO_SENS;

  // Enviar como CSV
  Serial.print(ax, 4); Serial.print(",");
  Serial.print(ay, 4); Serial.print(",");
  Serial.print(az, 4); Serial.print(",");
  Serial.print(gx, 4); Serial.print(",");
  Serial.print(gy, 4); Serial.print(",");
  Serial.println(gz, 4);

  delay(20);  // ~50 Hz de tasa de envío
}
