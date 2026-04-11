"""
scratch/adc_tester.py — ADS1115 poll-rate stress test.
Tries a sequence of sleep intervals between reads, runs N polls at each,
and reports success/error counts and actual throughput.

Fresh AnalogIn per read.  Bus is re-initialised between intervals if the
previous interval had errors.

Run on Raspberry Pi only:  python scratch/adc_tester.py
"""

import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

ADDRESS  = 0x49
CHANNELS = (0, 1, 2)           # A0 soil, A1 pH, A2 battery
POLLS    = 50                  # reads per interval
INTERVALS = [
    0.200,   # 5 Hz
    0.100,   # 10 Hz
    0.050,   # 20 Hz
    0.020,   # 50 Hz
    0.010,   # 100 Hz
    0.005,   # 200 Hz
    0.002,   # 500 Hz
    0.001,   # 1 kHz
    0.000,   # flat out — no sleep
]


def init_bus():
    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS1115(i2c, address=ADDRESS)
    ads.gain = 1  # +-4.096 V
    return i2c, ads


def read_all_channels(ads):
    """Create fresh AnalogIn objects and read each channel."""
    results = []
    for ch in CHANNELS:
        ain = AnalogIn(ads, ch)
        results.append((ain.value, ain.voltage))
    return results


# ── Setup ─────────────────────────────────────────────────────────────────────
i2c, ads = init_bus()

print(f"ADS1115 @ 0x{ADDRESS:02X}  |  channels {CHANNELS}  |  {POLLS} polls per interval\n")
print(f"{'sleep_s':>8}  {'target_Hz':>10}  {'ok':>4}  {'errors':>6}  {'actual_Hz':>10}  {'notes'}")
print("-" * 70)

# ── Test each interval ────────────────────────────────────────────────────────
prev_had_errors = False

for sleep_s in INTERVALS:
    # Re-init the bus if the previous interval had errors
    if prev_had_errors:
        try:
            i2c.deinit()
        except Exception:
            pass
        time.sleep(0.5)
        i2c, ads = init_bus()

    target_hz = 1.0 / sleep_s if sleep_s > 0 else float("inf")
    ok = 0
    errors = 0
    error_msgs = set()

    t0 = time.monotonic()
    for _ in range(POLLS):
        try:
            read_all_channels(ads)
            ok += 1
        except Exception as e:
            errors += 1
            error_msgs.add(str(e)[:40])

        if sleep_s > 0:
            time.sleep(sleep_s)
    elapsed = time.monotonic() - t0

    actual_hz = ok / elapsed if elapsed > 0 else 0
    notes = "; ".join(error_msgs) if error_msgs else ""
    prev_had_errors = errors > 0

    print(f"{sleep_s:8.3f}  {target_hz:10.1f}  {ok:4d}  {errors:6d}  {actual_hz:10.1f}  {notes}")

# ── Cleanup ───────────────────────────────────────────────────────────────────
try:
    i2c.deinit()
except Exception:
    pass
print("\nDone.")
