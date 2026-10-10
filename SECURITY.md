# Security Notice

Do not commit or publish real credentials.

Never put these values in README files, screenshots, issues, commits, or public repositories:

- VPS IP address or SSH login
- Web admin username/password
- 3x-ui panel URL, hidden web path, username/password, or API token
- MikroTik/custom-panel API key
- Telegram bot token
- Database password / connection URL
- NOWPayments API key
- Numeric Telegram admin IDs, unless you intentionally want them public

Use placeholders such as:

```env
BOT_TOKEN=CHANGE_ME_BOT_TOKEN
ADMIN_IDS=123456789
WEB_ADMIN_USERNAME=CHANGE_ME_ADMIN_USER
WEB_ADMIN_PASSWORD=CHANGE_ME_STRONG_ADMIN_PASSWORD
PANEL_URL=https://panel.example.com
PANEL_WEB_PATH=/your-hidden-path/
```

If a real secret was published, rotate it immediately and remove it from Git history before making the repository public again.
