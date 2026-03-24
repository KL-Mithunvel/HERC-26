/*
========================================================
ROVER CONTROL FIRMWARE
========================================================

Channel Mapping
CH1 → Turning
CH2 → Forward / Reverse movement
CH3 → Throttle (speed limiter)

CH5 → Servo 0
CH6 → Servo 1
CH7 → Servo 2

CH8 → KILL SWITCH (Emergency stop)

Features
✓ Smooth acceleration
✓ Speed-based steering reduction
✓ Servo control
✓ Kill switch
✓ Signal failsafe
✓ Status LEDs
========================================================
*/

#include <IBusBM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// =====================================================
// ================= OBJECTS ===========================
// =====================================================

// FlySky IBUS receiver
IBusBM ibus;

// PCA9685 servo driver
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver();


// =====================================================
// ================= MOTOR PINS ========================
// =====================================================

// Motor layout
// 0 = Front Right
// 1 = Front Left
// 2 = Mid Right
// 3 = Mid Left
// 4 = Back Right
// 5 = Back Left

int motorPWM[6] = {2, 3, 6, 7, 4, 5};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};


// =====================================================
// ================= LED PINS ==========================
// =====================================================

#define LED_SIGNAL   30
#define LED_CH5      31
#define LED_CH7      32
#define LED_CH8      33


// =====================================================
// ================= SERVO CONSTANTS ===================
// =====================================================

#define SERVO_MIN 150
#define SERVO_MAX 600


// =====================================================
// ================= DRIVE CONSTANTS ===================
// =====================================================

#define DEADZONE 40
#define CENTER_PWM 1500

#define ABSOLUTE_MAX_PWM 255

#define LOOP_DELAY 10
#define FAILSAFE_TIMEOUT 500


// =====================================================
// ================= DRIVE TUNING ======================
// =====================================================

// Maximum turning power
#define TURN_MAX 180

// Reduce steering at high speeds
#define TURN_REDUCTION 1.0

// Smooth acceleration tuning
#define BASE_ACCEL_STEP 12
#define SLOP_FACTOR 0.35
#define MAX_ACCEL_STEP 25


// =====================================================
// ================= GLOBAL VARIABLES ==================
// =====================================================

int ch1, ch2, ch3, ch5, ch6, ch7, ch8;

// Current motor speeds (used for smooth acceleration)
float currentSpeedL = 0;
float currentSpeedR = 0;

// Last time a valid signal was received
unsigned long lastSignalTime = 0;


// =====================================================
// ================= SETUP =============================
// =====================================================

void setup() {

  Serial.begin(115200);

  // Start IBUS receiver
  ibus.begin(Serial1);

  // Configure motor pins
  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  // Configure LED pins
  pinMode(LED_SIGNAL, OUTPUT);
  pinMode(LED_CH5, OUTPUT);
  pinMode(LED_CH7, OUTPUT);
  pinMode(LED_CH8, OUTPUT);

  // Initialize PCA9685 servo driver
  Wire.begin();
  pca9685.begin();
  pca9685.setPWMFreq(50);

  stopAllMotors();
}


// =====================================================
// ================= MAIN LOOP =========================
// =====================================================

void loop() {

  // Read channels safely
  if (readChannelsSafe()) {

    lastSignalTime = millis();
    digitalWrite(LED_SIGNAL, HIGH);

    // If kill switch activated
    if (ch8 > 1500) {

      applyKillSwitch();
    }

    else {

      handleDrive();     // control motors
      handleServos();    // control servos
      handleLEDs();      // update indicator LEDs
    }
  }

  // If receiver signal lost
  else {

    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {

      digitalWrite(LED_SIGNAL, LOW);
      applyFailsafe();
    }
  }

  delay(LOOP_DELAY);
}


// =====================================================
// ================= DRIVE CONTROL =====================
// =====================================================

void handleDrive() {

  // CH2 = movement stick
  int moveRaw = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);

  // CH3 = throttle / speed limiter
  int throttleRaw = (abs(ch3 - CENTER_PWM) < DEADZONE) ? 0 : (ch3 - CENTER_PWM);

  // CH1 = turning
  int turnRaw = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  // Normalize values (-1 to +1)
  float moveFactor = moveRaw / 500.0;
  float throttleFactor = throttleRaw / 500.0;
  float turnFactor = turnRaw / 500.0;

  // Base forward/backward speed
  float X = moveFactor * ABSOLUTE_MAX_PWM;

  // Throttle limits maximum speed
  float limitedX = X * throttleFactor;

  // Reduce turning at higher speeds
  float speedRatio = abs(limitedX) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = 1.0 - (speedRatio * TURN_REDUCTION);

  turnReductionMultiplier = constrain(turnReductionMultiplier, 0.2, 1.0);

  float Y = turnFactor * TURN_MAX * turnReductionMultiplier;

  // Differential drive mixing
  float targetL = limitedX + Y;
  float targetR = limitedX - Y;

  targetL = constrain(targetL, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  targetR = constrain(targetR, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  // Smooth acceleration
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
// ================= SERVO CONTROL =====================
// =====================================================

void handleServos() {

  // CH5 controls Servo 0
  pca9685.setPWM(0, 0, (ch5 > 1500) ? SERVO_MAX : SERVO_MIN);

  // CH6 controls Servo 1
  pca9685.setPWM(1, 0, (ch6 > 1500) ? SERVO_MAX : SERVO_MIN);

  // CH7 controls Servo 2
  pca9685.setPWM(2, 0, (ch7 > 1500) ? SERVO_MAX : SERVO_MIN);
}


// =====================================================
// ================= LED INDICATORS ====================
// =====================================================

void handleLEDs() {

  digitalWrite(LED_CH5, (ch5 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH7, (ch6 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH8, (ch7 > 1500) ? HIGH : LOW);
}


// =====================================================
// ================= READ RECEIVER =====================
// =====================================================

bool readChannelsSafe() {

  int test = ibus.readChannel(2);

  // Validate signal
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(0);
  ch2 = ibus.readChannel(1);
  ch3 = ibus.readChannel(2);

  ch5 = ibus.readChannel(4);
  ch6 = ibus.readChannel(5);
  ch7 = ibus.readChannel(6);
  ch8 = ibus.readChannel(7);

  return true;
}


// =====================================================
// ================= SAFETY FUNCTIONS ==================
// =====================================================

// Kill switch
void applyKillSwitch() {

  stopAllMotors();

  for (int i = 0; i < 3; i++)
    pca9685.setPWM(i, 0, SERVO_MIN);
}


// Receiver failsafe
void applyFailsafe() {

  stopAllMotors();

  for (int i = 0; i < 3; i++)
    pca9685.setPWM(i, 0, SERVO_MIN);
}


// Stop all motors
void stopAllMotors() {

  currentSpeedL = 0;
  currentSpeedR = 0;

  for (int i = 0; i < 6; i++)
    analogWrite(motorPWM[i], 0);
}
