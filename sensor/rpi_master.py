import smbus
import struct
import signal
import sys

bus = smbus.SMBus(1)
ADDR = 0x08

CMD_INCREMENT = 0xAA
CMD_RESET = 0xFF

def cleanup(sig=None, frame=None):
    print("\nSent to Mega: 0xFF (RESET)")
    try:
        bus.write_byte(ADDR, CMD_RESET)
    except:
        pass
    bus.close()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)

print("Press ENTER to increment (Ctrl+C to reset and exit)")

while True:
    input()

    print("Sent to Mega: 0xAA")
    bus.write_byte(ADDR, CMD_INCREMENT)

    raw = bus.read_i2c_block_data(ADDR, 0, 4)
    value = struct.unpack('<I', bytes(raw))[0]

    print("Received from Mega:", value)
