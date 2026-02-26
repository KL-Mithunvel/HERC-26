"""
tests/test_validation.py
========================
Manual smoke-test for the validation state machine.

Run from the project root:
    python tests/test_validation.py

What it checks:
  1. Air tool — no waiting, valid_window opens immediately on trigger
  2. Soil tool — 10 s waiting phase before valid_window opens
  3. Water tool — 10 s waiting + 170 s stabilizing before valid_window
  4. All tools — valid_window lasts exactly 15 reads then closes (done)
  5. All tools — OFF edge immediately resets to "off"

The test fast-forwards time by injecting on_s values directly,
so you do NOT need to wait 3 minutes for it to finish.

Expected output:
  Every phase transition line should show [PASS].
  Final line should read RESULT: ALL CHECKS PASSED.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spanner.validation import _AIR, _SOIL, _WATER, compute_validation

VALID_SAMPLES = 15


def check(condition: bool, label: str) -> bool:
    result = "PASS" if condition else "FAIL"
    print(f"    [{result}] {label}")
    return condition


def step(rule, is_on: bool, on_s: float) -> dict:
    """Call rule.update() and return the result dict."""
    return rule.update(is_on, on_s)


def print_state(label: str, v: dict) -> None:
    print(f"      {label:30s}  phase={v['phase']:12s}  valid={str(v['valid_sample']):5s}"
          f"  samples_left={v['samples_left']:2d}  on_s={v['on_s']:.1f}s")


# ─────────────────────────────────────────────────────────────────────────────
# Air tool tests
# ─────────────────────────────────────────────────────────────────────────────

def test_air() -> bool:
    print("\n[AIR]  No wait — valid_window opens immediately on trigger")
    _AIR.reset()
    ok = True

    # OFF baseline
    v = step(_AIR, False, 0.0)
    ok &= check(v["phase"] == "off" and not v["valid_sample"], "OFF → phase=off")

    # First ON read — should immediately be valid_window
    v = step(_AIR, True, 0.0)
    print_state("on_s=0.0 (trigger)", v)
    ok &= check(v["phase"] == "valid_window",        "on_s=0.0 → phase=valid_window (no wait)")
    ok &= check(v["valid_sample"] is True,            "on_s=0.0 → valid_sample=True")
    ok &= check(v["samples_left"] == VALID_SAMPLES - 1, f"on_s=0.0 → samples_left={VALID_SAMPLES-1}")

    # Count through all valid reads
    for read_num in range(2, VALID_SAMPLES + 1):
        v = step(_AIR, True, read_num * 0.5)
        print_state(f"read #{read_num}", v)
        ok &= check(v["phase"] == "valid_window" and v["valid_sample"],
                    f"read #{read_num} still valid_window")

    # Read after valid window — should be done
    v = step(_AIR, True, (VALID_SAMPLES + 1) * 0.5)
    print_state(f"read #{VALID_SAMPLES + 1} (post-window)", v)
    ok &= check(v["phase"] == "done",               "post-window → phase=done")
    ok &= check(v["valid_sample"] is False,          "post-window → valid_sample=False")
    ok &= check(v["samples_left"] == 0,              "post-window → samples_left=0")

    # OFF reset
    v = step(_AIR, False, 0.0)
    ok &= check(v["phase"] == "off" and not v["valid_sample"], "OFF → resets to phase=off")

    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Soil tool tests
# ─────────────────────────────────────────────────────────────────────────────

def test_soil() -> bool:
    print("\n[SOIL]  wait_s=10s → valid_window → 15 reads")
    _SOIL.reset()
    ok = True

    # OFF baseline
    v = step(_SOIL, False, 0.0)
    ok &= check(v["phase"] == "off", "OFF → phase=off")

    # Still waiting at 5 s
    v = step(_SOIL, True, 5.0)
    print_state("on_s=5.0 (mid-wait)", v)
    ok &= check(v["phase"] == "waiting",             "on_s=5.0 → phase=waiting")
    ok &= check(v["valid_sample"] is False,           "on_s=5.0 → valid_sample=False")
    ok &= check(round(v["valid_in_s"], 0) == 5.0,    f"on_s=5.0 → valid_in_s≈5.0s (got {v['valid_in_s']})")

    # Still waiting at 9.9 s
    v = step(_SOIL, True, 9.9)
    print_state("on_s=9.9 (just before window)", v)
    ok &= check(v["phase"] == "waiting" and not v["valid_sample"], "on_s=9.9 → still waiting")

    # Valid window opens at 10.0 s
    v = step(_SOIL, True, 10.0)
    print_state("on_s=10.0 (window opens)", v)
    ok &= check(v["phase"] == "valid_window",         "on_s=10.0 → phase=valid_window")
    ok &= check(v["valid_sample"] is True,             "on_s=10.0 → valid_sample=True")
    ok &= check(v["samples_left"] == VALID_SAMPLES - 1,
                f"on_s=10.0 → samples_left={VALID_SAMPLES-1}")

    # Count remaining valid reads (read #2 through #15)
    for read_num in range(2, VALID_SAMPLES + 1):
        v = step(_SOIL, True, 10.0 + read_num * 0.5)
        ok &= check(v["phase"] == "valid_window" and v["valid_sample"],
                    f"read #{read_num} still in valid_window")
    print_state(f"read #{VALID_SAMPLES}", v)

    # After valid window
    v = step(_SOIL, True, 10.0 + (VALID_SAMPLES + 1) * 0.5)
    print_state(f"read #{VALID_SAMPLES + 1} (post-window)", v)
    ok &= check(v["phase"] == "done" and not v["valid_sample"], "post-window → done")

    # OFF reset
    v = step(_SOIL, False, 0.0)
    ok &= check(v["phase"] == "off", "OFF → resets to phase=off")

    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Water tool tests
# ─────────────────────────────────────────────────────────────────────────────

def test_water() -> bool:
    WAIT_S   = 10.0
    STAB_S   = 170.0
    WINDOW_S = WAIT_S + STAB_S   # = 180.0

    print(f"\n[WATER]  wait_s={WAIT_S}s → stabilizing {STAB_S}s → valid_window → 15 reads")
    _WATER.reset()
    ok = True

    # OFF baseline
    v = step(_WATER, False, 0.0)
    ok &= check(v["phase"] == "off", "OFF → phase=off")

    # During 10 s wait
    v = step(_WATER, True, 5.0)
    print_state("on_s=5.0 (waiting)", v)
    ok &= check(v["phase"] == "waiting" and not v["valid_sample"], "on_s=5.0 → waiting")

    # Just hit stabilizing (on_s=10.0)
    v = step(_WATER, True, 10.0)
    print_state("on_s=10.0 (stabilizing starts)", v)
    ok &= check(v["phase"] == "stabilizing" and not v["valid_sample"],
                "on_s=10.0 → stabilizing")

    # Mid-stabilize
    v = step(_WATER, True, 95.0)
    print_state("on_s=95.0 (mid-stabilize)", v)
    ok &= check(v["phase"] == "stabilizing" and not v["valid_sample"],
                "on_s=95.0 → still stabilizing")
    ok &= check(v["valid_in_s"] > 0, f"valid_in_s > 0 (got {v['valid_in_s']})")

    # Just before window
    v = step(_WATER, True, 179.9)
    print_state("on_s=179.9 (just before window)", v)
    ok &= check(v["phase"] == "stabilizing" and not v["valid_sample"],
                "on_s=179.9 → still stabilizing")

    # Valid window opens at 180.0 s
    v = step(_WATER, True, 180.0)
    print_state("on_s=180.0 (window opens)", v)
    ok &= check(v["phase"] == "valid_window",          "on_s=180.0 → valid_window")
    ok &= check(v["valid_sample"] is True,              "on_s=180.0 → valid_sample=True")
    ok &= check(v["samples_left"] == VALID_SAMPLES - 1,
                f"on_s=180.0 → samples_left={VALID_SAMPLES-1}")

    # Count remaining valid reads
    for read_num in range(2, VALID_SAMPLES + 1):
        v = step(_WATER, True, 180.0 + read_num * 0.5)
        ok &= check(v["phase"] == "valid_window" and v["valid_sample"],
                    f"read #{read_num} still in valid_window")
    print_state(f"read #{VALID_SAMPLES}", v)

    # Post window
    v = step(_WATER, True, 180.0 + (VALID_SAMPLES + 1) * 0.5)
    print_state(f"read #{VALID_SAMPLES + 1} (post-window)", v)
    ok &= check(v["phase"] == "done" and not v["valid_sample"], "post-window → done")

    # OFF reset
    v = step(_WATER, False, 0.0)
    ok &= check(v["phase"] == "off", "OFF → resets to phase=off")

    return ok


# ─────────────────────────────────────────────────────────────────────────────
# compute_validation() integration test
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_validation() -> bool:
    print("\n[compute_validation()]  integration check")
    ok = True

    # All off
    result = compute_validation(
        {"air": False, "water": False, "soil": False},
        {"air_s": 0.0,  "water_s": 0.0,  "soil_s": 0.0},
    )
    ok &= check(result["air"]["phase"]   == "off", "all off → air phase=off")
    ok &= check(result["soil"]["phase"]  == "off", "all off → soil phase=off")
    ok &= check(result["water"]["phase"] == "off", "all off → water phase=off")

    # Air on, past valid window
    result = compute_validation(
        {"air": True, "water": False, "soil": False},
        {"air_s": 5.0, "water_s": 0.0, "soil_s": 0.0},
    )
    ok &= check(result["air"]["valid_sample"] is True or
                result["air"]["phase"] in ("valid_window", "done"),
                "air on at 5s → in or past valid_window")

    # Soil waiting at 5 s
    result = compute_validation(
        {"air": False, "water": False, "soil": True},
        {"air_s": 0.0, "water_s": 0.0, "soil_s": 5.0},
    )
    ok &= check(result["soil"]["phase"] == "waiting",
                "soil on at 5s → waiting")
    ok &= check(not result["soil"]["valid_sample"],
                "soil on at 5s → not valid yet")

    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  HERC-26 validation.py  —  state machine smoke-test")
    print("="*60)

    results = {
        "Air"                : test_air(),
        "Soil"               : test_soil(),
        "Water"              : test_water(),
        "compute_validation" : test_compute_validation(),
    }

    print("\n" + "="*60)
    all_ok = all(results.values())
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
    print()
    if all_ok:
        print("  RESULT: ALL CHECKS PASSED")
    else:
        print("  RESULT: SOME CHECKS FAILED — see [FAIL] lines above")
    print("="*60 + "\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
