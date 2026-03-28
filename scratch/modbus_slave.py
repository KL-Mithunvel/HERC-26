"""
scratch/modbus.py — Simple Modbus RTU Slave (test / loopback)

Listens on a serial port and replies to FC=0x03 / FC=0x04 requests with
dummy register values.  Use this to verify RS485 wiring + framing before
connecting the real PZEM-017.

Run on the Pi:
    python3 scratch/modbus.py

Tweak the CONFIG block below — nothing else needs touching.
"""

import time
import serial

try:
    import gpiod
    _GPIOD_OK = True
except ImportError:
    _GPIOD_OK = False

# =============================================================================
# CONFIG — edit these constants only
# =============================================================================

PORT       = "/dev/ttyAMA0"   # serial port
BAUD       = 9600             # baud rate
BYTESIZE   = 8                # data bits  (5 / 6 / 7 / 8)
PARITY     = "N"              # N=None  E=Even  O=Odd  M=Mark  S=Space
STOPBITS   = 2                # stop bits  (1 / 1.5 / 2)
TIMEOUT    = 0.1              # read timeout in seconds

SLAVE_ADDR = 0xF8             # Modbus slave address (248 = 0xF8 matches config.xml)

# RS485 DE/RE direction-control GPIO pin.
# Set to None for plain UART or USB-RS485 dongles that handle direction automatically.
# Set to an integer (e.g. 18) when the MAX485 DE/RE pin is wired to a Pi GPIO.
DE_RE_PIN  = None             # e.g. 18
GPIO_CHIP  = "/dev/gpiochip0" # confirmed via gpiodetect (pinctrl-rp1 = gpiochip0 on this Pi 5)

# Dummy register values returned for every read request.
# 16-bit unsigned integers.  Extend or shrink this list as needed.
# power_meter.py asks for 8 registers starting at 0x0000:
#   [0] voltage ×100 (mV)   e.g. 0x0064 = 100 → 1.00 V
#   [1] current ×100 (mA)
#   [2] power   ×10  (0.1 W)
#   [3..7] energy, status, alarms — leave 0 for test
DUMMY_REGISTERS = [
    0x0064,  # reg 0 — 100  (voltage:  1.00 V  as raw PZEM unit)
    0x0032,  # reg 1 — 50   (current:  0.50 A)
    0x03E8,  # reg 2 — 1000 (power:   100.0 W)
    0x0000,  # reg 3
    0x0000,  # reg 4
    0x0000,  # reg 5
    0x0000,  # reg 6
    0x0000,  # reg 7
]

# =============================================================================
# CRC-16/Modbus  (verbatim from sensor/power_meter.py)
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


def _crc_ok(frame: bytes) -> bool:
    """Return True if the last 2 bytes are valid CRC for the preceding bytes."""
    return _crc16(frame[:-2]) == frame[-2:]


# =============================================================================
# RS485 DE/RE direction helpers
# =============================================================================

_line = None  # gpiod LineRequest handle

def _gpio_setup():
    if DE_RE_PIN is None:
        return
    if not _GPIOD_OK:
        print("[WARN] gpiod not available — DE/RE pin will not be controlled")
        return
    global _line
    chip = gpiod.Chip(GPIO_CHIP)
    config = {DE_RE_PIN: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT)}
    _line = chip.request_lines(consumer="modbus_slave", config=config)
    _rx_mode()

def _tx_mode():
    if _line is not None:
        _line.set_value(DE_RE_PIN, gpiod.line.Value.ACTIVE)
        time.sleep(0.0001)

def _rx_mode():
    if _line is not None:
        _line.set_value(DE_RE_PIN, gpiod.line.Value.INACTIVE)

def _gpio_close():
    if _line is not None:
        _line.release()


# =============================================================================
# Response builders
# =============================================================================

def _build_read_response(start_reg: int, count: int) -> bytes:
    """FC 03/04 response with dummy register values."""
    regs = []
    for i in range(count):
        idx = start_reg + i
        val = DUMMY_REGISTERS[idx] if idx < len(DUMMY_REGISTERS) else 0x0000
        regs.append((val >> 8) & 0xFF)
        regs.append(val & 0xFF)
    body = bytes([SLAVE_ADDR, 0x04, len(regs)] + regs)
    return body + _crc16(body)


def _build_exception(fc: int, code: int) -> bytes:
    """Modbus exception response."""
    body = bytes([SLAVE_ADDR, fc | 0x80, code])
    return body + _crc16(body)


# =============================================================================
# Main loop
# =============================================================================

def _handle(frame: bytes) -> bytes | None:
    """Parse a Modbus RTU request frame and return the response bytes."""
    if len(frame) < 8:
        return None
    if not _crc_ok(frame):
        print(f"  [CRC FAIL] frame={frame.hex(' ')}")
        return None
    addr = frame[0]
    if addr != SLAVE_ADDR:
        print(f"  [SKIP] addr=0x{addr:02X} (not ours)")
        return None

    fc         = frame[1]
    start_reg  = (frame[2] << 8) | frame[3]
    count      = (frame[4] << 8) | frame[5]

    if fc in (0x03, 0x04):
        resp = _build_read_response(start_reg, count)
        return resp
    else:
        print(f"  [UNSUPPORTED FC] 0x{fc:02X}")
        return _build_exception(fc, 0x01)  # illegal function


def run():
    parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                  "O": serial.PARITY_ODD,  "M": serial.PARITY_MARK,
                  "S": serial.PARITY_SPACE}
    stop_map   = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE,
                  2: serial.STOPBITS_TWO}

    ser = serial.Serial(
        port     = PORT,
        baudrate = BAUD,
        bytesize = BYTESIZE,
        parity   = parity_map[PARITY],
        stopbits = stop_map[STOPBITS],
        timeout  = TIMEOUT,
    )
    print(f"Modbus slave 0x{SLAVE_ADDR:02X} on {PORT} "
          f"{BAUD}/{BYTESIZE}{PARITY}{STOPBITS}  (Ctrl+C to stop)")

    _gpio_setup()
    _rx_mode()

    try:
        while True:
            raw = ser.read(256)
            if not raw:
                continue

            print(f"RX ({len(raw):3d}B): {raw.hex(' ')}")

            resp = _handle(raw)
            if resp is None:
                continue

            _tx_mode()
            ser.write(resp)
            ser.flush()
            _rx_mode()

            print(f"TX ({len(resp):3d}B): {resp.hex(' ')}\n")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        _gpio_close()
        ser.close()


if __name__ == "__main__":
    run()
