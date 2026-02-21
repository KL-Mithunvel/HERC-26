#!/usr/bin/env python3
from gpiozero import OutputDevice
from time import sleep
from serial import Serial

de_re = OutputDevice(17)

def calculate_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def scan_address(s, addr):
    request = bytearray([addr, 0x04, 0x00, 0x00, 0x00, 0x06])
    crc = calculate_crc(request)
    request.append(crc & 0xFF)
    request.append((crc >> 8) & 0xFF)
    
    s.reset_input_buffer()
    s.reset_output_buffer()
    
    de_re.on()
    sleep(0.01)
    s.write(request)
    s.flush()
    sleep(0.01)
    de_re.off()
    sleep(0.3)
    
    response = s.read(100)
    return len(response) > 0

de_re.off()

print("Scanning for PZEM-017...")
print("=" * 40)

with Serial('/dev/ttyAMA10', 9600, timeout=1) as s:
    for addr in range(1, 248):
        if scan_address(s, addr):
            print(f"âœ“ FOUND DEVICE AT ADDRESS: {addr}")
        if addr % 50 == 0:
            print(f"Checked {addr} addresses...")
        sleep(0.05)

print("Scan complete!")
