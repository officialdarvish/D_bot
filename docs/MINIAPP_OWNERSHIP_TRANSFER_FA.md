# انتقال مالکیت در مینی‌اپ — 1.3.0

مدیر در «کانفیگ‌های من»، جزئیات کانفیگ شخصی را باز می‌کند و «انتقال مالکیت» را می‌زند. واردکردن آیدی عددی کاربر مقصد، بررسی نام کاربر، تأیید نهایی و مشاهده نتیجه همگی داخل مینی‌اپ انجام می‌شوند.

کاربر مقصد باید ربات را استارت کرده باشد و مسدود نباشد. امکان انتقال به خود مدیر، کانفیگ دیگران، سرویس نمایندگی و کانفیگ پنل خریداری‌شده وجود ندارد. هنگام وجود عملیات در انتظار روی همان کانفیگ، انتقال تا تعیین تکلیف آن مسدود است.

انتقال فقط مالک سرویس را عوض می‌کند؛ لینک، مشخصات اتصال، حجم، انقضا، سوابق پرداخت و موجودی کیف پول حفظ می‌شوند. بعد از ثبت موفق، به کاربر مقصد اعلان انتقال همراه با دکمه «کانفیگ‌های من» ارسال می‌شود. شکست ارسال اعلان، انتقال را لغو یا تکرار نمی‌کند و نتیجه آن در مینی‌اپ مشخص است.

## Release notes

- Added an administrator-only ownership transfer button to Mini App configuration details.
- Kept recipient lookup, confirmation and completion fully inside Mini App.
- Reused the shared ownership checks, atomic audit and recipient notification.
- Added idempotent transfer requests and blocked transfers during pending native configuration operations.
