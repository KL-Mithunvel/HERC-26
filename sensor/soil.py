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

_channel   = 0      # A0
_dry_ref   = 800    # raw ADC counts for dry soil  (from config.xml via real_stack)
_wet_ref   = 300    # raw ADC counts for wet soil  (from config.xml via real_stack)
_CONNECTED = False


# =============================================================================
# SENSOR FUNCTIONS SETUP
# =============================================================================

def setup(address: int = 0x49, channel: int = 0,
          dry_ref: int = 800, wet_ref: int = 300):
    """
    Initialise soil moisture sensor on the given ADS1115 channel.
    Delegates hardware init to sensor.ads1115 (call is idempotent).
    address, channel, dry_ref, wet_ref come from config.xml via real_stack.
    Default channel=0 (AIN0 / A0).
    """
    global _channel, _dry_ref, _wet_ref, _CONNECTED

    if dry_ref <= wet_ref:
        raise SoilSensorSetupError(
            f"Invalid calibration: dry_ref ({dry_ref}) must be > wet_ref ({wet_ref})"
        )

    try:
        _adc.setup(address=address)
        _adc.register_channel(channel)
    except ADCSensorSetupError as e:
        raise SoilSensorSetupError(str(e))

    _channel   = channel
    _dry_ref   = dry_ref
    _wet_ref   = wet_ref
    _CONNECTED = True

# =============================================================================
# FILTERED ADC READ
# =============================================================================

def read_filtered(samples=11):
    pairs = []

    for _ in range(samples):
        try:
            raw, voltage = _adc.read_all()[_channel]
            pairs.append((raw, voltage))
        except ADCSensorReadError:
            pass  # collect what we can — partial is better than nothing

    if not pairs:
        raise SoilSensorReadError("All ADC samples failed")

    # Median filtering — sort pairs together by raw value so the returned
    # raw and voltage always come from the same sample.
    pairs.sort(key=lambda p: p[0])
    mid = len(pairs) // 2
    return pairs[mid]

# =============================================================================
# MAIN READ FUNCTION
# =============================================================================

def read(samples=11):
    """
    Return soil moisture dict:
      raw:            {moisture: int}    (raw ADC counts)
      sensor_voltage: {moisture: float}  (V)
      moisture_value: float              (0.0–100.0 %)
    """
    if not _CONNECTED:
        raise SoilSensorReadError("Soil sensor not connected — call setup() first")
    try:
        raw, voltage = read_filtered(samples)
    except ADCSensorReadError as e:
        raise SoilSensorReadError(str(e))

    #Moisture calculation
    moisture_value = round(
        max(0.0, min(100.0, (_dry_ref - raw) * 100.0 / (_dry_ref - _wet_ref))),
        1
    )
    return {
        "raw":            {"moisture": raw},
        "sensor_voltage": {"moisture": round(voltage, 4)},
        "moisture_value": moisture_value,
    }

# =============================================================================
# CLEANUP
# =============================================================================
    
def close():
    """Mark this sensor as disconnected and close the shared ADS1115 bus."""
    global _CONNECTED
    _CONNECTED = False
    _adc.close()

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
                  f"moisture={d['moisture_value']:5.1f} %")
            time.sleep(1)
    except SoilSensorSetupError as e:
        print(f"[SETUP ERROR] {e}")

    except SoilSensorReadError as e:
        print(f"[READ ERROR] {e}")
        
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()
