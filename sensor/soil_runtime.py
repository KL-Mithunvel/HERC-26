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
# - Single-ended A3
# - Gain = ±4.096V
# - Single-shot mode
# - 128 SPS
CONFIG_A3 = 0xF283

# ----------------------------
# Calibration file path
# ----------------------------
CAL_FILE = "/home/krishna/Desktop/HERC-26/calibration/calib_data.xml"

# ----------------------------
# SMBus init
# ----------------------------
bus = SMBus(1)  # I2C bus 1

# ----------------------------
# Helper functions
# ----------------------------
def load_calibration():
    """Load dry and wet reference values from XML"""
    if not os.path.exists(CAL_FILE):
        raise FileNotFoundError("Calibration file not found")

    tree = ET.parse(CAL_FILE)
    root = tree.getroot()

    dry = int(root.find("dry").text)
    wet = int(root.find("wet").text)

    return dry, wet

def read_ads1115():
    """Read raw ADC value from ADS1115 channel A3"""
    bus.write_i2c_block_data(
        ADS1115_ADDR,
        CONFIG_REG,
        [(CONFIG_A3 >> 8) & 0xFF, CONFIG_A3 & 0xFF]
    )

    time.sleep(0.01)

    data = bus.read_i2c_block_data(ADS1115_ADDR, CONVERSION_REG, 2)
    raw = (data[0] << 8) | data[1]

    # Signed 16-bit conversion
    if raw > 32767:
        raw -= 65536

    return raw

def remove_outliers(values):
    """Remove abnormal spikes using Median Absolute Deviation"""
    median = statistics.median(values)
    deviations = [abs(x - median) for x in values]
    mad = statistics.median(deviations)

    if mad == 0:
        return values

    threshold = 3 * mad
    return [x for x in values if abs(x - median) <= threshold]

def raw_to_moisture(raw, dry, wet):
    """Convert raw ADC value to moisture percentage"""
    return max(0, min(100, (dry - raw) * 100 / (dry - wet)))

# ----------------------------
# Main function
# ----------------------------
def get_soil_moisture():
    samples = []

    print("Taking 10 readings (1 per second)...")
    for _ in range(10):
        samples.append(read_ads1115())
        time.sleep(1)

    print("[SOIL] Raw samples:", samples)

    cleaned = remove_outliers(samples)
    dry, wet = load_calibration()
    avg_raw = statistics.mean(cleaned)
    moisture_percent = raw_to_moisture(avg_raw, dry, wet)

    print(f"[SOIL] Cleaned samples: {cleaned}")
    print(f"[SOIL] Average raw value: {avg_raw}")
    print(f"[SOIL] Moisture level: {moisture_percent:.1f}%")

    return moisture_percent

# ----------------------------
# Entry point
# ----------------------------
if __name__ == "__main__":
    try:
        moisture = get_soil_moisture()
        print(f"\nFinal Soil Moisture: {moisture:.1f}%")
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print("ERROR:", e)
