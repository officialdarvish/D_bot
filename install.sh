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
  echo -e "${BLUE} Step $1/6 — $2${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

setup_wizard(){
  setup_header
  echo "Packages and Docker are ready. Now complete the project setup."
  echo
  read -r -p "Press Enter to start setup..." _

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

  setup_step 2 "Website Domain & HTTPS"
  while true; do
    DOMAIN_NAME="$(ask_required 'Domain name, example.com: ')"
    DOMAIN_NAME="$(normalize_domain "$DOMAIN_NAME")"
    valid_domain "$DOMAIN_NAME" && break
    warn "Invalid domain. Enter only the domain, for example: panel.example.com"
  done
  ENABLE_HTTPS="$(ask_yes_no 'Enable HTTPS with Let’s Encrypt?' 'y')"
  if [ "$ENABLE_HTTPS" = "true" ]; then
    LETSENCRYPT_EMAIL="$(ask_optional 'Let’s Encrypt email, optional: ')"
  else
    LETSENCRYPT_EMAIL=""
  fi

  CUSTOM_NGINX_PORTS="$(ask_yes_no 'Use custom Nginx public ports?' 'n')"
  if [ "$CUSTOM_NGINX_PORTS" = "true" ]; then
    while true; do
      NGINX_HTTP_PORT="$(ask_default 'Nginx HTTP listen port' '80')"
      valid_port "$NGINX_HTTP_PORT" && break
      warn "Port must be between 1 and 65535."
    done
    while true; do
      NGINX_HTTPS_PORT="$(ask_default 'Nginx HTTPS listen port' '443')"
      valid_port "$NGINX_HTTPS_PORT" && break
      warn "Port must be between 1 and 65535."
    done
  else
    NGINX_HTTP_PORT="80"
    NGINX_HTTPS_PORT="443"
  fi
  if [ "$ENABLE_HTTPS" = "true" ] && { [ "$NGINX_HTTP_PORT" != "80" ] || [ "$NGINX_HTTPS_PORT" != "443" ]; }; then
    warn "Automatic Let's Encrypt usually requires public ports 80 and 443. Custom Nginx ports may require manual SSL or extra firewall/proxy configuration."
  fi

  setup_step 3 "Web Admin Panel"
  AUTO_WEB_ADMIN="$(ask_yes_no 'Auto-generate web admin username/password?' 'y')"
  if [ "$AUTO_WEB_ADMIN" = "true" ]; then
    WEB_ADMIN_USERNAME="admin_$(openssl rand -hex 3)"
    WEB_ADMIN_PASSWORD="$(generate_password)"
  else
    WEB_ADMIN_USERNAME="$(ask_default 'Web admin username' 'admin')"
    WEB_ADMIN_PASSWORD="$(ask_secret_default 'Web admin password' "$(generate_password)")"
  fi

  setup_step 4 "Database"
  POSTGRES_DB="$(ask_default 'PostgreSQL database name' 'd_bot')"
  POSTGRES_USER="$(ask_default 'PostgreSQL username' 'dbot')"
  POSTGRES_PASSWORD="$(ask_secret_default 'PostgreSQL password' "$(generate_password)")"

  setup_step 5 "Runtime Settings"
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

  setup_step 6 "Review"
  echo "Project path       : ${APP_DIR}"
  echo "Repository         : ${REPO_URL}"
  echo "Branch             : ${BRANCH}"
  echo "Domain             : ${DOMAIN_NAME}"
  echo "HTTPS              : ${ENABLE_HTTPS}"
  echo "Admin Telegram IDs : ${ADMIN_IDS}"
  echo "Web login          : https://${DOMAIN_NAME}/login"
  echo "Web username       : ${WEB_ADMIN_USERNAME}"
  echo "Database           : ${POSTGRES_DB}"
  echo "Database user      : ${POSTGRES_USER}"
  echo "Internal API port  : ${API_PORT}"
  echo "Nginx HTTP port   : ${NGINX_HTTP_PORT}"
  echo "Nginx HTTPS port  : ${NGINX_HTTPS_PORT}"
  echo "Timezone           : ${TZ_VALUE}"
  echo "Channel URL        : ${CHANNEL_URL:-not set}"
  echo
  CONFIRM_SETUP="$(ask_yes_no 'Save this setup and continue installation?' 'y')"
  if [ "$CONFIRM_SETUP" != "true" ]; then
    warn "Setup cancelled by user. Run the installer again when ready."
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
  if [ -f "$APP_DIR/scripts/dbot-control.sh" ]; then
    install -m 755 "$APP_DIR/scripts/dbot-control.sh" /usr/local/bin/dbot
    ln -sf /usr/local/bin/dbot /usr/local/bin/d-bot
    ok "Manager command installed: dbot"
    return 0
  fi

  cat > /usr/local/bin/dbot <<'EOFCLI'
#!/usr/bin/env bash
set -e
APP_DIR="/opt/d-bot"
BACKUP_KEEP_DIR="/root/d-bot-backups"
ENV_FILE="$APP_DIR/.env"

if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi

C_GREEN='\033[1;32m'; C_BLUE='\033[1;34m'; C_YELLOW='\033[1;33m'; C_RED='\033[1;31m'; C_CYAN='\033[1;36m'; C_DIM='\033[2m'; C_NC='\033[0m'

cd_app(){
  [ -d "$APP_DIR" ] || { echo -e "${C_RED}D Bot is not installed at $APP_DIR${C_NC}"; exit 1; }
  cd "$APP_DIR"
}

load_env(){
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  fi
}

mask_value(){
  local v="${1:-}"
  if [ -z "$v" ]; then echo "not set"; return; fi
  local len=${#v}
  if [ "$len" -le 8 ]; then echo "********"; return; fi
  echo "${v:0:4}********${v: -4}"
}

line(){ printf '%b\n' "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_NC}"; }

header(){
  clear || true
  printf '%b\n' "${C_CYAN}╔══════════════════════════════════════════════════════════════╗${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC}                    ${C_GREEN}D Bot Control Center${C_NC}                    ${C_CYAN}║${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC}        ${C_DIM}Setup viewer, editor and VPS service manager${C_NC}        ${C_CYAN}║${C_NC}"
  printf '%b\n' "${C_CYAN}╚══════════════════════════════════════════════════════════════╝${C_NC}"
}

pause(){ echo; read -r -p "Press Enter to continue..." _ || true; }

confirm_action(){
  local prompt="$1" answer=""
  read -r -p "$prompt [y/N]: " answer || true
  case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

require_env(){
  [ -f "$ENV_FILE" ] || { echo -e "${C_RED}Missing .env: $ENV_FILE${C_NC}"; exit 1; }
}

set_env_value(){
  local key="$1" value="$2"
  require_env
  python3 - "$ENV_FILE" "$key" "$value" <<'PYENV'
import sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding='utf-8').splitlines()
out = []
written = False
for line in lines:
    if line.startswith(key + '='):
        if not written:
            out.append(f'{key}={value}')
            written = True
        continue
    out.append(line)
if not written:
    out.append(f'{key}={value}')
path.write_text('\n'.join(out).rstrip() + '\n', encoding='utf-8')
PYENV
  chmod 600 "$ENV_FILE"
}

get_env_value(){
  local key="$1"
  [ -f "$ENV_FILE" ] || return 0
  python3 - "$ENV_FILE" "$key" <<'PYGET'
import sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
for line in path.read_text(encoding='utf-8').splitlines():
    if line.startswith(key + '='):
        print(line.split('=', 1)[1])
        break
PYGET
}

valid_domain(){
  local d="$1"
  [[ "$d" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

normalize_domain(){
  local raw="$1"
  raw="${raw#http://}"; raw="${raw#https://}"; raw="${raw%%/*}"; raw="${raw%%:*}"
  echo "$raw"
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

port_suffix(){
  local scheme="$1" p="$2"
  if [ "$scheme" = "https" ] && [ "$p" != "443" ]; then echo ":$p"; return; fi
  if [ "$scheme" = "http" ] && [ "$p" != "80" ]; then echo ":$p"; return; fi
  echo ""
}

https_redirect_target(){
  local https_port="${1:-443}"
  if [ "$https_port" = "443" ]; then
    echo 'https://$host$request_uri'
  else
    echo "https://$server_name:${https_port}"'$request_uri'
  fi
}


ask_nonempty(){
  local prompt="$1" value=""
  while [ -z "$value" ]; do read -r -p "$prompt" value || true; done
  echo "$value"
}

ask_secret_nonempty(){
  local prompt="$1" value=""
  while [ -z "$value" ]; do read -r -s -p "$prompt" value; echo >&2; done
  echo "$value"
}

ask_default(){
  local prompt="$1" default="$2" value=""
  read -r -p "$prompt [$default]: " value || true
  echo "${value:-$default}"
}

ask_yes_no(){
  local prompt="$1" default="${2:-y}" value="" hint="Y/n"
  [ "$default" = "n" ] && hint="y/N"
  while true; do
    read -r -p "$prompt [$hint]: " value || true
    value="${value:-$default}"
    case "$value" in y|Y|yes|YES) echo "true"; return ;; n|N|no|NO) echo "false"; return ;; *) echo "Please answer y or n." ;; esac
  done
}

generate_password(){ openssl rand -base64 32 | tr -d '/+=' | cut -c1-24; }

panel_url(){
  load_env
  local domain="${DOMAIN_NAME:-not-set}" api_port="${API_PORT:-8000}" http_port="${NGINX_HTTP_PORT:-80}" https_port="${NGINX_HTTPS_PORT:-443}"
  if [ "${ENABLE_HTTPS:-false}" = "true" ] && [ "$domain" != "not-set" ]; then
    echo "https://${domain}$(port_suffix https "$https_port")/login"
  elif [ "$domain" != "not-set" ]; then
    echo "http://${domain}$(port_suffix http "$http_port")/login"
  else
    echo "http://SERVER_IP:${api_port}/login"
  fi
}

service_card(){
  load_env
  local domain="${DOMAIN_NAME:-not-set}" port="${API_PORT:-8000}" https="${ENABLE_HTTPS:-false}" http_port="${NGINX_HTTP_PORT:-80}" https_port="${NGINX_HTTPS_PORT:-443}"
  local url; url="$(panel_url)"
  printf '%b\n' "${C_CYAN}╔══════════════════════════════════════════════════════════════╗${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}Project${C_NC} : D Bot"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}Path${C_NC}    : ${APP_DIR}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}Panel${C_NC}   : ${url}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}Domain${C_NC}  : ${domain}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}HTTPS${C_NC}   : ${https}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_GREEN}Nginx${C_NC}   : HTTP ${http_port} / HTTPS ${https_port}"
  printf '%b\n' "${C_CYAN}╚══════════════════════════════════════════════════════════════╝${C_NC}"
}

