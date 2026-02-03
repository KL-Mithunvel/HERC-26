import time
import smbus

bus = smbus.SMBus(1)
ADDR = 0x48
CONV = 0x00
CFG  = 0x01
CONFIG_A2 = 0xF383  # AIN2, ±4.096V

def read_ads1115():
    bus.write_i2c_block_data(ADDR, CFG, [(CONFIG_A2 >> 8) & 0xFF, CONFIG_A2 & 0xFF])
    time.sleep(0.01)
    data = bus.read_i2c_block_data(ADDR, CONV, 2)
    val = (data[0] << 8) | data[1]
    if val > 32767:
        val -= 65536
    voltage = val * (4.096 / 32768.0)  # convert raw counts to voltage
    return val, voltage

while True:
    raw, voltage = read_ads1115()
    print(f"Raw ADC: {raw}, Voltage: {voltage:.3f} V")
    time.sleep(1)
