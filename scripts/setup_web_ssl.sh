#!/usr/bin/env bash
set -Eeuo pipefail

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

DOMAIN="${1:-}"
MODE="${2:-proxy}"
API_PORT="${API_PORT:-8000}"
NGINX_HTTP_PORT="${NGINX_HTTP_PORT:-80}"
NGINX_HTTPS_PORT="${NGINX_HTTPS_PORT:-443}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"

SITE_NAME="d-bot.conf"
SITE_AVAILABLE="/etc/nginx/sites-available/${SITE_NAME}"
SITE_ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}"
CONF_D_SITE="/etc/nginx/conf.d/${SITE_NAME}"
WEBROOT="/var/www/dbot-acme"
BOOTSTRAP_ROOT="/var/www/dbot-bootstrap"
BACKUP_ROOT="/etc/nginx/dbot-backups"

log() { echo "[dbot-ssl] $*"; }
warn() { echo "[dbot-ssl] WARNING: $*" >&2; }
fail() { echo "[dbot-ssl] ERROR: $*" >&2; exit 1; }

normalize_domain() {
  echo "$1" | sed -E 's#^https?://##; s#/.*$##; s/:.*$//; s/^[[:space:]]+|[[:space:]]+$//g'
}

valid_domain() {
  echo "$1" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'
}

valid_port() {
  echo "$1" | grep -Eq '^[0-9]+$' && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

install_requirements() {
  if command -v nginx >/dev/null 2>&1 && command -v certbot >/dev/null 2>&1; then
    return 0
  fi
  command -v apt-get >/dev/null 2>&1 || fail "Automatic Nginx/Certbot installation currently requires Ubuntu or Debian."
  log "Installing Nginx and Certbot..."
  apt-get update -y
  apt-get install -yq nginx certbot
}

open_firewall_ports() {
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    ufw allow 80/tcp >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    log "UFW rules for TCP 80 and 443 are present."
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
    firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    log "firewalld rules for HTTP and HTTPS are present."
  fi
}

check_dns() {
  local resolved resolved_v6 public_ip
  resolved="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | paste -sd, - || true)"
  [ -n "$resolved" ] || fail "The domain ${DOMAIN} does not currently resolve to an IPv4 address. Create its A record first."

  public_ip="$(curl --noproxy '*' -4fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  if [ -z "$public_ip" ]; then
    public_ip="$(curl --noproxy '*' -4fsS --max-time 8 https://ifconfig.me/ip 2>/dev/null || true)"
  fi

  log "Domain IPv4: ${resolved}"
  resolved_v6="$(getent ahostsv6 "$DOMAIN" 2>/dev/null | awk '{print $1}' | grep -vE '^::ffff:' | sort -u | paste -sd, - || true)"
  if [ -n "$resolved_v6" ]; then
    warn "The domain has a real AAAA record (${resolved_v6}). It must point to this VPS or be removed temporarily, otherwise Let's Encrypt may validate over IPv6."
  fi
  if [ -n "$public_ip" ]; then
    log "VPS public IPv4: ${public_ip}"
    if ! echo ",${resolved}," | grep -Fq ",${public_ip},"; then
      warn "The domain does not appear to point directly to this VPS. If Cloudflare is enabled, set the record to DNS only before continuing."
    fi
  else
    warn "Could not detect the VPS public IPv4 automatically; Certbot will perform the authoritative validation."
  fi
}

prepare_directories() {
  mkdir -p "$WEBROOT/.well-known/acme-challenge" "$BOOTSTRAP_ROOT" \
    /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d "$BACKUP_ROOT"
  chmod -R 755 "$WEBROOT" "$BOOTSTRAP_ROOT"
  rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
  rm -f /etc/nginx/sites-enabled/dbot-admin.conf 2>/dev/null || true
  rm -f /etc/nginx/sites-available/dbot-admin.conf 2>/dev/null || true
}

backup_conflicting_domain_configs() {
  local stamp backup_dir file found=0
  stamp="$(date +%Y%m%d-%H%M%S)"
  backup_dir="${BACKUP_ROOT}/${stamp}"

  while IFS= read -r file; do
    [ -n "$file" ] || continue
    case "$file" in
      "$SITE_AVAILABLE") continue ;;
    esac
    found=1
    mkdir -p "$backup_dir$(dirname "$file")"
    cp -aL "$file" "$backup_dir$file" 2>/dev/null || cp -a "$file" "$backup_dir$file" 2>/dev/null || true
    rm -f "$file"
    warn "Disabled conflicting Nginx config: ${file}"
  done < <(
    grep -RIlE --include='*.conf' --include='*' \
      "server_name[[:space:]]+([^;[:space:]]+[[:space:]]+)*${DOMAIN//./\\.}([[:space:]]+[^;]+)*;" \
      /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | sort -u || true
  )

  rm -f "$SITE_ENABLED" "$CONF_D_SITE" 2>/dev/null || true

  if [ "$found" -eq 1 ]; then
    log "Previous active configs for ${DOMAIN} were backed up under ${backup_dir}."
  fi
}

