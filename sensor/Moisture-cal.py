#CODE for initial readings

import time
import Adafruit_ADS1x15

# Create an ADS1115 ADC object
adc = Adafruit_ADS1x15.ADS1115()

# Set the gain to ±4.096V (adjust if needed)
GAIN = 1

# Main loop to read the analog value from the soil moisture sensor and print the raw ADC value
try:
    while True:
        # Read the raw analog value from channel A3
        raw_value = adc.read_adc(3, gain=GAIN)

        # Print the raw ADC value
        print("Raw Value: {}".format(raw_value))

        # Add a delay between readings (adjust as needed)
        time.sleep(3)

except KeyboardInterrupt:
    print("\nExiting the program.")
