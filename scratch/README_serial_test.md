# HERC-26  USB Serial Test Guide — Mega ↔ Raspberry Pi
## Team MOVIS

This guide covers everything needed to verify USB Serial communication between the
Arduino Mega and Raspberry Pi before deploying the rover firmware.

---

## File Map — What Is What

| File | What it is |
|---|---|
| `spanner/serial/mega_sanity/mega_sanity.ino` | **Standalone sanity sketch** — no motors, no iBUS, no PCA9685. Cycles through 5 known test states over USB Serial. Flash this FIRST. |
| `spanner/serial/pi_serial_sanity.py` | **Pi-side sanity script** — reads the 9-byte framed packets, pretty-prints every field. Works with both sanity sketch and rover firmware. |
| `mega/rover_mega/rover_mega.ino` | **Rover firmware** — full control stack. Has `BAREBONE_TEST 1` flag to disable drive motors during testing. |
| `sensor/mega.py` | Pi sensor driver for the Mega. Used by `real_stack.py` in production. |

---

## Hardware Required

- Raspberry Pi (any model)
- Arduino Mega 2560
- **USB cable** (Type-A to Type-B) — the same cable used to flash the Mega
- FlySky RC receiver (for Phase 3 only)

No level shifter. No SDA/SCL wires. Just the USB cable.

---

## Wiring

```
Raspberry Pi  USB-A  ────────────  USB-B  Arduino Mega
              (any USB port)               (USB port)
```

On the Pi, the Mega appears as `/dev/ttyACM0` (or `ttyACM1` if another device is connected first).

---

## One-Time Pi Setup

Install pyserial:

```bash
sudo apt install python3-serial
# or:
pip install pyserial
```

Verify the Mega is visible (Mega must be powered and USB connected):

```bash
ls /dev/ttyACM*
```

Expected output:

```
/dev/ttyACM0
```

If nothing appears: check the USB cable, confirm the Mega is powered, and confirm
the sketch is uploaded.

---

## Phase 1 — Sanity Test (Start Here)

**Goal:** Confirm the USB cable is working and the 9-byte frame format matches
between Mega and Pi before touching the rover firmware.

### Step 1 — Flash `mega_sanity.ino` to the Mega

```bash
# From the project root on your laptop (or Pi with arduino-cli installed):
arduino-cli compile --fqbn arduino:avr:mega spanner/serial/mega_sanity
arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 spanner/serial/mega_sanity
```

### Step 2 — Open Mega Serial Monitor (optional, for visual cross-check)

```bash
arduino-cli monitor -p /dev/ttyACM0 --config baudrate=115200
```

You should see the Mega cycling through states every 2 seconds:

```
============================================
 HERC-26  mega_sanity  USB Serial Ready
 Port    : /dev/ttyACM0 (USB cable to Pi)
 Baud    : 115200
 Frame   : 9 bytes (SYNC1 SYNC2 + 7 payload)
 Rate    : 10 Hz
 Cycle   : 2 s per state
============================================
[0] STATE 0 | all OFF  | failsafe ON
  payload: 00 00 00 00 00 00 01
[1] STATE 1 | water ON | FWD
  payload: 01 00 00 01 01 00 00
...
```

**Close the Serial Monitor before running the Pi script** — both cannot hold the
port open at the same time.

### Step 3 — Run Live Monitor on Pi

```bash
python spanner/serial/pi_serial_sanity.py
```

Expected output (one line per read, every 0.5 s):

```
============================================================
 HERC-26 Serial Sanity  │  /dev/ttyACM0 @ 115200  payload=7 bytes
============================================================
Mega responding — first read OK  payload=[01 00 00 01 01 00 00]

Live monitor — Ctrl+C to stop

  Poll │ water air   soil  │ move  pump  │ RC    failsafe  │ payload bytes (hex)
────────────────────────────────────────────────────────────────────────────────────
     1 │ YES   no    no    │ FWD   no    │ OK    off       │ [01 00 00 01 01 00 00]
     2 │ YES   no    no    │ FWD   no    │ OK    off       │ [01 00 00 01 01 00 00]
     3 │ no    no    no    │ STOP  no    │ LOST  ACTIVE    │ [00 00 00 00 00 00 01]
...
```

The states will cycle through all 5 in sequence, matching the Mega Serial output.

