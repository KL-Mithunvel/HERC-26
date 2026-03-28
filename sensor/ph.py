import time

import sensor.ads1115 as _adc
from sensor.ads1115 import ADCSensorSetupError, ADCSensorReadError


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PHSensorSetupError(Exception):
    pass

class PHSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

_channel   = 1      # A1
_CONNECTED = False

# Sensor output: 0–2 V maps linearly to pH 0–14.
# pH = voltage × 7.0  (confirmed from S-pH-01 user guide).
_PH_SCALE = 7.0


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x49, channel=1):
    """
    Initialise pH sensor on the given ADS1115 channel.
    Delegates hardware init to sensor.ads1115 (call is idempotent).
    Uses GAIN_2 (±2.048 V FSR) — pH output is 0–2 V, giving 62.5 µV resolution.
    address and channel come from config.xml at startup.
    Default channel=1 (AIN1 / A1).
    """
    global _channel, _CONNECTED
    try:
        _adc.setup(address=address)
    except ADCSensorSetupError as e:
        raise PHSensorSetupError(str(e))
    _channel   = channel
    _CONNECTED = True


def read():
    """
    Return pH dict:
      raw:            {ph: int}    (raw ADC counts at ±2.048 V gain)
      sensor_voltage: {ph: float}  (V, 0.0–2.0)
      ph_value:       float        (0.0–14.0)
    """
    if not _CONNECTED:
        raise PHSensorReadError("pH sensor not connected — call setup() first")
    try:
        raw, voltage = _adc.read_channel(_channel, gain=_adc.GAIN_2)
    except ADCSensorReadError as e:
        raise PHSensorReadError(str(e))

    voltage  = max(0.0, min(2.0, voltage))
    ph_value = round(max(0.0, min(14.0, voltage * _PH_SCALE)), 2)

    return {
        "raw":            {"ph": raw},
        "sensor_voltage": {"ph": round(voltage, 4)},
        "ph_value":       ph_value,
    }


def close():
    """
    Mark this sensor as disconnected.
    Does not close the shared ADS1115 — other sensors (soil.py) may still use it.
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
            print(f"raw={d['raw']['ph']:6d}  "
                  f"{d['sensor_voltage']['ph']:.4f} V  "
                  f"pH={d['ph_value']:.2f}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()