show_status(){
  header; service_card; echo
  printf '%b\n' "${C_BLUE}Docker services:${C_NC}"
  cd_app && $COMPOSE ps
}

show_setup_info(){
  header
  load_env
  printf '%b\n' "${C_CYAN}╔══════════════════════════════════════════════════════════════╗${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC}                    ${C_GREEN}Saved Setup Information${C_NC}                 ${C_CYAN}║${C_NC}"
  printf '%b\n' "${C_CYAN}╚══════════════════════════════════════════════════════════════╝${C_NC}"
  echo
  printf '%b\n' "${C_YELLOW}Telegram${C_NC}"
  printf '  Bot Token        : %s\n' "$(mask_value "${BOT_TOKEN:-}")"
  printf '  Admin IDs        : %s\n' "${ADMIN_IDS:-not set}"
  printf '  Owner IDs        : %s\n' "${OWNER_IDS:-not set}"
  printf '  Channel URL      : %s\n' "${DEFAULT_CHANNEL_URL:-not set}"
  echo
  printf '%b\n' "${C_YELLOW}Website & SSL${C_NC}"
  printf '  Domain           : %s\n' "${DOMAIN_NAME:-not set}"
  printf '  HTTPS            : %s\n' "${ENABLE_HTTPS:-false}"
  printf '  SSL Email        : %s\n' "${LETSENCRYPT_EMAIL:-not set}"
  printf '  Web Login        : %s\n' "$(panel_url)"
  printf '  API Port         : %s\n' "${API_PORT:-8000}"
  printf '  Nginx HTTP Port  : %s\n' "${NGINX_HTTP_PORT:-80}"
  printf '  Nginx HTTPS Port : %s\n' "${NGINX_HTTPS_PORT:-443}"
  echo
  printf '%b\n' "${C_YELLOW}Web Admin${C_NC}"
  printf '  Username         : %s\n' "${WEB_ADMIN_USERNAME:-not set}"
  printf '  Password         : %s\n' "$(mask_value "${WEB_ADMIN_PASSWORD:-}")"
  echo
  printf '%b\n' "${C_YELLOW}Database & Cache${C_NC}"
  printf '  Postgres DB      : %s\n' "${POSTGRES_DB:-d_bot}"
  printf '  Postgres User    : %s\n' "${POSTGRES_USER:-dbot}"
  printf '  Postgres Pass    : %s\n' "$(mask_value "${POSTGRES_PASSWORD:-}")"
  printf '  Postgres Host    : %s\n' "${POSTGRES_HOST:-db}"
  printf '  Postgres Port    : %s\n' "${POSTGRES_PORT:-5432}"
  printf '  Redis Host       : %s\n' "${REDIS_HOST:-redis}"
  printf '  Redis Port       : %s\n' "${REDIS_PORT:-6379}"
  echo
  printf '%b\n' "${C_YELLOW}Runtime${C_NC}"
  printf '  Timezone         : %s\n' "${TZ:-not set}"
  printf '  Server Sync      : %s seconds\n' "${SERVER_SYNC_SECONDS:-5}"
}

