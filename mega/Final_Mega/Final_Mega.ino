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
#define PUMP_PIN         52

#define SOIL_END_PIN     10
#define SOIL_MIDDLE_PIN  9
#define SOIL_BASE_PIN    8

// =====================================================
// ================= ESTOP PIN =========================
// =====================================================

#define ESTOP_PIN        48   // NO E-Stop button — connects pin to GND when pressed
                              // INPUT_PULLUP: HIGH = normal, LOW = E-Stop pressed

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
const unsigned long rotateBackTime   = rotateTime * 2;
const unsigned long pumpTime         = 60000;

// =====================================================
// ================= SOIL ARM TUNING ===================
// =====================================================

const int           MAX_REPEATS  = 1;
const unsigned long STEP_DELAY   = 60;

// =====================================================
// ================= SPRAY STATE MACHINE ===============
// =====================================================

enum SprayState {
  SPRAY_IDLE,
  SPRAY_ROTATING_OUT,
  SPRAY_PUMPING,
  SPRAY_ROTATING_BACK,
  SPRAY_ABORTING,       // <-- NEW: non-blocking return to home
  SPRAY_DONE
};

SprayState sprayState = SPRAY_IDLE;

// =====================================================
// ================= SOIL ARM STATE MACHINE ============
// =====================================================

enum SoilState {
  SOIL_IDLE,
  SOIL_RUNNING,
  SOIL_HOMING,          // <-- NEW: returning to home position
  SOIL_DONE
};

SoilState soilState = SOIL_IDLE;

// =====================================================
// ================= CH7 STATE MACHINE =================
// =====================================================

enum AirState {
  AIR_IDLE,
  AIR_RUNNING,
  AIR_DONE
};

AirState airState = AIR_IDLE;

// =====================================================
// ================= USB SERIAL (Pi status frame) ======
// =====================================================

#define SYNC1              0xAA
#define SYNC2              0x55
#define STATUS_INTERVAL_MS 100   // 10 Hz — matches mega.py read rate
#define MOV_STOP  0
#define MOV_FWD   1
#define MOV_BACK  2
#define MOV_LEFT  3
#define MOV_RIGHT 4

struct __attribute__((packed)) StatusPacket {
  bool    tool_water;
  bool    tool_air;
  bool    tool_soil;
  bool    ibus_pulse;
  uint8_t movement;     // MOV_* code above
  bool    kill_switch;  // true when CH8 kill or E-stop is active
};
StatusPacket status;
unsigned long _lastStatus = 0;

bool ibus_pulse     = false;
bool failsafeActive = false;
bool killActive     = false;

// =====================================================
// ================= GLOBAL VARIABLES ==================
// =====================================================

int ch1, ch2, ch3, ch5, ch6, ch7, ch8;

float currentSpeedL = 0;
float currentSpeedR = 0;

unsigned long lastSignalTime  = 0;
unsigned long servoStartTime  = 0;
unsigned long pumpStartTime   = 0;

bool ch6WasOn = false;
bool ch7WasOn = false;
bool ch5WasOn = false;

int  pose_base          = 0;
int  pose_middle        = 0;
int  pose_end           = 0;
int  soilStep           = 0;
int  repeatCount        = 0;
unsigned long lastSoilUpdate = 0;

// =====================================================
// ================= SERIAL HELPERS ====================
// =====================================================

uint8_t computeMovement() {
  if (failsafeActive) return MOV_STOP;
  float avgAbs = (fabs(currentSpeedL) + fabs(currentSpeedR)) / 2.0f;
  if (avgAbs < 5.0f) return MOV_STOP;
  int turnRaw = ch1 - CENTER_PWM;
  if (abs(turnRaw) > DEADZONE * 2) return (turnRaw > 0) ? MOV_RIGHT : MOV_LEFT;
  return (ch2 >= 1400) ? MOV_FWD : MOV_BACK;
}

void updateStatusPacket() {
  status.tool_water  = ch6WasOn;
  status.tool_air    = ch7WasOn;
  status.tool_soil   = ch5WasOn;
  status.ibus_pulse  = ibus_pulse;
  status.movement    = computeMovement();
  status.kill_switch = killActive;
}

