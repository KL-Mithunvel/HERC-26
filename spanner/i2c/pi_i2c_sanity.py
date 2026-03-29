#!/usr/bin/env python3
"""
spanner/i2c/pi_i2c_sanity.py  —  HERC-26 I2C Sanity Check (Pi side)
======================================================================
Reads the 7-byte StatusPacket from the Arduino Mega at I2C address 0x08
and pretty-prints every field.

Works against EITHER sketch:
  • spanner/i2c/mega_sanity/mega_sanity.ino  — standalone wiring test
  • mega/rover_mega/rover_mega.ino            — live rover firmware check

Usage (run on Raspberry Pi only):
  # Live monitor — prints packet every 0.5 s until Ctrl+C
  python spanner/i2c/pi_i2c_sanity.py

  # Verify mode — steps through all 5 mega_sanity.ino states and checks each
  python spanner/i2c/pi_i2c_sanity.py --verify

  # Override address or bus if needed
  python spanner/i2c/pi_i2c_sanity.py --addr 0x08 --bus 1

Requirements:
  sudo apt install python3-smbus
  i2cdetect -y 1   # should show 0x08 before running this script
"""

import struct
import time
import sys
import argparse

# ── Packet format — matches rover_mega.ino StatusPacket layout ────────────────
#   "<"  = little-endian, no padding (all fields are 1 byte anyway)
#   4?   = tool_water, tool_air, tool_soil, ibus_pulse  (4 × bool)
#   B    = movement  (uint8: 0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
#   2?   = pump_running, failsafe  (2 × bool)
_FMT    = "<4?B2?"
_NBYTES = struct.calcsize(_FMT)   # 7

MEGA_ADDR = 0x08
I2C_BUS   = 1

_MOVEMENT = {0: "STOP ", 1: "FWD  ", 2: "BACK ", 3: "LEFT ", 4: "RIGHT"}

# ── Expected states for --verify mode ────────────────────────────────────────
# Must match STATES[] in mega_sanity.ino exactly.
EXPECTED_STATES = [
    dict(tool_water=False, tool_air=False, tool_soil=False,
         ibus_pulse=False, movement=0, pump_running=False, failsafe=True,
         label="STATE 0 | all OFF  | failsafe ON"),
    dict(tool_water=True,  tool_air=False, tool_soil=False,
         ibus_pulse=True,  movement=1, pump_running=False, failsafe=False,
         label="STATE 1 | water ON | FWD"),
    dict(tool_water=False, tool_air=True,  tool_soil=False,
         ibus_pulse=True,  movement=2, pump_running=False, failsafe=False,
         label="STATE 2 | air ON   | BACK"),
    dict(tool_water=False, tool_air=False, tool_soil=True,
         ibus_pulse=True,  movement=3, pump_running=True,  failsafe=False,
         label="STATE 3 | soil ON  | pump | LEFT"),
    dict(tool_water=True,  tool_air=True,  tool_soil=True,
         ibus_pulse=True,  movement=4, pump_running=True,  failsafe=False,
         label="STATE 4 | all ON   | pump | RIGHT"),
]


# ── I2C helpers ───────────────────────────────────────────────────────────────

def open_bus(bus_num: int):
    try:
        import smbus
        return smbus.SMBus(bus_num)
    except ImportError:
        sys.exit("smbus not found. Install with:  sudo apt install python3-smbus")
    except Exception as e:
        sys.exit(f"Cannot open I2C bus {bus_num}: {e}")


