<p align="center">
  <img src="docs/images/logo.png" alt="Darvish Bot Logo" width="150" />
</p>

<h1 align="center">Darvish Bot</h1>

<p align="center">
  <b>Professional Telegram VPN sales, customer Mini App, reseller automation and web admin panel.</b>
</p>

<p align="center">
  <a href="./README.md">🇺🇸 English</a> · <a href="./README_FA.md">🇮🇷 فارسی</a>
</p>

<p align="center">
  <a href="https://t.me/officialdarvishchannel"><img src="https://img.shields.io/badge/Telegram-Channel-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Channel"></a>
  <a href="https://t.me/officialdarvish_bot"><img src="https://img.shields.io/badge/Telegram-Bot-229ED9?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot"></a>
  <a href="https://nowpayments.io/donation/officialdarvish"><img src="https://img.shields.io/badge/Donate-TRX-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/FastAPI-Backend-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Aiogram-Telegram%20Bot-2CA5E0?style=flat-square&logo=telegram&logoColor=white" alt="Aiogram">
  <img src="https://img.shields.io/badge/Next.js-Admin%20Panel-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js">
  <img src="https://img.shields.io/badge/PostgreSQL-Database-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-Cache-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready">
</p>

<p align="center">
  <img src="docs/images/readme-hero-neon.png" alt="Darvish Bot overview banner" width="100%" />
</p>

---

> **v1.3.0:** Fractional and greater-than-1 GB trial quotas (e.g. `0.1`, `0.2`, `2.5` GB). See [release notes](docs/RELEASE_1.3.0_FA.md).

## ✨ Overview

**Darvish Bot** is a production-oriented Telegram bot, customer Mini App and web admin panel for selling and managing VPN services. It handles user purchases, reseller traffic packages, wallet balance, card-to-card payments, crypto payments, tickets, server management, service delivery and admin reporting.

<table>
  <tr>
    <td align="center"><b>🤖 Telegram Bot</b><br/>User panel, purchases, configs, tickets</td>
    <td align="center"><b>🖥️ Admin Panel</b><br/>Users, plans, servers, payments, reports</td>
    <td align="center"><b>👥 Resellers</b><br/>Traffic packages, reseller users, refunds</td>
  </tr>
  <tr>
    <td align="center"><b>🔗 Panel Sync</b><br/>3x-ui, X-UI, Sanaei, PasarGuard, MikroTik</td>
    <td align="center"><b>💳 Payments</b><br/>Wallet, card-to-card, NOWPayments</td>
    <td align="center"><b>🐳 Docker</b><br/>API, bot, PostgreSQL, Redis stack</td>
  </tr>
</table>

### 🎨 Custom Text Center UI

The Custom Center interface is English (headings, filters, category/stage tags, statuses, editor controls and confirmations), while the actual user-facing bot message content remains in its original language and uses automatic text direction in the editor and preview.

The web admin **Custom** section is a user-journey editor rather than a broad source-string scanner. It only catalogs text that a normal Telegram user can actually see across start/menu, purchase, payment and receipt review, service delivery, renewals, My Services, wallet/account, tickets, test accounts, reseller flows, private messages, referrals and service alerts. Every item carries a clear English **category** and **journey-stage** tag in the web UI, with dedicated filters for both. The underlying Telegram message text remains unchanged and can still be Persian. Dynamic final messages such as the post-receipt purchase success message, complete service-delivery card and renewal confirmation are explicitly templated so they can be edited safely while preserving runtime placeholders. The UI keeps deferred search and progressive rendering for large catalogs.

### 🎥 YouTube

