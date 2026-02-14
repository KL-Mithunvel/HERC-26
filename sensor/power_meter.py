#!/usr/bin/env python3
import serial
import time
import RPi.GPIO as GPIO

# GPIO pin for RS485 direction control
DE_RE_PIN = 17  # GPIO 17 (Pin 11)

# PZEM-017 Modbus slave address
SLAVE_ADDR = 0x01

# Setup GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(DE_RE_PIN, GPIO.OUT)
GPIO.output(DE_RE_PIN, GPIO.LOW)  # Receive mode by default

# Setup serial port
ser = serial.Serial(
    port='/dev/serial0',  # or '/dev/ttyS0' depending on your RPi model
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1
)

def calculate_crc(data):
    """Calculate Modbus CRC16"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def read_pzem():
    """Read PZEM-017 data using Modbus RTU"""
    # Modbus RTU frame: [Slave_Addr][Function][Start_Hi][Start_Lo][Len_Hi][Len_Lo][CRC_Lo][CRC_Hi]
    # Read Input Registers (0x04), starting at 0x0000, read 6 registers
    request = bytearray([SLAVE_ADDR, 0x04, 0x00, 0x00, 0x00, 0x06])
    crc = calculate_crc(request)
    request.append(crc & 0xFF)
    request.append((crc >> 8) & 0xFF)
    
    # Clear buffers
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    # Set to transmit mode
    GPIO.output(DE_RE_PIN, GPIO.HIGH)
    time.sleep(0.001)  # Small delay for mode switch
    
    # Send request
    ser.write(request)
    ser.flush()
    
    # Set to receive mode
    time.sleep(0.001)
    GPIO.output(DE_RE_PIN, GPIO.LOW)
    time.sleep(0.1)  # Wait for response
    
    # Read response
    response = ser.read(17)  # Expected: 1+1+1+12+2 = 17 bytes
    
    if len(response) == 17:
        # Verify CRC
        received_crc = response[-2] | (response[-1] << 8)
        calculated_crc = calculate_crc(response[:-2])
        
        if received_crc == calculated_crc:
            # Parse data (starting at byte 3)
            voltage = int.from_bytes(response[3:5], byteorder='big') / 100.0
            current = int.from_bytes(response[5:7], byteorder='big') / 100.0
            power_low = int.from_bytes(response[7:9], byteorder='big')
            power_high = int.from_bytes(response[9:11], byteorder='big')
            power = ((power_high << 16) | power_low) / 10.0
            energy_low = int.from_bytes(response[11:13], byteorder='big')
            energy_high = int.from_bytes(response[13:15], byteorder='big')
            energy = (energy_high << 16) | energy_low
            
            return {
                'voltage': voltage,
                'current': current,
                'power': power,
                'energy': energy,
                'success': True
            }
        else:
            return {'success': False, 'error': 'CRC mismatch'}
    else:
        return {'success': False, 'error': f'Invalid response length: {len(response)}'}

def main():
    print("PZEM-017 POWER METER STARTED")
    print("=" * 40)
    
    try:
        while True:
            result = read_pzem()
            
            if result['success']:
                print(f"Voltage : {result['voltage']:.2f} V")
                print(f"Current : {result['current']:.2f} A")
                print(f"Power   : {result['power']:.1f} W")
                print(f"Energy  : {result['energy']:.0f} Wh")
                print("-" * 40)
            else:
                print(f"Modbus error: {result['error']}")
            
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        print("\nProgram stopped by user")
    finally:
        GPIO.cleanup()
        ser.close()

if __name__ == "__main__":
    main()
