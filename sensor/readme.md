## I2C / SMBus Note (TMP102 and other I2C sensors)

This project uses I2C-based sensors (for example **TMP102**, **BNO055**) when running on the **Raspberry Pi**.

### Important
- The Python **`smbus` / `smbus2`** library is **Linux-only** and **will NOT install on Windows**.
- For this reason, **`smbus` / `smbus2` is intentionally NOT included in `requirements.txt`**.
- During development on Windows (laptop), sensor modules may use placeholders or mock data.

### Raspberry Pi setup (required for real hardware)
When deploying to the Raspberry Pi, install SMBus support manually:

```bash
sudo apt update
sudo apt install -y python3-pip python3-dev i2c-tools
pip install smbus2
```

Verify I2C devices:
```bash
i2cdetect -y 1
```
### Why this approach is used
    
- The project is developed on **Windows** but deployed on a **Raspberry Pi**.
- Python I2C libraries (`smbus` / `smbus2`) are **Linux-specific** and depend on the Linux I2C subsystem.
- Including them in `requirements.txt` would cause **installation failures on Windows**.
- Installing them manually on the Raspberry Pi ensures:
  - Proper kernel-level I2C support
  - Stable and predictable sensor communication
  - No development-time dependency issues on non-Linux systems

> ⚠️ `smbus` / `smbus2` should **only** be installed on the Raspberry Pi.  
> Attempting to install these libraries on Windows will fail by design.

### Development vs Deployment

- **Windows (development)**  
  Sensor modules may return placeholder or mock values. Menu systems, logging, calibration flow, and configuration editing can be fully developed and tested.

- **Raspberry Pi (deployment)**  
  Real sensor access is enabled by manually installing `smbus2` and verifying I2C devices.

This separation keeps the codebase clean, portable, and robust for field operation.
