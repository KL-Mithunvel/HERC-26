import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

# Create I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Create ADS1115 ADC object
ads = ADS1115(i2c)

# Set gain to ±4.096 V (equivalent to GAIN = 1)
ads.gain = 1

# Create analog input on channel A3
chan = AnalogIn(ads, 3)

try:
    while True:
        # Read raw ADC value
        raw_value = chan.value

        # Print raw ADC value
        print(f"Raw Value: {raw_value}")

        # Delay between readings
        time.sleep(3)

except KeyboardInterrupt:
    print("\nExiting the program.")
