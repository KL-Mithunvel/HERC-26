"""
scripts/configure_ph_sensor.py — One-time S-pH-01 configuration.

Run this ONCE on the Pi to:
  1. Change the pH sensor Modbus slave address: 1 → 2
  2. Change the pH sensor stop bits: 1 → 2  (to match the PZEM-017 on the shared bus)

HOW TO USE
──────────
  1. Disconnect the PZEM-017 A+/B− wires from the RS485 bus (pH sensor only).
  2. Run:  python3 scripts/configure_ph_sensor.py
  3. Follow the prompts.
  4. Power-cycle ONLY the pH sensor when instructed.
  5. Reconnect the PZEM-017.

After this script completes successfully the pH sensor will be at address 2, 8N2.
"""

import time
import sys
import serial

try:
    import gpiod
    from gpiod.line import Direction, Value
    _GPIOD = True
except ImportError:
    _GPIOD = False


# ── Adjust these to match your wiring ────────────────────────────────────────
PORT      = "/dev/ttyAMA0"    # primary UART — GPIO 14 (TX) / GPIO 15 (RX)
BAUD      = 9600
DE_PIN    = 12                # GPIO 12 → MAX485 DE+RE (tied together)
GPIO_CHIP = "/dev/gpiochip4"  # Pi 5 → gpiochip4 | Pi 4 → gpiochip0
# ─────────────────────────────────────────────────────────────────────────────

OLD_ADDR  = 0x01   # factory default pH sensor address
NEW_ADDR  = 0x02   # target address (must not clash with PZEM-017 = 0x01)


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def build_write(slave: int, reg: int, value: int) -> bytes:
    """Build a Modbus FC 0x06 Write Single Register frame."""
    pdu = bytes([slave, 0x06, reg >> 8, reg & 0xFF, value >> 8, value & 0xFF])
    return pdu + crc16(pdu)


def transact(ser, req, de_pin, frame: bytes) -> bytes:
    ser.reset_input_buffer()

    req.set_value(de_pin, Value.ACTIVE)      # DE/RE HIGH = transmit
    ser.write(frame)
    ser.flush()
    tx_time = len(frame) * 11 / ser.baudrate
    time.sleep(tx_time + 0.005)
    req.set_value(de_pin, Value.INACTIVE)    # DE/RE LOW  = receive

    time.sleep(0.1)
    return ser.read(64)


def verify_crc(response: bytes) -> bool:
    if len(response) < 4:
        return False
    payload = response[:-2]
    return crc16(payload) == bytes(response[-2:])


def open_gpio():
    if not _GPIOD:
        print("ERROR: gpiod not available. Install python3-libgpiod via apt.")
        sys.exit(1)
    chip = gpiod.Chip(GPIO_CHIP)
    req  = chip.request_lines(
        consumer="ph-config",
        config={DE_PIN: gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.INACTIVE,
        )},
    )
    return chip, req


def send_write(ser, req, slave, reg, value, label):
    frame    = build_write(slave, reg, value)
    response = transact(ser, req, DE_PIN, frame)

    if not response:
        print(f"  ✗ {label}: no response (check wiring, power, address)")
        return False

    if not verify_crc(response):
        print(f"  ✗ {label}: CRC mismatch in response")
        return False

    # FC 0x06 success: slave echoes the request frame exactly
    if response[0] == slave and response[1] == 0x06:
        print(f"  ✓ {label}: OK")
        return True

    if response[1] & 0x80:
        print(f"  ✗ {label}: Modbus exception code 0x{response[2]:02X}")
        return False

    print(f"  ✗ {label}: unexpected response: {response.hex(' ')}")
    return False


def main():
    print("=" * 60)
    print("S-pH-01 One-Time Configuration Script")
    print("=" * 60)
    print(f"\nPort     : {PORT}  ({BAUD} baud, 8N1)")
    print(f"DE/RE pin: GPIO {DE_PIN}  ({GPIO_CHIP})")
    print(f"Old addr : {OLD_ADDR}  →  New addr : {NEW_ADDR}")
    print()
    input("Press Enter when ONLY the pH sensor is connected to the RS485 bus...")

    chip, req = open_gpio()

    # Open serial at current pH settings: 9600 8N1
    ser = serial.Serial(
        port=PORT, baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,   # pH sensor factory default = 1 stop bit
        timeout=1.0,
    )

    print("\nStep 1 — Verifying sensor is responding at address 1 ...")
    # Quick read of register 0x0001 (pH) to confirm sensor is alive
    pdu   = bytes([OLD_ADDR, 0x04, 0x00, 0x01, 0x00, 0x01])
    probe = pdu + crc16(pdu)
    resp  = transact(ser, req, DE_PIN, probe)
    if not resp:
        print("  ✗ No response — check wiring, power, and that ONLY the pH sensor is connected.")
        ser.close(); req.release(); chip.close()
        sys.exit(1)
    print("  ✓ Sensor responding")

    print("\nStep 2 — Writing new settings (still at address 1, 8N1) ...")

    # Register 0x0200: slave address → 2
    ok1 = send_write(ser, req, OLD_ADDR, 0x0200, NEW_ADDR,
                     f"Set slave address {OLD_ADDR} → {NEW_ADDR}")

    # Register 0x0205: stop bits → 1  (0 = 1 stop bit, 1 = 2 stop bits)
    ok2 = send_write(ser, req, OLD_ADDR, 0x0205, 0x0001,
                     "Set stop bits 1 → 2")

    ser.close()
    req.release()
    chip.close()

    if not (ok1 and ok2):
        print("\n✗ One or more writes failed. Do NOT power-cycle yet. Fix the error and re-run.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Both settings written successfully.")
    print(">>> NOW power-cycle (unplug/replug) the pH sensor. <<<")
    print("=" * 60)
    input("\nPress Enter after power-cycling the pH sensor to verify...")

    print("\nStep 3 — Verifying new settings (address 2, 8N2) ...")

    # Reopen serial at new settings: 8N2
    chip2, req2 = open_gpio()
    ser2 = serial.Serial(
        port=PORT, baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO,
        timeout=1.0,
    )

    pdu2  = bytes([NEW_ADDR, 0x04, 0x00, 0x01, 0x00, 0x01])
    probe2 = pdu2 + crc16(pdu2)
    resp2  = transact(ser2, req2, DE_PIN, probe2)

    if resp2 and verify_crc(resp2) and resp2[0] == NEW_ADDR:
        raw_ph = (resp2[3] << 8) | resp2[4]
        ph     = raw_ph / 100.0
        print(f"  ✓ Sensor responding at address {NEW_ADDR}, 8N2")
        print(f"  Current pH reading: {ph:.2f}")
        print("\n✓ Configuration complete. Reconnect the PZEM-017 to the bus.")
    else:
        raw = resp2.hex(' ') if resp2 else "(no response)"
        print(f"  ✗ Verification failed. Response: {raw}")
        print("  Check that you actually power-cycled the sensor.")

    ser2.close()
    req2.release()
    chip2.close()


if __name__ == "__main__":
    main()