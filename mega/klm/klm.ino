// =============================================================================
// klm.ino — HERC-26 Unified Mega Firmware Outline
// Team MOVIS | Human Exploration Rover Challenge
//
// PURPOSE:
//   Structured outline / skeleton for the final Arduino Mega firmware.
//   Each section is clearly labelled. Fill in each TODO section before deploying.
//   Do NOT remove section headers — they map directly to MEGA_DOCS.md.
//
// WHAT THIS INTEGRATES:
//   1. Drive          — 6-motor differential drive (Final_Mega envelope+sloppy accel)
//   2. Tool actuators — 3 servos via PCA9685 (air / water / soil)
//   3. Arm            — 3-servo absolute-time trajectory player via PCA9685
//   4. Pi I2C Slave   — 6-byte status report to Raspberry Pi at address 0x08
//   5. Status LEDs    — signal + per-tool state indicators
//   6. Failsafe       — hard stop on RC signal loss
//   7. Test Mode      — sequential individual motor spin (see CH_TESTMODE note)
//
// RC CHANNEL MAP (FlySky iBUS, 1000–2000 µs):
//   CH1 (idx 0) — Right stick horizontal → Turn left/right
//   CH2 (idx 1) — Left  stick vertical   → Forward/back base speed
//   CH3 (idx 2) — Right stick vertical   → Speed envelope scale
//   CH5 (idx 4) — Toggle switch A        → Air tool; also Test mode if > 1700
//   CH6 (idx 5) — Toggle switch D        → Kill switch (immediate stop, all tools off)
//   CH7 (idx 6) — Toggle switch B        → Water tool
//   CH8 (idx 7) — Toggle switch C        → Soil tool / arm trigger (TODO: decide)
//
// ⚠ CH5 CONFLICT: CH5 > 1700 activates Test Mode (drive stops).
//   CH5 > 1500 activates the air tool servo.
//   These are intentionally layered: test mode threshold (1700) > tool threshold (1500).
//   If a dedicated test-mode channel is preferred, change CH_TESTMODE below.
//
// PI I2C INTERFACE (address 0x08):
//   Pi sends Wire.requestFrom(0x08, 6) — Mega sends back 6 bytes:
//     byte 0: toolAir        (0 or 1)
//     byte 1: toolWater      (0 or 1)
//     byte 2: toolSoil       (0 or 1)
//     byte 3: movementState  (0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
//     byte 4: ch3 low byte   (raw iBUS pulse, little-endian uint16)
//     byte 5: ch3 high byte
//   sensor/mega.py (not yet written) reads these and returns:
//     {"tools": {"air": bool, "water": bool, "soil": bool},
//      "ibus_pulse": int, "movement": str}
//
// ARM TRAJECTORY FORMAT (absolute-time, matches ARM_sim/sim_view.py):
//   Each keyframe: {time_s (absolute), th1_deg, th2_deg, th3_deg}
//   Firmware interpolates using millis() — identical logic to sim_view.py.
//   Source: export from ARM_sim/sim_create.py, verify in ARM_sim/sim_view.py,
//   then embed here as the ArmKeyframe[] array.
//
// COMPILE:  arduino-cli compile --fqbn arduino:avr:mega klm/
// UPLOAD:   arduino-cli upload  --fqbn arduino:avr:mega --port /dev/ttyACM0 klm/
// =============================================================================

#include <IBusBM.h>
#include <Wire.h>
#include <SoftwareWire.h>          // Install: Library Manager → "SoftwareWire" by Testato
#include <Adafruit_PWMServoDriver.h>

// =============================================================================
// SECTION A — HARDWARE PIN DEFINITIONS
// =============================================================================

// --- 6 Motor PWM and Direction pins ---
// Layout: Driver1=Front, Driver2=Mid, Driver3=Back
//         Even index = Right side, Odd index = Left side
// These match Final_Mega.ino. Verify physical wiring matches this layout.
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

// --- PCA9685 channel assignments ---
// Tool actuator servos (binary on/off via SERVO_TOOL_MIN/MAX)
#define CH_SERVO_AIR    0
#define CH_SERVO_WATER  1
#define CH_SERVO_SOIL   2
// Arm servos (continuous angle control via ARM_SERVO_MIN_US/MAX_US)
#define CH_ARM_1        3    // θ1
#define CH_ARM_2        4    // θ2
#define CH_ARM_3        5    // θ3

