<p align="center"><img src="docs/images/logo.png" alt="D BOT" width="130" /></p>
<h1 align="center">D BOT</h1>
<p align="center"><b>Your VPN shop. Your customers. One connected platform.</b></p>
<p align="center"><a href="README.md">🇬🇧 English</a> · <a href="README_FA.md">🇮🇷 فارسی</a></p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.3.0-7c3aed?style=flat-square" alt="Version 1.3.0" />
  <img src="https://img.shields.io/badge/Mini_App-Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white" alt="Telegram Mini App" />
  <img src="https://img.shields.io/badge/Database-PostgreSQL_16-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/Deploy-Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker deployment" />
</p>

<p align="center"><img src="docs/images/readme-hero-neon.png" alt="D BOT — Telegram VPN sales, reseller automation and web administration" width="100%" /></p>

<p align="center">
  <a href="#features">Explore features</a> ·
  <a href="#install">Quick install</a> ·
  <a href="https://youtu.be/g2625m5gqBc">Watch D BOT</a> ·
  <a href="https://www.youtube.com/@officialdarvish">YouTube</a>
</p>

**From the first purchase to the next renewal, keep your VPN business in one connected workspace.** D BOT brings your Telegram shop, customer Mini App and reseller operations together with a dedicated web admin panel.

<table>
  <tr>
    <td width="33%" align="center" valign="top"><h3>🤖<br>Telegram Bot</h3><p>Sell subscriptions, deliver configurations and stay in touch with customers.</p></td>
    <td width="33%" align="center" valign="top"><h3>📱<br>Modern Mini App</h3><p>Buy, pay, request trials, track orders and manage services inside Telegram.</p></td>
    <td width="33%" align="center" valign="top"><h3>🖥️<br>Web Admin</h3><p>Manage servers, plans, users, payments and reports in EN / FA.</p></td>
  </tr>
</table>

<a id="features"></a>

## ✨ Built for your daily workflow

| Feature | What you get |
| --- | --- |
| 💱 Flexible pricing | Local prices in Toman or USD with automatic conversion through the configured exchange-rate system. |
| 💳 Payments & wallet | Card-to-card receipts, approval, wallet payments and top-ups; optional NOWPayments. |
| 🎫 Customer care | Tickets and replies, direct support, rules and per-app guides with tutorial videos. |
| 🏷️ Discounts | Fixed or percentage codes, usage limits and plan/server restrictions. |
| 🔔 Notifications | Payment and purchase updates, expiry/traffic alerts and administrator notifications. |
| 🎨 Make it yours | Edit bot buttons and messages; customize Mini App appearance and shortcuts. |
| 🔌 Telegram connectivity | Direct, HTTP/SOCKS, MikroTik SOCKS or V2/Xray routes, including Iranian VPS deployments. |
| 📊 Financial insight | Sales/order reports, reseller billing history and scheduled sales PDFs. |
| 🧰 Backups your way | Manual/scheduled database backups, full project archives and restore on another installation. |


### 🤝 Three ways to grow your reseller network

<table>
  <tr>
    <td width="33%" align="center" valign="top"><h3>📦<br>Volume</h3><p>Prepaid traffic packages and controlled sellable capacity.</p></td>
    <td width="33%" align="center" valign="top"><h3>⚡<br>Pay As You Go</h3><p>Usage-based billing with wallet and consumption tracking.</p></td>
    <td width="33%" align="center" valign="top"><h3>🌐<br>PasarGuard Panels</h3><p>Sell dedicated reseller web panels with scoped access.</p></td>
  </tr>
</table>

### 🔗 Connect the panels you use

| Sanaei / 3x-ui / X-UI | PasarGuard | MikroTik / OpenVPN |
| :---: | :---: | :---: |
| Xray services | Public & reseller services | Router & OpenVPN services |

Multi-server support with inbound/group policies. Available operations follow provider permissions.

<a id="install"></a>

## 🚀 From setup to your first sale

On a fresh Linux VPS, point your domain at the server and run:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```

1. **Install:** configure domain/SSL, Telegram credentials, web login and PostgreSQL.
2. **Complete Setup Wizard:** choose channel/rule options, bot/support details, home message and private web path; click **Save and complete setup**.
3. **Start selling:** connect your panels, add plans and enable the Mini App from the web admin.

<details>
<summary><b>⌨️ Setup & quick commands</b></summary>

Run `dbot` or `dbot menu` to open the Control Center. Enter the menu number or use its direct command:

| Menu | Command | Action |
| --- | --- | --- |
| 1 / 2 | `dbot status` / `dbot logs` | Container status / live logs (`Ctrl+C` to exit logs) |
| 3 / 4 / 5 | `dbot restart` / `dbot start` / `dbot stop` | Manage services |
| 6 | `dbot update` | Update and rebuild |
| 7 | `dbot backup` | Full project backup using the saved protection mode |
| 8 / 9 | — | View / edit setup values |
| 10 / 11 | — / `dbot credentials` | Nginx/SSL / Credentials Center |
| 13 | `dbot backups` | Manage saved backups |
| 0 | — | Exit menu |

Use `dbot backup-keys` to export the registered private recovery keys. Save sensitive output in a safe location with `umask 077`.

</details>

## 🔐 Choose how your backups are protected

Choose the mode in **Backup & Restore** or **Settings**, then save before creating backups:

| Mode | Recovery on a new VPS |
| --- | --- |
| Normal | No whole-file encryption; the database JSON or project archive is readable. |
| Private key | Use the recovery key or `dbot-recovery-keys.json`. Saving sends all registered backup keys to the configured destination; each delivered private-key backup also sends a separate key-list message. |
| AES password | AES-256-GCM with scrypt; use the password set when the backup was created. The password is not sent with the backup. |

Keep an offline copy of keys/passwords. Anyone with both a private-key backup and its recovery keys can restore it. Changing protection affects new files only. Database `.dbot`/JSON backups restore through web or bot; full project archives use the archive recovery tool. [Backup guide](docs/ENCRYPTED_BACKUPS_FA.md).

<details>
<summary><b>🐳 One Docker stack, connected services</b></summary>

Python / Aiogram / FastAPI + Next.js, with **PostgreSQL 16** for persistent data and **Redis** for runtime state/cache. The web admin and Mini App share the same backend.

<p align="center"><img src="docs/images/stack-diagram.svg" alt="D BOT Docker service architecture" width="100%" /></p>

</details>

## Official Links

| Resource | Link |
| --- | --- |
| GitHub | [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot) |
| Telegram channel | [@officialdarvishchannel](https://t.me/officialdarvishchannel) |
| Telegram bot | [@officialdarvish_bot](https://t.me/officialdarvish_bot) |
| YouTube channel | [@officialdarvish](https://www.youtube.com/@officialdarvish) |
| Introduction & installation | [Watch the tutorial](https://youtu.be/gzTt6hj752A?si=NP7Mwnb17jMunGaH) |
| D BOT v1.2.0 overview | [Watch the video](https://youtu.be/g2625m5gqBc) |
| Donations | [NOWPayments](https://nowpayments.io/donation/officialdarvish) |

## Support the Project

Star the repository, share D BOT, subscribe on YouTube, or [support development with a donation](https://nowpayments.io/donation/officialdarvish).

<p align="center"><a href="https://nowpayments.io/donation/officialdarvish"><img src="https://img.shields.io/badge/Support_D_BOT-NOWPayments-7c3aed?style=for-the-badge" alt="Support D BOT on NOWPayments" /></a></p>

Built with ❤️ by [Darvish](https://github.com/officialdarvish)
