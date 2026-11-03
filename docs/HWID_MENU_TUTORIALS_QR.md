# ریست HWID، منوها، آموزش‌ها و پس‌زمینه بارکد

## ریست و ارسال اطلاعات جدید

ریست HWID در ربات و عملیات مینی‌اپ برای سرویس‌های عمومی، نمایندگی و کانفیگ‌های پنل خریداری‌شده، اکنون علاوه بر پاک‌کردن دستگاه‌ها، اطلاعات اتصال را عوض می‌کند. سنایی Subscription ID و UUID/اعتبار اتصال را تغییر می‌دهد و نتیجه از پنل دوباره خوانده می‌شود. فیلدهای `uuid`/`id` و `subId`/`sub_id` نیز پشتیبانی می‌شوند. پاسخ موفقِ بدون نتیجهٔ قابل‌تأیید، موفقیت محسوب نمی‌شود.

PasarGuard از عملیات بومی `revoke_sub` برای تغییر لینک و اطلاعات پروکسی استفاده می‌کند. شناسهٔ عددی داخلی حساب ثابت می‌ماند؛ UUIDهای پروتکل و لینک اشتراک تغییر می‌کنند. کاربر حذف یا دوباره ساخته نمی‌شود و مصرف، حجم، انقضا و مالکیت حفظ می‌شوند. لینک ارسال‌شده همان لینک صادرشدهٔ پنل است. برای پلن‌های Happ در سنایی، لینک تحویل دوباره تولید می‌شود.

پس از موفقیت، اطلاعات تازه برای خریدار فرستاده می‌شود. در کانفیگ‌های پنل خریداری‌شده، عملیات با همان کلید پیگیری می‌شود: اگر پاسخ تغییر لینک گم شود، تلاش مجدد نتیجهٔ انجام‌شده را می‌خواند و دوباره UUID و لینک را عوض نمی‌کند. خطای ارسال پیام نیز عملیات موفق پنل را به عملیات قابل تکرار تبدیل نمی‌کند. مینی‌اپ پس از ریست، برخلاف عملیات غیرضروری دیگر، مجاز است کانفیگ تازه را در ربات ارسال کند.

### مجوز پنل محدود PasarGuard

نقش محدود D Bot برای `users.revoke_sub` و `hwids.read/delete` فقط مجوز OWN (`scope=1`) می‌گیرد. نقش قدیمی فقط وقتی ارتقا می‌یابد که شناسه و نام نقش دقیقاً مطابق رکورد باشند و تمامی مجوزهای قبلیِ آن همان الگوی محدود و امن D Bot باشند. مجوز ALL، مالکیت پنل یا دسترسی مدیریتی اضافه نمی‌شود. محدودیت‌های تعداد کاربر، دسترسی گروه‌ها و سایر محدودیت‌های نقش تغییر نمی‌کنند.

ارتقا از اتصال تنظیم‌شدهٔ سرور و با مجوز واقعی همان اتصال انجام می‌شود؛ اگر PasarGuard اجازهٔ تغییر نقش ندهد، عملیات برای بررسی متوقف می‌شود. عملیات کاربرِ زیرمدیر با توکن مالک جایگزین نمی‌شود. در اتصال‌های محدود عمومی یا نقش‌های سفارشی، مدیر بالادستی باید مجوزهای بومی ریست دستگاه و ابطال اشتراک را داده باشد.

## منوها و آموزش

