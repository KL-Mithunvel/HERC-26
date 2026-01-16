import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn

# Create the I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Create the ADS object
ads = ADS1115(i2c)

# Create single-ended input on channel 0
chan = AnalogIn(ads, 0)  # 0 = A0, 1 = A1, etc.

# Optional: calibration values for your soil sensor
dry_value = 20000   # Example: sensor reading when soil is dry
wet_value = 10000   # Example: sensor reading when soil is wet

while True:
    analog_value = chan.value        # Raw ADC value (0–65535)
    voltage = chan.voltage           # Voltage reading
    
    # Map to soil moisture percentage
    soil_moisture = max(0, min(100, (dry_value - analog_value) * 100 / (dry_value - wet_value)))

    print(f"ADC: {analog_value}, Voltage: {voltage:.3f} V, Moisture: {soil_moisture:.1f}%")
    time.sleep(1)

