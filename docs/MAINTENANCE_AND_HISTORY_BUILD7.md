# v1.4.0 build 7

## English

- Users → List opens bounded, independently paginated order and service history. It shows purchases/renewals, config usernames, plan/server, prices, status, creation and expiration dates. Historical missing/deleted links remain blank. No credentials or subscription URLs are returned.
- Home message editing is now in Custom; Settings retains the reseller panel visibility switch. The dedicated home editor keeps the existing welcome setting and saves it transactionally. The global header search/shortcut only appears in Users and Resellers and resets on navigation.
- Plan forms start with audience + custom Yes/No, then currency, title, and conditional prices/ranges. Fixed fields are omitted in custom mode. Custom rates use Toman and server-side bounds. Both public and reseller purchases freeze selected terms; reseller personal per-GB rates do not replace an explicit custom GB/day tariff. Existing normal packages retain their pricing behavior.
- The sidebar's D Bot User is an anonymous aggregate of participating active installations. The independent service and deployment guide are in `integrations/installation_counter`; an operator-owned HTTPS URL is required. No endpoint or live count is assumed.
- Receipt source messages are retained. Approval/rejection changes only the review keyboard; prompts and outcomes use new messages. Completed receipt buttons acknowledge without converting the receipt into a menu.
- Compact System Status/Version cards; English updater errors stay English; first/last revenue labels are kept inside the chart.
- Docker database/Redis logs now rotate at 10 MB × 3 files per container, as API/bot logs already did. Old existing Docker logs may not shrink until container recreation.

### Disk usage and cleanup

No production disk measurements were available. Code-identified contributors include Docker build cache/old images, recovery image tags, update SQL/logs, temporary exports, PostgreSQL data and Redis persistence. The last two are live application data and are never automatically pruned.

`sudo dbot disk` prints read-only filesystem, managed update-file, and Docker aggregate usage. Automatic host maintenance checks daily through a systemd timer and runs every 45 days; failures retry the next day. It removes old unused build cache/dangling images and aged D Bot recovery sets while retaining the latest two recovery sets. Updates and maintenance share a private operation lock. No container/volume/system prune or live database cleanup is executed.

Manual Clean Temporary Files and automatic maintenance delete eligible D Bot temporary backups/update SQL older than 24 hours, other disposable artifacts older than seven days; an in-progress update's backup is excluded. Saved backup archives outside disposable storage, keys, active services, financial records and database volumes are preserved. Installer refresh provisions the timer; verify with `systemctl status dbot-maintenance.timer` on the actual host.

## فارسی

دکمه List در Users سوابق خرید، تمدید و سرویس‌های کاربر را صفحه‌بندی‌شده نمایش می‌دهد. Bot home message به Custom منتقل شده و سرچ سراسری فقط در Users و Resellers دیده می‌شود. فرم پلن بر اساس انتخاب Yes/No عوض می‌شود و شرایط خرید دلخواه عمومی و نمایندگی جداگانه ثبت می‌شود.

رسید اصلی حذف یا ویرایش نمی‌شود؛ فقط دکمه وضعیت آن تغییر می‌کند و ادامه مراحل در پیام جدید انجام می‌شود. کارت‌های وضعیت و نسخه کوچک‌تر شده‌اند و متن انگلیسی نسخه و برچسب انتهای نمودار اصلاح شده است.

پاک‌سازی میزبان هر ۴۵ روز انجام می‌شود. بک‌آپ‌های موقت و SQL آپدیت قدیمی‌تر از ۲۴ ساعت و سایر خروجی‌های موقت قدیمی‌تر از ۷ روز حذف می‌شوند. این کار شامل بک‌آپ ذخیره‌شده کاربر، اطلاعات مالی، دیتابیس یا volume فعال نیست. دو مجموعه آخر بازیابی نگه‌داری می‌شوند. برای تشخیص مصرف واقعی دیسک سرور دستور `sudo dbot disk` اضافه شده است؛ اعداد VPS در محیط توسعه قابل اندازه‌گیری نبود.

D Bot User تعداد نصب‌های مشارکت‌کننده‌ای است که در ۱۵ دقیقه اخیر heartbeat داشته‌اند. تنها عدد عمومی نمایش داده می‌شود. راهنمای راه‌اندازی سرویس مستقل در `integrations/installation_counter/README.md` است؛ برای فعال‌سازی سراسری باید دامنه HTTPS سرویس مرکزی مشخص شود.
