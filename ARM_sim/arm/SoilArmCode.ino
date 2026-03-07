#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ================= PCA9685 =================
Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40);

#define SERVO_FREQ 50   // Servo frequency (Hz)

// Typical servo pulse range (adjust if needed)
#define SERVO_MIN_US 500
#define SERVO_MAX_US 2500

// PCA channels
#define SERVO_1 0   // Base servo (reversed)
#define SERVO_2 1
#define SERVO_3 2

// ================= TRAJECTORY =================
struct Pose {
  float time_s;   // time to reach this pose from previous
  float th1;      // base angle
  float th2;
  float th3;
};

Pose trajectory[] = {
  {1.0, 0, 0, 0},
  {2.916, 0, 29.375, 94.68},
  {2.916, 0, 29.375, 94.68},
  {5.034, 0, 43.4375, 94.68},
  {3.993, 0, 43.4375, 125.93},
  {2.083, 0, 23.125, 125.93},
};

const int NUM_POSES = sizeof(trajectory) / sizeof(Pose);

// ================= STATE =================
float currentAngles[3] = {0, 0, 0};
float startAngles[3];
float targetAngles[3];

unsigned long segmentStartMs;
unsigned long segmentDurationMs;
int currentPose = 0;
bool segmentActive = false;

// ================= UTILITY =================

// Convert servo angle to PCA9685 PWM value
uint16_t angleToPWM(float angleDeg) {

  angleDeg = constrain(angleDeg, 0, 180);

  float pulseUs =
    SERVO_MIN_US +
    (angleDeg / 180.0) * (SERVO_MAX_US - SERVO_MIN_US);

  return (uint16_t)(pulseUs * SERVO_FREQ * 4096 / 1000000);
}

// Send angles to servos
void setServos(float a1, float a2, float a3) {

  // Reverse base servo direction
  float reversedA1 = 180.0 - a1;

  pca.setPWM(SERVO_1, 0, angleToPWM(reversedA1));
  pca.setPWM(SERVO_2, 0, angleToPWM(a2));
  pca.setPWM(SERVO_3, 0, angleToPWM(a3));
}

// ================= SETUP =================
void setup() {

  Wire.begin();

  pca.begin();
  pca.setPWMFreq(SERVO_FREQ);

  delay(500);

  // Start at first pose
  currentAngles[0] = trajectory[0].th1;
  currentAngles[1] = trajectory[0].th2;
  currentAngles[2] = trajectory[0].th3;

  setServos(
    currentAngles[0],
    currentAngles[1],
    currentAngles[2]
  );

  currentPose = 0;
  segmentActive = false;
}

// ================= LOOP =================
void loop() {

  // Stop after final pose
  if (currentPose >= NUM_POSES - 1) return;

  // Start new motion segment
  if (!segmentActive) {

    startAngles[0] = currentAngles[0];
    startAngles[1] = currentAngles[1];
    startAngles[2] = currentAngles[2];

    targetAngles[0] = trajectory[currentPose + 1].th1;
    targetAngles[1] = trajectory[currentPose + 1].th2;
    targetAngles[2] = trajectory[currentPose + 1].th3;

    segmentDurationMs =
      trajectory[currentPose + 1].time_s * 1000.0;

    segmentStartMs = millis();
    segmentActive = true;
  }

  unsigned long now = millis();

  float t = (now - segmentStartMs) / (float)segmentDurationMs;

  if (t >= 1.0) t = 1.0;

  // Linear interpolation for smooth motion
  currentAngles[0] =
    startAngles[0] +
    t * (targetAngles[0] - startAngles[0]);

  currentAngles[1] =
    startAngles[1] +
    t * (targetAngles[1] - startAngles[1]);

  currentAngles[2] =
    startAngles[2] +
    t * (targetAngles[2] - startAngles[2]);

  setServos(
    currentAngles[0],
    currentAngles[1],
    currentAngles[2]
  );

  // Move to next pose
  if (t >= 1.0) {
    currentPose++;
    segmentActive = false;
  }

  delay(10);   // ~100 Hz update rate
}
