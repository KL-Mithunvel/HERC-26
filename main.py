import time
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
