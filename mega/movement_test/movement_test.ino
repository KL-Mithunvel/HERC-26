#include <IBusBM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

IBusBM ibus;
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver();

// ---------------- MOTOR PINS (Mapped by Driver) ----------------
// Driver 1: Front [0]=Right, [1]=Left
// Driver 2: Mid   [2]=Right, [3]=Left
// Driver 3: Back  [4]=Right, [5]=Left
int motorPWM[6] = {2, 3, 6, 7, 4, 5};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};

// Index helpers for clarity
#define FRONT_R 0
#define FRONT_L 1
#define MID_R   2
#define MID_L   3
#define BACK_R  4
#define BACK_L  5

// ---------------- LED PINS ----------------
#define LED_SIGNAL   30
#define LED_CH5      31
#define LED_CH7      32
#define LED_CH8      33

// ---------------- CONSTANTS ----------------
#define SERVO_MIN 150
#define SERVO_MAX 600
#define DEADZONE 40      
#define CENTER_PWM 1500

#define ABSOLUTE_MAX_PWM   255   
#define ACCEL_STEP         15    
#define LOOP_DELAY         10    
#define FAILSAFE_TIMEOUT   500

// ---------------- GLOBALS ----------------
int ch1, ch2, ch3, ch5, ch7, ch8;
float currentSpeedL = 0;
float currentSpeedR = 0;
unsigned long lastSignalTime = 0;
unsigned long testStartTime = 0;

void setup() {
  Serial.begin(115200);
  ibus.begin(Serial1);

  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  pinMode(LED_SIGNAL, OUTPUT);
  pinMode(LED_CH5, OUTPUT);
  pinMode(LED_CH7, OUTPUT);
  pinMode(LED_CH8, OUTPUT);

  Wire.begin();
  pca9685.begin();
  pca9685.setPWMFreq(50);

  stopAllMotors();
}

void loop() {
  if (readChannelsSafe()) {
    lastSignalTime = millis();
    digitalWrite(LED_SIGNAL, HIGH);

    // --- MODE SWITCHING ---
    if (ch5 > 1700) { // Test Mode Active
      runTestMode();
    } else {          // Normal Mode
      testStartTime = 0; // Reset timer for next time
      handleDrive();
    }
    
    handleServos();
    handleLEDs();
  } else {
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      digitalWrite(LED_SIGNAL, LOW);
      applyFailsafe();
    }
  }
  delay(LOOP_DELAY);
}

// =================================================
// TEST MODE LOGIC (Sequence: R Front -> R Mid -> R Back -> L Front -> L Mid -> L Back)
// =================================================
void runTestMode() {
  if (testStartTime == 0) testStartTime = millis();
  unsigned long elapsed = millis() - testStartTime;
  
  stopAllMotors(); // Default everything to off each frame
  int testSpeed = 150; // Moderate speed for testing

  // Right Side Sequence (0s, 4s, 8s marks)
  if (elapsed >= 0 && elapsed < 2000)        runMotor(FRONT_R, testSpeed);
  else if (elapsed >= 4000 && elapsed < 6000)  runMotor(MID_R,   testSpeed);
  else if (elapsed >= 8000 && elapsed < 10000) runMotor(BACK_R,  testSpeed);

  // Left Side Sequence (Starts after 10s)
  else if (elapsed >= 10000 && elapsed < 12000) runMotor(FRONT_L, testSpeed);
  else if (elapsed >= 14000 && elapsed < 16000) runMotor(MID_L,   testSpeed);
  else if (elapsed >= 18000 && elapsed < 20000) runMotor(BACK_L,  testSpeed);

  // Restart Sequence
  else if (elapsed >= 22000) testStartTime = millis(); 
}

void runMotor(int motorIdx, int speed) {
  digitalWrite(motorDIR[motorIdx], HIGH); // Forward
  analogWrite(motorPWM[motorIdx], speed);
}

// =================================================
// NORMAL DRIVE LOGIC
// =================================================
void handleDrive() {
  int speedLimit = map(ch3, 1000, 2000, 0, ABSOLUTE_MAX_PWM);
  speedLimit = constrain(speedLimit, 0, ABSOLUTE_MAX_PWM);

  int moveRaw = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int turnRaw = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  float moveFact = moveRaw / 500.0;
  float turnFact = turnRaw / 500.0;

  float targetL = (moveFact + turnFact) * speedLimit;
  float targetR = (moveFact - turnFact) * speedLimit;

  targetL = constrain(targetL, -speedLimit, speedLimit);
  targetR = constrain(targetR, -speedLimit, speedLimit);

  // Steep Ramping
  if (currentSpeedL < targetL) currentSpeedL += ACCEL_STEP;
  else if (currentSpeedL > targetL) currentSpeedL -= ACCEL_STEP;

  if (currentSpeedR < targetR) currentSpeedR += ACCEL_STEP;
  else if (currentSpeedR > targetR) currentSpeedR -= ACCEL_STEP;

  // Apply to Right Motors (Index 0, 2, 4)
  for (int i = 0; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedR >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedR));
  }
  // Apply to Left Motors (Index 1, 3, 5)
  for (int i = 1; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedL >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedL));
  }
}

// =================================================
// UTILS
// =================================================

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
  for (int i = 0; i < 3; i++) pca9685.setPWM(i, 0, SERVO_MIN);
}

void stopAllMotors() {
  currentSpeedL = 0;
  currentSpeedR = 0;
  for (int i = 0; i < 6; i++) analogWrite(motorPWM[i], 0);
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