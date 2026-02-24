# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**HERC-26** is a rover telemetry and control system for the **Human Exploration Rover Challenge (HERC)** competition, built by **Team MOVIS**. The system:

- Collects real-time sensor data: temperature (TMP102), GPS (serial NMEA), IMU (BNO055), soil pH and moisture (ADS1115 ADC), air quality CO2 (MH-Z19C), and power (PZEM-017 via RS485 Modbus)
- Continuously logs every poll cycle to both JSONL and SQLite with session tracking (both are mandatory)
- Serves a live web dashboard (Flask) that auto-refreshes every 500ms — accessible from any browser on the same Wi-Fi network
- Runs on a **Raspberry Pi** (deployment target) with an **Arduino Mega** as a co-processor for motor control (6 wheels, iBUS RC input) and tool actuation (air/water/soil)
- Runs on **Windows/Linux laptops** in development mode via `sensor/dev_stack.py` (simulated sensor data)

---

## Running the System

```bash
# Start the main system (sensor loop + Flask dashboard)
python main.py
# Dashboard: http://127.0.0.1:5000
# For tablet/network access: change host to "0.0.0.0" in main.py

# Calibration text menu
python calibration/calibration.py

# Config XML editor GUI (Tkinter)
python calibration/config_gui.py

# Team helper GUI (git + Mega firmware upload)
python spanner/GUI_help.py

# Log viewer
python logger/tools/log_viewer_gui.py
```

There is **no test suite or linter configured.**

---

## Architecture

### Two Operating Modes

| Mode | Default | Sensor source |
|---|---|---|
| **Development** (Windows / laptop) | Yes — set in `main.py` | `sensor/dev_stack.py` — simulated random-walk data |
| **Deployment** (Raspberry Pi) | No — requires manual swap | `sensor/tmp.py`, `gps.py`, `imu.py`, `air.py`, etc. |

### Threading Model

```
main()
 ├── Daemon thread: sensor_loop()
 │     └── every 0.5s:
 │           1. snap = dev_stack.read_all()              ← raw snapshot dict
 │           2. snap["validation"] = compute_validation(tools, timers)
 │           3. logger_dev.log_snapshot(snap)             → appends to data/dev_log.jsonl
 │           4. set_latest(snap)                          → updates LATEST in web/app.py
 │
 └── Main thread: app.run(host="127.0.0.1", port=5000)  ← Flask serves the UI
```

- The sensor loop is a **daemon thread** — it exits automatically when Flask (main thread) exits.
- `set_latest()` does a simple global dict replacement; it is safe because Python GIL protects single-assignment on dicts.
- The backend loop continues running regardless of Wi-Fi connectivity or UI crashes — full mission logging is always maintained.
- Flask never reads hardware directly; it only serves the pre-computed `LATEST` snapshot.

### Snapshot Schema

Every poll cycle produces this snapshot dict:

```python
{
  "ts":             float,    # Unix timestamp of the read
  "run_enabled":    bool,     # Global run switch (toggled via POST /api/run/on|off)
  "schema_version": 1,        # Always 1 (increment if structure changes)

  "data": {
    "power":       {"voltage_v": float, "current_a": float, "power_w": float},
    "gps":         {"timestamp": int, "lat": float, "lon": float},
    "imu":         {
                     "acceleration": {"x": float, "y": float, "z": float},
                     "orientation":  {"roll": float, "pitch": float, "yaw": float},
                     "g_force":      float,
                     "velocity":     {"x": float, "y": float, "z": float},
                   },
    "temperature": {"temp_c": float},
    "adc":         {
                     "raw":            {"ph": int, "moisture": int},
                     "sensor_voltage": {"ph": float, "moisture": float},
                     "ph_value":       float,
                     "moisture_value": float,
                   },
    "air":         {"co2_ppm": int},
    "mega":        {
                     "tools":     {"air": bool, "water": bool, "soil": bool},
                     "ibus_pulse": int,
                     "movement":  str,   # "STOP" | "FWD" | "BACK" | "LEFT" | "RIGHT"
                   },
    "timers":      {"air_s": float, "water_s": float, "soil_s": float},
  },

  "errors":     {sensor_name: error_string, ...},
  "health":     {sensor_name: {"ok": bool, "msg": str}, ...},
  "validation": {
    "air":   {"on", "on_s", "phase", "valid_sample", "valid_in_s", "samples_left"},
    "water": {...},
    "soil":  {...},
  },
  "status_log": [{"ts": float, "msg": str}, ...],  # last 200 entries
}
```

