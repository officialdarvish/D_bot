# D Bot

**D Bot** is an open-source Telegram bot and Cyber Admin panel for selling and managing VPN services.

It supports public users, resellers, wallet payments, manual receipts, discount codes, service categories, test accounts, backups, and server integrations such as **3x-ui / X-UI** and **MikroTik / Custom Panel**.

---

## Features

- Telegram sales bot for VPN services
- Modern web admin panel
- Public plans and reseller packages
- Wallet, card-to-card receipt flow, and crypto-ready settings
- Discount codes with usage limits and server restrictions
- Server categories, multi-server category selection, and service badges
- 3x-ui / X-UI integration
- MikroTik / Custom Panel integration
- OpenVPN profile delivery
- Backup and restore tools
- Docker-based deployment

---

## Requirements

- Ubuntu/Debian VPS
- Docker and Docker Compose
- Telegram Bot Token from BotFather
- Numeric Telegram admin ID
- Domain name for the admin website, optional but recommended

---

## Quick Install

```bash
git clone https://github.com/officialdarvish/D_bot.git
cd D_bot
cp .env.example .env
nano .env
docker compose up -d --build
```

Or use the installer:

```bash
sudo bash install.sh
```

After installation, open:

```text
https://your-domain.com/admin
```

---

## Environment

Copy `.env.example` to `.env` and fill only your private values.

Important values:

```env
BOT_TOKEN=CHANGE_ME_BOT_TOKEN
ADMIN_IDS=123456789
WEB_ADMIN_USERNAME=CHANGE_ME_ADMIN_USER
WEB_ADMIN_PASSWORD=CHANGE_ME_STRONG_ADMIN_PASSWORD
DATABASE_URL=postgresql+asyncpg://dbot:CHANGE_ME_DB_PASSWORD@db:5432/d_bot
FERNET_KEY=CHANGE_ME_FERNET_KEY
```

Never publish your real `.env` file.

---

## Useful Commands

```bash
docker compose up -d --build
docker compose logs -f bot
docker compose logs -f api
docker compose down
```

---

## Project Structure

```text
app/              Telegram bot, API, services, database models
frontend/         Next.js admin panel source
scripts/          Runtime helper scripts
Dockerfile        Production Docker build
docker-compose.yml
.env.example
README.md
SECURITY.md
LICENSE
```

---

## Security

Do not commit or publish:

- VPS IP or SSH login
- Telegram bot token
- Web admin username/password
- Database password
- Panel URL, hidden panel path, username/password, or API token
- MikroTik / Custom Panel API key
- Payment provider API keys

If a real secret was ever pushed to a public repository, rotate it immediately and clean the Git history.

More details: [`SECURITY.md`](SECURITY.md)

---

## Official Links

- GitHub: `https://github.com/officialdarvish/D_bot`
- Telegram Channel: `https://t.me/officialdarvishchannel`
- Telegram Bot: `https://t.me/officialdarvish_bot`

---

## Support The Project

If this project helps you, you can support development here:

- Donation: `https://nowpayments.io/donation/officialdarvish`

---

## Copyright

Copyright © 2026 Darvish.

All rights reserved.