- دکمهٔ MINI APP از منوی وب‌پنل حذف شده است. مینی‌اپ مشتری و نشانی مستقیم تنظیمات آن حذف نشده‌اند.
- مدیریت ربات ← **تنظیمات نمایندگی**: نام بخش اصلاح شده و گزینهٔ فعال/غیرفعال‌کردن **منوی نمایندگی** اضافه شده است. این گزینه، نمایش منوی نماینده را کنترل می‌کند و حساب‌ها یا سهمیه‌های قبلی را تغییر نمی‌دهد.
- مدیریت ربات ← تعامل با کاربر ← **آموزش**: برنامه را در Android، iOS یا Windows اضافه کنید؛ سپس نام، لینک دانلود مستقیم و متن آموزش را جداگانه ویرایش کنید. برنامه را هم می‌توان حذف کرد. لینک و متن در زمان ایجاد خالی‌اند؛ هیچ برنامه یا متن پیش‌فرضی ثبت نمی‌شود. برای خالی‌کردن لینک یا متن در ویرایشگر ربات، `-` بفرستید.
- وب‌پنل ← Settings ← **آموزش برنامه‌ها**: نام، سیستم‌عامل، لینک و متن هر برنامه قابل ویرایش‌اند و نمایش دکمهٔ آموزش در ربات از همین قسمت فعال/غیرفعال می‌شود. حداکثر ۶۰ برنامه، ۶۰ نویسه برای نام و ۱۲۰۰۰ نویسه برای متن پشتیبانی می‌شود. لینک دانلود HTTP/HTTPS است. متن طولانی با رعایت حد UTF-16 تلگرام در چند پیام ارسال می‌شود.
- منوی اصلی ← **قوانین**: متن قوانینِ تنظیم‌شدهٔ فعلی همراه با «شروع مجدد ربات» نمایش داده می‌شود. این صفحه تأییدیه نمی‌خواهد و پذیرش کاربر را تغییر نمی‌دهد. تنظیم جداگانهٔ پذیرش قوانین هنگام ورود اولیه، رفتار قبلی خود را حفظ می‌کند.

## پس‌زمینهٔ بارکد

مدیریت ربات ← تنظیمات ربات ← **بک گراند بارکد**: عکس یا فایل تصویر حداکثر ۵ مگابایت را بفرستید. تصویر به بوم ۱۰۸۰×۱۳۵۰ تبدیل و QR با حاشیهٔ سفید و کنتراست بالا در مرکز آن قرار می‌گیرد. برای پس‌زمینهٔ کامل، تصویر را از ابتدا با همین نسبت آماده کنید؛ نسبت‌های دیگر برش می‌خورند. `-` پس‌زمینهٔ پیش‌فرض را برمی‌گرداند.

تصویر در دیتابیس نگهداری می‌شود و به فایل موقت کانتینر وابسته نیست. دادهٔ حجیم تصویر وارد کش عمومی تنظیمات یا خروجی عمومی تنظیمات وب نمی‌شود. کارت‌های تحویل مشترک و ارسال مجدد لینک از پس‌زمینهٔ جدید استفاده می‌کنند؛ QR خامِ درون صفحهٔ مینی‌اپ برای نمایش و اسکن همچنان ساده باقی می‌ماند.

این نسخه migration جدیدی ندارد و روی سرور واقعی کاربر نصب یا آزمایش نشده است. سنایی، PasarGuard و تلگرام در تست‌ها شبیه‌سازی شده‌اند. تصاویر بررسی مرورگر صرفاً برای کنترل داخلی بوده و داخل بسته قرار نمی‌گیرند.

## اعتبارسنجی

- مجموعه کامل: ۵۶۱ تست موفق و پنج خطای پیشین در بررسی متنی داشبورد (دو مورد)، دنبالهٔ نام نمایندگی، خروجی درآمد و بررسی ویژگی‌های کارایی سنایی. خطای جدیدی باقی نمانده است.
- ۴۲ تست مرتبط پایانی شامل نقش محدود، بازیابی عملیات نیمه‌تمام، مالکیت کانفیگ و مدیریت محتوا موفق بودند.
- ساخت نهایی Next.js همراه با بررسی TypeScript موفق بود.
- مرورگر در عرض ۱۳۶۶ و ۳۹۰: حذف Mini App از ناوبری، فیلدهای اولیه خالی، افزودن برنامه، ذخیرهٔ نام/لینک/متن و غیرفعال‌سازی دکمهٔ آموزش بررسی شد. فرم سرریز افقی و خطای جاوااسکریپت نداشت. API و حساب مدیر در بررسی مرورگر شبیه‌سازی شدند.

