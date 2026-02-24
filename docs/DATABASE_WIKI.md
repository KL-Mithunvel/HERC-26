# HERC-26 SQLite Database — Developer Wiki

This document covers every aspect of the rover's SQLite telemetry database:
schema, data formats, how to write, how to read, and how to extend it.

---

## Table of Contents

1. [Overview](#1-overview)
2. [File Paths](#2-file-paths)
3. [Opening the Database](#3-opening-the-database)
4. [Schema — All Tables](#4-schema--all-tables)
   - [sessions](#sessions)
   - [events](#events)
   - [telemetry_tmp102](#telemetry_tmp102)
   - [telemetry_bno055](#telemetry_bno055)
   - [telemetry_gps](#telemetry_gps)
   - [telemetry_power](#telemetry_power)
   - [telemetry_air](#telemetry_air)
   - [telemetry_adc](#telemetry_adc)
   - [telemetry_mega](#telemetry_mega)
5. [The `quality` Field](#5-the-quality-field)
6. [The Session Model](#6-the-session-model)
7. [Writing Data (Python)](#7-writing-data-python)
8. [Reading Data (Python + SQL)](#8-reading-data-python--sql)
9. [Log Viewer GUI](#9-log-viewer-gui)
10. [Design Rules](#10-design-rules)
11. [Adding a New Sensor](#11-adding-a-new-sensor)

---

## 1. Overview

The SQLite database is the **permanent mission record** for every HERC-26 run.

- Every poll cycle (default 2 Hz) writes one telemetry row per sensor into the DB.
- Alongside the JSONL file, it provides a queryable, structured archive.
- Both logging paths are **mandatory** and run unconditionally — they never skip a cycle regardless of sensor errors or UI state.
- The database is **session-based**: each time `main.py` starts, a new session UUID is created. All rows written in that run are linked to it.
- The live DB is gitignored. A pre-seeded example DB (`data/example_rover_logs.sqlite`) is checked in for reference and development.

---

## 2. File Paths

| File | Purpose | Tracked in git |
|---|---|---|
| `data/rover_logs.sqlite` | Live mission database — written during every run | **No** (gitignored) |
| `data/example_rover_logs.sqlite` | Pre-seeded reference DB with full schema + sample rows | **Yes** |

The live DB path is set in `calibration/config.xml`:

```xml
<database>
  <sqlite_path>data/rover_logs.sqlite</sqlite_path>
</database>
```

`main.py` reads this at startup via `calibration/config_reader.load_config()`.

---

## 3. Opening the Database

### Log Viewer GUI (recommended)

```bash
python logger/tools/log_viewer_gui.py
```

Opens a Tkinter table viewer with a dropdown for every sensor table. Use the **example DB** to verify layout without running the rover.

### Python (for scripts and analysis)

```python
import sqlite3
con = sqlite3.connect("data/rover_logs.sqlite")
con.row_factory = sqlite3.Row   # enables column-name access: row["temp_c"]
```

### DB Browser for SQLite (GUI tool)

Download from https://sqlitebrowser.org — open either DB file directly. Best for exploratory queries and visual schema inspection.

### Command-line (if sqlite3 is installed)

```bash
sqlite3 data/example_rover_logs.sqlite
.tables
.schema telemetry_tmp102
SELECT * FROM telemetry_tmp102 LIMIT 5;
.quit
```

---

## 4. Schema — All Tables

All timestamps (`ts_utc`) are **ISO 8601 UTC strings**, e.g. `2025-01-15T10:32:05.123456+00:00`.

All telemetry tables have the same three opening columns:

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment row ID |
| `ts_utc` | TEXT | Timestamp of the poll cycle (UTC ISO 8601) |
| `session_id` | TEXT FK | Links to `sessions.session_id` |

---

### `sessions`

One row per `main.py` launch. All telemetry rows in that run reference this row.

| Column | Type | Description |
|---|---|---|
| `session_id` | TEXT PK | UUID v4, e.g. `"a3f2c1d0-…"` |
| `started_utc` | TEXT | When `start()` was called (ISO 8601 UTC) |
| `notes` | TEXT | Free-text label — e.g. `"HERC-26 rover telemetry — dev mode"` |

---

### `events`

State transitions, warnings, and errors. Committed immediately (not batched).

| Column | Type | Description |
|---|---|---|
| `level` | TEXT | `"INFO"` \| `"WARNING"` \| `"ERROR"` |
| `source` | TEXT | Component name — `"main"`, `"logger"`, `"gps"`, `"imu"`, … |
| `message` | TEXT | Human-readable description |
| `data_json` | TEXT \| NULL | Optional JSON payload, e.g. `{"temp_c": 24.5}` |

**Example rows:**

```
INFO  | main   | sensor_loop started          | {"mode": "dev", "poll_hz": 2.0}
INFO  | logger | SQLite logger started        | {"db_path": "data/rover_logs.sqlite"}
ERROR | gps    | GPS fix void (status=V)      | null
INFO  | gps    | GPS fix recovered (status=A) | null
```

---

### `telemetry_tmp102`

TMP102 temperature sensor (I2C 0x48).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `temp_c` | REAL \| NULL | °C | −40 to +125 | NULL on sensor error |
| `quality` | TEXT | — | `"ok"` / `"error"` | See §5 |

**Example:**
```sql
SELECT ts_utc, temp_c, quality FROM telemetry_tmp102 ORDER BY id DESC LIMIT 3;
-- 2025-01-15T10:32:05+00:00 | 24.72 | ok
-- 2025-01-15T10:32:04+00:00 | 24.70 | ok
-- 2025-01-15T10:32:03+00:00 | NULL  | error
```

---

### `telemetry_bno055`

BNO055 IMU (I2C 0x28).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `roll_deg` | REAL \| NULL | ° | −180 to +180 | NULL until imu.py reads euler angles |
| `pitch_deg` | REAL \| NULL | ° | −90 to +90 | NULL until imu.py reads euler angles |
| `yaw_deg` | REAL \| NULL | ° | 0 to 360 | NULL until imu.py reads euler angles |
| `g_force` | REAL \| NULL | g | ~0 to ~4 | Magnitude of acceleration vector |
| `vel_x` | REAL \| NULL | m/s | — | Integrated from linear accel |
| `vel_y` | REAL \| NULL | m/s | — | |
| `vel_z` | REAL \| NULL | m/s | — | |
| `quality` | TEXT | — | `"ok"` / `"error"` | |

> **Note:** `roll_deg`, `pitch_deg`, `yaw_deg` are populated once `sensor/imu.py`
> is updated to read euler angles from `IMU.euler`. They are `NULL` in current
> firmware and are reserved for that upgrade.

**Example:**
```sql
SELECT ts_utc, g_force, vel_x, vel_y, vel_z FROM telemetry_bno055
ORDER BY id DESC LIMIT 1;
-- 2025-01-15T10:32:05+00:00 | 1.0032 | 0.0121 | -0.0043 | 0.0012
```

---

### `telemetry_gps`

GPS module (serial NMEA, GPRMC/GNRMC sentences).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `lat` | REAL \| NULL | ° | −90 to +90 | Decimal degrees, WGS-84 |
| `lon` | REAL \| NULL | ° | −180 to +180 | Decimal degrees, WGS-84 |
| `speed_mps` | REAL \| NULL | m/s | 0+ | NULL — not yet extracted from driver |
| `sats` | INTEGER \| NULL | — | 0–30 | NULL — not yet extracted from driver |
| `hdop` | REAL \| NULL | — | 0.5–99 | NULL — not yet extracted from driver |
| `fix` | INTEGER \| NULL | — | 0=none, 1=fix | NULL — not yet extracted from driver |
| `quality` | TEXT | — | `"ok"` / `"error"` | |

> **Note:** `speed_mps`, `sats`, `hdop`, `fix` are reserved columns populated
> once `gps.py` is updated to return them. Currently `NULL` in all rows.

**Example:**
```sql
SELECT ts_utc, lat, lon, quality FROM telemetry_gps
WHERE quality = 'ok' ORDER BY id DESC LIMIT 5;
```

---

### `telemetry_power`

PZEM-017 power meter (RS485 Modbus, `/dev/ttyAMA10`).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `voltage_v` | REAL \| NULL | V | 0–300 | 0.01 V resolution |
| `current_a` | REAL \| NULL | A | 0–100 | 0.01 A resolution |
| `power_w` | REAL \| NULL | W | 0–30,000 | 0.1 W resolution |
| `quality` | TEXT | — | `"ok"` / `"error"` | |

**Example:**
```sql
SELECT ts_utc, voltage_v, current_a, power_w
FROM telemetry_power WHERE quality = 'ok'
ORDER BY id DESC LIMIT 10;
```

Compute energy used during a session:
```sql
-- Approximate Wh: average power × total time span ÷ 3600
SELECT
  AVG(power_w)                                    AS avg_power_w,
  (julianday(MAX(ts_utc)) - julianday(MIN(ts_utc))) * 24 AS duration_h,
  AVG(power_w) * (julianday(MAX(ts_utc)) - julianday(MIN(ts_utc))) * 24 AS energy_wh
FROM telemetry_power
WHERE session_id = 'your-session-uuid-here' AND quality = 'ok';
```

---

### `telemetry_air`

MH-Z19C CO₂ sensor (UART `/dev/ttyAMA0`).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `co2_ppm` | INTEGER \| NULL | ppm | 0–10,000 | Sensor rejects values outside this range |
| `quality` | TEXT | — | `"ok"` / `"error"` | |

**Typical CO₂ values:**

| Environment | ppm |
|---|---|
| Fresh outdoor air | ~420 |
| Ventilated indoor | 600–1000 |
| Poorly ventilated | 1000–2000 |
| Sensor warming up | can read 0 |

**Example:**
```sql
SELECT ts_utc, co2_ppm FROM telemetry_air
WHERE quality = 'ok' AND co2_ppm > 600
ORDER BY id DESC LIMIT 20;
```

---

### `telemetry_adc`

ADS1115 ADC for soil moisture (I2C 0x49).
pH channel removed — DFRobot V1.1 sensor is being replaced.

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `raw_moisture` | INTEGER \| NULL | counts | 0–65535 | Raw 16-bit ADC value |
| `v_moisture` | REAL \| NULL | V | 0–3.3 | `raw × 3.3 / 32768` |
| `moisture_value` | REAL \| NULL | % | 0.0–100.0 | Calibrated: 0% = dry_ref, 100% = wet_ref |
| `quality` | TEXT | — | `"ok"` / `"error"` | |

**Calibration values** (set in `calibration/config.xml`):

| Constant | Default | Meaning |
|---|---|---|
| `dry_ref` | 800 | Raw ADC count when sensor is fully dry |
| `wet_ref` | 300 | Raw ADC count when sensor is fully wet |

Moisture formula:
```
moisture_value = clamp((dry_ref − raw) × 100 / (dry_ref − wet_ref), 0, 100)
```

**Example:**
```sql
SELECT ts_utc, raw_moisture, moisture_value
FROM telemetry_adc WHERE quality = 'ok'
ORDER BY id DESC LIMIT 10;
```

---

### `telemetry_mega`

Arduino Mega tool states and movement (populated once `mega.py` driver is ready).

| Column | Type | Unit | Range | Notes |
|---|---|---|---|---|
| `air_on` | INTEGER \| NULL | — | 0 / 1 | Air tool servo state |
| `water_on` | INTEGER \| NULL | — | 0 / 1 | Water tool servo state |
| `soil_on` | INTEGER \| NULL | — | 0 / 1 | Soil sample tool servo state |
| `ibus_pulse` | INTEGER \| NULL | µs | 1000–2000 | Raw iBUS RC pulse width; 1500 = centre |
| `movement` | TEXT \| NULL | — | see below | Drive direction string |
| `quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` | |

**`movement` values:**

| Value | Meaning |
|---|---|
| `"STOP"` | All motors stopped |
| `"FWD"` | Driving forward |
| `"BACK"` | Driving backward |
| `"LEFT"` | Turning left |
| `"RIGHT"` | Turning right |

> **Note:** Until `sensor/mega.py` is written and the Mega firmware implements
> the I2C status response frame, every row in this table has `quality = "offline"`
> and all other columns are `NULL`.

**Example — count time each tool was ON per session:**
```sql
SELECT
  SUM(air_on)   AS air_on_samples,
  SUM(water_on) AS water_on_samples,
  SUM(soil_on)  AS soil_on_samples,
  COUNT(*)      AS total_samples
FROM telemetry_mega
WHERE session_id = 'your-session-uuid-here' AND quality = 'ok';
```

---

## 5. The `quality` Field

Every telemetry table has a `quality TEXT` column as the last field.

| Value | Meaning |
|---|---|
| `"ok"` | Sensor read succeeded; all numeric fields are valid |
| `"error"` | Sensor raised an exception; numeric fields are `NULL` |
| `"offline"` | Driver not yet implemented (Mega only, for now) |

**Rule:** always filter on `quality = 'ok'` before doing numeric aggregations (AVG, MIN, MAX, etc.) to avoid skewing results with NULL rows.

```sql
-- Correct: exclude error rows
SELECT AVG(temp_c) FROM telemetry_tmp102 WHERE quality = 'ok';

-- Wrong: NULLs cause AVG to silently exclude rows, but MIN/MAX may behave unexpectedly
SELECT MIN(temp_c) FROM telemetry_tmp102;  -- filters NULLs but intent is unclear
```

---

## 6. The Session Model

Each `main.py` launch creates one session:

```python
db = SQLiteLogger("data/rover_logs.sqlite")
session_id = db.start(notes="Competition run 3")
# session_id is a UUID string like "a3f2c1d0-4b5e-..."
```

All rows written during this run carry that `session_id`. When the process exits cleanly, `db.close()` logs a final event and commits.

**List all sessions:**
```sql
SELECT session_id, started_utc, notes FROM sessions ORDER BY started_utc DESC;
```

**Count rows per sensor in a specific session:**
```sql
SELECT 'tmp102' AS sensor, COUNT(*) AS rows FROM telemetry_tmp102 WHERE session_id = ?
UNION ALL
SELECT 'bno055', COUNT(*) FROM telemetry_bno055 WHERE session_id = ?
UNION ALL
SELECT 'gps',    COUNT(*) FROM telemetry_gps    WHERE session_id = ?
UNION ALL
SELECT 'power',  COUNT(*) FROM telemetry_power  WHERE session_id = ?
UNION ALL
SELECT 'air',    COUNT(*) FROM telemetry_air     WHERE session_id = ?
UNION ALL
SELECT 'adc',    COUNT(*) FROM telemetry_adc     WHERE session_id = ?
UNION ALL
SELECT 'mega',   COUNT(*) FROM telemetry_mega    WHERE session_id = ?;
```

---

## 7. Writing Data (Python)

All writes go through `logger/sqlite_db.py`. **Never** write to the DB directly from sensor modules or Flask routes — only from `main.py`'s sensor loop via `_log_snap_to_sqlite()`.

### Starting a session

```python
from logger.sqlite_db import SQLiteLogger

db = SQLiteLogger("data/rover_logs.sqlite")
session_id = db.start(notes="Test run")
```

### Writing telemetry rows

Each `log_*()` method maps directly to one table. Call them in the sensor loop:

```python
# Temperature
db.log_tmp102(temp_c=24.72, quality="ok")

# IMU
db.log_bno055(
    roll=1.2, pitch=-0.8, yaw=45.3,
    g_force=1.003, vel_x=0.01, vel_y=-0.005, vel_z=0.001,
    quality="ok"
)

# GPS
db.log_gps(lat=35.6895, lon=139.6917,
           speed_mps=None, sats=None, hdop=None, fix=None,
           quality="ok")

# Power
db.log_power(voltage_v=12.4, current_a=1.2, power_w=14.9, quality="ok")

# CO2
db.log_air(co2_ppm=480, quality="ok")

# Soil moisture
db.log_adc(raw_moisture=542, v_moisture=1.61, moisture_value=51.6, quality="ok")

# Mega
db.log_mega(air_on=False, water_on=False, soil_on=False,
            ibus_pulse=1500, movement="STOP", quality="ok")

# Commit all rows for this poll cycle
db.flush()
```

### Writing on sensor error

Pass `None` for all numeric fields and `quality="error"`:

```python
try:
    data = sensor.read()
    db.log_tmp102(temp_c=data["temp_c"], quality="ok")
except Exception:
    db.log_tmp102(temp_c=None, quality="error")
```

### Writing events (state transitions only)

```python
db.event("INFO",    "main", "RUN enabled", None)
db.event("WARNING", "imu",  "IMU read spike detected", {"latency_ms": 320})
db.event("ERROR",   "gps",  "GPS fix void", None)
```

`event()` commits immediately. Do **not** call it every poll tick — only on state changes.

### Commit timing

`log_*()` methods execute `INSERT` but do **not** commit. Call `db.flush()` once at the end of each poll cycle to batch-commit all rows:

```python
while True:
    # ... read sensors, call log_*() for each ...
    db.flush()          # one commit per cycle — safe and efficient
    time.sleep(POLL_S)
```

### Closing

```python
db.close()   # commits pending data, logs a closing event, closes connection
```

Always call `db.close()` on shutdown. In `main.py` this is done in the `finally` block after Flask exits.

---

## 8. Reading Data (Python + SQL)

### Latest value for each sensor

```python
import sqlite3

con = sqlite3.connect("data/rover_logs.sqlite")
con.row_factory = sqlite3.Row

# Latest temperature
row = con.execute(
    "SELECT temp_c, ts_utc FROM telemetry_tmp102 WHERE quality='ok' ORDER BY id DESC LIMIT 1"
).fetchone()
if row:
    print(f"Temperature: {row['temp_c']} °C  at {row['ts_utc']}")
```

### All readings for one session

```python
SESSION = "paste-your-session-uuid-here"

rows = con.execute(
    "SELECT ts_utc, temp_c FROM telemetry_tmp102 WHERE session_id=? AND quality='ok' ORDER BY id",
    (SESSION,)
).fetchall()

for r in rows:
    print(r["ts_utc"], r["temp_c"])
```

### Sensor health summary for one session

```python
SESSION = "paste-your-session-uuid-here"

tables = [
    ("temperature", "telemetry_tmp102"),
    ("imu",         "telemetry_bno055"),
    ("gps",         "telemetry_gps"),
    ("power",       "telemetry_power"),
    ("air",         "telemetry_air"),
    ("adc",         "telemetry_adc"),
    ("mega",        "telemetry_mega"),
]

for name, table in tables:
    total = con.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (SESSION,)).fetchone()[0]
    errors = con.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=? AND quality!='ok'", (SESSION,)).fetchone()[0]
    pct = (total - errors) / total * 100 if total else 0
    print(f"{name:15s}  {total:5d} rows  {errors:4d} errors  ({pct:.1f}% ok)")
```

### Useful SQL queries

**Average temperature by minute:**
```sql
SELECT
  strftime('%Y-%m-%dT%H:%M', ts_utc) AS minute,
  ROUND(AVG(temp_c), 2)              AS avg_temp_c,
  COUNT(*)                            AS samples
FROM telemetry_tmp102
WHERE quality = 'ok'
GROUP BY minute
ORDER BY minute;
```

**Highest CO₂ reading in the last session:**
```sql
SELECT ts_utc, co2_ppm
FROM telemetry_air
WHERE session_id = (SELECT session_id FROM sessions ORDER BY started_utc DESC LIMIT 1)
  AND quality = 'ok'
ORDER BY co2_ppm DESC
LIMIT 1;
```

**All movement changes (not just polling noise):**
```sql
SELECT ts_utc, movement FROM telemetry_mega
WHERE quality = 'ok'
  AND movement != LAG(movement) OVER (ORDER BY id)
ORDER BY id;
```

**Tool ON time (seconds) per session at 2 Hz poll rate:**
```sql
SELECT
  SUM(air_on)   * 0.5 AS air_on_s,
  SUM(water_on) * 0.5 AS water_on_s,
  SUM(soil_on)  * 0.5 AS soil_on_s
FROM telemetry_mega
WHERE session_id = 'your-session-uuid-here' AND quality = 'ok';
```

---

## 9. Log Viewer GUI

```bash
python logger/tools/log_viewer_gui.py
```

The viewer opens `data/rover_logs.sqlite` by default. To view the example DB, change `DB_PATH` at the top of `log_viewer_gui.py` temporarily, or just copy `example_rover_logs.sqlite` over `rover_logs.sqlite` for testing.

**Dropdown options:**

| View | Table queried |
|---|---|
| Events (latest) | `events` |
| TMP102 (latest) | `telemetry_tmp102` |
| BNO055 (latest) | `telemetry_bno055` |
| GPS (latest) | `telemetry_gps` |
| Power (latest) | `telemetry_power` |
| Air / CO2 (latest) | `telemetry_air` |
| ADC / Soil (latest) | `telemetry_adc` |
| Mega (latest) | `telemetry_mega` |

All views show the most recent N rows (default 200, adjustable via the Limit field). Hit **Refresh** to reload.

---

## 10. Design Rules

These rules are binding for all future changes to the database.

1. **`SQLiteLogger` is mandatory.** It must be started in `main.py` on every run. Never add a flag to skip it.

2. **Every poll cycle writes a row for every sensor** — including sensors that errored. A row with `quality="error"` and NULL numerics is a valid record. Gaps in the timeline mean something crashed.

3. **`flush()` is called once per poll cycle.** Individual `log_*()` methods do not commit. Batching commits to once per cycle avoids locking the DB on every insert.

4. **`event()` is for state transitions only.** Do not call it every tick. Log: startup, shutdown, sensor going offline, sensor recovering, run enable/disable. Nothing else.

5. **Numeric columns are `REAL` or `INTEGER` with `NULL` allowed.** Never store sentinel values (`-1`, `0`, `9999`) to represent "no data" — use `NULL`.

6. **`ts_utc` is always ISO 8601 UTC.** Generated by `utc_now_iso()` in `sqlite_db.py`. Never use Unix epoch integers in the DB.

7. **All tables have a `session_id` foreign key.** Queries that look at "this run" always filter by `session_id`.

8. **Schema changes require a migration.** Add new columns via `ALTER TABLE` in `_migrate()`. Wrap each statement in `try/except sqlite3.OperationalError` so it is a no-op on an already-migrated DB.

9. **Do not drop columns.** SQLite's `ALTER TABLE` does not support `DROP COLUMN` on older versions. Unused columns should be left with `NULL` values.

10. **The example DB must stay consistent with the schema.** When adding a new table or column, update `data/example_rover_logs.sqlite` and commit it.

---

## 11. Adding a New Sensor

Follow this checklist when integrating a new sensor into the database.

### Step 1 — Add a table in `_create_schema()`

```python
self.conn.execute(
    """
    CREATE TABLE IF NOT EXISTS telemetry_newsensor (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      ts_utc     TEXT NOT NULL,
      session_id TEXT NOT NULL,
      value_x    REAL,
      quality    TEXT,
      FOREIGN KEY(session_id) REFERENCES sessions(session_id)
    );
    """
)
self.conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_newsensor_ts ON telemetry_newsensor(ts_utc);"
)
```

### Step 2 — Add a `log_newsensor()` method

```python
def log_newsensor(self, value_x: float | None, quality: str) -> None:
    assert self.conn and self.session_id
    self.conn.execute(
        """
        INSERT INTO telemetry_newsensor(ts_utc, session_id, value_x, quality)
        VALUES(?,?,?,?)
        """,
        (utc_now_iso(), self.session_id, value_x, quality),
    )
```

### Step 3 — Add the sensor to `_log_snap_to_sqlite()` in `main.py`

```python
new = data.get("newsensor") or {}
if new or "newsensor" in errors:
    db.log_newsensor(
        value_x=new.get("value_x"),
        quality=quality("newsensor"),
    )
```

### Step 4 — Add a query to `log_viewer_gui.py`

```python
"NewSensor (latest)": (
    "SELECT id, ts_utc, value_x, quality FROM telemetry_newsensor ORDER BY id DESC LIMIT ?",
    200,
),
```

### Step 5 — Update the example DB

Re-generate `data/example_rover_logs.sqlite` to include rows for the new sensor:

```bash
python scripts/regenerate_example_db.py  # or run the generation snippet manually
```

Commit the updated example DB so the schema reference stays current.

---

*Last updated: 2026-02-24*
*Maintainer: Team MOVIS — HERC-26*
