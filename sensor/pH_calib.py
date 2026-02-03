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
CONFIG_A2 = 0xF383  # AIN2, ±4.096V

bus = SMBus(1)

# ----------------------------
# ADC read
# ----------------------------

def read_ads1115():
    bus.write_i2c_block_data(
        ADDR, CFG, [(CONFIG_A2 >> 8) & 0xFF, CONFIG_A2 & 0xFF]
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
    time.sleep(5)  # sensor settle
    for _ in range(n):
        values.append(read_ads1115())
        time.sleep(delay)
    return values

def calibrated_average():
    print("[INFO] Waiting 3 minutes for probe to stabilize...")
    time.sleep(180)  # 3 minutes = 180 seconds

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
def calibrate_ph4():
    print("\n[pH] Place sensor in pH 4 buffer solution")
    input("Press ENTER to start...")
    value = calibrated_average()
    data = load_calibration()
    data["ph4"] = value
    save_calibration(data)
    print(f"[pH] Calibration saved: pH4 raw = {value}")

def calibrate_ph7():
    print("\n[pH] Place sensor in pH 7 buffer solution")
    input("Press ENTER to start...")
    value = calibrated_average()
    data = load_calibration()
    data["ph7"] = value
    save_calibration(data)
    print(f"[pH] Calibration saved: pH7 raw = {value}")

# ----------------------------
# Standalone UI
# ----------------------------
if __name__ == "__main__":
    print("\nPH Sensor Calibration")
    print("1. Calibrate pH 4")
    print("2. Calibrate pH 7")
    print("3. Exit")

    choice = input("Select option: ")

    if choice == "1":
        calibrate_ph4()
    elif choice == "2":
        calibrate_ph7()
    else:
        print("Calibration exited")