reveal_secrets(){
  header
  if ! confirm_action "Show saved secrets on screen? Only do this on your own VPS terminal."; then return; fi
  load_env
  line
  echo -e "${C_YELLOW}Saved secrets${C_NC}"
  line
  printf 'BOT_TOKEN=%s\n' "${BOT_TOKEN:-}"
  printf 'WEB_ADMIN_USERNAME=%s\n' "${WEB_ADMIN_USERNAME:-}"
  printf 'WEB_ADMIN_PASSWORD=%s\n' "${WEB_ADMIN_PASSWORD:-}"
  printf 'POSTGRES_PASSWORD=%s\n' "${POSTGRES_PASSWORD:-}"
  printf 'FERNET_KEY=%s\n' "${FERNET_KEY:-}"
  printf 'JWT_SECRET=%s\n' "${JWT_SECRET:-}"
  line
}

restart_after_change(){
  echo
  if confirm_action "Restart D Bot services now to apply changes?"; then
    cd_app && $COMPOSE up -d
    echo -e "${C_GREEN}Services restarted/applied.${C_NC}"
  else
    echo -e "${C_YELLOW}Changes were saved. Run 'dbot restart' later.${C_NC}"
  fi
}

configure_nginx_ssl(){
  load_env
  local domain="${DOMAIN_NAME:-}" port="${API_PORT:-8000}" http_port="${NGINX_HTTP_PORT:-80}" https_port="${NGINX_HTTPS_PORT:-443}"
  if [ -z "$domain" ] || [ "$domain" = "not-set" ]; then
    echo -e "${C_RED}DOMAIN_NAME is empty. Set domain first.${C_NC}"
    return 1
  fi
  if ! command -v nginx >/dev/null 2>&1; then
    echo -e "${C_YELLOW}nginx is not installed. Skipping reverse proxy setup.${C_NC}"
    return 0
  fi
  if ! valid_port "$http_port" || ! valid_port "$https_port" || ! valid_port "$port"; then
    echo -e "${C_RED}Invalid port value in .env.${C_NC}"
    return 1
  fi
  local redirect_target; redirect_target="$(https_redirect_target "$https_port")"

  cat > /etc/nginx/sites-available/d-bot.conf <<EOFNGINX
server {
    listen ${http_port};
    server_name ${domain};

    location / {
        proxy_pass http://127.0.0.1:${port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOFNGINX
  ln -sf /etc/nginx/sites-available/d-bot.conf /etc/nginx/sites-enabled/d-bot.conf
  nginx -t && systemctl reload nginx || true

  if [ "${ENABLE_HTTPS:-false}" = "true" ]; then
    if [ "$http_port" != "80" ] || [ "$https_port" != "443" ]; then
      echo -e "${C_YELLOW}Warning: automatic Let's Encrypt usually requires public ports 80 and 443. Custom ports may fail unless you manage SSL manually.${C_NC}"
    fi
    if command -v certbot >/dev/null 2>&1; then
      echo "Requesting/renewing Let's Encrypt certificate for ${domain}..."
      if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then
        certbot --nginx -d "$domain" --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL" --redirect || echo "Certbot failed. Check DNS and public ports 80/443."
      else
        certbot --nginx -d "$domain" --non-interactive --agree-tos --register-unsafely-without-email --redirect || echo "Certbot failed. Check DNS and public ports 80/443."
      fi
      if [ -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]; then
        cat > /etc/nginx/sites-available/d-bot.conf <<EOFNGINX
server {
    listen ${http_port};
    server_name ${domain};
    location / {
        return 301 ${redirect_target};
    }
}

server {
    listen ${https_port} ssl http2;
    server_name ${domain};

    ssl_certificate /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:${port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOFNGINX
      fi
      nginx -t && systemctl reload nginx || true
    else
      echo -e "${C_YELLOW}certbot is not installed. HTTPS was not applied.${C_NC}"
    fi
  fi
}

edit_telegram(){
  header
  load_env
  echo -e "${C_YELLOW}Telegram Settings${C_NC}"
  echo "1) Change bot token"
  echo "2) Change admin/owner IDs"
  echo "3) Change default channel URL"
  echo "0) Back"
  read -r -p "Select: " c || true
  case "$c" in
    1)
      echo "The new Telegram Bot Token will be visible while typing."
      while true; do
        v="$(ask_nonempty 'New Telegram Bot Token: ')"
        valid_bot_token "$v" && break
        echo "Token format looks invalid. Example: 123456789:AAExample_Token-Value"
      done
      set_env_value BOT_TOKEN "$v"
      ;;
    2)
      while true; do
        v="$(ask_nonempty 'Admin Telegram IDs, comma separated: ')"; v="$(echo "$v" | tr -d ' ')"
        valid_ids "$v" && break
        echo "Invalid IDs. Example: 123456789 or 123456789,987654321"
      done
      set_env_value ADMIN_IDS "$v"; set_env_value OWNER_IDS "$v" ;;
    3) read -r -p "Default Telegram channel URL, empty to clear: " v || true; set_env_value DEFAULT_CHANNEL_URL "$v" ;;
    0) return ;;
  esac
  restart_after_change
}

