/*
========================================================
ROVER CONTROL FIRMWARE - MERGED
========================================================

Channel Mapping
CH1 → Turning
CH2 → Forward / Reverse movement
CH3 → Throttle (speed limiter)
CH4 → Manual spray servo control
CH5 → Soil arm trigger (4 cycles)
CH6 → Spray sequence trigger (motors disabled while ON)

CH8 → KILL SWITCH (Emergency stop)

Features
✓ Smooth acceleration
✓ Speed-based steering reduction
✓ 360° servo 270° sweep + return (CH6)
✓ Pump runs 20 sec then servo returns (CH6)
✓ CH6 OFF → servo returns to initial immediately
✓ Manual spray control (CH4)
✓ Motors disabled during spray (CH6 ON)
✓ 5 sec servo access after CH6 OFF
✓ Soil arm 3-servo sequence, 4 cycles (CH5)
✓ Kill switch
✓ Signal failsafe
✓ Extended return time to guarantee full return to initial position
========================================================
*/

#include <IBusBM.h>
#include <Servo.h>

// =====================================================
// ================= OBJECTS ===========================
// =====================================================

IBusBM ibus;
Servo sprayServo;
Servo servo_end, servo_middle, servo_base;


// =====================================================
// ================= MOTOR PINS ========================
// =====================================================

int motorPWM[6] = {2, 3, 6, 7, 4, 5};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};


// =====================================================
// ================= SERVO & PUMP PINS =================
// =====================================================

#define SERVO_PIN        12
#define PUMP_PIN         50

#define SOIL_END_PIN     10
#define SOIL_MIDDLE_PIN  9
#define SOIL_BASE_PIN    8


// =====================================================
// ================= DRIVE CONSTANTS ===================
// =====================================================

#define DEADZONE          40
#define CENTER_PWM      1500
#define ABSOLUTE_MAX_PWM 255
#define LOOP_DELAY        10
#define FAILSAFE_TIMEOUT 500


// =====================================================
// ================= DRIVE TUNING ======================
// =====================================================

#define TURN_MAX         180
#define TURN_REDUCTION   1.0
#define BASE_ACCEL_STEP   12
#define SLOP_FACTOR      0.35
#define MAX_ACCEL_STEP    25


// =====================================================
// ================= SERVO SPEED SETTINGS ==============
// =====================================================

#define SERVO_STOP      90
#define SERVO_FORWARD   80
#define SERVO_REVERSE  100


// =====================================================
// ================= SPRAY SEQUENCE TUNING =============
// =====================================================

const unsigned long rotateTime       = 2500;
const unsigned long rotateBackTime   = rotateTime * 2;  // ← extended return time to guarantee full return
const unsigned long pumpTime         = 20000;
const unsigned long postOffServoTime = 5000;


// =====================================================
// ================= SOIL ARM TUNING ===================
// =====================================================

const int           MAX_REPEATS  = 4;
const unsigned long STEP_DELAY   = 60;


// =====================================================
// ================= SPRAY STATE MACHINE ===============
// =====================================================

enum SprayState {
  SPRAY_IDLE,
  SPRAY_ROTATING_OUT,
  SPRAY_PUMPING,
  SPRAY_ROTATING_BACK,
  SPRAY_DONE
};

SprayState sprayState = SPRAY_IDLE;


// =====================================================
// ================= SOIL ARM STATE MACHINE ============
// =====================================================

enum SoilState {
  SOIL_IDLE,
  SOIL_RUNNING,
  SOIL_DONE
};

SoilState soilState = SOIL_IDLE;


// =====================================================
// ================= GLOBAL VARIABLES ==================
// =====================================================

int ch1, ch2, ch3, ch4, ch5, ch6, ch8;

float currentSpeedL = 0;
float currentSpeedR = 0;

unsigned long lastSignalTime  = 0;
unsigned long servoStartTime  = 0;
unsigned long pumpStartTime   = 0;
unsigned long ch6OffTime      = 0;

bool ch6WasOn           = false;
bool postOffServoActive = false;

int  pose_base          = 0;
int  pose_middle        = 0;
int  pose_end           = 0;
int  soilStep           = 0;
int  repeatCount        = 0;
unsigned long lastSoilUpdate = 0;
bool ch5WasOn           = false;


// =====================================================
// ================= SETUP =============================
// =====================================================

void setup() {

  Serial.begin(115200);
  ibus.begin(Serial1);

  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  pinMode(PUMP_PIN, OUTPUT);
  digitalWrite(PUMP_PIN, LOW);

  sprayServo.attach(SERVO_PIN);
  sprayServo.write(SERVO_STOP);

  servo_end.attach(SOIL_END_PIN);
  servo_middle.attach(SOIL_MIDDLE_PIN);
  servo_base.attach(SOIL_BASE_PIN);
  servo_end.write(0);
  servo_middle.write(0);
  servo_base.write(0);

  stopAllMotors();
}


