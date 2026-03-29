# Web Dashboard & Backend Architecture

**MOVIS Rover – HERC-26**

This document explains **how the web dashboard works**, **how it connects to the rover backend**, **what data it expects**, and **how to deploy it on a Raspberry Pi**.

This wiki is written for **first-time web developers** and future team members.

---

## 1. What This Web System Is (High Level)

The web system is **NOT an app running on the tablet**.

It is:

* A **web server running on the rover computer** (Laptop now, Raspberry Pi later)
* The tablet/phone/laptop just opens a **web page** in a browser
* Communication happens over **Wi-Fi using HTTP**

### Why this approach?

* No app installation needed
* Works on any device (tablet, phone, laptop)
* Survives Wi-Fi disconnection
* Easy to debug and extend

---

## 2. Overall Architecture

```
┌──────────────────────┐
│   Sensors / dev_stack│
│   (real or fake)     │
└──────────┬───────────┘
           │ read_all()
           ▼
┌──────────────────────┐
│ Backend Core (main)  │
│ - timers             │
│ - validation         │
│ - state              │
│ - logging            │
└──────────┬───────────┘
           │ snapshot (dict)
           ▼
┌──────────────────────┐
│ Flask Web Server     │
│ /api/snapshot        │
│ /api/run/on|off      │
│ /api/event (later)   │
└──────────┬───────────┘
           │ JSON
           ▼
┌──────────────────────┐
│ Web UI (Browser)     │
│ HTML + JS            │
│ Dark dashboard       │
└──────────────────────┘
```

---

## 3. How the System Works (Step-by-Step)

### 3.1 Backend Loop (Most Important Part)

1. The rover runs `main.py`
2. A background loop runs every fixed interval (e.g., 0.5s)
3. That loop:

   * calls `read_all()`
   * updates timers
   * computes validation
   * logs data
   * stores the latest snapshot in memory

The backend **never stops**, even if:

* Wi-Fi disconnects
* Browser closes
* UI crashes

---

### 3.2 Flask Web Server

Flask is a **Python web server**.

It provides:

* `/` → the dashboard web page
* `/api/snapshot` → latest rover data (JSON)
* `/api/run/on` → sets run flag ON
* `/api/run/off` → sets run flag OFF

Flask **does not read sensors**.
It only **serves data already prepared by the backend**.

---

### 3.3 Web UI (Browser)

The web page:

* loads once
* then repeatedly calls `/api/snapshot` (every ~500 ms)
* updates the display (values, LEDs, timers)

If Wi-Fi drops:

* browser stops updating
* backend keeps running and logging
* when Wi-Fi returns, UI resumes

---

## 4. `read_all()` – The Core Contract

### 4.1 What is `read_all()`?

`read_all()` is a **single function** that returns **everything the rover knows right now**.

It must:

* never crash the program
* always return a dictionary
* handle missing sensors gracefully

---

### 4.2 Required Output Structure (Schema v1)

`read_all()` must return **at least**:

```python
{
  "ts": float,            # UNIX timestamp
  "run_enabled": bool,    # run switch state

  "data": {...},          # all sensor values
  "health": {...},        # green/red status
  "errors": {...},        # sensor errors (if any)
  "validation": {...},    # data validity
  "status_log": [...]     # system messages
}
```

If a field is missing, the UI **will break**.

---

## 5. Expected Sensor Data Types

### 5.1 Power Meter

```python
"power": {
  "voltage_v": float,
  "current_a": float,
  "power_w": float
}
```

Units:

* Volts (V)
* Amps (A)
* Watts (W)

---

### 5.2 Temperature Sensor

```python
"temperature": {
  "temp_c": float
}
```

* Always Celsius
* No unit switching in UI

---

### 5.3 GPS

```python
"gps": {
  "timestamp": int,   # UTC time from GPS
  "lat": float,
  "lon": float
}
```

If GPS unavailable:

