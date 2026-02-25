# logger/sqlite_db.py
# SQLite logger — single unified telemetry table.
# One row per poll cycle holds every sensor reading + validation state.
# Error sentinel: -1 for all numeric columns (never NULL).

import os
import sqlite3
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteLogger:
    """
    Opens/creates the rover SQLite database.
    Schema: sessions, events, and one unified telemetry table.
    All numeric fields use -1 as the error/offline sentinel (never NULL).
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.session_id: Optional[str] = None

    # -------------------------
    # Lifecycle
    # -------------------------
    def start(self, notes: str = "") -> str:
        Path(os.path.dirname(self.db_path) or ".").mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")

        self._create_schema()
        self._migrate()

        self.session_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO sessions(session_id, started_utc, notes) VALUES(?,?,?)",
            (self.session_id, utc_now_iso(), notes),
        )
        self.conn.commit()

        self.event("INFO", "logger", "SQLite logger started", {"db_path": self.db_path})
        return self.session_id

    def close(self) -> None:
        if self.conn:
            try:
                self.event("INFO", "logger", "SQLite logger closed", None)
                self.conn.commit()
            finally:
                self.conn.close()
                self.conn = None
                self.session_id = None

    def flush(self) -> None:
        """Commit pending INSERTs. Call once per poll cycle."""
        if self.conn:
            self.conn.commit()

    # -------------------------
    # Schema
    # -------------------------
    def _create_schema(self) -> None:
        assert self.conn is not None

        # --- sessions ---
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id  TEXT PRIMARY KEY,
              started_utc TEXT NOT NULL,
              notes       TEXT
            );
            """
        )

        # --- events (state transitions, warnings, errors) ---
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc     TEXT NOT NULL,
              session_id TEXT NOT NULL,
              level      TEXT NOT NULL,
              source     TEXT NOT NULL,
              message    TEXT NOT NULL,
              data_json  TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # --- unified telemetry ---
        # One row per poll cycle. Every sensor in every row.
        # Numeric columns: -1 = error or offline sentinel (never NULL).
        # Quality columns: "ok" | "error" | "offline"
        # Phase columns:   "off" | "waiting" | "stabilizing" | "valid_window" | "done"
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc      TEXT    NOT NULL,
              session_id  TEXT    NOT NULL,

              -- Temperature (TMP102, I2C 0x48)
              temp_c              REAL    NOT NULL DEFAULT -1,
              temp_quality        TEXT    NOT NULL DEFAULT 'offline',

              -- IMU (BNO055, I2C 0x28)
              imu_roll_deg        REAL    NOT NULL DEFAULT -1,
              imu_pitch_deg       REAL    NOT NULL DEFAULT -1,
              imu_yaw_deg         REAL    NOT NULL DEFAULT -1,
              imu_g_force         REAL    NOT NULL DEFAULT -1,
              imu_vel_x           REAL    NOT NULL DEFAULT -1,
              imu_vel_y           REAL    NOT NULL DEFAULT -1,
              imu_vel_z           REAL    NOT NULL DEFAULT -1,
              imu_quality         TEXT    NOT NULL DEFAULT 'offline',

              -- GPS (serial NMEA)
              gps_lat             REAL    NOT NULL DEFAULT -1,
              gps_lon             REAL    NOT NULL DEFAULT -1,
              gps_speed_mps       REAL    NOT NULL DEFAULT -1,
              gps_sats            INTEGER NOT NULL DEFAULT -1,
              gps_fix             INTEGER NOT NULL DEFAULT -1,
              gps_quality         TEXT    NOT NULL DEFAULT 'offline',

              -- Power meter (PZEM-017, RS485)
              power_voltage_v     REAL    NOT NULL DEFAULT -1,
              power_current_a     REAL    NOT NULL DEFAULT -1,
              power_w             REAL    NOT NULL DEFAULT -1,
              power_quality       TEXT    NOT NULL DEFAULT 'offline',

              -- Air / CO2 (MH-Z19C) + validation
              co2_ppm             INTEGER NOT NULL DEFAULT -1,
              air_quality         TEXT    NOT NULL DEFAULT 'offline',
              air_phase           TEXT    NOT NULL DEFAULT 'off',
              air_valid           INTEGER NOT NULL DEFAULT 0,
              air_samples_left    INTEGER NOT NULL DEFAULT 0,

              -- Soil moisture (ADS1115, I2C) + validation
              soil_raw            INTEGER NOT NULL DEFAULT -1,
              soil_voltage_v      REAL    NOT NULL DEFAULT -1,
              soil_moisture_pct   REAL    NOT NULL DEFAULT -1,
              soil_quality        TEXT    NOT NULL DEFAULT 'offline',
              soil_phase          TEXT    NOT NULL DEFAULT 'off',
              soil_valid          INTEGER NOT NULL DEFAULT 0,
              soil_samples_left   INTEGER NOT NULL DEFAULT 0,

              -- Water / pH + validation
              water_ph            REAL    NOT NULL DEFAULT -1,
              water_quality       TEXT    NOT NULL DEFAULT 'offline',
              water_phase         TEXT    NOT NULL DEFAULT 'off',
              water_valid         INTEGER NOT NULL DEFAULT 0,
              water_samples_left  INTEGER NOT NULL DEFAULT 0,

              -- Arduino Mega (tool states + movement)
              mega_air_on         INTEGER NOT NULL DEFAULT -1,
              mega_water_on       INTEGER NOT NULL DEFAULT -1,
              mega_soil_on        INTEGER NOT NULL DEFAULT -1,
              mega_ibus_pulse     INTEGER NOT NULL DEFAULT -1,
              mega_movement       TEXT    NOT NULL DEFAULT 'UNKNOWN',
              mega_quality        TEXT    NOT NULL DEFAULT 'offline',

              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(ts_utc);")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_air_valid  ON telemetry(air_valid);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_soil_valid ON telemetry(soil_valid);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_water_valid ON telemetry(water_valid);"
        )

        self.conn.commit()

    def _migrate(self) -> None:
        """
        Ensures the unified telemetry table exists in databases created before
        this schema revision. Each statement is a no-op if already present.
        """
        assert self.conn is not None
        # If an old DB only has the per-sensor tables, create the new unified one.
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL, session_id TEXT NOT NULL,
              temp_c REAL NOT NULL DEFAULT -1, temp_quality TEXT NOT NULL DEFAULT 'offline',
              imu_roll_deg REAL NOT NULL DEFAULT -1, imu_pitch_deg REAL NOT NULL DEFAULT -1,
              imu_yaw_deg REAL NOT NULL DEFAULT -1, imu_g_force REAL NOT NULL DEFAULT -1,
              imu_vel_x REAL NOT NULL DEFAULT -1, imu_vel_y REAL NOT NULL DEFAULT -1,
              imu_vel_z REAL NOT NULL DEFAULT -1, imu_quality TEXT NOT NULL DEFAULT 'offline',
              gps_lat REAL NOT NULL DEFAULT -1, gps_lon REAL NOT NULL DEFAULT -1,
              gps_speed_mps REAL NOT NULL DEFAULT -1, gps_sats INTEGER NOT NULL DEFAULT -1,
              gps_fix INTEGER NOT NULL DEFAULT -1, gps_quality TEXT NOT NULL DEFAULT 'offline',
              power_voltage_v REAL NOT NULL DEFAULT -1, power_current_a REAL NOT NULL DEFAULT -1,
              power_w REAL NOT NULL DEFAULT -1, power_quality TEXT NOT NULL DEFAULT 'offline',
              co2_ppm INTEGER NOT NULL DEFAULT -1, air_quality TEXT NOT NULL DEFAULT 'offline',
              air_phase TEXT NOT NULL DEFAULT 'off', air_valid INTEGER NOT NULL DEFAULT 0,
              air_samples_left INTEGER NOT NULL DEFAULT 0,
              soil_raw INTEGER NOT NULL DEFAULT -1, soil_voltage_v REAL NOT NULL DEFAULT -1,
              soil_moisture_pct REAL NOT NULL DEFAULT -1, soil_quality TEXT NOT NULL DEFAULT 'offline',
              soil_phase TEXT NOT NULL DEFAULT 'off', soil_valid INTEGER NOT NULL DEFAULT 0,
              soil_samples_left INTEGER NOT NULL DEFAULT 0,
              water_ph REAL NOT NULL DEFAULT -1, water_quality TEXT NOT NULL DEFAULT 'offline',
              water_phase TEXT NOT NULL DEFAULT 'off', water_valid INTEGER NOT NULL DEFAULT 0,
              water_samples_left INTEGER NOT NULL DEFAULT 0,
              mega_air_on INTEGER NOT NULL DEFAULT -1, mega_water_on INTEGER NOT NULL DEFAULT -1,
              mega_soil_on INTEGER NOT NULL DEFAULT -1, mega_ibus_pulse INTEGER NOT NULL DEFAULT -1,
              mega_movement TEXT NOT NULL DEFAULT 'UNKNOWN', mega_quality TEXT NOT NULL DEFAULT 'offline',
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )
        # Add indexes if missing (safe to run repeatedly)
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_telemetry_ts          ON telemetry(ts_utc);",
            "CREATE INDEX IF NOT EXISTS idx_telemetry_air_valid   ON telemetry(air_valid);",
            "CREATE INDEX IF NOT EXISTS idx_telemetry_soil_valid  ON telemetry(soil_valid);",
            "CREATE INDEX IF NOT EXISTS idx_telemetry_water_valid ON telemetry(water_valid);",
        ]:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass
        self.conn.commit()

    # -------------------------
    # Writes
    # -------------------------
    def event(self, level: str, source: str, message: str, data: dict | None) -> None:
        """Write a state-transition event. Commits immediately. Do NOT call per tick."""
        assert self.conn and self.session_id
        data_json = None if data is None else json.dumps(data, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO events(ts_utc, session_id, level, source, message, data_json)
            VALUES(?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, level, source, message, data_json),
        )
        self.conn.commit()

    def log_telemetry(self, snap: dict, validation: dict) -> None:
        """
        Write one unified telemetry row from a full snapshot dict + validation dict.
        Call this once per poll cycle, then call flush() to commit.

        snap:       the dict returned by dev_stack.read_all() (or real sensor stack)
        validation: the dict returned by compute_validation()
        """
        assert self.conn and self.session_id

        data   = snap.get("data") or {}
        errors = snap.get("errors") or {}

        def _q(name: str) -> str:
            """Derive quality string from the snapshot errors/data dicts."""
            if name in errors:
                return "error"
            if name in data:
                return "ok"
            return "offline"

        def _n(val, default: float | int = -1) -> float | int:
            """Return val when present, else the -1 sentinel."""
            return val if val is not None else default

        # ---- extract sub-dicts ----
        tmp       = data.get("temperature") or {}
        imu       = data.get("imu")         or {}
        imu_or    = imu.get("orientation")  or {}
        imu_vel   = imu.get("velocity")     or {}
        gps       = data.get("gps")         or {}
        pwr       = data.get("power")       or {}
        air_d     = data.get("air")         or {}
        adc       = data.get("adc")         or {}
        adc_raw   = adc.get("raw")          or {}
        adc_sv    = adc.get("sensor_voltage") or {}
        mega      = data.get("mega")        or {}
        mega_t    = mega.get("tools")       or {}

        # ---- validation sub-dicts ----
        air_v   = validation.get("air")   or {}
        soil_v  = validation.get("soil")  or {}
        water_v = validation.get("water") or {}

        self.conn.execute(
            """
            INSERT INTO telemetry (
              ts_utc, session_id,

              temp_c, temp_quality,

              imu_roll_deg, imu_pitch_deg, imu_yaw_deg,
              imu_g_force, imu_vel_x, imu_vel_y, imu_vel_z, imu_quality,

              gps_lat, gps_lon, gps_speed_mps, gps_sats, gps_fix, gps_quality,

              power_voltage_v, power_current_a, power_w, power_quality,

              co2_ppm, air_quality, air_phase, air_valid, air_samples_left,

              soil_raw, soil_voltage_v, soil_moisture_pct,
              soil_quality, soil_phase, soil_valid, soil_samples_left,

              water_ph, water_quality, water_phase, water_valid, water_samples_left,

              mega_air_on, mega_water_on, mega_soil_on,
              mega_ibus_pulse, mega_movement, mega_quality
            ) VALUES (
              ?,?,
              ?,?,
              ?,?,?,?,?,?,?,?,
              ?,?,?,?,?,?,
              ?,?,?,?,
              ?,?,?,?,?,
              ?,?,?,?,?,?,?,
              ?,?,?,?,?,
              ?,?,?,?,?,?
            )
            """,
            (
                utc_now_iso(), self.session_id,

                # temperature
                _n(tmp.get("temp_c")),          _q("temperature"),

                # imu
                _n(imu_or.get("roll")),
                _n(imu_or.get("pitch")),
                _n(imu_or.get("yaw")),
                _n(imu.get("g_force")),
                _n(imu_vel.get("x")),
                _n(imu_vel.get("y")),
                _n(imu_vel.get("z")),
                _q("imu"),

                # gps
                _n(gps.get("lat")),
                _n(gps.get("lon")),
                _n(gps.get("speed_mps")),
                _n(gps.get("sats")),
                _n(gps.get("fix")),
                _q("gps"),

                # power
                _n(pwr.get("voltage_v")),
                _n(pwr.get("current_a")),
                _n(pwr.get("power_w")),
                _q("power"),

                # air + validation
                _n(air_d.get("co2_ppm")),
                _q("air"),
                air_v.get("phase", "off"),
                1 if air_v.get("valid_sample") else 0,
                _n(air_v.get("samples_left"), 0),

                # soil + validation
                _n(adc_raw.get("moisture")),
                _n(adc_sv.get("moisture")),
                _n(adc.get("moisture_value")),
                _q("adc"),
                soil_v.get("phase", "off"),
                1 if soil_v.get("valid_sample") else 0,
                _n(soil_v.get("samples_left"), 0),

                # water/pH + validation
                _n(adc.get("ph_value")),
                "offline",                          # water_quality: offline until pH sensor is back
                water_v.get("phase", "off"),
                1 if water_v.get("valid_sample") else 0,
                _n(water_v.get("samples_left"), 0),

                # mega
                int(mega_t.get("air",   False)),
                int(mega_t.get("water", False)),
                int(mega_t.get("soil",  False)),
                _n(mega.get("ibus_pulse")),
                mega.get("movement", "UNKNOWN"),
                _q("mega"),
            ),
        )
