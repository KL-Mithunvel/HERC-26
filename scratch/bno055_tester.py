"""
scratch/bno055_tester.py — BNO055 IMU diagnostic tool.
Probes the sensor at multiple levels to find where communication fails.
Run on Raspberry Pi only:  python scratch/bno055_tester.py
"""

import time

ADDRESS = 0x28

# ── 1. Raw smbus: read chip ID register ──────────────────────────────────────
#   BNO055 chip ID register 0x00 should return 0xA0.
#   This is the lowest-level test — no Adafruit libraries involved.
print("=== 1. Raw smbus — chip ID (reg 0x00, expect 0xA0) ===")
try:
    import smbus
    bus = smbus.SMBus(1)
    chip_id = bus.read_byte_data(ADDRESS, 0x00)
    print(f"  chip_id = 0x{chip_id:02X}  {'OK' if chip_id == 0xA0 else 'UNEXPECTED'}")
    bus.close()
except Exception as e:
    print(f"  FAIL: {e}")

# ── 2. Raw smbus: read multiple registers ────────────────────────────────────
#   ACC_ID (0x01) = 0xFB, MAG_ID (0x02) = 0x32, GYR_ID (0x03) = 0x0F
print("\n=== 2. Raw smbus — sub-sensor IDs ===")
try:
    import smbus
    bus = smbus.SMBus(1)
    regs = {
        "ACC_ID (0x01, expect 0xFB)": (0x01, 0xFB),
        "MAG_ID (0x02, expect 0x32)": (0x02, 0x32),
        "GYR_ID (0x03, expect 0x0F)": (0x03, 0x0F),
    }
    for label, (reg, expected) in regs.items():
        val = bus.read_byte_data(ADDRESS, reg)
        status = "OK" if val == expected else "UNEXPECTED"
        print(f"  {label}: 0x{val:02X}  {status}")
    bus.close()
except Exception as e:
    print(f"  FAIL: {e}")

# ── 3. Raw smbus: read operating mode and system status ──────────────────────
#   OPR_MODE (0x3D), SYS_STATUS (0x39), SYS_ERR (0x3A)
print("\n=== 3. Raw smbus — operating mode & status ===")
try:
    import smbus
    bus = smbus.SMBus(1)

    opr_mode   = bus.read_byte_data(ADDRESS, 0x3D)
    sys_status = bus.read_byte_data(ADDRESS, 0x39)
    sys_err    = bus.read_byte_data(ADDRESS, 0x3A)

    modes = {
        0x00: "CONFIG", 0x01: "ACCONLY", 0x02: "MAGONLY", 0x03: "GYROONLY",
        0x04: "ACCMAG", 0x05: "ACCGYRO", 0x06: "MAGGYRO", 0x07: "AMG",
        0x08: "IMU", 0x09: "COMPASS", 0x0A: "M4G", 0x0B: "NDOF_FMC_OFF",
        0x0C: "NDOF",
    }
    err_codes = {
        0: "No error", 1: "Peripheral init error", 2: "System init error",
        3: "Self-test fail", 4: "Reg map value out of range",
        5: "Reg map address out of range", 6: "Reg map write error",
        7: "Low-power mode not available", 8: "Accel power mode not available",
        9: "Fusion config error", 10: "Sensor config error",
    }

    print(f"  OPR_MODE   = 0x{opr_mode:02X}  ({modes.get(opr_mode, 'UNKNOWN')})")
    print(f"  SYS_STATUS = 0x{sys_status:02X}")
    print(f"  SYS_ERR    = 0x{sys_err:02X}  ({err_codes.get(sys_err, 'UNKNOWN')})")
    bus.close()
except Exception as e:
    print(f"  FAIL: {e}")

# ── 4. Raw smbus: try reading accel data ─────────────────────────────────────
#   ACC_DATA_X_LSB starts at 0x08, 6 bytes (X, Y, Z as signed 16-bit LE)
print("\n=== 4. Raw smbus — raw accelerometer (regs 0x08–0x0D) ===")
try:
    import smbus
    import struct
    bus = smbus.SMBus(1)

    # Set NDOF mode (0x0C) to enable fusion — sensor may be stuck in CONFIG
    current_mode = bus.read_byte_data(ADDRESS, 0x3D)
    if current_mode == 0x00:
        print("  Sensor in CONFIG mode — switching to NDOF...")
        bus.write_byte_data(ADDRESS, 0x3D, 0x0C)
        time.sleep(0.7)  # mode switch takes up to 600ms

    raw = bus.read_i2c_block_data(ADDRESS, 0x08, 6)
    x = struct.unpack_from('<h', bytes(raw), 0)[0]
    y = struct.unpack_from('<h', bytes(raw), 2)[0]
    z = struct.unpack_from('<h', bytes(raw), 4)[0]
    # BNO055 accel: 1 LSB = 1 m/s² in default range (±4g, fusion mode)
    print(f"  raw: x={x}  y={y}  z={z}")
    print(f"  m/s²: x={x/100:.2f}  y={y/100:.2f}  z={z/100:.2f}")
    bus.close()
except Exception as e:
    print(f"  FAIL: {e}")

# ── 5. Adafruit library ──────────────────────────────────────────────────────
print("\n=== 5. Adafruit library — full driver ===")
try:
    import board
    import busio as _busio
    import adafruit_bno055

    i2c = _busio.I2C(board.SCL, board.SDA)
    imu = adafruit_bno055.BNO055_I2C(i2c, address=ADDRESS)
    time.sleep(1.0)

    print(f"  acceleration     = {imu.acceleration}")
    print(f"  euler (h, r, p)  = {imu.euler}")
    print(f"  linear_accel     = {imu.linear_acceleration}")
    print(f"  gravity          = {imu.gravity}")
    print(f"  calibration      = {imu.calibration_status}")

    i2c.deinit()
except Exception as e:
    print(f"  FAIL: {e}")

print("\nDone.")
