"""
sensor/real_stack.py — Physical sensor stack for Raspberry Pi deployment.

Drop-in replacement for dev_stack.py.  Identical public API:
    setup(...)
    set_run_enabled(value: bool)
    read_all() -> dict

Threading model
───────────────
Each sensor runs in its own daemon thread (_sensor_worker).  The worker
loops continuously: read → cache result → sleep → repeat.  read_all()
assembles the snapshot from the cache instantly — it never blocks on hardware.

This means:
  • The web dashboard always refreshes at the full 500 ms poll rate.
  • Slow sensors (GPS serial reads, RS485 Modbus timeouts) only affect their
    own cache update rate, not the rest of the system.
  • Sensors that are offline retry on every worker loop iteration (1 s sleep
    on failure), so reconnect still happens automatically.

Sleep intervals per worker:
  • Read OK   → 0.1 s  (fast sensors like IMU/TMP stay responsive)
  • Read fail → 1.0 s  (back-off before reconnect attempt)

Auto-reconnect behaviour
────────────────────────
Each sensor has a flag (_sensor_up) and cached setup kwargs (_sensor_cfg).
Every worker loop iteration, for each sensor:

  • Sensor was UP   → call read()
      - read OK          → update cache with data
      - read fails       → attempt close() + setup() immediately
                               reconnect OK   → call read() once more
                               reconnect fail → mark offline, cache error

  • Sensor was DOWN → attempt close() + setup() immediately
      - reconnect OK   → call read()
      - reconnect fail → cache offline error

Missing drivers
───────────────
  mega.py  — not yet written.  Stub records a permanent health error.
  ph       — hardware TBD.    Stub records a permanent health error.
Replace each stub with _poll_sensor(...) once the driver exists.
"""

import time
import threading

# ─────────────────────────────────────────────────────────────────────────────
# Sensor imports — one guarded block per module.
# Failed imports are stored in _import_errors[name] and surfaced in health[].
# ─────────────────────────────────────────────────────────────────────────────

_import_errors: dict = {}

try:
    from sensor import tmp as _tmp
except ImportError as _e:
    _tmp = None
    _import_errors["temperature"] = str(_e)

try:
    from sensor import gps as _gps
except ImportError as _e:
    _gps = None
    _import_errors["gps"] = str(_e)

try:
    from sensor import imu as _imu
except ImportError as _e:
    _imu = None
    _import_errors["imu"] = str(_e)

try:
    from sensor import air as _air
except ImportError as _e:
    _air = None
    _import_errors["air"] = str(_e)

try:
    from sensor import soil as _soil
except ImportError as _e:
    _soil = None
    _import_errors["adc"] = str(_e)

try:
    from sensor import power_meter as _power
except ImportError as _e:
    _power = None
    _import_errors["power"] = str(_e)

try:
    from sensor import mega as _mega
except ImportError as _e:
    _mega = None
    _import_errors["mega"] = str(_e)


# ─────────────────────────────────────────────────────────────────────────────
# Module state
# ─────────────────────────────────────────────────────────────────────────────

run_enabled: bool  = False
_status_log: list  = []
STATUS_MAX         = 200
_last_health: dict = {}

_tool_on_since = {"air": None,  "water": None,  "soil": None}
_tool_elapsed  = {"air": 0.0,   "water": 0.0,   "soil": 0.0}

# True when the sensor is connected and ready to read.
_sensor_up: dict = {
    "temperature": False,
    "gps":         False,
    "imu":         False,
    "air":         False,
    "adc":         False,
    "power":       False,
    "mega":        False,
}

# Setup kwargs cached at startup — used verbatim on every reconnect attempt.
_sensor_cfg: dict = {}

# ─────────────────────────────────────────────────────────────────────────────
# Per-sensor result cache — written by worker threads, read by read_all().
# Each entry: {"data": dict|None, "error": str|None, "ok": bool, "msg": str}
# ─────────────────────────────────────────────────────────────────────────────

_SENSOR_NAMES = ("temperature", "gps", "imu", "air", "adc", "power", "mega")

_cache: dict = {
    name: {"data": None, "error": "starting...", "ok": False, "msg": "starting..."}
    for name in _SENSOR_NAMES
}
_cache_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg: str):
    _status_log.append({"ts": time.time(), "msg": msg})
    if len(_status_log) > STATUS_MAX:
        del _status_log[0]


def _update_health(out: dict, name: str, ok: bool, msg: str):
    """Write health entry and log only when state actually changes."""
    out["health"][name] = {"ok": bool(ok), "msg": msg or ""}
    prev = _last_health.get(name)
    curr = (bool(ok), msg or "")
    if prev != curr:
        _last_health[name] = curr
        label = f"{name}: {'OK' if ok else 'FAIL'}"
        _log(f"{label} — {msg}" if msg else label)


