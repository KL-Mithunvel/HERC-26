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
"""
'''
# main.py
# setup sensors once -> loop: snapshot = read_all() -> display (print for now)

import time
from sensor import fake_sensor
import read_all

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
        snapshot = read_all.read_all(sensors)

        # "display op" (print for now; later Flask/UI will show this)
        print("ts:", snapshot["ts"])
        print("data:", snapshot["data"])
        print("errors:", snapshot["errors"])
        print("-" * 40)

        time.sleep(POLL_S)

if __name__ == "__main__":
    main()
'''
import time
import threading

from sensor import dev_stack
from services import logger_dev
from web.app import app, set_latest
from services.validation import compute_validation



POLL_S = 0.5  # polling + logging rate


def sensor_loop():
    dev_stack.setup(fail_prob=0.01)
    logger_dev.log_event("Program started")

    while True:
        snap = dev_stack.read_all()
        tools = (snap.get("data", {}).get("mega", {}) or {}).get("tools", {})
        timers = (snap.get("data", {}) or {}).get("timers", {})
        snap["validation"] = compute_validation(tools, timers)

        # Always log
        logger_dev.log_snapshot(snap)

        # Update UI snapshot
        set_latest(snap)

        time.sleep(POLL_S)


def main():
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()

    # Laptop dev:
    #   host="127.0.0.1" -> only local machine
    # Pi / Wi-Fi access:
    #   host="0.0.0.0" -> reachable from tablet on same network
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
