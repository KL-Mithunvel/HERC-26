# logger/sqlite_db.py
# SQLite logger + schema creation in Python (no separate .sql file)

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
    - Opens/creates SQLite DB
    - Creates tables in Python (no schema.sql needed)
    - Migrates existing DBs to add new columns when needed
    - Creates a session_id per boot/run
    - Provides methods to write events + telemetry rows
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

        # Basic reliability/performance settings
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")

        # Create schema and run migrations
        self._create_schema()
        self._migrate()

        # Create session
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
        """Commit any pending telemetry INSERTs.  Call once per poll cycle."""
        if self.conn:
            self.conn.commit()

    # -------------------------
    # Schema
    # -------------------------
    def _create_schema(self) -> None:
        assert self.conn is not None

        # sessions
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              session_id TEXT PRIMARY KEY,
              started_utc TEXT NOT NULL,
              notes TEXT
            );
            """
        )

        # events (state messages, warnings, errors, etc.)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              level TEXT NOT NULL,
              source TEXT NOT NULL,
              message TEXT NOT NULL,
              data_json TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: TMP102
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_tmp102 (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              temp_c REAL,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: BNO055
        # Includes euler angles (populated once imu.py reads them) and
        # g_force / velocity (populated now by the current imu.py driver).
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_bno055 (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              roll_deg REAL,
              pitch_deg REAL,
              yaw_deg REAL,
              g_force REAL,
              vel_x REAL,
              vel_y REAL,
              vel_z REAL,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: GPS
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_gps (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              lat REAL,
              lon REAL,
              speed_mps REAL,
              sats INTEGER,
              hdop REAL,
              fix INTEGER,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: PZEM-017 power meter
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_power (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              voltage_v REAL,
              current_a REAL,
              power_w REAL,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: MH-Z19C CO2 air quality
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_air (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              co2_ppm INTEGER,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: ADS1115 ADC (soil moisture)
        # Note: pH channel removed from this module (DFRobot V1.1 replaced).
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_adc (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              raw_moisture INTEGER,
              v_moisture REAL,
              moisture_value REAL,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # telemetry: Arduino Mega (tool states + movement)
        # Populated once the Mega driver is ready; until then every row is
        # written with quality="offline".
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_mega (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              air_on INTEGER,
              water_on INTEGER,
              soil_on INTEGER,
              ibus_pulse INTEGER,
              movement TEXT,
              quality TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );
            """
        )

        # Indexes
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tmp_ts      ON telemetry_tmp102(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bno_ts      ON telemetry_bno055(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_gps_ts      ON telemetry_gps(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_power_ts    ON telemetry_power(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_air_ts      ON telemetry_air(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_adc_ts      ON telemetry_adc(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_mega_ts     ON telemetry_mega(ts_utc);")

        self.conn.commit()

    def _migrate(self) -> None:
        """
        Add columns that exist in the current schema but may be absent in
        databases created by an older version of this file.
        Each ALTER TABLE is wrapped in try/except so it is a no-op when the
        column already exists.
        """
        assert self.conn is not None
        migrations = [
            # bno055: g_force and velocity added after initial schema
            "ALTER TABLE telemetry_bno055 ADD COLUMN g_force REAL",
            "ALTER TABLE telemetry_bno055 ADD COLUMN vel_x   REAL",
            "ALTER TABLE telemetry_bno055 ADD COLUMN vel_y   REAL",
            "ALTER TABLE telemetry_bno055 ADD COLUMN vel_z   REAL",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists — safe to ignore
        self.conn.commit()

    # -------------------------
    # Writes
    # -------------------------
    def event(self, level: str, source: str, message: str, data: dict | None) -> None:
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

    def log_tmp102(self, temp_c: float | None, quality: str) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_tmp102(ts_utc, session_id, temp_c, quality)
            VALUES(?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, temp_c, quality),
        )

    def log_bno055(
        self,
        roll: float | None,
        pitch: float | None,
        yaw: float | None,
        g_force: float | None,
        vel_x: float | None,
        vel_y: float | None,
        vel_z: float | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_bno055
              (ts_utc, session_id, roll_deg, pitch_deg, yaw_deg,
               g_force, vel_x, vel_y, vel_z, quality)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id,
             roll, pitch, yaw, g_force, vel_x, vel_y, vel_z, quality),
        )

    def log_gps(
        self,
        lat: float | None,
        lon: float | None,
        speed_mps: float | None,
        sats: int | None,
        hdop: float | None,
        fix: int | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_gps
              (ts_utc, session_id, lat, lon, speed_mps, sats, hdop, fix, quality)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, lat, lon, speed_mps, sats, hdop, fix, quality),
        )

    def log_power(
        self,
        voltage_v: float | None,
        current_a: float | None,
        power_w: float | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_power
              (ts_utc, session_id, voltage_v, current_a, power_w, quality)
            VALUES(?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, voltage_v, current_a, power_w, quality),
        )

    def log_air(self, co2_ppm: int | None, quality: str) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_air(ts_utc, session_id, co2_ppm, quality)
            VALUES(?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, co2_ppm, quality),
        )

    def log_adc(
        self,
        raw_moisture: int | None,
        v_moisture: float | None,
        moisture_value: float | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_adc
              (ts_utc, session_id, raw_moisture, v_moisture, moisture_value, quality)
            VALUES(?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, raw_moisture, v_moisture, moisture_value, quality),
        )

    def log_mega(
        self,
        air_on: bool | None,
        water_on: bool | None,
        soil_on: bool | None,
        ibus_pulse: int | None,
        movement: str | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_mega
              (ts_utc, session_id, air_on, water_on, soil_on, ibus_pulse, movement, quality)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                utc_now_iso(), self.session_id,
                int(air_on) if air_on is not None else None,
                int(water_on) if water_on is not None else None,
                int(soil_on) if soil_on is not None else None,
                ibus_pulse, movement, quality,
            ),
        )
