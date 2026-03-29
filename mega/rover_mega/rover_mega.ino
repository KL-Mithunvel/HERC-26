// rover_mega.ino — HERC-26 Team MOVIS
// Arduino Mega — Unified Rover Controller
//
// ── BAREBONE_TEST flag ────────────────────────────────────────────────────────
//   1 = iBUS / I2C / tool logic active.  Drive motors are NOT driven.
//       Use this when verifying I2C comms with the Pi before field deployment.
//       All channel decoding, tool states, and I2C packet still work normally.
//   0 = Full deployment. All hardware active.
//
#define BAREBONE_TEST 1     // ← set 0 for full deployment
//
// Responsibilities:
//   1. Motor drive     — 6 wheels differential, trapezoidal acceleration
//   2. Tool actuators  — Soil / Water linear actuators (H-bridge), Air flag
//   3. Pump            — Peristaltic water pump, auto-timed (5 s)
//   4. Servos          — 3 × servo via PCA9685 (I2C master)
//   5. I2C slave       — Reports status to Raspberry Pi at address 0x08
//   6. Failsafe        — Hard-stop all outputs on RC signal loss > 500 ms
//
// ── Channel map (FlySky iBUS, 0-indexed internally) ──────────────────────────
//   CH1 (idx 0)  Steering / Turn  (< CENTER-DEADZONE = LEFT, > CENTER+DEADZONE = RIGHT)
//   CH2 (idx 1)  Fwd / Rev        (>= 1400 = forward)
//   CH3 (idx 2)  Throttle         (1000–2000 → 0–MAX_PWM); also RC validation
//   CH5 (idx 4)  Soil tool        — servo 0 + H-bridge actuator (SOIL_FWD/REV)
//   CH6 (idx 5)  Water tool       — servo 1 + H-bridge actuator (WATER_FWD/REV) + pump
//   CH7 (idx 6)  Air tool         — servo 2 + flag to Pi via I2C
//
// ── Motor layout ─────────────────────────────────────────────────────────────
//   Indices 0, 2, 4 = right side (PWM pins 2, 6, 9)
//   Indices 1, 3, 5 = left  side (PWM pins 3, 7, 10)
//
// ── I2C topology ─────────────────────────────────────────────────────────────
//   Mega master → PCA9685 @ 0x40  (pca9685.begin() first)
//   Pi  master  → Mega slave @ 0x08  (Wire.begin(0x08) on top — TWI supports both)
//   Physical bus: SDA=20, SCL=21
//
// ── I2C status packet (7 bytes, packed) ──────────────────────────────────────
//   byte 0: tool_water    bool
//   byte 1: tool_air      bool
//   byte 2: tool_soil     bool
//   byte 3: ibus_pulse    bool — true = RC signal valid this read cycle
//   byte 4: movement      uint8 — 0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT
//   byte 5: pump_running  bool
//   byte 6: failsafe      bool — true = 500 ms timeout, all outputs hard-stopped
//
// Compile:  arduino-cli compile --fqbn arduino:avr:mega mega/rover_mega
// Upload:   arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 mega/rover_mega

#include <IBusBM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

IBusBM ibus;
Adafruit_PWMServoDriver pca9685 = Adafruit_PWMServoDriver();

// ── I2C ──────────────────────────────────────────────────────────────────────
#define I2C_SLAVE_ADDR  0x08

// ── Motor pins ───────────────────────────────────────────────────────────────
int motorPWM[6] = {2, 3, 6, 7, 9, 10};
int motorDIR[6] = {22, 23, 24, 25, 26, 27};

// ── LED pins ─────────────────────────────────────────────────────────────────
#define LED_SIGNAL  30
#define LED_SOIL    31
#define LED_WATER   32
#define LED_AIR     33

// ── Servo constants (PCA9685) ─────────────────────────────────────────────────
#define SERVO_MIN  150
#define SERVO_MAX  600

// ── Drive constants ───────────────────────────────────────────────────────────
#define MAX_PWM           160     // ~63% duty (MDD10A safe limit)
#define DEADZONE           40     // iBUS dead band around CENTER_PWM
#define CENTER_PWM       1500     // iBUS neutral / centre value
#define TURN_MAX          100.0f  // max turn differential (PWM units)
#define TURN_REDUCTION    0.8f    // turn authority reduction at high speed
#define BASE_ACCEL_STEP    5.0f   // minimum speed change per loop tick
#define SLOP_FACTOR        0.3f   // extra step proportional to speed error
#define MAX_ACCEL_STEP    20.0f   // cap on per-tick step
#define LOOP_DELAY         20     // ms (~50 Hz main loop)
#define FAILSAFE_TIMEOUT  500     // ms without valid signal → hard stop