## کنترل نمایش آموزش و قوانین

- وب پنل ← تنظیمات ← آموزش برنامه‌ها: دکمه اصلی آموزش، دکمه قوانین صفحه اصلی و دکمه هر برنامه مستقل فعال/غیرفعال می‌شوند.
- مدیریت ربات ← تعامل با کاربر ← آموزش: کنترل دکمه اصلی و، داخل هر برنامه، کنترل همان برنامه. «نمایش دکمه قوانین» نیز در تعامل با کاربر اضافه شده است.
- خاموش کردن محتوا را حذف نمی‌کند؛ برنامه‌های قدیمی به صورت پیش‌فرض فعال‌اند. آموزش غیرفعال از فهرست حذف می‌شود و دکمه پیام قدیمی نیز متن آن را باز نمی‌کند.
- وضعیت دکمه قوانین از الزام پذیرش اولیه قوانین مستقل است. ذخیره از نسخه‌های قدیمی وب، وضعیت دکمه قوانین را تغییر نمی‌دهد.
- ۳۰ تست مرتبط موفق؛ ساخت Next.js و کنترل ذخیره سه نوع وضعیت در مرورگر، در عرض موبایل و دسکتاپ، موفق بود.

## باطل کردن لینک بدون تغییر عضویت

- مسیر ربات برای کاربر عمومی و نماینده، پنل PasarGuard را به API همان پنل هدایت می‌کند. UUID پروتکل در دیتابیس ربات و لینک جدید از پاسخ تأییدشده پنل ذخیره می‌شود.
- سنایی Subscription ID و UUID را روی همان کلاینت تغییر می‌دهد؛ پارامتر inboundIds و فیلدهای عضویت به درخواست update ارسال نمی‌شوند. هیچ detach، attach، حذف/ساخت کاربر یا افزودن اینباندی در این عملیات وجود ندارد. نام‌های قدیمی فیلد UUID و Subscription ID نیز هنگام تغییر شناسه‌ها سازگار نگه داشته می‌شوند.
- PasarGuard از POST revoke_sub داخلی استفاده می‌کند و سپس اطلاعات واقعی کاربر را دوباره می‌خواند؛ هیچ PUT روی group_ids و هیچ حذف/ساخت حسابی انجام نمی‌شود. شناسه عددی حساب حفظ می‌شود؛ این شناسه با UUID اتصال متفاوت است.
- تغییر لینک و UUIDهای VLESS/VMess و ثابت ماندن گروه‌ها/اینباندها بررسی می‌شود. پاسخ موفق ظاهری یا تغییر صرفاً لینک، موفقیت محسوب نمی‌شود. در صورت مشاهده تغییر عضویت، خطا گزارش می‌شود و سیستم برای اصلاح خودکار detach/attach اجرا نمی‌کند.
- در کانفیگ‌های ساخته‌شده از پنل نمایندگی مینی‌اپ، ادامه عملیات با همان شناسه نیز هم UUID و هم لینک و گروه‌ها را بررسی می‌کند. مجوز محدود revoke برای نقش‌های قدیمی سازگار، بدون گسترش دسترسی به کاربران دیگر، بررسی می‌شود.
- ۱۶ تست جدید: درخواست API سنایی بدون پارامتر عضویت، نام‌های قدیمی فیلدها، پاسخ ناقص پنل، حفظ گروه و حساب، بازیابی پاسخ ازدست‌رفته، و ذخیره UUID/لینک در هر چهار مسیر کاربر/نماینده × ربات/مینی‌اپ.
- تست‌های پنل و تلگرام شبیه‌سازی شده‌اند؛ روی سرور واقعی نصب یا آزمایش نشده است.
- مرجع API داخلی PasarGuard: https://github.com/PasarGuard/panel/blob/main/app/routers/user.py و app/operation/user.py؛ عملیات revoke_sub لینک و مشخصات اتصال را روی همان حساب عوض می‌کند.

