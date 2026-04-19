import serial, struct

MOV = {0: "STOP", 1: "FWD", 2: "BACK", 3: "LEFT", 4: "RIGHT"}

s = serial.Serial('COM3', 115200, timeout=1)
text_buf = b''

while True:
    b = s.read(1)
    if not b:
        continue

    if b[0] == 0xAA:
        # potential frame start — try to read the rest
        b2 = s.read(1)
        if b2 and b2[0] == 0x55:
            payload = s.read(6)
            if len(payload) == 6:
                water, air, soil, ibus, mov, kill = struct.unpack('<4?B?', payload)
                print(f"Water:{int(water)} Air:{int(air)} Soil:{int(soil)} | Move:{MOV.get(mov,'?'):5s} | RC:{'OK  ' if ibus else 'LOST'} Kill:{'YES' if kill else 'no'}")
            text_buf = b''
        elif b2:
            text_buf += b2
    elif b[0] in (0x0A,):  # newline — flush text buffer as debug line
        line = text_buf.decode('ascii', errors='replace').strip()
        if line:
            print(f"[DBG] {line}")
        text_buf = b''
    elif b[0] != 0x0D:     # ignore carriage return, buffer everything else
        text_buf += b