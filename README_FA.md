<p align="center">
  <img src="docs/images/logo.png" alt="Darvish Bot Logo" width="150" />
</p>

<h1 align="center">Darvish Bot</h1>

<p align="center">
  <b>ربات حرفه‌ای فروش VPN، مدیریت نمایندگی و پنل ادمین تحت وب.</b>
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
  <img src="https://img.shields.io/badge/Release-v1.1.14-7C3AED?style=flat-square" alt="Release v1.1.14">
</p>

<p align="center">
  <img src="docs/images/readme-hero.svg" alt="Darvish Bot overview banner" width="100%" />
</p>

---

<div dir="rtl">

## ✨ معرفی

**Darvish Bot** یک ربات تلگرام و پنل مدیریت وب برای فروش و مدیریت سرویس‌های VPN است. این پروژه برای خرید سرویس، مدیریت کاربران، پلن‌های نمایندگی، کیف پول، پرداخت کارت‌به‌کارت، پرداخت کریپتو، تیکت، مدیریت سرورها، ارسال کانفیگ و گزارش‌گیری طراحی شده است.

<table>
  <tr>
    <td align="center"><b>🤖 ربات تلگرام</b><br/>پنل کاربر، خرید، کانفیگ و تیکت</td>
    <td align="center"><b>🖥️ پنل مدیریت</b><br/>کاربران، پلن‌ها، سرورها، پرداخت‌ها و گزارش‌ها</td>
    <td align="center"><b>👥 نمایندگی</b><br/>بسته حجم، کاربران نماینده و برگشت حجم</td>
  </tr>
  <tr>
    <td align="center"><b>🔗 اتصال پنل</b><br/>3x-ui، X-UI، Sanaei و MikroTik flow</td>
    <td align="center"><b>💳 پرداخت‌ها</b><br/>کیف پول، کارت‌به‌کارت و NOWPayments</td>
    <td align="center"><b>🐳 Docker</b><br/>API، ربات، PostgreSQL و Redis</td>
  </tr>
</table>

---

## 🩹 اصلاح فوری v1.1.14

| بخش | تغییر |
|---|---|
| ورود کد تخفیف تمدید | خطای `NameError: ui_message is not defined` بعد از واردکردن کد تخفیف تمدید برطرف شد. |
| شاخه‌های خطا | پیام کد نامعتبر و سرویس پیدا نشد نیز در همین Handler بدون خطای ثانویه ارسال می‌شوند. |

---

## 🆕 تغییرات v1.1.13

| بخش | تغییر |
|---|---|
| کد تخفیف تمدید | در مرحله پرداخت تمدید، کاربر می‌تواند کد تخفیف وارد کند و مبلغ اصلی و نهایی را ببیند. |
| قوانین مشترک | اعتبار، تاریخ انقضا، سقف مصرف، محدودیت هر کاربر و محدودیت سرور برای خرید و تمدید از یک منطق مشترک استفاده می‌کنند. |
| کیف پول و کارت | مبلغ تخفیف‌خورده در پرداخت کیف پول، کارت‌به‌کارت، رسید مدیر و سفارش ذخیره می‌شود. |
| تخفیف کامل | اگر مبلغ نهایی صفر شود، تمدید بدون درخواست رسید صفر تومانی انجام می‌شود. |
| رزرو امن کد | در کارت‌به‌کارت، سهم استفاده از کد برای سفارش رزرو و در صورت لغو یا رد رسید آزاد می‌شود. |

---

## 🆕 تغییرات v1.1.12

| بخش | تغییر |
|---|---|
| کانفیگ‌های تمام‌شده | سرویس‌هایی که حجمشان تمام شده یا تاریخشان منقضی شده است، فوراً از «کانفیگ‌های من» حذف نمی‌شوند. |
| مهلت تمدید | سرویس تمام‌شده تا ۷۲ ساعت با وضعیت قرمز و دکمه تمدید در فهرست باقی می‌ماند. |
| ثبت زمان غیرفعال‌شدن | همه مسیرهای Sync سنایی و MikroTik اکنون `disabled_at` و علت غیرفعال‌شدن را همان لحظه ثبت می‌کنند. |
| تشخیص اتمام حجم | حتی اگر پنل هنوز `enable=true` برگرداند، رسیدن مصرف به سقف حجم به‌عنوان پایان سرویس تشخیص داده می‌شود. |
| حذف خودکار | فقط سرویس واقعاً منقضی، تمام‌شده یا حذف‌شده از پنل بعد از ۷۲ ساعت پاک می‌شود؛ غیرفعال‌کردن دستی باعث حذف سه‌روزه نمی‌شود. |
| صفحه جزئیات | زمان تقریبی باقی‌مانده برای تمدید داخل صفحه مشخصات کانفیگ نمایش داده می‌شود. |

