from tmp102 import TMP102
import time
class tmpSensorSetupError(Exception):
    pass

class tmpSensorReadError(Exception):
    pass

TMP_connected = False

def setup():
    try:
        # Initialize TMP Object
        global TMP
        TMP = TMP102('C', 0x48, 1)
        # Actually, lets make the temperatures Farenheit
        TMP.setUnits('F')
    except :
        raise tmpSensorSetupError("tmp sensor not reading up")
    global TMP_connected
    TMP_connected = True

def read():
    try:
        tmp = TMP.readTemperature()
    except :
        raise tmpSensorReadError("tmp sensor not reading up")
    if not TMP_connected:
        raise tmpSensorReadError("tmp sensor not reading up")

    return tmp

def close():
    global TMP_connected
    TMP_connected = False


if "__main__" == __name__:
    setup()
    while True:
        print(read())
        time.sleep(1)
    close()

