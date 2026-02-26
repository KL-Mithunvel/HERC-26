#!/usr/bin/env bash
# setup_pi.sh — One-shot Raspberry Pi setup for HERC-26
#
# Run from the project root after extracting the ZIP:
#   cd ~/HERC-26
#   chmod +x setup_pi.sh
#   ./setup_pi.sh
#
# IMPORTANT — two steps cannot be scripted and must be done MANUALLY first:
#   1. sudo raspi-config → Interface Options → enable I2C, SPI, Serial (no login shell, yes hardware)
#   2. sudo reboot        (after raspi-config, before running this script)
#
# A second reboot is triggered at the end of this script (for group membership).
# After that reboot the Pi is ready; verify with: python3 sensor/dev_stack.py

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================================================"
echo "  HERC-26 Pi Setup"
echo "  Project root: $PROJECT_ROOT"
echo "======================================================================"

# ── 1. APT packages ───────────────────────────────────────────────────────────
echo ""
echo "[1/4] Installing apt packages..."
sudo apt update
sudo apt install -y \
    git \
    curl \
    build-essential \
    swig \
    i2c-tools \
    python3-full \
    python3-dev \
    python3-libgpiod \
    python3-smbus \
    python3-serial \
    python3-tk

# ── 2. lgpio shim (Pi 5 Blinka compatibility) ─────────────────────────────────
# Adafruit Blinka imports `lgpio` at load time on Pi. The real lgpio does not
# support the Pi 5 RP1 GPIO chip. compat/lgpio.py is a shim backed by gpiod.
# We install it as a local wheel so pip tracks it (pip show / uninstall work).
# --break-system-packages is required on Pi OS (PEP 668); this is the ONE
# intentional pip call on system Python for this project.
echo ""
echo "[2/4] Installing lgpio shim (compat/ → site-packages)..."
pip install --break-system-packages "$PROJECT_ROOT/compat"

# Verify the shim landed correctly before continuing
python3 -c "import lgpio; print('  lgpio shim OK — version:', lgpio.get_module_version())"

# ── 3. User permissions ───────────────────────────────────────────────────────
echo ""
echo "[3/4] Adding $USER to hardware access groups..."
sudo usermod -aG gpio,i2c,spi,dialout "$USER"
echo "  Groups set — will take effect after reboot."

# ── 4. GPS venv (optional) ───────────────────────────────────────────────────
echo ""
echo "[4/4] GPS virtual environment (pynmea2)..."
if [[ "${SETUP_GPS:-no}" == "yes" ]]; then
    echo "  Creating gps_venv with --system-site-packages..."
    python3 -m venv --system-site-packages "$PROJECT_ROOT/gps_venv"
    "$PROJECT_ROOT/gps_venv/bin/pip" install pynmea2 pyserial smbus2
    echo "  GPS venv ready. Run GPS with: gps_venv/bin/python3 sensor/gps.py"
else
    echo "  Skipped (set SETUP_GPS=yes to enable)."
    echo "  GPS is not required — all other sensors work without it."
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================================"
echo "  Setup complete. Verify imports after reboot:"
echo ""
echo "    python3 - <<'EOF'"
echo "    for m in ['smbus','serial','gpiod','lgpio','sqlite3','tkinter']:"
echo "        try: __import__(m); print('OK:', m)"
echo "        except Exception as e: print('FAIL:', m, e)"
echo "    EOF"
echo ""
echo "  Then run: python3 main_sim.py    (dev/sim mode, no hardware needed)"
echo "        or: python3 main.py        (real hardware, Pi only)"
echo "======================================================================"
echo ""
echo "Rebooting in 5 seconds for group membership to take effect..."
echo "Press Ctrl+C to cancel the reboot and reboot manually later."
sleep 5
sudo reboot
