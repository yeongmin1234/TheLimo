#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
NGINX_CONF_PATH="/etc/nginx/conf.d/thelimo.conf"

if ! command -v nginx >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y nginx
  elif command -v yum >/dev/null 2>&1; then
    yum install -y nginx
  else
    echo "Neither dnf nor yum is available. Install nginx manually first." >&2
    exit 1
  fi
fi

cat > "$NGINX_CONF_PATH" <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://${APP_HOST}:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

nginx -t

systemctl enable nginx
systemctl restart nginx

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --add-service=http --permanent
  firewall-cmd --reload
fi

echo
echo "Nginx proxy installed: $NGINX_CONF_PATH"
echo "App target: http://${APP_HOST}:${APP_PORT}"
echo "Try: curl http://127.0.0.1/ | head"
