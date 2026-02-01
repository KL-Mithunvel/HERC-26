import os
import time
import json
from smbus2 import SMBus

# ----------------------------
# Paths
# ----------------------------
CAL_FILE = "/HERC-26/calibration/calib_data.json"

# ----------------------------
# ADS1115 constants
# ----------------------------
ADS1115_ADDR = 0x48
CONVERSION_REG = 0x00
CONFIG_REG = 0x01

# AIN3 single-ended, ±4.096V, single-shot, 128 SPS
CONFIG_A3 = 0xC3E3

# ----------------------------
# SMBus init
# ----------------------------
bus = SMBus(1)

# ----------------------------
# ADC read
# ----------------------------
def read_ads1115():
    bus.write_i2c_block_data(
        ADS1115_ADDR,
        CONFIG_REG,
        [(CONFIG_A3 >> 8) & 0xFF, CONFIG_A3 & 0xFF]
    )

    # Wait for conversion complete
    while True:
        cfg = bus.read_i2c_block_data(ADS1115_ADDR, CONFIG_REG, 2)
        if cfg[0] & 0x80:
            break
        time.sleep(0.001)

    data = bus.read_i2c_block_data(ADS1115_ADDR, CONVERSION_REG, 2)
    raw = (data[0] << 8) | data[1]

    if raw > 32767:
        raw -= 65536

    return raw

# ----------------------------
# Helpers
# ----------------------------
def read_samples(n=15, delay=0.3):
    values = []

    # Allow sensor to settle
    time.sleep(5)

    # Flush initial readings
    for _ in range(3):
        read_ads1115()
        time.sleep(0.1)

    for _ in range(n):
        values.append(read_ads1115())
        time.sleep(delay)

    return values

def calibrated_average():
    values = read_samples()
    print("[DEBUG] Samples:", values)
    return int(sum(values) / len(values))

# ----------------------------
# JSON handling
# ----------------------------
def load_calibration():
    if not os.path.exists(CAL_FILE):
        return {}
    with open(CAL_FILE, "r") as f:
        return json.load(f)

def save_calibration(data):
    os.makedirs(os.path.dirname(CAL_FILE), exist_ok=True)
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

# ----------------------------
# Standalone UI
# ----------------------------
if __name__ == "__main__":
    print("\nSoil Sensor Calibration")
    print("1. Calibrate DRY")
    print("2. Calibrate WET")
    print("3. Exit")

    choice = input("Select option: ")

    if choice == "1":
        calibrate_dry()
    elif choice == "2":
        calibrate_wet()
    else:
        print("Calibration exited")
