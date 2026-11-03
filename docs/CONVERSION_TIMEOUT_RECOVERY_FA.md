# D Bot 1.3.0 — اصلاح تایم‌اوت تبدیل تعرفه

لاگ ۳۰ اکتبر مربوط به دریافت‌نشدن پاسخ تغییر وضعیت مبدأ در پاسارگارد است؛ خطا قبل از فراخوانی ساخت مقصد رخ داده است. دریافت‌نشدن پاسخ، اثبات نمی‌کند که دستور غیرفعال‌کردن اجرا نشده است.

## تغییرات

- پس از یک بار ارسال تغییر وضعیت، وضعیت واقعی کاربر با خواندن مجدد بررسی می‌شود؛ درخواست تغییردهنده به علت تایم‌اوت تکرار نمی‌شود.
- پاسخ دیرهنگام، خواندن موقتاً ناموفق و وضعیت قدیمی با حداکثر چهار نوبت خواندن و بودجه کلی ۱۵ ثانیه بررسی می‌شوند.
- فقط تأیید صریح غیرفعال‌بودن مبدأ، اجازه ساخت مقصد را می‌دهد. وضعیت نامعلوم، منقضی یا محدودشده به‌جای تأیید غیرفعال‌سازی پذیرفته نمی‌شود.
- همین روش برای تأیید حجم دقیق و تاریخ انقضای ثبت‌شده در مقصد اعمال می‌شود. حجم نامحدود یا حجم اشتباه به‌عنوان نتیجه صحیح تبدیل پذیرفته نمی‌شود.
- زمان انتظار پاسخ تغییر وضعیت پاسارگارد به‌طور پیش‌فرض ۴۵ ثانیه است؛ زمان انتظار خواندن‌های معمول تغییر نکرده است.
- پیام مشتری و گزارش مدیر، توقف پیش از ساخت مقصد را از توقف هنگام ساخت یا ثبت تبدیل تفکیک می‌کنند.
- مسیر مشترک ربات و مینی‌اپ اصلاح شده است؛ قفل جلوگیری از تبدیل یا اعتبار تکراری حفظ می‌شود.

## نصب

فایل‌های پروژه را جایگزین کنید و تنظیمات و دیتابیس فعلی را نگه دارید:

```bash
docker compose up -d --build api bot
```

مقدار اختیاری زیر برای پنل‌هایی که تغییر وضعیت آن‌ها کندتر است قابل تنظیم است. برای استفاده از پیش‌فرض نیازی به تغییر `.env` نیست:

```dotenv
PASARGUARD_STATUS_TIMEOUT_SECONDS=45
```

## درخواست‌های قبلی در وضعیت بررسی

آپدیت، رزروهای قبلی مانند تبدیل شماره ۳ را خودکار پاک یا دوباره اجرا نمی‌کند. در لاگ ارسالی، ساخت مقصد فراخوانی نشده؛ ولی وضعیت واقعی مبدأ پس از تایم‌اوت نامعلوم است. مدیر باید وضعیت مبدأ و هر مقصد احتمالی را بررسی و درخواست را تعیین تکلیف کند. پاک‌کردن رزرو بدون بررسی، راهکار این خطا نیست.

## English release notes

- Reconcile lost enable/disable replies through bounded, read-only confirmation in both Sanaei and PasarGuard conversion paths.
- Confirm exact converted byte quota and inherited expiry after ambiguous update replies, without replaying mutations.
- Reject missing, expired, limited and on-hold states as evidence of a successful source disable.
- Add a dedicated configurable PasarGuard status-operation timeout; retain normal read timeouts and explicit timeout overrides.
- Record the failed conversion stage and explain when destination provisioning has not started.
- Preserve durable conversion claims and manual review for unresolved outcomes and previously failed requests.

Validation uses simulated panel responses and local database tests; no live VPS changes are included.
