// =============================================================================
// klm.ino — HERC-26 Unified Mega Firmware
// Team MOVIS | Human Exploration Rover Challenge
//
// INTEGRATES:
//   1. Drive          — 6-motor differential drive (envelope + sloppy accel)
//   2. Tool servos    — PLACEHOLDER: servo driver removed, to be replaced by teammate
//   3. Tool actuators — Soil H-bridge (pins 40/41), Water H-bridge (pins 42/43)
//   4. Pump           — Peristaltic pump (pin 44), auto-off after 5 s
//   5. Arm            — 3-servo absolute-time trajectory player (driver TBD)
//   6. Pi I2C Slave   — 6-byte status report to Raspberry Pi at address 0x08
//   7. Status LEDs    — signal + per-tool state indicators
//   8. Failsafe       — hard stop on RC signal loss > 500 ms
//   9. Kill switch    — CH6 operator hard stop
//  10. Test Mode      — sequential individual motor spin (CH5 > 1700)
//  11. Debug Serial   — JSON status line at 20 Hz for klm_monitor.py
//
// RC CHANNEL MAP (FlySky iBUS, 1000-2000 us):
//   CH1 (idx 0) — Right stick horizontal → Turn left/right
//   CH2 (idx 1) — Left  stick vertical   → Forward/back base speed
//   CH3 (idx 2) — Right stick vertical   → Speed envelope scale + iBUS pulse to Pi
//   CH5 (idx 4) — Switch A → Air tool (1500-1700) | Test mode (>1700)
//   CH6 (idx 5) — Switch D → Kill switch (>1500 = all stop)
//   CH7 (idx 6) — Switch B → Water tool (>1500)
//   CH8 (idx 7) — Switch C → Soil tool (1500-1700) | Arm trigger rising edge (>1700)
//
// PI I2C INTERFACE (address 0x08):
//   Pi sends Wire.requestFrom(0x08, 6) — Mega responds with 6 bytes:
//     byte 0: toolAir        (0 or 1)
//     byte 1: toolWater      (0 or 1)
//     byte 2: toolSoil       (0 or 1)
//     byte 3: movementState  (0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
//     byte 4: ch3 low byte   (raw iBUS pulse 1000-2000, little-endian)
//     byte 5: ch3 high byte
//   Pi can also SEND a command byte (onReceive):
//     0x01 = start arm trajectory
//     0x02 = stop arm trajectory
//     0x03 = emergency stop (same as kill)
//
// ARM TRAJECTORY (absolute-time, from arm_poses_sweep_soil.csv):
//   Converted from delta-time CSV to absolute elapsed seconds.
//   Start pose {0,0,0} added at t=0. 11 keyframes, ~24 s total.
//   θ1 base servo is physically reversed — firmware writes (180 - angle).
//   Triggered by rising edge of CH8 > 1700 or Pi command 0x01.
//
// COMPILE:  arduino-cli compile --fqbn arduino:avr:mega mega/klm
// UPLOAD:   arduino-cli upload  --fqbn arduino:avr:mega --port /dev/ttyACM0 mega/klm
// MONITOR:  python mega/klm_monitor.py  (115200 baud, JSON lines)
// =============================================================================

#include <IBusBM.h>
#include <Wire.h>

// =============================================================================
// SECTION A — HARDWARE PIN DEFINITIONS
// =============================================================================

// --- 6 Motor PWM and Direction pins ---
// Even index = Right side, Odd index = Left side
int motorPWM[6] = {2, 3, 6, 7, 4, 5};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};

#define FRONT_R 0
#define FRONT_L 1
#define MID_R   2
#define MID_L   3
#define BACK_R  4
#define BACK_L  5

// --- Status LEDs ---
#define LED_SIGNAL  30    // HIGH = valid RC frames being received
#define LED_AIR     31    // Mirrors air tool state
#define LED_WATER   32    // Mirrors water tool state
#define LED_SOIL    33    // Mirrors soil tool state

// --- Pi I2C slave address ---
#define I2C_SLAVE_ADDR  0x08

