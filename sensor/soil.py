import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# Initialize I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Create the ADS1115 ADC object
ads = ADS.ADS1115(i2c)

# Set gain (1 is suitable for 0–4.096 V range)
ads.gain = 1

# Create analog input channel on A0 (P0)
chan = AnalogIn(ads, ADS.P0)

# Continuously print voltage values
while True:
    print(f"MQ-135 Voltage: {chan.voltage} V")
    time.sleep(1)
