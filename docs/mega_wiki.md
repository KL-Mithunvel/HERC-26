# HERC-26 Arduino Mega — Developer Wiki

Complete reference for the rover's Arduino Mega co-processor: firmware inventory, hardware pin map, drive algorithm, arm trajectory systems, RC control scheme, and integration rules.

---

## Table of Contents

1. [System Role](#1-system-role)
2. [Folder Structure](#2-folder-structure)
3. [Library Dependencies](#3-library-dependencies)
4. [Final_Mega — Production Drive Firmware](#4-final_mega--production-drive-firmware)
   - [Motor Layout](#motor-layout)
   - [PCA9685 Servo Channels](#pca9685-servo-channels)
   - [Status LEDs](#status-leds)
   - [iBUS RC Channel Map](#ibus-rc-channel-map)
   - [Drive Algorithm](#drive-algorithm-envelope--sloppy-acceleration)
   - [Test Mode](#test-mode)
   - [Failsafe](#failsafe)
   - [Key Constants](#key-constants)
5. [rover_movement — Older Drive Firmware](#5-rover_movement--older-drive-firmware)
6. [movement_test — Intermediate Drive Firmware](#6-movement_test--intermediate-drive-firmware)
7. [Arm Subsystem](#7-arm-subsystem)
   - [mega/arm/ — Delta-time System](#7a-megaarm--delta-time-trajectory-system-older)
   - [ARM_sim/ — Absolute-time System](#7b-arm_sim--absolute-time-trajectory-system-newer)
   - [Format Comparison](#key-difference-delta-time-vs-absolute-time)
8. [USB Serial Test Sketch](#8-usb-serial-test-sketch)
9. [Other Test Sketches](#9-other-test-sketches)
10. [FlySky Transmitter — Control Scheme](#10-flysky-transmitter--control-scheme)
11. [Drive Firmware Comparison](#11-drive-firmware-comparison)
12. [klm/klm.ino — Integration Outline](#12-klmklmino--integration-outline)
13. [Known Hardware Issues](#13-known-hardware-issues)

---

## 1. System Role

The Raspberry Pi is the mission computer. The Arduino Mega is a dedicated real-time co-processor. Their responsibilities are strictly divided:

```
FlySky RC Receiver (iBUS, Serial1)
        │
        ▼
  Arduino Mega
  ├── 6-motor differential drive
  ├── 3 tool actuator servos (air / water / soil) via PCA9685 (I2C master)
  ├── 3-servo soil arm via PCA9685 (separate trajectory player)
  └── USB Serial (ttyACM0, 115200 baud)
        │  pushes 9-byte framed status frames at 10 Hz
        ▼
  Raspberry Pi  ←── sensor/mega.py  (pyserial driver)
  ├── All sensor logging (SQLite + JSONL)
  ├── Validation state machine (spanner/validation.py)
  └── Flask dashboard (web/app.py)
```

**Connection:** Standard USB-A to USB-B cable between Mega USB port and any Pi USB port.
No level shifter required. The Mega enumerates as `/dev/ttyACM0`.

**What the Pi receives from the Mega** (9-byte USB Serial frame, 10 Hz):

```python
{"tools":       {"air": bool, "water": bool, "soil": bool},
 "ibus_pulse":  bool,    # True = RC signal valid this cycle
 "movement":    str,     # "STOP" | "FWD" | "BACK" | "LEFT" | "RIGHT"
 "pump_running": bool,
 "failsafe":    bool}    # True = RC lost > 500 ms, all outputs stopped
```

`sensor/mega.py` calls `setup(port, baudrate)` and `read()` following the standard
sensor interface. It scans for the `0xAA 0x55` frame header and reads 7 payload bytes.

---

## 2. Folder Structure

```
mega/
├── Final_Mega/
│   ├── Final_Mega.ino            ← CURRENT production drive firmware (deploy this)
│   └── SlopeValuesRef.png        ← Reference chart for tuning SLOP_FACTOR
│
├── rover_movement/
│   └── rover_movement.ino        ← Older drive firmware (all-motors, trapezoidal)
│
├── movement_test/
│   └── movement_test.ino         ← Intermediate firmware (differential, fixed accel)
│
├── arm/                          ← Older arm tools — delta-time trajectory format
│   ├── SoilArmCode.ino           ← Delta-time arm trajectory player
│   ├── armPath_setter.py         ← Delta-time trajectory designer GUI
│   ├── arm_simulate.py           ← Delta-time trajectory simulator
│   ├── arm_poses_sweep_soil.csv  ← 10-pose delta-time trajectory
│   └── zeroAngle_orien.png       ← Arm zero-angle mounting reference
│
├── blink/
│   └── blink.ino                 ← LED blink sanity-check sketch
│
├── i2c_mega_recieve/
│   └── i2c_mega_recieve.ino      ← I2C slave test (counter, Pi sends 0xAA/0xFF)
│
├── modbus_led_slave_mega/
│   └── modbus_led_slave_mega.ino ← Modbus RTU slave test (LED via register)
│
├── powermeter_test/
│   └── powermeter_test.ino       ← PZEM-017 RS485 wiring test (bench only, not production)
│
├── klm/
│   └── klm.ino                   ← Outline for the unified final firmware
│
└── readme.md                     ← Brief library/controller notes
```

Also at the project root:

```
ARM_sim/                          ← Newer arm tools — absolute-time trajectory format
├── sim_create.py                 ← Advanced trajectory designer GUI
├── sim_view.py                   ← Animation player
└── arm_poses_5.csv               ← Placeholder trajectory (replace with real export)
```

---

## 3. Library Dependencies

| Library | Used by | Install via |
|---|---|---|
| `IBusBM` | Final_Mega, rover_movement, movement_test, klm | Arduino Library Manager |
| `Adafruit_PWMServoDriver` | Final_Mega, rover_movement, SoilArmCode, klm | Arduino Library Manager |
| `Wire` | All I2C sketches | Built-in (Arduino AVR core) |

---

## 4. Final_Mega — Production Drive Firmware

**File:** `mega/Final_Mega/Final_Mega.ino`
**Status:** Deploy this. It is the current rover drive firmware.

### Motor Layout

Six motors are arranged in three paired axles. Each pair is driven by one MDD10A dual-channel motor driver.

```
           FRONT
    ┌─────────────────┐
    │  FRONT_L  FRONT_R  │
    │   MID_L    MID_R   │
    │  BACK_L   BACK_R   │
    └─────────────────┘
           BACK
```

| Index | Constant | Position | PWM pin | DIR pin | Side |
|---|---|---|---|---|---|
| 0 | `FRONT_R` | Front Right | 2 | 22 | Right |
| 1 | `FRONT_L` | Front Left  | 3 | 23 | Left  |
| 2 | `MID_R`   | Mid Right   | 6 | 24 | Right |
| 3 | `MID_L`   | Mid Left    | 7 | 25 | Left  |
| 4 | `BACK_R`  | Back Right  | 4 | 26 | Right |
| 5 | `BACK_L`  | Back Left   | 5 | 27 | Left  |

Right-side motors (`FRONT_R`, `MID_R`, `BACK_R`) receive `targetR` from the mixer.
Left-side motors (`FRONT_L`, `MID_L`, `BACK_L`) receive `targetL`.

> **Warning:** Back motor PWM pins are **4 and 5** in Final_Mega. The older
> `rover_movement` sketch uses **9 and 10**. Verify physical wiring matches
> whichever sketch is loaded before powering the drive.

### PCA9685 Servo Channels

I2C address `0x40`, 50 Hz.

| Channel | Function |
|---|---|
| 0 | Tool actuator — CH5 switch (air) |
| 1 | Tool actuator — CH7 switch (water) |
| 2 | Tool actuator — CH8 switch (soil / arm) |

### Status LEDs

| Pin | Signal | Meaning |
|---|---|---|
| 30 | `LED_SIGNAL` | HIGH when a valid iBUS frame has been received |
| 31 | `LED_CH5` | Mirrors CH5 switch state |
| 32 | `LED_CH7` | Mirrors CH7 switch state |
| 33 | `LED_CH8` | Mirrors CH8 switch state |

### iBUS RC Channel Map

FlySky receiver on `Serial1`.

| Channel | Index | Physical input | Role |
|---|---|---|---|
| CH1 | 0 | Right stick horizontal | Turn (Y-axis) |
| CH2 | 1 | Left stick vertical | Forward / backward base speed |
| CH3 | 2 | Right stick vertical | Speed envelope scale |
| CH5 | 4 | Toggle switch A | Test mode when > 1700 µs; air tool servo otherwise |
| CH7 | 6 | Toggle switch B | Water tool servo |
| CH8 | 7 | Toggle switch C | Soil / arm tool servo |

> **CH5 conflict:** Test mode activates at > 1700 µs; the CH5 servo activates
> at > 1500 µs. The thresholds are intentionally staggered so the tool cannot
> be fully activated while test mode is engaged.

### Drive Algorithm: Envelope + Sloppy Acceleration

```
// Step 1 — Normalize with dead-band
moveRaw  = ch2 − 1500   (zeroed if |moveRaw|  < DEADZONE = 40)
scaleRaw = ch3 − 1500   (zeroed if |scaleRaw| < DEADZONE)
turnRaw  = ch1 − 1500   (zeroed if |turnRaw|  < DEADZONE)

moveFactor  = moveRaw  / 500
scaleFactor = scaleRaw / 500
turnFactor  = turnRaw  / 500

// Step 2 — Base speed and envelope
X        = moveFactor × 255          ← full-range base forward/back
limitedX = X × scaleFactor           ← CH3 scales the envelope

// Step 3 — Speed-proportional turn reduction
speedRatio = |limitedX| / 255
turnReduce = 1.0 − (speedRatio × TURN_REDUCTION)   [clamped 0.2–1.0]
Y          = turnFactor × TURN_MAX × turnReduce     ← weaker turns at high speed

// Step 4 — Differential mixing
targetL = limitedX + Y   [clamped ±255]
targetR = limitedX − Y   [clamped ±255]

// Step 5 — Sloppy adaptive ramp
dynamicStep = BASE_ACCEL_STEP + |error| × SLOP_FACTOR
dynamicStep = clamp(dynamicStep, BASE_ACCEL_STEP, MAX_ACCEL_STEP)
currentSpeed += sign(error) × min(dynamicStep, |error|)

// Step 6 — Apply to motors
//   Even indices (0, 2, 4) → right side → targetR
//   Odd  indices (1, 3, 5) → left side  → targetL
```

`SlopeValuesRef.png` is a reference chart for choosing `SLOP_FACTOR`. Higher = more aggressive ramp; lower = smoother.

### Test Mode

Activated when **CH5 > 1700 µs**. All driving stops. The Mega sequentially spins each motor forward at PWM 150 for 2 s with a 2 s pause between each.

Sequence: `FRONT_R → MID_R → BACK_R → FRONT_L → MID_L → BACK_L → repeat` (22 s cycle).

Use this to verify individual motor wiring, direction, and driver health before a run.

### Failsafe

Triggered when no valid iBUS frame is received for **500 ms**:

- `LED_SIGNAL` → LOW
- All 6 motors stopped (PWM = 0)
- All 3 PCA9685 servos → `SERVO_MIN` (retracted)

Exits automatically when RC signal is restored.

### Key Constants

| Constant | Value | Meaning |
|---|---|---|
| `DEADZONE` | 40 | Stick dead-band around 1500 µs center |
| `CENTER_PWM` | 1500 | Neutral RC pulse width (µs) |
| `ABSOLUTE_MAX_PWM` | 255 | Maximum motor PWM output |
| `TURN_MAX` | 180 | Maximum turn contribution |
| `TURN_REDUCTION` | 1.0 | Speed-proportional turn reduction multiplier |
| `BASE_ACCEL_STEP` | 12 | Minimum ramp step per 10 ms loop |
| `SLOP_FACTOR` | 0.35 | Error-proportional step multiplier |
| `MAX_ACCEL_STEP` | 25 | Maximum ramp step per loop |
| `LOOP_DELAY` | 10 ms | Main loop period (~100 Hz) |
| `FAILSAFE_TIMEOUT` | 500 ms | Signal loss before hard stop |
| `SERVO_MIN` / `SERVO_MAX` | 150 / 600 | PCA9685 counts for tool servo travel limits |

---

## 5. rover_movement — Older Drive Firmware

**File:** `mega/rover_movement/rover_movement.ino`
**Status:** Superseded by Final_Mega. Kept as reference only.

| Feature | rover_movement | Final_Mega |
|---|---|---|
| Turning | None — single speed, direction only | CH1 differential turn |
| CH2 use | > 1400 µs = forward, else backward | Normalized to ±speed |
| CH3 use | Throttle magnitude | Speed envelope scale |
| Acceleration | Fixed trapezoidal (ACCEL_STEP = 2) | Sloppy adaptive |
| MAX motor PWM | 160 (63% MDD10A safety cap) | 255 |
| Back motor PWM pins | **9, 10** | **4, 5** |
| Loop period | 20 ms (50 Hz) | 10 ms (100 Hz) |
| Direction-change delay | 200 ms pause on reversal | None |
| Failsafe tracking | `failsafeActive` bool | Inline timeout check |
| Servo safe position | Applied in `setup()` | Failsafe trigger only |

---

## 6. movement_test — Intermediate Drive Firmware

**File:** `mega/movement_test/movement_test.ino`
**Status:** Development iteration, superseded by Final_Mega.

Uses the same physical pin map as Final_Mega. Has differential drive, test mode, and failsafe. Key differences:

| Feature | movement_test | Final_Mega |
|---|---|---|
| Acceleration | Fixed step (ACCEL_STEP = 15) | Sloppy adaptive |
| Speed envelope | CH3 as hard speed cap | CH3 scales CH2 range |
| Turn reduction | None | Speed-proportional |
| Loop period | 10 ms | 10 ms |

---

## 7. Arm Subsystem

There are **two independent arm tool sets** in this project using **different trajectory formats**. They are not interchangeable as-is.

### 7a. mega/arm/ — Delta-time Trajectory System (older)

Each pose stores the **time to travel from the previous pose** (Δt in seconds).

**`SoilArmCode.ino`** embeds the trajectory directly as a `Pose[]` array. At power-up it plays the sequence once using `millis()`-based linear interpolation, then halts. The 10-pose sequence takes ~25 seconds total.

**`armPath_setter.py`** — designer GUI:
- Sliders for reference angles (mounting offset) and sweep angles (0–180°)
- Saves poses with their Δt, exports to `arm_poses_sweep.csv`

**`arm_simulate.py`** — playback simulator:
- Same reference + sweep sliders; SIMULATE button replays the full sequence

**Arm geometry:**

```
Base ── Link1 (L1 = 140 mm) ── Link2 (L2 = 140 mm) ── Bucket (LB = 55 mm)
        θ1                      θ2                      θ3
```

Forward kinematics (2D planar):

```
x1 = L1·cos(θ1)               y1 = L1·sin(θ1)
x2 = x1 + L2·cos(θ1+θ2)       y2 = y1 + L2·sin(θ1+θ2)
xb = x2 + LB·cos(θ1+θ2+θ3)    yb = y2 + LB·sin(θ1+θ2+θ3)
```

PCA9685 servo count: `count = pulseUs × 50 × 4096 / 1,000,000`
Pulse range: 500–2500 µs → angles 0–180°.

**10-pose trajectory** (`arm_poses_sweep_soil.csv`):

| Segment | Δt (s) | θ1 (°) | θ2 (°) | θ3 (°) |
|---|---|---|---|---|
| 0 → 1 | 3.02 | 180.0 | 159.7 | 150.6 |
| 1 → 2 | 3.06 | 31.9  | 83.4  | 30.3  |
| 2 → 3 | 3.06 | 0     | 0     | 20.9  |
| 3 → 4 | 3.06 | 0     | 49.4  | 104.7 |
| 4 → 5 | 2.05 | 0     | 100.0 | 40.9  |
| 5 → 6 | 2.05 | 55.3  | 100.0 | 0     |
| 6 → 7 | 2.05 | 109.7 | 61.9  | 0     |
| 7 → 8 | 2.05 | 115.0 | 180.0 | 0     |
| 8 → 9 | 1.15 | 115.0 | 180.0 | 87.2  |
| 9 (end) | 2.33 | 180.0 | 180.0 | 123.4 |

### 7b. ARM_sim/ — Absolute-time Trajectory System (newer)

Located at the project root, not inside `mega/`.

Each pose stores the **absolute elapsed time** at which that angle must be reached. Interpolation works across the whole timeline.

**`ARM_sim/sim_create.py`** — advanced designer GUI:
- Sliders and text-box inputs for θ1/θ2/θ3 + time
- Configurable joint limits (th1/2/3 min/max)
- Base position (X, Y) — sets the arm mounting point on the plot
- Yellow target box — draggable rectangle showing the soil sample collection zone
- Poses exported to `arm_poses_export.csv` (`time_s, th1_deg, th2_deg, th3_deg`)

**`ARM_sim/sim_view.py`** — animation player:
- Reads any CSV with columns `time_s, th1_deg, th2_deg, th3_deg`
- Play/Pause, scrub slider, variable speed (0.1×–2×), Reset
- Uses `numpy.interp()` for smooth linear interpolation between keyframes
- `L2 = 130 mm` here vs 140 mm in `mega/arm/` — **verify which matches the physical arm**

**`ARM_sim/arm_poses_5.csv`** — placeholder with 2 example rows. Replace with a real export from `sim_create.py`.

**Workflow for a new trajectory:**

```
1. Run ARM_sim/sim_create.py
   └── design poses (absolute times), Export CSV → arm_poses_export.csv

2. Review in ARM_sim/sim_view.py
   └── load the CSV, press Play, verify motion reaches the target box

3. Embed the CSV data in klm.ino as a lookup table
   └── firmware uses millis()-based interpolation matching sim_view logic
```

### Key Difference: Delta-time vs Absolute-time

| Property | mega/arm/ (SoilArmCode) | ARM_sim/ (sim_view) |
|---|---|---|
| `time_s` meaning | Duration from previous pose | Absolute elapsed time |
| Column names | `time_s, th1, th2, th3` | `time_s, th1_deg, th2_deg, th3_deg` |
| Playback | Linear interpolation, sequential | `numpy.interp` across full timeline |
| Firmware model | Delta → `segmentDurationMs` per segment | Absolute → lookup by `millis()` |
| L2 value | 140 mm | 130 mm — verify hardware |

---

## 8. USB Serial Test Sketch

**File:** `spanner/serial/mega_sanity/mega_sanity.ino`
**Purpose:** Verify Pi↔Mega USB Serial communication before deploying rover firmware.
**Pi script:** `spanner/serial/pi_serial_sanity.py`
**Full guide:** `scratch/README_serial_test.md`

- Mega pushes 9-byte framed packets over USB Serial (ttyACM0) at 10 Hz
- Cycles through 5 test states every 2 seconds
- Pi script reads frames, verifies every field, reports PASS/FAIL automatically

**Frame format (9 bytes):**

| Byte | Field | Values |
|---|---|---|
| 0 | SYNC1 | 0xAA |
| 1 | SYNC2 | 0x55 |
| 2 | `tool_water` | 0 = off, 1 = on |
| 3 | `tool_air` | 0 = off, 1 = on |
| 4 | `tool_soil` | 0 = off, 1 = on |
| 5 | `ibus_pulse` | 0 = RC bad, 1 = RC valid |
| 6 | `movement` | 0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT |
| 7 | `pump_running` | 0 = off, 1 = running |
| 8 | `failsafe` | 0 = normal, 1 = RC lost > 500 ms |

`sensor/mega.py` decodes these into:

```python
{"tools":        {"air": bool, "water": bool, "soil": bool},
 "ibus_pulse":   bool,
 "movement":     str,   # "STOP" | "FWD" | "BACK" | "LEFT" | "RIGHT"
 "pump_running": bool,
 "failsafe":     bool}
```

---

## 9. Other Test Sketches

These are **standalone bench verification scripts only**. None are part of the production firmware and none should be loaded on the Mega at competition time.

### mega/blink/blink.ino

Standard LED blink on pin 13. Used to confirm the Mega is reachable via `arduino-cli` and that the upload toolchain works before loading real firmware.

### mega/modbus_led_slave_mega/modbus_led_slave_mega.ino

Modbus RTU slave test. The Mega acts as a Modbus slave; a master (PC or Pi) can write to a register to toggle an LED. Used to verify RS485 wiring and Modbus framing on the Mega serial lines.

### mega/powermeter_test/powermeter_test.ino

Reads the PZEM-017 power meter directly from the Mega over RS485 and prints voltage / current / power to the Serial Monitor. Used to verify RS485 wiring during bench testing.

> **Important:** In the operational rover system the PZEM-017 is connected to
> the **Raspberry Pi** (via RS485 USB adapter) and read by
> `sensor/power_meter.py`. **The Mega does not read the power meter at any
> point during normal rover operation.** This sketch is not loaded at
> competition time.

---

## 10. FlySky Transmitter — Control Scheme

This section defines how FlySky transmitter inputs map to rover behavior. The control scheme prioritises safety (immediate stop, automatic failsafe) while giving the operator adjustable aggressiveness.

### 10.1 Left Stick (Vertical) — Base Speed

**Channel:** CH2 (left stick vertical, index 1)

The left stick vertical axis is the primary throttle. It sets the base forward/backward speed before the speed envelope is applied.

| Stick position | Effect |
|---|---|
| Full forward | Maximum forward base speed |
| Center (within deadzone) | Stop |
| Full back | Maximum reverse base speed |

### 10.2 Right Stick — Speed Scale and Turn

**Channels:** CH3 (vertical, speed scale) + CH1 (horizontal, turn)

| Axis | Channel | Role |
|---|---|---|
| Vertical | CH3 | Scales the speed envelope — how much of the CH2 base speed is used |
| Horizontal | CH1 | Differential turn — steers left or right |

**Movement matrix:**

| Right stick input | Rover motion |
|---|---|
| Vertical forward | Increases speed envelope |
| Vertical center | Speed envelope = 0 — rover stops regardless of CH2 |
| Horizontal left | Rotate / steer left |
| Horizontal right | Rotate / steer right |
| Forward + left | Forward left arc |
| Forward + right | Forward right arc |
| Back + left | Reverse left arc |
| Back + right | Reverse right arc |

Both sticks must be pushed to achieve full speed (`limitedX = X × scaleFactor`). This is intentional for safety.

### 10.3 Turn Reduction at Speed

At high forward speed the turn contribution is automatically reduced to prevent rollovers:

```
speedRatio = |limitedX| / 255
turnReduce = clamp(1.0 − speedRatio × TURN_REDUCTION, 0.2, 1.0)
Y          = turnFactor × TURN_MAX × turnReduce
```

Turn authority is always at least 20% (`turnReduce` floor = 0.2), so the rover can steer even at full speed.

### 10.4 Tool Switches

| Switch | Channel | Tool |
|---|---|---|
| Switch A | CH5 | Air sampling system |
| Switch B | CH7 | Water sampling system |
| Switch C | CH8 | Soil collection / arm trigger |

CH5 also triggers **test mode** when > 1700 µs (see [§4 Test Mode](#test-mode)). Tools only actuate when the RC link is healthy and the kill switch is inactive.

### 10.5 Kill Switch and Failsafe

**Kill switch** (manual, operator-controlled channel):

- All motor PWM → 0 within one 10 ms loop cycle
- All tool servos → `SERVO_MIN` (retracted)
- Rover stays in KILLED state until the switch is manually disengaged

**RC failsafe** (automatic — no valid iBUS frame for 500 ms):

- Same hard stop as kill switch
- Exits automatically when RC signal is restored

### 10.6 Safety Priority Order

```
1. RC Failsafe      (signal loss — highest priority)
2. Kill Switch      (operator manual stop)
3. Tool Interlock   (tools disabled if 1 or 2 are active)
4. Drive Command    (normal operation)
```

### 10.7 Control Loop Rate

Final_Mega runs at **100 Hz (10 ms cycle)**. All joystick inputs are read, processed, and applied to motors within each 10 ms cycle.

---

## 11. Drive Firmware Comparison

| Feature | rover_movement | movement_test | Final_Mega |
|---|---|---|---|
| Turning | None | CH1 differential | CH1 differential |
| Acceleration model | Fixed step = 2 | Fixed step = 15 | Sloppy adaptive |
| Speed control | CH3 = throttle magnitude | CH3 = hard speed cap | CH3 scales CH2 range |
| Turn reduction | N/A | None | Speed-proportional |
| MAX motor PWM | 160 | 255 | 255 |
| Back motor PWM pins | 9, 10 | 4, 5 | 4, 5 |
| Loop rate | 50 Hz | 100 Hz | 100 Hz |
| Direction-change delay | 200 ms pause | None | None |
| Test mode | No | Yes | Yes |
| Failsafe tracking | `failsafeActive` bool | Inline timeout | Inline timeout |
| Servo safe position on start | Yes (`setup()`) | No | No |

---

## 12. klm/klm.ino — Integration Outline

`mega/klm/klm.ino` is a structured outline (not yet functional firmware) for the unified competition firmware. It must integrate:

1. **Drive** — envelope + sloppy accel from Final_Mega. No changes needed.
2. **Tool actuators** — CH5/CH7/CH8 → PCA9685 servos for air/water/soil.
   - Decision needed: does CH5 serve both tool and test mode, or should test mode move to a dedicated channel?
3. **Arm** — absolute-time trajectory player using the ARM_sim format.
   - Embed trajectory from a `sim_create.py` exported CSV as a firmware lookup table.
   - Trigger: dedicated RC channel or Pi I2C command.
4. **Pi USB Serial push** — push 9-byte framed status frames at 10 Hz over ttyACM0:
   - `[0xAA, 0x55, tool_water, tool_air, tool_soil, ibus_pulse, movement, pump_running, failsafe]`
   - `sensor/mega.py` decodes these via pyserial.
5. **Failsafe** — hard stop + all servos to `SERVO_MIN` on signal loss.
6. **Status LEDs** — signal health (pin 30) + per-tool state (pins 31–33).

---

## 13. Known Hardware Issues

**GPIO conflict in `config.xml`:**

`config.xml` assigns `de_re_pin = 17` (RS485 DE/RE line for the PZEM-017) and `WATER_SENSOR_GPIO = 17` (water tool control) to the **same Pi GPIO pin**. This must be resolved before Pi deployment:

> Rewire the RS485 DE/RE line to a free GPIO pin and update `<de_re_pin>` in `calibration/config.xml`.

**L2 arm link length discrepancy:**

`mega/arm/` tools use `L2 = 140 mm`; `ARM_sim/sim_view.py` uses `L2 = 130 mm`. Measure the physical arm and update whichever value is wrong before generating competition trajectories.

---

*Last updated: 2026-03-04*
*Maintainer: Team MOVIS — HERC-26*