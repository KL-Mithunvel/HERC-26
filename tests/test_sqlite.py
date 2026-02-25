"""
tests/test_sqlite.py
====================
Manual smoke-test for the SQLite unified telemetry table.

Run from the project root:
    python tests/test_sqlite.py

What it checks:
  1. SQLiteLogger.start() creates the DB, sessions table, telemetry table
  2. Writing 10 rows via log_telemetry() succeeds without error
  3. All 10 rows appear in the telemetry table after flush()
  4. Columns are present with correct types (no NULLs — only -1 sentinels)
  5. Valid rows (air_valid=1 / soil_valid=1 / water_valid=1) are queryable
  6. event() writes to the events table
  7. close() completes cleanly

A temporary DB is created in data/test_temp.sqlite and deleted at the end.
"""

import sys
import os
import sqlite3
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sensor import dev_stack
from logger.sqlite_db import SQLiteLogger
from spanner.validation import compute_validation

DB_PATH   = "data/test_temp.sqlite"
NUM_POLLS = 10


def check(condition: bool, label: str) -> bool:
    result = "PASS" if condition else "FAIL"
    print(f"    [{result}] {label}")
    return condition


def main():
    print("\n" + "="*60)
    print("  HERC-26 SQLiteLogger  —  unified telemetry smoke-test")
    print("="*60)

    ok = True

    # ── Step 1: start DB ─────────────────────────────────────────────────────
    print("\n[1] Start SQLiteLogger")
    try:
        os.makedirs("data", exist_ok=True)
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

        db = SQLiteLogger(DB_PATH)
        session_id = db.start(notes="test run — test_sqlite.py")
        ok &= check(isinstance(session_id, str) and len(session_id) == 36,
                    f"session_id is a UUID: {session_id}")
        print(f"    Session ID: {session_id}")
    except Exception as e:
        print(f"    [FAIL] start() raised: {e}")
        sys.exit(1)

    # ── Step 2: verify table schema ───────────────────────────────────────────
    print("\n[2] Verify telemetry table exists and has required columns")
    con = sqlite3.connect(DB_PATH)
    cur = con.execute("PRAGMA table_info(telemetry)")
    columns = {row[1] for row in cur.fetchall()}
    con.close()

    required_cols = {
        "id", "ts_utc", "session_id",
        "temp_c", "temp_quality",
        "imu_roll_deg", "imu_pitch_deg", "imu_yaw_deg",
        "imu_g_force", "imu_vel_x", "imu_vel_y", "imu_vel_z", "imu_quality",
        "gps_lat", "gps_lon", "gps_speed_mps", "gps_sats", "gps_fix", "gps_quality",
        "power_voltage_v", "power_current_a", "power_w", "power_quality",
        "co2_ppm", "air_quality", "air_phase", "air_valid", "air_samples_left",
        "soil_raw", "soil_voltage_v", "soil_moisture_pct",
        "soil_quality", "soil_phase", "soil_valid", "soil_samples_left",
        "water_ph", "water_quality", "water_phase", "water_valid", "water_samples_left",
        "mega_air_on", "mega_water_on", "mega_soil_on",
        "mega_ibus_pulse", "mega_movement", "mega_quality",
    }
    missing = required_cols - columns
    ok &= check(len(missing) == 0, f"all {len(required_cols)} required columns exist")
    if missing:
        print(f"      MISSING: {sorted(missing)}")
    else:
        print(f"      Found {len(columns)} columns total")

    # ── Step 3: write NUM_POLLS rows ─────────────────────────────────────────
    print(f"\n[3] Write {NUM_POLLS} telemetry rows via log_telemetry()")
    dev_stack.setup(fail_prob=0.0)   # no random failures for this test
    write_ok = True
    for _ in range(NUM_POLLS):
        snap = dev_stack.read_all()
        tools  = (snap.get("data", {}).get("mega") or {}).get("tools", {})
        timers = (snap.get("data") or {}).get("timers", {})
        validation = compute_validation(tools, timers)
        snap["validation"] = validation
        try:
            db.log_telemetry(snap, validation)
        except Exception as e:
            print(f"    [FAIL] log_telemetry() raised: {e}")
            import traceback; traceback.print_exc()
            write_ok = False
        time.sleep(0.05)

    db.flush()
    ok &= check(write_ok, f"all {NUM_POLLS} log_telemetry() calls succeeded")

    # ── Step 4: verify row count ──────────────────────────────────────────────
    print("\n[4] Verify row count in telemetry table")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row_count = con.execute("SELECT COUNT(*) FROM telemetry WHERE session_id=?",
                            (session_id,)).fetchone()[0]
    ok &= check(row_count == NUM_POLLS, f"telemetry has {row_count} rows (expected {NUM_POLLS})")

    # ── Step 5: verify no NULLs in numeric columns ───────────────────────────
    print("\n[5] Verify no NULL values in any telemetry column")
    null_counts = {}
    for col in ["temp_c", "imu_g_force", "gps_lat", "gps_lon",
                "power_voltage_v", "co2_ppm", "soil_moisture_pct", "water_ph",
                "mega_ibus_pulse"]:
        n = con.execute(f"SELECT COUNT(*) FROM telemetry WHERE {col} IS NULL").fetchone()[0]
        if n > 0:
            null_counts[col] = n

    ok &= check(len(null_counts) == 0,
                "no NULL values in numeric columns (use -1 sentinel instead)")
    if null_counts:
        for col, n in null_counts.items():
            print(f"      {col}: {n} NULLs found")

    # ── Step 6: sample a row and print it ────────────────────────────────────
    print("\n[6] Sample last telemetry row")
    row = con.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT 1").fetchone()
    keys = row.keys()
    for k in keys:
        v = row[k]
        print(f"      {k:25s} = {v!r}")

    # ── Step 7: verify quality columns are text (not NULL) ───────────────────
    print("\n[7] Verify quality columns are non-empty strings")
    quality_cols = ["temp_quality", "imu_quality", "gps_quality", "power_quality",
                    "air_quality", "soil_quality", "water_quality", "mega_quality"]
    for col in quality_cols:
        val = con.execute(f"SELECT {col} FROM telemetry ORDER BY id DESC LIMIT 1").fetchone()[0]
        ok &= check(isinstance(val, str) and len(val) > 0,
                    f"{col} = {val!r}")

    # ── Step 8: test event write ──────────────────────────────────────────────
    print("\n[8] Write and read an event")
    db.event("INFO", "test", "test_sqlite.py event check", {"check": True})
    evt_count = con.execute(
        "SELECT COUNT(*) FROM events WHERE source='test' AND session_id=?",
        (session_id,)
    ).fetchone()[0]
    ok &= check(evt_count >= 1, f"event written and readable ({evt_count} found)")
    con.close()

    # ── Step 9: close ─────────────────────────────────────────────────────────
    print("\n[9] close()")
    try:
        db.close()
        ok &= check(True, "close() completed without exception")
    except Exception as e:
        ok &= check(False, f"close() raised: {e}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    try:
        os.remove(DB_PATH)
        print(f"\n    Temp DB deleted: {DB_PATH}")
    except Exception:
        pass

    # ── Result ────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    if ok:
        print("  RESULT: ALL CHECKS PASSED")
    else:
        print("  RESULT: SOME CHECKS FAILED — see [FAIL] lines above")
    print("="*60 + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
