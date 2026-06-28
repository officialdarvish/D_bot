<div align="center">

# Darvish D Bot

### Advanced Telegram VPN Sales Bot + Cyber Admin Panel

[فارسی](README_FA.md) • [English](README.md)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Admin%20API-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Cache-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)

</div>

---

## 📌 About

**Darvish D Bot** is a modular Telegram bot and web admin platform for selling and managing VPN services. It is designed for V2Ray / X-UI / 3x-ui based services, reseller packages, wallet payments, manual card-to-card receipts, discount codes, backups, reports, and a modern cyber-style admin website.

The project includes:

- Telegram bot for customers, resellers, and admins
- FastAPI backend and web admin API
- PostgreSQL database
- Redis cache
- Modern Cyber Admin UI
- Docker and one-command VPS installer
- Backup & Restore system
- PDF sales reports
- Website SSL management

---

## 📢 Official Links

- Telegram Channel: [officialdarvishchannel](https://t.me/officialdarvishchannel)
- Telegram Bot: [@officialdarvish_bot](https://t.me/officialdarvish_bot)
- GitHub Repository: [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot)

---

## 🚀 Quick Install on VPS

Run as root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```

The installer asks for:

- Telegram bot token
- Numeric admin Telegram ID
- Domain name
- PostgreSQL database name
- PostgreSQL username
- PostgreSQL password

At the end of installation, the VPS terminal displays the generated website login information:

```text
Login URL
Web Admin Username
Web Admin Password
Role: Owner
```

Save this information. You can also show it later with:

```bash
dbot credentials
```

---

## ✨ Main Features

### Telegram Bot

- Customer purchase flow
- Public plans and reseller plans
- Wallet payment support
- Card-to-card receipt approval
- Crypto payment support through NOWPayments
- Discount codes by percent or fixed Toman amount
- Reseller request and approval flow
- Test account flow
- Tickets and support flow
- Admin management flows
- X-UI / 3x-ui integration

### Cyber Admin Website

- Secure owner login page
- Modern dark dashboard
- Revenue overview
- Recent orders and recent activities
- Users management
- Resellers management
- Public plans and reseller packages
- Servers and categories management
- Payment methods management
- Discount codes management
- Backup & Restore page
- Website & SSL settings
- PDF sales export
- Profile image for admin header

### Backup & Restore

- Configure backup destination from the website
- Send backups to channel, group, or backup bot
- Test destination access before saving
- Manual backup run
- Local JSON restore and database synchronization
- Backup and restore actions are intended to be managed from the website

### Website & SSL

- Set or change website domain from admin panel
- Apply SSL from the website panel
- Show SSL success or error status
- Change web admin username and password
- Automatic logout after changing web credentials

---

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| Bot | Python, aiogram |
| API | FastAPI, Uvicorn |
| Database | PostgreSQL |
| Cache | Redis |
| Web UI | Next.js, React, Tailwind CSS |
| Charts | Recharts |
| Icons | Lucide Icons |
| Animation | Framer Motion |
| Deployment | Docker Compose |
| SSL | Nginx + Certbot |

---

## ✅ Requirements

Recommended VPS:

- Ubuntu 22.04 or 24.04
- Root access
- 1 CPU minimum
- 1 GB RAM minimum, 2 GB recommended
- A domain pointed to the VPS IP
- Open ports: `80`, `443`, and optional API port `8000`

Required accounts:

- Telegram bot token from BotFather
- Numeric Telegram admin ID
- Optional NOWPayments account for crypto payments

---

## 🔐 Web Admin Login

After installation, open:

```text
https://your-domain.com/login
```

Default role name inside the website is:

```text
Owner
```

If you change the website username or password from:

```text
Settings → Website & SSL
```

The system logs out automatically. You must log in again with the new credentials.

---

## 🧰 VPS Management Commands

After installation, use the `dbot` command:

```bash
dbot credentials           # Show web admin URL, username and password
dbot start                 # Start bot and API containers
dbot stop                  # Stop containers
dbot restart               # Restart containers
dbot logs                  # Show live logs
dbot status                # Show container status
dbot env                   # Edit .env file
dbot update                # Pull/rebuild/update project
dbot backup                # Create database and project backup
dbot mysql                 # Restore WizWiz/MySQL users interactively
dbot mysql /path/file.sql  # Restore WizWiz/MySQL users from SQL
dbot mysql /path/file.zip  # Restore WizWiz/MySQL users from ZIP
dbot uninstall             # Remove app but keep backups
dbot uninstall --purge     # Remove app and delete backups
```

---

## 🤖 Telegram Owner Commands

These commands are available only for owner/admin Telegram IDs:

```text
/websetup
/websetup example.com
/site_setup example.com
/sslsetup example.com
```

`/websetup example.com` saves the website domain, requests SSL on the VPS, then asks for the website owner username and password. After saving, open `https://example.com/admin` and log in with the new credentials.

Test Account management is available from:

```text
Admin Panel → Test Account
```

From this card you can enable/disable trial accounts, hide/show the Telegram test-account button, choose the server, set inbound IDs, volume, duration, and reset trial usage history.

---

## ⚙️ Environment Variables

Main `.env` values:

```env
BOT_TOKEN=123456789:REPLACE_WITH_YOUR_BOT_TOKEN
ADMIN_IDS=708872939
DATABASE_URL=postgresql+asyncpg://dbot:password@db:5432/d_bot
REDIS_URL=redis://redis:6379/0
API_HOST=0.0.0.0
API_PORT=8000
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=change_this_admin_password
DOMAIN_NAME=example.com
LETSENCRYPT_EMAIL=
FERNET_KEY=
DEFAULT_CHANNEL_URL=https://t.me/officialdarvishchannel
PAYG_MIN_BALANCE_IRT=300000
PAYG_SCAN_MINUTES=60
TZ=Asia/Tehran
SERVER_SYNC_SECONDS=600
NOWPAYMENTS_ENABLED=false
NOWPAYMENTS_API_KEY=
NOWPAYMENTS_IPN_SECRET=
NOWPAYMENTS_PAY_CURRENCY=trx
NOWPAYMENTS_PRICE_CURRENCY=usd
NOWPAYMENTS_API_URL=https://api.nowpayments.io/v1
NOWPAYMENTS_IPN_CALLBACK_URL=
```

Important notes:

- Never publish `.env`.
- Use a strong PostgreSQL password.
- Use a secure `FERNET_KEY`.
- Change web admin credentials after first login.

---

## 🐳 Docker Commands

Build image locally:

```bash
docker build --no-cache -t darvish021/d_bot:latest .
```

Push image:

```bash
docker push darvish021/d_bot:latest
```

Start with Docker Compose:

```bash
docker compose up -d --build
```

Restart:

```bash
docker compose restart
```

Logs:

```bash
docker compose logs -f --tail=200
```

---

## 🖥️ Admin Website Pages

| Page | Purpose |
|---|---|
| Dashboard | Sales, orders, resources, recent activities |
| Service Types | Manage service type labels |
| Plans | Public plans and reseller packages |
| Payments | Card-to-card/payment destination accounts |
| Orders Report | Order list and PDF export |
| Discount Codes | Percent and fixed Toman discount codes |
| Users | Telegram users, wallet, reseller status |
| Resellers | Reseller capacity, traffic, expiry |
| Servers | X-UI / 3x-ui servers and inbound refresh |
| Categories | Server/plan categories |
| Backup & Restore | Backup destination, test, manual backup, restore |
| Settings | Bot texts, rules, status, database info, website login, SSL |

---

## 📄 PDF Sales Report

From the dashboard or Orders Report page, use:

```text
Export PDF
```

The PDF report includes:

- Date range
- Total sales
- Order count
- Order ID
- Date
- User
- Plan
- Payment method
- Status
- Amount in Toman

Persian and Unicode text are supported.

---

## 💾 Backup & Restore Guide

Open:

```text
Admin Panel → Backup & Restore
```

Available destinations:

- Channel
- Group
- Backup bot/private bot

For channel and group, use the Test button to verify access. If the bot has the required admin permission, the panel shows a success status.

Restore:

1. Open Backup & Restore.
2. Select a local JSON backup file.
3. Click Restore & Sync.
4. The system synchronizes the database based on the backup structure.

---

## 🌐 SSL Guide

Open:

```text
Settings → Website & SSL
```

Set the domain, then click:

```text
Apply SSL
```

The website shows whether SSL was applied successfully or failed. DNS must point to the VPS IP and ports `80` and `443` must be open.

---

## 🧪 Development Commands

Frontend development:

```bash
cd frontend
npm install
npm run dev
npm run build
```

Backend/API development:

```bash
pip install -r requirements.txt
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Bot development:

```bash
python -m app.main
```

Compile check:

```bash
python -m compileall -q app
```

---

## 📁 Project Structure

```text
app/
  api/              FastAPI admin API and website routes
  bot/              Telegram bot handlers and keyboards
  core/             Settings, security and logging
  database/         SQLAlchemy models and sessions
  jobs/             Background jobs
  services/         Business services
  xui/              X-UI / 3x-ui client
frontend/
  app/              Next.js pages
  components/       Cyber Admin components
  lib/              Frontend API helpers
frontend_out/       Static exported admin website
docker-compose.yml  PostgreSQL, Redis, API and bot services
install.sh          One-command VPS installer
scripts/            Utility scripts
```

---

## 🛠️ Troubleshooting

### Website does not open

```bash
dbot status
dbot logs
```

Make sure the API container is running and the domain points to your VPS.

### SSL failed

Check DNS and ports:

```bash
ufw status
nginx -t
```

Then retry from:

```text
Settings → Website & SSL → Apply SSL
```

### I forgot the website login

Use:

```bash
dbot credentials
```

If you changed the website login from the admin panel, the latest value is stored in the database. Use the website settings carefully and save the new credentials immediately.

### Docker build issue

Use:

```bash
docker build --no-cache -t darvish021/d_bot:latest .
```

Then restart:

```bash
docker compose up -d --force-recreate
```

---

## 🔒 Security Notes

- Keep `.env` private.
- Do not share bot token, database password, FERNET key, panel passwords, or NOWPayments secrets.
- Change default website credentials after first login.
- Keep your VPS updated.
- Give Telegram bot admin access only where required.

---

## ❤️ Support The Project

If you enjoy Darvish Bot and want to support future development, you can donate with TRX or other supported crypto through NOWPayments:

<p align="center">
  <a href="https://nowpayments.io/donation/officialdarvish">
    <img src="https://img.shields.io/badge/Donate%20with%20TRX-NOWPayments-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX">
  </a>
</p>

Donation link:

```text
https://nowpayments.io/donation/officialdarvish
```

---

## ⚖️ Copyright, Usage & Permission

This project belongs to the Darvish Bot owner. Copying, reselling, redistributing, publishing modified versions, or using the project source for another public/private product is allowed only after receiving permission from the project owner.

For permission, contact the official project owner through the official Telegram links above.

---

<div align="center">

**Darvish D Bot — Built for professional VPN sales automation**

</div>


## UI v9 Final Fixes

- Website & SSL can request API/site and bot restart after successful SSL.
- Users page has pagination for more than 100 users.
- Test Account supports usage reset and inbound chip selection.
- Server add/edit/refresh tests the panel and syncs inbounds.
- Plan server changes sync inbound IDs correctly.
- Reseller page shows reseller menu plans.


## 3x-ui Panel Connection Notes

D BOT supports MHSanaei 3x-ui panel connections using the official panel session login and inbounds API. Enter the panel origin and web base path correctly:

```text
Panel URL / Origin: https://your-domain.com:PORT
Panel Web Path: /your-secret-path/
Username: your 3x-ui username
Password: your 3x-ui password
```

You can also paste a full panel URL such as `https://your-domain.com:PORT/your-secret-path/`; D BOT normalizes common `/login` and `/panel/api/...` tails automatically. Optional API token mode is supported by entering `token:<API_TOKEN>` in the password/token field.

## 3x-ui Hidden Path / CSRF Login Note

For newer 3x-ui panels with a hidden web base path, enter the panel origin and web path separately:

```text
Panel URL / Origin: https://panel.example.com
Panel Web Path: /your-hidden-path/
```

The D BOT XUI client now logs in by first loading the panel base path to receive the `3x-ui` cookie and CSRF token, then posts to `/login`, and finally calls `/panel/api/inbounds/list` with the same session.

## 3x-ui Client API Compatibility

D BOT uses the current 3x-ui Client API for client create, update, delete, renew, revoke/new-link, traffic reset, online users and IP checks. Hidden panel paths are supported through `Panel URL / Origin` plus `Panel Web Path`.

For example:

```text
Panel URL / Origin: https://panel.mgiftshop.ir
Panel Web Path: /U76peSug8RbmlymBHQ/
```
