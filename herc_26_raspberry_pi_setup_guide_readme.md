# HERC-26 – Raspberry Pi Setup Guide

This document describes how to run the Raspberry Pi side of the **HERC-26** system.

It is written for **Raspberry Pi OS 64-bit (Bookworm / Trixie)** and assumes the project was downloaded as a **ZIP file**.

---

## Target Platform

- Raspberry Pi 5 (primary target — uses `/dev/gpiochip4`)
- Raspberry Pi 4 (also supported — uses `/dev/gpiochip0`)
- Raspberry Pi OS 64-bit
- System Python 3
- No virtual environments for the main system

---

## 1. Extract the Project (ZIP Users)

```bash
echo "Moving to home directory..."
cd ~

echo "Extracting project ZIP..."
unzip HERC-26*.zip

echo "Renaming folder..."
mv HERC-26-* HERC-26
cd HERC-26
```

---

## 2. Enable Hardware Interfaces (REQUIRED)

```bash
echo "Opening raspi-config..."
sudo raspi-config
```

Enable the following options:

- **Interface Options → I2C → Enable**
- **Interface Options → SPI → Enable**
- **Interface Options → Serial**
  - Login shell: **NO**
  - Serial hardware: **YES**

Then reboot:

```bash
sudo reboot
```

---

## 3. Install All Required Packages (APT ONLY)

This installs everything required by the current Python files, except GPS parsing.

```bash
echo "Installing system and Python packages..."
sudo apt update
sudo apt install -y \
  git \
  curl \
  build-essential \
  swig \
  i2c-tools \
  python3-full \
  python3-dev \
  python3-libgpiod \
  python3-smbus \
  python3-serial \
  python3-tk
```

### Why These Are Needed

| Package            | Used By                                          |
|--------------------|--------------------------------------------------|
| python3-libgpiod   | RS485 DE/RE GPIO control in power_meter.py       |
| python3-smbus      | TMP102, DFRobot ADS1115                          |
| python3-serial     | GPS, RS485 power meter                           |
| python3-tk         | All GUIs                                         |
| i2c-tools          | I2C debugging (`i2cdetect`)                      |

> **Pi 5 vs Pi 4 GPIO chip:** `python3-libgpiod` uses the kernel character device
> ABI (`/dev/gpiochipN`). On Pi 5 this is `/dev/gpiochip4`; on Pi 4 it is
> `/dev/gpiochip0`. Set `gpio_chip` in `config.xml` to match your board.

---

## 4. User Permissions (CRITICAL)

```bash
echo "Adding user to hardware access groups..."
sudo usermod -aG gpio,i2c,spi,serial,dialout $USER
sudo reboot
```

After reboot:

```bash
groups
```

Must include:

```
gpio i2c spi dialout
```

---

## 5. GPS Support (Important Exception)

### The Problem

- `gps.py` imports `pynmea2`
- `pynmea2` is **not available via apt**
- `pip install` is blocked by Raspberry Pi OS (PEP 668)

### Supported Options

#### Option A (Recommended for Now): Disable GPS

- Do nothing
- Do not run `gps.py`
- All other sensors and GUIs work

#### Option B (Clean GPS Support): GPS-Only Virtual Environment

```bash
echo "Creating GPS-only virtual environment..."
python3 -m venv gps_venv

echo "Installing pynmea2..."
source gps_venv/bin/activate
pip install pynmea2
deactivate
```

Run GPS like this:

```bash
gps_venv/bin/python3 gps.py
```

Only GPS uses this virtual environment.
All other project code uses system Python.

---

## 6. Adafruit Blinka — lgpio Shim (Pi 5 Required)

### The Problem

Adafruit Blinka (`adafruit-blinka`) auto-detects Raspberry Pi and tries to
`import lgpio` at load time when running on the Pi GPIO backend. The real
`lgpio` library uses `/dev/mem` / sysfs paths that **do not work on the Pi 5
RP1 chip**. This causes an `ImportError` or `RuntimeError` the moment any code
does `import board` or `import busio` (used by `imu.py` and `soil.py`).

### The Fix

`compat/lgpio.py` is a drop-in shim that implements the exact API surface
Blinka calls, backed by `gpiod` (libgpiod v2). Installing it into site-packages
makes `import lgpio` resolve to the shim instead of the real package.

```bash
# From the project root. Uses --break-system-packages because Pi OS blocks
# pip on system Python — this is intentional for local ./ installs only.
echo "Installing lgpio shim for Pi 5..."
pip install --break-system-packages ./compat
```

Verify the shim is active:

```bash
python3 -c "import lgpio; print('lgpio shim OK')"
```

### Why This Is Safe

