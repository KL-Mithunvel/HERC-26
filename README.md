# HERC-26 — Raspberry Pi Setup Guide

Complete setup sequence for a fresh Raspberry Pi running Raspberry Pi OS (Bookworm or later).

---

## 1. Enable Hardware Interfaces

```bash
sudo raspi-config
```

Enable all of the following under **Interface Options**:

| Interface | Setting |
|---|---|
| I2C | Enable |
| SPI | Enable |
| Serial → Login shell | **NO** |
| Serial → Serial hardware | **YES** |

Then reboot:

```bash
sudo reboot
```

---

## 2. System Update

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 3. Wi-Fi Setup

```bash
sudo nmtui
```

Select **Activate a connection** and connect to your network.

---

## 4. Network Proxy (if required)

```bash
git config --global http.proxy  http://klm:TechnicHERC2026_@117.232.103.173:3128
git config --global https.proxy http://klm:TechnicHERC2026_@117.232.103.173:3128
```

---

## 5. GitHub Setup

Clone the repository:

```bash
git clone https://github.com/KL-Mithunvel/HERC-26.git
cd HERC-26
```

---

## 6. Enable Additional UARTs

The project uses multiple UART ports (GPS, CO2, RS485). Enable them by editing the boot config:

```bash
sudo nano /boot/firmware/config.txt
```

Add the following lines at the bottom (skip any already present):

```
enable_uart=1
dtoverlay=uart2
dtoverlay=uart3
dtoverlay=uart4
dtoverlay=uart5
```

What each line does:

| Line | UART | GPIO pins |
|---|---|---|
| `enable_uart=1` | UART0 (primary) | — |
| `dtoverlay=uart2` | UART2 | GPIO 0 / 1 |
| `dtoverlay=uart3` | UART3 | GPIO 4 / 5 |
| `dtoverlay=uart4` | UART4 | GPIO 8 / 9 |
| `dtoverlay=uart5` | UART5 | GPIO 12 / 13 |

Save and exit (`Ctrl+O` → `Enter` → `Ctrl+X`), then reboot:

```bash
sudo reboot
```

Verify UARTs are available after reboot:

```bash
ls /dev/ttyAMA*
```

Expected output:

```
/dev/ttyAMA0   /dev/ttyAMA2   /dev/ttyAMA3   /dev/ttyAMA4   /dev/ttyAMA5
```

---

## 7. Python Environment

```bash
cd HERC-26
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -r requirements.txt
bash setup_pi.sh
```

> `--system-site-packages` is required so the venv can access apt-installed libraries
> (`python3-libgpiod`, `python3-smbus`, etc.).

---

## 8. UART Port Assignments

| Device | Port | Notes |
|---|---|---|
| Arduino Mega | `/dev/ttyACM0` | USB serial |
| GPS (NEO-M8) | `/dev/ttyAMA3` | UART3 |
| CO2 (MH-Z19C) | `/dev/ttyAMA2` | UART2 |
| RS485 bus (PZEM-017 + S-pH-01) | `/dev/ttyAMA10` | Shared via MAX485 |

---

## 9. One-Time Sensor Configuration

### pH Sensor (S-pH-01) — Required Before First Run

The pH sensor ships with Modbus address 1 (same as the power meter) and 1 stop bit
(incompatible with the shared RS485 bus). Run this script once to fix both:

```bash
# With ONLY the pH sensor connected to the RS485 bus (disconnect PZEM-017 first)
python3 scripts/configure_ph_sensor.py
```

After it completes, reconnect the PZEM-017. Both sensors will be on the bus:

| Device | Modbus address | Serial config |
|---|---|---|
| PZEM-017 power meter | 1 | 9600 8N2 |
| S-pH-01 pH sensor | 2 | 9600 8N2 |

---

## 10. Running the System

```bash
# Raspberry Pi — real hardware
python main.py
# Dashboard: http://<pi-ip>:5000

# Laptop / development — simulated data
python main_sim.py
# Dashboard: http://127.0.0.1:5000
```

---

## 11. Individual Sensor Verification (Pi only)

Run any sensor driver directly to confirm the hardware is working:

```bash
python sensor/tmp.py          # TMP102 temperature
python sensor/gps.py          # GPS (NEO-M8)
python sensor/air.py          # MH-Z19C CO2
python sensor/imu.py          # BNO055 IMU
python sensor/soil.py         # ADS1115 soil moisture
python sensor/power_meter.py  # PZEM-017 power meter
python sensor/dev_stack.py    # Simulated stack (5-poll table)
```