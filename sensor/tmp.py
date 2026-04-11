try:
    from .tmp102 import TMP102   # imported as part of the sensor package (main.py)
except ImportError:
    from tmp102 import TMP102    # run directly: python3 sensor/tmp.py
import time

_I2C_RETRIES    = 3
_I2C_RETRY_DELAY = 0.015  # 15 ms between retries


# =============================================================================
# EXCEPTIONS
# =============================================================================

class TmpSensorSetupError(Exception):
    pass

class TmpSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

_TMP = None
_TMP_connected = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x48, bus=1):
    """Initialize TMP102 sensor. Address and bus from config.xml at startup."""
    global _TMP, _TMP_connected
    try:
        _TMP = TMP102('C', address, bus)
    except Exception as e:
        raise TmpSensorSetupError(f"TMP102 init failed: {e}")
    _TMP_connected = True


def read():
    """Return temperature in Celsius as {"temp_c": float}."""
    if not _TMP_connected or _TMP is None:
        raise TmpSensorReadError("TMP102 not connected")
    last_err = None
    for attempt in range(_I2C_RETRIES):
        try:
            temp_c = _TMP.readTemperature()
            return {"temp_c": round(temp_c, 2)}
        except Exception as e:
            last_err = e
            if attempt < _I2C_RETRIES - 1:
                time.sleep(_I2C_RETRY_DELAY)
    raise TmpSensorReadError(f"TMP102 read failed after {_I2C_RETRIES} attempts: {last_err}")


def close():
    global _TMP_connected
    _TMP_connected = False


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