---

## 🆕 تغییرات v1.1.11

| بخش | تغییر |
|---|---|
| عنوان سفارش | نوع سفارش در رسید مدیر فقط «تمدید» یا «خرید جدید» نمایش داده می‌شود. پیام‌های پردازش، خطا و دکمه تلاش مجدد نیز با نوع واقعی سفارش هماهنگ هستند. |
| تمدید 3x-ui | API رسمی `resetTraffic` هم مصرف را صفر می‌کند و هم Client را فعال می‌کند؛ D Bot دیگر `enable=true` را دستی ارسال نمی‌کند. |
| Update تمدید | بعد از Reset، وضعیت واقعی Client دوباره از پنل خوانده می‌شود و فقط `totalGB` و `expiryTime` تغییر می‌کنند تا وضعیت غیرفعال قدیمی دوباره روی پنل نوشته نشود. |
| مولتی‌لوکیشن | Update بدون فیلتر `inboundIds` اجرا می‌شود تا Client API رسمی تمام Inboundهای متصل و Nodeها را به‌روزرسانی کند. |
| بررسی نتیجه | فقط حجم و تاریخ نهایی بررسی می‌شوند و اختلاف واقعی با مقادیر قبل، هدف و نتیجه گزارش می‌شود. |

---

## 🆕 تغییرات v1.1.9

| بخش | تغییر |
|---|---|
| رد رسید | مدیر بعد از زدن رد، دلیل سفارشی می‌نویسد؛ رسید و مشخصات اصلی باقی می‌مانند، فقط دکمه نهایی «رسید رد شد» نمایش داده می‌شود و دلیل برای کاربر و دیتابیس ارسال می‌شود. |
| سابقه سفارش | دلیل، مدیر ردکننده و زمان رد در گزارش سفارش‌های سایت قابل مشاهده است. |
| حذف کانفیگ | پیام موفقیت حذف، یوزرنیم و مشخصات کامل سرویس، حجم، مصرف، سرور و تاریخ‌ها را نمایش می‌دهد. |
| ترتیب دسته‌ها | ترتیب Drag & Drop با نام پایدار گروه دسته ذخیره/حل می‌شود و بعد از فیلتر نوع سرویس نیز در ربات اعمال می‌شود. |
| Refresh نماینده | دکمه Refresh Stats مصرف پنل را همگام و Used، Total، Reserved و Remaining را از نو محاسبه می‌کند. |
| مصرف تاریخی | مصرف هر سرویس در فیلد مستقل نگه داشته می‌شود تا اشتباه دستی Used و ریست مصرف تمدید، تاریخچه را خراب نکند. |
| Inactive نماینده | غیرفعال‌شدن سرویس فقط آن را از Reserved خارج می‌کند؛ Total افزایش نمی‌یابد و مصرف آن در Used باقی می‌ماند. |

---

## 🆕 تغییرات v1.1.8

| بخش | تغییر |
|---|---|
| بازیابی تداخل SSL | کانفیگ‌های فعال Nginx برای همان دامنه پیش از Bootstrap بکاپ و غیرفعال می‌شوند؛ گواهی معتبر قبلی استفاده می‌شود و روش Standalone به‌عنوان مسیر جایگزین امن وجود دارد. |
| نصب‌کننده و Nginx | دامنه در اولین مرحله گرفته می‌شود؛ قبل از اطلاعات تلگرام، SSL صادر و یک صفحه امن «نصب در حال انجام است» روی HTTPS نمایش داده می‌شود. Nginx فقط بعد از سالم‌شدن API به برنامه متصل می‌شود تا خطای موقت 502 دیده نشود. |
| مجوز فایل‌های نصب | فایل‌های Shell که با مجوز `644` از GitHub دریافت شوند خودکار اصلاح می‌شوند؛ اگر ابزار SSL واقعاً موجود نباشد، پیش از صدور گواهی از شاخه Raw دریافت می‌شود. |
| OpenVPN / MikroTik | دکمه فعال/غیرفعال در «کانفیگ‌های من» اضافه شد و وضعیت دستی پنل هنگام بازشدن لیست و Job دوره‌ای همگام می‌شود. |
| تمدید | بعد از تمدید دیگر یوزرنیم، رمز یا لینک کانفیگ دوباره ارسال نمی‌شود؛ فقط رسید تمدید و آموزش Refresh در Happ نمایش داده می‌شود. |
| پسورد OpenVPN | هر پسورد غیرخالی و بدون فاصله/کاراکتر سفید، حتی یک‌کاراکتری، پذیرفته می‌شود. |
| ترتیب دسته‌ها | کارت‌های دسته‌بندی در پنل وب Drag & Drop هستند و همان ترتیب در ربات اعمال می‌شود. |
| API سنایی | تمام endpointهای رسمی Client در لایه 3x-ui اضافه شدند و مسیر ساخت عادی به یک Login، یک `clients/add` و حداکثر دو `clients/get` محدود شد. |
| پاک‌سازی کند | Login دوم، اسکن ۱۰هزار Client، پاک‌سازی Tombstone در زمان خرید، endpointهای Legacy و بازنویسی `inbound.settings` حذف شدند. |