// ── Actuator / pump pins ──────────────────────────────────────────────────────
#define SOIL_FWD   40
#define SOIL_REV   41
#define WATER_FWD  42
#define WATER_REV  43
#define PUMP_PIN   44   // PWM-capable pin; NOT pin 3 (that is a motor PWM)

const unsigned int PUMP_TIME_S = 5;   // pump auto-off after this many seconds

// ── Movement codes ────────────────────────────────────────────────────────────
#define MOV_STOP   0
#define MOV_FWD    1
#define MOV_BACK   2
#define MOV_LEFT   3
#define MOV_RIGHT  4

// ── I2C status packet (7 bytes, packed struct) ────────────────────────────────
struct __attribute__((packed)) StatusPacket {
  bool    tool_water;
  bool    tool_air;
  bool    tool_soil;
  bool    ibus_pulse;
  uint8_t movement;     // MOV_* code above
  bool    pump_running;
  bool    failsafe;
};
StatusPacket status;

// ── Channel values ────────────────────────────────────────────────────────────
int ch1, ch2, ch3, ch5, ch6, ch7;

// ── Drive state ───────────────────────────────────────────────────────────────
float currentSpeedL = 0.0f;   // left  side speed (−MAX_PWM … +MAX_PWM)
float currentSpeedR = 0.0f;   // right side speed (−MAX_PWM … +MAX_PWM)

// ── Failsafe ──────────────────────────────────────────────────────────────────
unsigned long lastSignalTime = 0;
bool failsafeActive = false;

// ── Tool / pump state ─────────────────────────────────────────────────────────
bool tool_soil   = false;
bool tool_water  = false;
bool tool_air    = false;
bool ibus_pulse  = false;
bool soilRunning  = false;
bool waterRunning = false;
bool pumpRunning  = false;
unsigned long pumpStart = 0;


// =============================================================================
// SETUP
// =============================================================================
void setup() {
  Serial.begin(115200);
  ibus.begin(Serial1);

  for (int i = 0; i < 6; i++) {
    pinMode(motorPWM[i], OUTPUT);
    pinMode(motorDIR[i], OUTPUT);
  }

  pinMode(LED_SIGNAL, OUTPUT);
  pinMode(LED_SOIL,   OUTPUT);
  pinMode(LED_WATER,  OUTPUT);
  pinMode(LED_AIR,    OUTPUT);
  pinMode(SOIL_FWD,   OUTPUT);
  pinMode(SOIL_REV,   OUTPUT);
  pinMode(WATER_FWD,  OUTPUT);
  pinMode(WATER_REV,  OUTPUT);
  pinMode(PUMP_PIN,   OUTPUT);

  // PCA9685 must call begin() first (internally calls Wire.begin as master).
  // Wire.begin(I2C_SLAVE_ADDR) then adds the slave address — TWI supports both.
  pca9685.begin();
  pca9685.setPWMFreq(50);
  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);

  stopAllMotors();
  allActuatorsOff();
  moveServosToSafe();

#if BAREBONE_TEST
  Serial.println("HERC-26 Rover Mega — BAREBONE TEST MODE (motors disabled)");
  Serial.println("  iBUS decoding, I2C packet, tools, pump, servos are all active.");
  Serial.println("  Set BAREBONE_TEST 0 for full deployment.");
#else
  Serial.println("HERC-26 Rover Mega — Full deployment mode");
#endif
}


// =============================================================================
// MAIN LOOP  (~50 Hz)
// =============================================================================
void loop() {
  if (readChannelsSafe()) {
    lastSignalTime = millis();
    failsafeActive = false;
    ibus_pulse     = true;
    digitalWrite(LED_SIGNAL, HIGH);
  } else {
    ibus_pulse = false;
    digitalWrite(LED_SIGNAL, LOW);
  }

  if (isFailsafeActive()) {
    applyFailsafe();
    delay(LOOP_DELAY);
    return;
  }

  handleDrive();
  handleServos();
  handleSoilTool();
  handleWaterTool();
  handleAirTool();
  handlePump();
  handleLEDs();
  updateStatusPacket();

  delay(LOOP_DELAY);
}


// =============================================================================
// iBUS READ — returns true if signal is valid
// =============================================================================
bool readChannelsSafe() {
  int test = ibus.readChannel(2);   // CH3 throttle — used as validity check
  if (test < 900 || test > 2100) return false;

  ch1 = ibus.readChannel(0);   // steering / turn
  ch2 = ibus.readChannel(1);   // forward / reverse direction
  ch3 = test;                  // throttle
  ch5 = ibus.readChannel(4);   // soil tool
  ch6 = ibus.readChannel(5);   // water tool
  ch7 = ibus.readChannel(6);   // air tool
  return true;
}


