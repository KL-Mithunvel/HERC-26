#include <IBusBM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

IBusBM ibus;
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver();

// ---------------- MOTOR PINS (6 MOTORS) ----------------
int motorPWM[6] = {2, 3, 6, 7, 9, 10};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};

// ---------------- LED PINS ----------------
#define LED_SIGNAL   30
#define LED_CH5      31
#define LED_CH7      32
#define LED_CH8      33

// ---------------- CONSTANTS ----------------
#define SERVO_MIN 150
#define SERVO_MAX 600

// ===== MOTOR SAFETY LIMITS (MDD10A SAFE) =====
#define MAX_PWM            160   // ~63% duty cycle Speed Limiter
#define START_PWM          100
#define ACCEL_STEP         2
#define LOOP_DELAY         20
#define DIR_CHANGE_DELAY   200   // ms

#define FAILSAFE_TIMEOUT   500

// ---------------- GLOBALS ----------------
int ch1, ch2, ch3, ch5, ch7, ch8;

int targetSpeed = 0;
int currentSpeed = 0;

unsigned long lastSignalTime = 0;
bool failsafeActive = false;

// ------------------------------------------------
// SETUP
// ------------------------------------------------
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
  moveServosToSafe();
}

// ------------------------------------------------
// MAIN LOOP
// ------------------------------------------------
void loop() {

  // -------- SIGNAL CHECK --------
  if (readChannelsSafe()) {
    lastSignalTime = millis();
    failsafeActive = false;
    digitalWrite(LED_SIGNAL, HIGH);
  } else {
    digitalWrite(LED_SIGNAL, LOW);
  }

  // -------- FAILSAFE --------
  if (isFailsafeActive()) {
    applyFailsafe();
    delay(LOOP_DELAY);
    return;
  }

  // -------- NORMAL OPERATION --------
  handleDirection();
  handleThrottleTrapezoidal();
  handleServos();
  handleLEDs();

  delay(LOOP_DELAY);
}

// =================================================
// SAFE CHANNEL READ
// =================================================
bool readChannelsSafe() {
  int test = ibus.readChannel(2); // CH3 throttle
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(0);
  ch2 = ibus.readChannel(1);
  ch3 = test;
  ch5 = ibus.readChannel(4);
  ch7 = ibus.readChannel(6);
  ch8 = ibus.readChannel(7);

  return true;
}

// =================================================
// FAILSAFE CHECK
// =================================================
bool isFailsafeActive() {
  if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
    failsafeActive = true;
  }
  return failsafeActive;
}

// =================================================
// APPLY FAILSAFE (HARD STOP)
// =================================================
void applyFailsafe() {
  stopAllMotors();
  delay(200);               // allow current decay
  moveServosToSafe();

  digitalWrite(LED_CH5, LOW);
  digitalWrite(LED_CH7, LOW);
  digitalWrite(LED_CH8, LOW);
}

// =================================================
// SAFE DIRECTION CONTROL
// =================================================
void handleDirection() {
  static bool lastDirection = true;
  bool forward = (ch2 >= 1400);

  if (forward != lastDirection) {
    stopAllMotors();
    delay(DIR_CHANGE_DELAY);
    lastDirection = forward;
  }

  for (int i = 0; i < 6; i++) {
    digitalWrite(motorDIR[i], forward);
  }
}

// =================================================
// SAFE TRAPEZOIDAL SPEED CONTROL
// =================================================
void handleThrottleTrapezoidal() {

  targetSpeed = map(ch3, 1000, 2000, 0, MAX_PWM);
  targetSpeed = constrain(targetSpeed, 0, MAX_PWM);

  if (currentSpeed < targetSpeed) {
    currentSpeed += ACCEL_STEP;
    if (currentSpeed > targetSpeed) currentSpeed = targetSpeed;
  } 
  else if (currentSpeed > targetSpeed) {
    currentSpeed -= ACCEL_STEP;
    if (currentSpeed < targetSpeed) currentSpeed = targetSpeed;
  }

  setAllMotors(currentSpeed);
}

// =================================================
// SET ALL MOTORS SPEED
// =================================================
void setAllMotors(int pwmVal) {
  for (int i = 0; i < 6; i++) {
    analogWrite(motorPWM[i], pwmVal);
  }
}

// =================================================
// STOP ALL MOTORS
// =================================================
void stopAllMotors() {
  currentSpeed = 0;
  setAllMotors(0);
}

// =================================================
// SERVO CONTROL
// =================================================
void handleServos() {
  controlServo(0, ch5);
  controlServo(1, ch7);
  controlServo(2, ch8);
}

// =================================================
// INDIVIDUAL SERVO LOGIC
// =================================================
void controlServo(uint8_t servoNum, int channelValue) {
  if (channelValue > 1500) {
    pca9685.setPWM(servoNum, 0, SERVO_MAX);
  } else {
    pca9685.setPWM(servoNum, 0, SERVO_MIN);
  }
}

// =================================================
// MOVE SERVOS TO SAFE
// =================================================
void moveServosToSafe() {
  pca9685.setPWM(0, 0, SERVO_MIN);
  pca9685.setPWM(1, 0, SERVO_MIN);
  pca9685.setPWM(2, 0, SERVO_MIN);
}

// =================================================
// LED STATUS HANDLER
// =================================================
void handleLEDs() {
  digitalWrite(LED_CH5, (ch5 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH7, (ch7 > 1500) ? HIGH : LOW);
  digitalWrite(LED_CH8, (ch8 > 1500) ? HIGH : LOW);
}
