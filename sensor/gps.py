import datetime
import serial

try:
    import pynmea2
    _PYNMEA2_AVAILABLE = True
except ImportError:
    _PYNMEA2_AVAILABLE = False


# =============================================================================
# EXCEPTIONS
# =============================================================================

class GPSSensorSetupError(Exception):
    pass

class GPSSensorReadError(Exception):
    pass


# =============================================================================
# MODULE STATE
# =============================================================================

_ser = None
_GPS_CONNECTED = False


# =============================================================================
# SENSOR FUNCTIONS
# =============================================================================

def setup(port="/dev/ttyUSB0", baudrate=9600, timeout=1.0):
    """
    Open the GPS serial port.
    Port and baud rate come from config.xml at startup.
    Raises GPSSensorSetupError on failure.
    """
    global _ser, _GPS_CONNECTED

    if not _PYNMEA2_AVAILABLE:
        raise GPSSensorSetupError("pynmea2 not installed — GPS unavailable on this platform")

    try:
        _ser = serial.Serial(port, baudrate, timeout=timeout)
        _GPS_CONNECTED = True
    except Exception as e:
        raise GPSSensorSetupError(f"GPS serial open failed on {port}: {e}")


def read(max_lines=50):
    """
    Read up to max_lines from the serial port looking for a valid RMC sentence.

    Returns:
      {"lat": float, "lon": float, "timestamp": int}
      timestamp is Unix epoch (UTC) derived from the GPS date+time fields.

    Raises GPSSensorReadError if:
      - serial port is not open
      - no valid RMC sentence found in max_lines
      - GPS fix is void (status != 'A')
      - lat/lon are missing from the sentence
    """
    if not _GPS_CONNECTED or _ser is None or not _ser.is_open:
        raise GPSSensorReadError("GPS serial not open")

    for _ in range(max_lines):
        try:
            line = _ser.readline().decode("ascii", errors="replace").strip()
        except Exception as e:
            raise GPSSensorReadError(f"Serial read error: {e}")

        if not line:
            continue
        if not (line.startswith("$GPRMC") or line.startswith("$GNRMC")):
            continue

        try:
            msg = pynmea2.parse(line)
        except pynmea2.ParseError:
            continue

        status = getattr(msg, "status", None)
        if status != "A":
            raise GPSSensorReadError(f"GPS fix not valid (status={status!r})")

        lat = getattr(msg, "latitude", None)
        lon = getattr(msg, "longitude", None)

        if lat is None or lon is None:
            raise GPSSensorReadError("GPS lat/lon missing from RMC sentence")

        # Derive Unix epoch from GPS UTC date + time fields
        ts_field = getattr(msg, "timestamp", None)
        ds_field = getattr(msg, "datestamp", None)
        timestamp = None
        if ts_field and ds_field:
            try:
                dt = datetime.datetime.combine(ds_field, ts_field)
                timestamp = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
            except Exception:
                timestamp = None

        return {"lat": lat, "lon": lon, "timestamp": timestamp}

    raise GPSSensorReadError(f"No valid RMC sentence found in {max_lines} lines")


def close():
    global _ser, _GPS_CONNECTED
    if _ser and _ser.is_open:
        _ser.close()
    _GPS_CONNECTED = False

