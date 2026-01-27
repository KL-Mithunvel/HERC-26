from sensors.base import SensorInitError, SensorReadError

class TMP:
    """
    Thin wrapper around sensor/tmp102.py's TMP102 class.
    - connect() creates the device once
    - read() returns a single temperature value
    - raises SensorInitError / SensorReadError (no prints)
    """
    def __init__(self, address=0x48, bus=1, unit="C"):
        self.address = address
        self.bus = bus
        self.unit = unit  # "C" or "F"
        self._dev = None

    def connect(self):
        try:
            from sensor.tmp102 import TMP102  # your existing library path
            self._dev = TMP102("C", self.address, self.bus)  # init in C (library design)
            # set desired output unit (library handles conversion)
            self._dev.setUnits(self.unit)
        except Exception as e:
            self._dev = None
            raise SensorInitError(f"TMP102 not found or init failed: {e}")

    def read(self) -> float:
        if self._dev is None:
            raise SensorReadError("TMP102 not connected")

        try:
            # library returns in configured units
            return float(self._dev.readTemperature())
        except Exception as e:
            raise SensorReadError(f"TMP102 read failed: {e}")

    def close(self):
        # TMP102 (smbus) typically doesn't require explicit close
        self._dev = None
