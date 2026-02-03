import time
import statistics
import os
import xml.etree.ElementTree as ET
from smbus import SMBus   # smbus1

# ----------------------------
# ADS1115 constants
# ----------------------------
ADS1115_ADDR = 0x48
CONVERSION_REG = 0x00
CONFIG_REG = 0x01

# Config bits:
# - Single-ended A2
# - Gain = ±4.096V
# - Single-shot mode
# - 128 SPS
CONFIG_A2 = 0xF383

# ----------------------------
# Calibration file path
# ----------------------------
CAL_FILE = "/home/krishna/Desktop/HERC-26/calibration/calib_data.xml"

# ----------------------------
# SMBus init
# ----------------------------
bus = SMBus(1)

# ----------------------------
# Helper functions
# ----------------------------
def load_calibration():
    """Load pH4 and pH7 reference raw values from XML"""
    if not os.path.exists(CAL_FILE):
        raise FileNotFoundError("Calibration file not found")

    tree = ET.parse(CAL_FILE)
    root = tree.getroot()

    ph4 = int(root.find("ph4").text)
    ph7 = int(root.find("ph7").text)

    return ph4, ph7

def read_ads1115():
    """Read raw ADC value from ADS1115 channel A2"""
    bus.write_i2c_block_data(
        ADS1115_ADDR,
        CONFIG_REG,
        [(CONFIG_A2 >> 8) & 0xFF, CONFIG_A2 & 0xFF]
    )
    time.sleep(0.01)
    data = bus.read_i2c_block_data(ADS1115_ADDR, CONVERSION_REG, 2)
    raw = (data[0] << 8) | data[1]

    # Signed 16-bit conversion
    if raw > 32767:
        raw -= 65536

    return raw

def raw_to_voltage(raw):
    """Convert raw ADC value to voltage (±4.096V range)"""
    return raw * (4.096 / 32768.0)

# ----------------------------
# Main function
# ----------------------------
def get_ph_value():
    # Load calibration points
    ph4_raw, ph7_raw = load_calibration()
    v_ph4 = raw_to_voltage(ph4_raw)
    v_ph7 = raw_to_voltage(ph7_raw)

    # Compute slope and offset
    slope = (7.0 - 4.0) / (v_ph7 - v_ph4)
    offset = 4.0 - slope * v_ph4

    print("[INFO] Place probe in solution and wait for stabilization...")
    time.sleep(180)  # 3 minutes

    samples = []
    print("Taking 10 readings (1 per second)...")
    for _ in range(10):
        raw = read_ads1115()
        voltage = raw_to_voltage(raw)
        samples.append(voltage)
        time.sleep(1)

    avg_voltage = statistics.mean(samples)
    ph_value = slope * avg_voltage + offset

    print(f"[pH] Voltage samples: {samples}")
    print(f"[pH] Average voltage: {avg_voltage:.3f} V")
    print(f"[pH] Calculated pH: {ph_value:.2f}")

    return ph_value

# ----------------------------
# Entry point
# ----------------------------
if __name__ == "__main__":
    try:
        ph = get_ph_value()
        print(f"\nFinal pH Value: {ph:.2f}")
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print("ERROR:", e)
