# D Bot 1.3.0 — تنظیمات نمایندگی و زبان وب

- عنوان بخش تنظیمات فروش نمایندگی به `Resseller Map and options` تغییر کرد؛ مسیر قبلی آن همچنان معتبر است.
- در مینی‌اپ، بسته‌های خرید حجم با سرور انتخاب‌شده تطبیق داده می‌شوند. عنوان و مبلغ بسته نمایش داده می‌شود و سرور، هنگام دریافت قیمت و پرداخت دوباره بررسی می‌شود. بسته بدون سرور قابل خرید نیست؛ سرور آن را در Plans مشخص کنید.
- پس از تأیید نمایندگی یا ساخت پنل نمایندگی، دکمه درخواست نمایندگی در خانه پنهان می‌شود.
- در Plans، هنگام ساخت یا ویرایش پلن نمایندگی سنایی و پاسارگارد، حالت انتخاب اینباند/گروه را روی دستی قرار دهید و موارد مجاز را انتخاب کنید. ابتدا فهرست سرور را در Servers همگام کنید.
- محدودیت پلن در خرید تأییدشده روی ساخت‌های بعدی نماینده اعمال می‌شود. خرید بسته محدودیت دستی مدیر را بازتر نمی‌کند؛ اگر محدودیت‌ها هیچ اشتراکی نداشته باشند، ساخت متوقف می‌شود تا مدیر تنظیمات را اصلاح کند.
- برای نماینده‌های موجود، محدودیت هر سرور را مستقیماً در Resellers → Edit تنظیم کنید. ویرایش پلن به‌تنهایی کانفیگ‌های ساخته‌شده قبلی را تغییر نمی‌دهد.
- دکمه‌های تکراری Refresh کارت نماینده و دفتر مالی حذف شدند؛ تازه‌سازی بالای صفحه داده‌های هر دو را دوباره می‌گیرد. گزینه تست اتصال سرور همچنان یک عملیات مجزا است.
- متن‌های جاافتاده فارسی، نگهداری متن اصلی هنگام تغییر زبان، راست‌چین/چپ‌چین قالب تحویل و ظاهر کارت ارسال لاگ اصلاح شدند. محتوای سفارشی مدیر، رمز، نشانی و شناسه‌ها خودکار ترجمه نمی‌شوند.
- بازشدن لینک پشتیبانی مینی‌اپ در نبود قابلیت تلگرام، از مسیر مرورگر انجام می‌شود.

## English release notes

- Match reseller volume packages to the selected authorized server in catalogs, quotes and payments; reject unbound and mismatched packages.
- Show only the plan title and price in the reseller application package selector.
- Hide reseller applications from the Mini App home after approval.
- Add server-specific inbound/group restrictions to Sanaei and PasarGuard reseller packages; preserve stricter administrator restrictions.
- Rename the reseller sales section to “Resseller Map and options”.
- Complete missing Persian UI labels, preserve original labels across language switches, and align delivery templates and error-log forms with shared controls.
- Remove duplicate reseller refresh actions and reload the ledger from the page refresh.
- Fall back to browser navigation for support links when Telegram link opening is unavailable.

No database schema migration is required. Existing prepaid reseller capacity remains in the existing account inventory model.
