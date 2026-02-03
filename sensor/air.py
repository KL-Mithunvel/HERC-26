#!/usr/bin/env python3

import serial
import time
import sys

# ============================================================================
# SENSOR MODULE
# ============================================================================

class MHZ19CSetupError(Exception):
    pass

class MHZ19CReadError(Exception):
    pass

# Global variables
_ser = None
_connected = False
_port = '/dev/ttyUSB0'
_baudrate = 9600

# Command bytes
_CMD_READ_CO2 = [0xFF, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79]
_CMD_CALIBRATE_ZERO = [0xFF, 0x01, 0x87, 0x00, 0x00, 0x00, 0x00, 0x00, 0x78]
_CMD_AUTO_CALIBRATION_ON = [0xFF, 0x01, 0x79, 0xA0, 0x00, 0x00, 0x00, 0x00, 0xE6]
_CMD_AUTO_CALIBRATION_OFF = [0xFF, 0x01, 0x79, 0x00, 0x00, 0x00, 0x00, 0x00, 0x86]


def setup(port='/dev/ttyUSB0', baudrate=9600):
    """
    Initialize the MH-Z19C sensor connection.
    
    Args:
        port: Serial port (e.g., '/dev/ttyUSB0' for Linux, 'COM3' for Windows)
        baudrate: Communication speed (default 9600 for MH-Z19C)
    
    Raises:
        MHZ19CSetupError: If sensor connection fails
    """
    global _ser, _connected, _port, _baudrate
    
    _port = port
    _baudrate = baudrate
    
    try:
        _ser = serial.Serial(port, baudrate=baudrate, timeout=2)
        time.sleep(0.5)  # Wait for serial connection to stabilize
        _connected = True
        
        # Test connection with a read
        _ser.write(bytearray(_CMD_READ_CO2))
        time.sleep(0.1)
        response = _ser.read(9)
        
        if len(response) != 9:
            raise MHZ19CSetupError(f"Sensor not responding correctly on {port}")
            
    except serial.SerialException as e:
        _connected = False
        raise MHZ19CSetupError(f"Failed to connect to sensor on {port}: {str(e)}")
    except Exception as e:
        _connected = False
        raise MHZ19CSetupError(f"Sensor initialization failed: {str(e)}")


def read():
    """
    Read CO2 concentration from sensor.
    
    Returns:
        int: CO2 concentration in ppm
    
    Raises:
        MHZ19CReadError: If sensor not initialized or read fails
    """
    global _ser, _connected
    
    if not _connected or _ser is None:
        raise MHZ19CReadError("Sensor not initialized. Call setup() first.")
    
    try:
        # Send read command
        _ser.write(bytearray(_CMD_READ_CO2))
        time.sleep(0.1)
        
        # Read response
        response = _ser.read(9)
        
        if len(response) != 9:
            raise MHZ19CReadError("Invalid response length from sensor")
        
        # Verify checksum
        checksum = 0xFF - (sum(response[1:8]) % 256) + 1
        if checksum != response[8]:
            raise MHZ19CReadError("Checksum verification failed")
        
        # Calculate CO2 value
        co2 = response[2] * 256 + response[3]
        
        # Sanity check (MH-Z19C range is 0-5000 ppm)
        if co2 < 0 or co2 > 10000:
            raise MHZ19CReadError(f"CO2 value out of range: {co2}")
        
        return co2
        
    except serial.SerialException as e:
        raise MHZ19CReadError(f"Serial communication error: {str(e)}")
    except MHZ19CReadError:
        raise
    except Exception as e:
        raise MHZ19CReadError(f"Unexpected error during read: {str(e)}")


def close():
    """
    Close the sensor connection and release resources.
    """
    global _ser, _connected
    
    if _ser is not None and _ser.is_open:
        _ser.close()
    
    _ser = None
    _connected = False


def calibrate_zero():
    """
    Calibrate zero point to 400ppm.
    WARNING: Sensor must be in fresh air (400ppm) for 20+ minutes before calibration!
    
    Raises:
        MHZ19CReadError: If sensor not initialized or calibration fails
    """
    global _ser, _connected
    
    if not _connected or _ser is None:
        raise MHZ19CReadError("Sensor not initialized. Call setup() first.")
    
    try:
        _ser.write(bytearray(_CMD_CALIBRATE_ZERO))
        time.sleep(0.1)
    except Exception as e:
        raise MHZ19CReadError(f"Zero point calibration failed: {str(e)}")


def calibrate_span(span_value=2000):
    """
    Calibrate span point to a known CO2 concentration.
    
    Args:
        span_value: Known CO2 concentration in ppm (default 2000)
    
    Raises:
        MHZ19CReadError: If sensor not initialized or calibration fails
    """
    global _ser, _connected
    
    if not _connected or _ser is None:
        raise MHZ19CReadError("Sensor not initialized. Call setup() first.")
    
    try:
        high_byte = (span_value >> 8) & 0xFF
        low_byte = span_value & 0xFF
        command = [0xFF, 0x01, 0x88, high_byte, low_byte, 0x00, 0x00, 0x00]
        checksum = 0xFF - (sum(command[1:8]) % 256) + 1
        command.append(checksum)
        
        _ser.write(bytearray(command))
        time.sleep(0.1)
    except Exception as e:
        raise MHZ19CReadError(f"Span point calibration failed: {str(e)}")


