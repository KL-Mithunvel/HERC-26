import struct
import time

try:
    import serial as _serial
    _HW = True
except ImportError:
    _serial = None
    _HW = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class MegaSensorSetupError(Exception):
    pass

class MegaSensorReadError(Exception):
    pass


# =============================================================================
# FRAME FORMAT — matches rover_mega.ino sendStatusFrame()
#
# USB Serial frame (9 bytes total):
#   byte 0: SYNC1  = 0xAA   \  two-byte magic header for reliable re-sync
#   byte 1: SYNC2  = 0x55   /
#   byte 2: tool_water    bool
#   byte 3: tool_air      bool
#   byte 4: tool_soil     bool
#   byte 5: ibus_pulse    bool — true = RC signal valid this read cycle
#   byte 6: movement      uint8 — 0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT
#   byte 7: pump_running  bool
#   byte 8: failsafe      bool — true = 500 ms RC timeout, all outputs stopped
#
# Mega pushes one frame every STATUS_INTERVAL_MS (100 ms, ~10 Hz).
# Pi reads the latest complete frame, flushing stale bytes first.
# =============================================================================

_SYNC1    = 0xAA
_SYNC2    = 0x55
_FMT      = "<4?B2?"              # 7 payload bytes
_NBYTES   = struct.calcsize(_FMT) # 7
_MAX_SCAN = 9 * 20                # scan at most 20 frames worth before giving up

_MOVEMENT_MAP = {0: "STOP", 1: "FWD", 2: "BACK", 3: "LEFT", 4: "RIGHT"}


# =============================================================================
# MODULE STATE
# =============================================================================

_ser       = None
_connected = False


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _sync_and_read() -> bytes:
    """
    Scan incoming bytes until the 0xAA 0x55 frame header is found, then
    return the 7 payload bytes that follow.
    Raises MegaSensorReadError on timeout or short read.
    """
    for _ in range(_MAX_SCAN):
        b = _ser.read(1)
        if not b:
            raise MegaSensorReadError("Serial timeout waiting for frame sync (0xAA)")
        if b[0] != _SYNC1:
            continue
        b2 = _ser.read(1)
        if not b2:
            raise MegaSensorReadError("Serial timeout after SYNC1")
        if b2[0] != _SYNC2:
            continue
        payload = _ser.read(_NBYTES)
        if len(payload) != _NBYTES:
            raise MegaSensorReadError(
                f"Short payload: expected {_NBYTES} bytes, got {len(payload)}"
            )
        return payload
    raise MegaSensorReadError(
        f"No valid frame found after scanning {_MAX_SCAN} bytes"
    )


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(port: str = "/dev/ttyACM0", baudrate: int = 115200):
    """
    Open USB serial port and confirm the Mega is sending status frames.
    port and baudrate come from config.xml at startup.
    Raises MegaSensorSetupError on failure.
    """
    global _ser, _connected

    if not _HW:
        raise MegaSensorSetupError(
            "pyserial not available — install with: pip install pyserial  "
            "or: sudo apt install python3-serial"
        )

    try:
        _ser = _serial.Serial(port, baudrate, timeout=0.5)
        time.sleep(0.1)             # allow USB-reset to settle
        _ser.reset_input_buffer()   # discard startup text / stale bytes
        # Probe — confirm Mega is alive and sending frames
        _sync_and_read()
        _connected = True
    except MegaSensorSetupError:
        raise
    except Exception as e:
        raise MegaSensorSetupError(
            f"Mega serial setup failed on {port} @ {baudrate}: {e}"
        )


def read() -> dict:
    """
    Read the latest status frame from the Mega.

    Flushes the input buffer first so stale buffered frames are discarded —
    we always return the most recently sent rover state.

    Returns:
        {
            "tools":        {"air": bool, "water": bool, "soil": bool},
            "ibus_pulse":   bool,
            "movement":     str,   # "STOP" | "FWD" | "BACK" | "LEFT" | "RIGHT"
            "pump_running": bool,
            "failsafe":     bool,
        }

    Raises MegaSensorReadError if no valid frame arrives within timeout.
    """
    if not _connected or _ser is None:
        raise MegaSensorReadError("Mega not initialized")

    try:
        _ser.reset_input_buffer()   # discard stale frames — want fresh data
        payload = _sync_and_read()
    except MegaSensorReadError:
        raise
    except _serial.SerialException as e:
        raise MegaSensorReadError(f"Serial error: {e}")

    tool_water, tool_air, tool_soil, ibus_pulse, movement_byte, pump_running, failsafe = \
        struct.unpack(_FMT, bytes(payload))

    return {
        "tools": {
            "air":   bool(tool_air),
            "water": bool(tool_water),
            "soil":  bool(tool_soil),
        },
        "ibus_pulse":   bool(ibus_pulse),
        "movement":     _MOVEMENT_MAP.get(int(movement_byte), "STOP"),
        "pump_running": bool(pump_running),
        "failsafe":     bool(failsafe),
    }


def close():
    global _ser, _connected
    if _ser is not None:
        try:
            _ser.close()
        except Exception:
            pass
    _ser = None
    _connected = False


# =============================================================================
# MAIN — run directly on Pi to verify Mega serial communication
# =============================================================================

if __name__ == "__main__":
    import sys

    PORT = "/dev/ttyACM0"
    BAUD = 115200

    print("=" * 60)
    print("Mega Status — Live (every 0.5 s)")
    print(f"Serial {PORT} @ {BAUD}  payload={_NBYTES} bytes  frame=9 bytes")
    print("=" * 60)

    try:
        setup(PORT, BAUD)
        print("Connected.\n")
    except MegaSensorSetupError as e:
        print(f"Setup failed: {e}")
        print("\nChecks:")
        print("  - Mega powered and running rover_mega firmware")
        print("  - USB cable from Mega to Pi")
        print(f"  - Port is {PORT}  (check with: ls /dev/ttyACM*)")
        sys.exit(1)

    try:
        while True:
            data = read()
            t = data["tools"]
            print(
                f"Water:{int(t['water'])}"
                f" Air:{int(t['air'])}"
                f" Soil:{int(t['soil'])}"
                f" | Move:{data['movement']:5s}"
                f" Pump:{int(data['pump_running'])}"
                f" | RC:{'OK  ' if data['ibus_pulse'] else 'LOST'}"
                f" Failsafe:{'YES' if data['failsafe'] else 'no '}"
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped")
    except MegaSensorReadError as e:
        print(f"\nRead error: {e}")
    finally:
        close()
        print("Closed")
