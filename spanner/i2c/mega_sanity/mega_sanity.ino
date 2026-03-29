// mega_sanity.ino — HERC-26 I2C Sanity Test Sketch
// ====================================================
// STANDALONE sketch — NOT the rover firmware.
// Flash this ONLY for wiring / I2C verification.
// After testing, re-flash rover_mega.ino for normal operation.
//
// What it does:
//   Sits as I2C slave at 0x08 and cycles through 5 known test states
//   every 2 seconds. Each state sends a predictable 7-byte packet so
//   the Pi-side script (pi_i2c_sanity.py) can verify every field.
//
// The 7-byte packet layout matches rover_mega.ino StatusPacket exactly:
//   byte 0: tool_water    bool
//   byte 1: tool_air      bool
//   byte 2: tool_soil     bool
//   byte 3: ibus_pulse    bool
//   byte 4: movement      uint8  (0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
//   byte 5: pump_running  bool
//   byte 6: failsafe      bool
//
// No motors, no actuators, no PCA9685, no iBUS — Wire.h only.
//
// Compile:  arduino-cli compile --fqbn arduino:avr:mega spanner/i2c/mega_sanity
// Upload:   arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 spanner/i2c/mega_sanity
// Monitor:  arduino-cli monitor -p /dev/ttyACM0 --config baudrate=115200

#include <Wire.h>

#define I2C_SLAVE_ADDR  0x08
#define CYCLE_MS        2000   // ms between state changes

// Movement codes — must match rover_mega.ino
#define MOV_STOP   0
#define MOV_FWD    1
#define MOV_BACK   2
#define MOV_LEFT   3
#define MOV_RIGHT  4

// ── Packet struct — packed, identical layout to rover_mega.ino ───────────────
struct __attribute__((packed)) StatusPacket {
  bool    tool_water;
  bool    tool_air;
  bool    tool_soil;
  bool    ibus_pulse;
  uint8_t movement;
  bool    pump_running;
  bool    failsafe;
};

StatusPacket status;

// ── Test state table ─────────────────────────────────────────────────────────
// 5 fixed states Pi script expects to see in order.
// Sync any changes here with EXPECTED_STATES in pi_i2c_sanity.py.
struct TestState {
  bool    tool_water;
  bool    tool_air;
  bool    tool_soil;
  bool    ibus_pulse;
  uint8_t movement;
  bool    pump_running;
  bool    failsafe;
  const char* label;
};

const TestState STATES[5] = {
  //  water   air     soil    ibus    movement   pump    failsafe  label
  {  false,  false,  false,  false,  MOV_STOP,  false,  true,   "STATE 0 | all OFF  | failsafe ON"  },
  {  true,   false,  false,  true,   MOV_FWD,   false,  false,  "STATE 1 | water ON | FWD"          },
  {  false,  true,   false,  true,   MOV_BACK,  false,  false,  "STATE 2 | air ON   | BACK"         },
  {  false,  false,  true,   true,   MOV_LEFT,  true,   false,  "STATE 3 | soil ON  | pump | LEFT"  },
  {  true,   true,   true,   true,   MOV_RIGHT, true,   false,  "STATE 4 | all ON   | pump | RIGHT" },
};

uint8_t       stateIndex = 0;
unsigned long lastChange = 0;


// =============================================================================
void setup() {
  Serial.begin(115200);

  Wire.begin(I2C_SLAVE_ADDR);
  Wire.onRequest(onRequest);

  applyState(0);
  lastChange = millis();

  Serial.println("============================================");
  Serial.println(" HERC-26  mega_sanity  I2C Slave Ready");
  Serial.println(" Address : 0x08");
  Serial.println(" Packet  : 7 bytes");
  Serial.println(" Cycle   : 2 s per state");
  Serial.println("============================================");
  printCurrentState();
}


// =============================================================================
void loop() {
  if (millis() - lastChange >= CYCLE_MS) {
    stateIndex = (stateIndex + 1) % 5;
    applyState(stateIndex);
    lastChange = millis();
    printCurrentState();
  }
}


// =============================================================================
void applyState(uint8_t s) {
  status.tool_water   = STATES[s].tool_water;
  status.tool_air     = STATES[s].tool_air;
  status.tool_soil    = STATES[s].tool_soil;
  status.ibus_pulse   = STATES[s].ibus_pulse;
  status.movement     = STATES[s].movement;
  status.pump_running = STATES[s].pump_running;
  status.failsafe     = STATES[s].failsafe;
}


// =============================================================================
void onRequest() {
  // Pi reads the full 7-byte packet on every request
  Wire.write((uint8_t*)&status, sizeof(status));
}


// =============================================================================
void printCurrentState() {
  Serial.print("[");
  Serial.print(stateIndex);
  Serial.print("] ");
  Serial.println(STATES[stateIndex].label);

  // Print raw bytes for cross-reference with pi_i2c_sanity.py output
  Serial.print("  raw: ");
  uint8_t* p = (uint8_t*)&status;
  for (int i = 0; i < (int)sizeof(status); i++) {
    if (p[i] < 0x10) Serial.print('0');
    Serial.print(p[i], HEX);
    Serial.print(' ');
  }
  Serial.println();
}