def read_packet(bus, addr: int) -> dict:
    raw = bus.read_i2c_block_data(addr, 0, _NBYTES)
    if len(raw) != _NBYTES:
        raise IOError(f"Expected {_NBYTES} bytes, got {len(raw)}")
    tw, ta, ts, ip, mv, pr, fs = struct.unpack(_FMT, bytes(raw))
    return {
        "tool_water":   bool(tw),
        "tool_air":     bool(ta),
        "tool_soil":    bool(ts),
        "ibus_pulse":   bool(ip),
        "movement":     int(mv),
        "pump_running": bool(pr),
        "failsafe":     bool(fs),
        "_raw":         list(raw),
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def _yn(v: bool) -> str:
    return "YES" if v else "no "

def _rc(v: bool) -> str:
    return "OK  " if v else "LOST"

def _mv(code: int) -> str:
    return _MOVEMENT.get(code, f"?({code})")

def _raw_hex(raw: list) -> str:
    return " ".join(f"{b:02X}" for b in raw)


# ── Live monitor ──────────────────────────────────────────────────────────────

def live_monitor(bus, addr: int) -> None:
    print("Live monitor — Ctrl+C to stop\n")
    header = (
        f"{'Poll':>6} │"
        f" {'water':5} {'air':5} {'soil':5} │"
        f" {'move':5} {'pump':5} │"
        f" {'RC':5} {'failsafe':9} │"
        f" raw bytes (hex)"
    )
    separator = "─" * len(header)
    print(header)
    print(separator)

    poll = 0
    while True:
        try:
            pkt = read_packet(bus, addr)
            poll += 1
            line = (
                f"{poll:>6} │"
                f" {_yn(pkt['tool_water']):5}"
                f" {_yn(pkt['tool_air']):5}"
                f" {_yn(pkt['tool_soil']):5} │"
                f" {_mv(pkt['movement']):5}"
                f" {_yn(pkt['pump_running']):5} │"
                f" {_rc(pkt['ibus_pulse']):5}"
                f" {'ACTIVE  ' if pkt['failsafe'] else 'off     ':9} │"
                f" [{_raw_hex(pkt['_raw'])}]"
            )
            print(line)
        except IOError as e:
            poll += 1
            print(f"{poll:>6} │ READ ERROR: {e}")
        time.sleep(0.5)


# ── Verify mode ───────────────────────────────────────────────────────────────

def verify_mode(bus, addr: int) -> None:
    """
    Steps through all 5 mega_sanity.ino states and checks each field.
    mega_sanity.ino cycles states every 2 s — timing is managed with prompts.
    """
    print("Verify mode")
    print("  Make sure mega_sanity.ino is running on the Mega.")
    print("  Open the Mega Serial monitor (115200 baud) to watch state changes.")
    print()
    input("Press ENTER when the Mega Serial shows '[0] STATE 0 ...' ...")
    print()

    passed = 0
    failed = 0

    for i, expected in enumerate(EXPECTED_STATES):
        print(f"Checking STATE {i}: {expected['label']}")
        time.sleep(0.4)   # let the I2C settle after state change

        try:
            pkt = read_packet(bus, addr)
        except IOError as e:
            print(f"  [FAIL] Read error: {e}\n")
            failed += 1
            if i < len(EXPECTED_STATES) - 1:
                input(f"  Fix the issue then press ENTER to continue to STATE {i + 1} ...")
                print()
            continue

        errors = []
        for field in ("tool_water", "tool_air", "tool_soil",
                      "ibus_pulse", "movement", "pump_running", "failsafe"):
            got      = pkt[field]
            expected_val = expected[field]
            if got != expected_val:
                errors.append(f"    {field:15s}: expected={expected_val!s:6}  got={got!s:6}")

        raw_str = _raw_hex(pkt["_raw"])
        if errors:
            print(f"  [FAIL]  raw=[{raw_str}]")
            for e in errors:
                print(e)
            failed += 1
        else:
            print(f"  [PASS]  raw=[{raw_str}]")
            passed += 1

        if i < len(EXPECTED_STATES) - 1:
            print(f"  Waiting 2 s for Mega to advance to STATE {i + 1} ...")
            print()
            time.sleep(2.2)

    print()
    print("=" * 50)
    print(f"Result: {passed} PASS / {failed} FAIL  ({len(EXPECTED_STATES)} total)")
    if failed == 0:
        print("ALL PASS — I2C wiring and packet format are correct.")
    else:
        print("FAILURES detected. See output above.")
        print("Common causes: byte order mismatch, missing GND, pull-up issues.")
    print("=" * 50)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HERC-26 I2C Sanity Check — Pi side"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Step through mega_sanity.ino states and verify each one"
    )
    parser.add_argument(
        "--addr", type=lambda x: int(x, 0), default=MEGA_ADDR,
        help=f"Mega I2C address (default {MEGA_ADDR:#x})"
    )
    parser.add_argument(
        "--bus", type=int, default=I2C_BUS,
        help=f"I2C bus number (default {I2C_BUS})"
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f" HERC-26 I2C Sanity  │  bus={args.bus}  addr={args.addr:#x}  packet={_NBYTES} bytes")
    print("=" * 60)

    bus = open_bus(args.bus)

    # Quick probe before doing anything
    try:
        pkt = read_packet(bus, args.addr)
        print(f"Mega responding — first read OK  raw=[{_raw_hex(pkt['_raw'])}]\n")
    except Exception as e:
        print(f"Mega NOT responding: {e}")
        print()
        print("Checklist:")
        print("  1. Is the Mega powered and sketch uploaded?")
        print("  2. Run:  i2cdetect -y 1  — does 0x08 appear?")
        print("  3. Check SDA/SCL wiring through the level shifter.")
        print("  4. Verify LV=3.3 V and HV=5 V sides are not swapped.")
        bus.close()
        sys.exit(1)

    try:
        if args.verify:
            verify_mode(bus, args.addr)
        else:
            live_monitor(bus, args.addr)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        bus.close()


if __name__ == "__main__":
    main()
