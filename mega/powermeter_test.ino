#include <ModbusMaster.h>
#include <SoftwareSerial.h>

// RS485 control pins
#define RE_PIN 2
#define DE_PIN 3

// SoftwareSerial for RS485
SoftwareSerial rs485(8, 9); // RX, TX
ModbusMaster node;

// Enable transmit
void preTransmission() {
  digitalWrite(RE_PIN, HIGH);
  digitalWrite(DE_PIN, HIGH);
}

// Enable receive
void postTransmission() {
  digitalWrite(RE_PIN, LOW);
  digitalWrite(DE_PIN, LOW);
}

void setup() {
  Serial.begin(9600);      // Serial Monitor
  rs485.begin(9600);      // PZEM baud rate

  pinMode(RE_PIN, OUTPUT);
  pinMode(DE_PIN, OUTPUT);

  digitalWrite(RE_PIN, LOW);
  digitalWrite(DE_PIN, LOW);

  node.begin(1, rs485);   // Slave ID = 1
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);

  Serial.println("PZEM-017 POWER METER STARTED");
}

void loop() {
  uint8_t result;

  result = node.readInputRegisters(0x0000, 6);

  if (result == node.ku8MBSuccess) {

    float voltage = node.getResponseBuffer(0) / 100.0;
    float current = node.getResponseBuffer(1) / 100.0;

    uint32_t power_raw = ((uint32_t)node.getResponseBuffer(3) << 16) |
                          node.getResponseBuffer(2);
    float power = power_raw / 10.0;

    uint32_t energy_raw = ((uint32_t)node.getResponseBuffer(5) << 16) |
                           node.getResponseBuffer(4);
    float energy = energy_raw;

    Serial.print("Voltage : "); Serial.print(voltage); Serial.println(" V");
    Serial.print("Current : "); Serial.print(current); Serial.println(" A");
    Serial.print("Power   : "); Serial.print(power);   Serial.println(" W");
    Serial.print("Energy  : "); Serial.print(energy);  Serial.println(" Wh");
    Serial.println("--------------------------");
  } 
  else {
    Serial.print("Modbus error: ");
    Serial.println(result);
  }

  delay(1500);
}
