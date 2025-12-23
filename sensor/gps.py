import serial
import pynmea2

ser = serial.Serial('/dev/serial0', baudrate=9600, timeout=1)

while True:
    line = ser.readline().decode('ascii', errors='replace')
    if line.startswith('$GNGGA'):
        msg = pynmea2.parse(line)
        print("Lat:", msg.latitude, "Lon:", msg.longitude)