edit_website(){
  header
  load_env
  echo -e "${C_YELLOW}Website & SSL Settings${C_NC}"
  echo "1) Change domain"
  echo "2) Toggle HTTPS"
  echo "3) Change Let's Encrypt email"
  echo "4) Change internal API port"
  echo "5) Change Nginx HTTP port"
  echo "6) Change Nginx HTTPS port"
  echo "7) Apply Nginx/SSL config"
  echo "0) Back"
  read -r -p "Select: " c || true
  case "$c" in
    1)
      while true; do
        v="$(ask_nonempty 'New domain, example: panel.example.com: ')"; v="$(normalize_domain "$v")"
        valid_domain "$v" && break
        echo "Invalid domain."
      done
      set_env_value DOMAIN_NAME "$v" ;;
    2) v="$(ask_yes_no 'Enable HTTPS?' 'y')"; set_env_value ENABLE_HTTPS "$v" ;;
    3) read -r -p "Let's Encrypt email, empty to clear: " v || true; set_env_value LETSENCRYPT_EMAIL "$v" ;;
    4)
      while true; do
        v="$(ask_default 'Internal API port' "${API_PORT:-8000}")"
        valid_port "$v" && break
        echo "Port must be between 1 and 65535."
      done
      set_env_value API_PORT "$v" ;;
    5)
      while true; do
        v="$(ask_default 'Nginx HTTP listen port' "${NGINX_HTTP_PORT:-80}")"
        valid_port "$v" && break
        echo "Port must be between 1 and 65535."
      done
      set_env_value NGINX_HTTP_PORT "$v" ;;
    6)
      while true; do
        v="$(ask_default 'Nginx HTTPS listen port' "${NGINX_HTTPS_PORT:-443}")"
        valid_port "$v" && break
        echo "Port must be between 1 and 65535."
      done
      set_env_value NGINX_HTTPS_PORT "$v" ;;
    7) configure_nginx_ssl; pause; return ;;
    0) return ;;
  esac
  configure_nginx_ssl || true
  restart_after_change
}

