import time

def init(address=0x48, bus=1):
    """
    Returns TMP102 object, or None if not found.
    """
    try:
        from sensor.tmp102 import TMP102  # keep your existing import
        dev = TMP102('C', address, bus)
        return dev
    except Exception:
        return None

def read(dev):
    """
    Returns dict, never throws.
    """
    if dev is None:
        return {"ok": False, "msg": "TMP102 sensor not found"}

    try:
        temp_c = float(dev.readTemperature())
        temp_f = (temp_c * 9.0 / 5.0) + 32.0
        return {"ok": True, "temp_c": temp_c, "temp_f": temp_f}
    except Exception:
        return {"ok": False, "msg": "TMP102 read failed"}
    

if __name__ == "__main__":
    dev = init()
    while True:
        print(read(dev))
        time.sleep(1)