- The shim is a local `./compat/pyproject.toml` package, not a PyPI package.
- It only replaces `lgpio` — no other packages are affected.
- On Windows/Linux dev machines the shim imports without error (gpiod import
  is guarded with `try/except ImportError`), so `import board` remains safe
  to add to non-Pi code as long as it stays behind a platform guard.
- If `imu.py` and `soil.py` only ever use `busio.I2C` (I2C via `/dev/i2c-1`),
  the GPIO functions in the shim are never called — but Blinka still needs the
  module importable to proceed past its own startup checks.

---

## 7. Verify Hardware

### I2C Scan

```bash
echo "Scanning I2C bus..."
sudo i2cdetect -y 1
```

Expected examples:

```
48  # ADS1115
49  # TMP102
28  # BNO055
```

### Verify Python Imports

```bash
echo "Verifying Python imports..."
python3 - << 'EOF'
modules = [
  "smbus",
  "serial",
  "gpiod",
  "lgpio",    # must resolve to compat/lgpio.py shim (section 6)
  "sqlite3",
  "tkinter"
]
for m in modules:
    try:
        __import__(m)
        print("OK:", m)
    except Exception as e:
        print("FAIL:", m, e)
EOF
```

---

## 8. File to Dependency Map (Source of Truth)

| File                     | Interface              |
|--------------------------|------------------------|
| tmp102.py                | I2C (smbus)            |
| DFRobot_ADS1115.py       | I2C (smbus)            |
| soil.py                  | I2C (ADS1115)          |
| DFRobot_PH.py            | Logic only             |
| DFRobot_EC.py            | Logic only             |
| gps.py                   | Serial + NMEA          |
| power_meter.py           | GPIO + Serial          |
| config_gui.py            | Tkinter GUI            |
| log_viewer_gui.py        | Tkinter GUI            |
| sqlite_db.py             | SQLite                 |

---

## 9. Running the System

### Config GUI

```bash
echo "Launching config GUI..."
python3 config_gui.py
```

### Log Viewer

```bash
echo "Launching log viewer..."
python3 logging/tools/log_viewer_gui.py
```

### Main System

```bash
echo "Starting HERC-26..."
python3 main.py
```

This will:

- Initialize sensors
- Create the SQLite database
- Start logging

---

## 10. Minimal Readiness Test

```bash
echo "Testing TMP102..."
python3 tmp102.py

echo "Starting main system..."
python3 main.py
```

If these run without import errors, the Raspberry Pi is ready.

---

## 11. Rules (Do Not Break)

```
RULES:
- Do NOT use pip on system Python (except: pip install --break-system-packages ./compat for the lgpio shim)
- Do NOT sudo pip install anything
- Use apt for all system dependencies
- GPS uses a separate virtual environment if enabled
```

---

## Appendix — Troubleshooting & GPS virtualenv

This appendix records fixes and commands used while testing on Raspberry Pi. Add or follow these if you hit missing-module errors, failed builds, or GPS-related issues.

### Make GPS optional at import-time

If `main.py` fails because `pynmea2` (or other GPS deps) are missing, change `sensor/__init__.py` to import GPS safely:

```python
try:
    from sensor.gps import GPS
except ImportError:
    GPS = None
```

Then guard any code that instantiates GPS with:

```python
if GPS is not None:
    gps = GPS(...)
else:
    gps = None
```

This allows the main system to run even when GPS dependencies are not installed.

### GPS virtualenv (clean workflow)

Create a GPS-only virtual environment that can also access apt-installed system packages (so hardware libraries like `lgpio` work):

```bash
cd ~/Desktop/HERC-26
rm -rf gps_venv
python3 -m venv --system-site-packages gps_venv
source gps_venv/bin/activate
pip install pynmea2 pyserial smbus2
deactivate
```

Important: do **not** try to `pip install gpiod`. `python3-libgpiod` must be
installed via apt so it links against the system libgpiod ABI:

```bash
sudo apt update
sudo apt install -y python3-libgpiod
```

This combination keeps the venv clean while allowing it to use system-level hardware bindings.

### Sanity / import check (inside venv)

```bash
source gps_venv/bin/activate
python3 - <<'EOF'
modules = [
    "pynmea2",
    "serial",
    "gpiod",
    "smbus",
    "sqlite3",
    "tkinter"
]
for m in modules:
    try:
        __import__(m)
        print("OK:", m)
    except Exception as e:
        print("FAIL:", m, e)
EOF
```

Notes:
- `python3-tk` (Tkinter) and `python3-libgpiod` are apt packages and must be installed via `sudo apt install`.
- Never use `sudo pip install` for system/hardware libraries.
- If a pip package fails to build, install the apt equivalent and recreate the venv with `--system-site-packages`.

---

