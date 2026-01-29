# sensors/dev_stack.py
# Dev-only full sensor stack simulator.
# - Call setup() once
# - Call read_all() repeatedly -> {"ts": ..., "data": {...}, "errors": {...}}
# - 1% independent error rate per sensor group

import time
import random

FAIL_PROB = 0.01
_ready = False


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

    # IMU
    "ax": 0.02, "ay": -0.01, "az": 9.81,
    "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
    "vx": 0.0, "vy": 0.0, "vz": 0.0,

    # ADC / soil
    "adc_raw_ph": 2100,
    "adc_raw_moist": 1800,

    # Air sensor
    "co2_ppm": 550,

    # Mega
    "tool_water": False,
    "tool_air": False,
    "tool_soil": False,
    "ibus_pulse": 1500,  # typical 1000-2000
    "move_cmd": "STOP",  # FWD/BACK/LEFT/RIGHT/STOP
}


def setup(fail_prob=0.01):
    global _ready, FAIL_PROB
    FAIL_PROB = fail_prob
    _ready = True


def _maybe_fail(name):
    if random.random() < FAIL_PROB:
        raise Exception(f"{name} simulated error")


def _clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def read_all():
    if not _ready:
        return {"ts": time.time(), "data": {}, "errors": {"stack": "dev_stack not setup"}}

    out = {"ts": time.time(), "data": {}, "errors": {}}

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
    except Exception as e:
        out["errors"]["power"] = str(e)

    # -------------------------
    # GPS (Timestamp, Lat, Lon)
    # -------------------------
    try:
        _maybe_fail("gps")
        _state["gps_lat"] += random.uniform(-0.00001, 0.00001)
        _state["gps_lon"] += random.uniform(-0.00001, 0.00001)

        out["data"]["gps"] = {
            "utc_ts": int(time.time()),  # dev placeholder; later GPS UTC
            "lat": round(_state["gps_lat"], 6),
            "lon": round(_state["gps_lon"], 6),
        }
    except Exception as e:
        out["errors"]["gps"] = str(e)

    # -------------------------
    # IMU (Acceleration, Orientation, G-force, Velocity)
    # -------------------------
    try:
        _maybe_fail("imu")

        # accel (m/s^2) around gravity on Z
        _state["ax"] += random.uniform(-0.05, 0.05)
        _state["ay"] += random.uniform(-0.05, 0.05)
        _state["az"] += random.uniform(-0.08, 0.08)
        _state["az"] = _clamp(_state["az"], 9.2, 10.4)

        # orientation (deg)
        _state["roll"] += random.uniform(-1.0, 1.0)
        _state["pitch"] += random.uniform(-1.0, 1.0)
        _state["yaw"] += random.uniform(-2.0, 2.0)

        # velocity (m/s) simple random walk
        _state["vx"] += random.uniform(-0.05, 0.05)
        _state["vy"] += random.uniform(-0.05, 0.05)
        _state["vz"] += random.uniform(-0.02, 0.02)

        # g-force magnitude (in g)
        g_mag = (_state["ax"]**2 + _state["ay"]**2 + _state["az"]**2) ** 0.5
        g_force = g_mag / 9.80665

        out["data"]["imu"] = {
            "accel_mps2": {
                "x": round(_state["ax"], 3),
                "y": round(_state["ay"], 3),
                "z": round(_state["az"], 3),
            },
            "orientation_deg": {
                "roll": round(_state["roll"], 2),
                "pitch": round(_state["pitch"], 2),
                "yaw": round(_state["yaw"], 2),
            },
            "g_force": round(g_force, 3),
            "velocity_mps": {
                "x": round(_state["vx"], 3),
                "y": round(_state["vy"], 3),
                "z": round(_state["vz"], 3),
            },
        }
    except Exception as e:
        out["errors"]["imu"] = str(e)

    # -------------------------
    # Temperature sensor (Temperature)
    # -------------------------
    try:
        _maybe_fail("temp")
        _state["temp_c"] += random.uniform(-0.1, 0.1)
        _state["temp_c"] = _clamp(_state["temp_c"], 10.0, 60.0)

        out["data"]["temperature"] = {
            "temp_c": round(_state["temp_c"], 2)
        }
    except Exception as e:
        out["errors"]["temperature"] = str(e)

    # -------------------------
    # ADC (Raw, Sensor Voltage, pH, Moisture)
    # -------------------------
    try:
        _maybe_fail("adc")

        # simulate raw ADC (0..4095 for 12-bit)
        _state["adc_raw_ph"] += random.randint(-20, 20)
        _state["adc_raw_moist"] += random.randint(-30, 30)
        _state["adc_raw_ph"] = int(_clamp(_state["adc_raw_ph"], 0, 4095))
        _state["adc_raw_moist"] = int(_clamp(_state["adc_raw_moist"], 0, 4095))

        # sensor voltage for 3.3V ADC
        ph_v = (_state["adc_raw_ph"] / 4095.0) * 3.3
        moist_v = (_state["adc_raw_moist"] / 4095.0) * 3.3

        # dev mapping (placeholder): pH 0-14 based on voltage 0-3.3
        ph_value = (ph_v / 3.3) * 14.0

        # dev mapping (placeholder): moisture % (inverse-ish)
        moist_pct = (1.0 - (moist_v / 3.3)) * 100.0
        moist_pct = _clamp(moist_pct, 0.0, 100.0)

        out["data"]["adc"] = {
            "raw": {
                "ph": _state["adc_raw_ph"],
                "moisture": _state["adc_raw_moist"],
            },
            "voltage_v": {
                "ph": round(ph_v, 3),
                "moisture": round(moist_v, 3),
            },
            "ph_value": round(ph_value, 2),
            "moisture_value": round(moist_pct, 1),
        }
    except Exception as e:
        out["errors"]["adc"] = str(e)

    # -------------------------
    # Air sensor (CO2 ppm)
    # -------------------------
    try:
        _maybe_fail("air")
        _state["co2_ppm"] += random.randint(-15, 15)
        _state["co2_ppm"] = int(_clamp(_state["co2_ppm"], 350, 5000))

        out["data"]["air"] = {
            "co2_ppm": _state["co2_ppm"]
        }
    except Exception as e:
        out["errors"]["air"] = str(e)

    # -------------------------
    # Mega (tools on/off, iBUS pulse, movement)
    # -------------------------
    try:
        _maybe_fail("mega")

        # randomly toggle tools occasionally
        if random.random() < 0.05:
            _state["tool_water"] = not _state["tool_water"]
        if random.random() < 0.05:
            _state["tool_air"] = not _state["tool_air"]
        if random.random() < 0.05:
            _state["tool_soil"] = not _state["tool_soil"]

        # simulate ibus pulse (1000-2000)
        _state["ibus_pulse"] += random.randint(-20, 20)
        _state["ibus_pulse"] = int(_clamp(_state["ibus_pulse"], 1000, 2000))

        # movement command selection
        moves = ["STOP", "FWD", "BACK", "LEFT", "RIGHT"]
        if random.random() < 0.1:
            _state["move_cmd"] = random.choice(moves)

        out["data"]["mega"] = {
            "tools": {
                "water": _state["tool_water"],
                "air": _state["tool_air"],
                "soil": _state["tool_soil"],
            },
            "ibus_pulse": _state["ibus_pulse"],
            "movement": _state["move_cmd"],
        }
    except Exception as e:
        out["errors"]["mega"] = str(e)

    return out
