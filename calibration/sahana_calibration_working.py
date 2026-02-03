# calibration.py
"""
Rover Calibration (Text Menu)
- Uses klm_menu.py menu system
- XML-based calibration storage
"""
import os
import sys
import xml.etree.ElementTree as ET
import klm_menu

# ----------------------------
# Placeholder actions
# ----------------------------

def calibrate_bno055():
    print("[BNO055] Calibration started...")
    print("[BNO055] Calibration done ✅")

def calibrate_ph_sensor():
    print("[pH] Calibration started...")
    print("[pH] Calibration done ✅")

# ----------------------------
# Soil calibration imports
# ----------------------------
sys.path.append("/home/krishna/Desktop/HERC-26/sensor")
from soil_calib import calibrate_dry, calibrate_wet

cal_file_path = "/home/krishna/Desktop/HERC-26/calibration/calib_data.xml"

# ----------------------------
# Soil moisture calibration menu
# ----------------------------
def calibrate_soil_moisture():
    while True:
        print("\n--- Soil Moisture Calibration ---")
        print("1. Calibrate DRY value")
        print("2. Calibrate WET value")
        print("3. View calibration values")
        print("q. Back")

        choice = input("Select option: ").strip().lower()

        if choice == "1":
            calibrate_dry()

        elif choice == "2":
            calibrate_wet()

        elif choice == "3":
            if not os.path.exists(cal_file_path):
                print("Dry value: Not calibrated")
                print("Wet value: Not calibrated")
                continue

            try:
                tree = ET.parse(cal_file_path)
                root = tree.getroot()

                dry_elem = root.find("dry")
                wet_elem = root.find("wet")

                dry = dry_elem.text if dry_elem is not None else "Not calibrated"
                wet = wet_elem.text if wet_elem is not None else "Not calibrated"

                print(f"Dry value: {dry}")
                print(f"Wet value: {wet}")

            except ET.ParseError:
                print(f"[ERROR] Failed to parse XML at {cal_file_path}")
                print("Dry value: Not calibrated")
                print("Wet value: Not calibrated")

        elif choice == "q":
            break

        else:
            print("[WARN] Invalid selection")

# ----------------------------
# Other placeholders
# ----------------------------
def calibrate_air_sensor():
    print("[AIR] Calibration started...")
    print("[AIR] Calibration done ✅")

def change_i2c_address():
    print("[CONFIG] Change I2C address flow started...")
    print("[CONFIG] I2C address updated (placeholder) ✅")

def view_current_config():
    print("[CONFIG] Showing current config (placeholder)...")
    print("[CONFIG] Done ✅")

def save_and_exit():
    print("[SYSTEM] Save & Exit ✅")

# ----------------------------
# Menu loop
# ----------------------------
def show_menu(menu_system, start_menu="cal_main"):
    ex = False
    menu_name = start_menu

    while not ex:
        cmd, menu_name = klm_menu.present_menu(menu_name, menu_system)

        if cmd == "exit":
            ex = True

        elif cmd == "cal_bno":
            calibrate_bno055()

        elif cmd == "cal_ph":
            calibrate_ph_sensor()

        elif cmd == "cal_soil":
            calibrate_soil_moisture()

        elif cmd == "cal_air":
            calibrate_air_sensor()

        elif cmd == "cfg_view":
            view_current_config()

        elif cmd == "cfg_i2c":
            change_i2c_address()

        elif cmd == "save_exit":
            save_and_exit()
            ex = True

        else:
            print(f"[WARN] Unknown command: {cmd}")

# ----------------------------
# Menus
# ----------------------------
cal_main_menu = {
    "menu": "Rover Calibration Main Menu",
    "name": "cal_main",
    "options": [
        ["menu:sensors", "Sensor Calibration", "s"],
        ["menu:config",  "Config / I2C Settings", "c"],
        ["save_exit",    "Save & Exit", "x"],
        ["exit",         "Exit (No Save)", "q"],
    ],
    "back_option": False,
    "back_to": None
}

sensor_menu = {
    "menu": "Sensor Calibration Menu",
    "name": "sensors",
    "options": [
        ["cal_bno",  "Calibrate BNO055", "i"],
        ["cal_ph",   "Calibrate pH Sensor", "p"],
        ["cal_soil", "Calibrate Soil Moisture", "m"],
        ["cal_air",  "Calibrate Air Sensor", "a"],
    ],
    "back_option": True,
    "back_to": "cal_main"
}

config_menu = {
    "menu": "Config / I2C Menu",
    "name": "config",
    "options": [
        ["cfg_view", "View Current Config (placeholder)", "v"],
        ["cfg_i2c",  "Change I2C Address (placeholder)", "i"],
    ],
    "back_option": True,
    "back_to": "cal_main"
}

menu_system = {
    "cal_main": cal_main_menu,
    "sensors":  sensor_menu,
    "config":   config_menu,
}

if __name__ == "__main__":
    show_menu(menu_system, start_menu="cal_main")