edit_web_admin(){
  header
  load_env
  echo -e "${C_YELLOW}Web Admin Settings${C_NC}"
  echo "1) Change username"
  echo "2) Change password manually"
  echo "3) Generate new password"
  echo "0) Back"
  read -r -p "Select: " c || true
  case "$c" in
    1) v="$(ask_default 'New web admin username' "${WEB_ADMIN_USERNAME:-admin}")"; set_env_value WEB_ADMIN_USERNAME "$v" ;;
    2) v="$(ask_secret_nonempty 'New web admin password: ')"; set_env_value WEB_ADMIN_PASSWORD "$v" ;;
    3) v="$(generate_password)"; set_env_value WEB_ADMIN_PASSWORD "$v"; echo "New password: $v" ;;
    0) return ;;
  esac
  restart_after_change
}

edit_runtime(){
  header
  load_env
  echo -e "${C_YELLOW}Runtime Settings${C_NC}"
  echo "1) Change timezone"
  echo "2) Change server sync seconds"
  echo "0) Back"
  read -r -p "Select: " c || true
  case "$c" in
    1) v="$(ask_default 'Timezone' "${TZ:-Asia/Tehran}")"; set_env_value TZ "$v" ;;
    2)
      while true; do
        v="$(ask_default 'Server sync seconds' "${SERVER_SYNC_SECONDS:-5}")"
        [[ "$v" =~ ^[0-9]+$ ]] && [ "$v" -ge 1 ] && break
        echo "Enter a positive number."
      done
      set_env_value SERVER_SYNC_SECONDS "$v" ;;
    0) return ;;
  esac
  restart_after_change
}

