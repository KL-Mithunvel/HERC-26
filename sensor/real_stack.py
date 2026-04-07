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
  • The web dashboard always refreshes at the full poll rate.
  • Slow sensors (GPS serial reads) only affect their own cache update rate.
  • Sensors that go offline retry on every worker loop iteration (1 s back-off).

Sleep intervals per worker:
  • Read OK   → 0.1 s
  • Read fail → 1.0 s  (back-off before reconnect attempt)

ADS1115 shared hardware
───────────────────────
soil, ph, and battery all share one ADS1115 chip via sensor.ads1115.
Each has its own worker thread and calls ads1115.read_all() independently.
The 200 ms cache in ads1115.py ensures only one I2C burst happens per poll
cycle regardless of how many workers call it concurrently.

Snapshot key mapping
────────────────────
  Internal worker name → snapshot data key
  "temperature"  → data["temperature"]
  "gps"          → data["gps"]
  "imu"          → data["imu"]
  "air"          → data["air"]
  "soil" + "ph"  → data["adc"]   (combined by read_all)
  "battery"      → data["battery"]
  "mega"         → data["mega"]
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
    _import_errors["soil"] = str(_e)

try:
    from sensor import ph as _ph
except ImportError as _e:
    _ph = None
    _import_errors["ph"] = str(_e)

try:
    from sensor import power as _power
except ImportError as _e:
    _power = None
    _import_errors["battery"] = str(_e)

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

# Internal worker names — note: soil + ph are combined into "adc" in read_all().
_WORKER_NAMES = ("temperature", "gps", "imu", "air", "soil", "ph", "battery", "mega")

_sensor_up: dict = {name: False for name in _WORKER_NAMES}

# Setup kwargs cached at startup — used verbatim on every reconnect attempt.
_sensor_cfg: dict = {}

# Per-sensor result cache — written by worker threads, read by read_all().
# Each entry: {"data": dict|None, "error": str|None, "ok": bool, "msg": str, "reconnecting": bool}
_cache: dict = {
    name: {"data": None, "error": "starting...", "ok": False, "msg": "starting...", "reconnecting": False}
    for name in _WORKER_NAMES
}
_cache_lock = threading.Lock()

# _sensor_up thread safety note:
# Each sensor worker only reads/writes its own _sensor_up[name] key.
# read_all() never reads _sensor_up — it only reads _cache (under _cache_lock).
# CPython GIL makes individual dict item writes atomic, so no lock is needed here.


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log(msg: str):
    _status_log.append({"ts": time.time(), "msg": msg})
    if len(_status_log) > STATUS_MAX:
        del _status_log[0]


def _update_health(out: dict, name: str, ok: bool, msg: str):
    """Write health entry; log only when state actually changes."""
    out["health"][name] = {"ok": bool(ok), "msg": msg or ""}
    prev = _last_health.get(name)
    curr = (bool(ok), msg or "")
    if prev != curr:
        _last_health[name] = curr
        label = f"{name}: {'OK' if ok else 'FAIL'}"
        _log(f"{label} — {msg}" if msg else label)


