# spanner/validation.py
# Stateful validation: after warmup/stabilize, the NEXT N readings are valid.

class _ToolRule:
    def __init__(self, name, warmup_s, valid_samples, stabilize_s=0.0, collect_s=0.0):
        self.name = name
        self.collect_s = float(collect_s)      # optional phase
        self.warmup_s = float(warmup_s)        # warmup before any stabilization
        self.stabilize_s = float(stabilize_s)  # additional stabilization time
        self.valid_samples = int(valid_samples)

        # internal state
        self._was_on = False
        self._window_started = False
        self._samples_left = 0

    def reset(self):
        self._was_on = False
        self._window_started = False
        self._samples_left = 0

    def update(self, is_on: bool, on_s: float):
        on_s = float(on_s or 0.0)

        # OFF -> reset
        if not is_on:
            self.reset()
            return {
                "on": False,
                "on_s": 0.0,
                "phase": "off",
                "valid_sample": False,
                "valid_in_s": None,
                "samples_left": 0,
            }

        # ON edge -> reset counters for a new run
        if is_on and not self._was_on:
            self._window_started = False
            self._samples_left = 0

        self._was_on = True

        # Phase timing for this tool
        # collect -> warmup -> stabilize -> validation-window
        collect_end = self.collect_s
        warmup_end = self.collect_s + self.warmup_s
        stabilize_end = self.collect_s + self.warmup_s + self.stabilize_s

        # Determine phase + countdown
        if on_s < collect_end:
            return {
                "on": True,
                "on_s": round(on_s, 1),
                "phase": "collecting",
                "valid_sample": False,
                "valid_in_s": round(collect_end - on_s, 1),
                "samples_left": 0,
            }

        if on_s < warmup_end:
            return {
                "on": True,
                "on_s": round(on_s, 1),
                "phase": "warmup",
                "valid_sample": False,
                "valid_in_s": round(warmup_end - on_s, 1),
                "samples_left": 0,
            }

        if on_s < stabilize_end:
            return {
                "on": True,
                "on_s": round(on_s, 1),
                "phase": "stabilizing",
                "valid_sample": False,
                "valid_in_s": round(stabilize_end - on_s, 1),
                "samples_left": 0,
            }

        # We are past all waiting phases -> open validation window once
        if not self._window_started:
            self._window_started = True
            self._samples_left = self.valid_samples

        # valid_sample only for the NEXT N reads
        valid_sample = self._samples_left > 0
        if self._samples_left > 0:
            self._samples_left -= 1

        return {
            "on": True,
            "on_s": round(on_s, 1),
            "phase": "valid_window" if valid_sample else "done",
            "valid_sample": bool(valid_sample),
            "valid_in_s": 0.0,
            "samples_left": int(self._samples_left),
        }


# ---- Rules requested ----
# Soil: wait 10s, then next 10 readings valid
_SOIL = _ToolRule("soil", warmup_s=10.0, valid_samples=10)

# Air: wait 2s, then next 10 readings valid
_AIR = _ToolRule("air", warmup_s=2.0, valid_samples=10)

# Water (pH):
# - First 10s: "collecting sample"
# - Then stabilize until 3 min total (180s) from ON
# - Then next 10 readings valid
# Implementation: collect=10s, warmup=0, stabilize=170s -> total = 180s
_WATER = _ToolRule("water", warmup_s=0.0, stabilize_s=170.0, collect_s=10.0, valid_samples=10)


def compute_validation(tools: dict, timers: dict):
    """
    tools:  {"air":bool, "water":bool, "soil":bool}
    timers: {"air_s":float, "water_s":float, "soil_s":float}
    Returns validation dict with per-tool phase + validity.
    """
    tools = tools or {}
    timers = timers or {}

    air = _AIR.update(bool(tools.get("air", False)), timers.get("air_s", 0.0))
    water = _WATER.update(bool(tools.get("water", False)), timers.get("water_s", 0.0))
    soil = _SOIL.update(bool(tools.get("soil", False)), timers.get("soil_s", 0.0))

    return {"air": air, "water": water, "soil": soil}
