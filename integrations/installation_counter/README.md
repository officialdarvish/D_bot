# D Bot active installation counter / شمارنده نصب‌های فعال

This separate service returns one aggregate only. A participating bot sends a random 256-bit token every five minutes. The service stores its SHA-256 hash and last heartbeat time, and counts hashes seen within 15 minutes. It is an approximate count of **participating active installations**, not people or Telegram subscribers. There are no user lists, Telegram IDs, bot tokens, domains, version metadata, or server addresses in the database or public response. Inactive hashes are pruned after 24 hours when a heartbeat arrives.

روی VPS مستقل یا VPS خودتان اجرا کنید:

```bash
cd integrations/installation_counter
docker compose up -d --build
```

Expose port 9080 through your existing HTTPS reverse proxy and certificate. Example location in an existing TLS server block (replace `count.example.com` with your own hostname):

```nginx
location / {
    access_log off;
    client_max_body_size 128;
    proxy_pass http://127.0.0.1:9080;
    proxy_set_header Host $host;
}
```

Uvicorn access logging is disabled. Disable request/access logs in the reverse proxy and any CDN too. Like any internet service, the network endpoint necessarily receives a source IP while serving a request; this implementation does not persist it. Do not enable body logging or request tracing.

For each D Bot installation, configure `.env`:

```dotenv
DBOT_COUNTER_URL=https://count.example.com
DBOT_COUNTER_ENABLED=true
```

Then recreate API/bot containers with your normal deployment command. `DBOT_COUNTER_URL` enables reading the public total; `DBOT_COUNTER_ENABLED` separately opts the bot into reporting. Both default to unconfigured/disabled. The sidebar shows `—` when the endpoint is absent or unavailable, never a fabricated count. The bot-only `installation_identity` volume preserves the random identity across updates and factory reset and is excluded from normal database backups. Deleting/cloning that volume changes/duplicates identity and affects accuracy.

این سرویس فقط مجموع نصب‌های مشارکت‌کننده و فعال در ۱۵ دقیقه اخیر را نشان می‌دهد. فعال‌سازی ارسال آمار اختیاری است و فقط توکن تصادفی ارسال می‌شود. سرویس قبل از مشخص‌شدن دامنه HTTPS روی VPS شما به‌صورت خودکار فعال نمی‌شود. هیچ فهرست عمومی یا API برای مشاهده نصب‌ها وجود ندارد.

Public anonymous heartbeats are not proof of ownership and can be forged. This counter is an approximate community statistic, not billing/licensing or fraud-resistant analytics. Apply infrastructure rate limits if publicly exposed; don't store identifying request logs. No heartbeat failure is sent to Telegram.

## Validation

Local tests cover duplicate tokens, expiry, body limits, hashed storage, unavailable list routes, disabled reporting, and stable local identity. A real VPS/TLS deployment still needs to be verified after configuring the hostname.
