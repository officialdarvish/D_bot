#!/usr/bin/env bash
set -Eeuo pipefail

# Darvish D Bot one-click installer
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
  echo "        Darvish D Bot Auto Installer         "
  echo "================================================"
  echo
}

install_base_packages(){
  info "Updating VPS and installing required packages..."
  export DEBIAN_FRONTEND=noninteractive

  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get upgrade -y
    apt-get install -y ca-certificates curl gnupg lsb-release git unzip openssl rsync nano python3 python3-pip
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

ask_secret(){
  # Inputs are intentionally visible while typing, because this installer is used interactively.
  local prompt="$1" value=""
  while [ -z "$value" ]; do
    read -r -p "$prompt" value
  done
  echo "$value"
}

ask_default(){
  local prompt="$1" default="$2" value=""
  read -r -p "$prompt [$default]: " value || true
  echo "${value:-$default}"
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
    # VPN Bot-like remote install: clone repo automatically.
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

collect_config(){
  info "Telegram configuration"
  BOT_TOKEN="$(ask_secret 'Enter Telegram Bot Token: ')"
  ADMIN_IDS="$(ask_required 'Enter numeric Admin Telegram ID: ')"
  read -r -p "Enter required channel link, or press Enter to skip: " CHANNEL_URL || true
  CHANNEL_URL="${CHANNEL_URL:-}"

  info "Database configuration"
  POSTGRES_DB="$(ask_default 'Enter PostgreSQL database name' 'd_bot')"
  POSTGRES_USER="$(ask_default 'Enter PostgreSQL username' 'dbot')"
  POSTGRES_PASSWORD="$(ask_secret 'Enter PostgreSQL password: ')"
  POSTGRES_HOST="$(ask_default 'Enter PostgreSQL host for Docker network' 'db')"
  POSTGRES_PORT="$(ask_default 'Enter PostgreSQL port' '5432')"

  info "Redis configuration"
  REDIS_HOST="$(ask_default 'Enter Redis host for Docker network' 'redis')"
  REDIS_PORT="$(ask_default 'Enter Redis port' '6379')"
  REDIS_DB="$(ask_default 'Enter Redis DB index' '0')"

  info "API and security configuration"
  API_HOST="$(ask_default 'Enter API host' '0.0.0.0')"
  API_PORT="$(ask_default 'Enter API public port' '8000')"
  TZ_VALUE="$(ask_default 'Enter timezone' 'Asia/Tehran')"
  read -r -p "Enter Fernet key, or press Enter to auto-generate: " FERNET_KEY || true

  if [ -z "${FERNET_KEY:-}" ]; then
    FERNET_KEY="$(python3 - <<'PY' 2>/dev/null || openssl rand -base64 32
try:
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())
except Exception:
    raise SystemExit(1)
PY
)"
  fi

  if ! [[ "$POSTGRES_PORT" =~ ^[0-9]+$ ]]; then
    fail "PostgreSQL port must be a number. Recommended value: 5432"
  fi

  if [ "$POSTGRES_PORT" = "$API_PORT" ]; then
    warn "PostgreSQL port and API port are both set to ${POSTGRES_PORT}."
    warn "For Docker Compose installs, PostgreSQL port should usually be 5432 and API port should usually be 8000."
  fi

  cat > "${APP_DIR}/.env" <<EOFENV
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}
REDIS_URL=redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}
API_HOST=${API_HOST}
API_PORT=${API_PORT}
FERNET_KEY=${FERNET_KEY}
DEFAULT_CHANNEL_URL=${CHANNEL_URL}
PAYG_MIN_BALANCE_IRT=300000
PAYG_SCAN_MINUTES=60
TZ=${TZ_VALUE}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_HOST=${POSTGRES_HOST}
POSTGRES_PORT=${POSTGRES_PORT}
REDIS_HOST=${REDIS_HOST}
REDIS_PORT=${REDIS_PORT}
REDIS_DB=${REDIS_DB}
EOFENV
  chmod 600 "${APP_DIR}/.env"

  ok ".env created successfully."
  echo
  echo "================================================"
  echo "Darvish D Bot configuration summary"
  echo "================================================"
  echo "Telegram Bot Token : ${BOT_TOKEN}"
  echo "Admin Telegram ID  : ${ADMIN_IDS}"
  echo "Required Channel   : ${CHANNEL_URL:-not set}"
  echo "Database Name      : ${POSTGRES_DB}"
  echo "Database User      : ${POSTGRES_USER}"
  echo "Database Password  : ${POSTGRES_PASSWORD}"
  echo "Database Host      : ${POSTGRES_HOST}"
  echo "Database Port      : ${POSTGRES_PORT}"
  echo "Database URL       : postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
  echo "Redis URL          : redis://${REDIS_HOST}:${REDIS_PORT}/${REDIS_DB}"
  echo "API Host           : ${API_HOST}"
  echo "API Public Port    : ${API_PORT}"
  echo "Timezone           : ${TZ_VALUE}"
  echo "Fernet Key         : ${FERNET_KEY}"
  echo "================================================"
  echo
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
  cat > /usr/local/bin/dbot <<'EOFCLI'
