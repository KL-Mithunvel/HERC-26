# HERC-26 SQLite Database — Developer Wiki

Complete reference for the rover's SQLite telemetry database:
schema, error convention, validation logic, write/read patterns, and extension rules.

---

## Table of Contents

1. [Overview](#1-overview)
2. [File Paths](#2-file-paths)
3. [Opening the Database](#3-opening-the-database)
4. [Table Structure](#4-table-structure)
   - [sessions](#sessions)
   - [events](#events)
   - [telemetry (unified)](#telemetry-unified)
5. [The -1 Error Sentinel](#5-the--1-error-sentinel)
6. [Validation — How It Works](#6-validation--how-it-works)
   - [Air](#air-co2--mh-z19c)
   - [Soil](#soil-moisture--ads1115)
   - [Water / pH](#water--ph)
   - [Validation columns in telemetry](#validation-columns-in-telemetry)
7. [What a Row Looks Like](#7-what-a-row-looks-like)
8. [Writing Data (Python)](#8-writing-data-python)
9. [Reading Data (Python + SQL)](#9-reading-data-python--sql)
10. [Log Viewer GUI](#10-log-viewer-gui)
11. [Design Rules](#11-design-rules)
12. [Adding a New Sensor](#12-adding-a-new-sensor)

---

## 1. Overview

The SQLite database is the permanent, queryable mission record for every HERC-26 run.

- **One unified table** (`telemetry`) holds every sensor reading for every poll cycle in a single row.
- No joins needed. All data — hardware values, quality flags, and validation state — comes out of one `SELECT`.
- Every poll cycle (default 2 Hz) writes exactly one row.
- Alongside the JSONL file, both logging paths are mandatory and unconditional.
- Each `main.py` launch creates a **session** (UUID). All telemetry rows in that run carry the session ID.

---

## 2. File Paths

| File | Purpose | In git |
|---|---|---|
| `data/rover_logs.sqlite` | Live mission database written every run | No (gitignored) |
| `data/example_rover_logs.sqlite` | Pre-seeded reference DB with sample rows | Yes |

Path is set in `calibration/config.xml`:
```xml
<database>
  <sqlite_path>data/rover_logs.sqlite</sqlite_path>
</database>
```

---

## 3. Opening the Database

**Log Viewer GUI** (recommended for browsing):
```bash
python logger/tools/log_viewer_gui.py
```

**Python** (for scripts and analysis):
```python
import sqlite3
con = sqlite3.connect("data/rover_logs.sqlite")
con.row_factory = sqlite3.Row   # lets you do row["temp_c"] instead of row[0]
```

**DB Browser for SQLite** — https://sqlitebrowser.org — open either DB file directly.

**Command-line:**
```bash
sqlite3 data/rover_logs.sqlite
.tables
.schema telemetry
SELECT id, ts_utc, temp_c, co2_ppm FROM telemetry LIMIT 5;
.quit
```

---

## 4. Table Structure

### `sessions`

One row per `main.py` launch.

| Column | Type | Description |
|---|---|---|
| `session_id` | TEXT PK | UUID v4, e.g. `"a3f2c1d0-…"` |
| `started_utc` | TEXT | ISO 8601 UTC timestamp of `start()` call |
| `notes` | TEXT | Free-text label, e.g. `"Competition run 3"` |

---

### `events`

State transitions, warnings, errors. Committed immediately — not buffered.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `ts_utc` | TEXT | ISO 8601 UTC |
| `session_id` | TEXT FK | Links to `sessions` |
| `level` | TEXT | `"INFO"` / `"WARNING"` / `"ERROR"` |
| `source` | TEXT | Component name: `"main"`, `"gps"`, `"logger"`, … |
| `message` | TEXT | Human-readable description |
| `data_json` | TEXT / NULL | Optional JSON payload |

Write events for state changes only (startup, shutdown, sensor going offline/recovering, run enable/disable). Never write an event every tick.

---

### `telemetry` (unified)

**One row per poll cycle. All sensors. All validation state. One table.**

Every timestamp (`ts_utc`) is **ISO 8601 UTC**, e.g. `2025-01-15T10:32:05.123456+00:00`.

#### Identity

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment row ID |
| `ts_utc` | TEXT NOT NULL | Poll cycle timestamp (UTC ISO 8601) |
| `session_id` | TEXT NOT NULL FK | Links to `sessions.session_id` |

#### Temperature — TMP102 (I2C 0x48)

| Column | Type | Unit | Notes |
|---|---|---|---|
| `temp_c` | REAL | °C | −40 to +125; **-1 on error** |
| `temp_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |

#### IMU — BNO055 (I2C 0x28)

| Column | Type | Unit | Notes |
|---|---|---|---|
| `imu_roll_deg` | REAL | ° | −180 to +180; **-1 on error** |
| `imu_pitch_deg` | REAL | ° | −90 to +90; **-1 on error** |
| `imu_yaw_deg` | REAL | ° | 0 to 360; **-1 on error** |
| `imu_g_force` | REAL | g | ~0 to ~4; **-1 on error** |
| `imu_vel_x` | REAL | m/s | Integrated from linear accel; **-1 on error** |
| `imu_vel_y` | REAL | m/s | **-1 on error** |
| `imu_vel_z` | REAL | m/s | **-1 on error** |
| `imu_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |

#### GPS — Serial NMEA

| Column | Type | Unit | Notes |
|---|---|---|---|
| `gps_lat` | REAL | ° | Decimal degrees WGS-84; **-1 on error** |
| `gps_lon` | REAL | ° | Decimal degrees WGS-84; **-1 on error** |
| `gps_speed_mps` | REAL | m/s | **-1 on error** |
| `gps_sats` | INTEGER | — | **-1 on error** |
| `gps_fix` | INTEGER | — | 1 = fix, 0 = no fix; **-1 on error** |
| `gps_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |

#### Power — PZEM-017 (RS485 Modbus)

| Column | Type | Unit | Notes |
|---|---|---|---|
| `power_voltage_v` | REAL | V | 0–300 V; **-1 on error** |
| `power_current_a` | REAL | A | 0–100 A; **-1 on error** |
| `power_w` | REAL | W | 0–30,000 W; **-1 on error** |
| `power_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |

#### Air / CO₂ — MH-Z19C (UART) + Validation

| Column | Type | Unit | Notes |
|---|---|---|---|
| `co2_ppm` | INTEGER | ppm | 0–10,000; **-1 on error** |
| `air_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |
| `air_phase` | TEXT | — | `"off"` / `"valid_window"` / `"done"` |
| `air_valid` | INTEGER | — | **1 = mission-valid reading**, 0 = not valid |
| `air_samples_left` | INTEGER | — | Countdown from 15 to 0 during valid window |

#### Soil Moisture — ADS1115 ADC (I2C) + Validation

| Column | Type | Unit | Notes |
|---|---|---|---|
| `soil_raw` | INTEGER | counts | Raw 16-bit ADC value; **-1 on error** |
| `soil_voltage_v` | REAL | V | 0–3.3 V; **-1 on error** |
| `soil_moisture_pct` | REAL | % | 0–100 calibrated; **-1 on error** |
| `soil_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |
| `soil_phase` | TEXT | — | `"off"` / `"waiting"` / `"valid_window"` / `"done"` |
| `soil_valid` | INTEGER | — | **1 = mission-valid reading**, 0 = not valid |
| `soil_samples_left` | INTEGER | — | Countdown from 15 to 0 during valid window |

#### Water / pH + Validation

| Column | Type | Unit | Notes |
|---|---|---|---|
| `water_ph` | REAL | pH | 0–14; **-1 on error or offline** |
| `water_quality` | TEXT | — | `"ok"` / `"error"` / `"offline"` |
| `water_phase` | TEXT | — | `"off"` / `"waiting"` / `"stabilizing"` / `"valid_window"` / `"done"` |
| `water_valid` | INTEGER | — | **1 = mission-valid reading**, 0 = not valid |
| `water_samples_left` | INTEGER | — | Countdown from 15 to 0 during valid window |

> `water_quality = "offline"` until the pH sensor replacement is fitted.
> The phase and validation columns are driven by the Mega water trigger regardless.

#### Arduino Mega — Tool states + movement

| Column | Type | Notes |
|---|---|---|
| `mega_air_on` | INTEGER | 1 = air tool active, 0 = off, **-1 = offline** |
| `mega_water_on` | INTEGER | 1 = water tool active, 0 = off, **-1 = offline** |
| `mega_soil_on` | INTEGER | 1 = soil tool active, 0 = off, **-1 = offline** |
| `mega_ibus_pulse` | INTEGER | Raw iBUS RC pulse µs, 1000–2000 (1500 = centre); **-1 = offline** |
| `mega_movement` | TEXT | `"STOP"` / `"FWD"` / `"BACK"` / `"LEFT"` / `"RIGHT"` / `"UNKNOWN"` |
| `mega_quality` | TEXT | `"ok"` / `"error"` / `"offline"` |

---

## 5. The -1 Error Sentinel

Every numeric column uses **-1** when the sensor failed or is not yet implemented. There are no NULLs in the telemetry table.

| `_quality` value | What it means | Numeric columns |
|---|---|---|
| `"ok"` | Sensor read succeeded | Real measured values |
| `"error"` | Sensor threw an exception this poll | `-1` for all that sensor's columns |
| `"offline"` | Driver not yet written / sensor not fitted | `-1` always |

**Always filter** on `_quality = 'ok'` before doing numeric aggregations:

```sql
-- Correct
SELECT AVG(temp_c) FROM telemetry WHERE temp_quality = 'ok';

-- Wrong — -1 sentinels will corrupt the average
SELECT AVG(temp_c) FROM telemetry;
```

---

## 6. Validation — How It Works

Validation is **separate from hardware quality**. A sensor can have `air_quality = "ok"` (hardware read successfully) but `air_valid = 0` (not yet inside the mission-valid window).

`air_valid`, `soil_valid`, `water_valid` are set by the state machine in `spanner/validation.py`. They are computed server-side every poll cycle and stored directly in the telemetry row.

---

### Air (CO₂ — MH-Z19C)

```
Mega sets mega_air_on = 1
        │
        ▼
   ┌────────────────┐
   │  valid_window  │  ← 15 reads (~7.5 s at 2 Hz)
   │  air_valid = 1 │    co2_ppm readings count for the task
   └────────────────┘
        │  (after 15 reads)
        ▼
      done  (air_valid = 0, air_samples_left = 0)

Mega sets mega_air_on = 0 → resets to "off" immediately
```

No waiting. Mega physically controls when the air sample reaches the sensor, so readings are valid the moment it triggers.

---

### Soil moisture (ADS1115)

```
Mega sets mega_soil_on = 1
        │
        ▼
   ┌──────────────┐
   │   waiting    │  ← 10 s (20 reads at 2 Hz)
   │ soil_valid=0 │    mechanical arm pressing probe into sample
   └──────────────┘
        │  (after 10 s)
        ▼
   ┌────────────────┐
   │  valid_window  │  ← 15 reads (~7.5 s)
   │  soil_valid=1  │    probe is in the sample — reading is valid
   └────────────────┘
        │  (after 15 reads)
        ▼
      done  (soil_valid = 0)

Mega sets mega_soil_on = 0 → resets to "off"
```

**Why wait 10 s?** The physical arm needs time to fully seat the probe in the collected soil sample. Readings during movement are noise.

---

### Water / pH

```
Mega sets mega_water_on = 1
        │
        ▼
   ┌──────────────┐
   │   waiting    │  ← 10 s (20 reads)
   │water_valid=0 │    water travelling from pump to sensor
   └──────────────┘
        │  (after 10 s)
        ▼
   ┌──────────────┐
   │ stabilizing  │  ← 170 s (~3 min total from trigger)
   │water_valid=0 │    pH electrode equilibrating with the water sample
   └──────────────┘
        │  (after 170 s)
        ▼
   ┌────────────────┐
   │  valid_window  │  ← 15 reads (~7.5 s)
   │ water_valid=1  │    pH has stabilised — reading is the real value
   └────────────────┘
        │  (after 15 reads)
        ▼
      done  (water_valid = 0)

Mega sets mega_water_on = 0 → resets to "off"
```

**Why wait 10 s?** Water needs time to flow from the pump to the sensor.
**Why 170 s stabilizing?** pH electrodes require equilibration time — reading before this gives drifting values.

---

### Validation timing summary

| Tool | Wait before measuring | Stabilization | Valid reads | Total time to first valid read |
|---|---|---|---|---|
| **Air** | 0 s | 0 s | 15 | Immediate |
| **Soil** | 10 s | 0 s | 15 | 10 s |
| **Water** | 10 s | 170 s | 15 | 180 s (3 min) |

---

### Validation columns in telemetry

| Column | Value during each phase |
|---|---|
| `*_phase` | `"off"` → `"waiting"` → `"stabilizing"` → `"valid_window"` → `"done"` |
| `*_valid` | `1` only during `"valid_window"`, `0` everywhere else |
| `*_samples_left` | Counts down from 15 to 0 during `"valid_window"`, `0` otherwise |

---

## 7. What a Row Looks Like

Full single row — all 45 columns — from a poll where the soil tool is in its valid window:

```
id                  = 320
ts_utc              = 2025-01-15T10:40:10+00:00
session_id          = a3f2c1d0-4b5e-...

temp_c              = 25.22          temp_quality        = ok

imu_roll_deg        = 2.1            imu_pitch_deg       = 1.0
imu_yaw_deg         = 180.0          imu_g_force         = 1.003
imu_vel_x           = 0.00           imu_vel_y           = 0.00
imu_vel_z           = 0.00           imu_quality         = ok

gps_lat             = 35.6900        gps_lon             = 139.6920
gps_speed_mps       = 0.0            gps_sats            = 8
gps_fix             = 1              gps_quality         = ok

power_voltage_v     = 12.2           power_current_a     = 2.4
power_w             = 29.3           power_quality       = ok

co2_ppm             = 489            air_quality         = ok
air_phase           = off            air_valid           = 0
air_samples_left    = 0

soil_raw            = 541            soil_voltage_v      = 1.61
soil_moisture_pct   = 51.8           soil_quality        = ok
soil_phase          = valid_window   soil_valid          = 1    ← mission-valid
soil_samples_left   = 12

water_ph            = -1             water_quality       = offline
water_phase         = off            water_valid         = 0
water_samples_left  = 0

mega_air_on         = 0              mega_water_on       = 0
mega_soil_on        = 1              mega_ibus_pulse     = 1500
mega_movement       = STOP           mega_quality        = ok
```

Same row when GPS fails that poll — only GPS columns change:

```
gps_lat = -1    gps_lon = -1    gps_speed_mps = -1
gps_sats = -1   gps_fix = -1    gps_quality = error
```

---

## 8. Writing Data (Python)

All writes go through `logger/sqlite_db.py`. Never write directly from sensor modules or Flask routes.

### Starting a session

```python
from logger.sqlite_db import SQLiteLogger

db = SQLiteLogger("data/rover_logs.sqlite")
session_id = db.start(notes="Competition run 3")
```

### Writing one telemetry row

Pass the full snapshot dict (from `dev_stack.read_all()` or the real sensor stack) and the validation dict (from `compute_validation()`):

```python
from spanner.validation import compute_validation

# Inside the sensor loop:
snap       = dev_stack.read_all()
validation = compute_validation(
    snap["data"]["mega"]["tools"],
    snap["data"]["timers"],
)
snap["validation"] = validation

db.log_telemetry(snap, validation)
db.flush()   # one commit per poll cycle
```

`log_telemetry()` extracts every field from `snap["data"]` and `validation`, converts errors to `-1`, and writes one row. `flush()` commits it.

### Writing events (state changes only)

```python
db.event("INFO",    "main",  "RUN enabled by operator",       None)
db.event("WARNING", "gps",   "GPS fix void, status=V",         None)
db.event("ERROR",   "power", "Modbus timeout",                 {"retry": 3})
db.event("INFO",    "soil",  "Soil valid window opened",        None)
```

`event()` commits immediately. Call it only when something significant changes, never every tick.

### Closing cleanly

```python
db.close()   # commits, logs a closing event, closes connection
```

Call in the `finally` block after Flask exits in `main.py`.

---

## 9. Reading Data (Python + SQL)

### Latest reading for a single sensor

```python
import sqlite3
con = sqlite3.connect("data/rover_logs.sqlite")
con.row_factory = sqlite3.Row

row = con.execute(
    "SELECT temp_c, ts_utc FROM telemetry WHERE temp_quality='ok' ORDER BY id DESC LIMIT 1"
).fetchone()

if row:
    print(f"{row['temp_c']} °C at {row['ts_utc']}")
```

### All mission-valid soil readings for a session

```python
SESSION = "a3f2c1d0-..."

rows = con.execute(
    """
    SELECT ts_utc, soil_moisture_pct, soil_samples_left
    FROM telemetry
    WHERE session_id = ? AND soil_valid = 1
    ORDER BY id
    """,
    (SESSION,),
).fetchall()

for r in rows:
    print(r["ts_utc"], r["soil_moisture_pct"])
```

### Sensor health summary for a session

```python
SESSION = "a3f2c1d0-..."

sensors = [
    ("temperature", "temp_quality"),
    ("imu",         "imu_quality"),
    ("gps",         "gps_quality"),
    ("power",       "power_quality"),
    ("air",         "air_quality"),
    ("soil",        "soil_quality"),
    ("mega",        "mega_quality"),
]

for name, col in sensors:
    total  = con.execute(f"SELECT COUNT(*) FROM telemetry WHERE session_id=?", (SESSION,)).fetchone()[0]
    errors = con.execute(f"SELECT COUNT(*) FROM telemetry WHERE session_id=? AND {col}!='ok'", (SESSION,)).fetchone()[0]
    pct    = (total - errors) / total * 100 if total else 0
    print(f"{name:15s} {total:5d} rows  {errors:4d} not-ok  ({pct:.1f}% ok)")
```

### Useful SQL queries

**Average temperature by minute (good reads only):**
```sql
SELECT
  strftime('%Y-%m-%dT%H:%M', ts_utc) AS minute,
  ROUND(AVG(temp_c), 2)              AS avg_temp_c,
  COUNT(*)                            AS samples
FROM telemetry
WHERE temp_quality = 'ok'
GROUP BY minute
ORDER BY minute;
```

**All three mission-valid tool readings in one query:**
```sql
SELECT
  ts_utc,
  co2_ppm,          air_phase,   air_samples_left,
  soil_moisture_pct, soil_phase,  soil_samples_left,
  water_ph,          water_phase, water_samples_left
FROM telemetry
WHERE air_valid = 1 OR soil_valid = 1 OR water_valid = 1
ORDER BY id;
```

**How long each tool was ON (at 2 Hz poll rate):**
```sql
SELECT
  SUM(CASE WHEN mega_air_on   = 1 THEN 1 ELSE 0 END) * 0.5 AS air_on_s,
  SUM(CASE WHEN mega_water_on = 1 THEN 1 ELSE 0 END) * 0.5 AS water_on_s,
  SUM(CASE WHEN mega_soil_on  = 1 THEN 1 ELSE 0 END) * 0.5 AS soil_on_s
FROM telemetry
WHERE session_id = 'your-session-uuid' AND mega_quality = 'ok';
```

**Peak CO₂ in the last session:**
```sql
SELECT ts_utc, co2_ppm
FROM telemetry
WHERE session_id = (SELECT session_id FROM sessions ORDER BY started_utc DESC LIMIT 1)
  AND air_quality = 'ok'
ORDER BY co2_ppm DESC
LIMIT 1;
```

**Energy used in a session (approximate Wh):**
```sql
SELECT
  ROUND(AVG(power_w), 1) AS avg_power_w,
  ROUND(
    (julianday(MAX(ts_utc)) - julianday(MIN(ts_utc))) * 24,
    3
  ) AS duration_h,
  ROUND(
    AVG(power_w) * (julianday(MAX(ts_utc)) - julianday(MIN(ts_utc))) * 24,
    2
  ) AS energy_wh
FROM telemetry
WHERE session_id = 'your-session-uuid' AND power_quality = 'ok';
```

---

## 10. Log Viewer GUI

```bash
python logger/tools/log_viewer_gui.py
```

Opens `data/rover_logs.sqlite`. Use the **example DB** to browse without running the rover.

**Dropdown views:**

| View | What it shows |
|---|---|
| Events (latest) | All events table rows |
| All Telemetry (latest) | Every column of the unified telemetry table |
| Temperature (latest) | `temp_c`, `temp_quality` |
| IMU (latest) | All IMU columns |
| GPS (latest) | All GPS columns |
| Power (latest) | Voltage, current, watts |
| Air / CO2 (latest) | CO2 + air validation columns |
| Soil Moisture (latest) | Soil raw/voltage/% + validation |
| Water / pH (latest) | pH + water validation columns |
| Mega (latest) | Tool states, pulse, movement |
| **Valid Air Readings** | Only rows where `air_valid = 1` |
| **Valid Soil Readings** | Only rows where `soil_valid = 1` |
| **Valid Water Readings** | Only rows where `water_valid = 1` |
| Sessions | List of all session UUIDs and start times |

The Limit field controls how many rows to show. Hit **Refresh** after changing it.

---

## 11. Design Rules

These rules apply to all changes to the database layer.

1. **One unified `telemetry` table.** All sensors in every row. Never add a new per-sensor table.

2. **-1 is the error sentinel, never NULL.** All numeric columns are `NOT NULL DEFAULT -1`. A `-1` combined with `_quality = "error"` or `"offline"` tells you why the value is missing.

3. **`log_telemetry()` is the only write path for sensor data.** Call it once per poll cycle with the full snap + validation dicts. Never write partial rows or call individual sensor methods.

4. **`flush()` is called once per poll cycle.** `log_telemetry()` executes an INSERT but does not commit. Batching the commit avoids DB locking on every insert.

5. **`event()` is for state transitions only.** Not for every tick. Log: startup, shutdown, sensor going offline, sensor recovering, run enable/disable, valid window opening/closing.

6. **`*_valid = 1` rows are what matter for task scoring.** Everything else is context. When presenting mission results, always filter on the relevant `*_valid` column.

7. **`*_quality` and `*_valid` are independent.** Hardware can succeed (`quality = "ok"`) while the reading is not yet mission-valid (`valid = 0`). A hardware error (`quality = "error"`) always forces `valid = 0`.

8. **`ts_utc` is always ISO 8601 UTC.** Generated by `utc_now_iso()` in `sqlite_db.py`. Never use Unix epoch integers in the DB.

9. **Session ID links everything.** Always filter by `session_id` when querying "this run". The `sessions` table tells you start time and any notes for each run.

10. **Schema changes use migration.** Add new columns via `ALTER TABLE ... ADD COLUMN` in `_migrate()`. Wrap in `try/except sqlite3.OperationalError` to make it a no-op on an already-migrated DB.

---

## 12. Adding a New Sensor

### Step 1 — Add columns to `telemetry` in `_create_schema()`

```python
# Inside the CREATE TABLE IF NOT EXISTS telemetry ( ... ) block:
-- New sensor (SHT31 humidity, I2C)
humidity_pct    REAL    NOT NULL DEFAULT -1,
humidity_quality TEXT   NOT NULL DEFAULT 'offline',
```

### Step 2 — Add the same columns to `_migrate()`

```python
for sql in [
    "ALTER TABLE telemetry ADD COLUMN humidity_pct     REAL    NOT NULL DEFAULT -1",
    "ALTER TABLE telemetry ADD COLUMN humidity_quality TEXT    NOT NULL DEFAULT 'offline'",
]:
    try:
        self.conn.execute(sql)
    except sqlite3.OperationalError:
        pass   # column already exists
```

### Step 3 — Extract and write in `log_telemetry()`

```python
# Inside log_telemetry(), add to the INSERT column list and values tuple:
humid   = data.get("humidity") or {}

# In the INSERT column list:
humidity_pct, humidity_quality,

# In the values tuple:
_n(humid.get("humidity_pct")), _q("humidity"),
```

### Step 4 — Add a view to `log_viewer_gui.py`

```python
"Humidity (latest)": (
    "SELECT id, ts_utc, humidity_pct, humidity_quality "
    "FROM telemetry ORDER BY id DESC LIMIT ?",
    200,
),
```

### Step 5 — Add to `dev_stack.py` first

Add simulated random-walk values for the new sensor to `dev_stack.py` before writing the real hardware driver. Verify the new columns appear in the viewer with plausible values before touching hardware.

### Step 6 — Update the example DB

Regenerate `data/example_rover_logs.sqlite` so the schema reference stays current, then commit it.

---

*Last updated: 2026-02-25*
*Maintainer: Team MOVIS — HERC-26*
