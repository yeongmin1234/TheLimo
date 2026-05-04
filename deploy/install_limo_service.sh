#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/TheLimo}"
SERVICE_PATH="/etc/systemd/system/limo.service"
SERVICE_TEMPLATE="$PROJECT_DIR/deploy/limo.service"
LIMO_PORT="${LIMO_PORT:-8000}"

case "$LIMO_PORT" in
  80|8080)
    echo "Refusing to use protected SCM port: $LIMO_PORT" >&2
    echo "Use a separate port such as 8000 or 8001." >&2
    exit 1
    ;;
esac

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
  echo "Example: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cd "$PROJECT_DIR"
cp deploy/limo.service "$SERVICE_PATH"
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|" "$SERVICE_PATH"
sed -i "s|^ExecStart=.*|ExecStart=$UVICORN_PATH app.main:app --host 0.0.0.0 --port $LIMO_PORT|" "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable limo
systemctl restart limo
ls -l "$SERVICE_PATH"
systemctl status limo --no-pager

echo
echo "Service installed: $SERVICE_PATH"
echo "App URL: http://SERVER_IP:${LIMO_PORT}/"
echo "Logs: journalctl -u limo -f"