// --- RC channel indices (0-based iBUS) ---
#define CH_TURN_IDX    0    // CH1: turn L/R
#define CH_FWD_IDX     1    // CH2: forward/back
#define CH_SCALE_IDX   2    // CH3: speed envelope / iBUS pulse to Pi
#define CH_AIR_IDX     4    // CH5: air tool + test mode
#define CH_KILL_IDX    5    // CH6: kill switch
#define CH_WATER_IDX   6    // CH7: water tool
#define CH_SOIL_IDX    7    // CH8: soil tool + arm trigger

// --- Tool H-bridge actuator pins ---
#define SOIL_FWD   40    // Soil linear actuator — forward (extend)
#define SOIL_REV   41    // Soil linear actuator — reverse (retract)
#define WATER_FWD  42    // Water linear actuator — forward (extend)
#define WATER_REV  43    // Water linear actuator — reverse (retract)

// --- Peristaltic pump pin ---
#define PUMP_PIN   44    // PWM-capable digital pin — HIGH = pump ON

// =============================================================================
// SECTION B — CONSTANTS
// =============================================================================

// --- RC signal ---
#define CENTER_PWM        1500
#define DEADZONE          40
#define FAILSAFE_TIMEOUT  500   // ms without valid iBUS frame

// --- Channel thresholds ---
#define TOOL_THRESHOLD      1500   // switch ON above this
#define TEST_MODE_THRESHOLD 1700   // test mode / arm trigger above this

// --- Drive tuning ---
#define ABSOLUTE_MAX_PWM   255
#define TURN_MAX           180
#define TURN_REDUCTION     1.0
#define BASE_ACCEL_STEP    12
#define SLOP_FACTOR        0.35
#define MAX_ACCEL_STEP     25

// --- Test mode motor speed ---
#define TEST_SPEED         150

// --- Loop timing ---
#define LOOP_DELAY_MS      10    // ms per main loop iteration (~100 Hz)

// --- Pump ---
#define PUMP_TIME_MS  5000UL   // auto-off after 5 seconds

// =============================================================================
// SECTION C — OBJECTS
// =============================================================================

IBusBM ibus;

// =============================================================================
// SECTION D — GLOBAL STATE
// =============================================================================

// --- RC channel values (raw us, 1000-2000) ---
int ch1, ch2, ch3, ch5, ch6, ch7, ch8;

// --- Drive state ---
float currentSpeedL = 0;
float currentSpeedR = 0;

// --- Signal watchdog ---
unsigned long lastSignalTime = 0;

// --- Test mode ---
unsigned long testStartTime = 0;

// --- Safety flags ---
bool killed        = false;
bool failsafeActive = false;

// --- Tool states ---
bool toolAir   = false;
bool toolWater = false;
bool toolSoil  = false;

// --- Movement state reported to Pi ---
// 0=STOP, 1=FWD, 2=BACK, 3=LEFT, 4=RIGHT
uint8_t movementState = 0;

// --- I2C response buffer ---
volatile uint8_t i2cBuf[6] = {0};

// --- Actuator running flags ---
// Prevent repeated re-triggering on every loop tick
bool soilRunning  = false;
bool waterRunning = false;

// --- Pump state ---
bool          pumpRunning = false;
unsigned long pumpStartMs = 0;

// --- Arm trigger edge detection ---
bool armTriggerPrev = false;

// --- Arm current interpolated angles (for debug output) ---
float armCurrentTh1 = 0;
float armCurrentTh2 = 0;
float armCurrentTh3 = 0;

// =============================================================================
// SECTION E — ARM TRAJECTORY
// =============================================================================
//
// Source: ARM_sim/arm/arm_poses_sweep_soil.csv (delta-time format)
// Converted to absolute elapsed time. Home pose {0,0,0} added at t=0.
// Total trajectory: ~23.9 seconds, 11 keyframes.
//
// θ1 base servo is physically reversed on the hardware — setArmServos()
// writes (180 - th1) to CH_ARM_1. The angle values here are the LOGICAL
// angles matching the sim; hardware inversion is handled in firmware.
//
// To replace with a new trajectory:
//   1. Design in ARM_sim/sim_create.py, export CSV
//   2. Verify in ARM_sim/sim_view.py
//   3. Convert delta-time to absolute-time (sum rows cumulatively)
//   4. Replace the array below and update ARM_NUM_FRAMES

