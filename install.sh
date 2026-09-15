#!/usr/bin/env bash
set -Eeuo pipefail

# D Bot one-click installer
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
# Optional:
#   REPO_URL="https://github.com/officialdarvish/D_bot.git" bash <(curl -fsSL .../install.sh)

APP_NAME="d-bot"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-${GITHUB_REPO_URL:-https://github.com/officialdarvish/D_bot.git}}"
BRANCH="${BRANCH:-${GITHUB_BRANCH:-main}}"
INSTALLER_ASSET_BASE_URL="${INSTALLER_ASSET_BASE_URL:-https://raw.githubusercontent.com/officialdarvish/D_bot/${BRANCH}}"
COMPOSE=""


GREEN='\033[1;32m'; BLUE='\033[1;34m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'
ok(){ echo -e "${GREEN}✅ $1${NC}"; }
info(){ echo -e "${BLUE}ℹ️  $1${NC}"; }
warn(){ echo -e "${YELLOW}⚠️  $1${NC}"; }
fail(){ echo -e "${RED}❌ $1${NC}"; exit 1; }

need_root(){
  [ "${EUID}" -eq 0 ] || fail "Please run as root. Use: sudo -i"
}

banner(){
  clear || true
  echo "================================================"
  echo "        D Bot Auto Installer         "
  echo "================================================"
  echo
}

install_base_packages(){
  info "Updating VPS and installing required packages..."
  export DEBIAN_FRONTEND=noninteractive

  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get upgrade -y
    apt-get install -y ca-certificates curl gnupg lsb-release git unzip openssl rsync nano python3 python3-pip nginx certbot python3-certbot-nginx
  elif command -v dnf >/dev/null 2>&1; then
    dnf update -y
    dnf install -y ca-certificates curl git unzip openssl rsync nano python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum update -y
    yum install -y ca-certificates curl git unzip openssl rsync nano python3 python3-pip
  else
    fail "Unsupported OS. Ubuntu/Debian is recommended."
  fi

  ok "System packages are ready."
}

install_docker(){
  if command -v docker >/dev/null 2>&1; then
    ok "Docker is already installed."
  else
    info "Installing Docker..."
    if command -v apt-get >/dev/null 2>&1; then
      install -m 0755 -d /etc/apt/keyrings
      . /etc/os-release
      curl -fsSL "https://download.docker.com/linux/${ID}/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      chmod a+r /etc/apt/keyrings/docker.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
      apt-get update -y
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
      curl -fsSL https://get.docker.com | sh
    fi
  fi

  systemctl enable docker >/dev/null 2>&1 || true
  systemctl restart docker || systemctl start docker || true

  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    fail "Docker Compose is not installed."
  fi

  ok "Docker and Compose are ready."
}

ask_required(){
  local prompt="$1" value=""
  while [ -z "$value" ]; do
    read -r -p "$prompt" value
  done
  echo "$value"
}

ask_optional(){
  local prompt="$1" value=""
  read -r -p "$prompt" value || true
  echo "$value"
}

ask_secret(){
  local prompt="$1" value=""
  while [ -z "$value" ]; do
    read -r -s -p "$prompt" value
    echo >&2
  done
  echo "$value"
}

ask_default(){
  local prompt="$1" default="$2" value=""
  read -r -p "$prompt [$default]: " value || true
  echo "${value:-$default}"
}

ask_secret_default(){
  local prompt="$1" default="$2" value=""
  read -r -s -p "$prompt [auto-generated, press Enter to use]: " value
  echo >&2
  echo "${value:-$default}"
}

ask_yes_no(){
  local prompt="$1" default="${2:-y}" value=""
  local hint="Y/n"
  [ "$default" = "n" ] && hint="y/N"
  while true; do
    read -r -p "$prompt [$hint]: " value || true
    value="${value:-$default}"
    case "$value" in
      y|Y|yes|YES) echo "true"; return 0 ;;
      n|N|no|NO) echo "false"; return 0 ;;
      *) warn "Please answer y or n." ;;
    esac
  done
}

generate_password(){
  openssl rand -base64 32 | tr -d '/+=' | cut -c1-24
}

generate_fernet_key(){
  python3 - <<'PYKEY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PYKEY
}

