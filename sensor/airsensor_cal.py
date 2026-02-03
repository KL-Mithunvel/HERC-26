import serial
import time

PORT = "/dev/ttyAMA0"
BAUDRATE = 9600

ser = serial.Serial(
    port=PORT,
    baudrate=BAUDRATE,
    timeout=2
)

time.sleep(2)                 # allow sensor UART to settle
ser.reset_input_buffer()      # clear boot junk

def checksum(packet):
    return (0xFF - (sum(packet[1:8]) % 256) + 1) & 0xFF

def read_co2():
    cmd = bytearray([0xFF, 0x01, 0x86, 0, 0, 0, 0, 0, 0])
    cmd[8] = checksum(cmd)

    ser.reset_input_buffer()      # CRITICAL
    ser.write(cmd)
    time.sleep(0.2)               # MH-Z19C needs this

    resp = ser.read(9)

    if len(resp) != 9:
        return None

    if resp[0] != 0xFF or resp[1] != 0x86:
        return None

    if checksum(resp) != resp[8]:
        return None

    co2 = resp[2] * 256 + resp[3]
    temp = resp[4] - 40

    return co2, temp


print("MH-Z19C calibrated readings started")
print("Press CTRL+C to stop\n")

try:
    while True:
        result = read_co2()
        if result is None:
            print("Read error")
        else:
            co2, temp = result
            print(f"CO2: {co2} ppm | Temp: {temp} °C")

        time.sleep(2)

except KeyboardInterrupt:
    print("\nStopped")
    ser.close()
