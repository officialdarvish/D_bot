# D BOT active installations / نصب‌های فعال D BOT

This independent service counts participating D BOT installations running on different VPSs. It does **not** count Telegram customers, VPN connections or people currently looking at the web panel. Each installation sends a persistent random identity every five minutes. An identity seen within the last **15 minutes** counts once; the web panel refreshes the total every minute. The initial total is zero until installations connect. Installations that do not opt in, cannot reach the endpoint or run older unconfigured versions cannot be counted.

## نصب کنار ربات روی VPS خودتان

یک زیردامنه جدا مثل `count.example.com` بسازید و رکورد A آن را روی IP همین VPS قرار دهید. اگر AAAA دارید، آن هم باید درست باشد. پورت‌های ۸۰ و ۴۴۳ باید برای صدور گواهی در دسترس باشند؛ برای راه‌اندازی اولیه CDN را روی DNS only بگذارید. نصاب برای VPS دارای Docker Compose، Nginx میزبان، Certbot، curl، Python 3 و systemd آماده شده؛ زیرساخت نصب استاندارد D BOT همین‌ها را دارد. قبل از اجرا، Nginx فعلی باید سالم باشد.

```bash
curl -fsSL https://raw.githubusercontent.com/officialdarvish/D_bot/main/integrations/installation_counter/install.sh -o /tmp/dbot-counter-install.sh
sudo bash /tmp/dbot-counter-install.sh count.example.com you@example.com
```

دامنه و ایمیل نمونه را عوض کنید. نصاب فایل‌های سرویس را در `/opt/dbot-installation-counter` قرار می‌دهد؛ کانتینر و volume مستقل دارد، فقط روی `127.0.0.1:9080` گوش می‌کند و برای زیردامنه یک سایت HTTPS جدا می‌سازد. تنظیمات سایت ربات و دیتابیس آن را تغییر نمی‌دهد. اگر نام دامنه قبلاً متعلق به سایت دیگری باشد یا پورت ۹۰۸۰ اشغال باشد، نصب باید متوقف شود؛ سایت ربات را حذف یا پورت آن را آزاد نکنید. در خطای تنظیم Nginx یا صدور گواهی، فایل سایت شمارنده به وضعیت قبلی برمی‌گردد. گواهی با Certbot تمدید می‌شود؛ timer یا cron تمدید Certbot روی میزبان باید فعال باشد.

بعد از نصب، این آدرس‌ها باید باز شوند:

- `https://count.example.com/health` — سلامت سرویس و دیتابیس.
- `https://count.example.com/count` — فقط مجموع نصب‌های فعال؛ ابتدا معمولاً صفر است.

**آدرس پایه HTTPS را برای اتصال پروژه ارسال کنید.** این نصب به‌تنهایی ربات‌های دیگران را ثبت نمی‌کند؛ آدرس شمارنده باید در آن نصب‌ها تنظیم و ارسال آمار فعال شود.

## Connect installations / اتصال هر نصب

Set these two values in that installation's existing `.env`, without replacing the rest of it:

```dotenv
DBOT_COUNTER_URL=https://count.example.com
DBOT_COUNTER_ENABLED=true
```

From the D BOT project directory, recreate only the API and bot services so they receive the environment changes:

```bash
docker compose up -d --no-deps --force-recreate api bot
```

`DBOT_COUNTER_URL` enables reading the public total; `DBOT_COUNTER_ENABLED` independently opts the bot into reporting. The bundled endpoint is `https://count.botgiftshop.ir`; reporting stays disabled until the owner enables `DBOT_COUNTER_ENABLED`. An explicit empty `DBOT_COUNTER_URL` disables reading too. Existing installations with a blank URL must set it explicitly. Use the same central URL on all participating installations. The sidebar shows **Active D BOT installs / نصب‌های فعال D BOT**, or `—` if the endpoint is unavailable. Allow up to five minutes for the first heartbeat plus one minute for the display cache.

The bot-only `installation_identity` volume preserves the identity across updates and factory reset and is excluded from database backups. Deleting it creates a new identity; the old one expires after 15 minutes. Cloning it causes multiple installations to count as one. Multiple bot processes sharing the identity count once. This is an approximate count of installations, not unique owners.

## Operations / مدیریت

```bash
cd /opt/dbot-installation-counter
docker compose -p dbot-installation-counter ps
docker compose -p dbot-installation-counter logs --tail=50
docker compose -p dbot-installation-counter restart
```

Re-run the installer with the same hostname to update the service. The persistent `counter_data` volume survives recreation. To stop just the counter, use `docker compose -p dbot-installation-counter down` in its directory; do not add `-v` unless you intend to delete its data. The web panel will show `—` while the counter is stopped; the bot continues working.

For an existing HTTPS proxy managed outside host Nginx, skip `install.sh`: run `docker compose -p dbot-installation-counter up -d --build` from this directory, then proxy your chosen HTTPS hostname to `127.0.0.1:9080`. Disable access logs and set a 128-byte request-body limit. Never expose the backend port directly.

## Privacy and accuracy / حریم خصوصی و دقت

Only the SHA-256 hash of a random 256-bit token and last heartbeat time are stored. No bot token, Telegram ID, customer count, domain, server address or version is sent. Old hashes are pruned after 24 hours when a heartbeat arrives. There are no public installation-list routes. Uvicorn and the generated Nginx site's access logs are disabled; disable CDN request logs/body tracing too. Like any internet service, the endpoint receives source IPs in transit, but this implementation does not persist them.

Public anonymous heartbeats can be forged and installation identities can be reset; this is an approximate community statistic, not a licensing, billing or unique-person counter. Apply suitable rate limits at your infrastructure if needed. No heartbeat failure is sent to Telegram, and statistics failures must not interrupt purchases or bot operation.

## Validation

```bash
python3 -m unittest discover -s integrations/installation_counter -p 'test_*.py' -v
bash -n integrations/installation_counter/install.sh
```

Tests cover duplicate tokens, expiry, malformed/oversized requests, hash-only storage, pruning, health and absent list routes. VPS Docker/Nginx/TLS deployment must be verified on the actual host after choosing the domain. This repository does not claim that a public counter has already been deployed.

## Current central endpoint / آدرس مرکزی فعلی

The maintainer-operated endpoint is `https://count.botgiftshop.ir`. Its health and count endpoints were verified after deployment. The first response reported zero installations; installing the counter itself does not register a bot. To participate, set both environment values above using this hostname and recreate API/bot containers.
