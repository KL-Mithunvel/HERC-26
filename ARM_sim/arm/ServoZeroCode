#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ================= PCA9685 =================
Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40);

#define SERVO_FREQ 50   // Hz

// Typical servo pulse range (adjust if needed)
#define SERVO_MIN_US 500
#define SERVO_MAX_US 2500

// PCA channels
#define SERVO_1 0
#define SERVO_2 1
#define SERVO_3 2

// ================= UTILITY =================
uint16_t angleToPWM(float angleDeg) {
  angleDeg = constrain(angleDeg, 0, 180);

  float pulseUs =
    SERVO_MIN_US +
    (angleDeg / 180.0) * (SERVO_MAX_US - SERVO_MIN_US);

  return (uint16_t)(pulseUs * SERVO_FREQ * 4096 / 1000000);
}

void setServos(float a1, float a2, float a3) {
  pca.setPWM(SERVO_1, 0, angleToPWM(a1));
  pca.setPWM(SERVO_2, 0, angleToPWM(a2));
  pca.setPWM(SERVO_3, 0, angleToPWM(a3));
}

// ================= SETUP =================
void setup() {
  Wire.begin();
  pca.begin();
  pca.setPWMFreq(SERVO_FREQ);
  delay(500);

  // Move all servos to 0°
  setServos(0, 0, 0);
}

// ================= LOOP =================
void loop() {
  // Nothing here — servos stay at 0°
}