اعتبارسنجی نهایی باطل کردن لینک: ۵۶۰ تست موفق و همان پنج خطای پیشین مجموعه کامل. ۶۹ تست مرتبط اولیه و چهار تست تکمیلی مسیر ربات/مینی‌اپ نیز موفق بودند.

## وضعیت منابع با به‌روزرسانی پنج‌ثانیه‌ای

- بخش System Status داشبورد وب هر ۵ ثانیه رم، CPU، Swap و فضای دیسک را از مسیر محافظت‌شده /admin/api/v2/resources دریافت می‌کند؛ صفحه دوباره بارگذاری نمی‌شود. زمان آخرین دریافت نمایش داده می‌شود.
- این درخواست فقط منابع سیستم را می‌خواند و کوئری‌های فروش و سفارش را تکرار نمی‌کند؛ پاسخ و درخواست بدون کش هستند.
- درخواست‌ها هم‌پوشانی ندارند؛ در تب پنهان متوقف می‌شوند و با برگشت به تب، دریافت فوری انجام می‌شود. خروج از داشبورد، تایمر و درخواست درحال‌اجرا را پاک می‌کند.
- خطای موقت، مقادیر قبلی را حذف نمی‌کند؛ وضعیت تلاش مجدد نمایش داده می‌شود و دریافت بعدی خودکار است. پایان اعتبار ورود نیز دریافت خودکار را متوقف و صفحه ورود را نمایش می‌دهد.
- تازه‌سازی دوره‌ای آمار کلی داشبورد، صفحه را به Skeleton برنمی‌گرداند و خطای موقت آمار فروش باعث حذف نمودار منابع نمی‌شود.
- اعتبارسنجی: تست API شامل احراز هویت، پاسخ تازه، غیرفعال بودن کش و عدم کوئری گزارش؛ ساخت Next.js و TypeScript؛ مرورگر با پاسخ‌های شبیه‌سازی‌شده برای فاصله ۵ ثانیه‌ای، حفظ مقادیر هنگام خطا، بازیابی خودکار، عدم رفرش سند و توقف هنگام خروج.
- مجموعه کامل: ۵۶۱ تست موفق و همان پنج خطای پیشین. نصب روی سرور واقعی انجام نشده است.

## آیکون‌های اختصاصی System Status

- آیکون‌های ایموجی این بخش با چهار تصویر برداری اختصاصی جایگزین شدند: چیپ CPU، ماژول RAM، درایو دیسک و ماژول‌های تبادل Swap.
- قاب‌های آبی، بنفش، سبز و کهربایی، گرادیان نور، جزئیات مدار و نشانگر کوچک دارند. آیکون‌ها به فونت، سرویس بیرونی یا دانلود تصویر وابسته نیستند.
- آیکون‌ها تزئینی و از صفحه‌خوان پنهان هستند؛ نام منابع کنارشان باقی می‌ماند. افکت حرکت برای prefers-reduced-motion غیرفعال می‌شود.
- ساخت Next.js و TypeScript و بررسی مرورگر در عرض ۱۳۶۶ و ۳۹۰ موفق بود؛ چهار SVG با شناسه‌های مستقل نمایش داده شدند و سرریز افقی یا خطای جاوااسکریپت وجود نداشت. به‌روزرسانی پنج‌ثانیه‌ای، بازیابی پس از خطا و توقف درخواست‌ها پس از خروج نیز بررسی شد.

## مصرف زنده کانفیگ‌های مینی‌اپ

