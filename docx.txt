#!/usr/bin/env bash
set -e

REPO_SSH="git@github.com:KL-Mithunvel/HERC-26.git"
REPO_DIR="$HOME/HERC-26"
EMAIL="klm@smtw.in"
NAME="KL-Mithunvel"

echo "== APT update/upgrade =="
sudo apt update
sudo apt full-upgrade -y

echo "== Install packages =="
sudo apt install -y \
  git curl wget vim tmux htop unzip zip \
  python3 python3-pip python3-venv python3-dev \
  build-essential cmake pkg-config \
  i2c-tools minicom screen

echo "== Optional: python3-lgpio (may not exist on some images) =="
sudo apt install -y python3-lgpio || true

echo "== Git config =="
git config --global user.name "$NAME"
git config --global user.email "$EMAIL"

echo "== SSH key (create if missing) =="
mkdir -p "$HOME/.ssh"
if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
  ssh-keygen -t ed25519 -C "$EMAIL" -f "$HOME/.ssh/id_ed25519" -N ""
fi

echo "== Start ssh-agent (only for this terminal session) =="
eval "$(ssh-agent -s)"
ssh-add "$HOME/.ssh/id_ed25519" >/dev/null

echo "== Your SSH public key (add this in GitHub -> Settings -> SSH keys) =="
echo "----------------------------------------"
cat "$HOME/.ssh/id_ed25519.pub"
echo "----------------------------------------"

echo "== Test GitHub SSH (expected to fail until key is added to GitHub) =="
ssh -o StrictHostKeyChecking=accept-new -T git@github.com || true

echo "== Clone repo (SSH) if missing =="
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "$REPO_SSH" "$REPO_DIR"
fi

echo "== Python venv =="
cd "$REPO_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

echo "== Activate venv and upgrade pip =="
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip

echo "== Done =="
echo "Next: cd ~/HERC-26 && source .venv/bin/activate"