- [Official Darvish YouTube Channel](https://www.youtube.com/@officialdarvish)
- [D Bot Introduction & Installation Tutorial](https://youtu.be/gzTt6hj752A?si=NP7Mwnb17jMunGaH)

---

## 🚀 Quick Install

Install on a fresh VPS with one command:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```

The installer asks for the domain **before every other setting**. It then installs/starts Nginx, validates the ACME webroot and obtains the Let’s Encrypt certificate. A temporary HTTPS “installation in progress” page stays online while Docker is installed and the application is built. Nginx switches to the API only after `/health` succeeds, so visitors do not see a temporary 502 page.

| Stage | What happens |
|---|---|
| First | Domain and optional Let’s Encrypt email are collected; DNS, ports 80/443, Nginx and SSL are checked immediately |
| 1 | Telegram bot token and owner/admin Telegram ID |
| 2 | Web admin username and password, auto-generated or custom |
| 3 | PostgreSQL database name, user and password |
| 4 | Internal API port, timezone and optional Telegram channel URL |
| 5 | Final review before writing `.env` and starting services |

<details>
<summary>Setup wizard preview</summary>

```text
╔══════════════════════════════════════════════════════════════╗
║                    D Bot Setup Wizard                       ║
╠══════════════════════════════════════════════════════════════╣
║ Fill the required values step by step.                      ║
║ Secrets will be saved only inside /opt/d-bot/.env.          ║
╚══════════════════════════════════════════════════════════════╝

First stage — Domain & SSL
Domain name: panel.example.com
Let’s Encrypt email, optional: admin@example.com
Start Nginx and request SSL now? [Y/n]: y
✓ HTTPS bootstrap page is active: https://panel.example.com

Step 1/5 — Telegram Bot
Telegram Bot Token: 123456789:AAExample_Token-Value
Owner/Admin Telegram ID: 123456789

Step 2/5 — Web Admin Panel
Auto-generate web admin username/password? [Y/n]: y

Step 5/5 — Review
SSL certificate    : active
Web login          : https://panel.example.com/login
Web username       : admin_a1b2c3
Save this setup and continue installation? [Y/n]: y
```

</details>

After installation, open the graphic Control Center with either command. From this menu you can view/edit the values entered in Setup Wizard and manage services:

```bash
dbot
dbot menu
```

Or use only these direct manager commands:

```bash
dbot status
dbot logs
dbot restart
dbot start
dbot stop
dbot update
dbot backup
dbot credentials
dbot uninstall --purge
```

---

## 🧩 Features

| Area | What it includes |
|---|---|
| 🤖 Telegram user panel | Buy services, manage configs, renew services, delete configs, wallet, tickets, guides, progress messages and success Home button |
| 📱 Telegram Mini App | Native purchases and receipt uploads, order tracking, wallet, configurations, trials and reseller workspace |
| 🖥️ Web admin panel | Manage users, plans, categories, servers, payments, reports, test accounts, settings and admin wallet operations |
| 👥 Reseller system | Reseller packages, sellable inventory accounting, cumulative used traffic, active reserved volume, reseller users and short admin notifications for reseller-created configs |
| 🔗 X-UI / 3x-ui integration | Create, delete, renew, rotate UUID and sync clients across supported panels |
| 🛡️ PasarGuard integration | Owner, administrator and restricted/OWN-scope reseller admins via the official PasarGuard REST API |
| 🌐 MikroTik / OpenVPN | User creation and management for MikroTik-based services |
| 🧭 Multi-server support | Add multiple servers, categories, service types and inbound IDs |
| 💳 Wallet & payments | Wallet payments, admin wallet increase/decrease by numeric Telegram ID, card-to-card receipt approval and order tracking |
| ₿ Crypto payments | NOWPayments integration with IPN webhook support |
| 🏷️ Discount codes | Percent/fixed discounts, global usage limit, per-user limit and server scoping |
| 🎫 Tickets | User support tickets with admin replies and close actions |
| 🔔 Admin alerts | Notify owners/admins about new users, reseller-created configs and short structured runtime errors |
| 🧰 Backup & restore | Portable cross-install JSON backup, full database synchronization, credential re-encryption and migration helper commands |
| 🔐 Credentials Center | Live website login URL, current username/password, direct username/password changes, secure password generation and infrastructure-secret view |
| 🐳 Docker deployment | API, bot, PostgreSQL, Redis and admin panel in a Docker-based stack |

---

## 🧳 Portable Backup & Cross-Installation Restore

Backups created from the web admin panel use portable format `4` and can be restored on another VPS or on multiple separate D BOT installations.

- All supported persistent database tables are exported and synchronized on restore.
- Server panel passwords are moved through a self-contained encrypted backup envelope and are encrypted again with the destination installation's own `FERNET_KEY`.
- The destination `.env`, `BOT_TOKEN`, database connection and runtime infrastructure are not replaced.
- A SHA-256 integrity checksum detects incomplete or modified backup files.
- Restore performs credential and structure preflight checks before deleting destination data.
- Old formats `1` to `3` remain readable when their server credentials can be decrypted with the current key. For a legacy backup created with another `FERNET_KEY`, update the source installation and create a new portable backup.

When only a legacy JSON file and the old source `FERNET_KEY` are available, convert it locally:

```bash
python3 scripts/convert_legacy_backup.py dbot_backup.json dbot_portable_backup_v4.json
```

The converter requests the old key with hidden input, or accepts `LEGACY_FERNET_KEY` from the environment.

> Portable backups contain recoverable service credentials. Keep every backup file private and send it only through a trusted destination.

---

## ⛓️ Supported Panels

<table>
  <tr>
    <td align="center"><b>3x-ui</b></td>
    <td align="center"><b>X-UI</b></td>
    <td align="center"><b>Sanaei X-UI</b></td>
    <td align="center"><b>PasarGuard</b></td>
    <td align="center"><b>MikroTik / OpenVPN</b></td>
    <td align="center"><b>Multi-inbound Xray</b></td>
  </tr>
</table>

### 🛡️ PasarGuard and restricted reseller admins

PasarGuard servers use the official PasarGuard REST API. Owner-level access is **not required**. D Bot supports both current RBAC profiles and older/legacy reseller profiles that do not expose the full `role.permissions` object through `/api/admin`.

A restricted reseller/operator account can be used when its role permits the required user operations. PasarGuard's own scope and limits remain authoritative:

- `users.create` is required to provision new services.
- `users.read` may be scoped to **OWN**, so D Bot only reads services owned by the configured PasarGuard admin.
- `users.delete` may also be scoped to **OWN**. It is useful for manual deletion and the delete/recreate renewal fallback, but it is not required just to register a server or sell a normal new service.
- `users.update` and `users.reset_usage` are recommended for normal in-place renewal. If reset is denied but update is allowed, D Bot preserves the subscription and extends quota by the fresh plan allowance. If update/reset are denied but create/delete are allowed, D Bot can recreate the same admin-owned username as a final renewal fallback.
- `groups.read_simple` is recommended but optional. Group discovery is automatic: visible PasarGuard groups → role `allowed_group_ids` → group IDs observed on users owned by this admin → group IDs exposed by allowed/visible PasarGuard templates → the last automatically synchronized group cache. Legacy panels also fall back from the lightweight group endpoint to the full group-list endpoint. An explicit empty `allowed_group_ids` list from current RBAC is respected. There is no manual Group ID field in Add Server.
- If the role has `require_template=true`, D Bot uses PasarGuard's official user-template endpoints. Template IDs are not entered when adding a server. D Bot discovers the allowed/visible templates and selects the matching template automatically for each D Bot plan using quota, duration, groups and HWID metadata.
- PasarGuard role limits such as maximum users, traffic range, expiry range and HWID limits are enforced by PasarGuard and are not bypassed by D Bot.
- Public plans can set an explicit HWID device limit for both Sanaei/3x-ui and PasarGuard. In **My Configs**, PasarGuard services expose the registered HWID/device list and a user-owned **Reset HWID** action through PasarGuard's official ID-based HWID API. Editing a plan also propagates the new HWID cap to active PasarGuard services.

In **Admin Web → Service Types**, each user-facing service type can be bound to a **Backend provider**. Choose **PasarGuard** for service types whose plans use PasarGuard servers, **X-UI / 3x-ui** for Xray/Sanaei servers, or **MikroTik** for OpenVPN/L2TP. **Auto detect** is retained for older installations. The purchase menu only shows categories that have an active plan on the selected provider, and saving a plan keeps its category linked to the selected server.

**PasarGuard categories in the V2Ray purchase menu (v1.2.0 fix):** When you link an active Category to a public PasarGuard server, it can be displayed alongside Sanaei / 3x-ui categories under the same **V2Ray** Service Type. Open **Service Types → Edit → Backend provider** and choose **V2Ray — Sanaei / 3x-ui + PasarGuard** for an explicit combined menu. Legacy X-UI V2Ray service types auto-include PasarGuard when there is no separate PasarGuard-specific Service Type. Alternatively, choose PasarGuard for a separate menu. Each plan is still provisioned using its actual server's provider. Inactive and reseller-only servers remain unsellable.

In **Admin Web → Servers → Add Server**, select **PasarGuard**, enter the PasarGuard dashboard URL or origin (subpaths such as `/hub/` are supported), then authenticate with either username/password or **API Token Panel** and use **Test & Auto Fill**. D Bot detects the REST API base, reseller scope, allowed groups and allowed templates automatically. When modern RBAC metadata is unavailable, it uses safe read-only API probes instead of treating every missing permission field as denied. Group IDs and Template IDs are never entered manually during server setup.

### 🌐 Bilingual Web Panel

The web panel supports **EN / FA** from the sidebar. English uses LTR layout and Persian uses RTL layout with Persian web typography. The selected language is stored in the browser. User-generated data and the actual Telegram bot message content are not machine-translated.

### 🔌 Telegram Connection

The **Connection** page can route only Telegram bot traffic through Direct, HTTP/SOCKS proxy, MikroTik SOCKS5, or V2/Xray (`VLESS`, `VMess`, `Trojan`, `Shadowsocks`). Connection secrets are stored encrypted, and the page includes a Telegram connectivity test before applying a route.

---


## 🎛️ Custom Bot Text Center

The web admin panel includes **Custom** directly above **Settings**. The catalog is intentionally scoped to the **normal user's interaction surface**, not every Persian string in the project. It scans public bot handlers and user-notification paths only, and excludes admin-only handlers, internal services, callback data, API/database values, logs and technical strings. Each editable item has an English category tag (for example Purchase & Payment, My Configs, Account & Wallet, Support & Tickets, Reseller) plus a more specific English journey-stage tag (for example Receipt & Approval, Service Delivery, Renewal Result). Important composed outputs are explicitly templated, including the final message after a card-to-card receipt is approved, the full delivered-service card, renewal confirmations and receipt-rejection messages. Dynamic placeholders such as usernames, plan names, amounts and traffic values remain available for safe customization. Overrides are stored in the existing `settings` table, so no migration is required.

<!-- D BOT Custom Text Center -->

## 🏗️ Architecture

<p align="center">
  <img src="docs/images/stack-diagram.svg" alt="Darvish Bot service architecture" width="100%" />
</p>

```text
Darvish Bot
├── app/                  Python backend, bot handlers, API, jobs and services
├── frontend/             Next.js web admin panel
├── scripts/              Helper scripts
├── Dockerfile            Main production Docker build
├── docker-compose.yml    API, bot, PostgreSQL and Redis services
├── install.sh            One-command VPS installer
├── README.md             English documentation
└── README_FA.md          Persian documentation
```

---

## 📦 Manual Installation

```bash
git clone https://github.com/officialdarvish/D_bot.git
cd D_bot
cp .env.example .env
nano .env
docker compose up -d --build
```

Admin panel URL:

```text
https://YOUR_DOMAIN/login
```

---

## ⚙️ Environment Configuration

Create a `.env` file in the project root and set your private values.

```env
BOT_TOKEN=CHANGE_ME_BOT_TOKEN
OWNER_IDS=123456789
DATABASE_URL=postgresql+asyncpg://dbot:CHANGE_ME_DB_PASSWORD@db:5432/d_bot
POSTGRES_DB=d_bot
POSTGRES_USER=dbot
POSTGRES_PASSWORD=CHANGE_ME_DB_PASSWORD
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD
FERNET_KEY=CHANGE_ME_FERNET_KEY
JWT_SECRET=CHANGE_ME_JWT_SECRET
```

> Never publish your real `.env`, bot token, API keys, panel credentials, server IPs or database passwords.

---

## ₿ NOWPayments Crypto Payments

Darvish Bot can create crypto payment invoices through NOWPayments and process payment status updates through an IPN webhook.

```env
NOWPAYMENTS_ENABLED=true
NOWPAYMENTS_API_KEY=YOUR_API_KEY
NOWPAYMENTS_IPN_SECRET=YOUR_IPN_SECRET
NOWPAYMENTS_PAY_CURRENCY=trx
NOWPAYMENTS_PRICE_CURRENCY=usd
NOWPAYMENTS_IPN_CALLBACK_URL=https://YOUR_DOMAIN/webhooks/nowpayments
```

Webhook endpoint:

```text
/webhooks/nowpayments
```

Orders are marked as paid after confirmed final payment statuses such as `confirmed`, `finished` or `sending`.

---

## 🏷️ Discount Codes

Discount codes support:

- Percent-based discounts
- Fixed-amount discounts
- Global usage limit
- Per-user usage limit
- Optional server/category scoping
- Activate, deactivate, edit and delete actions from the admin panel

---

## 🕹️ Graphic Control Center

The installer adds an interactive VPS control center. Run it with:

```bash
dbot
```

The menu can now **display and edit the values entered during the setup wizard**. Sensitive values are hidden by default and can only be revealed from the terminal after confirmation.

```text
╔══════════════════════════════════════════════════════════════╗
║                    D Bot Control Center                     ║
║        Setup viewer, editor and VPS service manager         ║
╚══════════════════════════════════════════════════════════════╝

Project : D Bot
Path    : /opt/d-bot
Panel   : https://panel.example.com/login
Domain  : panel.example.com
HTTPS   : true

1) Status                  Show containers
2) Logs                    Live logs, Ctrl+C to exit
3) Restart                 Restart all services
4) Start                   Start services
5) Stop                    Stop services
6) Update                  Pull/rebuild and restart
7) Backup                  Create a full backup
8) Setup Info              View values from setup wizard
9) Edit Setup              Change saved .env values
10) Apply Nginx/SSL        Rebuild reverse proxy/certificate
11) Credentials Center     Live username/password and protected secrets
12) Uninstall --purge      Remove app and backups
13) Delete Old Backup      List and delete saved backups
0) Exit
```

Editable setup sections:

| Section | Editable values |
|---|---|
| Telegram | Bot token, admin/owner IDs, default channel URL |
| Website & SSL | Domain, HTTPS on/off, Let’s Encrypt email, internal API port, and Nginx HTTP/HTTPS ports |
| Web Admin | Live admin username/password through the Credentials Center; changes are synchronized with the database |
| Runtime | Timezone and server sync interval |
| Database | PostgreSQL values with an advanced safety warning |

Control Center commands:

| Command | Description |
|---|---|
| `dbot` | Open the graphic Control Center |
| `dbot menu` | Open the same Control Center from VPS |

Direct commands are also supported:

| Command | Description |
|---|---|
| `dbot status` | Show container status |
| `dbot logs` | Show live logs |
| `dbot restart` | Restart all services |
| `dbot start` | Start services |
| `dbot stop` | Stop services |
| `dbot update` | Pull/rebuild and restart |
| `dbot backup` | Create a backup |
| `dbot backups` | Open backup manager for individual/all deletion |
| `dbot backup-list` | List backups from oldest to newest |
| `dbot credentials` | Open the live graphical Credentials Center |
| `dbot uninstall --purge` | Remove the app and delete backups |

---

## 🔐 Security Checklist Before Public Release

- Do not commit `.env` or real credentials.
- Do not commit panel URLs, panel usernames, passwords or tokens.
- Remove runtime files such as logs, backups, dumps, zips and cache files.
- Use `CHANGE_ME` placeholders for examples.
- Rotate any token that was ever committed publicly.

---

## 🔗 Official Links

| Platform | Link |
|---|---|
| Telegram Channel | [officialdarvishchannel](https://t.me/officialdarvishchannel) |
| Telegram Bot | [@officialdarvish_bot](https://t.me/officialdarvish_bot) |
| GitHub Repository | [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot) |
| Donation | [NOWPayments](https://nowpayments.io/donation/officialdarvish) |

---

## ❤️ Support the Project

If Darvish Bot helps you, you can support future development with a crypto donation:

<p align="center">
  <a href="https://nowpayments.io/donation/officialdarvish">
    <img src="https://img.shields.io/badge/Donate%20with%20TRX-NOWPayments-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX">
  </a>
</p>

---

<p align="center">
  Built with ❤️ by <a href="https://github.com/officialdarvish">Darvish</a>
</p>


### PasarGuard dashboard reseller sales (v1.2.0)

Admin Telegram → Resellers → **PasarGuard Reseller Panel Sales** lets the owner select
an active PasarGuard server, set a fixed IRR price, and enable/disable sales.
Configure an active reseller payment card (or a card assigned to that server).
The configured PasarGuard connection must use an HTTPS dashboard URL and
be authorized by PasarGuard to create a restricted OWN-scope role and administrator.
Owner is not required if a delegated Admin has those precise capabilities. Enabling sales verifies/creates a dedicated
`D_BOT_RESELLER_OWN_USERS_V1` role in PasarGuard with only:

- `users.create = true`
- `users.read = {"scope": 1}` (own only)
- `users.update = {"scope": 1}` (own only; renewal by updating expiry)
- `users.delete = {"scope": 1}` (own only)
- `groups.read_simple = true` (read-only names needed in the create-user form)

No access is granted to other users, admins, nodes, or panel settings. If the
existing role is modified to grant extra permissions, orders fail closed.
The requester chooses a unique panel username and strong password (12+ chars,
at least two upper/lower case letters, two digits and a supported symbol), views the fixed price and pays card-to-card.
After an owner confirms the receipt, the bot provisions the limited login
through the official PasarGuard API and privately sends its dashboard URL,
username and password. Passwords are encrypted while awaiting approval and
cleared from the bot database after successful Telegram delivery.

If the upstream API times out during provisioning, the order is flagged
`review_required` rather than blindly retrying and creating duplicates.
The owner must inspect the upstream panel before resolving such orders.
`delivery_pending` orders can retry Telegram delivery without recreating admins.

## PasarGuard Reseller Panel PAYG (v1.2.0)

In Web Admin → **PasarGuard Panel Sales** (immediately after OpenVPN Profiles), configure an HTTPS PasarGuard Reseller server whose Admin credentials permit safe sub-admin provisioning, enabled/disabled sales, initial panel price (0 = free), rate per GiB, rental rate per hour and maximum owned users. Web and Telegram admin screens read/write the same settings keys.

The bot keeps the original reseller request and workflow. It adds an **independent panel-purchase** button when sales are enabled, and a **Purchased Reseller Panels (Website)** button for users who already own a delivered panel. Purchasers can select by username, view their scoped panel URL, explicitly reveal their encrypted-at-rest password, change it, disable or re-enable their own created users, and refresh usage/cost/wallet information.

An APScheduler job in the bot process polls once per minute. Charges are calculated from PasarGuard user consumption scoped to the specific reseller Admin ID and elapsed active-panel hours; usage and debits are committed together against the customer's main wallet. Unpaid usage stays owed if the wallet runs out, and is charged after top-up. On wallet exhaustion, all currently active users owned by that reseller are disabled through PasarGuard's bulk endpoints, with repeated retries on errors. Re-enabling after topping up requires a customer action and does not revive users manually disabled by the customer. The Web Admin order list exposes suspension and last polling error.

**Operational caveats:** The maximum cutoff delay is the polling interval plus PasarGuard API latency (not instantaneous); connections and usage may be affected while remote API is unavailable. Use only one active bot scheduler process. Use a trusted HTTPS PasarGuard connection with delegated admin/role creation permissions and test on a staging server first. Prior purchases without a new PAYG meter are **not retrospectively charged or auto-migrated**. No historical usage is billed on upgrade. No rate changes are retroactively applied to existing PAYG snapshots.


### Customer Plan Conversion

Use **Admin Web → Plans → Convert** to configure the per-GB valuation (in Toman) and allowed servers for each service category. With at least two eligible categories configured, customers can use the **Convert Plan** Telegram menu to choose a source config, destination category, and destination plan/server.

- Destination bytes = `floor(unused_source_bytes * source_category_rate / target_category_rate)`; the destination inherits the **exact source expiry timestamp**.
- Supports active, finite-quota, dated **Sanaei/3x-ui** and **PasarGuard** services. MikroTik/OpenVPN conversions are not yet supported.
- Live provider usage and expiry are validated before a one-time conversion claim is reserved. Source is disabled first, the new client is created and read-back verified, and old-client removal is enqueued for safe retries.
- Ambiguous provider failures are placed in `needs_review` and administrators are alerted, rather than retrying blindly. Test conversions on nonproduction servers before enabling broadly.


### New categories in the Telegram purchase flow
An enabled category linked to an active public server now appears after selecting its Service Type even before the first plan has been created. Purchasing remains unavailable until an active plan exists. The web Categories form requires at least one public server and validates the selection server-side.

### Category visibility diagnostics (v1.2.0)

The **Categories** page now reports the Telegram visibility reason and backend provider for each category. Linked public categories remain listed under their service type even when the linked server is temporarily inactive; the bot blocks purchases until the server and plan are active. Reseller-only categories never appear in public purchases. If a category appears under a different service type, verify its linked server's provider and scope in **Servers**.

## Reseller server access and request visibility (v1.2.0)
- Admin Web → Resellers → Add/Edit: select multiple explicit servers (Sanaei/3x-ui, PasarGuard, MikroTik/OpenVPN); only active servers are eligible. The representative chooses one permitted server before creating each config. The default server retains Sanaei inbound/group restrictions; other Sanaei servers use automatic active inbounds. Old single-server resellers remain compatible.
- Admin Web → Resellers: toggle the regular-user Request Reseller button independently from PasarGuard Panel Sales and the already-approved Reseller Menu. Changes are shared with Bot Settings.
- On approval, the updated home menu is delivered to the applicant Telegram ID, not the approving admin. PasarGuard panel purchases also refresh the buyer menu after credentials are successfully delivered.


### Sanaei Happ Encrypted Link delivery (per public plan)

Configure **Send Happ Encrypted Link** in **Plans → Add/Edit Public Plan** for a Sanaei server. Enable Happ encrypted links and subscriptions in the Sanaei panel first. The bot uses the panel's official numeric-client-ID API and passes the returned crypt5 URI unchanged to the caption and QR. Mini App copy, QR and My Configs use the same resolver. Generation failures never fall back to a normal link.

The selected retail plan is authoritative, including imported or administrator-created retail services without a linked paid Order. Trials without a plan, resellers and conversions do not inherit the setting. Existing customers can retrieve the corrected link without buying again. Older edit forms that omit the Happ field preserve its current setting.

### Reseller management and pending receipts (v1.2.0)

- **Resellers → Add/Edit** supports multiple permitted servers (Sanaei, PasarGuard, MikroTik/OpenVPN), with independent inbound/group restrictions per server when applicable.
- Reseller request approval distinguishes prepaid-volume resale from PasarGuard Pay-As-You-Go panel purchasing; the latter still requires normal payment approval and a strictly limited OWN-scope PasarGuard role.
- Enabling **PasarGuard Panel Sales** requires HTTPS and genuine admin-creation/role-management privileges (Owner or delegated Admin),, and verifiably restricted reseller-role capabilities. Validation now reports specific errors instead of a single generic message.
- Customer-chosen configuration usernames are checked against the database and target provider before payment. Duplicate names trigger a retry; unreachable providers are not treated as proof that a name is available.
- Administrators and delegated payment-card reviewers can open the pending-receipts inbox. Reviewer visibility and approval actions remain scoped to their assigned receipts.


### Happ subscription mode in Plans (v1.2.0)
The **Happ Encrypted Link** option is now configured on each **Public Plan** for a Sanaei/3x-ui server, not when adding/editing a server. Select **Yes** to deliver only `happ://crypt5/...` for ordinary retail purchases of that plan; **No** uses the normal subscription link. Trial, reseller, and Convert accounts do not inherit this mode. Existing server-level flags are ignored.