* values can be `None`
* health flag must show error

---

### 5.4 IMU

```python
"imu": {
  "acceleration": {"x": float, "y": float, "z": float},
  "orientation": {"roll": float, "pitch": float, "yaw": float},
  "g_force": float,
  "velocity": {"x": float, "y": float, "z": float}
}
```

All values must be numeric or `None`.

---

### 5.5 ADC (pH + Moisture)

```python
"adc": {
  "raw": {
    "ph": int,
    "moisture": int
  },
  "sensor_voltage": {
    "ph": float,
    "moisture": float
  },
  "ph_value": float,
  "moisture_value": float
}
```

If sensor missing:

* set values to `None`
* do not divide by zero

---

### 5.6 Air Sensor (CO₂)

```python
"air": {
  "co2_ppm": int
}
```

---

### 5.7 Arduino Mega (RC + Tools)

```python
"mega": {
  "movement": "FWD|REV|LEFT|RIGHT|STOP",
  "ibus_ok": bool,
  "tools": {
    "air": bool,
    "water": bool,
    "soil": bool
  }
}
```

* UI only shows **green/red light** for iBUS
* Numeric pulse values not displayed

---

## 6. Validation Data (Derived, Not Sensor)

Validation is computed **after** reading sensors.

```python
"validation": {
  "water": {
    "on": bool,
    "on_s": float,
    "phase": "collecting|stabilizing|valid_window|done",
    "valid_sample": bool,
    "samples_left": int,
    "valid_in_s": float
  },
  "air": {...},
  "soil": {...}
}
```

Purpose:

* Identify which data is **trustworthy**
* Enable filtering during analysis
* Prevent garbage pH / sensor values

---

## 7. Health Flags (LEDs)

Each sensor must have:

```python
"health": {
  "power": {"ok": bool, "msg": str},
  "temperature": {"ok": bool, "msg": str},
  "gps": {"ok": bool, "msg": str},
  "imu": {"ok": bool, "msg": str},
  "adc": {"ok": bool, "msg": str},
  "air": {"ok": bool, "msg": str},
  "mega": {"ok": bool, "msg": str}
}
```

Rules:

* `ok=True` → green LED
* `ok=False` → red LED
* `msg` shown under card

---

## 8. Status Log (System Messages)

```python
"status_log": [
  {"ts": float, "msg": str},
  ...
]
```

Used for:

* sensor connected
* sensor disconnected
* run toggled
* obstacle markers
* errors

This is **not debug print spam**.

---

## 9. Logging (What Is Logged)

### Logged continuously:

* full snapshot
* validation flags
* run_enabled state
* timers
* movement + tool states

### Not logged yet (future):

* obstacle markers
* bypass decisions
* notes

These will be added as **events table** in SQLite.

---

## 10. Raspberry Pi Deployment Guide

### 10.1 OS

* Raspberry Pi OS Lite or Desktop
* Python 3.9+

### 10.2 Required packages

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git
```

### 10.3 Run the system

```bash
cd HERC-26
python3 main.py
```

### 10.4 Access from tablet

1. Find Pi IP:

```bash
hostname -I
```

2. Open browser:

```
http://<pi_ip>:5000
```

Tablet and Pi must be on the **same Wi-Fi network**.

---

## 11. Common Mistakes to Avoid

❌ Printing from sensors
❌ Computing timers in browser
❌ Doing SQL inside Flask routes
❌ UI depending on Wi-Fi uptime
❌ Sensors returning garbage instead of errors

---

## 12. Why This Architecture Matters for HERC

* Robust under field conditions
* Partial sensor failure tolerated
* Post-mission analysis possible
* Clear audit trail of rover behavior
* Easy to extend for autonomy later

---

## 13. Summary (Read This If Nothing Else)

* Backend always runs
* UI only displays data
* `read_all()` is the single source of truth
* Validation determines what data is usable
* Logging enables full mission replay

---

