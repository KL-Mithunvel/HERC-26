import time
import smbus

bus = smbus.SMBus(1)
ADDR = 0x48

CONV = 0x00
CFG  = 0x01

CONFIG_A3 = 0xF283  # Fixed, correct config for AIN3

while True:
    bus.write_i2c_block_data(
        ADDR, CFG,
        [(CONFIG_A3 >> 8) & 0xFF, CONFIG_A3 & 0xFF]
    )

    time.sleep(0.01)

    data = bus.read_i2c_block_data(ADDR, CONV, 2)
    val = (data[0] << 8) | data[1]
    if val > 32767:
        val -= 65536

    print(val)
    time.sleep(1)
