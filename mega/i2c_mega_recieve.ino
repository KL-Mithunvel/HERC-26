#include <Wire.h>

#define CMD_INCREMENT 0xAA
#define CMD_RESET     0xFF

volatile uint32_t counter = 0;
volatile uint32_t lastSent = 0;
volatile uint8_t lastCmd = 0;
volatile bool eventPending = false;

void setup() {
  Serial.begin(9600);

  Wire.begin(0x08);
  Wire.onReceive(onReceive);
  Wire.onRequest(onRequest);

  Serial.println("Mega I2C Slave Ready");
}

void loop() {
  if (eventPending) {
    Serial.print("Received from RPi: 0x");
    Serial.println(lastCmd, HEX);

    if (lastCmd == CMD_RESET) {
      Serial.println("Action: RESET counter to 0");
    } else if (lastCmd == CMD_INCREMENT) {
      Serial.print("Action: INCREMENT counter to ");
      Serial.println(counter);
    } else {
      Serial.println("Action: UNKNOWN command");
    }

    Serial.print("Sending back: ");
    Serial.println(lastSent);
    Serial.println("----------------------");

    eventPending = false;
  }
}

void onReceive(int) {
  if (!Wire.available()) return;

  lastCmd = Wire.read();

  if (lastCmd == CMD_RESET) {
    counter = 0;
    lastSent = counter;
  } else if (lastCmd == CMD_INCREMENT) {
    counter++;
    lastSent = counter;
  }

  eventPending = true;
}

void onRequest() {
  Wire.write((uint8_t *)&lastSent, sizeof(lastSent));
}
