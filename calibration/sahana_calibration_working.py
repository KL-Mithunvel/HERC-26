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
# Soil calibration imports
# ----------------------------
sys.path.append("/home/krishna/Desktop/HERC-26/sensor")
from soil_calib import calibrate_dry, calibrate_wet
from ph_calib import calibrate_ph4, calibrate_ph7   # <-- new module for pH sensor

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
            view_calibration_values(["dry", "wet"])
        elif choice == "q":
            break
        else:
            print("[WARN] Invalid selection")

# ----------------------------
# pH sensor calibration menu
# ----------------------------
def calibrate_ph_sensor():
    while True:
        print("\n--- pH Sensor Calibration ---")
        print("1. Calibrate pH 4 buffer")
        print("2. Calibrate pH 7 buffer")
        print("3. View calibration values")
        print("q. Back")

        choice = input("Select option: ").strip().lower()

        if choice == "1":
            calibrate_ph4()
        elif choice == "2":
            calibrate_ph7()
        elif choice == "3":
            view_calibration_values(["ph4", "ph7"])
        elif choice == "q":
            break
        else:
            print("[WARN] Invalid selection")

# ----------------------------
# Shared XML viewer
# ----------------------------
def view_calibration_values(tags):
    if not os.path.exists(cal_file_path):
        for tag in tags:
            print(f"{tag} value: Not calibrated")
        return

    try:
        tree = ET.parse(cal_file_path)
        root = tree.getroot()
        for tag in tags:
            elem = root.find(tag)
            val = elem.text if elem is not None else "Not calibrated"
            print(f"{tag} value: {val}")
    except ET.ParseError:
        print(f"[ERROR] Failed to parse XML at {cal_file_path}")
        for tag in tags:
            print(f"{tag} value: Not calibrated")

# ----------------------------
# Other placeholders
# ----------------------------
def calibrate_bno055():
    print("[BNO055] Calibration started...")
    print("[BNO055] Calibration done ✅")

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

       
