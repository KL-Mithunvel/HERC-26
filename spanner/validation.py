# spanner/validation.py
# Stateful validation: tracks per-tool phase and counts down valid samples.
#
# Phase sequence per tool:
#   Air:   off -> valid_window (15 reads) -> done
#   Soil:  off -> waiting (10 s) -> valid_window (15 reads) -> done
#   Water: off -> waiting (10 s) -> stabilizing (170 s) -> valid_window (15 reads) -> done
#
# valid_sample = True ONLY during valid_window, for exactly N reads.
# Resets fully when the tool goes OFF.

class _ToolRule:
    def __init__(self, name, valid_samples, wait_s=0.0, stabilize_s=0.0):
        """
        name          : tool name string (for reference)
        valid_samples : how many consecutive reads count as mission-valid
        wait_s        : seconds to wait before the valid window opens
                        (physical collection / travel time)
        stabilize_s   : additional seconds to wait after wait_s before opening
                        the valid window (sensor equilibration)
        """
        self.name          = name
        self.wait_s        = float(wait_s)
        self.stabilize_s   = float(stabilize_s)
        self.valid_samples = int(valid_samples)

        self._was_on         = False
        self._window_started = False
        self._samples_left   = 0

    def reset(self):
        self._was_on         = False
        self._window_started = False
        self._samples_left   = 0

    def update(self, is_on: bool, on_s: float) -> dict:
        on_s = float(on_s or 0.0)

        # Tool OFF — full reset
        if not is_on:
            self.reset()
            return {
                "on":           False,
                "on_s":         0.0,
                "phase":        "off",
                "valid_sample": False,
                "valid_in_s":   None,
                "samples_left": 0,
            }

        # Rising edge — reset counters for a fresh run
        if not self._was_on:
            self._window_started = False
            self._samples_left   = 0
        self._was_on = True

        stabilize_start = self.wait_s
        window_start    = self.wait_s + self.stabilize_s

        # Phase: waiting (physical collection / water travel time)
        if on_s < stabilize_start:
            return {
                "on":           True,
                "on_s":         round(on_s, 1),
                "phase":        "waiting",
                "valid_sample": False,
                "valid_in_s":   round(stabilize_start - on_s, 1),
                "samples_left": 0,
            }

        # Phase: stabilizing (sensor equilibration)
        if on_s < window_start:
            return {
                "on":           True,
                "on_s":         round(on_s, 1),
                "phase":        "stabilizing",
                "valid_sample": False,
                "valid_in_s":   round(window_start - on_s, 1),
                "samples_left": 0,
            }

        # Open the valid window once all waits are done
        if not self._window_started:
            self._window_started = True
            self._samples_left   = self.valid_samples

        valid_sample = self._samples_left > 0
        if self._samples_left > 0:
            self._samples_left -= 1

        return {
            "on":           True,
            "on_s":         round(on_s, 1),
            "phase":        "valid_window" if valid_sample else "done",
            "valid_sample": bool(valid_sample),
            "valid_in_s":   0.0,
            "samples_left": int(self._samples_left),
        }


# ---- Tool rules ----

# Air (CO2 — MH-Z19C):
#   No waiting. Mega controls when air hits the sensor.
#   Readings are valid immediately. Log next 15.
_AIR = _ToolRule("air", valid_samples=15, wait_s=0.0, stabilize_s=0.0)

# Soil moisture (ADS1115):
#   Wait 10 s for the probe to reach the collected sample.
#   Then log next 15 readings.
_SOIL = _ToolRule("soil", valid_samples=15, wait_s=10.0, stabilize_s=0.0)

# Water / pH:
#   Wait 10 s for water to travel from pump to sensor.
#   Then wait 170 s for the pH electrode to stabilise (total = 180 s / 3 min).
#   Then log next 15 readings.
_WATER = _ToolRule("water", valid_samples=15, wait_s=10.0, stabilize_s=170.0)


def compute_validation(tools: dict, timers: dict) -> dict:
    """
    tools:  {"air": bool, "water": bool, "soil": bool}
    timers: {"air_s": float, "water_s": float, "soil_s": float}
    Returns {"air": {...}, "water": {...}, "soil": {...}}
    """
    tools  = tools  or {}
    timers = timers or {}

    return {
        "air":   _AIR.update(  bool(tools.get("air",   False)), timers.get("air_s",   0.0)),
        "water": _WATER.update(bool(tools.get("water", False)), timers.get("water_s", 0.0)),
        "soil":  _SOIL.update( bool(tools.get("soil",  False)), timers.get("soil_s",  0.0)),
    }
