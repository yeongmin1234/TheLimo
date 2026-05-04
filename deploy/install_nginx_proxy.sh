#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_PORT="${PUBLIC_PORT:-8001}"
PUBLIC_PATH="${PUBLIC_PATH:-/delivery}"
NGINX_CONF_PATH="/etc/nginx/conf.d/thelimo-dashboard-${PUBLIC_PORT}.conf"

for port in "$APP_PORT" "$PUBLIC_PORT"; do
  case "$port" in
    80|8080)
      echo "Refusing to use protected SCM port: $port" >&2
      echo "SCM owns 80 and 8080 on 192.168.222.110. Use another port." >&2
      exit 1
      ;;
  esac
done

if ! command -v nginx >/dev/null 2>&1; then
  echo "nginx is not installed. Install it manually without changing SCM first." >&2
  exit 1
fi

if ! systemctl is-active --quiet nginx; then
  echo "nginx is not active. Refusing to start it automatically to avoid SCM impact." >&2
  exit 1
fi

cat > "$NGINX_CONF_PATH" <<EOF
server {
    listen ${PUBLIC_PORT};
    server_name _;

    location = ${PUBLIC_PATH} {
        return 301 ${PUBLIC_PATH}/;
    }

    location ${PUBLIC_PATH}/ {
        proxy_pass http://${APP_HOST}:${APP_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix ${PUBLIC_PATH};
        proxy_redirect off;
    }
}
EOF

nginx -t

systemctl reload nginx

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --add-port=${PUBLIC_PORT}/tcp --permanent
  firewall-cmd --reload
fi

echo
echo "Nginx proxy installed: $NGINX_CONF_PATH"
echo "App target: http://${APP_HOST}:${APP_PORT}"
echo "Public URL: http://SERVER_IP:${PUBLIC_PORT}${PUBLIC_PATH}/"