struct ArmKeyframe {
  float time_s;
  float th1_deg;
  float th2_deg;
  float th3_deg;
};

ArmKeyframe armTraj[] = {
  //  time_s     th1        th2        th3
  {  0.000000,   0.0000,   0.0000,   0.0000 },  // home
  {  3.020833, 180.0000, 159.6875, 150.6250 },
  {  6.076389,  31.8750,  83.4375,  30.3125 },
  {  9.131944,   0.0000,   0.0000,  20.9375 },
  { 12.187500,   0.0000,  49.3750, 104.6875 },
  { 14.236111,   0.0000, 100.0000,  40.9375 },
  { 16.284722,  55.3125, 100.0000,   0.0000 },
  { 18.333333, 109.6875,  61.8750,   0.0000 },
  { 20.381944, 115.0000, 180.0000,   0.0000 },
  { 21.527778, 115.0000, 180.0000,  87.1875 },
  { 23.854167, 180.0000, 180.0000, 123.4375 },
};
const int ARM_NUM_FRAMES = sizeof(armTraj) / sizeof(ArmKeyframe);

bool          armRunning = false;
unsigned long armStartMs = 0;

// =============================================================================
// SECTION F — SETUP
// =============================================================================

void setup() {
  Serial.begin(115200);
  ibus.begin(Serial1);

  // Motor pins
  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  // LED pins
  pinMode(LED_SIGNAL, OUTPUT);
  pinMode(LED_AIR,    OUTPUT);
  pinMode(LED_WATER,  OUTPUT);
  pinMode(LED_SOIL,   OUTPUT);

  // Actuator and pump pins
  pinMode(SOIL_FWD,  OUTPUT);
  pinMode(SOIL_REV,  OUTPUT);
  pinMode(WATER_FWD, OUTPUT);
  pinMode(WATER_REV, OUTPUT);
  pinMode(PUMP_PIN,  OUTPUT);

  // Safe initial state — all actuators and pump off
  digitalWrite(SOIL_FWD,  LOW);
  digitalWrite(SOIL_REV,  LOW);
  digitalWrite(WATER_FWD, LOW);
  digitalWrite(WATER_REV, LOW);
  digitalWrite(PUMP_PIN,  LOW);

  // Hardware I2C (pins 20/21) — Mega as I2C SLAVE to Raspberry Pi
  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(onI2CRequest);
  Wire.onReceive(onI2CReceive);

  stopAllMotors();

  Serial.println(F("HERC-26 KLM Ready"));
}

// =============================================================================
// SECTION G — MAIN LOOP
// =============================================================================

void loop() {

  if (readChannelsSafe()) {
    lastSignalTime  = millis();
    failsafeActive  = false;
    digitalWrite(LED_SIGNAL, HIGH);

    // Kill switch — highest priority below RC failsafe
    killed = (ch6 > TOOL_THRESHOLD);

    if (killed) {
      applyKill();

    } else {
      // Drive mode
      if (ch5 > TEST_MODE_THRESHOLD) {
        runTestMode();
      } else {
        testStartTime = 0;
        handleDrive();
      }

      // Tools (servo + actuator + pump)
      handleTools();
      handleActuators();
      handlePump();

      // Arm
      handleArm();
    }

    handleLEDs();
    updateI2CBuffer();

  } else {
    // No valid iBUS frame
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      failsafeActive = true;
      digitalWrite(LED_SIGNAL, LOW);
      applyFailsafe();
    }
  }

  debugPrint();
  delay(LOOP_DELAY_MS);
}

// =============================================================================
// SECTION H — RC INPUT
// =============================================================================

