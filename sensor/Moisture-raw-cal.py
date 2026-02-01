import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

# Create I2C bus using board pins
i2c = busio.I2C(board.SCL, board.SDA)

# Create ADS1115 object
ads = ADS1115(i2c)

# Set gain (±4.096 V)
ads.gain = 1

# Create channel A3
chan = AnalogIn(ads, ADS1115.P3)

try:
    while True:
        print(f"Raw Value: {chan.value}")
        print(f"Voltage: {chan.voltage:.3f} V")
        time.sleep(3)

except KeyboardInterrupt:
    print("\nExiting the program.")