// =====================================================
// ================= MAIN LOOP =========================
// =====================================================

void loop() {

  if (readChannelsSafe()) {

    lastSignalTime = millis();

    if (ch8 > 1500) {
      applyKillSwitch();
    }
    else {

      // -------- CH6 ON → spray mode --------
      if (ch6 > 1500) {
        stopAllMotors();
        ch6WasOn          = true;
        postOffServoActive = false;
        handleSpraySequence();
      }

      // -------- CH6 OFF --------
      else {

        if (ch6WasOn) {
          ch6WasOn          = false;
          postOffServoActive = true;
          ch6OffTime         = millis();
          abortSpraySequence();
        }

        if (postOffServoActive) {
          if (millis() - ch6OffTime < postOffServoTime) {
            if (ch4 > 1600)
              sprayServo.write(SERVO_FORWARD);
            else if (ch4 < 1400)
              sprayServo.write(SERVO_REVERSE);
            else
              sprayServo.write(SERVO_STOP);
          }
          else {
            sprayServo.write(SERVO_STOP);
            postOffServoActive = false;
          }
        }

        // -------- CH5 ON → soil arm --------
        if (ch5 > 1500) {

          if (!ch5WasOn) {
            ch5WasOn    = true;
            resetSoilArm();
            soilState   = SOIL_RUNNING;
            soilStep    = 1;
            repeatCount = 0;
            Serial.println("Soil arm started.");
          }

          handleSoilArm();
        }

        // -------- CH5 OFF --------
        else {

          if (ch5WasOn) {
            ch5WasOn = false;
            abortSoilArm();
          }

          handleDrive();
        }
      }
    }
  }
  else {
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      applyFailsafe();
    }
  }

  delay(LOOP_DELAY);
}


// =====================================================
// ================= DRIVE CONTROL =====================
// =====================================================

void handleDrive() {

  int moveRaw     = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int throttleRaw = (abs(ch3 - CENTER_PWM) < DEADZONE) ? 0 : (ch3 - CENTER_PWM);
  int turnRaw     = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  float moveFactor     = moveRaw     / 500.0;
  float throttleFactor = throttleRaw / 500.0;
  float turnFactor     = turnRaw     / 500.0;

  float X        = moveFactor * ABSOLUTE_MAX_PWM;
  float limitedX = X * throttleFactor;

  float speedRatio              = abs(limitedX) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = constrain(1.0 - (speedRatio * TURN_REDUCTION), 0.2, 1.0);

  float Y = turnFactor * TURN_MAX * turnReductionMultiplier;

  float targetL = constrain(limitedX + Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  float targetR = constrain(limitedX - Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  float diffL = targetL - currentSpeedL;
  float diffR = targetR - currentSpeedR;

  float dynamicStepL = constrain(BASE_ACCEL_STEP + abs(diffL) * SLOP_FACTOR, BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  float dynamicStepR = constrain(BASE_ACCEL_STEP + abs(diffR) * SLOP_FACTOR, BASE_ACCEL_STEP, MAX_ACCEL_STEP);

  currentSpeedL += (diffL > 0) ?  min(dynamicStepL,  diffL) : -min(dynamicStepL, -diffL);
  currentSpeedR += (diffR > 0) ?  min(dynamicStepR,  diffR) : -min(dynamicStepR, -diffR);

  for (int i = 0; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedR >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedR));
  }
  for (int i = 1; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedL >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedL));
  }
}


// =====================================================
// ================= SPRAY SEQUENCE ====================
// =====================================================

void handleSpraySequence() {

  switch (sprayState) {

    case SPRAY_IDLE:
      sprayServo.write(SERVO_FORWARD);
      servoStartTime = millis();
      sprayState     = SPRAY_ROTATING_OUT;
      break;

    case SPRAY_ROTATING_OUT:
      if (millis() - servoStartTime >= rotateTime) {
        sprayServo.write(SERVO_STOP);
        digitalWrite(PUMP_PIN, HIGH);
        pumpStartTime = millis();
        sprayState    = SPRAY_PUMPING;
      }
      break;

    case SPRAY_PUMPING:
      if (ch4 > 1600)
        sprayServo.write(SERVO_FORWARD);
      else if (ch4 < 1400)
        sprayServo.write(SERVO_REVERSE);
      else
        sprayServo.write(SERVO_STOP);

      if (millis() - pumpStartTime >= pumpTime) {
        digitalWrite(PUMP_PIN, LOW);
        sprayServo.write(SERVO_REVERSE);
        servoStartTime = millis();
        sprayState     = SPRAY_ROTATING_BACK;
      }
      break;

    case SPRAY_ROTATING_BACK:
      // ↓ Use rotateBackTime (2× rotateTime) to guarantee full return to initial position
      if (millis() - servoStartTime >= rotateBackTime) {
        sprayServo.write(SERVO_STOP);
        sprayState = SPRAY_DONE;
      }
      break;

    case SPRAY_DONE:
      sprayServo.write(SERVO_STOP);
      break;
  }
}