**All fields are mandatory.** Missing fields break the UI. If a sensor fails, its key in `data` is absent but `errors[name]` and `health[name]` are always populated.

---

## Key Modules

### `sensor/dev_stack.py` — Simulated Sensor Stack (Development Default)

- Generates realistic random-walk data for all sensor channels.
- `_state` dict holds current simulated values; each poll adds a small random delta and clamps to physical range.
- `FAIL_PROB = 0.01` — each sensor block independently has a 1% chance of raising an exception per poll, simulating hardware failures.
- Tool timers (`_tool_on_since`, `_tool_elapsed`) track cumulative ON-time per tool (air/water/soil) in seconds, computed server-side.
- `_update_health()` de-duplicates health log entries — only logs when status changes.
- `_status_log` is capped at `STATUS_MAX = 200` entries.
- **API**: `setup(fail_prob)`, `read_all()`, `set_run_enabled(bool)`, `_log(msg)`.

### `sensor/base.py` — Base Sensor Exceptions

```python
class SensorInitError(Exception): pass
class SensorReadError(Exception): pass
```

These are the generic base classes. In practice, each real hardware driver defines its own more specific exception classes (see wiki rules below).

### `sensor/tmp.py` — Temperature Sensor (TMP102, I2C 0x48)

- Interface: `setup()`, `read()`, `close()`
- Exceptions: `tmpSensorSetupError`, `tmpSensorReadError`
- Uses `tmp102` library (smbus-based). Returns temperature in Fahrenheit (configurable).
- `close()` only sets the `TMP_connected` flag; does not close I2C bus.

### `sensor/gps.py` — GPS (Serial NMEA, pynmea2)

- Class-based design: `GPS(port, baudrate, timeout)`
- Interface: `open()`, `read(max_lines=50)`, `close()` — note: uses `open()` not `setup()`
- Parses `$GPRMC` / `$GNRMC` sentences; validates status field (`'A'` = valid, `'V'` = void).
- Returns `{"ok": True, "lat", "lon", "utc_time", "utc_date", "speed_knots", "course_deg"}` on success or `{"ok": False, "error": ...}` on failure.
- **Requires `pynmea2`** — not in apt; needs a venv with `--system-site-packages` on Pi.

### `sensor/air.py` — CO2 Sensor (MH-Z19C, UART /dev/ttyAMA0)

- Interface: `setup()`, `read_co2()`, `close()`
- Exceptions: `MHZ19CSetupError`, `MHZ19CReadError`
- Communicates via 9-byte binary protocol over serial (CMD_READ_CO2 = `[0xFF, 0x01, 0x86, ...]`).
- Validates response length (9 bytes) and checksum; raises on out-of-range values (0–10,000 ppm).
- `disable_abc()` turns off automatic baseline correction.
- **Warning**: `setup()` and `disable_abc()` are currently called at module level — importing the module on a non-Pi machine will fail.

### `sensor/soil.py` — Soil Moisture (ADS1115 ADC, I2C via Adafruit)

- Currently a standalone test script, not a proper module with `setup()`/`read()`/`close()`.
- Uses Adafruit ADS1115 library; reads channel A0 for soil moisture percentage.
- Calibration via `dry_value` / `wet_value` constants (not yet pulled from `config.xml`).

### `sensor/power_meter.py` — Power Meter (PZEM-017, RS485 Modbus)

- Currently a standalone scanner/diagnostic script, not a proper sensor module.
- Communicates via RS485 using Modbus RTU with GPIO DE/RE pin control (GPIO 17 via sysfs).
- CRC-16 calculation included. Serial port `/dev/ttyAMA10` at 9600 baud.

### `sensor/rpi_master.py` — Raspberry Pi I2C Master (Test Script)

- Standalone test script for I2C communication with the Arduino Mega at address `0x08`.
- Commands: `0xAA` (increment), `0xFF` (reset). Reads back a 4-byte little-endian uint32.

### `web/app.py` — Flask Server

- `UI_MODE` constant (top of file) controls dashboard mode:
  - `"sensors"` — sensor data only (default)
  - `"obstacles"` — sensor data + obstacle marker controls
