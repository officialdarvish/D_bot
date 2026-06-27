<div align="center">

# Darvish D Bot

### ربات فروش VPN تلگرام + پنل مدیریت مدرن Cyber Admin

[فارسی](README_FA.md) • [English](README.md)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Admin%20API-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Cache-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)

</div>

---

## 📌 معرفی

**Darvish D Bot** یک ربات تلگرام و پنل مدیریت تحت وب برای فروش و مدیریت سرویس‌های VPN است. این پروژه برای سرویس‌های V2Ray / X-UI / 3x-ui، پلن‌های عمومی، پلن‌های نمایندگی، کیف پول، کارت‌به‌کارت، کد تخفیف، بکاپ، گزارش فروش، SSL و مدیریت کامل از طریق سایت طراحی شده است.

این پروژه شامل موارد زیر است:

- ربات تلگرام برای کاربران، نماینده‌ها و مدیرها
- بک‌اند FastAPI و API مخصوص پنل وب
- دیتابیس PostgreSQL
- کش Redis
- پنل مدیریت مدرن با استایل Cyber Admin
- Docker و نصب سریع روی VPS
- سیستم Backup & Restore
- خروجی PDF گزارش فروش
- مدیریت دامنه و SSL سایت

---

## 📢 لینک‌های رسمی

