"""
main.py — Raspberry Pi deployment entry point
==============================================
Uses real hardware sensor drivers (real_stack). Run ONLY on the Raspberry Pi.

    python main.py
    Dashboard accessible from any browser on Wi-Fi: http://<pi-ip>:5000

For development on a laptop with simulated data, use main_sim.py instead.
"""
import time
import threading
import traceback
import socket
import logging

# real_stack is Pi-only — see sensor/real_stack.py
from sensor import real_stack as _stack
from spanner import logger_dev
from web.app import app, set_latest, register_stack
from spanner.validation import compute_validation, configure_validation
from logger.sqlite_db import SQLiteLogger
from calibration.config_reader import load_config

# ─────────────────────────────────────────────────────────────────────────────
# Config — config.xml is required on the Pi
# ─────────────────────────────────────────────────────────────────────────────
_cfg = load_config()

configure_validation(_cfg)   # apply timing from config.xml before loop starts

_hz          = max(0.1, min(10.0, float(_cfg.get("sensor_read_hz", 2.0))))
POLL_S       = 1.0 / _hz
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
    _stack.setup(
        tmp_address   = _cfg.get("i2c_tmp102_address",  0x48),
        tmp_bus       = _cfg.get("i2c_bus",              1),
        gps_port      = _cfg.get("gps_port",             "/dev/ttyUSB0"),
        gps_baud      = _cfg.get("gps_baud",             9600),
        air_port      = _cfg.get("air_port",             "/dev/ttyAMA0"),
        air_baud      = _cfg.get("air_baud",             9600),
        # ADS1115 shared by soil (A0), pH (A1), battery (A2) — all GAIN_1
        adc_address   = _cfg.get("i2c_ads1115_address",  0x49),
        soil_channel  = 0,
        soil_dry_ref  = _cfg.get("soil_dry_ref",         800),
        soil_wet_ref  = _cfg.get("soil_wet_ref",         300),
        ph_channel    = 1,
        batt_channel  = 2,
        mega_port     = _cfg.get("mega_port",            "/dev/ttyACM0"),
        mega_baud     = _cfg.get("mega_baud",            115200),
    )
    logger_dev.log_event(f"sensor_loop started (real mode, {_hz:.1f} Hz)")
    db.event("INFO", "main", "sensor_loop started",
             {"mode": "real", "poll_hz": _hz, "poll_s": POLL_S})

    # ── Poll loop ─────────────────────────────────────────────────────────────
    while True:
        snap = None

        # Phase 1: read snapshot + compute validation.
        # Separated so a programming error here doesn't silently freeze the UI —
        # the full traceback is logged and the loop continues.
        try:
            snap = _stack.read_all()
            snap["schema_version"] = 1

            tools  = (snap.get("data", {}).get("mega") or {}).get("tools", {})
            timers = (snap.get("data") or {}).get("timers", {})
            snap["validation"] = compute_validation(tools, timers)
        except Exception as _loop_err:
            logger_dev.log_event(
                f"sensor_loop read error: {_loop_err}\n"
                + traceback.format_exc()
            )

        # Phase 2: log + update Flask — only when we have a valid snapshot.
        if snap is not None:
            try:
                logger_dev.log_snapshot(snap)
            except Exception as _log_err:
                logger_dev.log_event(f"JSONL write error: {_log_err}")

            try:
                _log_snap_to_sqlite(db, snap)
            except Exception as _db_err:
                logger_dev.log_event(f"SQLite write error: {_db_err}")

            set_latest(snap)

        time.sleep(POLL_S)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def _get_network_ip() -> str:
    """Return the Pi's outward-facing LAN IP (not loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def main():
    register_stack(_stack)   # wire real_stack into Flask routes

    db = SQLiteLogger(_SQLITE_PATH)
    db.start(notes="HERC-26 rover telemetry — real hardware")

    t = threading.Thread(target=sensor_loop, args=(db,), daemon=True)
    t.start()

    # Suppress Werkzeug's duplicate startup lines; print only the useful one.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"Dashboard: http://{_get_network_ip()}:5000")

    try:
        app.run(host="0.0.0.0", port=5000, debug=False)
    finally:
        db.close()


if __name__ == "__main__":
    main()
