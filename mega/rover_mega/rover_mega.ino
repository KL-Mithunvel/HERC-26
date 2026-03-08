// rover_mega.ino — HERC-26 Team MOVIS
// Arduino Mega — Unified Rover Controller
//
// Responsibilities:
//   1. Motor drive     — 6 wheels via MDD10A H-bridge, trapezoidal acceleration
//   2. Tool actuators  — Soil / Water linear actuators (H-bridge), Air flag
//   3. Pump            — Peristaltic water pump, auto-timed (5 s)
//   4. Servos          — 3 × servo via PCA9685 (I2C master), same channels as tools
//   5. I2C slave       — Reports tool status to Raspberry Pi at address 0x08
//   6. Failsafe        — Hard-stop all outputs on RC signal loss > 500 ms
//
// ── Channel map (FlySky iBUS, 0-indexed internally) ──────────────────────────
//   CH2 (idx 1)  Forward / Reverse direction  (>=1400 = forward)
//   CH3 (idx 2)  Throttle                     (1000–2000 → 0–MAX_PWM)
//   CH5 (idx 4)  Soil tool   — servo 0 + H-bridge actuator (SOIL_FWD/REV)
//   CH6 (idx 5)  Water tool  — servo 1 + H-bridge actuator (WATER_FWD/REV) + pump
//   CH7 (idx 6)  Air tool    — servo 2 + flag to Pi (no local actuator)
//
// ── I2C topology ─────────────────────────────────────────────────────────────
//   Mega master  →  PCA9685 servo driver @ 0x40  (Wire.beginTransmission)
//   Pi master    →  Mega slave @ 0x08             (Wire.onRequest / onReceive)
//   Both share the same physical bus (SDA=20, SCL=21).
//   pca9685.begin() is called first, then Wire.begin(I2C_SLAVE_ADDR) adds
//   the slave address on top — the ATmega TWI hardware supports both roles.
//
// ── Pin map ──────────────────────────────────────────────────────────────────
//   Motor PWM    :  2,  3,  6,  7,  9, 10
//   Motor DIR    : 22, 23, 24, 25, 26, 27
//   Soil actuator: 40 (FWD), 41 (REV)
//   Water actuator: 42 (FWD), 43 (REV)
//   Pump         : 44  ← PWM-capable; NOT pin 3 (pin 3 is motor PWM)
//   LEDs         : 30 (signal), 31 (soil), 32 (water), 33 (air)
//
// ── I2C status packet (4 bytes) sent to Pi on each onRequest ─────────────────
//   byte 0: tool_water  (bool)
//   byte 1: tool_air    (bool)
//   byte 2: tool_soil   (bool)
//   byte 3: ibus_pulse  (bool — true when RC signal is valid)
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

// ── Motor safety limits ───────────────────────────────────────────────────────
#define MAX_PWM           160   // ~63% duty (MDD10A safe limit)
#define ACCEL_STEP          2   // speed units per loop tick
#define LOOP_DELAY         20   // ms — loop runs at ~50 Hz
#define DIR_CHANGE_DELAY  200   // ms pause on direction reversal
#define FAILSAFE_TIMEOUT  500   // ms without valid signal → hard stop

// ── Actuator / pump pins ──────────────────────────────────────────────────────
#define SOIL_FWD   40
#define SOIL_REV   41
#define WATER_FWD  42
#define WATER_REV  43
#define PUMP_PIN   44   // PWM pin — NOT 3 (pin 3 = motor PWM)

const unsigned int PUMP_TIME_S = 5;   // pump auto-off after this many seconds

// ── I2C status packet ─────────────────────────────────────────────────────────
struct StatusPacket {
  bool tool_water;
  bool tool_air;
  bool tool_soil;
  bool ibus_pulse;
};
StatusPacket status;

// ── Channel values ────────────────────────────────────────────────────────────
int ch2, ch3, ch5, ch6, ch7;

// ── Motor state ───────────────────────────────────────────────────────────────
int  targetSpeed  = 0;
int  currentSpeed = 0;
bool lastDirection = true;   // true = forward

// ── Failsafe ──────────────────────────────────────────────────────────────────
unsigned long lastSignalTime = 0;
bool failsafeActive = false;

// ── Tool state ────────────────────────────────────────────────────────────────
bool tool_soil   = false;
bool tool_water  = false;
bool tool_air    = false;
bool ibus_pulse  = false;

bool soilRunning  = false;
bool waterRunning = false;

unsigned long pumpStart  = 0;
bool pumpRunning  = false;