def set_auto_calibration(enabled=True):
    """
    Enable or disable automatic baseline calibration (ABC).
    
    Args:
        enabled: True to enable ABC, False to disable
    
    Raises:
        MHZ19CReadError: If sensor not initialized or setting fails
    """
    global _ser, _connected
    
    if not _connected or _ser is None:
        raise MHZ19CReadError("Sensor not initialized. Call setup() first.")
    
    try:
        command = _CMD_AUTO_CALIBRATION_ON if enabled else _CMD_AUTO_CALIBRATION_OFF
        _ser.write(bytearray(command))
        time.sleep(0.1)
    except Exception as e:
        raise MHZ19CReadError(f"Auto-calibration setting failed: {str(e)}")


def read_average(num_readings=10, delay=2):
    """
    Read multiple CO2 values and return statistics.
    
    Args:
        num_readings: Number of readings to average (default 10)
        delay: Delay between readings in seconds (default 2)
    
    Returns:
        dict: Dictionary with 'average', 'min', 'max', 'count', and 'readings' keys
    
    Raises:
        MHZ19CReadError: If sensor not initialized or reads fail
    """
    if not _connected:
        raise MHZ19CReadError("Sensor not initialized. Call setup() first.")
    
    readings = []
    
    for i in range(num_readings):
        try:
            co2 = read()
            readings.append(co2)
            print(f"  Reading {i+1}/{num_readings}: {co2} ppm")
        except MHZ19CReadError as e:
            # Continue collecting other readings even if one fails
            print(f"  Warning: Reading {i+1} failed: {str(e)}")
        
        if i < num_readings - 1:
            time.sleep(delay)
    
    if not readings:
        raise MHZ19CReadError("All readings failed")
    
    return {
        'average': sum(readings) / len(readings),
        'min': min(readings),
        'max': max(readings),
        'count': len(readings),
        'readings': readings
    }


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def main():
    print("=" * 60)
    print("MH-Z19C CO2 Sensor - Complete Example")
    print("=" * 60)
    
    # Setup sensor
    try:
        print("\nInitializing sensor...")
        setup(port='/dev/ttyUSB0', baudrate=9600)
        print("✓ Sensor initialized successfully")
    except MHZ19CSetupError as e:
        print(f"✗ Setup failed: {e}")
        print("\nTroubleshooting tips:")
        print("  - Check wiring connections")
        print("  - Verify serial port (try 'ls /dev/tty*')")
        print("  - Check permissions: sudo chmod 666 /dev/ttyUSB0")
        sys.exit(1)
    
    try:
        # Single reading
        print("\n" + "-" * 60)
        print("Reading single CO2 value...")
        co2 = read()
        print(f"✓ CO2 Concentration: {co2} ppm")
        
        # Interpret the value
        if co2 < 400:
            status = "Below normal outdoor level"
        elif co2 < 1000:
            status = "Good air quality ✓"
        elif co2 < 2000:
            status = "Acceptable but may cause drowsiness"
        else:
            status = "Poor air quality - ventilation needed!"
        
        print(f"  Status: {status}")
        
        # Multiple readings with average
        print("\n" + "-" * 60)
        print("Taking 10 readings with 2-second intervals...")
        
        result = read_average(num_readings=10, delay=2)
        
        print("\n✓ Statistics:")
        print(f"  Average CO2: {result['average']:.2f} ppm")
        print(f"  Minimum: {result['min']} ppm")
        print(f"  Maximum: {result['max']} ppm")
        print(f"  Range: {result['max'] - result['min']} ppm")
        print(f"  Valid readings: {result['count']}/10")
        
        # Optional: Calibration examples (commented out for safety)
        print("\n" + "-" * 60)
        print("Calibration Functions Available:")
        print("  calibrate_zero()           # Calibrate to 400ppm")
        print("  calibrate_span(2000)       # Calibrate to 2000ppm")
        print("  set_auto_calibration(True) # Enable ABC")
        print("\n⚠ WARNING: Only calibrate in controlled environments!")
        
        # Uncomment below to enable auto-calibration
        # print("\nEnabling auto-calibration...")
        # set_auto_calibration(True)
        # print("✓ Auto-calibration enabled")
        
    except MHZ19CReadError as e:
        print(f"\n✗ Read error: {e}")
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
    finally:
        # Clean up
        print("\n" + "-" * 60)
        print("Closing sensor connection...")
        close()
        print("✓ Done")
        print("=" * 60)


if __name__ == "__main__":
    main()