// TODO: If arm and tool servos share one PCA9685 board (address 0x40), the
//       channel assignments above are sufficient. If a second board is used
//       (e.g. tools on 0x40, arm on 0x41), declare pca9685_arm separately.

// --- I2C bus separation ---
// Hardware I2C (Wire, pins 20 SDA / 21 SCL) → Pi slave interface ONLY.
// PCA9685 uses software I2C on the pins below so the two buses never share
// the same physical wires. This avoids bus contention between the Pi master
// transactions and the Mega's own master writes to the servo driver.
#define SDA_SW_PIN  11    // Software I2C SDA to PCA9685 — any free digital pin
#define SCL_SW_PIN  12    // Software I2C SCL to PCA9685 — any free digital pin

// --- Pi I2C slave address ---
#define I2C_SLAVE_ADDR  0x08    // Must match sensor/rpi_master.py and i2c_mega_recieve.ino

// --- RC channel indices (0-based) ---
#define CH_TURN_IDX    0    // CH1: turn L/R
#define CH_FWD_IDX     1    // CH2: forward/back
#define CH_SCALE_IDX   2    // CH3: speed envelope / iBUS pulse reported to Pi
#define CH_AIR_IDX     4    // CH5: air tool + test mode
#define CH_KILL_IDX    5    // CH6: kill switch — stops all motion and tools
#define CH_WATER_IDX   6    // CH7: water tool
#define CH_SOIL_IDX    7    // CH8: soil tool / arm trigger

// =============================================================================
// SECTION B — CONSTANTS
// =============================================================================

// --- Tool servo positions ---
#define SERVO_TOOL_MIN   150    // PCA9685 count: tool retracted / off
#define SERVO_TOOL_MAX   600    // PCA9685 count: tool extended / on

// --- Arm servo pulse range ---
#define ARM_SERVO_MIN_US  500
#define ARM_SERVO_MAX_US  2500
#define ARM_SERVO_FREQ    50    // Hz

// --- RC signal ---
#define CENTER_PWM        1500
#define DEADZONE          40
#define FAILSAFE_TIMEOUT  500   // ms without valid iBUS frame → failsafe

// --- Test mode trigger threshold ---
// CH5 > TEST_MODE_THRESHOLD activates Test Mode (drive suspended)
// CH5 > TOOL_THRESHOLD (1500) activates air tool servo
// TEST_MODE_THRESHOLD must be > TOOL_THRESHOLD to keep them layered.
#define TEST_MODE_THRESHOLD 1700
#define TOOL_THRESHOLD      1500

// --- Drive tuning (from Final_Mega — tune using SlopeValuesRef.png) ---
#define ABSOLUTE_MAX_PWM   255
#define TURN_MAX           180
#define TURN_REDUCTION     1.0   // 1.0 = full speed-proportional turn reduction
#define BASE_ACCEL_STEP    12
#define SLOP_FACTOR        0.35
#define MAX_ACCEL_STEP     25

// --- Test mode ---
#define TEST_SPEED         150

// --- Loop timing ---
#define LOOP_DELAY_MS      10    // ms per main loop iteration (~100 Hz)

// =============================================================================
// SECTION C — OBJECTS
// =============================================================================

IBusBM ibus;

// Software I2C master → PCA9685 (physically separate from the Pi slave bus).
// SoftwareWire implements the same API as TwoWire so it is accepted by
// Adafruit_PWMServoDriver's second constructor parameter.
SoftwareWire softWire(SDA_SW_PIN, SCL_SW_PIN);
Adafruit_PWMServoDriver pca9685(0x40, softWire);
// TODO: If arm servos use a second PCA9685 board (address 0x41):
//       Adafruit_PWMServoDriver pca9685_arm(0x41, softWire);

// =============================================================================
// SECTION D — GLOBAL STATE
// =============================================================================

// --- RC channel values (raw µs, 1000–2000) ---
int ch1, ch2, ch3, ch5, ch6, ch7, ch8;

// --- Drive state ---
float currentSpeedL = 0;
float currentSpeedR = 0;

// --- Signal watchdog ---
unsigned long lastSignalTime = 0;

// --- Test mode ---
unsigned long testStartTime = 0;