- پس از بازشدن مینی‌اپ، مصرف کانفیگ‌های متعلق به همان کاربر از پنل دریافت می‌شود و هر ۶۰ ثانیه در تب فعال دوباره خوانده می‌شود. بازگشت به مینی‌اپ نیز دریافت فوری دارد.
- کانفیگ‌های عمومی و مشتری‌های نمایندگی به‌روز می‌شوند؛ کانفیگ‌های پنل خریداری‌شده نیز از snapshot فعلی پنل خوانده می‌شوند. لیست و جزئیات بازشده، حجم مصرفی، باقی‌مانده و نمودار مصرف را بدون بازکردن دوباره صفحه تغییر می‌دهند.
- درصدهای کوچک با مقدار اعشاری برای عرض نوار محاسبه می‌شوند؛ نمایش نامحدود، مصرف واقعی را جداگانه نشان می‌دهد.
- مسیر /api/miniapp/usage با همان احراز هویت تلگرام و مجوز نمایش کانفیگ‌ها محافظت می‌شود. کانفیگ کاربران یا نماینده‌های دیگر خوانده نمی‌شود.
- برای خواندن از پنل حداکثر چهار درخواست هم‌زمان و مهلت هشت‌ثانیه‌ای اعمال شده است. هنگام انتظار شبکه تراکنش دیتابیس باز نمی‌ماند. قطع پنل، مصرف ذخیره‌شده را صفر نمی‌کند.
- به‌روزرسانی فقط مصرف/سقف مشاهده‌شده را ثبت می‌کند؛ UUID، لینک Happ/اشتراک، اینباند و گروه را تغییر نمی‌دهد و پرداخت یا پیامی در تلگرام ایجاد نمی‌کند. ثبت مصرف نماینده از مسیر delta موجود استفاده می‌کند تا نمونه تکراری دوباره جمع نشود.
- تغییر هم‌زمان سرویس مانند تمدید، چرخش شناسه یا ثبت نمونه جدیدتر باعث کنارگذاشتن پاسخ قدیمی می‌شود.
- پنج تست جدید شامل مالکیت، حفظ مصرف هنگام قطع پنل، ثبت یک‌باره مصرف نماینده، تمدید هم‌زمان و حجم صفر نامحدود موفق بودند؛ ۲۲ تست قبلی مینی‌اپ نیز موفق بودند. ساخت Next.js/TypeScript و بررسی مرورگر برای دریافت اولیه، تایمر یک‌دقیقه‌ای (تسریع‌شده در تست)، تغییر نمودار جزئیات و حفظ نمایش هنگام خطای شبکه موفق بود.
- پنل و تلگرام در بررسی‌ها شبیه‌سازی شده‌اند؛ این بسته روی سرور واقعی نصب نشده است.

اعتبارسنجی نهایی مصرف مینی‌اپ: مجموعه کامل با ۵۶۶ تست موفق و همان پنج خطای پیشین پایان یافت.

## نشست منقضی در تست اتصال وب‌پنل

- لاگ گزارش‌شده نشان می‌داد POST /admin/servers/test با 307 به /login منتقل و نهایتاً HTML صفحه ورود دریافت شده است. این درخواست قبل از اجرای تست پاسارگارد متوقف شده بود؛ نبودن API Token علت این نمونه نیست.
- درخواست‌های fetch/JSON به مسیرهای مدیریتی عادی نیز در احراز هویت به‌عنوان API شناخته می‌شوند و در نبود نشست، انقضا یا تغییر اطلاعات ورود، 401 JSON می‌گیرند.
- فرم‌های HTML قدیمی برای ورود مجدد از 303 استفاده می‌کنند تا مرورگر با GET وارد صفحه ورود شود. ارسال فرم جاوااسکریپت نیز redirect را خودکار دنبال نمی‌کند؛ در حالت 307 نسخه قدیمی، نام کاربری/رمز پنل دوباره به فرم login ارسال نمی‌شود.
- دکمه Test & Auto Fill در نشست نامعتبر، صفحه راهنمای ورود مجدد را نمایش می‌دهد. ورود معتبر به D Bot با CSRF صحیح همچنان تست پاسارگارد با نام کاربری/رمز و بدون API Token را اجرا می‌کند.
- هشت تست جدید برای نشست غایب، منقضی، تغییر اعتبارنامه‌ها، هدرهای fetch/JSON، فرم قدیمی و مسیر معتبر رمزعبور موفق بودند. ساخت Next.js و TypeScript موفق بود.
- این اصلاح اجرای هم‌زمان چند نمونه ربات با یک توکن را متوقف نمی‌کند؛ در خطای TelegramConflictError باید نمونه اضافه توسط مدیر متوقف شود. هیچ توکن یا محتوای لاگ خصوصی داخل بسته اضافه نشده است.

