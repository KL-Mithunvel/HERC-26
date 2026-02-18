#!/usr/bin/env python3
"""
Modbus RTU test script for Raspberry Pi 5.
Communicates with a power meter via UART -> RS485 converter.

Wiring:
  - RPi UART TX -> RS485 module DI
  - RPi UART RX -> RS485 module RO
  - RPi GPIO (DE_RE_PIN) -> RS485 module DE+RE (tied together)
"""

import time
import serial
import gpiod
from gpiod.line import Direction, Value

# â”€â”€ Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SERIAL_PORT = "/dev/ttyAMA0"   # RPi 5 UART  (adjust if needed)
BAUD_RATE   = 9600
DATA_BITS   = serial.EIGHTBITS
STOP_BITS   = serial.STOPBITS_ONE
PARITY      = serial.PARITY_NONE
TIMEOUT     = 1.0              # seconds to wait for response

DE_RE_PIN   = 18                # GPIO pin driving DE+RE on the RS485 module
GPIO_CHIP   = "/dev/gpiochip4" # RPi 5 uses gpiochip4 for user GPIO

DEVICE_ADDR = 0x01             # power meter slave address

# â”€â”€ CRC-16/Modbus â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def crc16_modbus(data: bytes) -> bytes:
    """Return CRC-16/Modbus as 2 bytes (low byte first)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder="little")


# â”€â”€ Build the request frame â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Addr=0x01  Func=0x04  StartReg=0x0000  Quantity=0x0008  + CRC
pdu = bytes([DEVICE_ADDR, 0x04, 0x00, 0x00, 0x00, 0x08])
request = pdu + crc16_modbus(pdu)


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    # Open GPIO line for DE/RE control (HIGH = transmit, LOW = receive)
    request_line = gpiod.request_lines(
        GPIO_CHIP,
        consumer="modbus_test",
        config={
            DE_RE_PIN: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            )
        },
    )

    # Open serial port
    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=DATA_BITS,
        stopbits=STOP_BITS,
        parity=PARITY,
        timeout=TIMEOUT,
    )

    print(f"Port   : {SERIAL_PORT}")
    print(f"Config : {BAUD_RATE} 8N1")
    print(f"Slave  : 0x{DEVICE_ADDR:02X}")
    print(f"TX ({len(request)} bytes): {request.hex(' ')}")

    try:
        # â”€â”€ Transmit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ser.reset_input_buffer()
        request_line.set_value(DE_RE_PIN, Value.ACTIVE)    # enable driver (TX mode)
        ser.write(request)
        ser.flush()
        # Wait for all bits to leave the wire:
        #   bytes * (1 start + 8 data + 2 stop) / baud
        tx_time = len(request) * 11 / BAUD_RATE
        time.sleep(tx_time + 0.005)       # small margin
        request_line.set_value(DE_RE_PIN, Value.INACTIVE)  # back to receive mode

        # â”€â”€ Receive â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Expected response for 8 registers:
        #   addr(1) + func(1) + byte_count(1) + data(16) + crc(2) = 21 bytes
        time.sleep(0.1)                   # give the meter a moment
        response = ser.read(256)          # read whatever comes back

        if not response:
            print("\nâš   No response received (timeout).")
            return

        print(f"RX ({len(response)} bytes): {response.hex(' ')}")

        # â”€â”€ Parse â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if len(response) < 5:
            print("Response too short to parse.")
            return

        rx_addr = response[0]
        rx_func = response[1]

        # Check for Modbus exception (function code has high bit set)
        if rx_func & 0x80:
            exc_code = response[2]
            print(f"\nModbus exception â€” function 0x{rx_func:02X}, "
                  f"exception code 0x{exc_code:02X}")
            return

        byte_count = response[2]
        data_bytes = response[3 : 3 + byte_count]

        # Verify CRC
        payload = response[:-2]
        expected_crc = crc16_modbus(payload)
        actual_crc = response[-2:]
        crc_ok = expected_crc == actual_crc

        print(f"\nSlave addr : 0x{rx_addr:02X}")
        print(f"Function   : 0x{rx_func:02X}")
        print(f"Byte count : {byte_count}")
        print(f"CRC check  : {'OK' if crc_ok else 'FAIL'}")

        # Print each 16-bit register value
        print(f"\nRegisters (0x0000 â€“ 0x0007):")
        for i in range(0, len(data_bytes) - 1, 2):
            reg_val = (data_bytes[i] << 8) | data_bytes[i + 1]
            reg_num = i // 2
            print(f"  [0x{reg_num:04X}]  0x{reg_val:04X}  ({reg_val})")

    finally:
        request_line.set_value(DE_RE_PIN, Value.INACTIVE)
        ser.close()
        request_line.release()


if __name__ == "__main__":
    main()#!/usr/bin/env python3
"""
Modbus RTU test script for Raspberry Pi 5.
Communicates with a power meter via UART -> RS485 converter.

