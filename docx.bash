#!/usr/bin/env bash
set -e

REPO_SSH="git@github.com:KL-Mithunvel/HERC-26.git"
REPO_DIR="$HOME/HERC-26"
EMAIL="klm@smtw.in"
NAME="KL-Mithunvel"

echo "== APT update/upgrade =="
sudo apt update
sudo apt full-upgrade -y

echo "== Update system =="
sudo apt update

echo "== Install system packages =="
sudo apt install -y \
  git curl wget vim tmux htop unzip zip \
  build-essential cmake pkg-config swig \
  i2c-tools minicom screen \
  python3-full python3-pip python3-venv python3-dev \
  python3-smbus python3-serial python3-rpi.gpio python3-tk \
  liblgpio1

echo "== Optional: python3-lgpio (may not exist on some images) =="
sudo apt install -y python3-lgpio || true

echo "== Installation complete =="



ls ~/.ssh
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
ssh -T git@github.com
git clone git@github.com:KL-Mithunvel/HERC-26.git


cd HERC-26/
python3 -m venv .venv
source .venv/bin/activate
