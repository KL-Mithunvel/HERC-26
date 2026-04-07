// mega_sanity.ino — HERC-26 USB Serial Sanity Test Sketch
// =========================================================
// STANDALONE sketch — NOT the rover firmware.
// Flash this ONLY for wiring / USB Serial verification.
// After testing, re-flash rover_mega.ino for normal operation.
//
// What it does:
//   Pushes 9-byte framed status packets over USB Serial (ttyACM0)
//   cycling through 5 known test states every 2 seconds.
//   The Pi-side script (pi_serial_sanity.py) reads the frames and
//   verifies every field against expected values.
//
// The 9-byte frame layout matches rover_mega.ino exactly:
//   byte 0: SYNC1  = 0xAA  \  two-byte magic header
//   byte 1: SYNC2  = 0x55  /
//   byte 2: tool_water    bool
//   byte 3: tool_air      bool
//   byte 4: tool_soil     bool
//   byte 5: ibus_pulse    bool
//   byte 6: movement      uint8  (0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
//   byte 7: pump_running  bool
//   byte 8: failsafe      bool
//
// No motors, no actuators, no PCA9685, no iBUS — USB Serial only.
// Wire: USB cable from Mega to Raspberry Pi.
//
// Compile:  arduino-cli compile --fqbn arduino:avr:mega spanner/serial/mega_sanity
// Upload:   arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 spanner/serial/mega_sanity
// Monitor:  arduino-cli monitor -p /dev/ttyACM0 --config baudrate=115200

#define SYNC1               0xAA
#define SYNC2               0x55
#define STATUS_INTERVAL_MS  100    // push a frame every 100 ms (~10 Hz)
#define CYCLE_MS           2000    // advance to next test state every 2 s

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
// 5 fixed states the Pi script expects in order.
// Sync any changes here with EXPECTED_STATES in pi_serial_sanity.py.
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

uint8_t       stateIndex  = 0;
unsigned long lastChange  = 0;
unsigned long lastFrame   = 0;


// =============================================================================
void setup() {
  Serial.begin(115200);

  applyState(0);
  lastChange = millis();
  lastFrame  = millis();

  Serial.println("============================================");
  Serial.println(" HERC-26  mega_sanity  USB Serial Ready");
  Serial.println(" Port    : /dev/ttyACM0 (USB cable to Pi)");
  Serial.println(" Baud    : 115200");
  Serial.println(" Frame   : 9 bytes (SYNC1 SYNC2 + 7 payload)");
  Serial.println(" Rate    : 10 Hz");
  Serial.println(" Cycle   : 2 s per state");
  Serial.println("============================================");
  printCurrentState();
}


// =============================================================================
void loop() {
  unsigned long now = millis();

  // Advance to next test state every CYCLE_MS
  if (now - lastChange >= CYCLE_MS) {
    stateIndex = (stateIndex + 1) % 5;
    applyState(stateIndex);
    lastChange = now;
    printCurrentState();
  }

  // Push a status frame every STATUS_INTERVAL_MS
  if (now - lastFrame >= STATUS_INTERVAL_MS) {
    lastFrame = now;
    sendStatusFrame();
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
void sendStatusFrame() {
  Serial.write((uint8_t)SYNC1);
  Serial.write((uint8_t)SYNC2);
  Serial.write((uint8_t*)&status, sizeof(status));
}


// =============================================================================
void printCurrentState() {
  Serial.print("[");
  Serial.print(stateIndex);
  Serial.print("] ");
  Serial.println(STATES[stateIndex].label);

  // Print raw payload bytes for cross-reference with pi_serial_sanity.py output
  Serial.print("  payload: ");
  uint8_t* p = (uint8_t*)&status;
  for (int i = 0; i < (int)sizeof(status); i++) {
    if (p[i] < 0x10) Serial.print('0');
    Serial.print(p[i], HEX);
    Serial.print(' ');
  }
  Serial.println();
}
