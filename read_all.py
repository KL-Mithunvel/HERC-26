# spanner/read_all.py
# Calls each sensor's read() and returns values + errors in one dict.

import time

def read_all(sensor):
    """
    sensors: dict like {"temp": module, "power": module, ...}
    Each module must have: setup(), read()
    """
    out = {
        "ts": time.time(),
        "data": {},
        "errors": {}
    }

    for name, mod in sensor.items():
        try:
            out["data"][name] = mod.read()
        except Exception as e:
            out["errors"][name] = str(e)

    return out
