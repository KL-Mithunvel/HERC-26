#Runs to take 10 values (refers to wet and dry val from calib) and then gives final moisture %
import time
import statistics
import json
import os

import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

# ----------------------------
# Calibration file path
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAL_FILE = os.path.join(BASE_DIR, "soil_calibration.json")

# ----------------------------
# Hardware setup
# ----------------------------
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)
ads.gain = 1
chan = AnalogIn(ads, 3)  # ADC channel A3 reads data

# ----------------------------
# Helper functions
# ----------------------------
#Loads the ref wet and dry val from .json file
def load_calibration():
    """Load dry and wet reference values from JSON"""
    with open(CAL_FILE, "r") as f:
        calib = json.load(f)
    return calib["dry"], calib["wet"]

#func removes outliers
def remove_outliers(values):
    """Remove abnormal spikes using Median Absolute Deviation"""
    median = statistics.median(values)
    deviations = [abs(x - median) for x in values]
    mad = statistics.median(deviations)
    if mad == 0:
        return values
    threshold = 3 * mad
    return [x for x in values if abs(x - median) <= threshold]

#func converts ADC --> Moisture %
def raw_to_moisture(raw, dry, wet):
    """Convert raw ADC value to moisture percentage"""
    return max(0, min(100, (dry - raw) * 100 / (dry - wet)))

# ----------------------------
# Main function - Takes 10 readings, cleans data, and gives final moisture 
# ----------------------------
def get_soil_moisture():
    samples = []

    print("Taking 10 readings (1 per second)...")
    for _ in range(10):
        samples.append(chan.value)
        time.sleep(1)

    print("[SOIL] Raw samples:", samples)

    cleaned = remove_outliers(samples)
    dry, wet = load_calibration()
    avg_raw = statistics.mean(cleaned)
    moisture_percent = raw_to_moisture(avg_raw, dry, wet)

    print(f"[SOIL] Cleaned samples: {cleaned}")
    print(f"[SOIL] Average raw value: {avg_raw}")
    print(f"[SOIL] Moisture level: {moisture_percent:.1f}%")

    return (moisture_percent)
