#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
PUBLIC_PORT="${PUBLIC_PORT:-8001}"
HTTPD_CONF_PATH="/etc/httpd/conf.d/thelimo-dashboard-${PUBLIC_PORT}.conf"

for port in "$APP_PORT" "$PUBLIC_PORT"; do
  case "$port" in
    80|8080)
      echo "Refusing to use protected SCM port: $port" >&2
      echo "SCM owns 80 and 8080 on 192.168.222.110. Use another port." >&2
      exit 1
      ;;
  esac
done

if ! command -v httpd >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y httpd
  elif command -v yum >/dev/null 2>&1; then
    yum install -y httpd
  else
    echo "Neither dnf nor yum is available. Install httpd manually first." >&2
    exit 1
  fi
fi

if [[ -f "$HTTPD_CONF_PATH" ]]; then
  cp "$HTTPD_CONF_PATH" "${HTTPD_CONF_PATH}.bak.$(date +%Y%m%d%H%M%S)"
fi

cat > "$HTTPD_CONF_PATH" <<EOF
Listen ${PUBLIC_PORT}

<VirtualHost *:${PUBLIC_PORT}>
    ServerName _

    ProxyPreserveHost On
    ProxyRequests Off

    ProxyPass / http://${APP_HOST}:${APP_PORT}/
    ProxyPassReverse / http://${APP_HOST}:${APP_PORT}/

    ErrorLog /var/log/httpd/thelimo_error.log
    CustomLog /var/log/httpd/thelimo_access.log combined
</VirtualHost>
EOF

if command -v setsebool >/dev/null 2>&1; then
  setsebool -P httpd_can_network_connect 1 || true
fi

httpd -t

systemctl enable httpd
systemctl reload httpd || systemctl restart httpd

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --add-port=${PUBLIC_PORT}/tcp --permanent
  firewall-cmd --reload
fi

echo
echo "Apache/httpd proxy installed: $HTTPD_CONF_PATH"
echo "App target: http://${APP_HOST}:${APP_PORT}"
echo "Public URL: http://SERVER_IP:${PUBLIC_PORT}/"