void sendStatusFrame() {
  // 8-byte framed packet: [0xAA, 0x55, 6 payload bytes]
  // Pi scans for 0xAA 0x55 header then reads 6 bytes — tolerates startup text.
  Serial.write((uint8_t)SYNC1);
  Serial.write((uint8_t)SYNC2);
  Serial.write((uint8_t*)&status, sizeof(status));
}

void maybeSendStatus() {
  if (millis() - _lastStatus >= STATUS_INTERVAL_MS) {
    _lastStatus = millis();
    sendStatusFrame();
  }
}

// =====================================================
// ================= SETUP =============================
// =====================================================

void setup() {

  Serial.begin(115200);
  ibus.begin(Serial1);

  pinMode(ESTOP_PIN, INPUT_PULLUP);

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

  // -------- HARDWARE E-STOP (always first) --------
  if (digitalRead(ESTOP_PIN) == LOW) {
    applyKillSwitch();
    updateStatusPacket();
    maybeSendStatus();
    delay(LOOP_DELAY);
    return;
  }

  if (readChannelsSafe()) {

    lastSignalTime  = millis();
    ibus_pulse      = true;
    failsafeActive  = false;

    // -------- Channel debug dump every 500 ms (remove after channel mapping confirmed) ----
    static unsigned long _lastChanDebug = 0;
    if (millis() - _lastChanDebug >= 500) {
      _lastChanDebug = millis();
      Serial.print("CH1:"); Serial.print(ch1);
      Serial.print(" CH2:"); Serial.print(ch2);
      Serial.print(" CH3:"); Serial.print(ch3);
      Serial.print(" CH5:"); Serial.print(ch5);
      Serial.print(" CH6:"); Serial.print(ch6);
      Serial.print(" CH7:"); Serial.print(ch7);
      Serial.print(" CH8:"); Serial.println(ch8);
    }

    // -------- CH8: RC Kill Switch --------
    if (ch8 >= 1500) {
      applyKillSwitch();   // killActive set inside
    }
    else {
      killActive = false;  // CH8 off and E-stop not pressed → no kill

      // =====================================================
      // CH6 — Water Task
      // =====================================================
      if (ch6 >= 1500) {

        stopAllMotors();

        // Fresh start: only trigger if not already running
        if (!ch6WasOn) {
          ch6WasOn = true;
          // If arm is mid-abort or done, reset before restarting
          if (sprayState != SPRAY_IDLE) {
            forceSprayHome();
          }
          sprayState = SPRAY_IDLE;
          Serial.println("Water task started");
        }

        handleSpraySequence();

      } else {

        // CH6 just turned OFF
        if (ch6WasOn) {
          ch6WasOn = false;
          beginSprayAbort();     // Non-blocking abort back to home
          Serial.println("Water task OFF — returning to home");
        }

        // Keep running abort sequence even while CH6 is off
        if (sprayState == SPRAY_ABORTING) {
          handleSpraySequence();
        }

        // =====================================================
        // CH7 — Air Task
        // =====================================================
        if (ch7 >= 1500) {

          if (!ch7WasOn) {
            ch7WasOn = true;
            airState = AIR_RUNNING;
            Serial.println("Air Sample started");
          }

          handleAirTask();

        } else {

          // CH7 just turned OFF
          if (ch7WasOn) {
            ch7WasOn = false;
            abortAirTask();       // Reset air task to home/idle
            Serial.println("Air task OFF — home position");
          }
        }

        // =====================================================
        // CH5 — Soil Task
        // =====================================================
        if (ch5 >= 1500) {

          if (!ch5WasOn) {
            ch5WasOn    = true;
            soilState   = SOIL_RUNNING;
            soilStep    = 1;
            repeatCount = 0;
            pose_base = pose_middle = pose_end = 0;
            resetSoilArm();
            Serial.println("Soil task started");
          }

          handleSoilArm();

        } else {

          // CH5 just turned OFF
          if (ch5WasOn) {
            ch5WasOn  = false;
            soilState = SOIL_HOMING;   // Non-blocking home return
            Serial.println("Soil task OFF — returning to home");
          }

          // Keep running homing even while CH5 is off
          if (soilState == SOIL_HOMING) {
            handleSoilHoming();
          } else {
            handleDrive();             // Drive only when no task is homing
          }
        }
      }
    }
  }
  else {
    ibus_pulse = false;
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      applyFailsafe();
    }
  }

  updateStatusPacket();
  maybeSendStatus();

  delay(LOOP_DELAY);
}