#!/usr/bin/env bash
set -e
APP_DIR="/opt/d-bot"
OLD_APP_DIR="/opt/dbot-vpn-bot"
BACKUP_KEEP_DIR="/root/d-bot-backups"

if [ "${1:-menu}" != "uninstall" ] && [ "${1:-menu}" != "remove" ]; then
  cd "$APP_DIR"
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
else
  if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
fi

backup_app(){
  cd "$APP_DIR"
  TS="$(date +%Y%m%d_%H%M%S)"
  BACKUP_DIR="$APP_DIR/backups/$TS"
  mkdir -p "$BACKUP_DIR"

  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi

  DB_NAME="${POSTGRES_DB:-d_bot}"
  DB_USER="${POSTGRES_USER:-dbot}"

  echo "Creating database backup..."
  if $COMPOSE ps db >/dev/null 2>&1; then
    $COMPOSE exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/database.sql" || true
  fi

  echo "Creating project files backup..."
  tar \
    --exclude='./backups' \
    --exclude='./postgres_data' \
    --exclude='./.git' \
    -czf "$BACKUP_DIR/project-files.tar.gz" .

  if [ -f .env ]; then
    cp .env "$BACKUP_DIR/.env.backup"
    chmod 600 "$BACKUP_DIR/.env.backup"
  fi

  cd "$APP_DIR/backups"
  tar -czf "dbot-backup-$TS.tar.gz" "$TS"
  rm -rf "$TS"

  echo "Backup created: $APP_DIR/backups/dbot-backup-$TS.tar.gz"
}


install_analytics(){
  cd "$APP_DIR"
  case "${1:-show}" in
    record) python3 scripts/install_analytics.py record --source "dbot" ;;
    generate) python3 scripts/install_analytics.py generate && echo "Chart updated: $APP_DIR/docs/install_chart.svg" ;;
    show|*) python3 scripts/install_analytics.py show ;;
  esac
}