// =============================================================================
// SETUP
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
  pinMode(LED_SOIL,   OUTPUT);
  pinMode(LED_WATER,  OUTPUT);
  pinMode(LED_AIR,    OUTPUT);

  // Actuator and pump pins
  pinMode(SOIL_FWD,  OUTPUT);
  pinMode(SOIL_REV,  OUTPUT);
  pinMode(WATER_FWD, OUTPUT);
  pinMode(WATER_REV, OUTPUT);
  pinMode(PUMP_PIN,  OUTPUT);

  // PCA9685: initialise as I2C master first (calls Wire.begin() internally)
  pca9685.begin();
  pca9685.setPWMFreq(50);

  // Slave address added on top of master mode — ATmega TWI supports both roles.
  // MUST be called after pca9685.begin() so the slave config is not overwritten.
  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);

  stopAllMotors();
  allActuatorsOff();
  moveServosToSafe();

  Serial.println("HERC-26 Rover Mega — Ready");
}


// =============================================================================
// MAIN LOOP  (~50 Hz)
// =============================================================================
void loop() {
  if (readChannelsSafe()) {
    lastSignalTime  = millis();
    failsafeActive  = false;
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

  handleDirection();
  handleThrottleTrapezoidal();
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
// iBUS READ
// =============================================================================
bool readChannelsSafe() {
  int test = ibus.readChannel(2);   // CH3 — throttle / validation check
  if (test < 900 || test > 2100) return false;

  ch2 = ibus.readChannel(1);        // direction
  ch3 = test;                       // throttle
  ch5 = ibus.readChannel(4);        // soil tool
  ch6 = ibus.readChannel(5);        // water tool
  ch7 = ibus.readChannel(6);        // air tool
  ibus_pulse = true;
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

  updateStatusPacket();

  digitalWrite(LED_SOIL,  LOW);
  digitalWrite(LED_WATER, LOW);
  digitalWrite(LED_AIR,   LOW);
}


// =============================================================================
// MOTOR CONTROL
// =============================================================================
void handleDirection() {
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

void handleThrottleTrapezoidal() {
  targetSpeed = map(ch3, 1000, 2000, 0, MAX_PWM);
  targetSpeed = constrain(targetSpeed, 0, MAX_PWM);

  if (currentSpeed < targetSpeed) {
    currentSpeed = min(currentSpeed + ACCEL_STEP, targetSpeed);
  } else if (currentSpeed > targetSpeed) {
    currentSpeed = max(currentSpeed - ACCEL_STEP, targetSpeed);
  }
  setAllMotors(currentSpeed);
}

void setAllMotors(int pwmVal) {
  for (int i = 0; i < 6; i++) analogWrite(motorPWM[i], pwmVal);
}

void stopAllMotors() {
  currentSpeed = 0;
  setAllMotors(0);
}


// =============================================================================
// SERVOS (PCA9685)
//   Servo 0 — CH5 (soil deployment angle)
//   Servo 1 — CH6 (water deployment angle)
//   Servo 2 — CH7 (air sensor position)
// =============================================================================
void handleServos() {
  controlServo(0, ch5);
  controlServo(1, ch6);
  controlServo(2, ch7);
}

void controlServo(uint8_t num, int chVal) {
  pca9685.setPWM(num, 0, chVal > 1500 ? SERVO_MAX : SERVO_MIN);
}

void moveServosToSafe() {
  for (uint8_t i = 0; i < 3; i++) pca9685.setPWM(i, 0, SERVO_MIN);
}


// =============================================================================
// SOIL TOOL  (CH5)
//   Activates: servo 0 + SOIL_FWD/REV actuator
// =============================================================================
void handleSoilTool() {
  if (ch5 > 1500) {
    tool_soil = true;
    if (!soilRunning) {
      soilRunning = true;
      startSoilForward();
    }
  } else {
    tool_soil = false;
    if (soilRunning) {
      stopSoil();
      retractSoil();
      soilRunning = false;
    }
  }
}


// =============================================================================
// WATER TOOL  (CH6)
//   Activates: servo 1 + WATER_FWD/REV actuator + pump (auto-timed)
// =============================================================================
void handleWaterTool() {
  if (ch6 > 1500) {
    tool_water = true;
    if (!waterRunning) {
      waterRunning = true;
      startWaterForward();   // also starts pump
    }
  } else {
    tool_water = false;
    if (waterRunning) {
      stopWater();
      retractWater();
      stopPump();
      waterRunning = false;
    }
  }
}


// =============================================================================
// AIR TOOL  (CH7)
//   Activates: servo 2 + sets tool_air flag (Pi reads via I2C to start MH-Z19C)
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
// STATUS PACKET
// =============================================================================
void updateStatusPacket() {
  status.tool_water = tool_water;
  status.tool_air   = tool_air;
  status.tool_soil  = tool_soil;
  status.ibus_pulse = ibus_pulse;
}


// =============================================================================
// I2C — Pi reads tool status
// =============================================================================
void onRequest() {
  Wire.write((uint8_t*)&status, sizeof(status));
}

// I2C — receive command from Pi (future: tool overrides, diagnostics)
void onReceive(int bytes) {
  while (Wire.available()) {
    byte cmd = Wire.read();
    Serial.print("Pi cmd: 0x");
    Serial.println(cmd, HEX);
  }
}