// --- Kill switch state ---
bool killed = false;

// --- Tool states ---
bool toolAir   = false;
bool toolWater = false;
bool toolSoil  = false;

// --- Movement state (reported to Pi) ---
// 0=STOP, 1=FWD, 2=BACK, 3=LEFT, 4=RIGHT
uint8_t movementState = 0;

// --- I2C response buffer (updated each loop, read by Pi on request) ---
// Layout: [toolAir, toolWater, toolSoil, movementState, ch3_lo, ch3_hi]
volatile uint8_t i2cBuf[6] = {0};

// =============================================================================
// SECTION E — ARM TRAJECTORY
// =============================================================================
//
// ABSOLUTE-TIME FORMAT (matches ARM_sim/sim_view.py):
//   Each keyframe stores the absolute time in seconds at which the arm must
//   reach the given angles. Firmware uses millis() to interpolate linearly
//   between keyframes — identical to how sim_view.py uses numpy.interp.
//
// HOW TO ADD A TRAJECTORY:
//   1. Design it in ARM_sim/sim_create.py (set joint limits, base pos, target box)
//   2. Verify in ARM_sim/sim_view.py (Play, confirm bucket reaches target box)
//   3. Copy the exported CSV values into the ArmKeyframe[] array below
//   4. Set ARM_NUM_FRAMES to the number of rows
//
// GEOMETRY (from ARM_sim/sim_create.py and mega/arm/):
//   L1 = 140 mm (link 1), L2 = 140 mm (link 2), LB = 55 mm (bucket)
//   Note: ARM_sim/sim_view.py uses L2=130 mm — verify the physical hardware
//   and use the correct value. Update sim_create.py if needed.

struct ArmKeyframe {
  float time_s;    // absolute elapsed time (seconds)
  float th1_deg;
  float th2_deg;
  float th3_deg;
};

// TODO: Replace placeholder with values exported from ARM_sim/sim_create.py
//       Rows must be in strictly increasing time order.
ArmKeyframe armTraj[] = {
  // {time_s, th1_deg, th2_deg, th3_deg}
  {0.0,  0.0,  0.0,  0.0},   // placeholder: start (all joints at 0°)
  {3.0, 45.0, 30.0, 15.0},   // placeholder: mid-point
  {6.0, 90.0, 60.0, 30.0},   // placeholder: end
};
const int ARM_NUM_FRAMES = sizeof(armTraj) / sizeof(ArmKeyframe);

// --- Arm state ---
bool     armRunning      = false;
unsigned long armStartMs = 0;

// TODO: Decide arm trigger mechanism. Options:
//   Option A: Dedicated RC channel threshold (e.g. CH8 > 1700)
//   Option B: I2C command byte from Pi (add Wire.onReceive handler)
//   Option C: Physical push-button on Mega GPIO

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

  // I2C — two physically separate buses:
  //   Bus 1: hardware Wire (pins 20/21) → Mega acts as I2C SLAVE to Raspberry Pi.
  //          Wire.begin(address) must be called ONCE. Do not call Wire.begin()
  //          without an address before this — it would put the Mega in master mode
  //          and break the slave registration.
  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(onI2CRequest);
  // TODO: Wire.onReceive(onI2CReceive) — add if Pi needs to send commands
  //       (arm trigger, emergency stop, etc.).

  //   Bus 2: software I2C (SoftwareWire, pins SDA_SW/SCL_SW) → Mega acts as
  //          I2C MASTER to PCA9685. Kept on a separate physical bus so it never
  //          contends with Pi transactions on Bus 1.
  softWire.begin();
  pca9685.begin();
  pca9685.setPWMFreq(50);
  // TODO: pca9685_arm.begin(); pca9685_arm.setPWMFreq(ARM_SERVO_FREQ);

  // Safe starting state
  stopAllMotors();
  safeAllServos();
}

// =============================================================================
// SECTION G — MAIN LOOP
// =============================================================================

