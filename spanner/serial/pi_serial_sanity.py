
#!/usr/bin/env python3
"""
spanner/serial/pi_serial_sanity.py  —  HERC-26 USB Serial Sanity Check (Pi side)
===============================================================================
Reads 9-byte framed status packets from the Arduino Mega over USB Serial
(/dev/ttyACM0, 115200 baud) and pretty-prints every field.

Works against EITHER sketch:
  • spanner/serial/mega_sanity/mega_sanity.ino  — standalone wiring test
  • mega/rover_mega/rover_mega.ino              — live rover firmware check

Frame format (9 bytes):
  byte 0: SYNC1  = 0xAA  \  two-byte magic header
  byte 1: SYNC2  = 0x55  /
  byte 2: tool_water    bool
  byte 3: tool_air      bool
  byte 4: tool_soil     bool
  byte 5: ibus_pulse    bool
  byte 6: movement      uint8  (0=STOP 1=FWD 2=BACK 3=LEFT 4=RIGHT)
  byte 7: pump_running  bool
  byte 8: failsafe      bool

Usage (run on Raspberry Pi only):
  # Live monitor — prints latest frame every 0.5 s until Ctrl+C
  python spanner/serial/pi_serial_sanity.py

  # Verify mode — steps through all 5 mega_sanity.ino states and checks each
  python spanner/serial/pi_serial_sanity.py --verify

  # Override port or baud if needed
  python spanner/serial/pi_serial_sanity.py --port /dev/ttyACM1 --baud 115200

Requirements:
  pip install pyserial      (or: sudo apt install python3-serial)
  ls /dev/ttyACM*           # should show ttyACM0 when Mega is connected via USB
"""

import struct
import time
import sys
import argparse

# ── Packet format — matches rover_mega.ino StatusPacket layout ────────────────
_SYNC1   = 0xAA
_SYNC2   = 0x55
_FMT     = "<4?B2?"
_NBYTES  = struct.calcsize(_FMT)   # 7 payload bytes
_MAX_SCAN = (_NBYTES + 2) * 20    # scan at most 20 frames worth before giving up

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200

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


# ── Serial helpers ────────────────────────────────────────────────────────────

def open_serial(port: str, baud: int):
    try:
        import serial
        ser = serial.Serial(port, baud, timeout=0.5)
        time.sleep(0.1)
        ser.reset_input_buffer()
        return ser
    except ImportError:
        sys.exit(
            "pyserial not found. Install with:\n"
            "  pip install pyserial\n"
            "  or: sudo apt install python3-serial"
        )
    except Exception as e:
        sys.exit(f"Cannot open {port} @ {baud}: {e}")


def _sync_and_read(ser) -> bytes:
    """
    Scan bytes until 0xAA 0x55 header is found, then return the 7 payload bytes.
    Raises IOError if no valid frame is found within _MAX_SCAN bytes.
    """
    for _ in range(_MAX_SCAN):
        b = ser.read(1)
        if not b:
            raise IOError("Serial timeout — no data from Mega")
        if b[0] != _SYNC1:
            continue
        b2 = ser.read(1)
        if not b2:
            raise IOError("Serial timeout after SYNC1")
        if b2[0] != _SYNC2:
            continue
        payload = ser.read(_NBYTES)
        if len(payload) != _NBYTES:
            raise IOError(f"Short payload: expected {_NBYTES} bytes, got {len(payload)}")
        return payload
    raise IOError(f"No valid frame found after scanning {_MAX_SCAN} bytes")


