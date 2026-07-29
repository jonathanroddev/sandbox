/*
  mpu_serial_bridge.ino
  ----------------------
  Reads accelerometer + gyroscope from an MPU-6050 over I2C and sends the
  values over Serial as CSV, one line per reading:

      ax,ay,az,gx,gy,gz

  - ax,ay,az in "g" (acceleration, ±2g by default)
  - gx,gy,gz in degrees/second (angular rate, ±250°/s by default)

  HARDWARE (confirmed by WHO_AM_I=0x68 diagnostics):
    The sensor is an MPU-6050 (6 axes, accel + gyro). It has NO
    magnetometer, so there is no absolute heading: yaw can only be
    integrated from the gyroscope and will therefore drift over time.
    Roll and pitch ARE absolute (gravity reference) and stable.

  I2C wiring (Arduino Uno, GY-521 / MPU-6050 module):
    VCC -> 5V (the GY-521 has an on-board 3.3V regulator)
    GND -> GND
    SCL -> A5
    SDA -> A4
*/

#include <Wire.h>

const int MPU_ADDR = 0x68;   // MPU-6050 I2C address (AD0 to GND)
const long BAUD_RATE = 115200;

// Default sensitivities
const float ACCEL_SENS = 16384.0;  // LSB/g for the ±2g range
const float GYRO_SENS  = 131.0;    // LSB/(°/s) for the ±250°/s range

void setup() {
  Wire.begin();
  Serial.begin(BAUD_RATE);

  // Wake up the MPU-6050 (it boots in "sleep" mode by default)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);  // PWR_MGMT_1 register
  Wire.write(0x00);  // Set to 0 => wakes the sensor
  Wire.endTransmission(true);

  // EXPLICITLY set the gyroscope range to ±250°/s (FS_SEL=0)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);  // GYRO_CONFIG
  Wire.write(0x00);  // FS_SEL=0 => ±250°/s => 131 LSB/(°/s)
  Wire.endTransmission(true);

  // EXPLICITLY set the accelerometer range to ±2g (AFS_SEL=0)
  // (don't trust the default: some clones don't boot in ±2g)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);  // ACCEL_CONFIG
  Wire.write(0x00);  // AFS_SEL=0 => ±2g => 16384 LSB/g
  Wire.endTransmission(true);

  delay(100);
}

void loop() {
  int16_t ax_raw, ay_raw, az_raw;
  int16_t gx_raw, gy_raw, gz_raw;

  // ---- Read accel + gyro (14 bytes from 0x3B) ----
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 14, true);

  ax_raw = (Wire.read() << 8) | Wire.read();
  ay_raw = (Wire.read() << 8) | Wire.read();
  az_raw = (Wire.read() << 8) | Wire.read();
  Wire.read(); Wire.read();  // Discard temperature
  gx_raw = (Wire.read() << 8) | Wire.read();
  gy_raw = (Wire.read() << 8) | Wire.read();
  gz_raw = (Wire.read() << 8) | Wire.read();

  // Convert to physical units
  float ax = ax_raw / ACCEL_SENS;
  float ay = ay_raw / ACCEL_SENS;
  float az = az_raw / ACCEL_SENS;
  float gx = gx_raw / GYRO_SENS;
  float gy = gy_raw / GYRO_SENS;
  float gz = gz_raw / GYRO_SENS;

  // Send as CSV
  Serial.print(ax, 4); Serial.print(",");
  Serial.print(ay, 4); Serial.print(",");
  Serial.print(az, 4); Serial.print(",");
  Serial.print(gx, 4); Serial.print(",");
  Serial.print(gy, 4); Serial.print(",");
  Serial.println(gz, 4);

  delay(20);  // ~50 Hz send rate
}
