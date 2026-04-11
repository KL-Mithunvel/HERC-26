"""
scratch/i2c_tester.py — Minimal I2C sensor test.
Reads each I2C sensor once, prints the result, and exits.
Run on Raspberry Pi only:  python scratch/i2c_tester.py
"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sensor"))

# ── 1. TMP102  (I2C 0x48) ────────────────────────────────────────────────────
#   Uses sensor/tmp102.py — same module as production code (sensor/tmp.py).
print("=== TMP102 (0x48) ===")
try:
    from tmp102 import TMP102
    t = TMP102('C', 0x48, 1)
    temp_c = t.readTemperature()
    print(f"  temp_c = {temp_c:.2f}")
except Exception as e:
    print(f"  FAIL: {e}")

# ── 2. BNO055 IMU  (I2C 0x28) ────────────────────────────────────────────────
print("\n=== BNO055 IMU (0x28) ===")
try:
    import board, busio, adafruit_bno055
    i2c = busio.I2C(board.SCL, board.SDA)
    imu = adafruit_bno055.BNO055_I2C(i2c, address=0x28)
    time.sleep(0.5)  # let sensor stabilise

    accel = imu.acceleration
    euler = imu.euler
    lin   = imu.linear_acceleration
    print(f"  acceleration      = {accel}")
    print(f"  euler (h, r, p)   = {euler}")
    print(f"  linear_accel      = {lin}")

    i2c.deinit()
except Exception as e:
    print(f"  FAIL: {e}")

# ── 3. ADS1115  (I2C 0x49) — soil A0, pH A1, battery A2 ─────────────────────
print("\n=== ADS1115 (0x49) ===")
try:
    import board as _board, busio as _busio
    from adafruit_ads1x15.ads1115 import ADS1115
    from adafruit_ads1x15.analog_in import AnalogIn

    i2c2 = _busio.I2C(_board.SCL, _board.SDA)
    ads  = ADS1115(i2c2, address=0x49)
    ads.gain = 1  # +-4.096 V

    for ch in (0, 1, 2):
        ain = AnalogIn(ads, ch)
        print(f"  A{ch}: raw={ain.value:6d}  {ain.voltage:.4f} V")

    i2c2.deinit()
except Exception as e:
    print(f"  FAIL: {e}")

print("\nDone.")