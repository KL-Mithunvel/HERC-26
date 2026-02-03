import time
import smbus

bus = smbus.SMBus(1)
ADDR = 0x48
CONV = 0x00
CFG  = 0x01
CONFIG_A3 = 0xF283  # AIN3, ±4.096V

# Example calibration (replace with your own)
v_ph4 = 3.00   # measured voltage in pH 4 buffer
v_ph7 = 2.50   # measured voltage in pH 7 buffer
slope = (7.0 - 4.0) / (v_ph7 - v_ph4)
offset = 4.0 - slope * v_ph4

def read_ads1115():
    bus.write_i2c_block_data(ADDR, CFG, [(CONFIG_A3 >> 8) & 0xFF, CONFIG_A3 & 0xFF])
    time.sleep(0.01)
    data = bus.read_i2c_block_data(ADDR, CONV, 2)
    val = (data[0] << 8) | data[1]
    if val > 32767:
        val -= 65536
    voltage = val * (4.096 / 32768.0)
    return val, voltage

while True:
    raw, voltage = read_ads1115()
    ph_value = slope * voltage + offset
    print(f"Raw: {raw}, Voltage: {voltage:.3f} V, pH: {ph_value:.2f}")
    time.sleep(1)
