import time
import smbus2
from adafruit_ads1x15.ads1115 import ADS1115

# Create I2C bus (bus 1 is standard on most SBCs)
i2c_bus = smbus2.SMBus(1)

# Create ADS1115 object (default address 0x48)
ads = ADS1115(i2c_bus)

# Set gain to ±4.096 V
ads.gain = 1

try:
    while True:
        # Read raw ADC value from channel A3
        raw_value = ads.read_adc(3)

        print(f"Raw Value: {raw_value}")

        time.sleep(3)

except KeyboardInterrupt:
    print("\nExiting the program.")
