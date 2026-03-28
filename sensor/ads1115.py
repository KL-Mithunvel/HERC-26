import time

try:
    import board
    import busio
    from adafruit_ads1x15.ads1115 import ADS1115
    from adafruit_ads1x15.analog_in import AnalogIn
    _HW = True
except ImportError:
    _HW = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ADCSensorSetupError(Exception):
    pass

class ADCSensorReadError(Exception):
    pass


# =============================================================================
# GAIN CONSTANTS
# Use GAIN_1 (±4.096 V) for soil moisture (capacitive sensor, wider swing).
# Use GAIN_2 (±2.048 V) for pH sensor (0–2 V output — maximises resolution).
# =============================================================================

GAIN_1 = 1   # ±4.096 V FSR — 125 µV / count
GAIN_2 = 2   # ±2.048 V FSR —  62.5 µV / count


# =============================================================================
# MODULE STATE
# Shared singleton — soil.py and ph.py both call setup(); it is idempotent.
# =============================================================================

_ADS = None
_CONNECTED = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address=0x49):
    """
    Initialise ADS1115 at the given I2C address.
    Idempotent — safe to call from multiple sensor modules (soil, ph).
    Default address 0x49: ADDR pin wired to VCC, avoids conflict with TMP102 (0x48).
    address comes from config.xml at startup.
    """
    global _ADS, _CONNECTED
    if _CONNECTED:
        return
    if not _HW:
        raise ADCSensorSetupError("board/busio/adafruit_ads1x15 not available on this platform")
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        _ADS = ADS1115(i2c, address=address)
    except Exception as e:
        raise ADCSensorSetupError(f"ADS1115 init failed at 0x{address:02X}: {e}")
    _CONNECTED = True


def read_channel(channel: int, gain: int = GAIN_1):
    """
    Read one channel of the ADS1115 in single-ended mode (AINx vs GND).
    Sets gain on the ADC object before each read — required when different
    channels use different gain settings.

    channel : 0–3  (AIN0–AIN3)
    gain    : GAIN_1 (±4.096 V) or GAIN_2 (±2.048 V)
    Returns : (raw_counts: int, voltage: float)
    """
    if not _CONNECTED or _ADS is None:
        raise ADCSensorReadError("ADS1115 not connected — call setup() first")
    try:
        _ADS.gain = gain
        chan = AnalogIn(_ADS, channel)
        return chan.value, chan.voltage
    except Exception as e:
        raise ADCSensorReadError(f"ADS1115 read failed (ch={channel}, gain={gain}): {e}")


def close():
    global _CONNECTED
    _CONNECTED = False


# =============================================================================
# MAIN — run directly on Pi to verify both channels
# =============================================================================

if __name__ == "__main__":
    setup()
    try:
        while True:
            raw0, v0 = read_channel(0, gain=GAIN_1)
            raw1, v1 = read_channel(1, gain=GAIN_2)
            print(f"A0 (moisture)  raw={raw0:6d}  {v0:.4f} V"
                  f"    A1 (pH)  raw={raw1:6d}  {v1:.4f} V  →  pH {v1 * 7.0:.2f}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()