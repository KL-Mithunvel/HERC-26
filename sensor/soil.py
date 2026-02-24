import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
import time


# =============================================================================
# EXCEPTIONS
# =============================================================================

class SoilSensorSetupError(Exception):
    pass

class SoilSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# NOTE: pH measurement has been removed from this module.
#       The pH sensor (DFRobot V1.1 via ADC) is being replaced with a
#       different sensor. This module now handles soil moisture only.
# =============================================================================

_ADS = None
_CHAN_MOISTURE = None
_CONNECTED = False

_dry_ref = 800
_wet_ref = 300


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x48, channel_moisture=1, dry_ref=800, wet_ref=300):
    """
    Initialize ADS1115 ADC for soil moisture only.
    address, channel assignment, and calibration values come from config.xml at startup.
    """
    global _ADS, _CHAN_MOISTURE, _CONNECTED
    global _dry_ref, _wet_ref

    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        _ADS = ADS1115(i2c, address=address)
        _CHAN_MOISTURE = AnalogIn(_ADS, channel_moisture)
    except Exception as e:
        raise SoilSensorSetupError(f"ADS1115 init failed: {e}")

    _dry_ref = dry_ref
    _wet_ref = wet_ref
    _CONNECTED = True


def read():
    """
    Return ADC snapshot dict:
      raw:            {moisture: int}    (raw ADC counts 0–65535)
      sensor_voltage: {moisture: float}  (V)
      moisture_value: float              (0.0–100.0 %)
    """
    if not _CONNECTED or _ADS is None:
        raise SoilSensorReadError("ADS1115 not connected")

    try:
        raw_moisture = _CHAN_MOISTURE.value
        v_moisture = _CHAN_MOISTURE.voltage
    except Exception as e:
        raise SoilSensorReadError(f"ADS1115 read failed: {e}")

    moisture_value = round(
        max(0.0, min(100.0, (_dry_ref - raw_moisture) * 100.0 / (_dry_ref - _wet_ref))),
        1
    )

    return {
        "raw":            {"moisture": raw_moisture},
        "sensor_voltage": {"moisture": round(v_moisture, 4)},
        "moisture_value": moisture_value,
    }


def close():
    global _CONNECTED
    _CONNECTED = False


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
