# rovercore/logging/sqlite_db.py
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

        # Create schema
        self._create_schema()

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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_bno055 (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_utc TEXT NOT NULL,
              session_id TEXT NOT NULL,
              roll_deg REAL,
              pitch_deg REAL,
              yaw_deg REAL,
              calib_sys INTEGER,
              calib_gyr INTEGER,
              calib_acc INTEGER,
              calib_mag INTEGER,
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

        # Indexes (helpful for quick viewing)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_tmp_ts ON telemetry_tmp102(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bno_ts ON telemetry_bno055(ts_utc);")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_gps_ts ON telemetry_gps(ts_utc);")

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
        cs: int | None,
        cg: int | None,
        ca: int | None,
        cm: int | None,
        quality: str,
    ) -> None:
        assert self.conn and self.session_id
        self.conn.execute(
            """
            INSERT INTO telemetry_bno055
              (ts_utc, session_id, roll_deg, pitch_deg, yaw_deg,
               calib_sys, calib_gyr, calib_acc, calib_mag, quality)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (utc_now_iso(), self.session_id, roll, pitch, yaw, cs, cg, ca, cm, quality),
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