restore_mysql_users(){
  cd "$APP_DIR"

  if [ ! -f .env ]; then
    echo "Missing .env in $APP_DIR. Install VPN Bot first."
    exit 1
  fi

  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a

  DB_NAME="${POSTGRES_DB:-d_bot}"
  DB_USER="${POSTGRES_USER:-dbot}"

  SRC="${1:-}"
  if [ -z "$SRC" ]; then
    echo "Enter WizWiz MySQL users backup path. Examples:"
    echo "  /root/wizwiz_users_854.sql"
    echo "  /root/wizwiz_users_854.zip"
    read -r -p "Backup path: " SRC
  fi

  [ -n "$SRC" ] || { echo "Backup path is empty."; exit 1; }
  [ -f "$SRC" ] || { echo "Backup file not found: $SRC"; exit 1; }

  TS="$(date +%Y%m%d_%H%M%S)"
  WORK_DIR="/tmp/dbot_restore_mysql_$TS"
  mkdir -p "$WORK_DIR"
  OUT_SQL="$WORK_DIR/dbot_import_users.sql"
  REPORT="$WORK_DIR/restore_report.txt"

  echo "Converting WizWiz MySQL users backup to VPN Bot PostgreSQL import..."
  python3 - "$SRC" "$OUT_SQL" "$REPORT" <<'PYRESTORE'
import ast
import io
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

src = Path(sys.argv[1])
out_sql = Path(sys.argv[2])
report = Path(sys.argv[3])

def read_source(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            sql_names = [n for n in z.namelist() if n.lower().endswith('.sql')]
            if not sql_names:
                raise SystemExit('No .sql file found inside zip backup.')
            # Prefer files with users in name, otherwise the first SQL.
            sql_names.sort(key=lambda n: (0 if 'user' in n.lower() else 1, n))
            data = z.read(sql_names[0])
    for enc in ('utf-8', 'utf-8-sig', 'latin1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode('utf-8', errors='replace')

def iter_user_insert_blocks(text: str):
    # Capture INSERT INTO `users` (...) VALUES ...; blocks, including multiline values.
    pat = re.compile(r"INSERT\s+INTO\s+`?users`?\s*\((.*?)\)\s*VALUES\s*(.*?);", re.I | re.S)
    for m in pat.finditer(text):
        cols_raw, values_raw = m.group(1), m.group(2)
        cols = [c.strip().strip('`').strip('"') for c in cols_raw.split(',')]
        yield cols, values_raw

def split_tuples(values: str):
    tuples = []
    start = None
    depth = 0
    in_str = False
    quote = ''
    esc = False
    for i, ch in enumerate(values):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue
        if ch == '(':
            if depth == 0:
                start = i
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values[start:i+1])
                start = None
    return tuples

def mysql_tuple_to_python_tuple(t: str):
    # Convert a MySQL value tuple to a Python literal tuple.
    # MySQL NULL -> None. Keep escaped quotes/backslashes compatible enough for ast.
    body = t.strip()
    body = re.sub(r'\bNULL\b', 'None', body, flags=re.I)
    # MySQL single quoted strings with backslash escapes are close to Python strings.
    try:
        return ast.literal_eval(body)
    except Exception:
        # Fallback parser for edge cases.
        vals = []
        cur = []
        in_str = False
        quote = ''
        esc = False
        token_was_string = False
        for ch in body[1:-1]:
            if in_str:
                if esc:
                    mapping = {'n':'\n','r':'\r','t':'\t','0':'\0'}
                    cur.append(mapping.get(ch, ch))
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == quote:
                    in_str = False
                else:
                    cur.append(ch)
            else:
                if ch in ("'", '"'):
                    in_str = True
                    quote = ch
                    token_was_string = True
                elif ch == ',':
                    raw = ''.join(cur).strip()
                    if token_was_string:
                        vals.append(raw)
                    elif raw.lower() == 'none' or raw == '':
                        vals.append(None)
                    else:
                        try: vals.append(int(raw))
                        except Exception: vals.append(raw)
                    cur=[]; token_was_string=False
                else:
                    cur.append(ch)
        raw=''.join(cur).strip()
        if token_was_string:
            vals.append(raw)
        elif raw.lower() == 'none' or raw == '':
            vals.append(None)
        else:
            try: vals.append(int(raw))
            except Exception: vals.append(raw)
        return tuple(vals)

def sql_literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, int):
        return str(value)
    s = str(value).replace("'", "''")
    return "'" + s + "'"

def clean_username(v):
    if v is None:
        return None
    s = str(v).strip()
    bad = {'', 'ندارد', ' ندارد ', 'ندارد ', ' ندارد', 'null', 'none', '-'}
    if s.lower() in bad or s in bad:
        return None
    if s.startswith('@'):
        s = s[1:]
    return s[:128] or None

def clean_name(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {'null', 'none'}:
        return None
    return s[:255]

def clean_wallet(v):
    try:
        return max(0, int(float(v or 0)))
    except Exception:
        return 0

def epoch_to_ts(v):
    try:
        n = int(float(v))
        if n <= 0:
            raise ValueError
        return datetime.fromtimestamp(n, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=' ', timespec='seconds')
    except Exception:
        return datetime.utcnow().replace(microsecond=0).isoformat(sep=' ')

text = read_source(src)
users = {}
raw_count = 0
for cols, values_raw in iter_user_insert_blocks(text):
    for tup in split_tuples(values_raw):
        row = mysql_tuple_to_python_tuple(tup)
        if len(row) != len(cols):
            continue
        d = dict(zip(cols, row))
        tg = d.get('userid')
        try:
            telegram_id = int(str(tg).strip())
        except Exception:
            continue
        if telegram_id <= 0:
            continue
        raw_count += 1
        users[telegram_id] = {
            'telegram_id': telegram_id,
            'username': clean_username(d.get('username')),
            'full_name': clean_name(d.get('name')),
            'wallet_balance': clean_wallet(d.get('wallet')),
            'joined_at': epoch_to_ts(d.get('date')),
        }

if not users:
    raise SystemExit('No users found in this backup. Make sure it is a WizWiz users SQL export or zip.')

rows = sorted(users.values(), key=lambda x: x['telegram_id'])
with out_sql.open('w', encoding='utf-8') as f:
    f.write('-- VPN Bot import generated from WizWiz MySQL users backup\n')
    f.write('-- This imports users only. Orders, configs and payments are untouched.\n')
    f.write('BEGIN;\n')
    f.write('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, telegram_id BIGINT UNIQUE);\n')
    f.write('INSERT INTO users (telegram_id, username, full_name, wallet_balance, wallet_v2ray_balance, wallet_openvpn_balance, accepted_rules, is_blocked, joined_at) VALUES\n')
    vals=[]
    for r in rows:
        vals.append('  (' + ', '.join([
            str(r['telegram_id']),
            sql_literal(r['username']),
            sql_literal(r['full_name']),
            str(r['wallet_balance']),
            str(r['wallet_balance']),
            '0',
            'TRUE',
            'FALSE',
            sql_literal(r['joined_at']),
        ]) + ')')
    f.write(',\n'.join(vals))
    f.write('\nON CONFLICT (telegram_id) DO UPDATE SET\n')
    f.write('  username = COALESCE(EXCLUDED.username, users.username),\n')
    f.write('  full_name = COALESCE(EXCLUDED.full_name, users.full_name),\n')
    f.write('  wallet_balance = GREATEST(users.wallet_balance, EXCLUDED.wallet_balance),\n')
    f.write('  wallet_v2ray_balance = GREATEST(users.wallet_v2ray_balance, EXCLUDED.wallet_v2ray_balance),\n')
    f.write('  joined_at = LEAST(users.joined_at, EXCLUDED.joined_at);\n')
    f.write('COMMIT;\n')

report.write_text(
    f'Raw WizWiz user rows: {raw_count}\nUnique Telegram IDs: {len(rows)}\nOutput SQL: {out_sql}\n',
    encoding='utf-8'
)
print(report.read_text(encoding='utf-8').strip())
PYRESTORE

  echo "Importing users into VPN Bot PostgreSQL database..."
  if ! $COMPOSE ps db >/dev/null 2>&1; then
    echo "PostgreSQL container is not available. Start VPN Bot first: dbot start"
    exit 1
  fi

  $COMPOSE exec -T db psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$OUT_SQL"

  echo "Checking imported users count..."
  $COMPOSE exec -T db psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT COUNT(*) AS total_users FROM users;"

  mkdir -p "$APP_DIR/backups/mysql-restore"
  cp "$OUT_SQL" "$APP_DIR/backups/mysql-restore/dbot_import_users_$TS.sql"
  cp "$REPORT" "$APP_DIR/backups/mysql-restore/restore_report_$TS.txt"

  echo "Restore completed."
  echo "Generated import SQL saved at: $APP_DIR/backups/mysql-restore/dbot_import_users_$TS.sql"
  echo "Report saved at: $APP_DIR/backups/mysql-restore/restore_report_$TS.txt"
}

update_app(){
  cd "$APP_DIR"

  ENV_BACKUP=""
  if [ -f .env ]; then
    ENV_BACKUP="$(mktemp)"
    cp .env "$ENV_BACKUP"
  fi

  if [ -d .git ]; then
    echo "Fetching latest source from GitHub..."
    git fetch origin main || {
      echo "Git fetch failed. Rebuilding current local source..."
    }

    if git rev-parse --verify origin/main >/dev/null 2>&1; then
      echo "Resetting local source to origin/main to avoid divergent branch errors..."
      git reset --hard origin/main
    fi
  else
    echo "Git repository not found. Rebuilding current local source..."
  fi

  if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" .env
    chmod 600 .env
    rm -f "$ENV_BACKUP"
  fi

  $COMPOSE up -d --build
}

uninstall_app(){
  PURGE="${1:-}"
  echo ""
  echo "WARNING!"
  echo "This will completely remove Darvish D Bot from this VPS."
  echo ""
  echo "Project directory: $APP_DIR"
  echo "Docker containers, volumes, networks, database files, Redis data, .env and CLI commands will be removed."
  if [ "$PURGE" = "--purge" ]; then
    echo "Backups will also be deleted."
  else
    echo "Existing backups will be moved to: $BACKUP_KEEP_DIR"
  fi
  echo ""
  read -r -p "Type yes to continue: " CONFIRM
  if [ "$CONFIRM" != "yes" ]; then
    echo "Uninstall cancelled."
    exit 0
  fi

  if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    echo "Stopping and removing Docker containers, networks and volumes..."
    $COMPOSE down -v --remove-orphans || true

    if [ "$PURGE" != "--purge" ] && [ -d "$APP_DIR/backups" ]; then
      mkdir -p "$BACKUP_KEEP_DIR"
      TS="$(date +%Y%m%d_%H%M%S)"
      mv "$APP_DIR/backups" "$BACKUP_KEEP_DIR/backups-$TS" || true
      echo "Backups saved in: $BACKUP_KEEP_DIR/backups-$TS"
    fi

    echo "Removing project files..."
    rm -rf "$APP_DIR"
  fi

  echo "Removing CLI commands..."
  rm -f /usr/local/bin/dbot /usr/local/bin/d-bot

  echo "Darvish D Bot has been completely removed."
}

case "${1:-menu}" in
  start) cd "$APP_DIR" && $COMPOSE up -d ;;
  stop) cd "$APP_DIR" && $COMPOSE down ;;
  restart) cd "$APP_DIR" && $COMPOSE restart ;;
  logs) cd "$APP_DIR" && $COMPOSE logs -f --tail=200 ;;
  update) update_app ;;
  backup) backup_app ;;
  analytics) install_analytics "${2:-show}" ;;
  mysql) restore_mysql_users "${2:-}" ;;
  restore)
    case "${2:-}" in
      mysql|wizwiz-users) restore_mysql_users "${3:-}" ;;
      *)
        echo "Usage: dbot mysql"
        echo "       dbot mysql /path/to/wizwiz_users.sql"
        echo "       dbot mysql /path/to/wizwiz_users.zip"
        echo "Also supported: dbot restore mysql /path/to/file"
        ;;
    esac
    ;;
  status) cd "$APP_DIR" && $COMPOSE ps ;;
  env) cd "$APP_DIR" && nano .env ;;
  remove|uninstall) uninstall_app "${2:-}" ;;
  menu|*)
    echo "Darvish D Bot VPS commands:"
    echo "dbot start                 Start bot"
    echo "dbot stop                  Stop bot"
    echo "dbot restart               Restart bot"
    echo "dbot logs                  Show logs"
    echo "dbot status                Show containers"
    echo "dbot env                   Edit .env"
    echo "dbot update                Pull/rebuild app"
    echo "dbot backup                Create database and project backup"
    echo "dbot analytics             Show installation stats"
    echo "dbot analytics generate    Regenerate install chart SVG"
    echo "dbot mysql                 Restore WizWiz/MySQL users; asks for backup path"
    echo "dbot mysql <file>          Restore WizWiz/MySQL users from SQL or ZIP"
    echo "dbot uninstall             Remove app, keep backups under /root/d-bot-backups"
    echo "dbot uninstall --purge     Remove app and delete backups"
    ;;
esac
EOFCLI
  chmod +x /usr/local/bin/dbot
  ln -sf /usr/local/bin/dbot /usr/local/bin/d-bot
  ok "Manager command installed: dbot"
}

record_install_analytics(){
  cd "$APP_DIR"
  if [ -f scripts/install_analytics.py ]; then
    info "Updating local installation chart..."
    python3 scripts/install_analytics.py record --source "install.sh" >/dev/null 2>&1 || true
  fi
}

start_app(){
  cd "$APP_DIR"
  info "Building and starting Docker containers..."
  $COMPOSE up -d --build
  echo
  ok "Darvish D Bot has been installed successfully."
  echo
  cat <<'EOF'
Useful commands:

  dbot logs
  dbot restart
  dbot status
  dbot backup
  dbot update
  dbot uninstall --purge
EOF
}

main(){
  need_root
  banner
  install_base_packages
  install_docker
  get_project
  collect_config
  patch_compose
  create_manager_command
  start_app
  record_install_analytics
}

main "$@"
