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

# ── pip helper — respects venv vs system Python ───────────────────────────────
# Inside a venv: plain pip (PEP 668 does not apply).
# System Python: --break-system-packages required by Pi OS (PEP 668).
pip_install() {
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        pip install "$@"
    else
        pip install --break-system-packages "$@"
    fi
}

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo "  venv detected: $VIRTUAL_ENV"
else
    echo "  No venv — pip will use --break-system-packages"
fi

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
# Must be installed BEFORE requirements.txt so Blinka imports succeed.
echo ""
echo "[2/4] Installing lgpio shim (compat/ → site-packages)..."
pip_install "$PROJECT_ROOT/compat"
python3 -c "import lgpio; print('  lgpio shim OK — version:', lgpio.get_module_version())"

# ── 3. Python packages ────────────────────────────────────────────────────────
echo ""
echo "[3/4] Installing Python packages from requirements.txt..."
pip_install -r "$PROJECT_ROOT/requirements.txt"

# ── 4. User permissions ───────────────────────────────────────────────────────
echo ""
echo "[4/4] Adding $USER to hardware access groups..."
sudo usermod -aG gpio,i2c,spi,dialout "$USER"
echo "  Groups set — will take effect after reboot."

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================================"
echo "  Verifying imports..."
echo ""
python3 - <<'EOF'
for m in ["smbus", "serial", "gpiod", "lgpio", "sqlite3", "tkinter",
          "flask", "board", "busio"]:
    try:
        __import__(m)
        print(f"  OK:   {m}")
    except Exception as e:
        print(f"  FAIL: {m} — {e}")
EOF
echo ""
echo "  Then run: python3 main_sim.py    (dev/sim mode, no hardware needed)"
echo "        or: python3 main.py        (real hardware, Pi only)"
echo "======================================================================"
echo ""
echo "Rebooting in 5 seconds for group membership to take effect..."
echo "Press Ctrl+C to cancel the reboot and reboot manually later."
sleep 5
sudo reboot