### Reseller-only servers and approval wizard

Only servers explicitly tagged `Reseller` (not Public, Public + Reseller, or a default placeholder) are selectable for reseller panel sales and volume resellers. In Telegram, approving a volume-reseller request now prompts admins to choose permitted servers, configure inbound/group restrictions for each server, set sellable GB and validity, and finally confirm. The approved user receives a separate congratulations message with the persistent Restart Bot button.

PasarGuard dashboard-account PAYG sales can use non-owner Admin credentials **only if the upstream PasarGuard account is permitted to create subordinate administrators and apply a verified OWN-only role**. If upstream denies these API operations, no safe dashboard-login delivery is possible without delegated permissions. The bot does not borrow broader permissions or expose the operator account.


## 📱 Telegram Mini App

D Bot includes a Persian, RTL Telegram Mini App for customers and resellers. Users open it from the menu button beside the message box in the bot's private chat. Purchases, receipt uploads, order tracking and configuration delivery can be completed inside the Mini App.

### Customer features

- **Buy subscriptions:** Browse the configured categories and plans, enter a configuration name, apply an optional discount code and review the final price. Names are checked against the database and destination panel, including PasarGuard username requirements.
- **Pay and track orders:** Pay from the wallet or upload a card-to-card receipt inside the app. Receipt approval remains an administrator/reviewer action. Order status and completed configurations can be retrieved after reopening the app.
- **Manage configurations:** View the configuration name, plan, server, traffic usage, remaining quota, expiry and active status. Usage refreshes from the panel every minute. Unlimited services are labeled accordingly.
- **Connect and maintain services:** Copy the subscription link, display its QR code, open it in Happ, renew, rotate the link, reset HWID or delete a configuration where supported. Sanaei plans configured for Happ encrypted links keep that delivery policy. MikroTik/OpenVPN services expose the applicable connection details and registered profile download.
- **Receive a free test account:** Request a trial and retrieve its configuration inside the app. Volume, duration and target servers follow the bot's test-account settings. The one-time entitlement is shared between the bot and Mini App, and repeated requests do not create another trial batch.
- **Wallet and support:** View the balance, submit top-up receipts, review recent orders and open the configured support account directly in Telegram.