// =====================================================
// ================= DRIVE CONTROL =====================
// =====================================================
void handleDrive() {
  // 1. INPUT PROCESSING
  // Move (Ch2) and Turn (Ch1) are centered at 1500 (Bidirectional)
  int moveRaw     = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int turnRaw     = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);
  
  // Throttle (Ch3) is a master scalar from 0 to 1.0 (Unidirectional)
  // Constrain ensures we don't get negative values if the stick is slightly below 1000
  float throttleFactor = constrain(ch3 - 1000, 0, 1000) / 1000.0; 

  float moveFactor     = moveRaw / 500.0;  // Range: -1.0 to 1.0
  float turnFactor     = turnRaw / 500.0;  // Range: -1.0 to 1.0

  // 2. TARGET SPEED CALCULATION
  // Base movement scaled by master throttle
  float X = (moveFactor * ABSOLUTE_MAX_PWM) * throttleFactor;

  // Turning logic with speed-based reduction
  float speedRatio              = abs(X) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = constrain(1.0 - (speedRatio * TURN_REDUCTION), 0.2, 1.0);
  
  // Y is also scaled by the master throttle
  float Y = (turnFactor * TURN_MAX * turnReductionMultiplier) * throttleFactor;

  float targetL = constrain(X + Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  float targetR = constrain(X - Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  // 3. SAFE DIRECTION CONTROL
  static bool lastDirL = true;
  static bool lastDirR = true;
  bool currentDirL = (targetL >= 0);
  bool currentDirR = (targetR >= 0);

  // If the intended direction flips, force a stop and a delay to protect the gearbox/H-bridge
  if (currentDirL != lastDirL || currentDirR != lastDirR) {
    stopAllMotors(); // Resets currentSpeedL/R to 0
    delay(150);      // Use a fixed delay (or define DIR_CHANGE_DELAY)
    lastDirL = currentDirL;
    lastDirR = currentDirR;
  }

  // 4. DYNAMIC TRAPEZOIDAL RAMPING
  float diffL = targetL - currentSpeedL;
  float diffR = targetR - currentSpeedR;

  float dynamicStepL = constrain(BASE_ACCEL_STEP + abs(diffL) * SLOP_FACTOR, BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  float dynamicStepR = constrain(BASE_ACCEL_STEP + abs(diffR) * SLOP_FACTOR, BASE_ACCEL_STEP, MAX_ACCEL_STEP);

  currentSpeedL += (diffL > 0) ? min(dynamicStepL, diffL) : -min(dynamicStepL, -diffL);
  currentSpeedR += (diffR > 0) ? min(dynamicStepR, diffR) : -min(dynamicStepR, -diffR);

  // 5. MOTOR OUTPUT
  // Send direction to DIR pins and magnitude to PWM pins
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
      if (millis() - pumpStartTime >= pumpTime) {
        digitalWrite(PUMP_PIN, LOW);
        sprayServo.write(SERVO_REVERSE);
        servoStartTime = millis();
        sprayState     = SPRAY_ROTATING_BACK;
      }
      break;

    case SPRAY_ROTATING_BACK:
      if (millis() - servoStartTime >= rotateBackTime) {
        sprayServo.write(SERVO_STOP);
        sprayState = SPRAY_DONE;
        Serial.println("Water task complete");
      }
      break;

    // Non-blocking abort: rotate back to home then go IDLE
    case SPRAY_ABORTING:
      if (millis() - servoStartTime >= rotateBackTime) {
        sprayServo.write(SERVO_STOP);
        sprayState = SPRAY_IDLE;     // Ready for next trigger
        Serial.println("Spray arm home — ready");
      }
      break;

    case SPRAY_DONE:
      sprayServo.write(SERVO_STOP);
      break;
  }
}

// Start a non-blocking abort (rotate back to home)
void beginSprayAbort() {
  digitalWrite(PUMP_PIN, LOW);
  sprayServo.write(SERVO_REVERSE);
  servoStartTime = millis();
  sprayState     = SPRAY_ABORTING;
}

// Instant snap to home (used by kill switch only)
void forceSprayHome() {
  digitalWrite(PUMP_PIN, LOW);
  sprayServo.write(SERVO_STOP);
  sprayState = SPRAY_IDLE;
}

// =====================================================
// ================= AIR TASK (CH7) ====================
// =====================================================

void handleAirTask() {
  // Add your air sampling hardware control here
  // e.g. fan, valve, sensor trigger, etc.
  // airState = AIR_DONE when sequence complete
}

void abortAirTask() {
  // Return any air task hardware to safe/home state here
  // e.g. turn off fan, close valve
  airState = AIR_IDLE;
}

// =====================================================
// ================= SOIL ARM ==========================
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
      } else {
        repeatCount++;
        if (repeatCount < MAX_REPEATS) {
          pose_base = pose_middle = pose_end = 0;
          soilStep = 1;
        } else {
          soilState = SOIL_DONE;
          Serial.println("Soil task complete");
        }
      }
      break;
  }
}

