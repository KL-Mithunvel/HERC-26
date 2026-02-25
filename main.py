import time
import threading

# ─────────────────────────────────────────────────────────────────────────────
# Sensor stack selection
# ─────────────────────────────────────────────────────────────────────────────
# Set USE_REAL_SENSORS = True when running on the Raspberry Pi.
# False (default) uses dev_stack (simulated data) on any development machine.
USE_REAL_SENSORS = False

if USE_REAL_SENSORS:
    from sensor import real_stack as _stack
else:
    from sensor import dev_stack as _stack

from spanner import logger_dev
from web.app import app, set_latest
from spanner.validation import compute_validation
from logger.sqlite_db import SQLiteLogger

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
try:
    from calibration.config_reader import load_config
    _cfg = load_config()
except Exception as _e:
    print(f"[main] WARNING: config.xml load failed ({_e}) — using built-in defaults")
    _cfg = {}

# Poll interval derived from config.xml → <rates><sensor_read_hz>.
# Clamped to [0.1 Hz, 10 Hz] to prevent accidental overload or near-zero rates.
_hz     = max(0.1, min(10.0, float(_cfg.get("sensor_read_hz", 2.0))))
POLL_S  = 1.0 / _hz

_SQLITE_PATH = _cfg.get("sqlite_path", "data/rover_logs.sqlite")

# ─────────────────────────────────────────────────────────────────────────────
# SQLite helper — called once per poll cycle
# ─────────────────────────────────────────────────────────────────────────────

def _log_snap_to_sqlite(db: SQLiteLogger, snap: dict) -> None:
    """Write one unified telemetry row per poll cycle, then commit."""
    db.log_telemetry(snap, snap.get("validation") or {})
    db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Sensor loop (daemon thread)
# ─────────────────────────────────────────────────────────────────────────────

def sensor_loop(db: SQLiteLogger) -> None:
    # ── Setup sensor stack ────────────────────────────────────────────────────
    if USE_REAL_SENSORS:
        _stack.setup(
            tmp_address   = _cfg.get("i2c_tmp102_address",  0x48),
            tmp_bus       = _cfg.get("i2c_bus",              1),
            gps_port      = _cfg.get("gps_port",             "/dev/ttyUSB0"),
            gps_baud      = _cfg.get("gps_baud",             9600),
            air_port      = _cfg.get("air_port",             "/dev/ttyAMA0"),
            air_baud      = _cfg.get("air_baud",             9600),
            power_port    = _cfg.get("power_port",           "/dev/ttyAMA10"),
            power_baud    = _cfg.get("power_baud",           9600),
            power_de_pin  = _cfg.get("power_de_re_pin",      17),
            power_modbus  = _cfg.get("power_modbus_addr",    1),
            adc_address   = _cfg.get("i2c_ads1115_address",  0x49),
            adc_ch_moist  = 1,
            adc_dry_ref   = _cfg.get("soil_dry_ref",         800),
            adc_wet_ref   = _cfg.get("soil_wet_ref",         300),
        )
    else:
        _stack.setup(fail_prob=0.01)

    mode = "real" if USE_REAL_SENSORS else "dev"
    logger_dev.log_event(f"sensor_loop started ({mode} mode, {_hz:.1f} Hz)")
    db.event("INFO", "main", "sensor_loop started",
             {"mode": mode, "poll_hz": _hz, "poll_s": POLL_S})

    # ── Poll loop ─────────────────────────────────────────────────────────────
    while True:
        snap = _stack.read_all()
        snap["schema_version"] = 1

        tools  = (snap.get("data", {}).get("mega") or {}).get("tools", {})
        timers = (snap.get("data") or {}).get("timers", {})
        snap["validation"] = compute_validation(tools, timers)

        # JSONL log — unconditional, every poll cycle (rule 18)
        logger_dev.log_snapshot(snap)

        # SQLite log — unconditional; errors are caught so the loop never dies
        try:
            _log_snap_to_sqlite(db, snap)
        except Exception:
            pass  # DB failure must not stop sensor collection

        # Update Flask snapshot
        set_latest(snap)

        time.sleep(POLL_S)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    db = SQLiteLogger(_SQLITE_PATH)
    db.start(notes=f"HERC-26 rover telemetry — {'real' if USE_REAL_SENSORS else 'dev'} mode")

    t = threading.Thread(target=sensor_loop, args=(db,), daemon=True)
    t.start()

    try:
        # Development (laptop): host="127.0.0.1" — local machine only.
        # Raspberry Pi / tablet access: change to host="0.0.0.0".
        app.run(host="127.0.0.1", port=5000, debug=False)
    finally:
        db.close()


if __name__ == "__main__":
    main()
