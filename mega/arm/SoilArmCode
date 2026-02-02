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

// ================= TRAJECTORY =================
struct Pose {
  float time_s;   // time to reach this pose from previous
  float th1;      // 0–180 sweep
  float th2;
  float th3;
};

Pose trajectory[] = {
  {3.0208333333,180,159.6875,150.625},
  {3.0555555556,31.875,83.4375,30.3125},
  {3.0555555556,0,0,20.9375},
  {3.0555555556,0,49.375,104.6875},
  {2.0486111111,0,100.0,40.9375},
  {2.0486111111,55.3125,100.0,0},
  {2.0486111111,109.6875,61.875,0},
  {2.0486111111,115.0,180,0},
  {1.1458333333,115.0,180,87.1875},
  {2.3263888889,180,180,123.4375}
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

  // Start from first pose smoothly
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
  if (currentPose >= NUM_POSES - 1) return;

  if (!segmentActive) {
    // Start new segment
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

  // Linear interpolation
  currentAngles[0] = startAngles[0] +
                     t * (targetAngles[0] - startAngles[0]);
  currentAngles[1] = startAngles[1] +
                     t * (targetAngles[1] - startAngles[1]);
  currentAngles[2] = startAngles[2] +
                     t * (targetAngles[2] - startAngles[2]);

  setServos(
    currentAngles[0],
    currentAngles[1],
    currentAngles[2]
  );

  if (t >= 1.0) {
    currentPose++;
    segmentActive = false;
  }

  delay(10);  // ~100 Hz update
}