اعتبارسنجی اصلاح نشست وب: هشت تست مرتبط و دو حالت مرورگر (401 و redirect قدیمی 307) موفق بودند؛ هیچ درخواست login و ارسال مجدد اعتبارنامه رخ نداد. مجموعه کامل ۵۷۴ تست موفق و همان پنج خطای پیشین داشت.

## حذف کانفیگ در مینی‌اپ

- در انتهای جزئیات هر کانفیگ، دکمه قرمز و مستقل «حذف کانفیگ» قرار دارد: خرید عمومی، کانفیگ مشتری نمایندگی و کانفیگ ساخته‌شده از پنل نمایندگی. دکمه‌های تکراری حذف از شبکه ابزارها برداشته شده‌اند.
- صفحه تأیید نام کانفیگ و قطع اتصال پس از حذف را نمایش می‌دهد؛ بدون فشردن دکمه تأیید، درخواست حذف ثبت نمی‌شود. متن حسابداری نمایندگی برای خرید عمومی نمایش داده نمی‌شود.
- حذف عمومی از مسیر موجود حذف ربات استفاده می‌کند و مالکیت دوباره بررسی می‌شود. سوابق حذف و پاک‌سازی پنل و حالت صف در قطعی پنل حفظ می‌شوند. پیام چت به خریدار ارسال نمی‌شود.
- نتیجه حذف از وضعیت واقعی ذخیره‌شده خوانده می‌شود؛ قطعی اطلاع‌رسانی مدیر، حذف کامل‌شده را ناموفق یا قابل تکرار نمی‌کند. هر درخواست با کلید یکتا فقط یک بار اجرا می‌شود.
- نماینده پس از پایان اعتبار نمایندگی هم امکان حذف کانفیگ متعلق به خود را دارد؛ الزامات اعتبار برای ساخت، تمدید و افزایش منابع تغییر نکرده‌اند. محدودیت بررسی دستیِ کانفیگ در حال تغییر سیستم مالی باقی می‌ماند.
- ۲۲ تست مرتبط موفق: حذف عمومی سنایی و پاسارگارد، احراز هویت، تأیید، مالکیت، شناسه تکراری، حفظ سوابق، قطعی پنل/تلگرام و حذف نمایندگی منقضی. مرورگر سه مسیر عمومی، نماینده منقضی و پنل نمایندگی را بدون خطای جاوااسکریپت آزمایش کرد؛ پس از نتیجه، کانفیگ از لیست حذف شد. ساخت Next.js/TypeScript نیز موفق بود.
- آزمون‌ها با پنل و تلگرام شبیه‌سازی‌شده انجام شده‌اند؛ نصب روی سرور واقعی انجام نشده است.

اعتبارسنجی نهایی حذف مینی‌اپ: ۵۷۹ تست موفق و همان پنج خطای پیشین در مجموعه کامل.


## Website actions incorrectly requesting login (2026-10-21)

Root cause: submitForm uses redirect=manual to prevent replaying credentials to login, but requests still targeted bare /admin routes. The private web-path middleware returns 307 to /<web_path>/admin, which was classified as expired authentication. API requests now resolve the active website prefix before sending the request, including reads, saves and GET actions. Backup restore and navigation share the same resolver. Already-prefixed routes, external URLs and Mini App routes remain unchanged.

HTTP 403 now displays the server denial while keeping the current session UI; HTTP 401 continues to request login. CSRF and same-origin enforcement remain enabled, and POST redirects remain blocked. No session timeout extension or authentication bypass is introduced.

Validation: node tests/admin_api_paths.cjs exercises all three API helpers with private, bare and admin-prefixed private path names, unchanged CSRF and credentials headers, 403/401 handling and POST redirect protection. Seventeen related backend tests pass. Production Next.js/TypeScript build passes. Browser checks on /private-admin/admin/servers verify repeated successful requests and 403 stay in the modal, while 401 and unexpected redirect require login; six requests reached the prefixed endpoint, no login request/credential repost and no JavaScript errors. Live deployment was not performed.


