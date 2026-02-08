# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HERC-26 is a rover telemetry and control system for the HERC (Human Exploration Rover Challenge) competition. It collects sensor data (temperature, GPS, IMU, soil/pH/moisture, air quality, power), logs it, and displays it via a real-time web dashboard. The system runs on a Raspberry Pi with an Arduino Mega as a co-processor for tools/movement.

## Running the System

```bash
# Start the main system (sensor loop + Flask dashboard)
python main.py
# Dashboard available at http://127.0.0.1:5000
# Change host to 0.0.0.0 in main.py for network access from tablet

# Calibration text menu
python calibration/calibration.py

# Config XML editor GUI (Tkinter)
python calibration/config_gui.py

# Team helper GUI (git + Mega firmware upload)
python spanner/GUI_help.py

# Log viewer
python logger/tools/log_viewer_gui.py
```

There is no test suite or linter configured.

## Architecture

### Two operating modes

- **Development (Windows/laptop):** `sensor/dev_stack.py` generates simulated sensor data with random walks and configurable failure probability. This is the current default in `main.py`.
- **Deployment (Raspberry Pi):** Real sensor modules in `sensor/` talk to hardware via I2C (smbus), serial, and GPIO. These only work on Linux/Pi.

### Main loop (`main.py`)

A background thread (`sensor_loop`) polls `dev_stack.read_all()` every 0.5s, computes validation state, logs to JSONL, and updates the Flask app's shared snapshot. The Flask server runs on the main thread.

### Snapshot schema

Every read cycle produces a snapshot dict:
```
{ts, run_enabled, schema_version, data:{power, gps, imu, temperature, adc, air, mega, timers}, errors:{}, health:{}, validation:{}, status_log:[]}
```

### Key modules

| Module | Role |
|---|---|
| `sensor/dev_stack.py` | Simulated sensor stack (development). Returns full snapshot dict. |
| `sensor/tmp.py`, `soil.py`, `gps.py`, `power_meter.py` | Real hardware sensor drivers (Pi only). Each follows `setup()`/`read()`/`close()` pattern. |
| `sensor/base.py` | `SensorInitError` and `SensorReadError` exception classes. |
| `web/app.py` | Flask app. Serves dashboard, exposes `/api/snapshot` (GET), `/api/run/on|off` (POST), `/api/event` (POST). |
| `web/static/app.js` | Dashboard JS. Polls `/api/snapshot` every 500ms, renders sensor cards with health LEDs. |
| `web/templates/index.html` | Main dashboard template. `obstacles.html` is an alternate UI mode. |
| `spanner/validation.py` | Stateful per-tool validation: tracks warmup/stabilize/valid-window phases for air (2s), soil (10s), water (180s total). |
| `spanner/logger_dev.py` | JSONL file logger to `data/dev_log.jsonl`. |
| `logger/sqlite_db.py` | `SQLiteLogger` class with session-based schema (sessions, events, telemetry tables for TMP102/BNO055/GPS). DB stored at `data/rover_logs.sqlite`. |
| `calibration/` | Text-menu calibration system (`klm_menu`-based) and Tkinter XML config editor with auto-backup. |
| `mega/` | Arduino sketches for the Mega co-processor: `arm/`, `blink/`, `rover_movement/`, `modbus_led_slave_mega/`. Compiled/uploaded via `arduino-cli`. |

### Web dashboard UI modes

Set `UI_MODE` in `web/app.py`:
- `"sensors"` — sensor dashboard only (default)
- `"obstacles"` — sensor dashboard + obstacle marker controls

## Platform Constraints

- **smbus/lgpio are Linux-only** — sensor hardware modules will not import on Windows. Dev uses `dev_stack.py` instead.
- **GPS requires `pynmea2`** — not available via apt; needs a separate venv with `--system-site-packages` on Pi. GPS import may fail; guard with try/except in `sensor/__init__.py`.
- **On Raspberry Pi, use apt for Python packages** (not pip on system Python). See `herc_26_raspberry_pi_setup_guide_readme.md` for full setup.
- **Arduino Mega firmware** is compiled/uploaded with `arduino-cli` using FQBN `arduino:avr:mega` on port `/dev/ttyACM0`.

## Data Files

- `data/dev_log.jsonl` — JSONL snapshot log (gitignored via `*.jsonl`)
- `data/rover_logs.sqlite` — SQLite telemetry database
- `calibration/config.xml` — rover configuration; backups go to `calibration/config_backups/` (auto-created by config GUI)