- **Routes**:
  - `GET /` → renders `index.html` with `ui_mode`
  - `GET /api/snapshot` → returns `LATEST` dict as JSON
  - `POST /api/run/on` → calls `dev_stack.set_run_enabled(True)`, returns `{"ok": True}`
  - `POST /api/run/off` → calls `dev_stack.set_run_enabled(False)`
  - `POST /api/event` → logs obstacle events (payload: `{obstacle_id: int, action: "enter"|"exit"|"bypass"}`)
- `LATEST` is a global dict initialized with empty/default values; replaced by `set_latest()` each poll.

### `web/static/app.js` — Dashboard Frontend

- Polls `GET /api/snapshot` every **500ms** via `setInterval`.
- On connection failure, shows `"DISCONNECTED"` in the UI state pill.
- Health LEDs: green (`ok: true`), red (default, `ok: false`), yellow (warning).
- Key helpers: `setLED(id, state)`, `fillKV(containerId, rows)`, `validationLine(name, v)`, `fmtNum(x, digits)`, `fmtSec(s)`, `fmtInt(x)`.
- Validation phases displayed as: `COLLECT (M:SS left)`, `WARMUP (M:SS left)`, `STABILIZE (M:SS left)`, `VALID (N left)`, `DONE`.
- RUN ON/OFF buttons post to `/api/run/on` and `/api/run/off`.

### `web/templates/index.html` — Dashboard Template

- Dark-themed UI with CSS custom properties (`--bg: #0b0f14`, `--good: #22c55e`, `--bad: #ef4444`, `--warn: #f59e0b`).
- 12-column CSS grid layout. Cards span 4 columns by default; `.wide` spans 12, `.span6` spans 6.
- Responsive breakpoints: 6 columns at ≤1100px, full-width at ≤700px.
- Obstacle card is conditionally rendered only when `ui_mode == "obstacles"` (Jinja2 block).
- `obstacles.js` loaded only when `ui_mode == "obstacles"`.

### `spanner/validation.py` — Tool Validation State Machine

Tracks per-tool warmup/stabilization phases. Phase sequence:

```
off → collecting → warmup → stabilizing → valid_window → done
```

| Tool | collect_s | warmup_s | stabilize_s | Total wait | Valid samples |
|---|---|---|---|---|---|
| Air | 0 | 2s | 0 | 2s | 10 |
| Soil | 0 | 10s | 0 | 10s | 10 |
| Water | 10s | 0 | 170s | 180s (3 min) | 10 |

- `_ToolRule` resets fully on OFF edge; re-initializes on ON edge.
- `valid_sample = True` **only** during `valid_window` phase (counts down from N to 0).
- Output per tool: `{on, on_s, phase, valid_sample, valid_in_s, samples_left}`.
- Called in `main.py` as `compute_validation(tools, timers)`.

### `spanner/logger_dev.py` — JSONL Logger

- Appends each snapshot as a single JSON line to `data/dev_log.jsonl`.
- Creates `data/` directory if it doesn't exist.
- `log_snapshot(snap)` — always called, every poll cycle.
- `log_event(msg)` — optional named event (writes `{"ts": ..., "event": msg}`).

### `logger/sqlite_db.py` — SQLite Logger (**MANDATORY**)

- `SQLiteLogger(db_path)` class. **Must be active in `main.py` on every run** — not optional.
- Call `start(notes="")` to open DB, create schema, start a session; returns `session_id` (UUID).
- Pragmas: WAL mode, foreign keys ON, synchronous NORMAL.
- **Current schema** (partially complete — missing tables for power, air, soil, adc):
  - `sessions(session_id PK, started_utc, notes)`
  - `events(id, ts_utc, session_id FK, level, source, message, data_json)`
  - `telemetry_tmp102(id, ts_utc, session_id FK, temp_c, quality)`
  - `telemetry_bno055(id, ts_utc, session_id FK, roll_deg, pitch_deg, yaw_deg, calib_sys/gyr/acc/mag, quality)`
  - `telemetry_gps(id, ts_utc, session_id FK, lat, lon, speed_mps, sats, hdop, fix, quality)`
- **Missing telemetry tables** (not yet implemented): `telemetry_power`, `telemetry_air`, `telemetry_adc`, `telemetry_mega`
- Indexes on `ts_utc` for all telemetry tables.
- DB stored at path from `config.xml → <database><sqlite_path>`.

