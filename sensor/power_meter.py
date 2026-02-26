import os
import time
from serial import Serial


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PowerSensorSetupError(Exception):
    pass

class PowerSensorReadError(Exception):
    pass


# =============================================================================
# GPIO SYSFS HELPERS (internal)
# =============================================================================

def _gpio_export(pin):
    if not os.path.exists(f'/sys/class/gpio/gpio{pin}'):
        with open('/sys/class/gpio/export', 'w') as f:
            f.write(str(pin))
        time.sleep(0.1)

def _gpio_set_direction(pin, direction):
    with open(f'/sys/class/gpio/gpio{pin}/direction', 'w') as f:
        f.write(direction)

def _gpio_write(pin, value):
    with open(f'/sys/class/gpio/gpio{pin}/value', 'w') as f:
        f.write(str(value))

def _gpio_cleanup(pin):
    if os.path.exists(f'/sys/class/gpio/gpio{pin}'):
        with open('/sys/class/gpio/unexport', 'w') as f:
            f.write(str(pin))


# =============================================================================
# MODBUS RTU HELPERS (internal)
# =============================================================================

def _crc16(data):
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

_ser = None
_de_re_pin = None
_modbus_address = 1
_connected = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(port="/dev/ttyAMA10", baudrate=9600, de_re_pin=17, modbus_address=1):
    """
    Initialize RS485 serial and DE/RE GPIO for PZEM-017.
    Port, baudrate, GPIO pin, and Modbus address come from config.xml at startup.
    """
    global _ser, _de_re_pin, _modbus_address, _connected
    _de_re_pin = de_re_pin
    _modbus_address = modbus_address

    try:
        _gpio_export(_de_re_pin)
        _gpio_set_direction(_de_re_pin, 'out')
        _gpio_write(_de_re_pin, 0)  # RX mode
    except Exception as e:
        raise PowerSensorSetupError(f"GPIO setup failed for pin {de_re_pin}: {e}")

    try:
        _ser = Serial(port, baudrate, timeout=1)
    except Exception as e:
        _gpio_cleanup(_de_re_pin)
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
        _gpio_write(_de_re_pin, 1)  # TX mode
        time.sleep(0.01)
        _ser.write(request)
        _ser.flush()
        time.sleep(0.01)
        _gpio_write(_de_re_pin, 0)  # RX mode
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
    if _de_re_pin is not None:
        _gpio_cleanup(_de_re_pin)
    _ser = None
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