## Category service selection and service badge colors (2026-10-21)

Categories now expose a Linked service type selector in Add/Edit, and show the saved service name on their cards. Explicit bindings use stable service keys in Setting(category_service_type:<id>), so renaming a service does not unlink its categories. Legacy/unassigned categories retain automatic provider-based routing; the explicit empty option restores that behavior. Saving a logical duplicate category updates its sibling bindings and preserves/migrates legacy plan references using the existing category editor. Invalid/nonexistent service keys are rejected before saving; old clients omitting the field preserve its current value.

Telegram category browsing and Mini App public catalogue share the binding filter: two service types on the same provider can have separate categories. Existing provider/scope/active-plan checks remain in force. Explicitly bound categories cannot fall through to another service when their selected service is disabled. Old Telegram category/plan selections refresh bindings. No existing subscription credentials, membership, quota or purchased service records are changed by this catalogue setting.

Service Type Add/Edit now has a color picker. Colors are validated as #RRGGBB, normalized and persisted under service_type_badge_color:<slug>. The admin card's active badge and icon use the selected color; Mini App category service labels receive the same color, and Telegram purchase/query menus use its closest supported circle emoji. Omitted colors preserve prior settings; legacy types have provider defaults. The new form labels support Persian.

Validation: 80 targeted tests pass, including six database/API/bot regressions covering assignment, switching, legacy preservation, duplicate IDs, disabled services, invalid keys/colors, rename persistence and session/CSRF enforcement. Full suite: 585 passed; the same five pre-existing unrelated failures remain. Production Next.js/TypeScript build passes. Browser checks add a category, edit its linked service, save a service color, verify rendered color and reopen the form to confirm persistence; all three mutations use the private website path and no JavaScript errors occurred. No live deployment was performed.


## Ready-made and custom service delivery templates (2026-10-21)

Custom now contains a dedicated delivery-template section. The default Simple preset sends the QR using the configured barcode artwork, a short caption with username, plan, traffic (including unlimited), validity and the exact subscription link, followed by the existing persistent Restart Bot button. The former caption with connection instructions remains selectable as Legacy. Existing inline controls and OpenVPN profile delivery are preserved; trial wording stays separate.

Admins can copy a preset, add/edit/delete up to 30 named custom templates, preview with sample data, and select a global default for both ordinary customers and resellers. Changes take effect after Save without restarting the bot. The saved configuration lives in Setting(service_delivery_templates_v1), so normal backups include it. Deleting an active custom template switches the pending selection to Simple. Existing raw Custom text controls remain available for Legacy. Selected ready-made/custom templates bypass legacy text matching only during their own send operations, preventing old fragment overrides from rewriting the chosen caption; the context resets after failures and is isolated between async tasks.

Formatting supports validated plain Telegram HTML and named placeholders only (username/title/traffic/duration/sub_link and the other listed fields). Dynamic values are HTML-escaped; malformed tags, unsupported fields/conversions, invalid entities, duplicate IDs, missing active choices and oversized input are rejected on save. A real subscription link omitted by a custom body is appended automatically, and OpenVPN passwords/access fields are preserved. Preview never sends a Telegram message. Existing long-caption delivery keeps QR and full links intact. Happ policy is resolved before template rendering. The direct reseller creation path uses the same template renderer and configured QR artwork.

Authenticated, same-origin/CSRF-protected endpoints: GET/POST /admin/api/v2/delivery-templates and POST /admin/api/v2/delivery-templates/preview. Validation: 93 related tests initially passed; final template-only tests (17 cases after two additional malformed-markup checks) pass. Full suite: 600 passed with the same five pre-existing unrelated failures. Next.js/TypeScript production build passes. Browser checks cover copying/editing, preview, selecting/saving/reopening the custom default, returning to Simple, private URL paths and a 390px layout with no overflow or JS errors. No live deployment was performed.