### `calibration/config.xml` — Master Configuration

Parsed once at startup by the GUI tools. Contains:

```
<rates>     sensor_read_hz=1, lcd_refresh_hz=2
<serial>    Mega port=/dev/ttyACM0 baud=115200, GPS port=/dev/ttyUSB0 baud=9600
<gpio>      WATER_SENSOR=17, SOIL_SENSOR=27, AIR_SENSOR=22, LCD_RESET=23
<i2c>       bus=1, BNO055=0x28, TMP102=0x48
<calibration>
  BNO055: mounting offsets (yaw/pitch/roll), accel/gyro/mag offsets
  TMP102: temp_offset_c=0.0
  pH sensor: settling_time=120s, two calibration points, computed slope/offset
  Soil: dry_ref=800, wet_ref=300
  Air: baseline=0.0
<database>  sqlite_path=data/rover_logs.sqlite
```

### `calibration/config_gui.py` — Config XML Editor (Tkinter)

- Tkinter GUI for editing `config.xml` with auto-backup before each save.
- Backups saved to `calibration/config_backups/` (auto-created).

### `spanner/GUI_help.py` — Team Helper GUI (Tkinter)

- Tabbed Tkinter GUI with two tabs:
  - **Git**: status, pull, push, commit with file selector (auto-unchecks `data/` files)
  - **Mega Upload**: compile and upload Arduino firmware via `arduino-cli`
- Runs all commands via `subprocess.run()` and displays output in a scrollable text widget.
- Firmware selection from subdirectories of `mega/`.

### `mega/rover_movement/rover_movement.ino` — Arduino Mega Firmware

- **Input**: iBUS RC receiver on Serial1. Reads channels CH1–CH3, CH5, CH7, CH8.
- **Failsafe**: If no valid signal for 500ms → stop all motors, move servos to safe position.
- **Motor control**: 6 motors on PWM pins `{2, 3, 6, 7, 9, 10}`, DIR pins `{22–27}`. MAX_PWM=160 (~63% duty). Trapezoidal acceleration (ACCEL_STEP=2, LOOP_DELAY=20ms). Direction change causes a 200ms stop pause.
- **Servo control**: 3 servos via PCA9685 (I2C PWM driver, 50Hz). CH5/CH7/CH8 toggle servos between SERVO_MIN=150 and SERVO_MAX=600.
- **LED status**: GPIO 30 (signal), 31 (CH5), 32 (CH7), 33 (CH8).
- Compiled with `arduino-cli` FQBN `arduino:avr:mega`, uploaded to `/dev/ttyACM0`.

---

## Data Files

| File | Purpose | Tracked in git |
|---|---|---|
| `data/dev_log.jsonl` | JSONL snapshot log, one line per poll | No (`*.jsonl` gitignored) |
| `data/rover_logs.sqlite` | SQLite telemetry database | Yes |
| `calibration/config.xml` | Master rover configuration | Yes |
| `calibration/config_backups/` | Auto-backups from GUI saves | Yes |

---

## Platform Constraints

- **`smbus`, `lgpio`, `RPi.GPIO`, `board`, `busio` are Linux/Pi-only** — hardware sensor modules will not import on Windows. Always use `dev_stack.py` on development machines.
- **`pynmea2` is not available via apt** — requires a separate Python venv with `--system-site-packages` on Pi. Guard GPS import with `try/except ImportError`.
- **`air.py` calls `setup()` and `disable_abc()` at module level** — importing it on a non-Pi machine will attempt to open a serial port and fail immediately.
- **On Raspberry Pi**, install Python packages via `apt`, not `pip` on system Python. See `herc_26_raspberry_pi_setup_guide_readme.md`.
- **`arduino-cli`** must be installed with the `arduino:avr` core to compile/upload Mega firmware.

---

## Known Technical Debt

These are existing inconsistencies noted for future cleanup:

