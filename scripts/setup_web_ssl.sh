#!/usr/bin/env bash
set -u
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then echo "Domain is required" >&2; exit 1; fi

log() { echo "[dbot-ssl] $*"; }
fail() { echo "[dbot-ssl] ERROR: $*" >&2; exit 1; }

DOMAIN="$(echo "$DOMAIN" | sed -E 's#^https?://##; s#/.*$##; s/^[[:space:]]+|[[:space:]]+$//g')"
if ! echo "$DOMAIN" | grep -Eq '^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'; then
  fail "Invalid domain: $DOMAIN"
fi

run_apt() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -yq nginx certbot
  else
    fail "apt-get not found. Install nginx/certbot manually."
  fi
}

start_or_reload_nginx() {
  nginx -t || return 1
  if command -v systemctl >/dev/null 2>&1; then
    systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
  elif command -v service >/dev/null 2>&1; then
    service nginx reload 2>/dev/null || service nginx restart 2>/dev/null || true
  fi
  if ! pgrep -x nginx >/dev/null 2>&1; then
    nginx 2>/dev/null || true
  else
    nginx -s reload 2>/dev/null || true
  fi
}

if ! command -v nginx >/dev/null 2>&1 || ! command -v certbot >/dev/null 2>&1; then
  log "Installing nginx and certbot in non-interactive mode..."
  run_apt
fi

WEBROOT="/var/www/dbot-acme"
mkdir -p "$WEBROOT/.well-known/acme-challenge" /etc/nginx/sites-available /etc/nginx/sites-enabled
chmod -R 755 "$WEBROOT"

# Disable default nginx site so ACME challenge does not get intercepted by a different server block.
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

cat >/etc/nginx/sites-available/dbot-admin.conf <<NGINX
server {
    listen 80 default_server;
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/dbot-admin.conf /etc/nginx/sites-enabled/dbot-admin.conf
start_or_reload_nginx || fail "Nginx config/reload failed"

# Local challenge sanity check before asking Let's Encrypt.
TEST_FILE="dbot-test-$(date +%s).txt"
echo "ok" > "$WEBROOT/.well-known/acme-challenge/$TEST_FILE"
if command -v curl >/dev/null 2>&1; then
  LOCAL_TEST="$(curl -fsS --max-time 5 "http://127.0.0.1/.well-known/acme-challenge/$TEST_FILE" -H "Host: ${DOMAIN}" 2>/dev/null || true)"
  if [ "$LOCAL_TEST" != "ok" ]; then
    rm -f "$WEBROOT/.well-known/acme-challenge/$TEST_FILE"
    fail "Local ACME webroot test failed. Nginx is not serving /.well-known/acme-challenge correctly."
  fi
fi
rm -f "$WEBROOT/.well-known/acme-challenge/$TEST_FILE"

log "Requesting Let's Encrypt certificate for ${DOMAIN} with webroot challenge..."
certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --preferred-challenges http --keep-until-expiring
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  cat >&2 <<ERR
Certbot failed.
Check these items:
1) Domain A record must point to this VPS public IP.
2) Port 80 must be open from the internet.
3) Cloudflare proxy/CDN should be disabled while issuing SSL, or set to DNS only.
4) No other web server should answer /.well-known/acme-challenge/ for this domain.
Log file: /var/log/letsencrypt/letsencrypt.log
ERR
  exit "$STATUS"
fi

cat >/etc/nginx/sites-available/dbot-admin.conf <<NGINX
server {
    listen 80 default_server;
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
NGINX
start_or_reload_nginx || fail "Nginx final reload failed"
log "SSL is active for ${DOMAIN}."
