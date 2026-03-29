# HERC-26  I2C Test Guide — Mega ↔ Raspberry Pi
## Team MOVIS

This guide covers everything needed to verify I2C communication between the
Arduino Mega and Raspberry Pi before deploying the rover firmware.

---

## File Map — What Is What

| File | What it is |
|---|---|
| `spanner/i2c/mega_sanity/mega_sanity.ino` | **Standalone sanity sketch** — no motors, no iBUS, no PCA9685. Cycles through 5 known test states over I2C. Flash this FIRST. |
| `spanner/i2c/pi_i2c_sanity.py` | **Pi-side sanity script** — reads the 7-byte packet, pretty-prints every field. Works with both sanity sketch and rover firmware. |
| `mega/rover_mega/rover_mega.ino` | **Rover firmware** — full control stack. Has `BAREBONE_TEST 1` flag to disable drive motors during testing. |
| `sensor/mega.py` | Pi sensor driver for the Mega. Used by `real_stack.py` in production. |

---

## Hardware Required

- Raspberry Pi (any model with 40-pin GPIO)
- Arduino Mega 2560
- **Bidirectional I2C level shifter** (e.g. BSS138-based 4-channel module)
  — needed because Pi GPIO is **3.3 V** and Mega I2C is **5 V**
- FlySky RC receiver (for Phase 3 only)
- USB cable for Mega (for serial monitor during testing)
- Jumper wires

---

## Wiring — Level Shifter to Pi and Mega

The level shifter has two sides: **LV (low voltage = 3.3 V)** and **HV (high voltage = 5 V)**.

```
┌──────────────────────────────────────────────────────────────────┐
│              Bidirectional I2C Level Shifter                     │
│                                                                  │
│  LV side (3.3 V)          │          HV side (5 V)              │
│  ─────────────────         │         ──────────────────          │
│  LV  ← Pi 3.3 V (pin 1)   │   HV  ← Mega 5V pin                │
│  GND ← Pi GND  (pin 6)    │   GND ← Mega GND                   │
│  SDA ← Pi GPIO2 (pin 3)   │   SDA → Mega SDA (pin 20)          │
│  SCL ← Pi GPIO3 (pin 5)   │   SCL → Mega SCL (pin 21)          │
└──────────────────────────────────────────────────────────────────┘
```

**Pi GPIO header reference (physical pin numbers):**

```
Pin 1  = 3.3 V       Pin 2  = 5 V
Pin 3  = GPIO2 SDA   Pin 4  = 5 V
Pin 5  = GPIO3 SCL   Pin 6  = GND
Pin 9  = GND
```

**Mega I2C pins:**
```
Pin 20 = SDA
Pin 21 = SCL
```

> **Important:** Do NOT connect Pi GPIO directly to Mega I2C without the level
> shifter. 5 V on a Pi GPIO pin will damage it.

> **Pull-ups:** Most BSS138 modules include 10 kΩ pull-ups on both sides.
> If your module has no pull-ups, add 4.7 kΩ from SDA and SCL to 3.3 V on
> the Pi side.

---

## One-Time Pi Setup

Enable I2C on the Pi if you haven't already:

```bash
sudo raspi-config
# Interface Options → I2C → Yes → Finish → reboot
```

Install smbus:

```bash
sudo apt install python3-smbus i2c-tools
```

Verify I2C is working (Mega must be powered and running any sketch):

```bash
i2cdetect -y 1
```

Expected output — `08` must appear:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- 08 -- -- -- -- -- -- --
```

If `08` does not appear: check wiring, power, and that the Mega sketch is running.

---

## Phase 1 — Sanity Test (Start Here)

**Goal:** Confirm the physical I2C wiring is correct and the 7-byte packet
format matches between Mega and Pi before touching the rover firmware.

### Step 1 — Flash `mega_sanity.ino` to the Mega

```bash
# From the project root on your laptop (or Pi with arduino-cli installed):
arduino-cli compile --fqbn arduino:avr:mega spanner/i2c/mega_sanity
arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyACM0 spanner/i2c/mega_sanity
```

### Step 2 — Open Mega Serial Monitor

```bash
arduino-cli monitor -p /dev/ttyACM0 --config baudrate=115200
```

You should see the Mega cycling through states every 2 seconds:

```
============================================
 HERC-26  mega_sanity  I2C Slave Ready
 Address : 0x08
 Packet  : 7 bytes
 Cycle   : 2 s per state
============================================
[0] STATE 0 | all OFF  | failsafe ON
  raw: 00 00 00 00 00 00 01
[1] STATE 1 | water ON | FWD
  raw: 01 00 00 01 01 00 00
...
```

Keep this window open — you will use it to sync the verify mode below.

### Step 3 — Run Live Monitor on Pi

```bash
python spanner/i2c/pi_i2c_sanity.py
```

Expected output (one line per read, every 0.5 s):

```
======================================================
 HERC-26 I2C Sanity  │  bus=1  addr=0x08  packet=7 bytes
======================================================
Mega responding — first read OK  raw=[01 00 00 01 01 00 00]

