"""
scripts/debug_power_meter.py — Step-by-step power meter diagnostics.

Run on Pi:  python3 scripts/debug_power_meter.py
Each step prints PASS or FAIL with details so you know exactly where it breaks.
"""
import time, sys

PORT      = "/dev/ttyAMA0"
BAUD      = 9600
DE_PIN    = 18               # GPIO 18 = physical pin 12
GPIO_CHIP = "/dev/gpiochip0"
ADDR      = 0xF8   # PZEM general address (single-slave mode)

# ── Step 1: gpiod import ──────────────────────────────────────────────────────
print("\n[1] gpiod import ...", end=" ")
try:
    import gpiod
    from gpiod.line import Direction, Value
    print(f"PASS  (version {gpiod.__version__})")
except ImportError as e:
    print(f"FAIL  {e}")
    sys.exit(1)

# ── Step 2: open GPIO chip ────────────────────────────────────────────────────
print(f"[2] open {GPIO_CHIP} ...", end=" ")
try:
    chip = gpiod.Chip(GPIO_CHIP)
    print("PASS")
except Exception as e:
    print(f"FAIL  {e}")
    sys.exit(1)

# ── Step 3: claim DE/RE pin ───────────────────────────────────────────────────
print(f"[3] claim GPIO {DE_PIN} as output ...", end=" ")
try:
    req = chip.request_lines(
        consumer="debug-dere",
        config={DE_PIN: gpiod.LineSettings(
            direction=Direction.OUTPUT,
            output_value=Value.INACTIVE,
        )},
    )
    print("PASS")
except Exception as e:
    print(f"FAIL  {e}")
    chip.close()
    sys.exit(1)

# ── Step 4: toggle DE/RE ──────────────────────────────────────────────────────
print(f"[4] toggle DE/RE HIGH then LOW ...", end=" ")
try:
    req.set_value(DE_PIN, Value.ACTIVE)
    time.sleep(0.01)
    req.set_value(DE_PIN, Value.INACTIVE)
    print("PASS")
except Exception as e:
    print(f"FAIL  {e}")
    req.release(); chip.close()
    sys.exit(1)

# ── Step 5: open serial port ──────────────────────────────────────────────────
print(f"[5] open {PORT} at {BAUD} 8N2 ...", end=" ")
try:
    import serial
    ser = serial.Serial(
        port=PORT, baudrate=BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_TWO,
        timeout=1.0,
    )
    print("PASS")
except Exception as e:
    print(f"FAIL  {e}")
    req.release(); chip.close()
    sys.exit(1)

# ── Step 6: build + send Modbus frame ────────────────────────────────────────
def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")

pdu     = bytes([ADDR, 0x04, 0x00, 0x00, 0x00, 0x08])
request = pdu + crc16(pdu)

print(f"[6] send frame: {request.hex(' ')} ...", end=" ")
try:
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    req.set_value(DE_PIN, Value.ACTIVE)       # TX mode
    time.sleep(0.005)
    ser.write(request)
    ser.flush()
    tx_time = len(request) * 11 / BAUD
    time.sleep(tx_time + 0.015)
    req.set_value(DE_PIN, Value.INACTIVE)     # RX mode
    print("PASS")
except Exception as e:
    print(f"FAIL  {e}")
    ser.close(); req.release(); chip.close()
    sys.exit(1)

# ── Step 7: read response ─────────────────────────────────────────────────────
print("[7] waiting for response (1s timeout) ...", end=" ")
time.sleep(0.1)
response = ser.read(256)

if not response:
    print("FAIL  — no bytes received (timeout)")
    print("\n  Possible causes:")
    print("  a) PZEM not powered / not connected to RS485 bus")
    print("  b) TX/RX wires swapped (try swapping DI/RO on MAX485)")
    print("  c) DE/RE not switching (check GPIO 18 wiring)")
    print("  d) Wrong serial port (check /dev/ttyAMA0 is your MAX485 UART)")
    ser.close(); req.release(); chip.close()
    sys.exit(1)

print(f"PASS  ({len(response)} bytes: {response.hex(' ')})")

# ── Step 8: parse response ────────────────────────────────────────────────────
print("[8] parse response ...", end=" ")
if len(response) < 5:
    print(f"FAIL  too short ({len(response)} bytes)")
elif response[1] & 0x80:
    print(f"FAIL  Modbus exception code 0x{response[2]:02X}")
else:
    byte_count = response[2]
    payload    = response[:3 + byte_count]
    exp_crc    = crc16(payload)
    act_crc    = bytes(response[3 + byte_count: 3 + byte_count + 2])
    if exp_crc != act_crc:
        print(f"FAIL  CRC mismatch (expected {exp_crc.hex()}, got {act_crc.hex()})")
    else:
        data = response[3: 3 + byte_count]
        regs = [(data[i] << 8) | data[i+1] for i in range(0, len(data)-1, 2)]
        print("PASS")
        print(f"\n  Raw registers : {[hex(r) for r in regs]}")
        if len(regs) >= 4:
            print(f"  Voltage       : {regs[0] * 0.01:.2f} V")
            print(f"  Current       : {regs[1] * 0.01:.2f} A")
            power_raw = (regs[3] << 16) | regs[2]
            print(f"  Power         : {power_raw * 0.1:.1f} W")

ser.close()
req.release()
chip.close()
print("\nDone.")