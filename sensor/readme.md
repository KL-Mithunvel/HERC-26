## Sensor Library Notes

### I2C / SMBus sensors (TMP102, BNO055, ADS1115)

These sensors communicate over I2C and use the `smbus` library on Linux.

- `smbus` / `smbus2` is **Linux-only** — it will NOT install on Windows.
- It is **not included in `requirements.txt`** for this reason.
- On Windows, use `main_sim.py` with `sensor/dev_stack.py` (simulated data).

**Raspberry Pi setup:**

```bash
sudo apt update
sudo apt install -y python3-smbus i2c-tools
i2cdetect -y 1   # verify I2C devices are detected
```

---

### Arduino Mega (rover co-processor) — USB Serial

The Mega communicates with the Pi via **USB cable** on `/dev/ttyACM0`.
This uses `pyserial`, not smbus.

- `pyserial` must be installed on the Pi:
  ```bash
  sudo apt install python3-serial
  # or: pip install pyserial
  ```
- The driver is `sensor/mega.py`. It reads 9-byte framed packets at 115200 baud.
- Verify the port: `ls /dev/ttyACM*` (Mega appears as `ttyACM0` when USB-connected).
- See `scratch/README_serial_test.md` for the full wiring and test procedure.

**No level shifter required.** USB is electrically isolated; just plug in the cable.

---

### Development vs Deployment

| Mode | Platform | How to run |
|---|---|---|
| Development | Windows / any laptop | `python main_sim.py` — simulated data via `sensor/dev_stack.py` |
| Deployment | Raspberry Pi | `python main.py` — real hardware via `sensor/real_stack.py` |

Sensor hardware modules (`smbus`, `board`, `busio`, `pynmea2`, `serial`) are all
guarded with `try/except ImportError` so the system always starts on Windows
without crashing — missing hardware shows as OFFLINE in the dashboard.
