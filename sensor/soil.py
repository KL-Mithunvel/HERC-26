import time

import os
import xml.etree.ElementTree as ET

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
# CONFIG
# =============================================================================

CAL_FILE = "/home/krishna/Desktop/HERC-26/calibration/calib_data.xml"


# =============================================================================
# MODULE STATE
# =============================================================================

_channel  = 0      # A0
_dry_ref  = None    # raw ADC counts for dry soil  (from config.xml)
_wet_ref  = None    # raw ADC counts for wet soil  (from config.xml)
_CONNECTED = False

# =============================================================================
# XML LOADER
# =============================================================================

def load_calibration():
    if not os.path.exists(CAL_FILE):
        raise SoilSensorSetupError("Calibration file not found")

    try:
        tree = ET.parse(CAL_FILE)
        root = tree.getroot()

        dry = root.find("dry")
        wet = root.find("wet")

        if dry is None or wet is None:
            raise SoilSensorSetupError("Missing dry/wet calibration in XML")

        dry_val = int(dry.text)
        wet_val = int(wet.text)

        # Validation
        if dry_val <= wet_val:
            raise SoilSensorSetupError(
                f"Invalid calibration: dry ({dry_val}) must be > wet ({wet_val})"
            )

        return dry_val, wet_val

    except ET.ParseError:
        raise SoilSensorSetupError("Failed to parse calibration XML")


# =============================================================================
# SENSOR FUNCTIONS SETUP
# =============================================================================

def setup(address=0x49, channel=0):
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

    # Load calibration from XML
    _dry_ref, _wet_ref = load_calibration()
    _channel = channel
    _CONNECTED = True

# =============================================================================
# FILTERED ADC READ
# =============================================================================

def read_filtered(samples=11, delay=0.01):
    values = []
    voltages = []

    for _ in range(samples):
        raw, voltage = _adc.read_all()[_channel]
        values.append(raw)
        voltages.append(voltage)
        time.sleep(delay)

    # Median filtering (more robust than mean)
    values.sort()
    voltages.sort()

    mid = len(values) // 2

    raw = values[mid]
    voltage = voltages[mid]

    return raw, voltage

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