Live monitor — Ctrl+C to stop

  Poll │ water air   soil  │ move  pump  │ RC    failsafe  │ raw bytes (hex)
──────────────────────────────────────────────────────────────────────────────
     1 │ YES   no    no    │ FWD   no    │ OK    off       │ [01 00 00 01 01 00 00]
     2 │ YES   no    no    │ FWD   no    │ OK    off       │ [01 00 00 01 01 00 00]
     3 │ no    no    no    │ STOP  no    │ LOST  ACTIVE    │ [00 00 00 00 00 00 01]
...
```

The states will cycle in sync with what the Mega Serial monitor shows.

### Step 4 — Run Verify Mode on Pi (optional but recommended)

This mode checks each of the 5 states against expected values and reports PASS/FAIL:

```bash
python spanner/i2c/pi_i2c_sanity.py --verify
```

Follow the prompts — the script will tell you when to watch for each state
on the Mega Serial monitor. All 5 states should PASS.

```
Result: 5 PASS / 0 FAIL  (5 total)
ALL PASS — I2C wiring and packet format are correct.
```

---

## Phase 2 — Rover Firmware (Barebone, No Movement)

**Goal:** Flash the actual rover firmware with motors disabled and verify the
full I2C packet including iBUS channel decoding and tool states.

> **`BAREBONE_TEST 1`** in `rover_mega.ino` disables drive motors entirely.
> Servos, actuators, pump, and I2C packet still work. You can test tool
> channels without the rover moving.

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

Mega Serial should print:

```
HERC-26 Rover Mega — BAREBONE TEST MODE (motors disabled)
  iBUS decoding, I2C packet, tools, pump, servos are all active.
  Set BAREBONE_TEST 0 for full deployment.
```

### Step 3 — Run Live Monitor on Pi

```bash
python spanner/i2c/pi_i2c_sanity.py
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
produce the correct values in the I2C packet.

### iBUS Receiver Wiring to Mega

```
FlySky Receiver iBUS port
  Signal wire (white/orange)  →  Mega RX1 (pin 19)
  5V (red)                    →  Mega 5V
  GND (black/brown)           →  Mega GND
```

> iBUS uses a single-wire half-duplex protocol on the receiver's iBUS output
> port. Connect only the signal wire to Mega RX1. Do not use the UART TX1 pin.

### Channel Map (FlySky iBUS, as read by rover_mega.ino)

| Stick / Switch | Channel | iBUS index | What you should see in packet |
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
python spanner/i2c/pi_i2c_sanity.py
```

### Step 3 — Move sticks and flip switches

What to check:

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

## Packet Reference

The 7-byte packet sent from Mega to Pi on every I2C read:

```
Byte  Field         Type    Values
──────────────────────────────────────────────────────────────────
  0   tool_water    bool    0x00 = off,  0x01 = on
  1   tool_air      bool    0x00 = off,  0x01 = on
  2   tool_soil     bool    0x00 = off,  0x01 = on
  3   ibus_pulse    bool    0x00 = RC signal bad this cycle
                            0x01 = RC signal valid this cycle
  4   movement      uint8   0x00 = STOP
                            0x01 = FWD
                            0x02 = BACK
                            0x03 = LEFT
                            0x04 = RIGHT
  5   pump_running  bool    0x00 = pump off,  0x01 = pump running
  6   failsafe      bool    0x00 = normal
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

**`i2cdetect -y 1` shows nothing / blank grid**
- Check LV/HV sides of level shifter are not swapped
- Confirm Mega is powered and sketch is uploaded and running
- Confirm GND is shared between Pi and Mega

**`0x08` appears in `i2cdetect` but pi_i2c_sanity.py fails to read**
- Try: `python spanner/i2c/pi_i2c_sanity.py --addr 0x08 --bus 1`
- Check if PCA9685 (0x40) is also on the bus — if it conflicts, check wiring

**All fields read as 0x00 on every poll**
- The Mega may be sending a packet of all zeros if `updateStatusPacket()` is
  not being called. Check the Mega Serial monitor for output.

**`movement` always shows STOP even when sticks are moved**
- In BAREBONE_TEST mode, `currentSpeedL/R` must reach > 5.0 before movement
  is reported. Throttle (CH3) must be above centre to scale speed up.

**`failsafe` stays ACTIVE after turning on transmitter**
- `lastSignalTime` resets as soon as one valid iBUS frame is received. Check
  that the iBUS signal wire is on Mega RX1 (pin 19) and not RX0 (pin 0).

**verify mode shows field mismatches**
- Most likely a timing issue — the Pi read during a state transition.
  Re-run verify mode and follow the prompts more slowly.

---

## Going to Full Deployment

When I2C tests pass in all three phases:

1. Set `#define BAREBONE_TEST 0` in `mega/rover_mega/rover_mega.ino`
2. Recompile and upload
3. Mega Serial will print: `HERC-26 Rover Mega — Full deployment mode`
4. All 6 drive motors are now active — **keep the rover on blocks for the
   first movement test**

Use `python sensor/mega.py` on the Pi for a live print of what
`real_stack.py` will see in production.