---

## 🚀 نصب سریع

نصب روی VPS تازه با یک دستور:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```

نصب‌کننده **قبل از هر تنظیم دیگری دامنه را می‌پرسد**. سپس Nginx را نصب و فعال می‌کند، مسیر ACME را آزمایش می‌کند و همان ابتدا گواهی Let’s Encrypt می‌گیرد. تا زمانی که Docker و برنامه کامل بالا بیایند، روی دامنه یک صفحه HTTPS با متن «نصب در حال انجام است» نمایش داده می‌شود. اتصال Nginx به API فقط بعد از موفق‌شدن `/health` انجام می‌شود؛ بنابراین کاربر با صفحه موقت 502 روبه‌رو نمی‌شود.

| مرحله | اتفاقی که می‌افتد |
|---|---|
| ابتدا | دریافت دامنه و ایمیل اختیاری Let’s Encrypt، بررسی DNS و پورت‌های ۸۰/۴۴۳، اجرای Nginx و صدور فوری SSL |
| ۱ | توکن ربات تلگرام و آیدی عددی Owner/Admin |
| ۲ | یوزرنیم و پسورد پنل وب، به‌صورت خودکار یا دستی |
| ۳ | نام دیتابیس PostgreSQL، یوزر و پسورد دیتابیس |
| ۴ | پورت داخلی API، تایم‌زون و لینک اختیاری کانال تلگرام |
| ۵ | نمایش خلاصه نهایی قبل از ساخت `.env` و اجرای سرویس‌ها |

<details>
<summary>نمونه منوی نصب</summary>

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
✓ صفحه موقت HTTPS فعال شد: https://panel.example.com

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

بعد از نصب، برای باز شدن منوی گرافیکی Control Center از یکی از این دو دستور استفاده کنید؛ از همین منو می‌توانید اطلاعات Setup Wizard را ببینید، تغییر دهید و سرویس‌ها را مدیریت کنید:

```bash
dbot
dbot menu
```

یا فقط از این دستورهای مستقیم مدیریتی استفاده کنید:

```bash
dbot status
dbot logs
dbot restart
dbot start
dbot stop
dbot update
dbot backup
dbot uninstall --purge
```

---

## 🧩 امکانات

| بخش | توضیحات |
|---|---|
| 🤖 پنل کاربر تلگرام | خرید سرویس، مدیریت کانفیگ‌ها، تمدید، حذف کانفیگ، کیف پول، تیکت، راهنما، پیام وضعیت ساخت/تمدید و دکمه خانه بعد از موفقیت |
| 🖥️ پنل مدیریت وب | مدیریت کاربران، پلن‌ها، دسته‌بندی‌ها، سرورها، پرداخت‌ها، گزارش‌ها، تست اکانت، تنظیمات و مدیریت کیف پول کاربران |
| 👥 سیستم نمایندگی | بسته‌های نمایندگی، مصرف تجمعی، حجم رزروشده فعال، ظرفیت باقی‌مانده، کاربران نماینده و اعلان کوتاه ساخت کانفیگ برای مدیر |
| 🔗 اتصال به X-UI / 3x-ui | ساخت، حذف، تمدید، تغییر UUID و همگام‌سازی کلاینت‌ها |
| 🌐 MikroTik / OpenVPN | ساخت و مدیریت یوزر برای سرویس‌های MikroTik-based |
| 🧭 چند سرور | افزودن چند سرور، دسته‌بندی سرورها، نوع سرویس و inbound ID |
| 💳 کیف پول و پرداخت | پرداخت از کیف پول، افزایش/کاهش کیف پول توسط مدیر با آیدی عددی، پرداخت کارت‌به‌کارت، تایید رسید و پیگیری سفارش |
| ₿ پرداخت کریپتو | اتصال به NOWPayments و پشتیبانی از IPN Webhook |
| 🏷️ کد تخفیف | تخفیف درصدی/مبلغی، سقف استفاده کلی، سقف استفاده هر کاربر و محدودسازی روی سرور |
| 🎫 تیکت | ارسال تیکت توسط کاربر، پاسخ ادمین و بستن تیکت |
| 🔔 اعلان‌های مدیریتی | ارسال اطلاعات کاربر جدید، اعلان ساخت کانفیگ نماینده و گزارش خطای کوتاه و مرتب برای Owner/Admin |
| 🧰 بکاپ و ریستور | بکاپ پروژه/دیتابیس، بازیابی و ابزارهای کمکی مهاجرت |
| 🐳 اجرای Docker | اجرای API، ربات، PostgreSQL، Redis و پنل مدیریت در یک ساختار Docker-based |

---

## ⛓️ پنل‌های پشتیبانی‌شده

<table>
  <tr>
    <td align="center"><b>3x-ui</b></td>
    <td align="center"><b>X-UI</b></td>
    <td align="center"><b>Sanaei X-UI</b></td>
    <td align="center"><b>MikroTik / OpenVPN</b></td>
    <td align="center"><b>Multi-inbound Xray</b></td>
  </tr>
</table>

---

## 🏗️ ساختار و معماری

<p align="center">
  <img src="docs/images/stack-diagram.svg" alt="Darvish Bot service architecture" width="100%" />
</p>

```text
Darvish Bot
├── app/                  بک‌اند، هندلرهای ربات، API، jobها و سرویس‌ها
├── frontend/             سورس پنل مدیریت Next.js
├── scripts/              اسکریپت‌های کمکی
├── Dockerfile            فایل build اصلی Docker
├── docker-compose.yml    سرویس‌های API، ربات، PostgreSQL و Redis
├── install.sh            نصب‌کننده یک‌خطی VPS
├── README.md             مستندات انگلیسی
└── README_FA.md          مستندات فارسی
```

---

## 📦 نصب دستی

```bash
git clone https://github.com/officialdarvish/D_bot.git
cd D_bot
git checkout v1.1.14
cp .env.example .env
nano .env
docker compose up -d --build
```

آدرس پنل مدیریت:

```text
https://YOUR_DOMAIN/login
```

---

## ⚙️ تنظیمات محیطی

فایل `.env` را در ریشه پروژه بسازید و مقدارهای خصوصی خودتان را داخل آن قرار دهید.

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

> فایل `.env` واقعی، توکن ربات، API Key، اطلاعات پنل، IP سرورها و رمز دیتابیس را داخل GitHub منتشر نکنید.

---

## ₿ پرداخت کریپتو با NOWPayments

Darvish Bot می‌تواند از طریق NOWPayments فاکتور پرداخت کریپتو بسازد و با IPN Webhook وضعیت پرداخت را دریافت کند.

```env
NOWPAYMENTS_ENABLED=true
NOWPAYMENTS_API_KEY=YOUR_API_KEY
NOWPAYMENTS_IPN_SECRET=YOUR_IPN_SECRET
NOWPAYMENTS_PAY_CURRENCY=trx
NOWPAYMENTS_PRICE_CURRENCY=usd
NOWPAYMENTS_IPN_CALLBACK_URL=https://YOUR_DOMAIN/webhooks/nowpayments
```

مسیر Webhook:

```text
/webhooks/nowpayments
```

بعد از وضعیت‌های نهایی مثل `confirmed`، `finished` یا `sending` سفارش پرداخت‌شده محسوب می‌شود.

---

## 🏷️ کدهای تخفیف

سیستم کد تخفیف از موارد زیر پشتیبانی می‌کند:

- تخفیف درصدی
- تخفیف مبلغی ثابت
- سقف استفاده کلی
- سقف استفاده برای هر کاربر
- محدودسازی روی سرور/دسته‌بندی خاص
- فعال/غیرفعال کردن، ویرایش و حذف از پنل مدیریت

---

## 🕹️ مرکز کنترل گرافیکی

نصب‌کننده یک مرکز کنترل تعاملی برای VPS اضافه می‌کند. برای باز کردن آن بزنید:

```bash
dbot
```

این منو حالا می‌تواند **اطلاعاتی که در Setup Wizard وارد شده‌اند را نمایش دهد و تغییر بدهد**. مقدارهای حساس به‌صورت پیش‌فرض مخفی هستند و فقط با تایید شما داخل ترمینال نمایش داده می‌شوند.

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

1) Status                  نمایش وضعیت کانتینرها
2) Logs                    نمایش لاگ زنده، خروج با Ctrl+C
3) Restart                 ریستارت همه سرویس‌ها
4) Start                   شروع سرویس‌ها
5) Stop                    توقف سرویس‌ها
6) Update                  دریافت آپدیت، rebuild و اجرای دوباره
7) Backup                  ساخت بکاپ کامل
8) Setup Info              نمایش اطلاعات واردشده در نصب
9) Edit Setup              تغییر مقدارهای ذخیره‌شده در .env
10) Apply Nginx/SSL        اعمال دوباره Nginx و گواهی SSL
11) Show Secrets           نمایش اطلاعات حساس ذخیره‌شده
12) Uninstall --purge      حذف کامل برنامه و بکاپ‌ها
0) Exit                    خروج
```

