import time
import random

FAIL_PROB = 0.01

_ready = False
run_enabled = False

_status_log = []
STATUS_MAX = 200

_tool_on_since = {"air": None, "water": None, "soil": None}
_tool_elapsed = {"air": 0.0, "water": 0.0, "soil": 0.0}

_last_health = {}  # to avoid log spam


# -------------------------
# Internal simulated state
# -------------------------
_state = {
    # Temp (C)
    "temp_c": 28.0,

    # Power
    "voltage_v": 24.0,
    "current_a": 3.0,

    # GPS
    "gps_lat": 12.9716,
    "gps_lon": 80.2470,

    # IMU (g_force + velocity only — orientation/acceleration removed)
    "ax": 0.02, "ay": -0.01, "az": 9.81,
    "vx": 0.0, "vy": 0.0, "vz": 0.0,

    # pH sensor (future Modbus sensor — simulated as direct pH value)
    "ph_value": 7.0,

    # ADC / soil moisture only (pH no longer via ADC)
    "adc_raw_moist": 1800,

    # Air sensor
    "co2_ppm": 550,

    # Mega
    "tool_water": False,
    "tool_air": False,
    "tool_soil": False,
    "ibus_pulse": 1500,
    "move_cmd": "STOP",
}


def setup(fail_prob=0.01):
    global _ready, FAIL_PROB
    FAIL_PROB = float(fail_prob)
    _ready = True
    _log(f"dev_stack setup OK (FAIL_PROB={FAIL_PROB})")


def set_run_enabled(value: bool):
    global run_enabled
    run_enabled = bool(value)
    _log(f"RUN set to {run_enabled}")


def _log(msg: str):
    now = time.time()
    _status_log.append({"ts": now, "msg": msg})
    if len(_status_log) > STATUS_MAX:
        del _status_log[0]


def _maybe_fail(name: str):
    if random.random() < FAIL_PROB:
        raise Exception(f"{name} simulated error")


def _clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _update_health(out, name: str, ok: bool, msg: str):
    out["health"][name] = {"ok": bool(ok), "msg": msg or ""}

    prev = _last_health.get(name)
    curr = (bool(ok), msg or "")
    if prev is None:
        _last_health[name] = curr
        _log(f"{name} health = {curr[0]} ({curr[1]})" if curr[1] else f"{name} health = {curr[0]}")
        return

    if prev != curr:
        _last_health[name] = curr
        _log(f"{name} health = {curr[0]} ({curr[1]})" if curr[1] else f"{name} health = {curr[0]}")


def _update_tool_timers(tools: dict):
    now = time.time()
    for k in ("air", "water", "soil"):
        is_on = bool(tools.get(k, False))
        on_since = _tool_on_since[k]

        if is_on and on_since is None:
            _tool_on_since[k] = now
        elif (not is_on) and (on_since is not None):
            _tool_elapsed[k] += (now - on_since)
            _tool_on_since[k] = None


def _get_tool_timer_seconds(k: str):
    now = time.time()
    base = _tool_elapsed[k]
    if _tool_on_since[k] is not None:
        base += (now - _tool_on_since[k])
    return base


