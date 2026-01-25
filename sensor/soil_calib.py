import os
import time
import json
import statistics
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAL_FILE = os.path.join(BASE_DIR, "soil_calibration.json")

# ----------------------------
# ADC setup
# ----------------------------
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)
ads.gain = 1
chan = AnalogIn(ads, 3)

# ----------------------------
# Helpers
# ----------------------------

def read_samples(n=10, delay=0.5):
    values = []
    for _ in range(n):
        values.append(chan.value)
        time.sleep(delay)
    return values

def remove_odd_one_out(values):
    """
    Removes the value farthest from the median
    """
    median = statistics.median(values)
    distances = [(abs(v - median), v) for v in values]
    distances.sort(reverse=True)
    values.remove(distances[0][1])
    return values

def calibrated_average():
    values = read_samples()
    filtered = remove_odd_one_out(values)
    return int(sum(filtered) / len(filtered))

def load_calibration():
    try:
        with open(CAL_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_calibration(data):
    with open(CAL_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ----------------------------
# Public API
# ----------------------------

def calibrate_dry():
    print("\n[SOIL] Place sensor in DRY soil")
    input("Press ENTER to start...")
    value = calibrated_average()
    data = load_calibration()
    data["dry"] = value
    save_calibration(data)
    print(f"[SOIL] Dry calibration saved: {value}")

def calibrate_wet():
    print("\n[SOIL] Place sensor in WET soil")
    input("Press ENTER to start...")
    value = calibrated_average()
    data = load_calibration()
    data["wet"] = value
    save_calibration(data)
    print(f"[SOIL] Wet calibration saved: {value}")

def view_calibration():
    data = load_calibration()
    print("\n[SOIL] Current calibration values:")
    print(f"  Dry : {data.get('dry', 'Not calibrated')}")
    print(f"  Wet : {data.get('wet', 'Not calibrated')}")
