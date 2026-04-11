"""
scratch/adc_tester.py — ADS1115 diagnostic tool.
Figures out WHY reads fail after a sleep.

Tests:
  1. Single read after increasing idle gaps (find the threshold)
  2. Burst read, long pause, burst read (power droop test)
  3. Bus re-init after pause (does a fresh bus fix it?)
  4. Per-poll log showing exactly which polls fail

Run on Raspberry Pi only:  python scratch/adc_tester.py
"""

import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

ADDRESS  = 0x49
CHANNELS = (0, 1, 2)


def init_bus():
    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS1115(i2c, address=ADDRESS)
    ads.gain = 1
    return i2c, ads


def read_once(ads):
    """Read all channels. Returns (True, data) or (False, error_str)."""
    try:
        data = []
        for ch in CHANNELS:
            ain = AnalogIn(ads, ch)
            data.append((ain.value, ain.voltage))
        return True, data
    except Exception as e:
        return False, str(e)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 1: Find the idle gap threshold
#   One read, sleep N ms, one read.  Which gap length breaks it?
# ═════════════════════════════════════════════════════════════════════════════
print("=== TEST 1: Idle gap threshold ===")
print("  Read once, sleep N ms, read again. Find where it breaks.\n")
print(f"  {'gap_ms':>8}  {'result'}")
print("  " + "-" * 40)

GAPS_MS = [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]

i2c, ads = init_bus()
for gap_ms in GAPS_MS:
    # Warm up with a successful read
    ok1, _ = read_once(ads)
    if not ok1:
        # Bus dead — reinit
        try: i2c.deinit()
        except: pass
        time.sleep(0.1)
        i2c, ads = init_bus()
        read_once(ads)  # warm up again

    # The actual test: sleep, then read
    time.sleep(gap_ms / 1000.0)
    ok2, result = read_once(ads)
    status = "OK" if ok2 else f"FAIL: {result[:50]}"
    print(f"  {gap_ms:8d}  {status}")

try: i2c.deinit()
except: pass


# ═════════════════════════════════════════════════════════════════════════════
# TEST 2: Power droop test
#   10 fast reads (no sleep), 3 second pause, 10 fast reads.
#   If the second burst fails, power is drooping during idle.
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 2: Power droop (burst → 3s pause → burst) ===\n")

i2c, ads = init_bus()

print("  Burst 1 (10 fast reads):")
for i in range(10):
    ok, result = read_once(ads)
    tag = "OK" if ok else f"FAIL: {result[:40]}"
    print(f"    [{i+1:2d}] {tag}")

print(f"\n  Sleeping 3 seconds...")
time.sleep(3.0)

print(f"\n  Burst 2 (10 reads after 3s idle):")
for i in range(10):
    ok, result = read_once(ads)
    tag = "OK" if ok else f"FAIL: {result[:40]}"
    print(f"    [{i+1:2d}] {tag}")

try: i2c.deinit()
except: pass


# ═════════════════════════════════════════════════════════════════════════════
# TEST 3: Does re-init fix it?
#   Read, sleep 1s (should fail based on prior results), try read,
#   then re-init bus and try again.
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 3: Re-init recovery ===")
print("  Read → sleep 1s → read (expect fail) → re-init bus → read\n")

i2c, ads = init_bus()
ok, _ = read_once(ads)
print(f"  Before sleep:  {'OK' if ok else 'FAIL'}")

time.sleep(1.0)
ok, result = read_once(ads)
print(f"  After 1s sleep: {'OK' if ok else f'FAIL: {result[:50]}'}")

print("  Re-initialising bus...")
try: i2c.deinit()
except: pass
time.sleep(0.1)
i2c, ads = init_bus()
ok, result = read_once(ads)
print(f"  After re-init:  {'OK' if ok else f'FAIL: {result[:50]}'}")

try: i2c.deinit()
except: pass
time.sleep(0.5)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 4: 20 polls at 200ms with per-poll logging
#   Re-inits bus after each failure to keep going.
# ═════════════════════════════════════════════════════════════════════════════
print("\n=== TEST 4: Per-poll log (20 polls, 200ms interval) ===\n")

i2c, ads = init_bus()
for i in range(20):
    ok, result = read_once(ads)
    if ok:
        vals = "  ".join(f"A{ch}: {result[j][0]:6d} {result[j][1]:.4f}V"
                         for j, ch in enumerate(CHANNELS))
        print(f"  [{i+1:2d}] OK   {vals}")
    else:
        print(f"  [{i+1:2d}] FAIL {result[:60]}")
        # Re-init so next poll has a chance
        try: i2c.deinit()
        except: pass
        time.sleep(0.1)
        i2c, ads = init_bus()
    time.sleep(0.200)

try: i2c.deinit()
except: pass

print("\nDone.")