edit_database(){
  header
  load_env
  echo -e "${C_RED}Advanced database settings${C_NC}"
  echo "Changing database values after data exists can break the app unless you migrate the database or recreate volumes."
  echo "A backup is recommended before changing these values."
  if ! confirm_action "Continue anyway?"; then return; fi
  echo "1) Change database name"
  echo "2) Change database username"
  echo "3) Change database password"
  echo "4) Change database host/port"
  echo "0) Back"
  read -r -p "Select: " c || true
  case "$c" in
    1) v="$(ask_default 'PostgreSQL database name' "${POSTGRES_DB:-d_bot}")"; set_env_value POSTGRES_DB "$v" ;;
    2) v="$(ask_default 'PostgreSQL username' "${POSTGRES_USER:-dbot}")"; set_env_value POSTGRES_USER "$v" ;;
    3) v="$(ask_secret_nonempty 'PostgreSQL password: ')"; set_env_value POSTGRES_PASSWORD "$v" ;;
    4)
      h="$(ask_default 'PostgreSQL host' "${POSTGRES_HOST:-db}")"
      p="$(ask_default 'PostgreSQL port' "${POSTGRES_PORT:-5432}")"
      set_env_value POSTGRES_HOST "$h"; set_env_value POSTGRES_PORT "$p" ;;
    0) return ;;
  esac
  # Keep DATABASE_URL aligned with the new values.
  load_env
  dburl="postgresql+asyncpg://${POSTGRES_USER:-dbot}:${POSTGRES_PASSWORD:-dbot}@${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-d_bot}"
  set_env_value DATABASE_URL "$dburl"
  restart_after_change
}

edit_setup_menu(){
  while true; do
    header
    echo -e "${C_YELLOW}Edit saved setup values${C_NC}"
    echo
    echo "1) Telegram bot settings"
    echo "2) Website, domain, HTTPS and port"
    echo "3) Web admin username/password"
    echo "4) Runtime settings"
    echo "5) Database settings (advanced)"
    echo "0) Back"
    echo
    read -r -p "Select: " c || true
    case "$c" in
      1) edit_telegram ;;
      2) edit_website ;;
      3) edit_web_admin ;;
      4) edit_runtime ;;
      5) edit_database ;;
      0|q|Q) return ;;
      *) echo -e "${C_RED}Invalid option.${C_NC}"; sleep 1 ;;
    esac
  done
}

install_manager_self(){
  local src="$APP_DIR/scripts/dbot-control.sh"
  if [ -f "$src" ]; then
    install -m 755 "$src" /usr/local/bin/dbot
    ln -sf /usr/local/bin/dbot /usr/local/bin/d-bot
    echo -e "${C_GREEN}Manager command updated: dbot${C_NC}"
  fi
}

backup_app(){
  cd_app
  TS="$(date +%Y%m%d_%H%M%S)"
  BACKUP_DIR="$APP_DIR/backups/$TS"
  mkdir -p "$BACKUP_DIR"
  load_env
  DB_NAME="${POSTGRES_DB:-d_bot}"
  DB_USER="${POSTGRES_USER:-dbot}"
  echo "Creating database backup..."
  if $COMPOSE ps db >/dev/null 2>&1; then
    $COMPOSE exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/database.sql" || true
  fi
  echo "Creating project files backup..."
  tar --exclude='./backups' --exclude='./postgres_data' --exclude='./.git' -czf "$BACKUP_DIR/project-files.tar.gz" .
  if [ -f .env ]; then cp .env "$BACKUP_DIR/.env.backup"; chmod 600 "$BACKUP_DIR/.env.backup"; fi
  cd "$APP_DIR/backups"
  tar -czf "dbot-backup-$TS.tar.gz" "$TS"
  rm -rf "$TS"
  echo "Backup created: $APP_DIR/backups/dbot-backup-$TS.tar.gz"
}

