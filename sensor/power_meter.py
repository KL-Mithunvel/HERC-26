#!/usr/bin/env python3
import os
import time
from serial import Serial

# GPIO control using sysfs (works on all Pi models)
DE_RE_PIN = 17

def gpio_export(pin):
    if not os.path.exists(f'/sys/class/gpio/gpio{pin}'):
        with open('/sys/class/gpio/export', 'w') as f:
            f.write(str(pin))
        time.sleep(0.1)

def gpio_set_direction(pin, direction):
    with open(f'/sys/class/gpio/gpio{pin}/direction', 'w') as f:
        f.write(direction)

def gpio_write(pin, value):
    with open(f'/sys/class/gpio/gpio{pin}/value', 'w') as f:
        f.write(str(value))

def gpio_cleanup(pin):
    if os.path.exists(f'/sys/class/gpio/gpio{pin}'):
        with open('/sys/class/gpio/unexport', 'w') as f:
            f.write(str(pin))

# Setup GPIO
gpio_export(DE_RE_PIN)
gpio_set_direction(DE_RE_PIN, 'out')
gpio_write(DE_RE_PIN, 0)

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
    
    gpio_write(DE_RE_PIN, 1)  # TX mode
    time.sleep(0.01)
    s.write(request)
    s.flush()
    time.sleep(0.01)
    gpio_write(DE_RE_PIN, 0)  # RX mode
    time.sleep(0.3)
    
    response = s.read(100)
    return len(response) > 0

print("Scanning for PZEM-017...")
print("=" * 40)

try:
    with Serial('/dev/ttyAMA10', 9600, timeout=1) as s:
        for addr in range(1, 248):
            if scan_address(s, addr):
                print(f"âœ“ FOUND DEVICE AT ADDRESS: {addr}")
            if addr % 50 == 0:
                print(f"Checked {addr} addresses...")
            time.sleep(0.05)
finally:
    gpio_cleanup(DE_RE_PIN)

print("Scan complete!")
