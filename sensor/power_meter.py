"""
sensor/power_meter.py — PZEM-003/017 DC Power Meter driver.

Communicates via RS485 Modbus RTU (UART + DE/RE direction pin via gpiod v2).

Interface
─────────
    setup(port, baudrate, de_re_pin, modbus_address, gpio_chip)
    read()   → {"voltage_v": float, "current_a": float, "power_w": float}
    close()

Scaling (PZEM-003 datasheet)
─────────────────────────────
    Voltage : reg[0x0000] × 0.01          → V
    Current : reg[0x0001] × 0.01          → A
    Power   : (reg[0x0003] << 16 | reg[0x0002]) × 0.1  → W  (32-bit value)

Serial config: 9600 baud, 8 data bits, no parity, 2 stop bits (8N2).
GPIO:          DE/RE pin controlled via gpiod v2 (libgpiod, python3-libgpiod via apt).
               HIGH = transmit, LOW = receive.
"""

import time
import serial

try:
    import gpiod
    from gpiod.line import Direction, Value
    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PowerSensorSetupError(Exception):
    pass

class PowerSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

_ser       = None
_chip      = None
_req       = None
_de_pin    = None
_modbus    = None
_connected = False


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _crc16(data: bytes) -> bytes:
    """CRC-16/Modbus — returns 2 bytes, low byte first."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder="little")


def _gpio_open(chip_path: str, pin: int):
    """
    Open GPIO chip and claim the DE/RE pin as output, starting LOW (receive mode).
    Returns (chip, request).  Raises PowerSensorSetupError on failure.
    """
    if not _GPIOD_AVAILABLE:
        raise PowerSensorSetupError(
            "gpiod not available — install python3-libgpiod via apt"
        )
    try:
        chip = gpiod.Chip(chip_path)
        req = chip.request_lines(
            consumer="power-meter-dere",
            config={
                pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE,   # start LOW = receive mode
                )
            },
        )
        return chip, req
    except Exception as e:
        raise PowerSensorSetupError(
            f"GPIO open failed (chip={chip_path}, pin={pin}): {e}"
        )


def _gpio_tx():
    """Switch DE/RE HIGH — enable RS485 transmit."""
    _req.set_value(_de_pin, Value.ACTIVE)


def _gpio_rx():
    """Switch DE/RE LOW — enable RS485 receive."""
    _req.set_value(_de_pin, Value.INACTIVE)


def _gpio_close():
    global _chip, _req
    if _req is not None:
        try:
            _req.release()
        except Exception:
            pass
        _req = None
    if _chip is not None:
        try:
            _chip.close()
        except Exception:
            pass
        _chip = None


def _transact(request: bytes, expected_bytes: int = 21) -> bytes:
    """
    Transmit a Modbus request frame and return the raw response bytes.

    Handles DE/RE toggling:
      1. Pull DE/RE HIGH → transmit
      2. Write frame + flush
      3. Wait for all bits to leave the wire (calculated from baud rate)
      4. Pull DE/RE LOW → receive
      5. Read response

    Raises PowerSensorReadError if no response arrives within the serial timeout.
    """
    _ser.reset_input_buffer()
    _ser.reset_output_buffer()
    _gpio_tx()
    time.sleep(0.005)
    _ser.write(request)
    _ser.flush()

    # Wait for all bits to leave the wire: bytes × (1 start + 8 data + 2 stop) / baud
    tx_time = len(request) * 11 / _ser.baudrate
    time.sleep(tx_time + 0.015)   # small margin

    _gpio_rx()
    time.sleep(0.1)              # give meter time to compose its response

    response = _ser.read(expected_bytes)

    if not response:
        raise PowerSensorReadError("No response from power meter (timeout)")

    return response


def _read_registers() -> list:
    """
    Send Modbus FC 0x04: read 8 input registers starting at 0x0000.

    Returns a list of 8 int register values (raw, unscaled).
    Raises PowerSensorReadError on any protocol or CRC error.

    Expected response (21 bytes):
        addr(1) + func(1) + byte_count(1) + data(16) + crc(2)
    """
    pdu     = bytes([_modbus, 0x04, 0x00, 0x00, 0x00, 0x08])
    request = pdu + _crc16(pdu)

    response = _transact(request, expected_bytes=21)

    if len(response) < 5:
        raise PowerSensorReadError(
            f"Response too short: {len(response)} bytes"
        )

    if response[1] & 0x80:
        raise PowerSensorReadError(
            f"Modbus exception: func=0x{response[1]:02X}, code=0x{response[2]:02X}"
        )

    byte_count = response[2]
    min_len    = 3 + byte_count + 2

    if len(response) < min_len:
        raise PowerSensorReadError(
            f"Truncated response: expected {min_len} bytes, got {len(response)}"
        )

    # CRC covers everything except the trailing 2 CRC bytes
    payload      = response[:3 + byte_count]
    expected_crc = _crc16(payload)
    actual_crc   = bytes(response[3 + byte_count : 3 + byte_count + 2])
    if expected_crc != actual_crc:
        raise PowerSensorReadError(
            f"CRC mismatch: expected {expected_crc.hex()}, got {actual_crc.hex()}"
        )

    # Unpack big-endian 16-bit registers from the data section
    data = response[3 : 3 + byte_count]
    regs = []
    for i in range(0, len(data) - 1, 2):
        regs.append((data[i] << 8) | data[i + 1])

    if len(regs) < 4:
        raise PowerSensorReadError(
            f"Not enough registers: got {len(regs)}, need at least 4"
        )

    return regs


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(
    port: str           = "/dev/ttyAMA0",
    baudrate: int       = 9600,
    de_re_pin: int      = 18,
    modbus_address: int = 1,
    gpio_chip: str      = "/dev/gpiochip0",
):
    """
    Open the serial port and claim the DE/RE GPIO pin.
    All parameters come from config.xml at startup.

    Raises PowerSensorSetupError on failure.
    """
    global _ser, _chip, _req, _de_pin, _modbus, _connected

    _de_pin = de_re_pin
    _modbus = modbus_address

    _chip, _req = _gpio_open(gpio_chip, de_re_pin)

    try:
        _ser = serial.Serial(
            port     = port,
            baudrate = baudrate,
            bytesize = serial.EIGHTBITS,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_TWO,
            timeout  = 1.0,
        )
    except Exception as e:
        _gpio_close()
        raise PowerSensorSetupError(f"Serial open failed on {port}: {e}")

    # Probe the meter — fail fast if unreachable so real_stack marks it offline
    try:
        _read_registers()
    except PowerSensorReadError as e:
        _ser.close()
        _gpio_close()
        raise PowerSensorSetupError(f"Meter probe failed — not responding: {e}")

    _connected = True


def read():
    """
    Return power meter readings.

    Returns:
        {"voltage_v": float, "current_a": float, "power_w": float}

    Scaling from PZEM-003 datasheet:
        voltage_v = reg[0] × 0.01
        current_a = reg[1] × 0.01
        power_w   = (reg[3] << 16 | reg[2]) × 0.1   ← 32-bit combined value

    Raises PowerSensorReadError if the meter is offline or the response is invalid.
    """
    if not _connected or _ser is None:
        raise PowerSensorReadError("Power meter not initialized")

    regs = _read_registers()

    voltage_v = round(regs[0] * 0.01, 2)
    current_a = round(regs[1] * 0.01, 2)
    power_raw = (regs[3] << 16) | regs[2]    # high word in reg[3], low word in reg[2]
    power_w   = round(power_raw * 0.1, 1)

    return {
        "voltage_v": voltage_v,
        "current_a": current_a,
        "power_w":   power_w,
    }


def close():
    """Close the serial port and release the GPIO line."""
    global _ser, _connected
    _connected = False
    if _ser is not None and _ser.is_open:
        try:
            _ser.close()
        except Exception:
            pass
    _ser = None
    _gpio_close()


# =============================================================================
# MAIN — run directly on Pi to verify sensor
# =============================================================================

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("PZEM-003/017 Power Meter — Live Readings (every 2 seconds)")
    print("=" * 60)

    try:
        print("\nInitializing...")
        setup()
        print("Meter initialized OK")
    except PowerSensorSetupError as e:
        print(f"Setup failed: {e}")
        print("\nChecks:")
        print("  - RS485 module powered (5V, min 100 mA)")
        print("  - TX/RX wired correctly (RPi TX → RS485 DI, RPi RX → RS485 RO)")
        print("  - DE/RE pin matches config.xml power_de_re_pin")
        print("  - Serial port matches config.xml power_port")
        print("  - Meter Modbus address matches config.xml power_modbus_address")
        sys.exit(1)

    print("\nPress Ctrl+C to stop\n")

    try:
        while True:
            data = read()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"[{ts}]  "
                f"{data['voltage_v']:7.2f} V   "
                f"{data['current_a']:6.2f} A   "
                f"{data['power_w']:8.1f} W"
            )
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopping")
    except PowerSensorReadError as e:
        print(f"\nRead error: {e}")
    finally:
        close()
        print("Meter closed")
        print("=" * 60)