1. **`soil.py` and `power_meter.py` are standalone scripts**, not proper sensor modules with `setup()`/`read()`/`close()`. They need to be refactored before being integrated into the real deployment stack.
2. **`gps.py` uses `open()` instead of `setup()`**, deviating from the standard interface pattern.
3. **`air.py` calls `setup()` at module import level** (outside `if __name__ == "__main__"`), causing immediate serial port access on import — this is a bug.
4. **`sensor/rpi_master.py`** is an I2C test script, not a driver module.
5. **Exception classes are inconsistent** — `tmp.py` uses `tmpSensorSetupError`/`tmpSensorReadError`, `air.py` uses `MHZ19CSetupError`/`MHZ19CReadError`, but `sensor/base.py` defines `SensorInitError`/`SensorReadError`. The wiki mandates sensor-specific exceptions; `base.py` exists but is not used by actual drivers.

---

## Development Rules

### Rules Mandated by the Wiki (HERC-26 SENSORS wiki page)

These are binding architectural rules from the project wiki. All sensor code must follow them:

1. **Sensors are responsible for only three things**: connecting to hardware, reading data, and reporting errors. They must never print output, write to log files, interact with databases, manage UI or Flask operations, or control any global state.

2. **A sensor never exits the program.** Failures raise exceptions — the system catches them and continues. Never call `sys.exit()`, `raise SystemExit`, or block indefinitely inside a sensor.

3. **Every sensor must implement**: `setup()` (initialize hardware), `read()` (retrieve sensor values), and optionally `close()` (cleanup). These are the only public functions.

4. **Each sensor defines its own specific exception classes** for setup and read failures (e.g., `TmpSensorSetupError`, `MHZ19CSetupError`). This enables clear error source identification and sensor-specific UI messaging. Do not reuse generic exceptions from `base.py` for real hardware drivers.

5. **Never silently return garbage values.** If data is invalid, unavailable, or out of range, raise the appropriate sensor exception. Do not return `0`, `-1`, `None`, or a default fallback when hardware has actually failed.

6. **Sensors return raw numeric values, strings, or dicts for grouped measurements.** They must never attach timestamps, format strings for display, or include logging flags in their return values.

7. **Fake/simulated sensors must mirror real sensor return structure exactly.** Function names, return key names, and exception behavior must be identical. No system-level code should need to change when switching from fake to real.

8. **Fake sensors include ~1% random failure probability** to simulate real hardware conditions during development.

### Rules Mandated by the Wiki (HERC-26 WEB wiki page)

These are binding architectural rules for the web/backend system:

9. **The `read_all()` function must always return a complete snapshot dict** with all required top-level keys: `ts`, `run_enabled`, `data`, `health`, `errors`, `validation`, `status_log`. Missing keys will break the UI.

10. **Flask only serves pre-computed snapshots.** No sensor reads, no timer computation, no business logic in Flask route handlers. Routes only read from `LATEST` and call `dev_stack` setters.

11. **The UI only displays information.** No timers, no data computation, no business logic in JavaScript. Timer countdowns are computed server-side; JS only formats and renders the values from the snapshot.

12. **The backend loop must continue regardless of Wi-Fi or UI state.** The sensor loop and JSONL logging must work even if no browser is connected.

### Rules Currently Followed (Observed in Codebase)

These patterns are established and must be maintained:

13. **Snapshot-first design** — every data source contributes to the snapshot dict. The snapshot is the single source of truth passed between sensor_loop, the logger, and Flask.

14. **Error isolation per sensor** — a failure in one sensor must never crash the sensor loop. Each sensor block in `read_all()` is wrapped independently in `try/except`. Errors go into `snap["errors"][name]`, health into `snap["health"][name]`.

15. **Health tracking with de-duplication** — `health[name] = {"ok": bool, "msg": str}` is updated every poll but only logged to `status_log` when the state changes from previous.

16. **Status log cap** — `_status_log` is capped at `STATUS_MAX = 200` entries. Always trim before it grows unbounded.

17. **Tool timers are computed server-side** — cumulative ON-time per tool (air/water/soil) is computed in `dev_stack.py` (and must be in real drivers), never in JavaScript.

18. **JSONL logging is unconditional** — `log_snapshot()` is called every poll. Do not add conditions to skip it.

19. **Daemon thread for sensor loop** — `threading.Thread(target=sensor_loop, daemon=True)`. Do not change this.

20. **No live config reload** — `config.xml` is parsed once at startup. Changes require a restart.

21. **UI mode is a file constant** — `UI_MODE` in `web/app.py` is changed by editing the file, not via env var or runtime config.

### Rules for Future Development

These guidelines must be followed when adding or modifying anything:

