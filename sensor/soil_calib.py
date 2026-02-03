import os
import time
import xml.etree.ElementTree as ET
from smbus import SMBus   # smbus1

# ----------------------------
# Paths
# ----------------------------
CAL_FILE = "/home/krishna/Desktop/HERC-26/calibration/calib_data.xml"

# ----------------------------
# ADS1115 constants
# ----------------------------
ADDR = 0x48
CONV = 0x00
CFG  = 0x01

# EXACT config that works
CONFIG_A3 = 0xF283

# ----------------------------
# SMBus init
# ----------------------------
bus = SMBus(1)

# ----------------------------
# ADC read (MATCHES WORKING CODE)
# ----------------------------
def read_ads1115():
    bus.write_i2c_block_data(
        ADDR,
        CFG,
        [(CONFIG_A3 >> 8) & 0xFF, CONFIG_A3 & 0xFF]
    )

    time.sleep(0.01)

    data = bus.read_i2c_block_data(ADDR, CONV, 2)
    val = (data[0] << 8) | data[1]

    if val > 32767:
        val -= 65536

    return val

# ----------------------------
# Helpers
# ----------------------------
def read_samples(n=15, delay=0.3):
    values = []

    # Sensor settle
    time.sleep(5)

    for _ in range(n):
        values.append(read_ads1115())
        time.sleep(delay)

    return values

def calibrated_average():
    values = read_samples()
    print("[DEBUG] Samples:", values)
    return int(sum(values) / len(values))

# ----------------------------
# XML handling
# ----------------------------
def load_calibration():
    if not os.path.exists(CAL_FILE):
        return {}

    tree = ET.parse(CAL_FILE)
    root = tree.getroot()

    data = {}
    for child in root:
        data[child.tag] = int(child.text)

    return data

def save_calibration(data):
    os.makedirs(os.path.dirname(CAL_FILE), exist_ok=True)

    root = ET.Element("calibration")

    for key, value in data.items():
        elem = ET.SubElement(root, key)
        elem.text = str(value)

    tree = ET.ElementTree(root)
    tree.write(CAL_FILE, encoding="utf-8", xml_declaration=True)

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
