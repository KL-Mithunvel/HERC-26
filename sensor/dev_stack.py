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

    # Battery (A2 via voltage divider: R1=30k, R2=7.5k, scale=5)
    # adc_batt_v is the voltage at the ADC pin (V_batt / 5).
    # 11.0 V battery → 2.2 V ADC. Range: 1.8 V (9 V) – 2.52 V (12.6 V).
    "adc_batt_v": 2.2,

    # GPS
    "gps_lat": 12.9716,
    "gps_lon": 80.2470,
    "gps_speed_knots": 0.5,
    "gps_sats": 8,
    "gps_fix": 1,

    # IMU (g_force + velocity only — orientation/acceleration removed)
    "ax": 0.02, "ay": -0.01, "az": 9.81,
    "vx": 0.0, "vy": 0.0, "vz": 0.0,

    # ADC / soil moisture (A0) + pH (A1 via 0–2 V analog output)
    "adc_raw_moist": 1800,
    "adc_ph_v":      1.0,   # simulated pH sensor voltage (0–2 V → pH 0–14)

    # Air sensor
    "co2_ppm": 550,

    # Mega
    "tool_water": False,
    "tool_air": False,
    "tool_soil": False,
    "ibus_pulse": True,   # bool — True = RC signal valid
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
    # Battery (voltage divider → ADS1115 A2)
    # -------------------------
    try:
        _maybe_fail("battery")
        _state["adc_batt_v"] += random.uniform(-0.005, 0.005)
        _state["adc_batt_v"]  = round(_clamp(_state["adc_batt_v"], 1.62, 2.52), 4)
        # 1.62 V ADC = 8.1 V battery (reserve floor); 2.52 V ADC = 12.6 V (full)

        v_batt     = round(_state["adc_batt_v"] * 5.0, 3)
        batt_pct   = round(max(0.0, min(100.0, (v_batt - 9.0) / (12.6 - 9.0) * 100.0)), 1)
        reserved   = v_batt < 9.0
        reserve_pct = round(
            max(0.0, min(100.0, (v_batt - 8.1) / (9.0 - 8.1) * 100.0)), 1
        ) if reserved else 0.0

        out["data"]["battery"] = {
            "voltage_v":   v_batt,
            "percentage":  batt_pct,
            "reserved":    reserved,
            "reserve_pct": reserve_pct,
        }
        _update_health(out, "battery", True, "")
    except Exception as e:
        out["errors"]["battery"] = str(e)
        _update_health(out, "battery", False, str(e))

    # -------------------------
    # GPS (Timestamp, Lat, Lon)
    # -------------------------
    try:
        _maybe_fail("gps")
        _state["gps_lat"] += random.uniform(-0.00001, 0.00001)
        _state["gps_lon"] += random.uniform(-0.00001, 0.00001)
        _state["gps_speed_knots"] += random.uniform(-0.05, 0.05)
        _state["gps_speed_knots"] = _clamp(_state["gps_speed_knots"], 0.0, 5.0)

        out["data"]["gps"] = {
            "timestamp": int(time.time()),
            "lat":       round(_state["gps_lat"], 6),
            "lon":       round(_state["gps_lon"], 6),
            "speed_mps": round(_state["gps_speed_knots"] * 0.5144, 3),
            "sats":      _state["gps_sats"],
            "fix":       _state["gps_fix"],
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
    # ADC (Soil Moisture A0 + pH A1)
    # -------------------------
    try:
        _maybe_fail("adc")

        # Soil moisture (A0) — capacitive sensor, wider voltage swing
        _state["adc_raw_moist"] += random.randint(-30, 30)
        _state["adc_raw_moist"] = int(_clamp(_state["adc_raw_moist"], 0, 4095))
        moist_v   = (_state["adc_raw_moist"] / 4095.0) * 3.3
        moist_pct = _clamp((1.0 - (moist_v / 3.3)) * 100.0, 0.0, 100.0)

        # pH sensor (A1) — 0–2 V output, GAIN_2 (±2.048 V), pH = voltage × 7
        _state["adc_ph_v"] += random.uniform(-0.03, 0.03)
        _state["adc_ph_v"]  = round(_clamp(_state["adc_ph_v"], 0.0, 2.0), 4)
        ph_raw   = round(_state["adc_ph_v"] / 2.048 * 32767)
        ph_value = round(_clamp(_state["adc_ph_v"] * 7.0, 0.0, 14.0), 2)

        out["data"]["adc"] = {
            "raw":            {"moisture": _state["adc_raw_moist"], "ph": ph_raw},
            "sensor_voltage": {"moisture": round(moist_v, 3),       "ph": _state["adc_ph_v"]},
            "moisture_value": round(moist_pct, 1),
            "ph_value":       ph_value,
        }
        _update_health(out, "adc", True, "")
        _update_health(out, "ph",  True, "")   # pH shares ADS1115 — same health
    except Exception as e:
        out["errors"]["adc"] = str(e)
        _update_health(out, "adc", False, str(e))
        _update_health(out, "ph",  False, str(e))

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

        # ibus_pulse: True = RC signal valid. Rare random drop to simulate loss.
        if random.random() < 0.02:
            _state["ibus_pulse"] = not _state["ibus_pulse"]

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


# ---------------------------------------------------------------------------
# Pretty-printer — used by __main__ below and importable by test scripts
# ---------------------------------------------------------------------------

def pretty_print(snap: dict, poll_num: int = 1) -> None:
    """Print one snapshot in a human-readable format."""
    import datetime

    SEP  = "─" * 56
    HEAD = "═" * 56

    def _ts(ts_float):
        return datetime.datetime.fromtimestamp(ts_float, tz=datetime.timezone.utc)\
               .strftime("%Y-%m-%d  %H:%M:%S  UTC")

    def _tag(ok: bool):
        return f"[{'OK    ' if ok else 'ERROR '}]"

    data   = snap.get("data",       {})
    errors = snap.get("errors",     {})
    val    = snap.get("validation", {})

    print()
    print(f"  {'═'*10}  HERC-26  SNAPSHOT  #{poll_num}  {'═'*10}")
    print(f"  Timestamp  : {_ts(snap.get('ts', 0))}")
    print(f"  Run        : {'ENABLED' if snap.get('run_enabled') else 'DISABLED'}")
    print(f"  {HEAD}")

    # ---- Temperature ----
    tmp = data.get("temperature") or {}
    tag = _tag(snap["health"].get("temperature", {}).get("ok", False))
    print(f"  Temperature  {tmp.get('temp_c', '–')} °C                          {tag}")

    # ---- IMU ----
    imu = data.get("imu") or {}
    vel = imu.get("velocity") or {}
    ori = imu.get("orientation") or {}
    tag = _tag(snap["health"].get("imu", {}).get("ok", False))
    gf  = imu.get("g_force", "–")
    print(f"  IMU          g={gf}  roll={ori.get('roll','–')}  pitch={ori.get('pitch','–')}  yaw={ori.get('yaw','–')}")
    print(f"               vel x={vel.get('x','–')}  y={vel.get('y','–')}  z={vel.get('z','–')}  {tag}")

    # ---- GPS ----
    gps = data.get("gps") or {}
    tag = _tag(snap["health"].get("gps", {}).get("ok", False))
    print(f"  GPS          lat={gps.get('lat','–')}  lon={gps.get('lon','–')}               {tag}")

    # ---- Battery ----
    batt = data.get("battery") or {}
    tag  = _tag(snap["health"].get("battery", {}).get("ok", False))
    rsv  = "  [RESERVE]" if batt.get("reserved") else ""
    print(f"  Battery      {batt.get('voltage_v','–')} V  {batt.get('percentage','–')} %{rsv}  {tag}")

    # ---- Air ----
    air = data.get("air") or {}
    tag = _tag(snap["health"].get("air", {}).get("ok", False))
    print(f"  CO2 / Air    {air.get('co2_ppm','–')} ppm                             {tag}")

    # ---- Soil + pH (both from ADS1115 ADC) ----
    adc     = data.get("adc") or {}
    raw_m   = (adc.get("raw") or {}).get("moisture", "–")
    sv_m    = (adc.get("sensor_voltage") or {}).get("moisture", "–")
    raw_ph  = (adc.get("raw") or {}).get("ph", "–")
    sv_ph   = (adc.get("sensor_voltage") or {}).get("ph", "–")
    tag     = _tag(snap["health"].get("adc", {}).get("ok", False))
    print(f"  Soil         {adc.get('moisture_value','–')} %  raw={raw_m}  {sv_m} V              {tag}")
    print(f"  pH           {adc.get('ph_value','–')}  raw={raw_ph}  {sv_ph} V")

    # ---- Mega ----
    mega  = data.get("mega") or {}
    tools = mega.get("tools") or {}
    tag   = _tag(snap["health"].get("mega", {}).get("ok", False))
    pulse_str = "OK" if mega.get("ibus_pulse") else "LOST"
    print(f"  Mega         {mega.get('movement','–')}  rc={pulse_str}"
          f"  air={int(tools.get('air',0))} wtr={int(tools.get('water',0))} soil={int(tools.get('soil',0))}  {tag}")

    # ---- Timers ----
    tmr = data.get("timers") or {}
    print(f"  Timers       air={tmr.get('air_s','–')}s  water={tmr.get('water_s','–')}s  soil={tmr.get('soil_s','–')}s")

    # ---- Errors ----
    print(f"  {SEP}")
    if errors:
        print(f"  ERRORS:")
        for k, v in errors.items():
            print(f"    {k:12s} : {v}")
    else:
        print(f"  ERRORS       (none)")

    # ---- Validation ----
    print(f"  {SEP}")
    print(f"  VALIDATION")
    for tool in ("air", "soil", "water"):
        v = val.get(tool) or {}
        valid_flag = "VALID" if v.get("valid_sample") else "     "
        print(f"    {tool:6s}  phase={v.get('phase','off'):12s}  {valid_flag}"
              f"  samples_left={v.get('samples_left',0):2d}"
              f"  on_s={v.get('on_s',0.0):.1f}s")

    # ---- Status log tail ----
    log = snap.get("status_log") or []
    if log:
        print(f"  {SEP}")
        print(f"  STATUS LOG (last 3)")
        for entry in log[-3:]:
            t = datetime.datetime.fromtimestamp(entry["ts"], tz=datetime.timezone.utc)\
                .strftime("%H:%M:%S")
            print(f"    [{t}] {entry['msg']}")
    print(f"  {'═'*56}")


# ---------------------------------------------------------------------------
# Run directly:  python sensor/dev_stack.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    POLLS = 5
    DELAY = 0.5
    print(f"\n  dev_stack direct run — {POLLS} polls at {1/DELAY:.0f} Hz\n")
    setup(fail_prob=0.02)
    for i in range(1, POLLS + 1):
        snap = read_all()
        pretty_print(snap, poll_num=i)
        if i < POLLS:
            time.sleep(DELAY)