22. **Add new sensors to `dev_stack.py` first.** Before writing a real hardware driver, add simulated data for the new sensor to `dev_stack.py` with realistic random-walk values and clamped physical ranges. Verify it works end-to-end in the dashboard before touching hardware.

23. **Dev stack and real drivers must have identical data schemas.** Every key in `snap["data"]["sensor_name"]` must be present in both the simulated and real implementations. Mismatches will cause silent `None` values in the UI.

24. **New measurement tools with stabilization requirements must have a `_ToolRule` in `validation.py`.** Warmup/stabilization logic lives in `spanner/validation.py`, not scattered in `main.py`, `app.py`, or frontend code.

25. **Sensor loop must not be blocked.** Operations inside `sensor_loop()` must complete in well under 500ms. For slow operations (e.g., RS485 Modbus reads, long serial reads), use a dedicated background thread with a result queue.

26. **New Flask API routes must follow the existing response shape**: `{"ok": bool, ...}` on all paths. Match the pattern in `api_run_on()` and `api_event()`.

27. **Hardware addresses and port names do not belong in driver files.** They go in `calibration/config.xml`. Drivers should accept them as constructor parameters or read from config at startup — not hardcode them.

28. **Log significant state transitions, not poll-tick data.** Use `_log(msg)` for: startup, shutdown, run enable/disable, sensor health transitions, tool on/off edges. Do not log on every 500ms tick.

29. **New UI features go into the existing `"sensors"` mode first.** Only promote to a separate `UI_MODE` if the feature is operationally distinct (like the obstacle tracker).

30. **Arduino Mega serial protocol changes require documentation in the sketch header.** If the Pi-to-Mega communication format changes (baud rate, frame structure, command bytes), update the corresponding Pi driver and note the change in the `.ino` file's header comment.

31. **Config backups are managed automatically by the GUI.** Never manually delete from `calibration/config_backups/`. Do not add backup logic anywhere else.

32. **`SQLiteLogger` is mandatory.** It must be started in `main.py` on every run alongside JSONL logging. Both logging paths run unconditionally every poll cycle. The SQLite DB path is read from `config.xml` at startup.

33. **Do not break platform abstraction.** Any import of a Linux-only library (`smbus`, `lgpio`, `RPi.GPIO`, `board`, `busio`, `pynmea2`) must be guarded with `try/except ImportError`. The system must remain runnable on Windows in development mode.

---

---

## Project TODO List

This list was generated by reading every file in the repository and comparing the current code state against the architecture rules and requirements above. Items are grouped by area and marked with priority indicators.

Legend: 🔴 Bug / rule violation in existing code | 🟡 Incomplete feature | 🟢 Not started at all

---

### CRITICAL — Bugs in Existing Code

These break rules explicitly and must be fixed before deployment:

- 🔴 **`sensor/air.py` — `setup()` called at module level** (line 147–148). `setup()` and `disable_abc()` are called outside any `if __name__ == "__main__"` guard. Importing this file on Windows (or any non-Pi machine) immediately attempts to open `/dev/ttyAMA0` and crashes. Move these calls inside `if __name__ == "__main__"`.

- 🔴 **`sensor/air.py` — port `/dev/ttyAMA0` hardcoded in driver file** (line 21). Rule 27 says hardware addresses and port names belong in `config.xml`. The driver must accept the port as a parameter or read it from config at startup.

- 🔴 **`sensor/gps.py` — uses `open()` instead of `setup()`** (line 12). Violates rule 3. All sensor drivers must implement `setup()`, `read()`, `close()`. The GPS class uses `open()` instead of `setup()`, breaking the uniform interface.

- 🔴 **`sensor/gps.py` — no custom exception classes**. Returns `{"ok": False, "error": ...}` dicts on failure instead of raising exceptions. Violates rules 4 and 5. Must define `GPSSensorSetupError` and `GPSSensorReadError` and raise them instead of returning error dicts.

- 🔴 **`sensor/gps.py` — `pynmea2` import not guarded** (line 3). Will crash with `ImportError` on Windows where `pynmea2` is not installed. Must be wrapped with `try/except ImportError` per rule 33.

- 🔴 **`sensor/imu.py` — only implements `read_gforce()`, not `read()`** (line 29). Violates rule 3. The public interface must be `setup()` / `read()` / `close()`. `read_gforce()` is not a valid public function name per the sensor interface contract.