بخش‌هایی که از داخل منو قابل تغییر هستند:

| بخش | مقدارهای قابل تغییر |
|---|---|
| Telegram | توکن ربات، آیدی ادمین/اونر، لینک کانال پیش‌فرض |
| Website & SSL | دامنه، فعال/غیرفعال کردن HTTPS، ایمیل Let’s Encrypt، پورت داخلی API و پورت‌های HTTP/HTTPS مربوط به Nginx |
| Web Admin | نام کاربری و رمز پنل مدیریت وب |
| Runtime | تایم‌زون و فاصله زمانی همگام‌سازی سرورها |
| Database | مقدارهای PostgreSQL همراه با هشدار امنیتی پیشرفته |

دستورهای باز کردن Control Center:

| دستور | توضیح |
|---|---|
| `dbot` | باز کردن منوی گرافیکی Control Center |
| `dbot menu` | باز کردن همان منوی مدیریتی داخل VPS |

دستورهای مستقیم هم پشتیبانی می‌شوند:

| دستور | توضیح |
|---|---|
| `dbot status` | نمایش وضعیت کانتینرها |
| `dbot logs` | نمایش لاگ زنده |
| `dbot restart` | ریستارت همه سرویس‌ها |
| `dbot start` | شروع سرویس‌ها |
| `dbot stop` | توقف سرویس‌ها |
| `dbot update` | دریافت آپدیت، rebuild و اجرای دوباره |
| `dbot backup` | ساخت بکاپ |
| `dbot uninstall --purge` | حذف کامل برنامه و بکاپ‌ها |

