#!/usr/bin/env bash
set -e

APP_DIR="${DBOT_APP_DIR:-/opt/d-bot}"
CONTROL_SCRIPT="$APP_DIR/scripts/dbot-control.sh"

if [ ! -f "$CONTROL_SCRIPT" ]; then
  echo "D Bot control script was not found: $CONTROL_SCRIPT" >&2
  echo "If D Bot is installed elsewhere, set DBOT_APP_DIR before running dbot." >&2
  exit 1
fi

# Always execute the control script from the currently installed project.
# This prevents /usr/local/bin/dbot from becoming stale after `dbot update`.
exec bash "$CONTROL_SCRIPT" "$@"