// =============================================================================
// FAILSAFE
// =============================================================================
bool isFailsafeActive() {
  if (millis() - lastSignalTime > FAILSAFE_TIMEOUT) failsafeActive = true;
  return failsafeActive;
}

void applyFailsafe() {
  stopAllMotors();
  allActuatorsOff();
  moveServosToSafe();
  stopPump();

  tool_soil = tool_water = tool_air = ibus_pulse = false;
  soilRunning = waterRunning = false;

  // Mark failsafe in the packet immediately so the Pi can see it
  status.failsafe     = true;
  status.pump_running = false;
  status.ibus_pulse   = false;
  status.movement     = MOV_STOP;
  status.tool_water   = false;
  status.tool_air     = false;
  status.tool_soil    = false;

  digitalWrite(LED_SOIL,  LOW);
  digitalWrite(LED_WATER, LOW);
  digitalWrite(LED_AIR,   LOW);
}


// =============================================================================
// DRIVE — differential left/right, trapezoidal acceleration
//
//   CH1  steering : > CENTER+DEADZONE → turn RIGHT  (left wheels faster)
//                   < CENTER-DEADZONE → turn LEFT   (right wheels faster)
//   CH2  direction: >= 1400 = forward, < 1400 = reverse
//   CH3  throttle : 1000–2000 scales total speed 0–MAX_PWM
//
//   In BAREBONE_TEST mode: speeds are computed for movement reporting
//   but no PWM/DIR signals are written to motor pins.
// =============================================================================
float rampSpeed(float cur, float tgt) {
  float diff = tgt - cur;
  float step = constrain(BASE_ACCEL_STEP + fabs(diff) * SLOP_FACTOR,
                         BASE_ACCEL_STEP, MAX_ACCEL_STEP);
  if (diff > 0.0f) return cur + min(step, diff);
  return cur - min(step, -diff);
}

void handleDrive() {
  // Throttle scale: 0.0 → 1.0
  float throttle = constrain((ch3 - 1000) / 1000.0f, 0.0f, 1.0f);

  // Forward / back factor: −1.0 → +1.0
  float moveFactor = 0.0f;
  int moveRaw = ch2 - CENTER_PWM;
  if (abs(moveRaw) > DEADZONE) moveFactor = (float)moveRaw / 500.0f;

  // Steering factor: −1.0 → +1.0  (> 0 = right turn)
  float turnFactor = 0.0f;
  int turnRaw = ch1 - CENTER_PWM;
  if (abs(turnRaw) > DEADZONE) turnFactor = (float)turnRaw / 500.0f;

  // Base speed
  float baseSpeed = moveFactor * (float)MAX_PWM * throttle;

  // Reduce turn authority at high speed
  float speedRatio = fabs(baseSpeed) / (float)MAX_PWM;
  float turnMult   = constrain(1.0f - speedRatio * TURN_REDUCTION, 0.2f, 1.0f);
  float turnOffset = turnFactor * TURN_MAX * turnMult;

  // Differential mix: right = base − turn,  left = base + turn
  float targetR = constrain(baseSpeed - turnOffset, -(float)MAX_PWM, (float)MAX_PWM);
  float targetL = constrain(baseSpeed + turnOffset, -(float)MAX_PWM, (float)MAX_PWM);

  currentSpeedR = rampSpeed(currentSpeedR, targetR);
  currentSpeedL = rampSpeed(currentSpeedL, targetL);

#if !BAREBONE_TEST
  // Right side motors: indices 0, 2, 4
  bool rightFwd = (currentSpeedR >= 0.0f);
  for (int i = 0; i < 6; i += 2) {
    digitalWrite(motorDIR[i], rightFwd ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedR));
  }
  // Left side motors: indices 1, 3, 5
  bool leftFwd = (currentSpeedL >= 0.0f);
  for (int i = 1; i < 6; i += 2) {
    digitalWrite(motorDIR[i], leftFwd ? HIGH : LOW);
    analogWrite(motorPWM[i], abs((int)currentSpeedL));
  }
#endif
}

// Derive a single movement label from current speed and stick positions.
uint8_t computeMovement() {
  if (failsafeActive) return MOV_STOP;

  float avgAbs = (fabs(currentSpeedL) + fabs(currentSpeedR)) / 2.0f;
  if (avgAbs < 5.0f) return MOV_STOP;

  // Dominant turn: ch1 must be more than 2× deadzone from centre
  int turnRaw = ch1 - CENTER_PWM;
  if (abs(turnRaw) > DEADZONE * 2) {
    return (turnRaw > 0) ? MOV_RIGHT : MOV_LEFT;
  }

  return (ch2 >= 1400) ? MOV_FWD : MOV_BACK;
}

