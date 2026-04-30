#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/yeongmin1234/TheLimo.git}"
PROJECT_DIR="${1:-/root/TheLimo}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required. Install it first." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it first." >&2
  exit 1
fi

if [[ -d "$PROJECT_DIR/.git" ]]; then
  cd "$PROJECT_DIR"
  git pull origin main
else
  rm -rf "$PROJECT_DIR"
  git clone "$REPO_URL" "$PROJECT_DIR"
  cd "$PROJECT_DIR"
fi

python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

chmod +x deploy/install_limo_service.sh
bash deploy/install_limo_service.sh "$PROJECT_DIR"

echo
echo "Limo service is installed."
echo "Status: systemctl status limo"
echo "Logs: journalctl -u limo -f"