// =====================================================
// ================= ABORT SPRAY =======================
// =====================================================

void abortSpraySequence() {

  digitalWrite(PUMP_PIN, LOW);

  if (sprayState == SPRAY_ROTATING_OUT ||
      sprayState == SPRAY_PUMPING      ||
      sprayState == SPRAY_ROTATING_BACK) {
    sprayServo.write(SERVO_REVERSE);
    delay(rotateBackTime);  // ← extended time to guarantee full return to initial position
  }

  sprayServo.write(SERVO_STOP);
  sprayState = SPRAY_IDLE;
}


// =====================================================
// ================= SOIL ARM SEQUENCE =================
// =====================================================

void handleSoilArm() {

  if (soilState != SOIL_RUNNING) return;
  if (millis() - lastSoilUpdate < STEP_DELAY) return;
  lastSoilUpdate = millis();

  switch (soilStep) {

    case 1:
      if (pose_middle < 80) servo_middle.write(pose_middle++);
      else soilStep = 2;
      break;

    case 2:
      if (pose_base < 80) servo_base.write(pose_base++);
      else soilStep = 3;
      break;

    case 3:
      if (pose_middle < 120) servo_middle.write(pose_middle++);
      else soilStep = 4;
      break;

    case 4:
      if (pose_end < 120) servo_end.write(pose_end++);
      else soilStep = 5;
      break;

    case 5:
      if (pose_middle > 100) servo_middle.write(pose_middle--);
      else soilStep = 6;
      break;

    case 6:
      if (pose_base > 0) servo_base.write(pose_base--);
      else soilStep = 7;
      break;

    case 7:
      if (pose_middle > 0) {
        servo_middle.write(pose_middle--);
      }
      else {
        repeatCount++;
        Serial.print("Soil cycle done: ");
        Serial.print(repeatCount);
        Serial.print(" / ");
        Serial.println(MAX_REPEATS);

        if (repeatCount < MAX_REPEATS) {
          pose_base   = 0;
          pose_middle = 0;
          pose_end    = 0;
          soilStep    = 1;
        }
        else {
          soilState = SOIL_DONE;
          Serial.println("All soil cycles complete.");
        }
      }
      break;
  }
}


// =====================================================
// ================= RESET / ABORT SOIL ARM ============
// =====================================================

void resetSoilArm() {
  pose_base   = 0;
  pose_middle = 0;
  pose_end    = 0;
  servo_end.write(0);
  servo_middle.write(0);
  servo_base.write(0);
  delay(300);
}

void abortSoilArm() {
  soilState   = SOIL_IDLE;
  soilStep    = 0;
  repeatCount = 0;
  resetSoilArm();
  Serial.println("Soil arm aborted.");
}


// =====================================================
// ================= READ RECEIVER =====================
// =====================================================

bool readChannelsSafe() {

  int test = ibus.readChannel(2);
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(0);
  ch2 = ibus.readChannel(1);
  ch3 = ibus.readChannel(2);
  ch4 = ibus.readChannel(3);
  ch5 = ibus.readChannel(4);
  ch6 = ibus.readChannel(5);
  ch8 = ibus.readChannel(7);

  return true;
}


// =====================================================
// ================= SAFETY FUNCTIONS ==================
// =====================================================

void applyKillSwitch() {
  stopAllMotors();
  digitalWrite(PUMP_PIN, LOW);
  sprayServo.write(SERVO_STOP);
  sprayState         = SPRAY_IDLE;
  postOffServoActive = false;
  abortSoilArm();
}

void applyFailsafe() {
  stopAllMotors();
  digitalWrite(PUMP_PIN, LOW);
  sprayServo.write(SERVO_STOP);
  sprayState         = SPRAY_IDLE;
  postOffServoActive = false;
  abortSoilArm();
}

void stopAllMotors() {
  currentSpeedL = 0;
  currentSpeedR = 0;
  for (int i = 0; i < 6; i++)
    analogWrite(motorPWM[i], 0);
}
