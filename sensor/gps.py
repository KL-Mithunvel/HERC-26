import time
import serial
import pynmea2


class GPS:
    def __init__(self, port="/dev/serial0", baudrate=9600, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def open(self):
        if self.ser is None or not self.ser.is_open:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def read(self, max_lines=40):
        """
        Reads up to `max_lines` lines and returns first valid RMC dict.
        Does NOT reopen the port each time.
        """
        if self.ser is None or not self.ser.is_open:
            return {"ok": False, "error": "GPS serial not open"}

        for _ in range(max_lines):
            line = self.ser.readline().decode("ascii", errors="replace").strip()
            if not line:
                continue

            if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                try:
                    msg = pynmea2.parse(line)
                except pynmea2.ParseError:
                    continue

                status = getattr(msg, "status", None)  # 'A' valid, 'V' void
                if status and status != "A":
                    return {"ok": False, "error": "RMC status not valid", "raw": line}

                timestamp = getattr(msg, "timestamp", None)
                datestamp = getattr(msg, "datestamp", None)

                return {
                    "ok": True,
                    "utc_time": str(timestamp) if timestamp else None,
                    "utc_date": str(datestamp) if datestamp else None,
                    "lat": getattr(msg, "latitude", None),
                    "lon": getattr(msg, "longitude", None),
                    "speed_knots": getattr(msg, "spd_over_grnd", None),
                    "course_deg": getattr(msg, "true_course", None),
                    "raw": line,
                }

        return {"ok": False, "error": f"No valid RMC found in {max_lines} lines"}


def _run():
    gps = GPS()
    gps.open()
    try:
        while True:
            data = gps.read()
            if data.get("ok"):
                print(
                    f"GPS UTC {data['utc_date']} {data['utc_time']} | "
                    f"Lat={data['lat']} Lon={data['lon']} | "
                    f"Spd(kn)={data['speed_knots']} Course(deg)={data['course_deg']}"
                )
            else:
                print("GPS ERR:", data.get("error"))
            time.sleep(0.5)
    finally:
        gps.close()


if __name__ == "__main__":
    _run()