Plan conversion is available from configuration details and continues through the established bot conversion flow.

### Reseller workspace

Approved resellers can view their balance or sellable volume, usage, validity and customer configurations. The workspace supports bulk-volume and Pay As You Go accounts, server selection, configuration creation, top-ups, volume/day increases, renewals and supported configuration controls. Server access, inbound restrictions and client groups follow the administrator's per-reseller settings.

Purchased PasarGuard reseller panels have their own panel cards, balance/usage information, recharge flow, configuration creation and panel-login link. Available actions depend on the account's permissions, financial mode and provider.

### Enable and customize

1. Configure a public HTTPS domain in the website settings and run both the `api` and `bot` services with the current project version.
2. Open **MINI APP** in the web admin panel, enable the app and set the title, welcome text and real support Telegram username.
3. Choose the accent color, animations, supported fullscreen mode, visible sections and reseller workspace. Up to six custom HTTPS shortcuts can be added.
4. Send `/start` in the bot's private chat, then use the menu button beside the message box. Its label follows the bot's current Telegram name.

The application URL is `https://YOUR-DOMAIN/miniapp`. Open it through Telegram so the API can validate the Telegram session. Blocked-user checks, required rule acceptance, required channel membership and section visibility are enforced on the server. Trial availability is controlled by the existing test-account settings.

For a manual source deployment, rebuild and restart the application services from the project root:

```bash
docker compose up -d --build api bot
```

See [native checkout and receipt handling](docs/MINIAPP_CHECKOUT_FA.md), [trial accounts](docs/MINIAPP_TRIAL_AND_TUTORIAL_VIDEOS_FA.md), [reseller billing](docs/RESELLER_PAYG_FA.md) and [per-reseller groups and renewal activation](docs/RESELLER_GROUPS_AND_RENEWAL_ACTIVATION_FA.md) for detailed Persian guides.

## Reseller billing / سیستم مالی نمایندگان

[راهنمای PAYG، خرید حجم و مینی‌اپ مدیر](docs/RESELLER_PAYG_FA.md)

