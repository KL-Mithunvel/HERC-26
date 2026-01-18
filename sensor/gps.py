import serial
import pynmea2

# Open the serial port (use /dev/serial0 for Raspberry Pi)
ser = serial.Serial('/dev/serial0', 9600, timeout=1)

while True:
    try:
        newdata = ser.readline().decode('ascii', errors='replace')
        if newdata.startswith('$GPRMC') or newdata.startswith('$GNRMC'):
            newmsg = pynmea2.parse(newdata)
            
            # UTC time from the GPS fix
            timestamp = newmsg.timestamp  # datetime.time object
            
            # Latitude and Longitude
            lat = newmsg.latitude
            lng = newmsg.longitude
            
            gps_info = f"Time(UTC)={timestamp}, Latitude={lat}, Longitude={lng}"
            print(gps_info)
    except pynmea2.ParseError:
        continue