- 🔴 **`sensor/imu.py` — `read_gforce()` returns incomplete data** (lines 44–50). The snapshot schema requires `acceleration: {x, y, z}`, `orientation: {roll, pitch, yaw}`, `g_force: float`, and `velocity: {x, y, z}`. The current implementation only reads raw acceleration and converts to g-force — it does not read euler angles, does not expose individual axis accelerations in the required format, and has no velocity data at all.

- 🔴 **`sensor/imu.py` — `board` and `busio` imports not guarded** (lines 1–2). These are Pi/Linux-only libraries. Importing this file on Windows will crash. Must add `try/except ImportError` guard per rule 33.

- 🔴 **`sensor/tmp.py` — returns Fahrenheit but snapshot expects `temp_c`** (line 17). `TMP.setUnits('F')` means `read()` returns temperature in Fahrenheit. The snapshot schema field is `temp_c` (Celsius). This is a silent data error — the UI will show wrong values with the wrong unit.

- 🔴 **`sensor/tmp.py` — I2C address and bus hardcoded in driver** (line 15). `TMP102('C', 0x48, 1)` hardcodes the address and bus. Rule 27 says these belong in `config.xml` and must be passed as parameters.

- 🔴 **`sensor/tmp.py` — bare `except:` clauses** (lines 18, 26). Catches all exceptions including `KeyboardInterrupt` and `SystemExit`. Must be `except Exception:` at minimum. Bare `except:` is a latent bug.

- 🔴 **`sensor/soil.py` — module-level hardware access, no `setup()`/`read()`/`close()`** (lines 8–14). Hardware is accessed at import time (I2C bus created on line 8). This crashes immediately on Windows. This is a script, not a proper sensor module. Must be fully refactored.

- 🔴 **`sensor/power_meter.py` — GPIO configured at module level** (lines 29–31). `gpio_export()`, `gpio_set_direction()`, and `gpio_write()` are called at module-level, meaning they run on import. Also, this file is a scanner/diagnostic script, not a proper sensor module. Must be fully refactored.

---

### HIGH — Missing Core Integration

These features are needed for the system to work end-to-end:

- 🟡 **`main.py` — SQLiteLogger not connected**. `SQLiteLogger` is fully implemented in `logger/sqlite_db.py` but never instantiated in `main.py`. The sensor loop must call the SQLite logger every poll cycle alongside `log_snapshot()`. The DB path must be read from `config.xml`. Add: instantiate `SQLiteLogger`, call `start()` at boot, call logging methods each poll.

- 🟡 **`logger/sqlite_db.py` — missing telemetry tables for power, air, soil, adc**. The schema only has `telemetry_tmp102`, `telemetry_bno055`, and `telemetry_gps`. There are no tables or methods for: power (voltage, current, watts), air (co2_ppm), adc (ph_value, moisture_value, raw, sensor_voltage), or mega (tool states, movement, ibus_pulse). These must be added to match the full snapshot schema.

- 🟡 **`logger/tools/log_viewer_gui.py` — only shows 3 sensor tables**. The viewer (`QUERIES` dict, lines 10–28) only queries `events`, `telemetry_tmp102`, `telemetry_bno055`, and `telemetry_gps`. When the missing tables are added to SQLite, the viewer must be updated to expose them.

- 🟡 **`main.py` — `config.xml` never read at runtime**. The config file exists with sensor rates, serial ports, I2C addresses, calibration values, and the SQLite path — but `main.py` imports nothing from it. All of this is currently hardcoded or ignored. A config-reading utility must be created and used at startup to pass values to drivers and set the poll rate.

- 🟡 **No real deployment stack** — `main.py` is permanently wired to `dev_stack`. There is no mechanism to switch to real sensor drivers for Pi deployment. A clean swap (e.g., import guard checking platform, or a `USE_REAL_SENSORS` flag in `main.py`) must be implemented before field use.

---

### MEDIUM — Sensor Driver Incompleteness

These drivers exist but don't fully satisfy the snapshot schema or interface rules:

- 🟡 **`sensor/imu.py` — orientation and velocity not implemented**. The BNO055 sensor provides euler angles (roll, pitch, yaw) via `IMU.euler` and linear acceleration via `IMU.linear_acceleration`. Neither is currently read. The `read()` function must return the full IMU dict matching the snapshot schema.