### Step 4 — Run Verify Mode on Pi (recommended)

This mode checks each of the 5 states against expected values automatically
and reports PASS/FAIL with no manual prompts:

```bash
python spanner/serial/pi_serial_sanity.py --verify
```

All 5 states should PASS:

```
Result: 5 PASS / 0 FAIL  (5 total)
ALL PASS — USB Serial wiring and packet format are correct.
```

---

## Phase 2 — Rover Firmware (Barebone, No Movement)

**Goal:** Flash the actual rover firmware with motors disabled and verify the
full status frame including iBUS channel decoding and tool states.

> **`BAREBONE_TEST 1`** in `rover_mega.ino` disables drive motors entirely.
> Servos, actuators, pump, and USB Serial status frames still work. You can test
> tool channels without the rover moving.

### Step 1 — Confirm `BAREBONE_TEST 1` in rover_mega.ino

Open `mega/rover_mega/rover_mega.ino` and check line 10:

```cpp
#define BAREBONE_TEST 1     // ← must be 1 for this phase
```

### Step 2 — Flash rover_mega.ino

```bash
arduino-cli compile --fqbn arduino:avr:mega mega/rover_mega
arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 mega/rover_mega
```

Mega Serial should print (close the monitor before Step 3):

```
HERC-26 Rover Mega — BAREBONE TEST MODE (motors disabled)
  iBUS decoding, USB serial status frames, tools, pump, servos are all active.
  Set BAREBONE_TEST 0 for full deployment.
```

### Step 3 — Run Live Monitor on Pi

```bash
python spanner/serial/pi_serial_sanity.py
```

At this point (no RC receiver connected):
- `ibus_pulse` = `no` (no valid RC signal)
- `failsafe` = `ACTIVE` (signal lost timeout triggered)
- All tool fields = `no`
- `movement` = `STOP`

This is correct — failsafe activates when no RC signal is present.

---

## Phase 3 — iBUS Live Test (RC Receiver Connected)

**Goal:** Verify that stick and switch inputs from the FlySky transmitter
produce the correct values in the status frame.

### iBUS Receiver Wiring to Mega

```
FlySky Receiver iBUS port
  Signal wire (white/orange)  →  Mega RX1 (pin 19)
  5V (red)                    →  Mega 5V
  GND (black/brown)           →  Mega GND
```

> iBUS uses a single-wire half-duplex protocol on the receiver's iBUS output
> port. Connect only the signal wire to Mega RX1. The USB cable to the Pi is
> completely separate — they do not interfere.

### Channel Map (FlySky iBUS, as read by rover_mega.ino)

| Stick / Switch | Channel | iBUS index | What you should see in status frame |
|---|---|---|---|
| Right stick ↑ / ↓ | CH2 | idx 1 | `move = FWD` or `BACK` |
| Right stick ← / → | CH1 | idx 0 | `move = LEFT` or `RIGHT` |
| Right stick centred | — | — | `move = STOP` |
| Throttle (CH3) | CH3 | idx 2 | Scales overall speed; iBUS valid check |
| SW-A or assigned switch | CH5 | idx 4 | `soil = YES` when high |
| SW-B or assigned switch | CH6 | idx 5 | `water = YES`, `pump = YES` when high |
| SW-C or assigned switch | CH7 | idx 6 | `air = YES` when high |

> **Movement threshold:** A turn is reported as LEFT or RIGHT only when CH1 is
> more than 2× deadzone from centre (>80 units). Small stick deflections with
> forward/back still show FWD/BACK.

### Step 1 — Turn on transmitter and receiver

Power the receiver from the Mega 5V pin. Turn on the FlySky transmitter.
The Mega `LED_SIGNAL` (pin 30) should light up when a valid signal is received.

### Step 2 — Run Live Monitor on Pi

```bash
python spanner/serial/pi_serial_sanity.py
```

### Step 3 — Move sticks and flip switches

| Action | Expected in live monitor |
|---|---|
| Transmitter off → on | `RC: LOST → OK`, `failsafe: ACTIVE → off` |
| Push right stick forward | `move: FWD` |
| Push right stick back | `move: BACK` |
| Push right stick left | `move: LEFT` |
| Push right stick right | `move: RIGHT` |
| Centre all sticks | `move: STOP` |
| Flip CH5 switch high | `soil: YES` |
| Flip CH6 switch high | `water: YES`, `pump: YES` |
| Flip CH7 switch high | `air: YES` |
| Turn off transmitter (> 0.5 s) | `failsafe: ACTIVE`, all fields reset |