write_installation_page() {
  cat >"${BOOTSTRAP_ROOT}/index.html" <<HTML
<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>D Bot Installation</title>
  <style>
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b16;color:#f8fafc;font-family:Tahoma,Arial,sans-serif}.card{width:min(92%,620px);padding:42px;border:1px solid #25304a;border-radius:24px;background:linear-gradient(145deg,#10182b,#0a1020);box-shadow:0 24px 80px #0008;text-align:center}.mark{width:72px;height:72px;margin:0 auto 22px;border-radius:22px;display:grid;place-items:center;background:#7c3aed;font:700 38px Arial}.spin{width:28px;height:28px;margin:26px auto 0;border:3px solid #334155;border-top-color:#a78bfa;border-radius:50%;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(360deg)}}h1{font-size:26px;margin:0 0 14px}p{color:#aebbd0;line-height:2;margin:0}.domain{direction:ltr;color:#c4b5fd;margin-top:18px}
  </style>
</head>
<body><main class="card"><div class="mark">D</div><h1>نصب D Bot در حال انجام است</h1><p>دامنه و گواهی امنیتی با موفقیت فعال شده‌اند.<br>پس از پایان نصب، پنل مدیریت به‌صورت خودکار در همین آدرس باز می‌شود.</p><div class="domain">https://${DOMAIN}</div><div class="spin"></div></main></body>
</html>
HTML
}

activate_site_config() {
  rm -f "$SITE_ENABLED" "$CONF_D_SITE" 2>/dev/null || true
  ln -sf "$SITE_AVAILABLE" "$SITE_ENABLED"

  if ! nginx -T 2>&1 | grep -Fq "# configuration file ${SITE_ENABLED}:"; then
    rm -f "$SITE_ENABLED"
    ln -sf "$SITE_AVAILABLE" "$CONF_D_SITE"
    nginx -T 2>&1 | grep -Fq "# configuration file ${CONF_D_SITE}:" || \
      fail "Nginx does not load /etc/nginx/sites-enabled or /etc/nginx/conf.d. Check /etc/nginx/nginx.conf include directives."
    log "Activated D Bot config through /etc/nginx/conf.d."
  else
    log "Activated D Bot config through /etc/nginx/sites-enabled."
  fi
}

reload_nginx() {
  nginx -t || fail "Nginx configuration test failed."
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable nginx >/dev/null 2>&1 || true
    systemctl reload nginx 2>/dev/null || systemctl restart nginx
  else
    nginx -s reload 2>/dev/null || nginx
  fi
}

write_http_bootstrap_config() {
  cat >"$SITE_AVAILABLE" <<NGINX
server {
    listen ${NGINX_HTTP_PORT};
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    root ${BOOTSTRAP_ROOT};
    index index.html;
    location / { try_files \$uri /index.html; }
}
NGINX
  activate_site_config
  reload_nginx
}

local_acme_test() {
  local token body_file headers_file status body
  token="dbot-$(date +%s)-$$"
  body_file="$(mktemp)"
  headers_file="$(mktemp)"
  echo "ok" >"${WEBROOT}/.well-known/acme-challenge/${token}"

  status="$(curl --noproxy '*' -sS --max-time 7 \
    --resolve "${DOMAIN}:${NGINX_HTTP_PORT}:127.0.0.1" \
    -D "$headers_file" -o "$body_file" -w '%{http_code}' \
    "http://${DOMAIN}:${NGINX_HTTP_PORT}/.well-known/acme-challenge/${token}" 2>/dev/null || true)"
  body="$(cat "$body_file" 2>/dev/null || true)"

  rm -f "${WEBROOT}/.well-known/acme-challenge/${token}" "$body_file" "$headers_file"

  if [ "$status" = "200" ] && [ "$body" = "ok" ]; then
    log "Local ACME path test passed."
    return 0
  fi

  warn "Local ACME path test failed (HTTP ${status:-000}, body: ${body:0:120})."
  warn "Active listeners on port ${NGINX_HTTP_PORT}:"
  ss -ltnp 2>/dev/null | grep -E ":${NGINX_HTTP_PORT}([[:space:]]|$)" >&2 || true
  warn "Matching active Nginx server blocks:"
  nginx -T 2>/dev/null | grep -nE "server_name[[:space:]].*${DOMAIN//./\\.}|proxy_pass|\.well-known/acme-challenge" | tail -n 30 >&2 || true
  return 1
}

certificate_is_usable() {
  local cert="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  local key="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
  [ -s "$cert" ] && [ -s "$key" ] && openssl x509 -checkend 2592000 -noout -in "$cert" >/dev/null 2>&1
}

certbot_common_args() {
  CERT_ARGS=(-d "$DOMAIN" --non-interactive --agree-tos --preferred-challenges http --keep-until-expiring)
  if [ -n "$LETSENCRYPT_EMAIL" ]; then
    CERT_ARGS+=(-m "$LETSENCRYPT_EMAIL" --no-eff-email)
  else
    CERT_ARGS+=(--register-unsafely-without-email)
  fi
}

