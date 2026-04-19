import time

_I2C_RETRIES     = 3
_I2C_RETRY_DELAY = 0.015  # 15 ms between retries

try:
    import board
    import busio
    from adafruit_ads1x15.ads1115 import ADS1115
    from adafruit_ads1x15.analog_in import AnalogIn
    _HW = True
except Exception:
    # Catches ImportError (missing library) and RuntimeError/OSError
    # that Adafruit Blinka raises on Pi 5 when lgpio shim is absent.
    _HW = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class ADCSensorSetupError(Exception):
    pass

class ADCSensorReadError(Exception):
    pass


# =============================================================================
# GAIN CONSTANT
# All three channels (moisture A0, pH A1, battery A2) use GAIN_1 (±4.096 V).
# Resolution is 125 µV/count — far exceeds the accuracy of all connected sensors.
# =============================================================================

GAIN_1 = 1   # ±4.096 V FSR — 125 µV / count


# =============================================================================
# MODULE STATE
# =============================================================================

_ADS          = None
_i2c          = None          # busio.I2C object — kept for close()/deinit
_CONNECTED    = False
_channels     = set()        # registered channel indices

# read_all() cache — all sensor read() calls within one poll cycle share one
# I2C burst rather than re-reading the hardware independently.
_CACHE_TTL    = 0.2          # seconds
_cache        = {}           # {channel: (raw, voltage)}
_cache_time   = 0.0


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(address: int = 0x49):
    """
    Initialise ADS1115 at the given I2C address.
    Idempotent — soil.py, ph.py, and power.py all call this; only the first
    call opens the bus.
    Default address 0x49: ADDR pin wired to VCC, avoids conflict with TMP102 (0x48).
    address comes from config.xml at startup.
    """
    global _ADS, _i2c, _CONNECTED
    if _CONNECTED:
        return
    if not _HW:
        raise ADCSensorSetupError(
            "board/busio/adafruit_ads1x15 not available on this platform"
        )
    try:
        _i2c = busio.I2C(board.SCL, board.SDA)
        _ADS = ADS1115(_i2c, address=address)
        _ADS.gain = GAIN_1
    except Exception as e:
        raise ADCSensorSetupError(f"ADS1115 init failed at 0x{address:02X}: {e}")
    _CONNECTED = True


def register_channel(channel: int):
    """
    Register a channel to be included in read_all() scans.
    Called once by each sensor module during its own setup().
    channel: 0–3 (AIN0–AIN3, single-ended vs GND).
    """
    _channels.add(channel)


def read_all() -> dict:
    """
    Read all registered channels in one sequential burst and return cached results.

    Returns {channel_index: (raw_counts, voltage_v), ...}

    Result is cached for CACHE_TTL seconds. When soil.read(), ph.read(), and
    power.read() all call read_all() within the same 500 ms poll cycle, only
    the first call hits the hardware; the rest return the cached snapshot.

    Raises ADCSensorReadError if the chip is unreachable.
    """
    global _cache, _cache_time

    if not _CONNECTED or _ADS is None:
        raise ADCSensorReadError("ADS1115 not connected — call setup() first")

    now = time.monotonic()
    if _cache and (now - _cache_time) < _CACHE_TTL:
        return _cache

    last_err = None
    for attempt in range(_I2C_RETRIES):
        try:
            result = {}
            for ch in sorted(_channels):
                chan = AnalogIn(_ADS, ch)
                result[ch] = (chan.value, chan.voltage)
            _cache      = result
            _cache_time = now
            return result
        except Exception as e:
            last_err = e
            if attempt < _I2C_RETRIES - 1:
                time.sleep(_I2C_RETRY_DELAY)
    # All retries exhausted — mark bus as dead so next setup() actually reinits.
    _CONNECTED = False
    raise ADCSensorReadError(f"ADS1115 read failed after {_I2C_RETRIES} attempts: {last_err}")


def close():
    """Close the I2C bus and mark as disconnected. Next setup() will reinit."""
    global _ADS, _i2c, _CONNECTED
    _CONNECTED = False
    _ADS = None
    if _i2c is not None:
        try:
            _i2c.deinit()
        except Exception:
            pass
        _i2c = None


# =============================================================================
# MAIN — run directly on Pi to verify all three channels
# =============================================================================

if __name__ == "__main__":
    # Register all three channels for the standalone test
    setup()
    register_channel(0)
    register_channel(1)
    register_channel(2)
    try:
        while True:
            ch = read_all()
            r0, v0 = ch.get(0, (0, 0.0))
            r1, v1 = ch.get(1, (0, 0.0))
            r2, v2 = ch.get(2, (0, 0.0))
            print(
                f"A0 moisture  raw={r0:6d}  {v0:.4f} V  |  "
                f"A1 pH        raw={r1:6d}  {v1:.4f} V  pH={v1 * 7.0:.2f}  |  "
                f"A2 battery   raw={r2:6d}  {v2:.4f} V  batt={v2 * 5.0:.2f} V"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        close()