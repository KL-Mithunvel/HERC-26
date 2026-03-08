// tool_controller.ino — HERC-26 Team MOVIS
// Arduino Mega — Tool Control System
//
// Responsibilities:
//   - Read FlySky RC commands via iBUS (Serial1)
//   - Control soil and water actuators (H-bridge direction pins)
//   - Control peristaltic water pump (timed, 5 s)
//   - Signal air sensing activation to Raspberry Pi
//   - Report tool status to Raspberry Pi via I2C (slave 0x08)
//
// I2C packet (4 bytes, sent on onRequest):
//   byte 0: tool_water  (bool)
//   byte 1: tool_air    (bool)
//   byte 2: tool_soil   (bool)
//   byte 3: ibus_pulse  (bool — true when RC signal is valid)
//
// Channel mapping (iBUS, 0-indexed):
//   ch5 (idx 4) → Soil tool
//   ch6 (idx 5) → Water tool
//   ch7 (idx 6) → Air tool
//
// Compile: arduino-cli compile --fqbn arduino:avr:mega mega/tool_controller
// Upload:  arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 mega/tool_controller

#include <IBusBM.h>
#include <Wire.h>

IBusBM ibus;

#define I2C_ADDR 0x08

// ---------------- CHANNELS ----------------
int ch5, ch6, ch7;

// ---------------- STATUS FLAGS ----------------
bool tool_water  = false;
bool tool_air    = false;
bool tool_soil   = false;
bool ibus_pulse  = false;

// ---------------- PUMP ----------------
const int pumpPin  = 3;
const int pumpTime = 5;   // seconds

// ---------------- ACTUATOR PINS ----------------
#define SOIL_FWD  40
#define SOIL_REV  41
#define WATER_FWD 42
#define WATER_REV 43

// ---------------- I2C STATUS PACKET ----------------
struct StatusPacket {
  bool tool_water;
  bool tool_air;
  bool tool_soil;
  bool ibus_pulse;
};
StatusPacket status;

// ---------------- ACTUATOR STATE ----------------
bool soilRunning  = false;
bool waterRunning = false;
unsigned long pumpStart  = 0;
bool pumpRunning  = false;

// =================================================
// SETUP
// =================================================
void setup() {
  Serial.begin(115200);
  ibus.begin(Serial1);

  pinMode(pumpPin,  OUTPUT);
  pinMode(SOIL_FWD, OUTPUT);
  pinMode(SOIL_REV, OUTPUT);
  pinMode(WATER_FWD, OUTPUT);
  pinMode(WATER_REV, OUTPUT);

  Wire.begin(I2C_ADDR);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);

  Serial.println("Mega Tool Controller Ready");
}

// =================================================
// LOOP  (~50 Hz)
// =================================================
void loop() {
  readIBUS();
  handleSoilTool();
  handleWaterTool();
  handleAirTool();
  handlePump();
  updateStatusPacket();
  delay(20);
}

// =================================================
// IBUS READ
// =================================================
void readIBUS() {
  int test = ibus.readChannel(2);
  if (test > 900 && test < 2100) {
    ibus_pulse = true;
    ch5 = ibus.readChannel(4);
    ch6 = ibus.readChannel(5);
    ch7 = ibus.readChannel(6);
  } else {
    ibus_pulse = false;
  }
}

// =================================================
// SOIL TOOL  (CH5)
// =================================================
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

// =================================================
// WATER TOOL  (CH6)
// =================================================
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

// =================================================
// AIR TOOL  (CH7) — Mega only signals Pi; no local actuator
// =================================================
void handleAirTool() {
  tool_air = (ch7 > 1500);
}

// =================================================
// PUMP  (timed, pumpTime seconds)
// =================================================
void startPump() {
  pumpStart   = millis();
  pumpRunning = true;
  digitalWrite(pumpPin, HIGH);
}

void handlePump() {
  if (!pumpRunning) return;
  if (millis() - pumpStart > (unsigned long)pumpTime * 1000UL) {
    stopPump();
  }
}

void stopPump() {
  digitalWrite(pumpPin, LOW);
  pumpRunning = false;
}

// =================================================
// SOIL ACTUATOR
// =================================================
void startSoilForward() {
  digitalWrite(SOIL_FWD, HIGH);
  digitalWrite(SOIL_REV, LOW);
}
void retractSoil() {
  digitalWrite(SOIL_FWD, LOW);
  digitalWrite(SOIL_REV, HIGH);
}
void stopSoil() {
  digitalWrite(SOIL_FWD, LOW);
  digitalWrite(SOIL_REV, LOW);
}

// =================================================
// WATER ACTUATOR
// =================================================
void startWaterForward() {
  digitalWrite(WATER_FWD, HIGH);
  digitalWrite(WATER_REV, LOW);
  startPump();
}
void retractWater() {
  digitalWrite(WATER_FWD, LOW);
  digitalWrite(WATER_REV, HIGH);
}
void stopWater() {
  digitalWrite(WATER_FWD, LOW);
  digitalWrite(WATER_REV, LOW);
}

// =================================================
// UPDATE STATUS PACKET
// =================================================
void updateStatusPacket() {
  status.tool_water  = tool_water;
  status.tool_air    = tool_air;
  status.tool_soil   = tool_soil;
  status.ibus_pulse  = ibus_pulse;
}

// =================================================
// I2C — SEND TO PI  (called on Pi request)
// =================================================
void onRequest() {
  Wire.write((uint8_t*)&status, sizeof(status));
}

// =================================================
// I2C — RECEIVE FROM PI  (debug / future commands)
// =================================================
void onReceive(int bytes) {
  while (Wire.available()) {
    byte cmd = Wire.read();
    Serial.print("Command from RPi: ");
    Serial.println(cmd, HEX);
  }
}