normalize_domain(){
  local raw="$1"
  raw="${raw#http://}"
  raw="${raw#https://}"
  raw="${raw%%/*}"
  raw="${raw%%:*}"
  echo "$raw"
}

valid_domain(){
  local d="$1"
  [[ "$d" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

valid_port(){
  local p="$1"
  [[ "$p" =~ ^[0-9]+$ ]] && [ "$p" -ge 1 ] && [ "$p" -le 65535 ]
}

valid_ids(){
  local ids="$1"
  [[ "$ids" =~ ^[0-9]+([,[:space:]]*[0-9]+)*$ ]]
}

valid_bot_token(){
  local token="$1"
  [[ "$token" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{20,}$ ]]
}

valid_email(){
  local email="$1"
  [[ "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]
}

setup_header(){
  clear || true
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║                    D Bot Setup Wizard                       ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║ Fill the required values step by step.                      ║"
  echo "║ Secrets will be saved only inside /opt/d-bot/.env.          ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo
}

setup_step(){
  echo
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE} Step $1/${SETUP_TOTAL_STEPS:-5} — $2${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

domain_first_wizard(){
  setup_header
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE} First stage — Domain & SSL${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo "The domain is requested before Telegram and all other project settings."
  echo "Nginx will immediately publish a temporary installation page and obtain SSL."
  echo

  while true; do
    DOMAIN_NAME="$(ask_required 'Domain name, example panel.example.com: ')"
    DOMAIN_NAME="$(normalize_domain "$DOMAIN_NAME")"
    valid_domain "$DOMAIN_NAME" && break
    warn "Invalid domain. Enter only the domain, for example: panel.example.com"
  done

  while true; do
    LETSENCRYPT_EMAIL="$(ask_optional 'Let’s Encrypt email, optional: ')"
    [ -z "$LETSENCRYPT_EMAIL" ] && break
    valid_email "$LETSENCRYPT_EMAIL" && break
    warn "Invalid email format. Leave it empty or enter a valid address."
  done
  ENABLE_HTTPS="true"
  NGINX_HTTP_PORT="80"
  NGINX_HTTPS_PORT="443"

  echo
  echo "Before continuing, make sure:"
  echo "  • The domain A record points to this VPS."
  echo "  • Public TCP ports 80 and 443 are open."
  echo "  • If Cloudflare is used, the record is temporarily set to DNS only."
  echo
  DOMAIN_CONFIRM="$(ask_yes_no "Start Nginx and request SSL for ${DOMAIN_NAME} now?" 'y')"
  if [ "$DOMAIN_CONFIRM" != "true" ]; then
    warn "Installation cancelled before any project configuration was collected."
    exit 0
  fi
}

bootstrap_domain_ssl(){
  [ -f "${APP_DIR}/scripts/setup_web_ssl.sh" ] || fail "Missing scripts/setup_web_ssl.sh"
  chmod 755 "${APP_DIR}/scripts/setup_web_ssl.sh"
  info "Starting Nginx and obtaining SSL before Telegram setup..."
  DOMAIN_NAME="$DOMAIN_NAME" \
  LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL" \
  NGINX_HTTP_PORT="$NGINX_HTTP_PORT" \
  NGINX_HTTPS_PORT="$NGINX_HTTPS_PORT" \
    bash "${APP_DIR}/scripts/setup_web_ssl.sh" "$DOMAIN_NAME" bootstrap
  ok "Domain and SSL are ready: https://${DOMAIN_NAME}"
  echo "A temporary installation page will remain online until the D Bot API is healthy."
}

setup_wizard(){
  SETUP_TOTAL_STEPS=5
  setup_header
  echo -e "${GREEN}✓ Domain and HTTPS are already active: https://${DOMAIN_NAME}${NC}"
  echo "Now complete Telegram and the remaining project settings."
  echo
  read -r -p "Press Enter to continue..." _

  setup_step 1 "Telegram Bot"
  echo "The Telegram Bot Token is visible while typing so you can verify it before saving."
  while true; do
    BOT_TOKEN="$(ask_required 'Telegram Bot Token: ')"
    valid_bot_token "$BOT_TOKEN" && break
    warn "Token format looks invalid. Example: 123456789:AAExample_Token-Value"
  done
  while true; do
    ADMIN_IDS="$(ask_required 'Owner/Admin Telegram ID, comma separated if more than one: ')"
    ADMIN_IDS="$(echo "$ADMIN_IDS" | tr -d ' ')"
    valid_ids "$ADMIN_IDS" && break
    warn "Admin IDs must be numeric. Example: 123456789 or 123456789,987654321"
  done

  setup_step 2 "Web Admin Panel"
  AUTO_WEB_ADMIN="$(ask_yes_no 'Auto-generate web admin username/password?' 'y')"
  if [ "$AUTO_WEB_ADMIN" = "true" ]; then
    WEB_ADMIN_USERNAME="admin_$(openssl rand -hex 3)"
    WEB_ADMIN_PASSWORD="$(generate_password)"
  else
    WEB_ADMIN_USERNAME="$(ask_default 'Web admin username' 'admin')"
    WEB_ADMIN_PASSWORD="$(ask_secret_default 'Web admin password' "$(generate_password)")"
  fi

  setup_step 3 "Database"
  POSTGRES_DB="$(ask_default 'PostgreSQL database name' 'd_bot')"
  POSTGRES_USER="$(ask_default 'PostgreSQL username' 'dbot')"
  POSTGRES_PASSWORD="$(ask_secret_default 'PostgreSQL password' "$(generate_password)")"

  setup_step 4 "Runtime Settings"
  while true; do
    API_PORT="$(ask_default 'Internal API port' '8000')"
    valid_port "$API_PORT" && break
    warn "Port must be between 1 and 65535."
  done
  TZ_VALUE="$(ask_default 'Timezone' 'Asia/Tehran')"
  CHANNEL_URL="$(ask_optional 'Default Telegram channel URL, optional: ')"

  POSTGRES_HOST="db"
  POSTGRES_PORT="5432"
  REDIS_HOST="redis"
  REDIS_PORT="6379"
  REDIS_DB="0"
  API_HOST="0.0.0.0"
  SERVER_SYNC_SECONDS="5"
  FERNET_KEY="$(generate_fernet_key)"
  JWT_SECRET="$(generate_password)$(generate_password)"

  setup_step 5 "Review"
  echo "Project path       : ${APP_DIR}"
  echo "Repository         : ${REPO_URL}"
  echo "Branch             : ${BRANCH}"
  echo "Domain             : ${DOMAIN_NAME}"
  echo "SSL certificate    : active"
  echo "Admin Telegram IDs : ${ADMIN_IDS}"
  echo "Web login          : https://${DOMAIN_NAME}/login"
  echo "Web username       : ${WEB_ADMIN_USERNAME}"
  echo "Database           : ${POSTGRES_DB}"
  echo "Database user      : ${POSTGRES_USER}"
  echo "Internal API port  : ${API_PORT}"
  echo "Nginx HTTP port    : ${NGINX_HTTP_PORT}"
  echo "Nginx HTTPS port   : ${NGINX_HTTPS_PORT}"
  echo "Timezone           : ${TZ_VALUE}"
  echo "Channel URL        : ${CHANNEL_URL:-not set}"
  echo
  CONFIRM_SETUP="$(ask_yes_no 'Save this setup and continue installation?' 'y')"
  if [ "$CONFIRM_SETUP" != "true" ]; then
    warn "Setup cancelled. The HTTPS installation page remains active; rerun the installer to finish."
    exit 0
  fi
}

write_config_env(){
  cat > "${APP_DIR}/.env" <<EOFENV
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
OWNER_IDS=${ADMIN_IDS}
SELLER_IDS=
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}
REDIS_URL=redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}
API_HOST=${API_HOST}
API_PORT=${API_PORT}
NGINX_HTTP_PORT=${NGINX_HTTP_PORT}
NGINX_HTTPS_PORT=${NGINX_HTTPS_PORT}
FERNET_KEY=${FERNET_KEY}
JWT_SECRET=${JWT_SECRET}
DEFAULT_CHANNEL_URL=${CHANNEL_URL}
TZ=${TZ_VALUE}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_HOST=${POSTGRES_HOST}
POSTGRES_PORT=${POSTGRES_PORT}
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}
REDIS_DB=${REDIS_DB}
SERVER_SYNC_SECONDS=${SERVER_SYNC_SECONDS}
DOMAIN_NAME=${DOMAIN_NAME}
ENABLE_HTTPS=${ENABLE_HTTPS}
LETSENCRYPT_EMAIL=${LETSENCRYPT_EMAIL}
WEB_ADMIN_USERNAME=${WEB_ADMIN_USERNAME}
WEB_ADMIN_PASSWORD=${WEB_ADMIN_PASSWORD}
NOWPAYMENTS_ENABLED=false
NOWPAYMENTS_API_KEY=
NOWPAYMENTS_IPN_SECRET=
NOWPAYMENTS_PAY_CURRENCY=trx
NOWPAYMENTS_PRICE_CURRENCY=usd
NOWPAYMENTS_API_URL=https://api.nowpayments.io/v1
NOWPAYMENTS_IPN_CALLBACK_URL=
XUI_VERIFY_TLS=true
XUI_CA_BUNDLE=
BACKUP_REQUIRE_SIGNATURE=true
BACKUP_SIGNING_SECRET=
DBOT_ALLOW_DOCKER_RESTART=false
EOFENV
  chmod 600 "${APP_DIR}/.env"

  ok ".env created successfully."
  echo
  echo "================================================"
  echo "D Bot configuration summary"
  echo "================================================"
  echo "Telegram Bot Token : [saved in .env]"
  echo "Admin Telegram IDs : ${ADMIN_IDS}"
  echo "Website Domain     : ${DOMAIN_NAME}"
  echo "HTTPS Enabled      : ${ENABLE_HTTPS}"
  echo "Web Admin Login    : https://${DOMAIN_NAME}/login"
  echo "Web Admin Username : ${WEB_ADMIN_USERNAME}"
  echo "Web Admin Password : ${WEB_ADMIN_PASSWORD}"
  echo "Database Name      : ${POSTGRES_DB}"
  echo "Database User      : ${POSTGRES_USER}"
  echo "Database Password  : [saved in .env]"
  echo "Database Host      : ${POSTGRES_HOST}"
  echo "Database Port      : ${POSTGRES_PORT}"
  echo "Redis URL          : redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
  echo "Internal API Port : ${API_PORT}"
  echo "Nginx HTTP Port   : ${NGINX_HTTP_PORT}"
  echo "Nginx HTTPS Port  : ${NGINX_HTTPS_PORT}"
  echo "Fernet Key         : [saved in .env]"
  echo "JWT Secret         : [saved in .env]"
  echo "================================================"
  echo
}

ensure_runtime_scripts(){
  local scripts_dir="${APP_DIR}/scripts"
  local ssl_script="${scripts_dir}/setup_web_ssl.sh"
  local control_script="${scripts_dir}/dbot-control.sh"

  mkdir -p "$scripts_dir"

  # GitHub web uploads commonly store shell files as mode 100644. The installer
  # executes them through bash, so existence matters; restore executable bits
  # locally for direct/manual use as well.
  if [ ! -f "$ssl_script" ]; then
    warn "setup_web_ssl.sh was not present in the cloned project; downloading the installer asset..."
    if ! curl -fsSL --retry 3 --connect-timeout 10 \
      "${INSTALLER_ASSET_BASE_URL}/scripts/setup_web_ssl.sh" -o "${ssl_script}.tmp"; then
      rm -f "${ssl_script}.tmp"
      fail "Could not obtain scripts/setup_web_ssl.sh. Make sure the full scripts/ directory is committed to ${REPO_URL}."
    fi
    mv "${ssl_script}.tmp" "$ssl_script"
  fi

  [ -s "$ssl_script" ] || fail "scripts/setup_web_ssl.sh exists but is empty."
  head -n 1 "$ssl_script" | grep -q '^#!/usr/bin/env bash' || fail "scripts/setup_web_ssl.sh is not a valid D Bot shell script."
  chmod 755 "$ssl_script"

  if [ -f "$control_script" ]; then
    chmod 755 "$control_script"
  fi
  if [ -f "${scripts_dir}/dbot-launcher.sh" ]; then
    chmod 755 "${scripts_dir}/dbot-launcher.sh"
  fi
  if [ -f "${scripts_dir}/repair-dbot-cli.sh" ]; then
    chmod 755 "${scripts_dir}/repair-dbot-cli.sh"
  fi
  if [ -f "${APP_DIR}/install.sh" ]; then
    chmod 755 "${APP_DIR}/install.sh"
  fi

  ok "Installer scripts are present and executable."
}

get_project(){
  if [ -d "${OLD_APP_DIR:-}" ] && [ "$OLD_APP_DIR" != "$APP_DIR" ]; then
  warn "Removing old install path: ${OLD_APP_DIR}"
  rm -rf "$OLD_APP_DIR"
fi

info "Preparing install path: ${APP_DIR}"
  mkdir -p "$APP_DIR"

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd || echo /tmp)"

  # Manual ZIP install: run install.sh from extracted project folder.
  if [ -f "${script_dir}/docker-compose.yml" ] && [ -d "${script_dir}/app" ]; then
    info "Local project files detected. Copying files..."
    if [ "$script_dir" != "$APP_DIR" ]; then
      rsync -a --delete --exclude '.git' --exclude '.env' --exclude 'postgres_data' --exclude 'backups' "${script_dir}/" "${APP_DIR}/"
    fi
  else
    # D Bot-like remote install: clone repo automatically.
    info "Downloading project from: ${REPO_URL}"
    if [ -d "${APP_DIR}/.git" ]; then
      git -C "$APP_DIR" fetch origin "$BRANCH"
      git -C "$APP_DIR" reset --hard "origin/${BRANCH}"
    else
      rm -rf "${APP_DIR:?}/"*
      git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    fi
  fi

  cd "$APP_DIR"
  [ -f docker-compose.yml ] || fail "docker-compose.yml was not found in ${APP_DIR}. Check REPO_URL or upload the full project."
  [ -f Dockerfile ] || fail "Dockerfile was not found in ${APP_DIR}."
  [ -d app ] || fail "app/ directory was not found in ${APP_DIR}."
  ensure_runtime_scripts
  ok "Project files are ready."
}

patch_compose(){
  cd "$APP_DIR"
  python3 - <<'PY'
from pathlib import Path
p = Path('docker-compose.yml')
s = p.read_text()

# Make PostgreSQL service use the same values generated inside .env.
s = s.replace('POSTGRES_DB: d_bot', 'POSTGRES_DB: ${POSTGRES_DB:-d_bot}')
s = s.replace('POSTGRES_USER: dbot', 'POSTGRES_USER: ${POSTGRES_USER:-dbot}')
s = s.replace('POSTGRES_PASSWORD: dbot', 'POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dbot}')

# Make host API port configurable from .env, while keeping container port 8000.
s = s.replace('"8000:8000"', '"${API_PORT:-8000}:8000"')
s = s.replace('- "8000:8000"', '- "${API_PORT:-8000}:8000"')
s = s.replace('8000:8000', '${API_PORT:-8000}:8000')

p.write_text(s)
PY
}
create_manager_command(){
  local repair="$APP_DIR/scripts/repair-dbot-cli.sh"
  local launcher="$APP_DIR/scripts/dbot-launcher.sh"
  local control="$APP_DIR/scripts/dbot-control.sh"

  if [ -f "$repair" ]; then
    chmod 755 "$repair"
    DBOT_APP_DIR="$APP_DIR" bash "$repair"
    ok "Manager command installed: dbot (live project symlink)"
    return 0
  fi

  local target=""
  if [ -f "$launcher" ]; then
    target="$launcher"
  elif [ -f "$control" ]; then
    target="$control"
  else
    fail "Cannot install dbot command: missing scripts/dbot-launcher.sh and scripts/dbot-control.sh"
  fi
  chmod 755 "$target"
  rm -f /usr/local/bin/dbot /usr/local/bin/d-bot
  ln -s "$target" /usr/local/bin/dbot
  ln -s /usr/local/bin/dbot /usr/local/bin/d-bot
  hash -r 2>/dev/null || true
  ok "Manager command installed: dbot -> $target"
}



show_web_credentials(){
  cd "$APP_DIR"
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
  DOMAIN_DISPLAY="${DOMAIN_NAME:-your-domain.com}"
  HTTP_PORT_DISPLAY="${NGINX_HTTP_PORT:-80}"
  HTTPS_PORT_DISPLAY="${NGINX_HTTPS_PORT:-443}"
  USER_DISPLAY="${WEB_ADMIN_USERNAME:-admin}"
  PASS_DISPLAY="${WEB_ADMIN_PASSWORD:-change_this_admin_password}"
  if [ "${ENABLE_HTTPS:-true}" = "true" ]; then
    if [ "${HTTPS_PORT_DISPLAY}" = "443" ]; then
      LOGIN_URL="https://${DOMAIN_DISPLAY}/login"
    else
      LOGIN_URL="https://${DOMAIN_DISPLAY}:${HTTPS_PORT_DISPLAY}/login"
    fi
  else
    if [ "${HTTP_PORT_DISPLAY}" = "80" ]; then
      LOGIN_URL="http://${DOMAIN_DISPLAY}/login"
    else
      LOGIN_URL="http://${DOMAIN_DISPLAY}:${HTTP_PORT_DISPLAY}/login"
    fi
  fi
  echo
  echo "================================================"
  echo "        D Bot Web Admin Access"
  echo "================================================"
  echo "Login URL          : ${LOGIN_URL}"
  echo "Direct API URL     : http://${DOMAIN_DISPLAY}:${API_PORT:-8000}/login"
  echo "Web Admin Username : ${USER_DISPLAY}"
  echo "Web Admin Password : ${PASS_DISPLAY}"
  echo "Role               : Owner"
  echo "================================================"
  echo "Save these credentials now. You can change them later from Settings > Website & SSL."
  echo "After changing username/password from the website, the panel logs out automatically."
  echo "================================================"
  echo
}


wait_for_api(){
  local attempts=90
  info "Waiting for the D Bot API health check before switching Nginx to the application..."
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 3 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
      ok "D Bot API is healthy."
      return 0
    fi
    sleep 2
  done

  warn "The API did not become healthy. Nginx will keep showing the safe installation page instead of a 502 error."
  cd "$APP_DIR"
  $COMPOSE ps || true
  $COMPOSE logs --tail=120 api || true
  fail "Fix the API error and run: dbot restart, then dbot → Apply Nginx/SSL"
}

finalize_https_admin(){
  [ -f "${APP_DIR}/scripts/setup_web_ssl.sh" ] || fail "Missing scripts/setup_web_ssl.sh"
  chmod 755 "${APP_DIR}/scripts/setup_web_ssl.sh"
  info "Switching Nginx from the installation page to the healthy D Bot API..."
  DOMAIN_NAME="$DOMAIN_NAME" \
  LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL" \
  API_PORT="$API_PORT" \
  NGINX_HTTP_PORT="$NGINX_HTTP_PORT" \
  NGINX_HTTPS_PORT="$NGINX_HTTPS_PORT" \
    bash "${APP_DIR}/scripts/setup_web_ssl.sh" "$DOMAIN_NAME" proxy
  ok "Nginx reverse proxy is active without requesting a second certificate."
}

start_app(){
  cd "$APP_DIR"
  info "Building and starting Docker containers..."
  $COMPOSE up -d --build
  echo
  ok "D Bot containers were built and started."
  echo
  cat <<'EOF'
Control menu:

  dbot
  dbot menu

Direct commands:

  dbot status
  dbot logs
  dbot restart
  dbot start
  dbot stop
  dbot update
  dbot backup
  dbot backups
  dbot uninstall --purge
EOF
}

main(){
  if [ "${1:-}" = "--repair-cli" ] || [ "${1:-}" = "repair-cli" ]; then
    need_root
    APP_DIR="${DBOT_APP_DIR:-$APP_DIR}"
    ensure_runtime_scripts
    create_manager_command
    echo
    ok "D Bot CLI repair completed. Run: dbot"
    return 0
  fi

  need_root
  banner
  domain_first_wizard
  install_base_packages
  get_project
  bootstrap_domain_ssl
  install_docker
  setup_wizard
  write_config_env
  patch_compose
  create_manager_command
  start_app
  wait_for_api
  finalize_https_admin
  show_web_credentials
}

main "$@"