def _update_tool_timers(tools: dict):
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
        pass
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
    Writes into out["data"][name] on success, out["errors"][name] on failure.
    """
    if mod is None:
        err = _import_errors.get(name, "module unavailable")
        out["errors"][name] = err
        _update_health(out, name, False, err)
        return

    if not _sensor_up[name]:
        if _try_reconnect(name, mod):
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

    try:
        out["data"][name] = mod.read()
        _update_health(out, name, True, "")
    except Exception as e:
        _sensor_up[name] = False
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


def _write_cache(name: str, data, error, ok: bool, msg: str, reconnecting: bool = False):
    with _cache_lock:
        _cache[name] = {"data": data, "error": error, "ok": ok, "msg": msg, "reconnecting": reconnecting}


def _sensor_worker(name: str, mod):
    """
    Daemon thread for one sensor.
    Reads hardware, writes result to _cache, sleeps, repeat.
    0.1 s on success, 1.0 s on failure.
    Outer try/except ensures the thread never dies on an unexpected error.
    """
    while True:
        try:
            # Signal reconnecting before the attempt so the UI sees it immediately
            if not _sensor_up[name] and mod is not None:
                _write_cache(name, data=None, error="reconnecting...",
                             ok=False, msg="reconnecting...", reconnecting=True)

            out = {"data": {}, "errors": {}, "health": {}}
            _poll_sensor(name, out, mod)

            data   = out["data"].get(name)
            error  = out["errors"].get(name)
            health = out["health"].get(name, {})

            _write_cache(name, data=data, error=error,
                         ok=health.get("ok", False), msg=health.get("msg", ""),
                         reconnecting=False)

            time.sleep(0.1 if health.get("ok") else 1.0)
        except Exception as _e:
            _log(f"{name}: worker error — {_e}")
            time.sleep(1.0)


def _start_workers():
    """Spawn one daemon thread per sensor.  Called once from setup()."""
    sensors = [
        ("temperature", _tmp),
        ("gps",         _gps),
        ("imu",         _imu),
        ("air",         _air),
        ("soil",        _soil),
        ("ph",          _ph),
        ("battery",     _power),
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
    # TMP102 temperature (I2C)
    tmp_address: int    = 0x48,
    tmp_bus: int        = 1,

    # GPS (serial NMEA)
    gps_port: str       = "/dev/ttyUSB0",
    gps_baud: int       = 9600,

    # MH-Z19C CO2 (UART)
    air_port: str       = "/dev/ttyAMA0",
    air_baud: int       = 9600,

    # ADS1115 (I2C 0x49) — shared by soil, pH, and battery
    # All three channels use GAIN_1 (±4.096 V).
    adc_address: int    = 0x49,
    soil_channel: int   = 0,        # A0 — capacitive soil moisture sensor
    soil_dry_ref: int   = 800,      # raw ADC counts for dry soil (config.xml)
    soil_wet_ref: int   = 300,      # raw ADC counts for wet soil (config.xml)
    ph_channel: int     = 1,        # A1 — 0–2 V pH sensor (pH = V × 7.0)
    batt_channel: int   = 2,        # A2 — voltage divider (R1=30k, R2=7.5k)

    # Arduino Mega (USB Serial via ttyACM0)
    mega_port: str      = "/dev/ttyACM0",
    mega_baud: int      = 115200,
):
    """
    Initialise all physical sensors, then start per-sensor worker threads.
    Call once at startup from main.py.  All parameters come from config.xml.

    Sensors that fail setup are marked offline; their workers retry automatically.
    """
    global _sensor_cfg

    _sensor_cfg = {
        "temperature": dict(address=tmp_address, bus=tmp_bus),
        "gps":         dict(port=gps_port, baudrate=gps_baud),
        "air":         dict(port=air_port, baudrate=air_baud),
        "soil":        dict(address=adc_address, channel=soil_channel,
                            dry_ref=soil_dry_ref, wet_ref=soil_wet_ref),
        "ph":          dict(address=adc_address, channel=ph_channel),
        "battery":     dict(address=adc_address, channel=batt_channel),
        "imu":         {},
        "mega":        dict(port=mega_port, baudrate=mega_baud),
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
    _init("soil",        _soil)
    _init("ph",          _ph)
    _init("battery",     _power)
    _init("mega",        _mega)

    _log("real_stack: all sensors initialized — starting worker threads")
    _start_workers()


def read_all() -> dict:
    """
    Assemble a snapshot from the per-sensor cache and return it instantly.
    Never blocks on hardware — all reads happen in background worker threads.

    soil + ph worker results are combined into data["adc"].
    battery worker result maps directly to data["battery"].
    """
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

    # ── Direct 1-to-1 mappings ────────────────────────────────────────────────
    for name in ("temperature", "gps", "imu", "air", "mega"):
        entry = cached[name]
        if entry["data"] is not None:
            out["data"][name] = entry["data"]
        if entry["error"] is not None:
            out["errors"][name] = entry["error"]
        out["health"][name] = {"ok": entry["ok"], "msg": entry["msg"],
                               "reconnecting": entry.get("reconnecting", False)}

    # ── Battery → data["battery"] ─────────────────────────────────────────────
    batt = cached["battery"]
    if batt["data"] is not None:
        out["data"]["battery"] = batt["data"]
    if batt["error"] is not None:
        out["errors"]["battery"] = batt["error"]
    out["health"]["battery"] = {"ok": batt["ok"], "msg": batt["msg"],
                                "reconnecting": batt.get("reconnecting", False)}

    # ── Soil + pH → data["adc"] (combined) ───────────────────────────────────
    soil = cached["soil"]
    ph   = cached["ph"]

    adc_raw = {}
    adc_sv  = {}
    adc_out = {}

    if soil["data"] is not None:
        adc_raw["moisture"] = soil["data"]["raw"]["moisture"]
        adc_sv["moisture"]  = soil["data"]["sensor_voltage"]["moisture"]
        adc_out["moisture_value"] = soil["data"]["moisture_value"]

    if ph["data"] is not None:
        adc_raw["ph"] = ph["data"]["raw"]["ph"]
        adc_sv["ph"]  = ph["data"]["sensor_voltage"]["ph"]
        adc_out["ph_value"] = ph["data"]["ph_value"]

    if adc_out:
        adc_out["raw"]            = adc_raw
        adc_out["sensor_voltage"] = adc_sv
        out["data"]["adc"] = adc_out

    # Report individual errors so the UI can show which sub-sensor failed
    if soil["error"]:
        out["errors"]["soil"] = soil["error"]
    if ph["error"]:
        out["errors"]["ph"] = ph["error"]

    # Soil gets its own health key so the Soil Moisture card LED is independent
    out["health"]["soil"] = {"ok": soil["ok"], "msg": soil["msg"],
                             "reconnecting": soil.get("reconnecting", False)}

    # Combined adc health: both soil and pH must be OK
    adc_msgs = [m for m in (soil["msg"], ph["msg"]) if m]
    out["health"]["adc"] = {
        "ok":          soil["ok"] and ph["ok"],
        "msg":         "; ".join(adc_msgs) if adc_msgs else "",
        "reconnecting": soil.get("reconnecting", False) or ph.get("reconnecting", False),
    }

    # pH gets its own health key so the pH card LED works independently
    out["health"]["ph"] = {"ok": ph["ok"], "msg": ph["msg"],
                           "reconnecting": ph.get("reconnecting", False)}

    # ── Mega tool timers (server-side) ────────────────────────────────────────
    mega_data  = out["data"].get("mega") or {}
    mega_tools = mega_data.get("tools", {})
    _update_tool_timers(mega_tools)

    # Zero integrated velocity when the rover is confirmed stopped with a valid
    # RC signal. This prevents IMU drift accumulating during stationary periods.
    if (mega_data.get("movement") == "STOP"
            and mega_data.get("ibus_pulse")
            and not mega_data.get("failsafe")
            and _imu is not None
            and _sensor_up.get("imu")):
        try:
            _imu.reset_velocity()
        except Exception:
            pass
    out["data"]["timers"] = {
        "air_s":   round(_get_timer_s("air"),   1),
        "water_s": round(_get_timer_s("water"), 1),
        "soil_s":  round(_get_timer_s("soil"),  1),
    }

    return out