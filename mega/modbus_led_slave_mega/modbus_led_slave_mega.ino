#include <ModbusRTU.h>

ModbusRTU mb;

constexpr uint8_t SLAVE_ID = 1;

// Holding register addresses (0-based)
constexpr uint16_t REG_LED_CMD   = 0;
constexpr uint16_t REG_LED_STATE = 1;

bool cbWriteLedCmd(TRegister* reg, uint16_t val) {
  // Only accept 0/1
  uint16_t cmd = (val != 0) ? 1 : 0;

  // Mega onboard LED is pin 13
  digitalWrite(LED_BUILTIN, cmd ? HIGH : LOW);

  // Update readback register
  mb.Hreg(REG_LED_STATE, cmd);

  return true;
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.begin(115200);

  mb.begin(&Serial);
  mb.slave(SLAVE_ID);

  // Add holding registers
  mb.addHreg(REG_LED_CMD, 0);
  mb.addHreg(REG_LED_STATE, 0);

  // Attach callback for writes to LED_CMD
  mb.onSetHreg(REG_LED_CMD, cbWriteLedCmd);
}

void loop() {
  mb.task();

  // Optional: keep REG_LED_STATE consistent even if something else changed the LED
  // (not required, but safe)
  uint16_t state = (digitalRead(LED_BUILTIN) == HIGH) ? 1 : 0;
  mb.Hreg(REG_LED_STATE, state);
}
