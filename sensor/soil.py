import time

import sensor.ads1115 as _adc
from sensor.ads1115 import ADCSensorSetupError, ADCSensorReadError


# =============================================================================
# EXCEPTIONS
# =============================================================================

class SoilSensorSetupError(Exception):
    pass

class SoilSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

_channel  = 0      # A0
_dry_ref  = 800    # raw ADC counts for dry soil  (from config.xml)
_wet_ref  = 300    # raw ADC counts for wet soil  (from config.xml)
_CONNECTED = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x49, channel=0, dry_ref=800, wet_ref=300):
    """
    Initialise soil moisture sensor on the given ADS1115 channel.
    Delegates hardware init to sensor.ads1115 (call is idempotent).
    address, channel, dry_ref, wet_ref come from config.xml at startup.
    Default channel=0 (AIN0 / A0).
    """
    global _channel, _dry_ref, _wet_ref, _CONNECTED
    try:
        _adc.setup(address=address)
        _adc.register_channel(channel)
    except ADCSensorSetupError as e:
        raise SoilSensorSetupError(str(e))
    _channel   = channel
    _dry_ref   = dry_ref
    _wet_ref   = wet_ref
    _CONNECTED = True


def read():
    """
    Return soil moisture dict:
      raw:            {moisture: int}    (raw ADC counts)
      sensor_voltage: {moisture: float}  (V)
      moisture_value: float              (0.0–100.0 %)
    """
    if not _CONNECTED:
        raise SoilSensorReadError("Soil sensor not connected — call setup() first")
    try:
        raw, voltage = _adc.read_all()[_channel]
    except ADCSensorReadError as e:
        raise SoilSensorReadError(str(e))

    moisture_value = round(
        max(0.0, min(100.0, (_dry_ref - raw) * 100.0 / (_dry_ref - _wet_ref))),
        1
    )
    return {
        "raw":            {"moisture": raw},
        "sensor_voltage": {"moisture": round(voltage, 4)},
        "moisture_value": moisture_value,
    }


def close():
    """
    Mark this sensor as disconnected.
    Does not close the shared ADS1115 — other sensors (ph.py) may still use it.
    """
    global _CONNECTED
    _CONNECTED = False


# =============================================================================
# MAIN — run directly on Pi to verify sensor
# =============================================================================

if __name__ == "__main__":
    setup()
    try:
        while True:
            d = read()
            print(f"raw={d['raw']['moisture']:6d}  "
                  f"{d['sensor_voltage']['moisture']:.4f} V  "
                  f"moisture={d['moisture_value']:.1f} %")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()