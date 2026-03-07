/*
✅ Right stick vertical → Main movement
✅ Left stick vertical → Speed envelope limiter
✅ Right stick horizontal → Turning
✅ Speed-based steering reduction
✅ Adjustable sloppy acceleration
✅ Test mode
✅ Failsafe
✅ Small comments explaining each section
*/
#include <IBusBM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ================= OBJECTS =================
IBusBM ibus;                              // FlySky IBUS receiver
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver();  // Servo driver

// ================= MOTOR PINS =================
// Index mapping:
// 0 = Front Right
// 1 = Front Left
// 2 = Mid Right
// 3 = Mid Left
// 4 = Back Right
// 5 = Back Left

int motorPWM[6] = {2, 3, 6, 7, 4, 5};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};

// ================= LED PINS =================
#define LED_SIGNAL   30
#define LED_CH5      31
#define LED_CH7      32
#define LED_CH8      33

// ================= BASIC CONSTANTS =================
#define SERVO_MIN 150
#define SERVO_MAX 600

#define DEADZONE 40
#define CENTER_PWM 1500

#define ABSOLUTE_MAX_PWM 255
#define LOOP_DELAY 10
#define FAILSAFE_TIMEOUT 500

// ================= DRIVE TUNING =================
// Max turning strength
#define TURN_MAX 180

// How much turning reduces at high speed (1.0 = strong reduction)
#define TURN_REDUCTION 1.0

// Acceleration control parameters
#define BASE_ACCEL_STEP 12
#define SLOP_FACTOR 0.35      // Higher = more “sloppy” feel
#define MAX_ACCEL_STEP 25

// ================= GLOBAL VARIABLES =================
int ch1, ch2, ch3, ch5, ch7, ch8;

float currentSpeedL = 0;
float currentSpeedR = 0;

unsigned long lastSignalTime = 0;
unsigned long testStartTime = 0;

// =====================================================

void setup() {

  Serial.begin(115200);
  ibus.begin(Serial1);     // IBUS on Serial1

  // Setup motor pins
  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  // Setup LEDs
  pinMode(LED_SIGNAL, OUTPUT);
  pinMode(LED_CH5, OUTPUT);
  pinMode(LED_CH7, OUTPUT);
  pinMode(LED_CH8, OUTPUT);

  // Setup PCA9685 servo driver
  Wire.begin();
  pca9685.begin();
  pca9685.setPWMFreq(50);

  stopAllMotors();
}

// =====================================================

void loop() {

  if (readChannelsSafe()) {

    lastSignalTime = millis();
    digitalWrite(LED_SIGNAL, HIGH);

    // CH5 high → Test Mode
    if (ch5 > 1700) {
      runTestMode();
    }
    else {
      testStartTime = 0;
      handleDrive();   // Normal drive logic
    }

    handleServos();
    handleLEDs();
  }
  else {
    // If signal lost for some time → stop everything
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      digitalWrite(LED_SIGNAL, LOW);
      applyFailsafe();
    }
  }

  delay(LOOP_DELAY);
}

// =====================================================
// ================= DRIVE LOGIC =======================
// Right stick vertical  → Main movement
// Left stick vertical   → Speed envelope
// Right stick horizontal → Turning
// =====================================================