update_app(){
  cd_app
  ENV_BACKUP=""
  if [ -f .env ]; then ENV_BACKUP="$(mktemp)"; cp .env "$ENV_BACKUP"; fi
  if [ -d .git ]; then
    echo "Fetching latest source from GitHub..."
    git fetch origin main || echo "Git fetch failed. Rebuilding current local source..."
    if git rev-parse --verify origin/main >/dev/null 2>&1; then git reset --hard origin/main; fi
  else
    echo "Git repository not found. Rebuilding current local source..."
  fi
  if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then cp "$ENV_BACKUP" .env; chmod 600 .env; rm -f "$ENV_BACKUP"; fi
  install_manager_self
  $COMPOSE up -d --build
}

uninstall_app(){
  PURGE="${1:-}"
  echo; echo -e "${C_RED}WARNING! This will remove D Bot from this VPS.${C_NC}"; echo
  echo "Project directory: $APP_DIR"
  echo "Docker containers, volumes, networks, database files, Redis data, .env and CLI commands will be removed."
  [ "$PURGE" = "--purge" ] && echo "Backups will also be deleted." || echo "Backups will be moved to: $BACKUP_KEEP_DIR"
  echo
  read -r -p "Type yes to continue: " CONFIRM
  [ "$CONFIRM" = "yes" ] || { echo "Uninstall cancelled."; exit 0; }
  if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    $COMPOSE down -v --remove-orphans || true
    if [ "$PURGE" != "--purge" ] && [ -d "$APP_DIR/backups" ]; then
      mkdir -p "$BACKUP_KEEP_DIR"; TS="$(date +%Y%m%d_%H%M%S)"; mv "$APP_DIR/backups" "$BACKUP_KEEP_DIR/backups-$TS" || true
    fi
    rm -rf "$APP_DIR"
  fi
  rm -f /usr/local/bin/dbot /usr/local/bin/d-bot
  echo "D Bot has been completely removed."
}

show_main_menu(){
  printf '%b\n' "${C_CYAN}╔══════════════════════════════════════════════════════════════╗${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}1${C_NC}) Status                  ${C_DIM}Show containers${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}2${C_NC}) Logs                    ${C_DIM}Live logs, Ctrl+C to exit${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}3${C_NC}) Restart                 ${C_DIM}Restart all services${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}4${C_NC}) Start                   ${C_DIM}Start services${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}5${C_NC}) Stop                    ${C_DIM}Stop services${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}6${C_NC}) Update                  ${C_DIM}Pull/rebuild and restart${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}7${C_NC}) Backup                  ${C_DIM}Create a full backup${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}8${C_NC}) Setup Info              ${C_DIM}View values from setup wizard${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}9${C_NC}) Edit Setup              ${C_DIM}Change saved .env values${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}10${C_NC}) Apply Nginx/SSL        ${C_DIM}Rebuild reverse proxy/certificate${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}11${C_NC}) Show Secrets           ${C_DIM}Reveal saved credentials${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_RED}12${C_NC}) Uninstall --purge     ${C_DIM}Remove app and backups${C_NC}"
  printf '%b\n' "${C_CYAN}║${C_NC} ${C_YELLOW}0${C_NC}) Exit"
  printf '%b\n' "${C_CYAN}╚══════════════════════════════════════════════════════════════╝${C_NC}"
}

control_menu(){
  while true; do
    header; service_card; echo; show_main_menu; echo
    read -r -p "Select an option: " choice || true
    case "$choice" in
      1|status) show_status; pause ;;
      2|logs) header; echo -e "${C_YELLOW}Showing live logs. Press Ctrl+C to exit logs.${C_NC}"; cd_app && $COMPOSE logs -f --tail=200 ;;
      3|restart) header; cd_app && $COMPOSE restart; echo -e "${C_GREEN}Done.${C_NC}"; pause ;;
      4|start) header; cd_app && $COMPOSE up -d; echo -e "${C_GREEN}Done.${C_NC}"; pause ;;
      5|stop) header; if confirm_action "Stop all D Bot services?"; then cd_app && $COMPOSE down; echo -e "${C_GREEN}Services stopped.${C_NC}"; fi; pause ;;
      6|update) header; if confirm_action "Update, rebuild and restart D Bot?"; then update_app; echo -e "${C_GREEN}Update completed.${C_NC}"; fi; pause ;;
      7|backup) header; backup_app; pause ;;
      8|info) show_setup_info; pause ;;
      9|edit) edit_setup_menu ;;
      10|nginx|ssl) header; configure_nginx_ssl; pause ;;
      11|secrets) reveal_secrets; pause ;;
      12|uninstall|purge) header; uninstall_app "--purge"; exit 0 ;;
      0|q|Q|exit) exit 0 ;;
      *) echo -e "${C_RED}Invalid option.${C_NC}"; sleep 1 ;;
    esac
  done
}

