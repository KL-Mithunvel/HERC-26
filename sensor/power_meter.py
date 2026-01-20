from pymodbus.client import ModbusSerialClient
import csv
import time
from datetime import datetime
import os

COM_PORT = "COM10"
SLAVE_ID = 1
CSV_FILE = "power_meter_log.csv"
READ_INTERVAL = 1

# Initialize serial RTU client (no 'method' argument)
client = ModbusSerialClient(
    port=COM_PORT,
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1
)

if not client.connect():
    print(f" Failed to connect to {COM_PORT}")
    exit()

print(f" Connected to power meter on {COM_PORT}")

# Prepare CSV
file_exists = os.path.isfile(CSV_FILE)
csv_file = open(CSV_FILE, mode="a", newline="")
writer = csv.writer(csv_file)
if not file_exists:
    writer.writerow(["Timestamp", "Voltage(V)", "Current(A)", "Power(W)"])
    csv_file.flush()

# Main loop
try:
    while True:
        # ✅ Use slave_id instead of unit
        voltage = client.read_holding_registers(SLAVE_ID, 0, 1)
        current = client.read_holding_registers(SLAVE_ID, 1, 1)
        power   = client.read_holding_registers(SLAVE_ID, 2, 1)


        if voltage.isError() or current.isError() or power.isError():
            print("⚠️ Modbus read error, retrying...")
            client.close()
            time.sleep(1)
            client.connect()
            continue

        v = voltage.registers[0] / 10
        c = current.registers[0] / 100
        p = power.registers[0]

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(timestamp, v, c, p)
        writer.writerow([timestamp, v, c, p])
        csv_file.flush()

        time.sleep(READ_INTERVAL)

except KeyboardInterrupt:
    print("\nStopped by user")

finally:
    csv_file.close()
    client.close()