void loop() {

  // G1. Read RC channels
  if (readChannelsSafe()) {
    lastSignalTime = millis();
    digitalWrite(LED_SIGNAL, HIGH);

    // G2. Kill switch (priority 2 — below RC failsafe, above everything else)
    //     CH6 > 1500 → hard stop, all tools off, arm halted.
    //     Releases automatically when operator flips CH6 back below 1500.
    killed = (ch6 > TOOL_THRESHOLD);
    if (killed) {
      applyKill();
    } else {
      // G3. Drive mode selection
      if (ch5 > TEST_MODE_THRESHOLD) {
        runTestMode();          // sequential motor spin; drive suspended
      } else {
        testStartTime = 0;      // reset test timer for next activation
        handleDrive();
      }

      // G4. Tool actuators
      handleTools();

      // G5. Arm
      handleArm();
    }

    // G6. Status LEDs (always updated so LEDs reflect killed state too)
    handleLEDs();

    // G7. Update I2C buffer for Pi
    updateI2CBuffer();

  } else {
    // G8. No valid signal
    if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) {
      digitalWrite(LED_SIGNAL, LOW);
      applyFailsafe();
    }
  }

  delay(LOOP_DELAY_MS);
}

// =============================================================================
// SECTION H — RC INPUT
// =============================================================================

bool readChannelsSafe() {
  // Probe CH3 first. If it's out of the valid RC range, the receiver
  // is not sending valid frames — skip this cycle entirely.
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
// SECTION I — DRIVE (Final_Mega algorithm: envelope + sloppy adaptive accel)
// =============================================================================

void handleDrive() {

  // I1. Apply dead-band and normalize stick inputs to factors in [-1, +1]
  int moveRaw  = (abs(ch2 - CENTER_PWM) < DEADZONE) ? 0 : (ch2 - CENTER_PWM);
  int scaleRaw = (abs(ch3 - CENTER_PWM) < DEADZONE) ? 0 : (ch3 - CENTER_PWM);
  int turnRaw  = (abs(ch1 - CENTER_PWM) < DEADZONE) ? 0 : (ch1 - CENTER_PWM);

  float moveFactor  = moveRaw  / 500.0;   // left stick up/down  [-1..+1]
  float scaleFactor = scaleRaw / 500.0;   // right stick up/down [-1..+1]
  float turnFactor  = turnRaw  / 500.0;   // right stick L/R     [-1..+1]

  // I2. Speed envelope: left stick sets base speed, right stick scales it
  float X        = moveFactor * ABSOLUTE_MAX_PWM;
  float limitedX = X * scaleFactor;

  // I3. Speed-proportional turn reduction (less turning at high speed)
  float speedRatio              = abs(limitedX) / ABSOLUTE_MAX_PWM;
  float turnReductionMultiplier = 1.0 - (speedRatio * TURN_REDUCTION);
  turnReductionMultiplier       = constrain(turnReductionMultiplier, 0.2, 1.0);
  float Y = turnFactor * TURN_MAX * turnReductionMultiplier;

  // I4. Differential mixing — left and right tracks get independent targets
  float targetL = constrain(limitedX + Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);
  float targetR = constrain(limitedX - Y, -ABSOLUTE_MAX_PWM, ABSOLUTE_MAX_PWM);

  // I5. Sloppy adaptive acceleration ramp
  //     Larger error → bigger step → snaps to target quickly
  //     Small error  → small step  → settles smoothly
  float diffL = targetL - currentSpeedL;
  float diffR = targetR - currentSpeedR;

  float stepL = constrain(BASE_ACCEL_STEP + abs(diffL) * SLOP_FACTOR,
                           BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  float stepR = constrain(BASE_ACCEL_STEP + abs(diffR) * SLOP_FACTOR,
                           BASE_ACCEL_STEP, MAX_ACCEL_STEP);

  currentSpeedL += (diffL > 0) ?  min(stepL,  diffL) : -min(stepL, -diffL);
  currentSpeedR += (diffR > 0) ?  min(stepR,  diffR) : -min(stepR, -diffR);

  // I6. Apply to motors (even index = right side, odd = left side)
  for (int i = 0; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedR >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedR));
  }
  for (int i = 1; i < 6; i += 2) {
    digitalWrite(motorDIR[i], (currentSpeedL >= 0) ? HIGH : LOW);
    analogWrite(motorPWM[i],  abs((int)currentSpeedL));
  }

  // I7. Compute movement string for Pi snapshot
  movementState = computeMovementState(limitedX, Y);
}

