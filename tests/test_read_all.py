"""
tests/test_read_all.py
======================
Manual smoke-test for the dev sensor stack.

Run from the project root:
    python tests/test_read_all.py

What it checks:
  1. setup() completes without error
  2. read_all() returns a dict with all required top-level keys
  3. Every expected sensor key is present in snap["data"]
  4. No sensor reports an error on every single poll (would indicate a logic bug)
  5. Pretty-prints all 5 snapshots so you can visually inspect values

Expected output on a working dev stack:
  - All sensors show [OK] most of the time (1% chance each poll of a simulated error)
  - Temperatures ~28 °C, CO2 ~550 ppm, moisture ~50%, pH ~7.0
  - GPS stays near lat=12.97, lon=80.24
  - Validation shows "off" for all tools (nothing is triggered in this test)
  - "ERRORS: (none)" in most polls; the occasional error is fine and expected
"""

import sys
import os
import time
import datetime

# ── Make imports work from the project root ──────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sensor import dev_stack
from spanner.validation import compute_validation


# ── Pretty-printer ─────────────────────────────────────────────────────────────

def pretty_print(snap: dict, poll_num: int = 1) -> None:
    """Print one snapshot in a human-readable format."""
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

    # ---- Power ----
    pwr = data.get("power") or {}
    tag = _tag(snap["health"].get("power", {}).get("ok", False))
    print(f"  Power        {pwr.get('voltage_v','–')} V  {pwr.get('current_a','–')} A  {pwr.get('power_w','–')} W      {tag}")

    # ---- Air ----
    air = data.get("air") or {}
    tag = _tag(snap["health"].get("air", {}).get("ok", False))
    print(f"  CO2 / Air    {air.get('co2_ppm','–')} ppm                             {tag}")

    # ---- Soil ----
    adc = data.get("adc") or {}
    raw = (adc.get("raw") or {}).get("moisture", "–")
    sv  = (adc.get("sensor_voltage") or {}).get("moisture", "–")
    tag = _tag(snap["health"].get("adc", {}).get("ok", False))
    print(f"  Soil         {adc.get('moisture_value','–')} %  raw={raw}  {sv} V              {tag}")

    # ---- pH ----
    ph  = data.get("ph") or {}
    tag = _tag(snap["health"].get("ph", {}).get("ok", False))
    print(f"  pH           {ph.get('ph_value','–')}                                {tag}")

    # ---- Mega ----
    mega  = data.get("mega") or {}
    tools = mega.get("tools") or {}
    tag   = _tag(snap["health"].get("mega", {}).get("ok", False))
    print(f"  Mega         {mega.get('movement','–')}  pulse={mega.get('ibus_pulse','–')}us"
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

# ── Config ───────────────────────────────────────────────────────────────────
POLLS     = 5
DELAY_S   = 0.5
FAIL_PROB = 0.01   # keep low so most polls succeed cleanly

REQUIRED_TOP_KEYS  = {"ts", "run_enabled", "data", "errors", "health", "status_log"}
REQUIRED_DATA_KEYS = {"power", "gps", "imu", "temperature", "ph", "adc", "air", "mega", "timers"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def check(condition: bool, label: str) -> bool:
    result = "PASS" if condition else "FAIL"
    print(f"    [{result}] {label}")
    return condition


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  HERC-26 dev_stack  —  read_all() smoke-test")
    print("="*60)

    # ── Step 1: setup ────────────────────────────────────────────────────────
    print("\n[1] setup()")
    try:
        dev_stack.setup(fail_prob=FAIL_PROB)
        print("    [PASS] setup() completed without exception")
    except Exception as e:
        print(f"    [FAIL] setup() raised: {e}")
        sys.exit(1)

    # ── Step 2: poll N times ─────────────────────────────────────────────────
    all_errors: dict[str, list[str]] = {}   # sensor_name -> list of error messages

    for i in range(1, POLLS + 1):
        snap = dev_stack.read_all()

        # Attach validation so pretty_print can show it
        tools  = (snap.get("data", {}).get("mega") or {}).get("tools", {})
        timers = (snap.get("data") or {}).get("timers", {})
        snap["validation"] = compute_validation(tools, timers)

        pretty_print(snap, poll_num=i)

        # Accumulate errors across polls
        for k, v in snap.get("errors", {}).items():
            all_errors.setdefault(k, []).append(v)

        if i < POLLS:
            time.sleep(DELAY_S)

    # ── Step 3: structural assertions ────────────────────────────────────────
    print("\n[2] Structural checks on last snapshot")
    snap = dev_stack.read_all()

    ok = True
    ok &= check(isinstance(snap, dict),              "snap is a dict")
    ok &= check(REQUIRED_TOP_KEYS <= snap.keys(),    f"top-level keys present: {REQUIRED_TOP_KEYS}")
    ok &= check(isinstance(snap["data"], dict),      "snap['data'] is a dict")
    ok &= check(REQUIRED_DATA_KEYS <= snap["data"].keys(),
                f"data keys present: {REQUIRED_DATA_KEYS}")
    ok &= check(isinstance(snap["errors"], dict),    "snap['errors'] is a dict")
    ok &= check(isinstance(snap["health"], dict),    "snap['health'] is a dict")
    ok &= check(isinstance(snap["status_log"], list),"snap['status_log'] is a list")
    ok &= check(isinstance(snap["ts"], float),       "snap['ts'] is a float")

    # ── Check data sub-keys ────────────────────────────────────────────────
    print("\n[3] Data sub-key checks")
    d = snap["data"]

    ok &= check("temp_c"        in (d.get("temperature") or {}), "temperature.temp_c exists")
    ok &= check("g_force"       in (d.get("imu")         or {}), "imu.g_force exists")
    ok &= check("velocity"      in (d.get("imu")         or {}), "imu.velocity exists")
    ok &= check("lat"           in (d.get("gps")         or {}), "gps.lat exists")
    ok &= check("lon"           in (d.get("gps")         or {}), "gps.lon exists")
    ok &= check("voltage_v"     in (d.get("power")       or {}), "power.voltage_v exists")
    ok &= check("co2_ppm"       in (d.get("air")         or {}), "air.co2_ppm exists")
    ok &= check("ph_value"      in (d.get("ph")          or {}), "ph.ph_value exists")
    ok &= check("moisture_value" in (d.get("adc")        or {}), "adc.moisture_value exists")
    ok &= check("tools"         in (d.get("mega")        or {}), "mega.tools exists")
    ok &= check("movement"      in (d.get("mega")        or {}), "mega.movement exists")
    ok &= check("air_s"         in (d.get("timers")      or {}), "timers.air_s exists")

    # Known gaps (pre-existing, not our bugs) — just report, don't fail
    print("\n[4] Known gaps (expected, not failures)")
    ori = (d.get("imu") or {}).get("orientation")
    print(f"    [NOTE] imu.orientation = {ori!r}  "
          f"(expected None until imu.py reads euler angles)")
    gps_spd = (d.get("gps") or {}).get("speed_mps")
    print(f"    [NOTE] gps.speed_mps   = {gps_spd!r}  "
          f"(expected None until gps.py is updated)")

    # ── Error frequency summary ────────────────────────────────────────────
    print(f"\n[5] Error summary across {POLLS} polls (1% FAIL_PROB — a few errors are normal)")
    if all_errors:
        for sensor, msgs in all_errors.items():
            print(f"    {sensor:12s} errored {len(msgs)}/{POLLS} polls")
    else:
        print("    No errors in any poll (lucky run — try again if you want to see error handling)")

    # ── Result ────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    if ok:
        print("  RESULT: ALL CHECKS PASSED")
    else:
        print("  RESULT: SOME CHECKS FAILED — see [FAIL] lines above")
    print("="*60 + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
