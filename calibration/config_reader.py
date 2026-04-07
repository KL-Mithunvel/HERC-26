"""
calibration/config_reader.py — Parse config.xml into a plain dict.

Usage:
    from calibration.config_reader import load_config
    cfg = load_config()
    print(cfg["gps_port"], cfg["sqlite_path"])

All keys and their defaults:
    sensor_read_hz      float   — poll rate (default 1.0)
    mega_port           str     — Mega USB Serial port (default /dev/ttyACM0)
    mega_baud           int     — Mega baud rate (default 115200)
    gps_port            str
    gps_baud            int
    air_port            str     — MH-Z19C UART
    air_baud            int
    WATER_SENSOR_GPIO   int     — from <gpio> block
    SOIL_SENSOR_GPIO    int
    AIR_SENSOR_GPIO     int
    LCD_RESET_GPIO      int
    i2c_bus             int
    i2c_bno055_address  int     — hex, e.g. 0x28
    i2c_tmp102_address  int     — hex, e.g. 0x48
    i2c_ads1115_address int     — hex, e.g. 0x49 (shared: soil A0, pH A1, battery A2)
    soil_dry_ref        int
    soil_wet_ref        int
    tmp102_offset_c     float
    sqlite_path         str
"""

import xml.etree.ElementTree as ET
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).parent / "config.xml"


def load_config(path=None) -> dict:
    """
    Parse config.xml and return a flat dict of all config values.
    Missing fields are filled in with safe defaults so callers never
    have to handle KeyError.
    """
    path = Path(path) if path else _DEFAULT_CONFIG
    tree = ET.parse(str(path))
    root = tree.getroot()

    def _text(xpath: str, default: str = "") -> str:
        node = root.find(xpath)
        return (node.text or "").strip() if node is not None else default

    def _int(xpath: str, default: int = 0) -> int:
        try:
            return int(_text(xpath, str(default)))
        except ValueError:
            return default

    def _float(xpath: str, default: float = 0.0) -> float:
        try:
            return float(_text(xpath, str(default)))
        except ValueError:
            return default

    cfg: dict = {}

    # ── Rates ────────────────────────────────────────────────────────────────
    cfg["sensor_read_hz"] = _float("rates/sensor_read_hz", 1.0)

    # ── Serial ports ─────────────────────────────────────────────────────────
    cfg["mega_port"] = _text("serial/mega/port", "/dev/ttyACM0")
    cfg["mega_baud"] = _int("serial/mega/baud",  115200)
    cfg["gps_port"]  = _text("serial/gps/port",  "/dev/ttyUSB0")
    cfg["gps_baud"]  = _int("serial/gps/baud",   9600)
    cfg["air_port"]  = _text("serial/air/port",  "/dev/ttyAMA0")
    cfg["air_baud"]  = _int("serial/air/baud",   9600)

    # ── GPIO ─────────────────────────────────────────────────────────────────
    for pin in root.findall("gpio/pin"):
        name = (pin.get("name") or "").strip()
        try:
            cfg[name] = int(pin.text or 0)
        except ValueError:
            cfg[name] = 0

    cfg.setdefault("WATER_SENSOR_GPIO", 17)
    cfg.setdefault("SOIL_SENSOR_GPIO",  27)
    cfg.setdefault("AIR_SENSOR_GPIO",   22)
    cfg.setdefault("LCD_RESET_GPIO",    23)

    # ── I2C ──────────────────────────────────────────────────────────────────
    cfg["i2c_bus"] = _int("i2c/bus", 1)
    for device in root.findall("i2c/device"):
        name = (device.get("name") or "").strip().lower()
        addr_text = (device.findtext("address") or "0x00").strip()
        try:
            cfg[f"i2c_{name}_address"] = int(addr_text, 16)
        except ValueError:
            cfg[f"i2c_{name}_address"] = 0

    cfg.setdefault("i2c_bno055_address",  0x28)
    cfg.setdefault("i2c_tmp102_address",  0x48)
    cfg.setdefault("i2c_ads1115_address", 0x49)

    # ── Calibration ──────────────────────────────────────────────────────────
    cfg["soil_dry_ref"]    = _int("calibration/soil_moisture/dry_ref",  800)
    cfg["soil_wet_ref"]    = _int("calibration/soil_moisture/wet_ref",  300)
    cfg["tmp102_offset_c"] = _float("calibration/tmp102/temp_offset_c", 0.0)

    # ── Database ─────────────────────────────────────────────────────────────
    cfg["sqlite_path"] = _text("database/sqlite_path", "data/rover_logs.sqlite")

    return cfg