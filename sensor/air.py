#!/usr/bin/env python3

import serial
import time
import sys

# =============================================================================
# EXCEPTIONS
# =============================================================================

class MHZ19CSetupError(Exception):
    pass

class MHZ19CReadError(Exception):
    pass


# =============================================================================
# GLOBAL CONFIG
# =============================================================================

PORT = "/dev/ttyAMA0"   # GPIO UART
BAUDRATE = 9600         # MH-Z19C default

_ser = None
_connected = False


# =============================================================================
# COMMAND BYTES
# =============================================================================

CMD_READ_CO2 = bytes([0xFF, 0x01, 0x86, 0, 0, 0, 0, 0, 0x79])
CMD_CALIBRATE_ZERO = bytes([0xFF, 0x01, 0x79, 0xA0, 0, 0, 0, 0, 0x78])
CMD_DISABLE_ABC = bytes([0xFF, 0x01, 0x79, 0x00, 0, 0, 0, 0, 0x86])


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup():
    """Initialize serial connection to MH-Z19C."""
    global _ser, _connected

    try:
        _ser = serial.Serial(PORT, BAUDRATE, timeout=2)
        time.sleep(0.5)

        # Test read
        _ser.write(CMD_READ_CO2)
        time.sleep(0.1)
        response = _ser.read(9)

        if len(response) != 9:
            raise MHZ19CSetupError("Sensor did not respond correctly")

        _connected = True

    except Exception as e:
        _connected = False
        raise MHZ19CSetupError(f"Setup failed: {e}")

def disable_abc():
    if not _connected:
        return
    _ser.write(CMD_DISABLE_ABC)
    time.sleep(0.1)

def read_co2():
    """Read CO2 concentration in ppm."""
    if not _connected or _ser is None:
        raise MHZ19CReadError("Sensor not initialized")

    _ser.write(CMD_READ_CO2)
    time.sleep(0.1)
    response = _ser.read(9)

    if len(response) != 9:
        raise MHZ19CReadError("Invalid response length")

    checksum = 0xFF - (sum(response[1:8]) % 256) + 1
    if checksum != response[8]:
        raise MHZ19CReadError("Checksum mismatch")

    co2 = response[2] * 256 + response[3]

    if not (0 <= co2 <= 10000):
        raise MHZ19CReadError(f"CO2 value out of range: {co2}")

    return co2


def close():
    """Close serial connection cleanly."""
    global _ser, _connected

    if _ser is not None and _ser.is_open:
        _ser.close()

    _ser = None
    _connected = False


# =============================================================================
# MAIN LOOP
# =============================================================================

def main():
    print("=" * 60)
    print("MH-Z19C CO2 Sensor - Live Readings (every 2 seconds)")
    print("=" * 60)

    try:
        print("\nInitializing sensor...")
        setup()
        print("✓ Sensor initialized successfully")

    except MHZ19CSetupError as e:
        print(f"✗ {e}")
        print("\nChecks:")
        print(" - Sensor powered with 5V")
        print(" - TX ↔ RX crossed")
        print(" - Using /dev/ttyAMA0")
        sys.exit(1)

    print("\nPress Ctrl+C to stop\n")

    try:
        while True:
            co2 = read_co2()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] CO₂ concentration: {co2} ppm")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStopping CO₂ monitoring")

    except MHZ19CReadError as e:
        print(f"\nRead error: {e}")

    finally:
        close()
        print("Sensor closed")
        print("=" * 60)

setup()
disable_abc()

# =============================================================================

if __name__ == "__main__":
    main()