- کانال تلگرام: [officialdarvishchannel](https://t.me/officialdarvishchannel)
- ربات تلگرام: [@officialdarvish_bot](https://t.me/officialdarvish_bot)
- مخزن گیت‌هاب: [officialdarvish/D_bot](https://github.com/officialdarvish/D_bot)

---

## 🚀 نصب سریع روی VPS

با کاربر root اجرا کن:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/officialdarvish/D_bot/main/install.sh)
```

نصاب از تو این موارد را می‌پرسد:

- توکن ربات تلگرام
- آیدی عددی ادمین تلگرام
- دامنه سایت
- نام دیتابیس PostgreSQL
- یوزرنیم دیتابیس PostgreSQL
- پسوورد دیتابیس PostgreSQL

در انتهای نصب، داخل ترمینال VPS اطلاعات ورود سایت نمایش داده می‌شود:

```text
Login URL
Web Admin Username
Web Admin Password
Role: Owner
```

این اطلاعات را ذخیره کن. بعداً هم می‌توانی با دستور زیر دوباره مشاهده کنی:

```bash
dbot credentials
```

---

## ✨ قابلیت‌های اصلی

### ربات تلگرام

- فرآیند خرید برای کاربران
- پلن عمومی و پلن نمایندگی
- پشتیبانی از پرداخت با کیف پول
- تایید رسید کارت‌به‌کارت توسط مدیر
- پشتیبانی از پرداخت کریپتو با NOWPayments
- کد تخفیف درصدی و کد تخفیف مبلغی بر اساس تومان
- درخواست و تایید نمایندگی
- ساخت اکانت تست
- سیستم تیکت و پشتیبانی
- منوهای مدیریت برای ادمین
- اتصال به X-UI / 3x-ui

### سایت مدیریت Cyber Admin

- صفحه لاگین امن برای Owner
- داشبورد تیره و مدرن
- نمودار درآمد
- سفارش‌های اخیر و فعالیت‌های اخیر
- مدیریت کاربران
- مدیریت نماینده‌ها
- مدیریت پلن عمومی و پلن نمایندگی
- مدیریت سرورها و دسته‌بندی‌ها
- مدیریت روش‌های پرداخت
- مدیریت کدهای تخفیف
- صفحه Backup & Restore
- تنظیمات سایت و SSL
- خروجی PDF گزارش فروش
- قابلیت قرار دادن عکس پروفایل در هدر ادمین

### Backup & Restore

- تنظیم مقصد بکاپ فقط از داخل سایت
- ارسال بکاپ به کانال، گروه یا ربات بکاپ
- تست دسترسی مقصد قبل از ذخیره
- اجرای بکاپ دستی
- ریستور فایل JSON لوکال و همگام‌سازی دیتابیس
- مدیریت بکاپ و ریستور از پنل سایت

### Website & SSL

- تنظیم یا تغییر دامنه سایت از پنل مدیریت
- گرفتن و اعمال SSL از داخل سایت
- نمایش وضعیت موفق یا ناموفق بودن SSL
- تغییر یوزرنیم و پسوورد پنل وب
- خروج خودکار بعد از تغییر اطلاعات ورود سایت

---

## 🧱 تکنولوژی‌های استفاده‌شده

| بخش | تکنولوژی |
|---|---|
| ربات | Python, aiogram |
| API | FastAPI, Uvicorn |
| دیتابیس | PostgreSQL |
| کش | Redis |
| پنل وب | Next.js, React, Tailwind CSS |
| نمودارها | Recharts |
| آیکون‌ها | Lucide Icons |
| انیمیشن | Framer Motion |
| دیپلوی | Docker Compose |
| SSL | Nginx + Certbot |

---

## ✅ پیش‌نیازها

VPS پیشنهادی:

- Ubuntu 22.04 یا Ubuntu 24.04
- دسترسی root
- حداقل ۱ هسته CPU
- حداقل ۱ گیگ RAM، پیشنهاد ۲ گیگ
- دامنه متصل به IP سرور
- باز بودن پورت‌های `80` و `443` و در صورت نیاز `8000`

اکانت‌های مورد نیاز:

- توکن ربات تلگرام از BotFather
- آیدی عددی ادمین تلگرام
- اکانت NOWPayments در صورت استفاده از پرداخت کریپتو

---

## 🔐 ورود به پنل سایت

بعد از نصب، این آدرس را باز کن:

```text
https://your-domain.com/login
```

نقش اصلی داخل سایت:

```text
Owner
```

اگر از مسیر زیر یوزرنیم یا پسوورد سایت را تغییر بدهی:

```text
Settings → Website & SSL
```

سیستم به صورت خودکار لاگ‌اوت می‌کند و باید با اطلاعات جدید دوباره وارد شوی.

---

## 🧰 کامندهای مدیریت VPS

بعد از نصب، دستور `dbot` فعال است:

```bash
dbot credentials           # نمایش آدرس ورود سایت، یوزرنیم و پسوورد
dbot start                 # روشن کردن کانتینرهای ربات و API
dbot stop                  # خاموش کردن کانتینرها
dbot restart               # ری‌استارت کانتینرها
dbot logs                  # نمایش لاگ زنده
dbot status                # نمایش وضعیت کانتینرها
dbot env                   # ویرایش فایل .env
dbot update                # دریافت/بیلد/آپدیت پروژه
dbot backup                # ساخت بکاپ دیتابیس و فایل‌های پروژه
dbot mysql                 # ریستور کاربران WizWiz/MySQL به صورت تعاملی
dbot mysql /path/file.sql  # ریستور کاربران WizWiz/MySQL از فایل SQL
dbot mysql /path/file.zip  # ریستور کاربران WizWiz/MySQL از فایل ZIP
dbot uninstall             # حذف پروژه و نگهداری بکاپ‌ها
dbot uninstall --purge     # حذف کامل پروژه همراه با بکاپ‌ها
```

---

## 🤖 کامندهای مالک داخل ربات تلگرام

این دستورها فقط برای آیدی‌های Owner/Admin فعال هستند:

```text
/websetup
/websetup example.com
/site_setup example.com
/sslsetup example.com
```

دستور `/websetup example.com` دامنه سایت را ذخیره می‌کند، روی VPS برای همان دامنه SSL می‌گیرد، سپس یوزرنیم و پسوورد پنل سایت را می‌پرسد و ذخیره می‌کند. بعد از ذخیره، از مسیر `https://example.com/admin` با اطلاعات جدید وارد پنل شو.

مدیریت اکانت تست از داخل سایت در مسیر زیر انجام می‌شود:

```text
Admin Panel → Test Account
```

داخل این کارت می‌توانی اکانت تست را فعال/غیرفعال کنی، دکمه اکانت تست داخل ربات را نمایش/مخفی کنی، سرور، inbound، حجم، مدت اعتبار و ریست تاریخچه دریافت تست را تنظیم کنی.

---

## ⚙️ متغیرهای محیطی

مقادیر اصلی فایل `.env`:

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

نکات مهم:

- فایل `.env` را منتشر نکن.
- برای دیتابیس پسوورد قوی استفاده کن.
- برای `FERNET_KEY` مقدار امن بساز.
- بعد از اولین ورود، اطلاعات ورود سایت را تغییر بده.

---

## 🐳 کامندهای Docker

ساخت image به صورت لوکال:

```bash
docker build --no-cache -t darvish021/d_bot:latest .
```

ارسال image:

```bash
docker push darvish021/d_bot:latest
```

اجرای Docker Compose:

```bash
docker compose up -d --build
```

ری‌استارت:

```bash
docker compose restart
```

مشاهده لاگ:

```bash
docker compose logs -f --tail=200
```

---

## 🖥️ صفحات پنل مدیریت

| صفحه | کاربرد |
|---|---|
| Dashboard | فروش، سفارش‌ها، منابع سیستم و فعالیت‌های اخیر |
| Service Types | مدیریت عنوان نوع سرویس‌ها |
| Plans | پلن عمومی و پکیج نمایندگی |
| Payments | حساب‌ها و کارت‌های پرداخت |
| Orders Report | لیست سفارش‌ها و خروجی PDF |
| Discount Codes | کد تخفیف درصدی و مبلغی تومان |
| Users | کاربران تلگرام، کیف پول و وضعیت نمایندگی |
| Resellers | حجم، مصرف و تاریخ انقضای نماینده‌ها |
| Servers | سرورهای X-UI / 3x-ui و Refresh اینباندها |
| Categories | دسته‌بندی سرورها و پلن‌ها |
| Backup & Restore | مقصد بکاپ، تست، بکاپ دستی و ریستور |
| Settings | متن شروع، قوانین، وضعیت ربات، دیتابیس، ورود سایت و SSL |

---

## 📄 گزارش فروش PDF

از داشبورد یا صفحه Orders Report روی گزینه زیر بزن:

```text
Export PDF
```

فایل PDF شامل موارد زیر است:

- بازه تاریخ
- مجموع فروش
- تعداد سفارش‌ها
- شماره سفارش
- تاریخ
- کاربر
- پلن
- روش پرداخت
- وضعیت
- مبلغ به تومان

متن فارسی و Unicode پشتیبانی می‌شود.

---

## 💾 راهنمای Backup & Restore

مسیر:

```text
Admin Panel → Backup & Restore
```

مقصدهای قابل انتخاب:

- کانال
- گروه
- ربات بکاپ یا private bot

برای کانال و گروه، دکمه Test را بزن تا دسترسی بررسی شود. اگر ربات دسترسی ادمین لازم را داشته باشد، داخل پنل وضعیت موفق نمایش داده می‌شود.

ریستور:

1. وارد Backup & Restore شو.
2. فایل JSON بکاپ را از سیستم خودت انتخاب کن.
3. روی Restore & Sync بزن.
4. سیستم دیتابیس را بر اساس ساختار فایل بکاپ همگام‌سازی می‌کند.

---

## 🌐 راهنمای SSL

مسیر:

```text
Settings → Website & SSL
```

دامنه را وارد کن و سپس بزن:

```text
Apply SSL
```

داخل سایت وضعیت موفق یا ناموفق بودن SSL نمایش داده می‌شود. دامنه باید به IP سرور وصل باشد و پورت‌های `80` و `443` باز باشند.

---

## 🧪 کامندهای توسعه

اجرای فرانت‌اند:

```bash
cd frontend
npm install
npm run dev
npm run build
```

اجرای بک‌اند/API:

```bash
pip install -r requirements.txt
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

اجرای ربات:

```bash
python -m app.main
```

بررسی کامپایل:

```bash
python -m compileall -q app
```

---

## 📁 ساختار پروژه

```text
app/
  api/              مسیرهای FastAPI و پنل سایت
  bot/              هندلرها و کیبوردهای ربات تلگرام
  core/             تنظیمات، امنیت و لاگینگ
  database/         مدل‌ها و اتصال دیتابیس
  jobs/             جاب‌های پس‌زمینه
  services/         سرویس‌های اصلی پروژه
  xui/              کلاینت X-UI / 3x-ui
frontend/
  app/              صفحات Next.js
  components/       کامپوننت‌های Cyber Admin
  lib/              ابزارهای ارتباط با API
frontend_out/       خروجی استاتیک پنل سایت
docker-compose.yml  سرویس‌های PostgreSQL، Redis، API و Bot
install.sh          نصب سریع روی VPS
scripts/            اسکریپت‌های کمکی
```

---

## 🛠️ رفع مشکل‌های رایج

### سایت باز نمی‌شود

```bash
dbot status
dbot logs
```

مطمئن شو کانتینر API روشن است و دامنه به IP سرور وصل شده است.

### SSL خطا می‌دهد

DNS و پورت‌ها را بررسی کن:

```bash
ufw status
nginx -t
```

بعد از داخل پنل دوباره تست کن:

```text
Settings → Website & SSL → Apply SSL
```

### اطلاعات ورود سایت را فراموش کردم

از این دستور استفاده کن:

```bash
dbot credentials
```

اگر اطلاعات ورود سایت را از داخل پنل تغییر داده باشی، مقدار جدید داخل دیتابیس ذخیره می‌شود. بعد از تغییر اطلاعات ورود، آن را همان لحظه ذخیره کن.

### مشکل در Docker build

```bash
docker build --no-cache -t darvish021/d_bot:latest .
```

سپس ری‌استارت کن:

```bash
docker compose up -d --force-recreate
```

---

## 🔒 نکات امنیتی

- فایل `.env` را خصوصی نگه دار.
- توکن ربات، پسوورد دیتابیس، FERNET_KEY، رمز پنل‌ها و کلیدهای NOWPayments را منتشر نکن.
- بعد از اولین ورود، اطلاعات پنل وب را تغییر بده.
- VPS را همیشه آپدیت نگه دار.
- فقط در جاهایی که لازم است به ربات دسترسی ادمین بده.

---

## ❤️ حمایت از پروژه

اگر از Darvish Bot استفاده می‌کنی و می‌خوای از توسعه نسخه‌های بعدی حمایت کنی، می‌تونی با TRX یا سایر ارزهای پشتیبانی‌شده از طریق NOWPayments دونیت کنی:

<p align="center">
  <a href="https://nowpayments.io/donation/officialdarvish">
    <img src="https://img.shields.io/badge/Donate%20with%20TRX-NOWPayments-orange?style=for-the-badge&logo=tron&logoColor=white" alt="Donate with TRX">
  </a>
</p>

لینک دونیت:

```text
https://nowpayments.io/donation/officialdarvish
```

---

## ⚖️ کپی‌رایت، شرایط استفاده و اجازه کپی

این پروژه متعلق به صاحب Darvish Bot است. کپی کردن، فروش مجدد، بازنشر، انتشار نسخه تغییر داده‌شده یا استفاده از سورس پروژه برای محصول عمومی یا خصوصی دیگر فقط با اجازه صاحب پروژه مجاز است.

برای دریافت اجازه، از طریق لینک‌های رسمی تلگرام با صاحب پروژه ارتباط بگیر.

---

<div align="center">

**Darvish D Bot — ساخته‌شده برای اتوماسیون حرفه‌ای فروش VPN**

</div>


## UI v9 Final Fixes

- Website & SSL can request API/site and bot restart after successful SSL.
- Users page has pagination for more than 100 users.
- Test Account supports usage reset and inbound chip selection.
- Server add/edit/refresh tests the panel and syncs inbounds.
- Plan server changes sync inbound IDs correctly.
- Reseller page shows reseller menu plans.


## نکات اتصال پنل 3x-ui

D BOT برای اتصال به پنل MHSanaei 3x-ui از لاگین رسمی پنل و API اینباندها استفاده می‌کند. آدرس پنل و Web Path را دقیق وارد کنید:

```text
Panel URL / Origin: https://your-domain.com:PORT
Panel Web Path: /your-secret-path/
Username: نام کاربری پنل 3x-ui
Password: رمز عبور پنل 3x-ui
```

می‌توانید لینک کامل پنل مثل `https://your-domain.com:PORT/your-secret-path/` را هم وارد کنید؛ D BOT انتهای رایج مثل `/login` و `/panel/api/...` را خودکار اصلاح می‌کند. حالت API Token هم پشتیبانی می‌شود؛ کافی است داخل فیلد رمز/token مقدار `token:<API_TOKEN>` را وارد کنید.

## نکته اتصال به 3x-ui با مسیر مخفی و CSRF

برای نسخه‌های جدید 3x-ui که مسیر مخفی دارند، آدرس اصلی پنل و مسیر وب را جدا وارد کنید:

```text
Panel URL / Origin: https://panel.example.com
Panel Web Path: /your-hidden-path/
```

کلاینت D BOT حالا اول صفحه مسیر اصلی پنل را باز می‌کند تا cookie و CSRF token را بگیرد، بعد به `/login` درخواست می‌زند و سپس با همان session مسیر `/panel/api/inbounds/list` را صدا می‌زند.

## سازگاری API پنل 3x-ui

D BOT برای ساخت، تمدید، حذف، تغییر لینک، ریست ترافیک، کاربران آنلاین و بررسی IP از API جدید Client پنل 3x-ui استفاده می‌کند. مسیر مخفی پنل با دو فیلد `Panel URL / Origin` و `Panel Web Path` پشتیبانی می‌شود.

مثال:

```text
Panel URL / Origin: https://panel.mgiftshop.ir
Panel Web Path: /U76peSug8RbmlymBHQ/
```
