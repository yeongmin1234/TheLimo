#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/배송예약_개발}"
SERVICE_PATH="/etc/systemd/system/limo.service"
SERVICE_TEMPLATE="$PROJECT_DIR/deploy/limo.service"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Project directory not found: $PROJECT_DIR" >&2
  exit 1
fi

if [[ ! -f "$SERVICE_TEMPLATE" ]]; then
  echo "Service template not found: $SERVICE_TEMPLATE" >&2
  exit 1
fi

if [[ -x "$PROJECT_DIR/venv/bin/uvicorn" ]]; then
  UVICORN_PATH="$PROJECT_DIR/venv/bin/uvicorn"
else
  UVICORN_PATH="$(command -v uvicorn || true)"
fi

if [[ -z "${UVICORN_PATH:-}" ]]; then
  echo "uvicorn not found. Install dependencies or create a venv first." >&2
  echo "Example: python3 -m venv venv && ./venv/bin/pip install fastapi uvicorn" >&2
  exit 1
fi

cd "$PROJECT_DIR"
cp deploy/limo.service "$SERVICE_PATH"
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" "$SERVICE_PATH"
sed -i "s|^ExecStart=.*|ExecStart=$UVICORN_PATH app.main:app --host 0.0.0.0 --port 8000|" "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable limo
systemctl restart limo
ls -l "$SERVICE_PATH"
systemctl status limo --no-pager

echo
echo "Service installed: $SERVICE_PATH"
echo "Logs: journalctl -u limo -f"