void stopAllMotors() {
  currentSpeedL = 0.0f;
  currentSpeedR = 0.0f;
#if !BAREBONE_TEST
  for (int i = 0; i < 6; i++) analogWrite(motorPWM[i], 0);
#endif
}


// =============================================================================
// SERVOS (PCA9685)
//   Servo 0 — CH5 (soil deployment angle)
//   Servo 1 — CH6 (water deployment angle)
//   Servo 2 — CH7 (air sensor arm)
// =============================================================================
void handleServos() {
  pca9685.setPWM(0, 0, ch5 > 1500 ? SERVO_MAX : SERVO_MIN);
  pca9685.setPWM(1, 0, ch6 > 1500 ? SERVO_MAX : SERVO_MIN);
  pca9685.setPWM(2, 0, ch7 > 1500 ? SERVO_MAX : SERVO_MIN);
}

void moveServosToSafe() {
  for (uint8_t i = 0; i < 3; i++) pca9685.setPWM(i, 0, SERVO_MIN);
}


// =============================================================================
// SOIL TOOL  (CH5)
// =============================================================================
void handleSoilTool() {
  if (ch5 > 1500) {
    tool_soil = true;
    if (!soilRunning) { soilRunning = true; startSoilForward(); }
  } else {
    tool_soil = false;
    if (soilRunning) { stopSoil(); retractSoil(); soilRunning = false; }
  }
}


// =============================================================================
// WATER TOOL  (CH6)
// =============================================================================
void handleWaterTool() {
  if (ch6 > 1500) {
    tool_water = true;
    if (!waterRunning) { waterRunning = true; startWaterForward(); }
  } else {
    tool_water = false;
    if (waterRunning) { stopWater(); retractWater(); stopPump(); waterRunning = false; }
  }
}


// =============================================================================
// AIR TOOL  (CH7)
// =============================================================================
void handleAirTool() {
  tool_air = (ch7 > 1500);
}


// =============================================================================
// PUMP  (auto-off after PUMP_TIME_S seconds)
// =============================================================================
void startPump() {
  pumpStart   = millis();
  pumpRunning = true;
  digitalWrite(PUMP_PIN, HIGH);
}

void handlePump() {
  if (!pumpRunning) return;
  if (millis() - pumpStart > (unsigned long)PUMP_TIME_S * 1000UL) stopPump();
}

void stopPump() {
  digitalWrite(PUMP_PIN, LOW);
  pumpRunning = false;
}


// =============================================================================
// SOIL ACTUATOR
// =============================================================================
void startSoilForward() { digitalWrite(SOIL_FWD, HIGH); digitalWrite(SOIL_REV, LOW);  }
void retractSoil()      { digitalWrite(SOIL_FWD, LOW);  digitalWrite(SOIL_REV, HIGH); }
void stopSoil()         { digitalWrite(SOIL_FWD, LOW);  digitalWrite(SOIL_REV, LOW);  }


// =============================================================================
// WATER ACTUATOR
// =============================================================================
void startWaterForward() {
  digitalWrite(WATER_FWD, HIGH);
  digitalWrite(WATER_REV, LOW);
  startPump();
}
void retractWater() { digitalWrite(WATER_FWD, LOW);  digitalWrite(WATER_REV, HIGH); }
void stopWater()    { digitalWrite(WATER_FWD, LOW);  digitalWrite(WATER_REV, LOW);  }

void allActuatorsOff() {
  stopSoil();
  stopWater();
}


// =============================================================================
// LEDs
// =============================================================================
void handleLEDs() {
  digitalWrite(LED_SOIL,  tool_soil  ? HIGH : LOW);
  digitalWrite(LED_WATER, tool_water ? HIGH : LOW);
  digitalWrite(LED_AIR,   tool_air   ? HIGH : LOW);
}


// =============================================================================
// STATUS PACKET  — assembled every loop cycle
// =============================================================================
void updateStatusPacket() {
  status.tool_water   = tool_water;
  status.tool_air     = tool_air;
  status.tool_soil    = tool_soil;
  status.ibus_pulse   = ibus_pulse;
  status.movement     = computeMovement();
  status.pump_running = pumpRunning;
  status.failsafe     = failsafeActive;
}


// =============================================================================
// I2C  — Pi reads tool/movement status
// =============================================================================
void onRequest() {
  Wire.write((uint8_t*)&status, sizeof(status));
}

// Receive commands from Pi (future: remote overrides, diagnostics)
void onReceive(int bytes) {
  while (Wire.available()) {
    byte cmd = Wire.read();
    Serial.print("Pi cmd: 0x");
    Serial.println(cmd, HEX);
  }
}
