# calibration.py
"""
Rover Calibration (Text Menu)
- Uses klm_menu.py menu system (same style as your Furnace_simulation project)
- For now, actions only print "done" so you can validate menu flow on laptop
- Later: each action will call real calibration modules + edit config.xml
"""

import klm_menu

# ----------------------------
# Placeholder actions (for now)
# ----------------------------

def calibrate_bno055():
    print("[BNO055] Calibration started...")
    # TODO: call rovercore/calibration/bno055_calib.py later
    print("[BNO055] Calibration done ✅")

def calibrate_ph_sensor():
    print("[pH] Calibration started...")
    # TODO: call rovercore/calibration/ph_calib.py later
    print("[pH] Calibration done ✅")


import sys
sys.path.append("/home/krishna/Desktop/HERC-26/sensor")

from soil_calib import calibrate_dry, calibrate_wet, view_calibration
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
            load_calibration()

        elif choice == "q":
            break

        else:
            print("[WARN] Invalid selection")


def calibrate_air_sensor():
    print("[AIR] Calibration started...")
    # TODO: call rovercore/calibration/air_calib.py later
    print("[AIR] Calibration done ✅")

def change_i2c_address():
    print("[CONFIG] Change I2C address flow started...")
    # TODO: edit config.xml here later (safe edit + backup)
    print("[CONFIG] I2C address updated (placeholder) ✅")

def view_current_config():
    print("[CONFIG] Showing current config (placeholder)...")
    # TODO: read + print key fields from config.xml later
    print("[CONFIG] Done ✅")

def save_and_exit():
    # TODO: if you maintain a staged config in memory, write it here
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

        elif cmd == "menu:sensors":
            # handled inside klm_menu (it returns menu:sensors only when using back)
            pass

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
# Menus (same structure as your old project)
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