// Non-blocking smooth return to home (runs each loop tick)
void handleSoilHoming() {

  if (soilState != SOIL_HOMING) return;
  if (millis() - lastSoilUpdate < STEP_DELAY) return;
  lastSoilUpdate = millis();

  bool allHome = true;

  if (pose_end > 0)    { servo_end.write(--pose_end);       allHome = false; }
  if (pose_middle > 0) { servo_middle.write(--pose_middle); allHome = false; }
  if (pose_base > 0)   { servo_base.write(--pose_base);     allHome = false; }

  if (allHome) {
    soilState = SOIL_IDLE;     // Ready for next trigger
    Serial.println("Soil arm home — ready");
  }
}

void resetSoilArm() {
  pose_base = pose_middle = pose_end = 0;
  servo_end.write(0);
  servo_middle.write(0);
  servo_base.write(0);
}

// =====================================================
// ================= RECEIVER ==========================
// =====================================================

bool readChannelsSafe() {

  // Note: FS-iA10B sends failsafe channel values at full iBUS rate after TX loss.
  // RC:LOST cannot be detected via iBUS on this receiver.
  // Safety is handled via failsafe: program CH8 to kill position on receiver,
  // so kill_switch fires automatically when TX turns off.

  int test = ibus.readChannel(2);
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
// ================= SAFETY ============================
// =====================================================

void applyKillSwitch() {
  stopAllMotors();
  forceSprayHome();
  abortAirTask();
  resetSoilArm();
  soilState  = SOIL_IDLE;
  airState   = AIR_IDLE;
  ch5WasOn   = false;
  ch6WasOn   = false;
  ch7WasOn   = false;
  killActive = true;
}

void applyFailsafe() {
  stopAllMotors();
  forceSprayHome();
  abortAirTask();
  resetSoilArm();
  soilState      = SOIL_IDLE;
  airState       = AIR_IDLE;
  ch5WasOn       = false;
  ch6WasOn       = false;
  ch7WasOn       = false;
  failsafeActive = true;
  // Pre-fill status so Pi sees RC-loss state immediately on next frame
  // kill_switch stays as-is — RC loss is NOT a kill switch event
  status.ibus_pulse  = false;
  status.movement    = MOV_STOP;
  status.tool_water  = false;
  status.tool_air    = false;
  status.tool_soil   = false;
}

void stopAllMotors() {
  currentSpeedL = 0;
  currentSpeedR = 0;
  for (int i = 0; i < 6; i++)
    analogWrite(motorPWM[i], 0);
}
