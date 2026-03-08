import struct

try:
    import smbus as _smbus
    _HW = True
except ImportError:
    _smbus = None
    _HW = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class MegaSensorSetupError(Exception):
    pass

class MegaSensorReadError(Exception):
    pass


# =============================================================================
# PACKET FORMAT
# Arduino StatusPacket: { tool_water, tool_air, tool_soil, ibus_pulse }
# Each Arduino bool is 1 byte → 4 bytes total.
# =============================================================================

_FMT   = "4?"
_NBYTES = struct.calcsize(_FMT)   # 4


# =============================================================================
# MODULE STATE
# =============================================================================

_bus     = None
_address = None
_connected = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address: int = 0x08, bus: int = 1):
    """
    Open the I2C bus and confirm the Mega is responding.
    address and bus come from config.xml at startup.
    """
    global _bus, _address, _connected

    if not _HW:
        raise MegaSensorSetupError("smbus not available on this platform")

    try:
        _bus = _smbus.SMBus(bus)
        _address = address
        # Probe — one read to confirm the Mega is present and sending data
        raw = _bus.read_i2c_block_data(_address, 0, _NBYTES)
        if len(raw) != _NBYTES:
            raise MegaSensorSetupError(
                f"Probe read: expected {_NBYTES} bytes, got {len(raw)}"
            )
        _connected = True
    except MegaSensorSetupError:
        raise
    except Exception as e:
        raise MegaSensorSetupError(f"Mega I2C setup failed on bus {bus} addr {address:#x}: {e}")


def read():
    """
    Read the current tool status packet from the Mega.

    Returns:
        {
            "tools":      {"air": bool, "water": bool, "soil": bool},
            "ibus_pulse": bool,
            "movement":   str,   # "STOP" — tool_controller.ino does not track movement
        }
    """
    if not _connected or _bus is None:
        raise MegaSensorReadError("Mega not initialized")

    try:
        raw = _bus.read_i2c_block_data(_address, 0, _NBYTES)
    except Exception as e:
        raise MegaSensorReadError(f"I2C read failed: {e}")

    if len(raw) != _NBYTES:
        raise MegaSensorReadError(f"Bad packet length: expected {_NBYTES}, got {len(raw)}")

    tool_water, tool_air, tool_soil, ibus_pulse = struct.unpack(_FMT, bytes(raw))

    return {
        "tools": {
            "air":   bool(tool_air),
            "water": bool(tool_water),
            "soil":  bool(tool_soil),
        },
        "ibus_pulse": bool(ibus_pulse),
        "movement":   "STOP",   # movement not tracked by tool_controller firmware
    }


def close():
    global _bus, _connected
    if _bus is not None:
        try:
            _bus.close()
        except Exception:
            pass
    _bus = None
    _connected = False


# =============================================================================
# MAIN — run directly on Pi to verify Mega I2C communication
# =============================================================================

if __name__ == "__main__":
    import sys
    import time

    print("=" * 50)
    print("Mega Tool Status — Live (every 0.5 s)")
    print(f"I2C bus=1  addr=0x08  packet={_NBYTES} bytes")
    print("=" * 50)

    try:
        setup()
        print("Connected.\n")
    except MegaSensorSetupError as e:
        print(f"Setup failed: {e}")
        print("\nChecks:")
        print("  - Mega powered and running tool_controller firmware")
        print("  - SDA/SCL wired correctly to Pi GPIO 2/3")
        print("  - i2cdetect -y 1  should show 0x08")
        sys.exit(1)

    try:
        while True:
            data = read()
            t = data["tools"]
            print(
                f"Water: {int(t['water'])}  "
                f"Air: {int(t['air'])}  "
                f"Soil: {int(t['soil'])}  "
                f"IBUS: {int(data['ibus_pulse'])}"
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped")
    except MegaSensorReadError as e:
        print(f"\nRead error: {e}")
    finally:
        close()
        print("Closed")
