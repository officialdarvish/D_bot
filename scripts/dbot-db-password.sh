# Sourced by setup and the VPS control menu.
read_db_password(){
  local default="${1:-}" value hint=""
  if [ -n "$default" ]; then hint=" (Enter to generate)"; fi
  echo "PostgreSQL password: 12–128 English letters, digits, _ or -." >&2
  while true; do
    if ! IFS= read -r -s -p "PostgreSQL password${hint}: " value; then
      echo >&2
      return 1
    fi
    echo >&2
    value="${value:-$default}"
    if [[ "$value" =~ ^[a-zA-Z0-9_-]{12,128}$ ]]; then
      printf '%s\n' "$value"
      return 0
    fi
    echo "Invalid password. Use 12–128 English letters, digits, _ or -. Try again." >&2
  done
}
