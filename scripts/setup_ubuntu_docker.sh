#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "[1/5] Updating apt indexes"
$SUDO apt update

echo "[2/5] Installing base packages"
$SUDO apt install -y ca-certificates curl gnupg git

echo "[3/5] Configuring Docker apt repository"
$SUDO install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
$SUDO chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "[4/5] Installing Docker Engine and Compose plugin"
$SUDO apt update
$SUDO apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[5/5] Verifying Docker"
$SUDO docker --version
$SUDO docker compose version

echo
echo "Docker installation completed."
echo "Next steps:"
echo "  git clone https://github.com/lioralo/Private_Clinic.git"
echo "  cd Private_Clinic"
echo "  cp .env.prod.example .env.prod"
