import time
from serial import Serial

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
# GPIO HELPERS (internal — libgpiod v2 ABI)
#
# Abstracted because the request_lines() call is too verbose to repeat inline.
# _gpio_tx() / _gpio_rx() are thin semantic wrappers kept here so read() stays
# readable as a Modbus flow, not a GPIO tutorial.
# =============================================================================

_gpio_chip    = None   # gpiod.Chip handle
_gpio_request = None   # gpiod line request handle
_de_re_pin    = None   # pin number (int), set in setup()


def _gpio_open(chip_path: str, pin: int) -> None:
    """
    Open the GPIO chip and request the DE/RE line as an output, initially
    LOW (RX mode). Stores handles in module-level _gpio_chip / _gpio_request.

    Raises PowerSensorSetupError if gpiod is unavailable or chip open fails.

    # PLACEHOLDER: add Pi-model auto-detection here if gpio_chip needs to be
    # resolved automatically (e.g. probe /dev/gpiochip0..4 for the right chip).
    # For now the caller passes the chip path explicitly from config.xml.
    """
    global _gpio_chip, _gpio_request

    if not _GPIOD_AVAILABLE:
        raise PowerSensorSetupError(
            "gpiod not available — install python3-libgpiod via apt"
        )

    try:
        _gpio_chip = gpiod.Chip(chip_path)
        _gpio_request = _gpio_chip.request_lines(
            consumer="herc26-power-de-re",
            config={
                pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE,   # LOW = RX mode at startup
                )
            },
        )
    except Exception as e:
        raise PowerSensorSetupError(
            f"GPIO open failed (chip={chip_path}, pin={pin}): {e}"
        )


def _gpio_tx() -> None:
    """Drive DE/RE HIGH — enables RS485 transmit mode."""
    _gpio_request.set_value(_de_re_pin, Value.ACTIVE)


def _gpio_rx() -> None:
    """Drive DE/RE LOW — enables RS485 receive mode."""
    _gpio_request.set_value(_de_re_pin, Value.INACTIVE)


def _gpio_close() -> None:
    """Release the GPIO line request and close the chip handle."""
    global _gpio_chip, _gpio_request
    if _gpio_request is not None:
        try:
            _gpio_request.release()
        except Exception:
            pass
        _gpio_request = None
    if _gpio_chip is not None:
        try:
            _gpio_chip.close()
        except Exception:
            pass
        _gpio_chip = None


# =============================================================================
# MODBUS RTU HELPERS (internal)
# =============================================================================

def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


# =============================================================================
# MODULE STATE
# =============================================================================

_ser            = None
_modbus_address = 1
_connected      = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(port="/dev/ttyAMA10", baudrate=9600, de_re_pin=17, modbus_address=1,
          gpio_chip="/dev/gpiochip4"):
    """
    Initialize RS485 serial and DE/RE GPIO for PZEM-017.
    All parameters come from config.xml at startup — do not hardcode here.

    gpio_chip: "/dev/gpiochip4" for Raspberry Pi 5 (default)
               "/dev/gpiochip0" for Raspberry Pi 4 and earlier
    """
    global _ser, _de_re_pin, _modbus_address, _connected

    _de_re_pin      = de_re_pin
    _modbus_address = modbus_address

    _gpio_open(gpio_chip, de_re_pin)   # raises PowerSensorSetupError on failure

    try:
        _ser = Serial(port, baudrate, timeout=1)
    except Exception as e:
        _gpio_close()
        raise PowerSensorSetupError(f"Serial open failed on {port}: {e}")

    _connected = True


def read():
    """
    Read voltage, current, and power from PZEM-017 via Modbus RTU FC04.
    Returns {"voltage_v": float, "current_a": float, "power_w": float}.
    """
    if not _connected or _ser is None:
        raise PowerSensorReadError("Power meter not connected")

    # Modbus RTU FC04: read 4 input registers from 0x0000
    request = bytearray([_modbus_address, 0x04, 0x00, 0x00, 0x00, 0x04])
    crc = _crc16(request)
    request.append(crc & 0xFF)
    request.append((crc >> 8) & 0xFF)

    try:
        _ser.reset_input_buffer()
        _ser.reset_output_buffer()
        _gpio_tx()
        time.sleep(0.01)
        _ser.write(request)
        _ser.flush()
        time.sleep(0.01)
        _gpio_rx()
        time.sleep(0.1)
        # addr(1) + FC(1) + byte_count(1) + 4 regs × 2 bytes(8) + CRC(2) = 13
        response = _ser.read(13)
    except Exception as e:
        raise PowerSensorReadError(f"Serial communication failed: {e}")

    if len(response) != 13:
        raise PowerSensorReadError(f"Invalid response length: {len(response)}")

    crc_calc = _crc16(response[:-2])
    crc_recv = response[-2] | (response[-1] << 8)
    if crc_calc != crc_recv:
        raise PowerSensorReadError("CRC mismatch")

    # Parse registers (big-endian uint16)
    voltage_v  = ((response[3] << 8) | response[4])  / 100.0  # 0.01 V resolution
    current_a  = ((response[5] << 8) | response[6])  / 100.0  # 0.01 A resolution
    power_low  =  (response[7] << 8) | response[8]
    power_high =  (response[9] << 8) | response[10]
    power_w    = ((power_high << 16) | power_low)    / 10.0   # 0.1 W resolution

    return {
        "voltage_v": round(voltage_v, 2),
        "current_a": round(current_a, 2),
        "power_w":   round(power_w,   1),
    }


def close():
    global _ser, _connected
    if _ser is not None and _ser.is_open:
        _ser.close()
    _gpio_close()
    _ser       = None
    _connected = False


# =============================================================================
# MAIN — run directly on Pi to verify sensor
# =============================================================================

if __name__ == "__main__":
    setup()
    try:
        while True:
            print(read())
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()