issue_certificate_webroot() {
  certbot_common_args
  log "Requesting/validating the Let's Encrypt certificate for ${DOMAIN} with Nginx webroot..."
  certbot certonly --webroot -w "$WEBROOT" "${CERT_ARGS[@]}"
}

issue_certificate_standalone() {
  local nginx_was_active=0
  certbot_common_args
  warn "Switching briefly to Certbot standalone validation because the local Nginx challenge test did not pass."

  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
    nginx_was_active=1
    systemctl stop nginx
  else
    nginx -s stop >/dev/null 2>&1 || true
  fi

  if ss -ltnp 2>/dev/null | grep -qE ":${NGINX_HTTP_PORT}([[:space:]]|$)"; then
    warn "Another process is still using TCP port ${NGINX_HTTP_PORT}:"
    ss -ltnp 2>/dev/null | grep -E ":${NGINX_HTTP_PORT}([[:space:]]|$)" >&2 || true
    [ "$nginx_was_active" -eq 1 ] && systemctl start nginx >/dev/null 2>&1 || true
    return 1
  fi

  if ! certbot certonly --standalone --http-01-port "$NGINX_HTTP_PORT" "${CERT_ARGS[@]}"; then
    [ "$nginx_was_active" -eq 1 ] && systemctl start nginx >/dev/null 2>&1 || true
    return 1
  fi

  [ "$nginx_was_active" -eq 1 ] && systemctl start nginx >/dev/null 2>&1 || true
  return 0
}

issue_certificate() {
  if certificate_is_usable; then
    log "A valid existing certificate for ${DOMAIN} was found; no new issuance is required."
  elif local_acme_test; then
    if ! issue_certificate_webroot; then
      warn "Webroot validation failed; trying standalone validation once."
      issue_certificate_standalone || certificate_failure_help
    fi
  else
    issue_certificate_standalone || certificate_failure_help
  fi

  [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ] || fail "Certbot finished but the certificate files were not found."
  if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now certbot.timer >/dev/null 2>&1 || true
  fi
}

certificate_failure_help() {
  cat >&2 <<ERR
[dbot-ssl] Certificate request failed.

Check all of the following, then run the installer again:
  1) The A record for ${DOMAIN} points to this VPS.
  2) TCP ports 80 and 443 are open in the VPS firewall and provider firewall.
  3) Cloudflare proxy is disabled (DNS only) while the certificate is issued.
  4) No Apache, Caddy, HAProxy, Docker container, or another service is occupying port 80.
  5) Any real AAAA record points to this VPS or is removed temporarily.
  6) Certbot details: /var/log/letsencrypt/letsencrypt.log
ERR
  fail "Unable to issue or validate the SSL certificate for ${DOMAIN}."
}

write_https_bootstrap_config() {
  cat >"$SITE_AVAILABLE" <<NGINX
server {
    listen ${NGINX_HTTP_PORT};
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen ${NGINX_HTTPS_PORT} ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    root ${BOOTSTRAP_ROOT};
    index index.html;
    location / { try_files \$uri /index.html; }
}
NGINX
  activate_site_config
  reload_nginx
}

write_proxy_config() {
  [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ] || fail "SSL certificate for ${DOMAIN} is missing. Run bootstrap mode first."
  valid_port "$API_PORT" || fail "Invalid API port: ${API_PORT}"

  backup_conflicting_domain_configs
  cat >"$SITE_AVAILABLE" <<NGINX
server {
    listen ${NGINX_HTTP_PORT};
    server_name ${DOMAIN};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
        try_files \$uri =404;
    }

    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen ${NGINX_HTTPS_PORT} ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;

    client_max_body_size 100m;

    location / {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 15s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
    }
}
NGINX
  activate_site_config
  reload_nginx
}

DOMAIN="$(normalize_domain "$DOMAIN")"
[ -n "$DOMAIN" ] || fail "Domain is required."
valid_domain "$DOMAIN" || fail "Invalid domain: ${DOMAIN}"
valid_port "$NGINX_HTTP_PORT" || fail "Invalid HTTP port: ${NGINX_HTTP_PORT}"
valid_port "$NGINX_HTTPS_PORT" || fail "Invalid HTTPS port: ${NGINX_HTTPS_PORT}"

install_requirements
open_firewall_ports
prepare_directories

case "$MODE" in
  bootstrap)
    [ "$NGINX_HTTP_PORT" = "80" ] && [ "$NGINX_HTTPS_PORT" = "443" ] || fail "Initial automatic SSL setup requires public Nginx ports 80 and 443."
    check_dns
    backup_conflicting_domain_configs
    write_installation_page
    write_http_bootstrap_config
    issue_certificate
    write_https_bootstrap_config
    log "HTTPS bootstrap page is active at https://${DOMAIN}"
    ;;
  proxy|final)
    write_proxy_config
    log "Nginx now proxies https://${DOMAIN} to D Bot API on 127.0.0.1:${API_PORT}."
    ;;
  *)
    fail "Unknown mode '${MODE}'. Use bootstrap or proxy."
    ;;
esac
