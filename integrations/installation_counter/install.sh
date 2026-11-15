#!/usr/bin/env bash
# Install alongside D BOT using its existing host Nginx and Docker.
set -Eeuo pipefail
fail(){ echo "[dbot-counter] ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Run with sudo bash.'
DOMAIN="${1:-}"
EMAIL="${2:-}"
[[ -n "$DOMAIN" ]] || read -rp 'Counter subdomain (e.g. count.example.com): ' DOMAIN
DOMAIN="${DOMAIN,,}"
[[ ${#DOMAIN} -le 253 && "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || fail 'Enter a hostname only, without https:// or a path.'
[[ -n "$EMAIL" ]] || read -rp 'Email for TLS certificate renewal: ' EMAIL
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || fail 'Invalid email.'
for tool in docker nginx certbot curl python3; do command -v "$tool" >/dev/null || fail "Missing $tool. Install Docker, host Nginx, Certbot, curl and Python 3 first (D BOT already uses them)."; done
docker compose version >/dev/null || fail 'Docker Compose plugin is required.'
nginx -t || fail 'Fix the existing Nginx configuration first.'
# Do not change the bot site or take over an existing hostname.
SITE=/etc/nginx/conf.d/dbot-installation-counter.conf
if [[ -e "$SITE" ]] && ! grep -Fxq "# D BOT counter: $DOMAIN" "$SITE"; then
  fail 'This counter is already configured with another domain.'
fi
if nginx -T 2>/dev/null | python3 -c 'import re,sys; domain=sys.argv[1]; text=sys.stdin.read(); text=re.sub(r"#.*", "", text); sys.exit(0 if any(domain in names.split() for names in re.findall(r"\bserver_name\s+([^;]+);", text)) else 1)' "$DOMAIN"; then
  [[ -e "$SITE" ]] || fail 'That hostname already belongs to an Nginx site. Use a separate subdomain.'
fi
INSTALL=/opt/dbot-installation-counter
mkdir -p "$INSTALL" /var/www/dbot-counter-acme/.well-known/acme-challenge
chmod 755 /var/www/dbot-counter-acme
# Keep the counter independent of the main Compose project and its data.
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD=''
if [[ ! -f "$SOURCE/service.py" || ! -f "$SOURCE/Dockerfile" || ! -f "$SOURCE/compose.yml" ]]; then
  DOWNLOAD="$(mktemp -d)"
  trap 'rm -rf "$DOWNLOAD"' EXIT
  REF="${DBOT_COUNTER_REF:-main}"
  [[ "$REF" == main || "$REF" =~ ^[0-9a-f]{40}$ ]] || fail 'DBOT_COUNTER_REF must be main or a full commit SHA.'
  for file in service.py Dockerfile compose.yml; do
    curl --fail --silent --show-error --location --proto '=https' --max-time 60 "https://raw.githubusercontent.com/officialdarvish/D_bot/$REF/integrations/installation_counter/$file" -o "$DOWNLOAD/$file"
  done
  SOURCE="$DOWNLOAD"
fi
for file in service.py Dockerfile compose.yml; do
  [[ -f "$SOURCE/$file" ]] || fail "Missing $file; download/extract the counter package first."
  if [[ "$SOURCE" != "$INSTALL" ]]; then install -m 644 "$SOURCE/$file" "$INSTALL/$file"; fi
done
if [[ -n "$DOWNLOAD" ]]; then rm -rf "$DOWNLOAD"; trap - EXIT; fi
cd "$INSTALL"
docker compose -p dbot-installation-counter up -d --build --wait --wait-timeout 120
curl --fail --silent --show-error --retry 5 --retry-connrefused http://127.0.0.1:9080/health >/dev/null
BACKUP="$(mktemp)"
HAD_SITE=false
if [[ -e "$SITE" ]]; then cp "$SITE" "$BACKUP"; HAD_SITE=true; fi
COMMITTED=false
rollback(){
  if [[ "$COMMITTED" != true ]]; then
    if [[ "$HAD_SITE" == true ]]; then cp "$BACKUP" "$SITE"; else rm -f "$SITE"; fi
    nginx -t && systemctl reload nginx || true
  fi
  rm -f "$BACKUP"
}
trap rollback EXIT
cat > "$SITE" <<EOF
# D BOT counter: $DOMAIN
server {
    listen 80;
    server_name $DOMAIN;
    access_log off;
    location ^~ /.well-known/acme-challenge/ { root /var/www/dbot-counter-acme; }
    location / { return 404; }
}
EOF
nginx -t && systemctl reload nginx
certbot certonly --webroot -w /var/www/dbot-counter-acme -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --keep-until-expiring
cat > "$SITE" <<EOF
# D BOT counter: $DOMAIN
server {
    listen 80;
    server_name $DOMAIN;
    access_log off;
    location ^~ /.well-known/acme-challenge/ { root /var/www/dbot-counter-acme; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl;
    server_name $DOMAIN;
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log off;
    client_max_body_size 128;
    location / {
        proxy_pass http://127.0.0.1:9080;
        proxy_set_header Host \$host;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
    }
}
EOF
nginx -t && systemctl reload nginx
COMMITTED=true
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/dbot-counter-nginx.sh <<'HOOK'
#!/bin/sh
nginx -t && systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/dbot-counter-nginx.sh
curl --fail --silent --show-error --max-time 15 "https://$DOMAIN/health"
printf '\nCounter ready: https://%s\nPublic total: https://%s/count\nSend the counter URL to connect D BOT installations.\n' "$DOMAIN" "$DOMAIN"