- 🟡 **`sensor/soil.py` — needs full refactor into proper module**. Must become a module with `SoilSensorSetupError`, `SoilSensorReadError`, `setup()`, `read()`, `close()`. `read()` must return the full ADC snapshot dict: `{"raw": {"ph": int, "moisture": int}, "sensor_voltage": {"ph": float, "moisture": float}, "ph_value": float, "moisture_value": float}`. Calibration values (`dry_ref`, `wet_ref`, pH slope/offset) must be read from `config.xml`.

- 🟡 **`sensor/power_meter.py` — needs full refactor into proper module**. Must become a module with `PowerSensorSetupError`, `PowerSensorReadError`, `setup()`, `read()`, `close()`. `read()` must return `{"voltage_v": float, "current_a": float, "power_w": float}`. Port and Modbus address must come from `config.xml`.

- 🟡 **`sensor/gps.py` — snapshot keys don't match schema**. The GPS `read()` returns `utc_time`, `utc_date`, `speed_knots`, `course_deg`, but the snapshot schema only uses `timestamp`, `lat`, `lon`. The return structure must be reconciled — either the schema is updated or the driver output is remapped in `dev_stack` / the real stack.

- 🟡 **No Pi-Mega communication driver**. `sensor/rpi_master.py` is a test script for I2C with the Mega (address 0x08). There is no real driver that reads tool states (`air`, `water`, `soil`), iBUS pulse, and movement string from the Mega and feeds them into the snapshot. This is currently simulated by `dev_stack`. A real `mega.py` driver module is needed for deployment.

---

### LOW — Calibration System Stubs

All calibration menu actions are non-functional placeholders:

- 🟢 **`calibration/calibration.py` — BNO055 calibration is a stub** (line 15–18). Prints "done" and does nothing. Must implement actual BNO055 offset collection and write computed values to `config.xml`.

- 🟢 **`calibration/calibration.py` — pH sensor calibration is a stub** (line 20–23). Prints "done" and does nothing. Must implement two-point calibration (buffer solutions at pH 4 and pH 7), compute slope/offset, and save to `config.xml`.

- 🟢 **`calibration/calibration.py` — soil moisture calibration is a stub** (line 25–28). Prints "done" and does nothing. Must implement dry/wet reference collection and write `dry_ref`/`wet_ref` to `config.xml`.

- 🟢 **`calibration/calibration.py` — air sensor calibration is a stub** (line 30–33). Prints "done" and does nothing. Must implement baseline zero-point calibration and update `config.xml`.

- 🟢 **`calibration/calibration.py` — "View current config" is a stub** (line 40–43). Prints "done" and does nothing. Must read and display key fields from `config.xml`.

- 🟢 **`calibration/config.xml` — pH calibration values are zeroed out** (lines 83–94). `slope=0.0` and `offset=0.0` mean the pH calculation is non-functional. These values will only be correct after real calibration is performed and saved.

---

### NOT STARTED — Missing Entire Features

These have no code at all yet:

- 🟢 **Config reader utility**. There is no module that parses `config.xml` and returns a structured config object. One must be created (e.g., `calibration/config_reader.py`) and used in `main.py` at startup to supply port names, I2C addresses, calibration constants, poll rate, and the SQLite path to the rest of the system.

- 🟢 **Real sensor integration in `sensor_loop()`**. When running on Pi, the sensor loop needs to call the real hardware drivers instead of `dev_stack`. The architecture for switching (platform detection, import guards, initialization) does not exist yet.

- 🟢 **SQLite telemetry writes in sensor loop**. Once `SQLiteLogger` is integrated into `main.py`, the sensor loop must call the appropriate `log_*()` method for each sensor after each successful read. These per-sensor calls don't exist yet.

- 🟢 **`telemetry_power` SQLite table and `log_power()` method**. No schema, no method, not implemented in `sqlite_db.py`.

- 🟢 **`telemetry_air` SQLite table and `log_air()` method**. No schema, no method, not implemented in `sqlite_db.py`.

- 🟢 **`telemetry_adc` SQLite table and `log_adc()` method**. No schema, no method, not implemented in `sqlite_db.py`.

- 🟢 **`telemetry_mega` SQLite table and `log_mega()` method**. No schema, no method, not implemented in `sqlite_db.py`.

---

## User Rules

<!-- Add your own rules below this line -->
