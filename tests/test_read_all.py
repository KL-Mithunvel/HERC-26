"""
tests/test_read_all.py
======================
Hardware smoke-test for the real physical sensor stack.
Run this on the Raspberry Pi BEFORE starting main.py.

    python tests/test_read_all.py

What it does:
  - Loads port/address config from calibration/config.xml
  - Calls real_stack.setup() to initialize all physical sensors
  - Polls real_stack.read_all() every second and pretty-prints each snapshot
  - Runs until Ctrl+C
  - On exit, prints a summary of which sensors were OK and which stayed offline

Sensors that fail to connect show as [OFFLINE] — this is not a crash.
The reconnect logic inside real_stack will keep retrying them every poll.
If a sensor comes online mid-run you will see it flip from [OFFLINE] to [OK].
"""

import sys
import os
import time
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sensor import real_stack
from sensor.dev_stack import pretty_print          # formatting only — works on any snapshot
from spanner.validation import compute_validation
from calibration.config_reader import load_config

# ── Load config ───────────────────────────────────────────────────────────────
try:
    _cfg = load_config()
except Exception as e:
    print(f"[ERROR] Could not load config.xml: {e}")
    print("        Make sure you are running from the project root.")
    sys.exit(1)

POLL_S = 1.0   # 1-second interval for manual inspection (main.py uses 0.5s)

# ── Sensor health tracking ────────────────────────────────────────────────────
_poll_count   = 0
_ok_counts    = {}   # sensor_name -> polls where health was OK
_total_counts = {}   # sensor_name -> total polls seen


# ── Graceful exit on Ctrl+C ───────────────────────────────────────────────────
_running = True

def _handle_sigint(sig, frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _handle_sigint)


# ── Setup ─────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  HERC-26 — real_stack hardware smoke-test")
print("  Press Ctrl+C to stop")
print("="*60)

print("\n[SETUP] Initializing physical sensors from config.xml ...")
real_stack.setup(
    tmp_address  = _cfg.get("i2c_tmp102_address",  0x48),
    tmp_bus      = _cfg.get("i2c_bus",              1),
    gps_port     = _cfg.get("gps_port",             "/dev/ttyUSB0"),
    gps_baud     = _cfg.get("gps_baud",             9600),
    air_port     = _cfg.get("air_port",             "/dev/ttyAMA0"),
    air_baud     = _cfg.get("air_baud",             9600),
    # ADS1115 shared by soil (A0), pH (A1), battery (A2)
    adc_address  = _cfg.get("i2c_ads1115_address",  0x49),
    soil_channel = 0,
    soil_dry_ref = _cfg.get("soil_dry_ref",         800),
    soil_wet_ref = _cfg.get("soil_wet_ref",         300),
    ph_channel   = 1,
    batt_channel = 2,
    mega_port    = _cfg.get("mega_port",            "/dev/ttyACM0"),
    mega_baud    = _cfg.get("mega_baud",            115200),
)
print("[SETUP] Done — starting poll loop\n")


# ── Poll loop ─────────────────────────────────────────────────────────────────
while _running:
    _poll_count += 1

    snap = real_stack.read_all()
    snap["schema_version"] = 1

    tools  = (snap.get("data", {}).get("mega") or {}).get("tools", {})
    timers = (snap.get("data") or {}).get("timers", {})
    snap["validation"] = compute_validation(tools, timers)

    pretty_print(snap, poll_num=_poll_count)

    # Track per-sensor health across polls
    for name, h in snap.get("health", {}).items():
        _total_counts[name] = _total_counts.get(name, 0) + 1
        if h.get("ok"):
            _ok_counts[name] = _ok_counts.get(name, 0) + 1

    try:
        time.sleep(POLL_S)
    except KeyboardInterrupt:
        break


# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"  SUMMARY — {_poll_count} polls")
print("="*60)
all_names = sorted(_total_counts.keys())
for name in all_names:
    ok    = _ok_counts.get(name, 0)
    total = _total_counts[name]
    pct   = 100 * ok // total if total else 0
    status = "OK      " if ok == total else ("OFFLINE " if ok == 0 else "FLAKY   ")
    print(f"  [{status}] {name:12s}  {ok}/{total} polls OK  ({pct}%)")
print("="*60 + "\n")
