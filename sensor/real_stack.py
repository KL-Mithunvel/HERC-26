"""
sensor/real_stack.py — Physical sensor stack for Raspberry Pi deployment.

Drop-in replacement for dev_stack.py.  Identical public API:
    setup(...)
    set_run_enabled(value: bool)
    read_all() -> dict

Auto-reconnect behaviour
────────────────────────
Each sensor has a flag (_sensor_up) and cached setup kwargs (_sensor_cfg).
Every read_all() call, for each sensor:

  • Sensor was UP   → call read()
      - read OK          → return data
      - read fails       → attempt close() + setup() immediately
                               reconnect OK   → call read() once more
                               reconnect fail → mark offline, record error

  • Sensor was DOWN → attempt close() + setup() immediately
      - reconnect OK   → call read()
      - reconnect fail → record offline error

This means every poll cycle is one reconnect attempt for offline sensors.
The loop is never blocked: all exceptions from close()/setup() are caught.

Missing drivers
───────────────
  mega.py  — not yet written.  Stub records a permanent health error.
  ph       — hardware TBD.    Stub records a permanent health error.
Replace each stub with _poll_sensor(...) once the driver exists.
"""

import time

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
}

# Setup kwargs cached at startup — used verbatim on every reconnect attempt.
_sensor_cfg: dict = {}


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
):
    """
    Initialize all physical sensors from config values.  Call once at startup.

    Every parameter matches a value in config.xml or a sensor driver default.
    Sensors that fail setup are marked offline; read_all() retries them
    automatically on every poll cycle.
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

    _log("real_stack: all sensors initialized")


def read_all() -> dict:
    """
    Read all physical sensors and return a snapshot dict identical in schema
    to dev_stack.read_all().

    Auto-reconnect runs inside this call for any sensor that is offline or
    that raises a read error.  The snapshot always contains all top-level keys
    required by the UI (ts, run_enabled, data, errors, health, status_log).
    """
    out = {
        "ts":          time.time(),
        "run_enabled": run_enabled,
        "data":        {},
        "errors":      {},
        "health":      {},
        "status_log":  list(_status_log),
    }

    _poll_sensor("temperature", out, _tmp)
    _poll_sensor("gps",         out, _gps)
    _poll_sensor("imu",         out, _imu)
    _poll_sensor("air",         out, _air)
    _poll_sensor("adc",         out, _soil)
    _poll_sensor("power",       out, _power)

    # ── Mega: driver not yet written ──────────────────────────────────────
    # When mega.py exists with setup()/read()/close() returning:
    #   {"tools": {"air": bool, "water": bool, "soil": bool},
    #    "ibus_pulse": int, "movement": str}
    # replace this stub with:
    #   from sensor import mega as _mega   (at top of file)
    #   _poll_sensor("mega", out, _mega)
    out["errors"]["mega"] = "mega.py not yet implemented"
    _update_health(out, "mega", False, "mega.py not yet implemented")
    mega_tools = {}  # no tool states until driver exists

    # ── pH sensor: hardware TBD ───────────────────────────────────────────
    # When a pH driver exists with setup()/read()/close() returning:
    #   {"ph_value": float}
    # replace this stub with:
    #   from sensor import ph as _ph   (at top of file)
    #   _poll_sensor("ph", out, _ph)
    out["errors"]["ph"] = "pH hardware driver not yet implemented"
    _update_health(out, "ph", False, "pH hardware driver not yet implemented")

    # ── Tool timers (server-side) ─────────────────────────────────────────
    _update_tool_timers(mega_tools)
    out["data"]["timers"] = {
        "air_s":   round(_get_timer_s("air"),   1),
        "water_s": round(_get_timer_s("water"), 1),
        "soil_s":  round(_get_timer_s("soil"),  1),
    }

    return out