Wiring:
  - RPi UART TX -> RS485 module DI
  - RPi UART RX -> RS485 module RO
  - RPi GPIO (DE_RE_PIN) -> RS485 module DE+RE (tied together)
"""

import time
import serial
import gpiod
from gpiod.line import Direction, Value

# â”€â”€ Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SERIAL_PORT = "/dev/ttyAMA0"   # RPi 5 UART  (adjust if needed)
BAUD_RATE   = 9600
DATA_BITS   = serial.EIGHTBITS
STOP_BITS   = serial.STOPBITS_TWO
PARITY      = serial.PARITY_NONE
TIMEOUT     = 1.0              # seconds to wait for response

DE_RE_PIN   = 4                # GPIO pin driving DE+RE on the RS485 module
GPIO_CHIP   = "/dev/gpiochip4" # RPi 5 uses gpiochip4 for user GPIO

DEVICE_ADDR = 0x01             # power meter slave address


# â”€â”€ CRC-16/Modbus â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def crc16_modbus(data: bytes) -> bytes:
    """Return CRC-16/Modbus as 2 bytes (low byte first)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder="little")


# â”€â”€ Build the request frame â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Addr=0x01  Func=0x04  StartReg=0x0000  Quantity=0x0008  + CRC
pdu = bytes([DEVICE_ADDR, 0x04, 0x00, 0x00, 0x00, 0x08])
request = pdu + crc16_modbus(pdu)


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    # Open GPIO line for DE/RE control (HIGH = transmit, LOW = receive)
    request_line = gpiod.request_lines(
        GPIO_CHIP,
        consumer="modbus_test",
        config={
            DE_RE_PIN: gpiod.LineSettings(
                direction=Direction.OUTPUT,
                output_value=Value.INACTIVE,
            )
        },
    )

    # Open serial port
    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=BAUD_RATE,
        bytesize=DATA_BITS,
        stopbits=STOP_BITS,
        parity=PARITY,
        timeout=TIMEOUT,
    )

    print(f"Port   : {SERIAL_PORT}")
    print(f"Config : {BAUD_RATE} 8N2")
    print(f"Slave  : 0x{DEVICE_ADDR:02X}")
    print(f"TX ({len(request)} bytes): {request.hex(' ')}")

    try:
        # â”€â”€ Transmit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ser.reset_input_buffer()
        request_line.set_value(DE_RE_PIN, Value.ACTIVE)    # enable driver (TX mode)
        ser.write(request)
        ser.flush()
        # Wait for all bits to leave the wire:
        #   bytes * (1 start + 8 data + 2 stop) / baud
        tx_time = len(request) * 11 / BAUD_RATE
        time.sleep(tx_time + 0.005)       # small margin
        request_line.set_value(DE_RE_PIN, Value.INACTIVE)  # back to receive mode

        # â”€â”€ Receive â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Expected response for 8 registers:
        #   addr(1) + func(1) + byte_count(1) + data(16) + crc(2) = 21 bytes
        time.sleep(0.1)                   # give the meter a moment
        response = ser.read(256)          # read whatever comes back

        if not response:
            print("\nâš   No response received (timeout).")
            return

        print(f"RX ({len(response)} bytes): {response.hex(' ')}")

        # â”€â”€ Parse â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if len(response) < 5:
            print("Response too short to parse.")
            return

        rx_addr = response[0]
        rx_func = response[1]

        # Check for Modbus exception (function code has high bit set)
        if rx_func & 0x80:
            exc_code = response[2]
            print(f"\nModbus exception â€” function 0x{rx_func:02X}, "
                  f"exception code 0x{exc_code:02X}")
            return

        byte_count = response[2]
        data_bytes = response[3 : 3 + byte_count]

        # Verify CRC
        payload = response[:-2]
        expected_crc = crc16_modbus(payload)
        actual_crc = response[-2:]
        crc_ok = expected_crc == actual_crc

        print(f"\nSlave addr : 0x{rx_addr:02X}")
        print(f"Function   : 0x{rx_func:02X}")
        print(f"Byte count : {byte_count}")
        print(f"CRC check  : {'OK' if crc_ok else 'FAIL'}")

        # Print each 16-bit register value
        print(f"\nRegisters (0x0000 â€“ 0x0007):")
        for i in range(0, len(data_bytes) - 1, 2):
            reg_val = (data_bytes[i] << 8) | data_bytes[i + 1]
            reg_num = i // 2
            print(f"  [0x{reg_num:04X}]  0x{reg_val:04X}  ({reg_val})")

    finally:
        request_line.set_value(DE_RE_PIN, Value.INACTIVE)
        ser.close()
        request_line.release()


if __name__ == "__main__":
    main()
