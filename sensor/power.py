import time

import sensor.ads1115 as _adc
from sensor.ads1115 import ADCSensorSetupError, ADCSensorReadError


# =============================================================================
# EXCEPTIONS
# =============================================================================

class BatterySensorSetupError(Exception):
    pass

class BatterySensorReadError(Exception):
    pass


# =============================================================================
# BATTERY + DIVIDER CONSTANTS
# 3S LiPo: 3 × 4.2 V = 12.6 V full, 3 × 3.0 V = 9.0 V nominal empty.
# 3S LiPo: 3 × 2.7 V = 8.1 V absolute floor (reserve charge floor).
# Voltage divider: R1=30 kΩ, R2=7.5 kΩ → scale = (R1+R2)/R2 = 5.0
# ADC input range: 9.0 × 0.2 = 1.80 V  →  12.6 × 0.2 = 2.52 V  (GAIN_1, safe)
# =============================================================================

_DIVIDER_SCALE = 5.0    # V_batt = V_adc × 5.0
_V_FULL        = 12.6   # 100 % charge
_V_EMPTY       = 9.0    # 0 % charge  (reserve starts below this)
_V_ABS_MIN     = 8.1    # absolute floor — reserve_pct = 0 % here


# =============================================================================
# MODULE STATE
# =============================================================================

_channel   = 2      # A2
_CONNECTED = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x49, channel=2):
    """
    Initialise battery voltage monitor on the given ADS1115 channel.
    Delegates hardware init to sensor.ads1115 (call is idempotent).
    Voltage divider (R1=30 kΩ, R2=7.5 kΩ) scales 9–12.6 V → 1.8–2.52 V.
    GAIN_1 (±4.096 V) used — consistent with all other ADC channels.
    address and channel come from config.xml at startup.
    Default channel=2 (AIN2 / A2).
    """
    global _channel, _CONNECTED
    try:
        _adc.setup(address=address)
        _adc.register_channel(channel)
    except ADCSensorSetupError as e:
        raise BatterySensorSetupError(str(e))
    _channel   = channel
    _CONNECTED = True


def read():
    """
    Return battery dict:
      voltage_v:   float   actual battery voltage after divider scaling (V)
      percentage:  float   0–100 % mapped to 9.0 V–12.6 V, clamped at 0 below 9 V
      reserved:    bool    True when voltage < 9.0 V (using reserve charge)
      reserve_pct: float   % of reserve remaining within 8.1–9.0 V window
                           (100 % at 9.0 V, 0 % at 8.1 V; 0 when not reserved)
    """
    if not _CONNECTED:
        raise BatterySensorReadError("Battery sensor not connected — call setup() first")
    try:
        raw, v_adc = _adc.read_all()[_channel]
    except ADCSensorReadError as e:
        raise BatterySensorReadError(str(e))

    v_batt = round(v_adc * _DIVIDER_SCALE, 3)

    percentage = round(
        max(0.0, min(100.0, (v_batt - _V_EMPTY) / (_V_FULL - _V_EMPTY) * 100.0)), 1
    )

    reserved = v_batt < _V_EMPTY
    if reserved:
        reserve_pct = round(
            max(0.0, min(100.0,
                (v_batt - _V_ABS_MIN) / (_V_EMPTY - _V_ABS_MIN) * 100.0
            )), 1
        )
    else:
        reserve_pct = 0.0

    return {
        "voltage_v":   v_batt,
        "percentage":  percentage,
        "reserved":    reserved,
        "reserve_pct": reserve_pct,
    }


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
            status = "RESERVE" if d["reserved"] else "OK"
            print(
                f"{d['voltage_v']:.3f} V  "
                f"{d['percentage']:.1f} %  "
                f"[{status}]"
                + (f"  reserve_pct={d['reserve_pct']:.1f} %" if d["reserved"] else "")
            )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()