# Running only `dbot` or `dbot menu` opens the graphic Control Center.
# Direct commands like `dbot status` or `dbot restart` still work.
if [ "$#" -eq 0 ]; then
  control_menu
  exit 0
fi

case "${1}" in
  menu|m|control|center|--menu) control_menu ;;
  start) cd_app && $COMPOSE up -d ;;
  stop) cd_app && $COMPOSE down ;;
  restart) cd_app && $COMPOSE restart ;;
  logs) cd_app && $COMPOSE logs -f --tail=200 ;;
  update) update_app ;;
  backup) backup_app ;;
  status) show_status ;;
  remove|uninstall) uninstall_app "${2:-}" ;;
  help|-h|--help) control_menu ;;
  *) control_menu ;;
esac

EOFCLI
  chmod +x /usr/local/bin/dbot
  ln -sf /usr/local/bin/dbot /usr/local/bin/d-bot
  ok "Manager command installed: dbot"
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


setup_https_admin(){
  if [ "${ENABLE_HTTPS:-true}" != "true" ]; then
    warn "HTTPS setup was disabled in the setup wizard."
    return 0
  fi
  if [ -z "${DOMAIN_NAME:-}" ] || [ "$DOMAIN_NAME" = "example.com" ]; then
    warn "Domain is empty/example.com. Skipping HTTPS certificate setup."
    return 0
  fi
  NGINX_HTTP_PORT="${NGINX_HTTP_PORT:-80}"
  NGINX_HTTPS_PORT="${NGINX_HTTPS_PORT:-443}"
  if [ "$NGINX_HTTP_PORT" != "80" ] || [ "$NGINX_HTTPS_PORT" != "443" ]; then
    warn "Automatic Let’s Encrypt normally needs public ports 80 and 443. Custom ports may fail unless SSL is handled manually."
  fi
  info "Configuring nginx reverse proxy on HTTP ${NGINX_HTTP_PORT} / HTTPS ${NGINX_HTTPS_PORT} for ${DOMAIN_NAME} ..."
  cat > /etc/nginx/sites-available/d-bot.conf <<EOFNGINX
server {
    listen ${NGINX_HTTP_PORT};
    server_name ${DOMAIN_NAME};

    location / {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOFNGINX
  ln -sf /etc/nginx/sites-available/d-bot.conf /etc/nginx/sites-enabled/d-bot.conf
  nginx -t && systemctl reload nginx

  if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then
    certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos -m "$LETSENCRYPT_EMAIL" --redirect || warn "Certbot failed. Make sure DNS points to this VPS and public ports 80/443 are open."
  else
    certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos --register-unsafely-without-email --redirect || warn "Certbot failed. Make sure DNS points to this VPS and public ports 80/443 are open."
  fi

  if [ -f "/etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]; then
    if [ "${NGINX_HTTPS_PORT}" = "443" ]; then
      REDIRECT_TARGET='https://$host$request_uri'
    else
      REDIRECT_TARGET="https://$server_name:${NGINX_HTTPS_PORT}"'$request_uri'
    fi
    cat > /etc/nginx/sites-available/d-bot.conf <<EOFNGINX
server {
    listen ${NGINX_HTTP_PORT};
    server_name ${DOMAIN_NAME};
    location / {
        return 301 ${REDIRECT_TARGET};
    }
}

server {
    listen ${NGINX_HTTPS_PORT} ssl http2;
    server_name ${DOMAIN_NAME};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN_NAME}/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
EOFNGINX
  fi
  systemctl reload nginx || true
}

start_app(){
  cd "$APP_DIR"
  info "Building and starting Docker containers..."
  $COMPOSE up -d --build
  echo
  ok "D Bot has been installed successfully."
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
  dbot uninstall --purge
EOF
}

main(){
  need_root
  banner
  install_base_packages
  install_docker
  setup_wizard
  get_project
  write_config_env
  patch_compose
  create_manager_command
  start_app
  setup_https_admin || true
  show_web_credentials
}

main "$@"
