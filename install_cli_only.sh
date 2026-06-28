#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [ "${EUID}" -ne 0 ]; then
  echo "Please run as root. Use: sudo -i"
  exit 1
fi
if [ ! -f scripts/dbot ]; then
  echo "scripts/dbot was not found. Run this script from the extracted VPN Bot source folder."
  exit 1
fi
install -m 0755 scripts/dbot /usr/local/bin/dbot
ln -sf /usr/local/bin/dbot /usr/local/bin/d-bot
echo "VPN Bot CLI updated."
echo "Check it with: dbot"
echo "Restore WizWiz users with: dbot mysql"