def read_packet(ser) -> dict:
    ser.reset_input_buffer()   # discard stale buffered frames — want freshest
    payload = _sync_and_read(ser)
    tw, ta, ts, ip, mv, pr, fs = struct.unpack(_FMT, bytes(payload))
    return {
        "tool_water":   bool(tw),
        "tool_air":     bool(ta),
        "tool_soil":    bool(ts),
        "ibus_pulse":   bool(ip),
        "movement":     int(mv),
        "pump_running": bool(pr),
        "failsafe":     bool(fs),
        "_raw":         list(payload),
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

def live_monitor(ser) -> None:
    print("Live monitor — Ctrl+C to stop\n")
    header = (
        f"{'Poll':>6} │"
        f" {'water':5} {'air':5} {'soil':5} │"
        f" {'move':5} {'pump':5} │"
        f" {'RC':5} {'failsafe':9} │"
        f" payload bytes (hex)"
    )
    separator = "─" * len(header)
    print(header)
    print(separator)

    poll = 0
    while True:
        try:
            pkt = read_packet(ser)
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

def verify_mode(ser) -> None:
    """
    Steps through all 5 mega_sanity.ino states automatically.
    mega_sanity.ino cycles states every 2 s — we wait 2.5 s between checks.
    No manual ENTER prompts needed.
    """
    print("Verify mode — checking all 5 states automatically.")
    print("Make sure mega_sanity.ino is running on the Mega.")
    print("The Mega Serial monitor (115200 baud) shows the current state label.")
    print()
    print("Waiting 2 s for Mega to settle on STATE 0 ...")
    time.sleep(2.0)
    print()

    passed = 0
    failed = 0

    for i, expected in enumerate(EXPECTED_STATES):
        print(f"Checking STATE {i}: {expected['label']}")
        time.sleep(0.3)   # let the serial settle after any state change

        try:
            pkt = read_packet(ser)
        except IOError as e:
            print(f"  [FAIL] Read error: {e}\n")
            failed += 1
            if i < len(EXPECTED_STATES) - 1:
                print(f"  Waiting 2.5 s for STATE {i + 1} ...")
                time.sleep(2.5)
            continue

        errors = []
        for field in ("tool_water", "tool_air", "tool_soil",
                      "ibus_pulse", "movement", "pump_running", "failsafe"):
            got          = pkt[field]
            expected_val = expected[field]
            if got != expected_val:
                errors.append(f"    {field:15s}: expected={expected_val!s:6}  got={got!s:6}")

        raw_str = _raw_hex(pkt["_raw"])
        if errors:
            print(f"  [FAIL]  payload=[{raw_str}]")
            for e in errors:
                print(e)
            failed += 1
        else:
            print(f"  [PASS]  payload=[{raw_str}]")
            passed += 1

        if i < len(EXPECTED_STATES) - 1:
            print(f"  Waiting 2.5 s for Mega to advance to STATE {i + 1} ...")
            print()
            time.sleep(2.5)

    print()
    print("=" * 50)
    print(f"Result: {passed} PASS / {failed} FAIL  ({len(EXPECTED_STATES)} total)")
    if failed == 0:
        print("ALL PASS — USB Serial wiring and packet format are correct.")
    else:
        print("FAILURES detected. See output above.")
        print("Common causes: byte order mismatch, wrong port, USB cable fault.")
    print("=" * 50)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HERC-26 USB Serial Sanity Check — Pi side"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Step through mega_sanity.ino states and verify each one automatically"
    )
    parser.add_argument(
        "--port", default=DEFAULT_PORT,
        help=f"Serial port (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--baud", type=int, default=DEFAULT_BAUD,
        help=f"Baud rate (default {DEFAULT_BAUD})"
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f" HERC-26 Serial Sanity  │  {args.port} @ {args.baud}  payload={_NBYTES} bytes")
    print("=" * 60)

    ser = open_serial(args.port, args.baud)

    # Quick probe before doing anything
    try:
        pkt = read_packet(ser)
        print(f"Mega responding — first read OK  payload=[{_raw_hex(pkt['_raw'])}]\n")
    except Exception as e:
        print(f"Mega NOT responding: {e}")
        print()
        print("Checklist:")
        print("  1. Is the Mega powered and sketch uploaded?")
        print(f"  2. Run:  ls /dev/ttyACM*  — does {args.port} appear?")
        print("  3. Check the USB cable between Mega and Pi.")
        print("  4. Make sure no other process has the port open (e.g. arduino-cli monitor).")
        ser.close()
        sys.exit(1)

    try:
        if args.verify:
            verify_mode(ser)
        else:
            live_monitor(ser)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