def _update_tool_timers(tools: dict):
    """Accumulate per-tool ON-time.  tools = {"air": bool, "water": bool, "soil": bool}."""
    now = time.time()
    for k in ("air", "water", "soil"):
        is_on    = bool(tools.get(k, False))
        on_since = _tool_on_since[k]
        if is_on and on_since is None:
            _tool_on_since[k] = now
        elif (not is_on) and on_since is not None:
            _tool_elapsed[k] += now - on_since
            _tool_on_since[k] = None


def _get_timer_s(k: str) -> float:
    base = _tool_elapsed[k]
    if _tool_on_since[k] is not None:
        base += time.time() - _tool_on_since[k]
    return base


def _try_reconnect(name: str, mod) -> bool:
    """
    Attempt mod.close() → mod.setup(**_sensor_cfg[name]).
    Updates _sensor_up[name].  Returns True on success.  Never raises.
    """
    cfg = _sensor_cfg.get(name, {})
    try:
        mod.close()
    except Exception:
        pass  # close() must not prevent a reconnect attempt
    try:
        mod.setup(**cfg)
        _sensor_up[name] = True
        _log(f"{name}: reconnected OK")
        return True
    except Exception as e:
        _sensor_up[name] = False
        _log(f"{name}: reconnect failed — {e}")
        return False


def _poll_sensor(name: str, out: dict, mod):
    """
    Poll one sensor with full auto-reconnect logic.

    Writes into out["data"][name] on success, or out["errors"][name] on
    failure, and always updates out["health"][name].

    mod: the imported sensor module, or None if its import failed on this
         platform (e.g. board/busio unavailable on a dev machine).
    """
    # ── Module not available on this platform ──────────────────────────────
    if mod is None:
        err = _import_errors.get(name, "module unavailable")
        out["errors"][name] = err
        _update_health(out, name, False, err)
        return

    # ── Sensor currently offline → attempt reconnect first ─────────────────
    if not _sensor_up[name]:
        if _try_reconnect(name, mod):
            # Reconnected — try one read
            try:
                out["data"][name] = mod.read()
                _update_health(out, name, True, "")
            except Exception as e:
                _sensor_up[name] = False
                out["errors"][name] = str(e)
                _update_health(out, name, False, f"read failed after reconnect: {e}")
        else:
            out["errors"][name] = "offline — reconnect failed"
            _update_health(out, name, False, "offline — reconnect failed")
        return

    # ── Sensor online → normal read ────────────────────────────────────────
    try:
        out["data"][name] = mod.read()
        _update_health(out, name, True, "")
    except Exception as e:
        _sensor_up[name] = False
        # Immediate reconnect attempt within this same poll cycle
        if _try_reconnect(name, mod):
            try:
                out["data"][name] = mod.read()
                _update_health(out, name, True, "")
            except Exception as e2:
                out["errors"][name] = str(e2)
                _update_health(out, name, False, f"read failed after reconnect: {e2}")
        else:
            out["errors"][name] = str(e)
            _update_health(out, name, False, str(e))


def _write_cache(name: str, data, error, ok: bool, msg: str):
    """Update one sensor's cache entry (thread-safe)."""
    with _cache_lock:
        _cache[name] = {"data": data, "error": error, "ok": ok, "msg": msg}


def _sensor_worker(name: str, mod):
    """
    Daemon thread for one sensor.  Runs continuously — reads the sensor,
    writes the result to _cache, then sleeps before the next iteration.

    Sleep intervals:
      0.1 s after a successful read  — keeps fast sensors (I2C) responsive.
      1.0 s after a failed read      — back-off before next reconnect attempt.
    """
    while True:
        out = {"data": {}, "errors": {}, "health": {}}
        _poll_sensor(name, out, mod)

        data   = out["data"].get(name)
        error  = out["errors"].get(name)
        health = out["health"].get(name, {})
        ok     = health.get("ok", False)
        msg    = health.get("msg", "")

        _write_cache(name, data=data, error=error, ok=ok, msg=msg)

        time.sleep(0.1 if ok else 1.0)


def _start_workers():
    """Spawn one daemon thread per sensor.  Called once from setup()."""
    sensors = [
        ("temperature", _tmp),
        ("gps",         _gps),
        ("imu",         _imu),
        ("air",         _air),
        ("adc",         _soil),
        ("power",       _power),
        ("mega",        _mega),
    ]
    for name, mod in sensors:
        t = threading.Thread(
            target=_sensor_worker,
            args=(name, mod),
            name=f"sensor-{name}",
            daemon=True,
        )
        t.start()
        _log(f"{name}: worker thread started")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def set_run_enabled(value: bool):
    global run_enabled
    run_enabled = bool(value)
    _log(f"RUN set to {run_enabled}")


