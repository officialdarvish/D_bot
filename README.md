<p align="center">
  <img src="docs/images/logo.png" alt="Darvish Bot Logo" width="220" />
</p>

<h1 align="center">Darvish Bot</h1>

<p align="center">
  <b>Professional Telegram VPN sales and management bot for X-UI / 3X-UI panels.</b>
</p>

<p align="center">
  <a href="https://t.me/officialdarvishchannel"><img src="https://img.shields.io/badge/Telegram-Channel-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Channel"></a>
  <a href="https://t.me/officialdarvish_bot"><img src="https://img.shields.io/badge/Telegram-Bot-229ED9?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot"></a>
  <a href="https://nowpayments.io/donation/officialdarvish"><img src="https://img.shields.io/badge/Donate-TRX-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX"></a>
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Ready">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+">
</p>

<p align="center">
  <a href="./README.md">🇺🇸 English</a> | <a href="./README_FA.md">🇮🇷 فارسی</a>
</p>

---

## 🚀 Quick Install

Install Darvish Bot on your VPS with one command:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```



---

## ✨ Features

| Feature | Description |
|---|---|
| Telegram user panel | Buy services, manage configs, wallet recharge, tickets, and connection guides |
| Admin panel | Manage users, plans, categories, servers, payments, tickets, and reports |
| Reseller system | Sell traffic packages with role-based access and reseller management |
| X-UI / 3X-UI integration | Create, delete, renew, rotate UUID, and manage panel clients |
| Multi-server support | Add multiple servers and select inbound IDs for service creation |
| Wallet & payments | Card-to-card receipt flow with admin approval |
| Ticket system | User support tickets with admin reply and close actions |
| Docker ready | One-command deployment with PostgreSQL, Redis, API, and bot services |
| Backup & restore | Backup project files and database, then restore when needed |

---

## ⛓️ Supported Panels

- 3x-ui
- X-UI
- Sanaei X-UI
- Multi-inbound Xray panels

---

## 🛠️ Management Commands

After installation, use these commands:

| Command | Description |
|---|---|
| `darvish-bot update` | Pull latest source/image and restart services |
| `darvish-bot edit-env` | Edit the `.env` configuration file |
| `darvish-bot start` | Start all services |
| `darvish-bot stop` | Stop all services |
| `darvish-bot restart` | Restart API, bot, database, and Redis |
| `darvish-bot logs` | View live service logs |
| `darvish-bot backup` | Create a full backup |
| `darvish-bot restore` | Restore from backup |
| `darvish-bot analytics show` | Show local install analytics |
| `darvish-bot analytics generate` | Regenerate the install chart SVG |
| `darvish-bot uninstall` | Remove the project completely |

---

## 📦 Manual Installation

```bash
git clone https://github.com/officialdarvish/D_bot.git
cd D_bot
cp .env.example .env
nano .env
docker compose up -d --build
```

---

## 🐳 Docker Services

```text
Darvish Bot
├── bot        Telegram bot service
├── api        FastAPI backend service
├── db         PostgreSQL database
└── redis      Redis cache/session service
```

---

## 🔐 Security

- Role-based admin access
- Encrypted panel credentials
- Secure environment configuration
- Docker isolated services
- Admin approval for sensitive actions

---

## 📢 Official Links

- Telegram Channel: [officialdarvishchannel](https://t.me/officialdarvishchannel)
- Telegram Bot: [@officialdarvish_bot](https://t.me/officialdarvish_bot)
- GitHub Repository: [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot)

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

## 📈 Installation Analytics

The installer includes a local analytics generator that records installs and creates a README-ready SVG chart.

> GitHub does not automatically expose public install counts for `curl | bash` scripts. This chart is generated from the project analytics file and can be updated with GitHub Actions or by committing the generated stats/chart files.

<p align="center">
  <img src="docs/install_chart.svg" alt="Darvish Bot installation growth chart" width="920" />
</p>

---

Built with ❤️ by [Darvish](https://github.com/officialdarvish)
