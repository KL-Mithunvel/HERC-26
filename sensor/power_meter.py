import serial
import RPi.GPIO as GPIO
import time

# Define GPIO pin for RE/DE control
RS485_CONTROL = 18  

# Set up GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(RS485_CONTROL, GPIO.OUT)

# Configure the serial connection
ser = serial.Serial(
    port='/dev/serial0',  # Raspberry Pi UART port
    baudrate=9600,        # Set baud rate to match RS485 device
    timeout=1
)

def send_data(data):
    GPIO.output(RS485_CONTROL, GPIO.HIGH)  # Enable transmission
    time.sleep(0.01)  # Small delay before sending
    ser.write(data.encode())  # Send data as bytes
    time.sleep(0.01)  # Small delay to ensure data is sent
    GPIO.output(RS485_CONTROL, GPIO.LOW)  # Enable receiving

def receive_data():
    GPIO.output(RS485_CONTROL, GPIO.LOW)  # Enable reception
    data = ser.readline().decode('utf-8').strip()
    return data

try:
    while True:
        send_data("Hello RS485 Device!\n")
        print("Data sent!")

        # Wait for a response
        response = receive_data()
        if response:
            print(f"Received: {response}")

        time.sleep(2)
except KeyboardInterrupt:
    print("Exiting...")
finally:
    ser.close()
    GPIO.cleanup()