def read_all():
    """
    Returns snapshot:
      {
        ts, run_enabled,
        data: {...},
        errors: {...},
        health: {...},
        status_log: [...],
      }
    """
    if not _ready:
        return {
            "ts": time.time(),
            "run_enabled": run_enabled,
            "data": {},
            "errors": {"stack": "dev_stack not setup"},
            "health": {"stack": {"ok": False, "msg": "dev_stack not setup"}},
            "status_log": list(_status_log),
        }

    out = {
        "ts": time.time(),
        "run_enabled": run_enabled,
        "data": {},
        "errors": {},
        "health": {},
        "status_log": list(_status_log),
    }

    # -------------------------
    # Power meter (V, A, W)
    # -------------------------
    try:
        _maybe_fail("power")
        _state["voltage_v"] += random.uniform(-0.2, 0.2)
        _state["current_a"] += random.uniform(-0.05, 0.05)
        _state["voltage_v"] = _clamp(_state["voltage_v"], 18.0, 30.0)
        _state["current_a"] = _clamp(_state["current_a"], 0.0, 20.0)
        power_w = _state["voltage_v"] * _state["current_a"]

        out["data"]["power"] = {
            "voltage_v": round(_state["voltage_v"], 2),
            "current_a": round(_state["current_a"], 2),
            "power_w": round(power_w, 2),
        }
        _update_health(out, "power", True, "")
    except Exception as e:
        out["errors"]["power"] = str(e)
        _update_health(out, "power", False, str(e))

    # -------------------------
    # GPS (Timestamp, Lat, Lon)
    # -------------------------
    try:
        _maybe_fail("gps")
        _state["gps_lat"] += random.uniform(-0.00001, 0.00001)
        _state["gps_lon"] += random.uniform(-0.00001, 0.00001)

        out["data"]["gps"] = {
            "timestamp": int(time.time()),
            "lat": round(_state["gps_lat"], 6),
            "lon": round(_state["gps_lon"], 6),
        }
        _update_health(out, "gps", True, "")
    except Exception as e:
        out["errors"]["gps"] = str(e)
        _update_health(out, "gps", False, str(e))

    # -------------------------
    # IMU
    # -------------------------
    try:
        _maybe_fail("imu")

        _state["ax"] += random.uniform(-0.05, 0.05)
        _state["ay"] += random.uniform(-0.05, 0.05)
        _state["az"] += random.uniform(-0.08, 0.08)
        _state["az"] = _clamp(_state["az"], 9.2, 10.4)

        _state["vx"] += random.uniform(-0.05, 0.05)
        _state["vy"] += random.uniform(-0.05, 0.05)
        _state["vz"] += random.uniform(-0.02, 0.02)

        g_mag = (_state["ax"]**2 + _state["ay"]**2 + _state["az"]**2) ** 0.5
        g_force = g_mag / 9.80665

        out["data"]["imu"] = {
            "g_force":  round(g_force, 3),
            "velocity": {"x": round(_state["vx"], 3), "y": round(_state["vy"], 3), "z": round(_state["vz"], 3)},
        }
        _update_health(out, "imu", True, "")
    except Exception as e:
        out["errors"]["imu"] = str(e)
        _update_health(out, "imu", False, str(e))

    # -------------------------
    # Temperature sensor
    # -------------------------
    try:
        _maybe_fail("temperature")
        _state["temp_c"] += random.uniform(-0.1, 0.1)
        _state["temp_c"] = _clamp(_state["temp_c"], 10.0, 60.0)
        out["data"]["temperature"] = {"temp_c": round(_state["temp_c"], 2)}
        _update_health(out, "temperature", True, "")
    except Exception as e:
        out["errors"]["temperature"] = str(e)
        _update_health(out, "temperature", False, str(e))

    # -------------------------
    # pH sensor (Modbus — hardware TBD; simulated as direct pH reading)
    # -------------------------
    try:
        _maybe_fail("ph")
        _state["ph_value"] += random.uniform(-0.05, 0.05)
        _state["ph_value"] = round(_clamp(_state["ph_value"], 4.0, 10.0), 2)
        out["data"]["ph"] = {"ph_value": _state["ph_value"]}
        _update_health(out, "ph", True, "")
    except Exception as e:
        out["errors"]["ph"] = str(e)
        _update_health(out, "ph", False, str(e))

    # -------------------------
    # ADC (Soil Moisture only)
    # -------------------------
    try:
        _maybe_fail("adc")
        _state["adc_raw_moist"] += random.randint(-30, 30)
        _state["adc_raw_moist"] = int(_clamp(_state["adc_raw_moist"], 0, 4095))

        moist_v = (_state["adc_raw_moist"] / 4095.0) * 3.3
        moist_pct = _clamp((1.0 - (moist_v / 3.3)) * 100.0, 0.0, 100.0)

        out["data"]["adc"] = {
            "raw":            {"moisture": _state["adc_raw_moist"]},
            "sensor_voltage": {"moisture": round(moist_v, 3)},
            "moisture_value": round(moist_pct, 1),
        }
        _update_health(out, "adc", True, "")
    except Exception as e:
        out["errors"]["adc"] = str(e)
        _update_health(out, "adc", False, str(e))

    # -------------------------
    # Air sensor (CO2 ppm)
    # -------------------------
    try:
        _maybe_fail("air")
        _state["co2_ppm"] += random.randint(-15, 15)
        _state["co2_ppm"] = int(_clamp(_state["co2_ppm"], 350, 5000))
        out["data"]["air"] = {"co2_ppm": _state["co2_ppm"]}
        _update_health(out, "air", True, "")
    except Exception as e:
        out["errors"]["air"] = str(e)
        _update_health(out, "air", False, str(e))

    # -------------------------
    # Mega (tools, iBUS, movement)
    # -------------------------
    try:
        _maybe_fail("mega")

        # random toggles
        if random.random() < 0.05:
            _state["tool_water"] = not _state["tool_water"]
        if random.random() < 0.05:
            _state["tool_air"] = not _state["tool_air"]
        if random.random() < 0.05:
            _state["tool_soil"] = not _state["tool_soil"]

        _state["ibus_pulse"] += random.randint(-20, 20)
        _state["ibus_pulse"] = int(_clamp(_state["ibus_pulse"], 1000, 2000))

        moves = ["STOP", "FWD", "BACK", "LEFT", "RIGHT"]
        if random.random() < 0.10:
            _state["move_cmd"] = random.choice(moves)

        mega = {
            "tools": {"air": _state["tool_air"], "water": _state["tool_water"], "soil": _state["tool_soil"]},
            "ibus_pulse": _state["ibus_pulse"],
            "movement": _state["move_cmd"],
        }
        out["data"]["mega"] = mega

        # timers computed server-side
        _update_tool_timers(mega["tools"])
        out["data"]["timers"] = {
            "air_s": round(_get_tool_timer_seconds("air"), 1),
            "water_s": round(_get_tool_timer_seconds("water"), 1),
            "soil_s": round(_get_tool_timer_seconds("soil"), 1),
        }

        _update_health(out, "mega", True, "")
    except Exception as e:
        out["errors"]["mega"] = str(e)
        _update_health(out, "mega", False, str(e))

    return out
