#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" = 0 ] || { echo 'Web updater requires root installation'; exit 1; }
command -v systemctl >/dev/null || exit 0
mkdir -p "$app_dir/.web-update" /usr/local/lib
chmod 700 "$app_dir/.web-update"
install -m 700 "$app_dir/scripts/web-update-worker.py" /usr/local/lib/dbot-web-update-worker.py
cat > /etc/systemd/system/dbot-web-update.service <<EOF
[Unit]
Description=D BOT web update worker
After=docker.service
Requires=docker.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/lib/dbot-web-update-worker.py $app_dir
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable dbot-web-update.service
systemctl restart dbot-web-update.service