void handleDrive() {

  // Read sticks (with deadzone)
  int moveRaw = (abs(ch3 - CENTER_PWM) < DEADZONE) ? 0 : (ch3 - CENTER_PWM);
  int speedScaleRaw = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int turnRaw = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  // Normalize to -1 to +1
  float moveFactor = moveRaw / 500.0;
  float speedScaleFactor = speedScaleRaw / 500.0;
  float turnFactor = turnRaw / 500.0;

  // Base speed from right stick
  float X = moveFactor * ABSOLUTE_MAX_PWM;

  // Left stick limits the maximum allowed movement (envelope)
  float limitedX = X * speedScaleFactor;

  // Reduce turning at high speeds to prevent instability
  float speedRatio = abs(limitedX) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = 1.0 - (speedRatio * TURN_REDUCTION);
  turnReductionMultiplier = constrain(turnReductionMultiplier, 0.2, 1.0);

  float Y = turnFactor * TURN_MAX * turnReductionMultiplier;

  // Differential drive mixing
  float targetL = limitedX + Y;
  float targetR = limitedX - Y;

  targetL = constrain(targetL, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  targetR = constrain(targetR, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  // Sloppy acceleration logic
  float diffL = targetL - currentSpeedL;
  float diffR = targetR - currentSpeedR;

  float dynamicStepL = BASE_ACCEL_STEP + abs(diffL) * SLOP_FACTOR;
  float dynamicStepR = BASE_ACCEL_STEP + abs(diffR) * SLOP_FACTOR;

  dynamicStepL = constrain(dynamicStepL, BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  dynamicStepR = constrain(dynamicStepR, BASE_ACCEL_STEP, MAX_ACCEL_STEP);

  if (diffL > 0)
    currentSpeedL += min(dynamicStepL, diffL);
  else
    currentSpeedL -= min(dynamicStepL, -diffL);

  if (diffR > 0)
    currentSpeedR += min(dynamicStepR, diffR);
  else
    currentSpeedR -= min(dynamicStepR, -diffR);

  // Apply speeds to motors
  for (int i = 0; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedR >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedR));
  }

  for (int i = 1; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedL >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedL));
  }
}

// =====================================================
// ================= TEST MODE =========================
// Runs each motor individually for debugging
// =====================================================

void runTestMode() {

  if (testStartTime == 0) testStartTime = millis();
  unsigned long elapsed = millis() - testStartTime;

  stopAllMotors();
  int testSpeed = 150;

  if (elapsed >= 0 && elapsed < 2000) runMotor(0, testSpeed);
  else if (elapsed >= 4000 && elapsed < 6000) runMotor(2, testSpeed);
  else if (elapsed >= 8000 && elapsed < 10000) runMotor(4, testSpeed);
  else if (elapsed >= 10000 && elapsed < 12000) runMotor(1, testSpeed);
  else if (elapsed >= 14000 && elapsed < 16000) runMotor(3, testSpeed);
  else if (elapsed >= 18000 && elapsed < 20000) runMotor(5, testSpeed);
  else if (elapsed >= 22000) testStartTime = millis();
}

void runMotor(int motorIdx, int speed) {
  digitalWrite(motorDIR[motorIdx], HIGH);
  analogWrite(motorPWM[motorIdx], speed);
}

// =====================================================
// ================= UTILITIES =========================
// =====================================================

bool readChannelsSafe() {

  int test = ibus.readChannel(2);
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(0);
  ch2 = ibus.readChannel(1);
  ch3 = ibus.readChannel(2);
  ch5 = ibus.readChannel(4);
  ch7 = ibus.readChannel(6);
  ch8 = ibus.readChannel(7);

  return true;
}

void applyFailsafe() {
  stopAllMotors();
  for (int i = 0; i < 3; i++)
    pca9685.setPWM(i, 0, SERVO_MIN);
}

void stopAllMotors() {
  currentSpeedL = 0;
  currentSpeedR = 0;
  for (int i = 0; i < 6; i++)
    analogWrite(motorPWM[i], 0);
}

void handleServos() {
  pca9685.setPWM(0, 0, (ch5 > 1500) ? SERVO_MAX : SERVO_MIN);
  pca9685.setPWM(1, 0, (ch7 > 1500) ? SERVO_MAX : SERVO_MIN);
  pca9685.setPWM(2, 0, (ch8 > 1500) ? SERVO_MAX : SERVO_MIN);
}

void handleLEDs() {
  digitalWrite(LED_CH5, (ch5 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH7, (ch7 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH8, (ch8 > 1500) ? HIGH : LOW);
}
