#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" = 0 ] || { echo 'Web updater requires root installation'; exit 1; }
command -v systemctl >/dev/null || { echo 'VPS web updater requires systemd'; exit 1; }
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
ExecStart=/usr/bin/python3 /usr/local/lib/dbot-web-update-worker.py "$app_dir"
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
install -m 700 "$app_dir/scripts/host-maintenance.py" /usr/local/lib/dbot-host-maintenance.py
cat > /etc/systemd/system/dbot-maintenance.service <<EOF
[Unit]
Description=D BOT disposable cache and temporary backup maintenance
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/lib/dbot-host-maintenance.py "$app_dir"
EOF
cat > /etc/systemd/system/dbot-maintenance.timer <<'EOF'
[Unit]
Description=Check D BOT 45-day maintenance schedule
[Timer]
OnBootSec=10min
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now dbot-maintenance.timer
systemctl enable dbot-web-update.service
if [ "${1:-}" != '--defer-restart' ]; then
  rm -f "$app_dir/.web-update/ready"
  systemctl restart dbot-web-update.service
  for attempt in $(seq 1 15); do
    if systemctl is-active --quiet dbot-web-update.service && [ -f "$app_dir/.web-update/ready" ]; then
      echo 'VPS web updater connected.'
      exit 0
    fi
    sleep 1
  done
  echo 'VPS web updater did not become ready. Check: journalctl -u dbot-web-update.service -n 50'
  exit 1
fi
