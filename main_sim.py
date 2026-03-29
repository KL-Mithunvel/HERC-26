"""
ain_sim.py — Development entry point (laptop / Windows / Linux)
================================================================
Uses simulated sensor data (dev_stack). Safe to run on any machine.

    python main_sim.py
    Dashboard: http://127.0.0.1:5000

For Raspberry Pi deployment with real hardware, use main.py instead.
"""
import time
import threading

from sensor import dev_stack as _stack
from spanner import logger_dev
from web.app import app, set_latest, register_stack
from spanner.validation import compute_validation
from logger.sqlite_db import SQLiteLogger

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
try:
    from calibration.config_reader import load_config
    _cfg = load_config()
except Exception as _e:
    print(f"[main_sim] WARNING: config.xml load failed ({_e}) — using built-in defaults")
    _cfg = {}

_hz          = max(0.1, min(10.0, float(_cfg.get("sensor_read_hz", 2.0))))
POLL_S       = 1.0 / _hz
_SQLITE_PATH = _cfg.get("sqlite_path", "data/dev_logs.sqlite")


# ─────────────────────────────────────────────────────────────────────────────
# SQLite helper — called once per poll cycle
# ─────────────────────────────────────────────────────────────────────────────

def _log_snap_to_sqlite(db: SQLiteLogger, snap: dict) -> None:
    db.log_telemetry(snap, snap.get("validation") or {})
    db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Sensor loop (daemon thread)
# ─────────────────────────────────────────────────────────────────────────────

def sensor_loop(db: SQLiteLogger) -> None:
    _stack.setup(fail_prob=0.01)
    logger_dev.log_event(f"sensor_loop started (sim mode, {_hz:.1f} Hz)")
    db.event("INFO", "main_sim", "sensor_loop started",
             {"mode": "sim", "poll_hz": _hz, "poll_s": POLL_S})

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
        except Exception as _db_err:
            logger_dev.log_event(f"SQLite write error: {_db_err}")

        set_latest(snap)
        time.sleep(POLL_S)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    register_stack(_stack)   # explicit: confirm dev_stack is the active stack

    db = SQLiteLogger(_SQLITE_PATH)
    db.start(notes="HERC-26 rover telemetry — sim mode")

    t = threading.Thread(target=sensor_loop, args=(db,), daemon=True)
    t.start()

    try:
        # Local machine only — laptop development
        app.run(host="127.0.0.1", port=5000, debug=False)
    finally:
        db.close()


if __name__ == "__main__":
    main()