---

## Frame Reference

The 9-byte frame pushed from Mega to Pi over USB Serial at 10 Hz:

```
Byte  Field         Type    Values
──────────────────────────────────────────────────────────────────────
  0   SYNC1         magic   0xAA  (frame header byte 1)
  1   SYNC2         magic   0x55  (frame header byte 2)
  2   tool_water    bool    0x00 = off,  0x01 = on
  3   tool_air      bool    0x00 = off,  0x01 = on
  4   tool_soil     bool    0x00 = off,  0x01 = on
  5   ibus_pulse    bool    0x00 = RC signal bad this cycle
                            0x01 = RC signal valid this cycle
  6   movement      uint8   0x00 = STOP
                            0x01 = FWD
                            0x02 = BACK
                            0x03 = LEFT
                            0x04 = RIGHT
  7   pump_running  bool    0x00 = pump off,  0x01 = pump running
  8   failsafe      bool    0x00 = normal
                            0x01 = RC lost > 500 ms, all outputs stopped
```

**ibus_pulse vs failsafe — what is the difference:**

- `ibus_pulse = 0` means the Mega read an invalid RC frame on *this specific
  loop cycle* (50 Hz). The Mega still holds its last state for up to 500 ms.
  This is normal during brief RF glitches.

- `failsafe = 1` means 500 ms of *continuous* signal loss has passed. The
  Mega has now actively stopped all motors, actuators, pump, and servos.
  The rover is physically halted. This is the critical state.

Both flags together give three distinct states on the Pi/dashboard:
1. `ibus_pulse=1, failsafe=0` — RC OK, normal operation
2. `ibus_pulse=0, failsafe=0` — brief glitch, rover still running last command
3. `ibus_pulse=0, failsafe=1` — RC truly lost, rover hard-stopped

---

## Troubleshooting

**`ls /dev/ttyACM*` shows nothing**
- Check the USB cable is fully seated on both ends
- Try a different USB port on the Pi
- Confirm the Mega is powered (power LED should be on)
- Confirm the sketch is uploaded — a blank Mega may not enumerate as ttyACM

**`pi_serial_sanity.py` fails immediately with "Cannot open /dev/ttyACM0"**
- Check `ls /dev/ttyACM*` — port may be `ttyACM1` if another USB serial device is connected
- Try: `python spanner/serial/pi_serial_sanity.py --port /dev/ttyACM1`
- Make sure the Mega Serial monitor (arduino-cli monitor) is closed — it holds the port

**`Mega NOT responding: Serial timeout`**
- arduino-cli monitor may still be holding the port — close it first
- The sketch may not be running — power-cycle the Mega and wait 2 s

**All fields read as 0x00 on every poll**
- The Mega may not be sending frames. Check the Serial monitor shows state cycling.
- `sendStatusFrame()` is called from `maybeSendStatus()` — confirm the sketch was compiled fresh.

**`movement` always shows STOP even when sticks are moved**
- In BAREBONE_TEST mode, `currentSpeedL/R` must reach > 5.0 before movement
  is reported. Throttle (CH3) must be above centre to scale speed up.

**`failsafe` stays ACTIVE after turning on transmitter**
- `lastSignalTime` resets as soon as one valid iBUS frame is received. Check
  that the iBUS signal wire is on Mega RX1 (pin 19) and not RX0 (pin 0).

**verify mode shows field mismatches**
- Most likely a timing issue — the Pi read during a state transition.
  Re-run verify mode; it automatically waits 2.5 s between state checks.

---

## Going to Full Deployment

When serial tests pass in all three phases:

1. Set `#define BAREBONE_TEST 0` in `mega/rover_mega/rover_mega.ino`
2. Recompile and upload
3. Mega Serial will print: `HERC-26 Rover Mega — Full deployment mode`
4. All 6 drive motors are now active — **keep the rover on blocks for the
   first movement test**

Use `python sensor/mega.py` on the Pi for a live print of what
`real_stack.py` will see in production.
