"""
lgpio compatibility shim for Raspberry Pi 5.

Adafruit Blinka imports lgpio at load time when it detects a Raspberry Pi.
The real lgpio library uses the /dev/mem / sysfs GPIO path, which does NOT
work on the Pi 5 RP1 chip. This shim exposes the same API surface that Blinka
uses, backed entirely by gpiod (libgpiod v2, installed via python3-libgpiod).

Only the symbols consumed by Blinka's lgpio_pin.py are implemented:
    gpiochip_open, gpio_claim_output, gpio_claim_input,
    gpio_write, gpio_read, gpio_free, error_text
    + module properties: exceptions, error

Install into the active Python environment so it shadows any real lgpio:
    pip install ./compat          (from the project root)

Requires: python3-libgpiod (apt) — provides the `gpiod` module.
"""

# ── gpiod import (guarded: must not crash on Windows dev machines) ────────────

try:
    import gpiod
    from gpiod.line import Direction, Value
    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False


# ── Module-level properties expected by Blinka ────────────────────────────────

# Blinka sets lgpio.exceptions = True before calling any GPIO function.
# Setting it here means any code that reads the flag sees True immediately.
exceptions: bool = True


class error(Exception):
    """Raised by shim functions on failure (mirrors lgpio.error)."""


OKAY: int = 0


# ── Internal state ────────────────────────────────────────────────────────────
#
# lgpio uses opaque integer handles for chips; lines are identified by
# (handle, pin). We map these onto gpiod objects:
#
#   _chips[(handle)]       → gpiod.Chip
#   _requests[(handle, pin)] → gpiod.LineRequest  (one request per pin)
#
# Keeping one request per pin matches lgpio's claim/free model and avoids
# having to batch-reconfigure multi-line requests when a single pin changes.

_chips: dict   = {}   # handle_id → gpiod.Chip
_requests: dict = {}  # (handle_id, pin) → gpiod.LineRequest
_next_handle: list = [0]  # mutable int (list avoids 'global' in nested scope)


# ── PLACEHOLDER: gpiod chip-path resolver ────────────────────────────────────
#
# lgpio uses integer chip numbers (0, 4, …); gpiod uses device paths.
# Right now we do the trivial mapping  N → /dev/gpiochipN, which is correct:
#   • Pi 4:  chip 0  →  /dev/gpiochip0
#   • Pi 5:  chip 0  →  /dev/gpiochip0  (pinctrl-rp1, confirmed via gpiodetect)
#
# PLACEHOLDER: if auto-detection is ever needed (e.g. probe available chips
# and pick the one with the right label), implement it here instead of the
# one-liner below.

def _chip_path(chip_number: int) -> str:
    return f"/dev/gpiochip{chip_number}"


# ── Public API (Blinka surface) ───────────────────────────────────────────────

def gpiochip_open(chip_number: int) -> int:
    """
    Open /dev/gpiochipN and return an opaque integer handle.
    Raises lgpio.error if gpiod is unavailable or the chip cannot be opened.
    """
    if not _GPIOD_AVAILABLE:
        raise error(
            "lgpio shim: gpiod not available — "
            "install python3-libgpiod via apt"
        )
    path = _chip_path(chip_number)
    try:
        chip = gpiod.Chip(path)
    except Exception as exc:
        raise error(f"gpiochip_open({chip_number}): {exc}") from exc

    handle = _next_handle[0]
    _next_handle[0] += 1
    _chips[handle] = chip
    return handle


def gpiochip_close(handle: int) -> int:
    """Release all lines claimed on this handle, then close the chip."""
    if handle not in _chips:
        return OKAY
    for key in [k for k in _requests if k[0] == handle]:
        _release_request(key)
    try:
        _chips[handle].close()
    except Exception:
        pass
    del _chips[handle]
    return OKAY


def gpio_claim_output(handle: int, lFlags: int, pin: int,
                      initial_value: int) -> int:
    """
    Claim a GPIO pin as output with an initial level.
    lFlags is accepted but ignored (pull-up/down not applicable to outputs).
    """
    _free_if_claimed(handle, pin)
    _assert_handle(handle, "gpio_claim_output")
    try:
        req = _chips[handle].request_lines(
            consumer="blinka-lgpio-shim",
            config={
                pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.ACTIVE if initial_value else Value.INACTIVE,
                )
            },
        )
        _requests[(handle, pin)] = req
    except Exception as exc:
        raise error(
            f"gpio_claim_output(handle={handle}, pin={pin}): {exc}"
        ) from exc
    return OKAY


def gpio_claim_input(handle: int, lFlags: int, pin: int) -> int:
    """
    Claim a GPIO pin as input.
    lFlags is accepted but ignored (Blinka passes 0 for plain input).

    # PLACEHOLDER: lFlags encodes pull-up/down bias in real lgpio.
    # Mapping to gpiod.line.Bias.PULL_UP / PULL_DOWN can be added here
    # if a sensor driver ever needs internal pull resistors via this shim.
    """
    _free_if_claimed(handle, pin)
    _assert_handle(handle, "gpio_claim_input")
    try:
        req = _chips[handle].request_lines(
            consumer="blinka-lgpio-shim",
            config={pin: gpiod.LineSettings(direction=Direction.INPUT)},
        )
        _requests[(handle, pin)] = req
    except Exception as exc:
        raise error(
            f"gpio_claim_input(handle={handle}, pin={pin}): {exc}"
        ) from exc
    return OKAY


def gpio_write(handle: int, pin: int, value: int) -> int:
    """Drive a claimed output pin HIGH (1) or LOW (0)."""
    req = _get_request(handle, pin, "gpio_write")
    try:
        req.set_value(pin, Value.ACTIVE if value else Value.INACTIVE)
    except Exception as exc:
        raise error(f"gpio_write(handle={handle}, pin={pin}): {exc}") from exc
    return OKAY


def gpio_read(handle: int, pin: int) -> int:
    """Read the current level of a claimed pin. Returns 0 or 1."""
    req = _get_request(handle, pin, "gpio_read")
    try:
        val = req.get_value(pin)
        return 1 if val == Value.ACTIVE else 0
    except Exception as exc:
        raise error(f"gpio_read(handle={handle}, pin={pin}): {exc}") from exc


def gpio_free(handle: int, pin: int) -> int:
    """Release a previously claimed pin."""
    _free_if_claimed(handle, pin)
    return OKAY


def error_text(error_code: int) -> str:
    """Convert an lgpio error code to a human-readable string."""
    # This shim only ever returns OKAY (0) from its own functions.
    # Negative codes are lgpio internal; we surface them as-is.
    return f"lgpio shim error code {error_code}"


# ── Stubs for symbols Blinka may check at import time ────────────────────────

def get_module_version() -> int:
    """Return a fake lgpio module version (shim always reports 0)."""
    return 0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _assert_handle(handle: int, caller: str) -> None:
    if handle not in _chips:
        raise error(f"{caller}: unknown handle {handle}")


def _get_request(handle: int, pin: int, caller: str):
    req = _requests.get((handle, pin))
    if req is None:
        raise error(f"{caller}: pin {pin} not claimed on handle {handle}")
    return req


def _free_if_claimed(handle: int, pin: int) -> None:
    """Release the existing request for (handle, pin) if one exists."""
    key = (handle, pin)
    if key in _requests:
        _release_request(key)


def _release_request(key: tuple) -> None:
    try:
        _requests[key].release()
    except Exception:
        pass
    del _requests[key]
