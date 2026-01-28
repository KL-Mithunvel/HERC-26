""""import time
from sensors.tmp import TMP
from sensors.base import SensorInitError, SensorReadError

tmp = TMP(address=0x48, bus=1, unit="F")  # or "C"

try:
    tmp.connect()
except SensorInitError as e:
    print(e)
    raise SystemExit(1)

while True:
    try:
        print(tmp.read())
    except SensorReadError as e:
        print(e)
    time.sleep(1)
""""

# main.py
# setup sensors once -> loop: snapshot = read_all() -> display (print for now)

import time
from sensors import fake_sensor
from services.read_all import read_all

POLL_S = 1.0

def main():
    # Register sensors (add more later)
    sensors = {
        "fake1": fake_sensor,
        "fake2": fake_sensor,   # you can also create another file for a second fake sensor
    }

    # Setup once
    for name, mod in sensors.items():
        try:
            mod.setup()
        except Exception as e:
            print(f"{name} setup error: {e}")

    # Main loop
    while True:
        snapshot = read_all(sensors)

        # "display op" (print for now; later Flask/UI will show this)
        print("ts:", snapshot["ts"])
        print("data:", snapshot["data"])
        print("errors:", snapshot["errors"])
        print("-" * 40)

        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
