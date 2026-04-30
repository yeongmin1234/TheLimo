#!/usr/bin/env bash
set -euo pipefail

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
HTTPD_CONF_PATH="/etc/httpd/conf.d/00-thelimo-proxy.conf"

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

if systemctl is-enabled --quiet nginx 2>/dev/null || systemctl is-active --quiet nginx 2>/dev/null; then
  systemctl stop nginx 2>/dev/null || true
  systemctl disable nginx 2>/dev/null || true
fi

if [[ -f "$HTTPD_CONF_PATH" ]]; then
  cp "$HTTPD_CONF_PATH" "${HTTPD_CONF_PATH}.bak.$(date +%Y%m%d%H%M%S)"
fi

cat > "$HTTPD_CONF_PATH" <<EOF
<VirtualHost *:80>
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
systemctl restart httpd

if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --add-service=http --permanent
  firewall-cmd --reload
fi

echo
echo "Apache/httpd proxy installed: $HTTPD_CONF_PATH"
echo "App target: http://${APP_HOST}:${APP_PORT}"
echo "Try: curl http://127.0.0.1/ | head"
