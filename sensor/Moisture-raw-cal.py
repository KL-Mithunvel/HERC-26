import time
import smbus2

# I2C configuration
I2C_BUS = 1
ADS1115_ADDRESS = 0x48

# ADS1115 Registers
CONVERSION_REG = 0x00
CONFIG_REG = 0x01

# Create I2C bus
bus = smbus2.SMBus(I2C_BUS)

def read_adc(channel):
    """
    Read single-ended ADC value from ADS1115
    Channel: 0,1,2,3
    """
    if channel not in [0, 1, 2, 3]:
        raise ValueError("Channel must be 0-3")

    # Config register value
    # Single-shot, AINx to GND, Gain ±4.096V, 128 SPS
    config = (
        0x8000 |                 # Start single conversion
        (0x4000 >> channel) |    # Channel selection
        0x0200 |                 # Gain = ±4.096V
        0x0100 |                 # Single-shot mode
        0x0080                   # 128 samples per second
    )

    # Write config to ADS1115
    bus.write_i2c_block_data(
        ADS1115_ADDRESS,
        CONFIG_REG,
        [(config >> 8) & 0xFF, config & 0xFF]
    )

    # Wait for conversion
    time.sleep(0.01)

    # Read conversion result
    data = bus.read_i2c_block_data(
        ADS1115_ADDRESS,
        CONVERSION_REG,
        2
    )

    # Convert to signed integer
    value = (data[0] << 8) | data[1]
    if value > 32767:
        value -= 65536

    return value

try:
    while True:
        raw_value = read_adc(3)  # Read AIN3
        print(f"Raw Value: {raw_value}")
        time.sleep(3)

except KeyboardInterrupt:
    print("\nExiting the program.")
