#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${DBOT_APP_DIR:-/opt/d-bot}"
BIN_DIR="${DBOT_BIN_DIR:-/usr/local/bin}"
LAUNCHER="$APP_DIR/scripts/dbot-launcher.sh"
CONTROL="$APP_DIR/scripts/dbot-control.sh"
TARGET=""

if [ -f "$LAUNCHER" ]; then
  TARGET="$LAUNCHER"
elif [ -f "$CONTROL" ]; then
  TARGET="$CONTROL"
else
  echo "D Bot CLI repair failed: neither launcher nor control script exists under $APP_DIR/scripts" >&2
  exit 1
fi

chmod 755 "$TARGET"
[ ! -f "$CONTROL" ] || chmod 755 "$CONTROL"
mkdir -p "$BIN_DIR"

# Use a symlink into the live project instead of copying a shell script.
# Git/update can replace the project file and the command immediately follows it.
rm -f "$BIN_DIR/dbot" "$BIN_DIR/d-bot"
ln -s "$TARGET" "$BIN_DIR/dbot"
ln -s "$BIN_DIR/dbot" "$BIN_DIR/d-bot"
hash -r 2>/dev/null || true

echo "D Bot CLI repaired: $BIN_DIR/dbot -> $TARGET"