---

## 🔐 چک‌لیست امنیت قبل از انتشار عمومی

- فایل `.env` واقعی را commit نکنید.
- آدرس پنل، یوزرنیم، پسورد، توکن و اطلاعات سرور را داخل کد نگذارید.
- فایل‌های runtime مثل log، backup، dump، zip و cache را حذف کنید.
- در نمونه‌ها فقط از مقدارهای امن مثل `CHANGE_ME` استفاده کنید.
- هر توکنی که حتی یک‌بار عمومی شده را حتماً rotate کنید.

---

## 🔗 لینک‌های رسمی

| پلتفرم | لینک |
|---|---|
| کانال تلگرام | [officialdarvishchannel](https://t.me/officialdarvishchannel) |
| ربات تلگرام | [@officialdarvish_bot](https://t.me/officialdarvish_bot) |
| ریپازیتوری گیت‌هاب | [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot) |
| دونیت | [NOWPayments](https://nowpayments.io/donation/officialdarvish) |

---

## ❤️ حمایت از پروژه

اگر Darvish Bot برای شما مفید بود، می‌توانید از توسعه آینده پروژه با دونیت کریپتو حمایت کنید:

<p align="center">
  <a href="https://nowpayments.io/donation/officialdarvish">
    <img src="https://img.shields.io/badge/Donate%20with%20TRX-NOWPayments-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX">
  </a>
</p>

---

<p align="center">
  ساخته‌شده با ❤️ توسط <a href="https://github.com/officialdarvish">Darvish</a>
</p>

</div>


> نکته: پورت‌های سفارشی Nginx از داخل Setup Wizard و `dbot` Control Center قابل تنظیم هستند. برای SSL خودکار Let’s Encrypt معمولاً پورت‌های عمومی 80 و 443 باید در دسترس باشند.

- Fixed reseller service visibility after server edits/deletes: reseller-created usernames are preserved in DB and repaired from panel by username when server links become stale.

- در ویرایش نماینده داخل وبسایت فقط حجم کل و تاریخ انقضا قابل تنظیم است؛ Used، Reserved و Remaining به‌صورت خودکار محاسبه و نمایش داده می‌شوند.