def setup(
    # TMP102 (I2C)
    # config.xml → <i2c><device name="TMP102"><address>
    tmp_address: int   = 0x48,
    tmp_bus: int       = 1,

    # GPS (serial NMEA)
    # config.xml → <serial><gps>
    gps_port: str      = "/dev/ttyUSB0",
    gps_baud: int      = 9600,

    # MH-Z19C CO2 (UART)
    # config.xml → <serial><air>
    air_port: str      = "/dev/ttyAMA0",
    air_baud: int      = 9600,

    # PZEM-017 power meter (RS485 Modbus)
    # config.xml → <serial><power>
    # NOTE: verify power_de_pin does not conflict with other GPIO uses.
    power_port: str    = "/dev/ttyAMA10",
    power_baud: int    = 9600,
    power_de_pin: int  = 17,
    power_modbus: int  = 1,

    # ADS1115 soil moisture (I2C)
    # config.xml → <i2c><device name="ADS1115"> and <calibration><soil_moisture>
    # Address 0x49: ADDR pin wired to VCC to avoid conflict with TMP102 (0x48).
    adc_address: int   = 0x49,
    adc_ch_moist: int  = 1,
    adc_dry_ref: int   = 800,
    adc_wet_ref: int   = 300,

    # Arduino Mega tool controller (I2C slave)
    # config.xml → <i2c><device name="Mega">
    mega_address: int  = 0x08,
    mega_bus: int      = 1,
):
    """
    Initialize all physical sensors from config values, then start per-sensor
    worker threads.  Call once at startup.

    Every parameter matches a value in config.xml or a sensor driver default.
    Sensors that fail setup are marked offline; their worker threads retry
    automatically on every loop iteration.
    """
    global _sensor_cfg

    _sensor_cfg = {
        "temperature": dict(address=tmp_address, bus=tmp_bus),
        "gps":         dict(port=gps_port, baudrate=gps_baud),
        "air":         dict(port=air_port, baudrate=air_baud),
        "power":       dict(port=power_port, baudrate=power_baud,
                            de_re_pin=power_de_pin, modbus_address=power_modbus),
        "adc":         dict(address=adc_address, channel_moisture=adc_ch_moist,
                            dry_ref=adc_dry_ref, wet_ref=adc_wet_ref),
        "imu":         {},  # imu.setup() takes no parameters
        "mega":        dict(address=mega_address, bus=mega_bus),
    }

    def _init(name, mod):
        if mod is None:
            _log(f"{name}: import failed — {_import_errors.get(name, 'unknown')}")
            return
        try:
            mod.setup(**_sensor_cfg.get(name, {}))
            _sensor_up[name] = True
            _log(f"{name}: setup OK")
        except Exception as e:
            _sensor_up[name] = False
            _log(f"{name}: setup failed — {e}")

    _init("temperature", _tmp)
    _init("gps",         _gps)
    _init("imu",         _imu)
    _init("air",         _air)
    _init("adc",         _soil)
    _init("power",       _power)
    _init("mega",        _mega)

    _log("real_stack: all sensors initialized")

    # Start background worker threads — one per sensor.
    # From this point on, _cache is updated continuously by each thread.
    _start_workers()


def read_all() -> dict:
    """
    Assemble a snapshot from the per-sensor cache and return it instantly.

    This call never blocks on hardware — all reads happen in background
    worker threads.  The snapshot always contains all top-level keys
    required by the UI (ts, run_enabled, data, errors, health, status_log).
    """
    # Snapshot the cache atomically
    with _cache_lock:
        cached = {name: dict(entry) for name, entry in _cache.items()}

    out = {
        "ts":          time.time(),
        "run_enabled": run_enabled,
        "data":        {},
        "errors":      {},
        "health":      {},
        "status_log":  list(_status_log),
    }

    for name in _SENSOR_NAMES:
        entry = cached[name]
        if entry["data"] is not None:
            out["data"][name] = entry["data"]
        if entry["error"] is not None:
            out["errors"][name] = entry["error"]
        out["health"][name] = {"ok": entry["ok"], "msg": entry["msg"]}

    # ── Mega tool controller — extract tools from cached data ─────────────
    mega_tools = (out["data"].get("mega") or {}).get("tools", {})

    # ── pH sensor: hardware TBD ───────────────────────────────────────────
    # When a pH driver exists with setup()/read()/close() returning:
    #   {"ph_value": float}
    # replace this stub with:
    #   from sensor import ph as _ph   (at top of file)
    #   _poll_sensor("ph", out, _ph)   (in _sensor_worker / _start_workers)
    out["errors"]["ph"] = "pH hardware driver not yet implemented"
    out["health"]["ph"] = {"ok": False, "msg": "pH hardware driver not yet implemented"}

    # ── Tool timers (server-side) ─────────────────────────────────────────
    _update_tool_timers(mega_tools)
    out["data"]["timers"] = {
        "air_s":   round(_get_timer_s("air"),   1),
        "water_s": round(_get_timer_s("water"), 1),
        "soil_s":  round(_get_timer_s("soil"),  1),
    }

    return out