// Movement state mapping: STOP=0, FWD=1, BACK=2, LEFT=3, RIGHT=4
uint8_t computeMovementState(float fwd, float turn) {
  if (abs(fwd) < 10 && abs(turn) < 10) return 0;   // STOP
  if (abs(turn) > abs(fwd) * 0.8)
    return (turn > 0) ? 4 : 3;                       // RIGHT or LEFT
  return (fwd >= 0) ? 1 : 2;                         // FWD or BACK
}

// =============================================================================
// SECTION J — TOOL ACTUATORS (air / water / soil)
// =============================================================================

void handleTools() {
  // Map toggle switch channels to binary tool states
  toolAir   = (ch5 > TOOL_THRESHOLD) && (ch5 <= TEST_MODE_THRESHOLD);
  // NOTE: toolAir is TRUE only between 1500 and 1700.
  // At ch5 > 1700 the rover is in test mode and tools should be OFF.
  // If this behaviour is not desired, change to: toolAir = (ch5 > TOOL_THRESHOLD);

  toolWater = (ch7 > TOOL_THRESHOLD);
  toolSoil  = (ch8 > TOOL_THRESHOLD);

  // Drive tool servos on PCA9685
  pca9685.setPWM(CH_SERVO_AIR,   0, toolAir   ? SERVO_TOOL_MAX : SERVO_TOOL_MIN);
  pca9685.setPWM(CH_SERVO_WATER, 0, toolWater ? SERVO_TOOL_MAX : SERVO_TOOL_MIN);
  pca9685.setPWM(CH_SERVO_SOIL,  0, toolSoil  ? SERVO_TOOL_MAX : SERVO_TOOL_MIN);
}

// =============================================================================
// SECTION K — ARM TRAJECTORY PLAYER
// =============================================================================
//
// Absolute-time interpolation matching ARM_sim/sim_view.py:
//   Given current elapsed time T:
//   - Find the two keyframes that bracket T (k and k+1)
//   - t_frac = (T - armTraj[k].time_s) / (armTraj[k+1].time_s - armTraj[k].time_s)
//   - angle = lerp(armTraj[k].angle, armTraj[k+1].angle, t_frac)
//   - Apply to PCA9685 channels CH_ARM_1/2/3
//   - Stop when T >= armTraj[ARM_NUM_FRAMES-1].time_s

void handleArm() {
  // TODO: Implement arm trigger. Example (CH8 > 1700 starts the trajectory):
  //   static bool armTriggerPrev = false;
  //   bool armTriggerNow = (ch8 > 1700);
  //   if (armTriggerNow && !armTriggerPrev) startArm();
  //   armTriggerPrev = armTriggerNow;

  if (!armRunning) return;

  float elapsedS = (millis() - armStartMs) / 1000.0;

  // Clamp to trajectory end
  if (elapsedS >= armTraj[ARM_NUM_FRAMES - 1].time_s) {
    // Hold final pose
    setArmServos(armTraj[ARM_NUM_FRAMES - 1].th1_deg,
                 armTraj[ARM_NUM_FRAMES - 1].th2_deg,
                 armTraj[ARM_NUM_FRAMES - 1].th3_deg);
    armRunning = false;
    return;
  }

  // Find bracketing keyframes
  int k = 0;
  for (int i = 0; i < ARM_NUM_FRAMES - 1; i++) {
    if (elapsedS >= armTraj[i].time_s && elapsedS < armTraj[i + 1].time_s) {
      k = i;
      break;
    }
  }

  float dt      = armTraj[k + 1].time_s - armTraj[k].time_s;
  float t_frac  = (dt > 0) ? (elapsedS - armTraj[k].time_s) / dt : 1.0;

  float a1 = armTraj[k].th1_deg + t_frac * (armTraj[k + 1].th1_deg - armTraj[k].th1_deg);
  float a2 = armTraj[k].th2_deg + t_frac * (armTraj[k + 1].th2_deg - armTraj[k].th2_deg);
  float a3 = armTraj[k].th3_deg + t_frac * (armTraj[k + 1].th3_deg - armTraj[k].th3_deg);

  setArmServos(a1, a2, a3);
}

void startArm() {
  armStartMs = millis();
  armRunning = true;
}

void setArmServos(float th1, float th2, float th3) {
  pca9685.setPWM(CH_ARM_1, 0, armAngleToPWM(th1));
  pca9685.setPWM(CH_ARM_2, 0, armAngleToPWM(th2));
  pca9685.setPWM(CH_ARM_3, 0, armAngleToPWM(th3));
}