bool readChannelsSafe() {
  // Probe CH3 first. If out of valid RC range, receiver is not sending
  // valid frames — skip this cycle.
  int test = ibus.readChannel(CH_SCALE_IDX);
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(CH_TURN_IDX);
  ch2 = ibus.readChannel(CH_FWD_IDX);
  ch3 = test;
  ch5 = ibus.readChannel(CH_AIR_IDX);
  ch6 = ibus.readChannel(CH_KILL_IDX);
  ch7 = ibus.readChannel(CH_WATER_IDX);
  ch8 = ibus.readChannel(CH_SOIL_IDX);

  return true;
}

// =============================================================================
// SECTION I — DRIVE (envelope + sloppy adaptive acceleration)
// =============================================================================

void handleDrive() {

  // I1. Apply dead-band and normalize to [-1, +1]
  int moveRaw  = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int scaleRaw = (abs(ch3 - CENTER_PWM) < DEADZONE) ? 0 : (ch3 - CENTER_PWM);
  int turnRaw  = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  float moveFactor  = moveRaw  / 500.0;
  float scaleFactor = scaleRaw / 500.0;
  float turnFactor  = turnRaw  / 500.0;

  // I2. Speed envelope
  float X        = moveFactor * ABSOLUTE_MAX_PWM;
  float limitedX = X * scaleFactor;

  // I3. Speed-proportional turn reduction (less turn authority at high speed)
  float speedRatio              = abs(limitedX) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = 1.0 - (speedRatio * TURN_REDUCTION);
  turnReductionMultiplier       = constrain(turnReductionMultiplier, 0.2, 1.0);
  float Y = turnFactor * TURN_MAX * turnReductionMultiplier;

  // I4. Differential mixing
  float targetL = constrain(limitedX + Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  float targetR = constrain(limitedX - Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  // I5. Sloppy adaptive acceleration ramp
  float diffL = targetL - currentSpeedL;
  float diffR = targetR - currentSpeedR;

  float stepL = constrain(BASE_ACCEL_STEP + abs(diffL) * SLOP_FACTOR,
                           BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  float stepR = constrain(BASE_ACCEL_STEP + abs(diffR) * SLOP_FACTOR,
                           BASE_ACCEL_STEP, MAX_ACCEL_STEP);

  currentSpeedL += (diffL > 0) ?  min(stepL,  diffL) : -min(stepL, -diffL);
  currentSpeedR += (diffR > 0) ?  min(stepR,  diffR) : -min(stepR, -diffR);

  // I6. Apply to motors
  for (int i = 0; i < 6; i += 2) {   // right side: even indices
    digitalWrite(motorDIR[i], (currentSpeedR >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedR));
  }
  for (int i = 1; i < 6; i += 2) {   // left side: odd indices
    digitalWrite(motorDIR[i], (currentSpeedL >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedL));
  }

  // I7. Compute movement state for Pi
  movementState = computeMovementState(limitedX, Y);
}

// STOP=0, FWD=1, BACK=2, LEFT=3, RIGHT=4
uint8_t computeMovementState(float fwd, float turn) {
  if (abs(fwd) < 10 && abs(turn) < 10) return 0;
  if (abs(turn) > abs(fwd) * 0.8) return (turn > 0) ? 4 : 3;
  return (fwd >= 0) ? 1 : 2;
}

// =============================================================================
// SECTION J — TOOL SERVOS
// =============================================================================
//
// Air   — CH5 1500-1700 only (>1700 is test mode, air is OFF in test mode)
// Water — CH7 > 1500
// Soil  — CH8 1500-1700 only (>1700 is arm trigger, soil OFF while arm triggers)

void handleTools() {
  toolAir   = (ch5 > TOOL_THRESHOLD) && (ch5 <= TEST_MODE_THRESHOLD);
  toolWater = (ch7 > TOOL_THRESHOLD);
  toolSoil  = (ch8 > TOOL_THRESHOLD) && (ch8 <= TEST_MODE_THRESHOLD);

  // PLACEHOLDER: servo output removed — teammate will add their servo driver here
}

// =============================================================================
// SECTION J2 — TOOL ACTUATORS (H-bridge)
// =============================================================================
//
// Soil:
//   ON edge  → SOIL_FWD HIGH (extend)
//   OFF edge → SOIL_REV HIGH (retract — holds until tool ON or kill/failsafe)
//
// Water:
//   ON edge  → WATER_FWD HIGH + start pump
//   OFF edge → WATER_REV HIGH + stop pump

void handleActuators() {

  // --- Soil linear actuator ---
  if (toolSoil) {
    if (!soilRunning) {
      soilRunning = true;
      digitalWrite(SOIL_FWD, HIGH);
      digitalWrite(SOIL_REV, LOW);
    }
    // While soilRunning: pins already set, nothing more to do each tick
  } else {
    if (soilRunning) {
      soilRunning = false;
      // Switch to retract direction — stays retracted until tool ON again
      digitalWrite(SOIL_FWD, LOW);
      digitalWrite(SOIL_REV, HIGH);
    }
    // While !soilRunning and !toolSoil: retract direction held by pin state
  }

  // --- Water linear actuator ---
  if (toolWater) {
    if (!waterRunning) {
      waterRunning = true;
      digitalWrite(WATER_FWD, HIGH);
      digitalWrite(WATER_REV, LOW);
      startPump();
    }
  } else {
    if (waterRunning) {
      waterRunning = false;
      stopPump();
      // Switch to retract
      digitalWrite(WATER_FWD, LOW);
      digitalWrite(WATER_REV, HIGH);
    }
  }
}

// =============================================================================
// SECTION J3 — PERISTALTIC PUMP (auto-off after PUMP_TIME_MS)
// =============================================================================

void startPump() {
  pumpStartMs = millis();
  pumpRunning = true;
  digitalWrite(PUMP_PIN, HIGH);
}

void handlePump() {
  if (!pumpRunning) return;
  if (millis() - pumpStartMs >= PUMP_TIME_MS) {
    stopPump();
  }
}

void stopPump() {
  pumpRunning = false;
  digitalWrite(PUMP_PIN, LOW);
}

// =============================================================================
// SECTION K — ARM TRAJECTORY PLAYER
// =============================================================================
//
// Trigger: rising edge of CH8 > 1700 OR Pi I2C command 0x01.
// θ1 base servo is physically reversed — written as (180 - angle) to PCA9685.
// Interpolation: find bracketing keyframes by elapsed time, lerp between them.
// Holds final pose when trajectory ends (armRunning = false).

void handleArm() {

  // Rising-edge trigger on CH8 > TEST_MODE_THRESHOLD
  bool armTriggerNow = (ch8 > TEST_MODE_THRESHOLD);
  if (armTriggerNow && !armTriggerPrev) {
    startArm();
  }
  armTriggerPrev = armTriggerNow;

  if (!armRunning) {
    // Show home pose angles in debug while idle
    armCurrentTh1 = armTraj[0].th1_deg;
    armCurrentTh2 = armTraj[0].th2_deg;
    armCurrentTh3 = armTraj[0].th3_deg;
    return;
  }

  float elapsedS = (millis() - armStartMs) / 1000.0;

  // Clamp to end of trajectory
  if (elapsedS >= armTraj[ARM_NUM_FRAMES - 1].time_s) {
    armCurrentTh1 = armTraj[ARM_NUM_FRAMES - 1].th1_deg;
    armCurrentTh2 = armTraj[ARM_NUM_FRAMES - 1].th2_deg;
    armCurrentTh3 = armTraj[ARM_NUM_FRAMES - 1].th3_deg;
      armRunning = false;
    return;
  }

  // Find the two keyframes bracketing the current elapsed time
  int k = 0;
  for (int i = 0; i < ARM_NUM_FRAMES - 1; i++) {
    if (elapsedS >= armTraj[i].time_s && elapsedS < armTraj[i + 1].time_s) {
      k = i;
      break;
    }
  }

  float dt     = armTraj[k + 1].time_s - armTraj[k].time_s;
  float t_frac = (dt > 0) ? (elapsedS - armTraj[k].time_s) / dt : 1.0;

  // Linear interpolation
  armCurrentTh1 = armTraj[k].th1_deg + t_frac * (armTraj[k + 1].th1_deg - armTraj[k].th1_deg);
  armCurrentTh2 = armTraj[k].th2_deg + t_frac * (armTraj[k + 1].th2_deg - armTraj[k].th2_deg);
  armCurrentTh3 = armTraj[k].th3_deg + t_frac * (armTraj[k + 1].th3_deg - armTraj[k].th3_deg);

  // PLACEHOLDER: servo output removed — teammate will add their servo driver here
}

void startArm() {
  armStartMs = millis();
  armRunning = true;
}

// =============================================================================
// SECTION L — TEST MODE
// =============================================================================
// Spins each of the 6 motors individually for 2 s with 2 s gaps.
// Sequence: FRONT_R → MID_R → BACK_R → FRONT_L → MID_L → BACK_L → repeat.
// Activated when CH5 > TEST_MODE_THRESHOLD. Drive is suspended while active.

void runTestMode() {
  if (testStartTime == 0) testStartTime = millis();
  unsigned long elapsed = millis() - testStartTime;

  stopAllMotors();  // default everything off each frame

  if      (elapsed <  2000) spinMotor(FRONT_R, TEST_SPEED);
  else if (elapsed <  4000) { /* 2 s gap */ }
  else if (elapsed <  6000) spinMotor(MID_R,   TEST_SPEED);
  else if (elapsed <  8000) { /* 2 s gap */ }
  else if (elapsed < 10000) spinMotor(BACK_R,  TEST_SPEED);
  else if (elapsed < 12000) spinMotor(FRONT_L, TEST_SPEED);
  else if (elapsed < 14000) { /* 2 s gap */ }
  else if (elapsed < 16000) spinMotor(MID_L,   TEST_SPEED);
  else if (elapsed < 18000) { /* 2 s gap */ }
  else if (elapsed < 20000) spinMotor(BACK_L,  TEST_SPEED);
  else if (elapsed >= 22000) testStartTime = millis();  // restart sequence
}

void spinMotor(int idx, int speed) {
  digitalWrite(motorDIR[idx], HIGH);   // forward direction
  analogWrite(motorPWM[idx],  speed);
}

// =============================================================================
// SECTION M — KILL SWITCH + FAILSAFE
// =============================================================================

void applyKill() {
  stopAllMotors();
  allActuatorsOff();
  stopPump();
  armRunning    = false;
  movementState = 0;
  toolAir = toolWater = toolSoil = false;
  soilRunning = waterRunning = false;
  updateI2CBuffer();
}

void applyFailsafe() {
  stopAllMotors();
  allActuatorsOff();
  stopPump();
  armRunning    = false;
  movementState = 0;
  toolAir = toolWater = toolSoil = false;
  soilRunning = waterRunning = false;
  updateI2CBuffer();
}

// =============================================================================
// SECTION N — UTILITIES
// =============================================================================

void stopAllMotors() {
  currentSpeedL = 0;
  currentSpeedR = 0;
  for (int i = 0; i < 6; i++) analogWrite(motorPWM[i], 0);
}

void allActuatorsOff() {
  // Set all H-bridge pins LOW — coast/brake, no direction
  digitalWrite(SOIL_FWD,  LOW);
  digitalWrite(SOIL_REV,  LOW);
  digitalWrite(WATER_FWD, LOW);
  digitalWrite(WATER_REV, LOW);
}

void handleLEDs() {
  digitalWrite(LED_AIR,   toolAir   ? HIGH : LOW);
  digitalWrite(LED_WATER, toolWater ? HIGH : LOW);
  digitalWrite(LED_SOIL,  toolSoil  ? HIGH : LOW);
}

// =============================================================================
// SECTION O — PI I2C SLAVE INTERFACE
// =============================================================================

void updateI2CBuffer() {
  noInterrupts();
  i2cBuf[0] = (uint8_t)toolAir;
  i2cBuf[1] = (uint8_t)toolWater;
  i2cBuf[2] = (uint8_t)toolSoil;
  i2cBuf[3] = movementState;
  i2cBuf[4] = (uint8_t)(ch3 & 0xFF);         // ch3 low byte
  i2cBuf[5] = (uint8_t)((ch3 >> 8) & 0xFF);  // ch3 high byte
  interrupts();
}

// Called when Pi does Wire.requestFrom(0x08, 6)
void onI2CRequest() {
  Wire.write((uint8_t *)i2cBuf, sizeof(i2cBuf));
}

// Called when Pi sends a command byte to Mega
void onI2CReceive(int bytes) {
  while (Wire.available()) {
    uint8_t cmd = Wire.read();
    if      (cmd == 0x01) startArm();              // start arm trajectory
    else if (cmd == 0x02) armRunning = false;      // stop arm
    else if (cmd == 0x03) applyKill();             // Pi-triggered e-stop
  }
}

// =============================================================================
// SECTION P — DEBUG SERIAL OUTPUT (for klm_monitor.py)
// =============================================================================
//
// Outputs a JSON line at ~20 Hz over Serial (115200 baud).
// klm_monitor.py reads these lines to display live rover state.
// F() macro keeps string literals in flash, not SRAM.

void debugPrint() {
  static unsigned long lastDebug = 0;
  unsigned long now = millis();
  if (now - lastDebug < 50) return;   // 20 Hz
  lastDebug = now;

  const char* moveStr[] = {"STOP","FWD","BACK","LEFT","RIGHT"};
  uint8_t mIdx = (movementState < 5) ? movementState : 0;

  // Pump remaining seconds (1 decimal)
  float pumpRemaining = 0.0;
  if (pumpRunning) {
    unsigned long elapsed = now - pumpStartMs;
    pumpRemaining = (elapsed < PUMP_TIME_MS)
                    ? (float)(PUMP_TIME_MS - elapsed) / 1000.0
                    : 0.0;
  }

  bool inTestMode = (ch5 > TEST_MODE_THRESHOLD) && !killed && !failsafeActive;

  Serial.print(F("{"));
  Serial.print(F("\"sig\":")); Serial.print(failsafeActive ? 0 : 1);
  Serial.print(F(",\"kill\":")); Serial.print(killed ? 1 : 0);
  Serial.print(F(",\"fs\":")); Serial.print(failsafeActive ? 1 : 0);
  Serial.print(F(",\"test\":")); Serial.print(inTestMode ? 1 : 0);
  Serial.print(F(",\"move\":\"")); Serial.print(moveStr[mIdx]); Serial.print('"');
  Serial.print(F(",\"spL\":")); Serial.print((int)currentSpeedL);
  Serial.print(F(",\"spR\":")); Serial.print((int)currentSpeedR);
  Serial.print(F(",\"air\":")); Serial.print(toolAir ? 1 : 0);
  Serial.print(F(",\"water\":")); Serial.print(toolWater ? 1 : 0);
  Serial.print(F(",\"soil\":")); Serial.print(toolSoil ? 1 : 0);
  Serial.print(F(",\"pump\":")); Serial.print(pumpRunning ? 1 : 0);
  Serial.print(F(",\"pumpT\":")); Serial.print(pumpRemaining, 1);
  Serial.print(F(",\"arm\":")); Serial.print(armRunning ? 1 : 0);
  Serial.print(F(",\"th1\":")); Serial.print(armCurrentTh1, 1);
  Serial.print(F(",\"th2\":")); Serial.print(armCurrentTh2, 1);
  Serial.print(F(",\"th3\":")); Serial.print(armCurrentTh3, 1);
  Serial.print(F(",\"i2c\":["));
  for (int i = 0; i < 6; i++) {
    Serial.print(i2cBuf[i]);
    if (i < 5) Serial.print(',');
  }
  Serial.print(F("],\"ch1\":"));  Serial.print(ch1);
  Serial.print(F(",\"ch2\":"));   Serial.print(ch2);
  Serial.print(F(",\"ch3\":"));   Serial.print(ch3);
  Serial.print(F(",\"ch5\":"));   Serial.print(ch5);
  Serial.print(F(",\"ch6\":"));   Serial.print(ch6);
  Serial.print(F(",\"ch7\":"));   Serial.print(ch7);
  Serial.print(F(",\"ch8\":"));   Serial.print(ch8);
  Serial.println(F("}"));
}