uint16_t armAngleToPWM(float angleDeg) {
  angleDeg = constrain(angleDeg, 0, 180);
  float us = ARM_SERVO_MIN_US +
             (angleDeg / 180.0) * (ARM_SERVO_MAX_US - ARM_SERVO_MIN_US);
  return (uint16_t)(us * ARM_SERVO_FREQ * 4096 / 1000000.0);
}

// =============================================================================
// SECTION L — TEST MODE
// =============================================================================
// Spins each of the 6 motors individually for 2 s with 2 s gaps.
// Useful to verify motor wiring direction and driver health at competition.
// Activated when CH5 > TEST_MODE_THRESHOLD (1700). Drive is suspended.

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
// SECTION M — FAILSAFE
// =============================================================================

void applyKill() {
  // Operator-triggered hard stop (CH6 switch).
  // Identical effect to failsafe but releases when CH6 is flipped back.
  stopAllMotors();
  safeAllServos();
  armRunning    = false;
  movementState = 0;
  toolAir = toolWater = toolSoil = false;
  updateI2CBuffer();
}

void applyFailsafe() {
  // Automatic hard stop on RC signal loss (>500 ms without valid iBUS frame).
  // Exits when signal is restored.
  stopAllMotors();
  safeAllServos();
  armRunning    = false;
  movementState = 0;
  toolAir = toolWater = toolSoil = false;
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

void safeAllServos() {
  // Tool servos: retract
  pca9685.setPWM(CH_SERVO_AIR,   0, SERVO_TOOL_MIN);
  pca9685.setPWM(CH_SERVO_WATER, 0, SERVO_TOOL_MIN);
  pca9685.setPWM(CH_SERVO_SOIL,  0, SERVO_TOOL_MIN);
  // Arm: hold current position (do not force-drive on failsafe)
  // TODO: Optionally drive arm to a known home pose on failsafe.
}

void handleLEDs() {
  digitalWrite(LED_AIR,   toolAir   ? HIGH : LOW);
  digitalWrite(LED_WATER, toolWater ? HIGH : LOW);
  digitalWrite(LED_SOIL,  toolSoil  ? HIGH : LOW);
}

// =============================================================================
// SECTION O — PI I2C SLAVE INTERFACE
// =============================================================================
//
// The Pi calls:  Wire.requestFrom(0x08, 6)
// The Mega sends: 6 bytes from i2cBuf[]
//
// sensor/mega.py (not yet written) will decode this into:
//   {"tools": {"air": bool, "water": bool, "soil": bool},
//    "ibus_pulse": int, "movement": str}
//
// The "movement" string mapping:
//   movementState 0 → "STOP"
//   movementState 1 → "FWD"
//   movementState 2 → "BACK"
//   movementState 3 → "LEFT"
//   movementState 4 → "RIGHT"
// Pi-side mega.py must decode movementState byte using this mapping.
//
// The "ibus_pulse" value is ch3 raw (right stick vertical, 1000–2000 µs).
// Pi reconstructs it as: (i2cBuf[5] << 8) | i2cBuf[4]

void updateI2CBuffer() {
  noInterrupts();
  i2cBuf[0] = (uint8_t)toolAir;
  i2cBuf[1] = (uint8_t)toolWater;
  i2cBuf[2] = (uint8_t)toolSoil;
  i2cBuf[3] = movementState;
  i2cBuf[4] = (uint8_t)(ch3 & 0xFF);         // low byte of ch3
  i2cBuf[5] = (uint8_t)((ch3 >> 8) & 0xFF);  // high byte of ch3
  interrupts();
}

void onI2CRequest() {
  // Called automatically when Pi calls Wire.requestFrom(0x08, 6)
  Wire.write((uint8_t *)i2cBuf, sizeof(i2cBuf));
}

// TODO: void onI2CReceive(int bytes) { ... }
//       Uncomment Wire.onReceive(onI2CReceive) in setup() if Pi needs to
//       send commands to Mega (arm trigger, emergency stop, etc.).
//       Read one byte: uint8_t cmd = Wire.read();
//       Example commands: 0x01 = start arm, 0x02 = stop arm, 0x03 = e-stop
