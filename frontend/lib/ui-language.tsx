'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type UiLanguage = 'en' | 'fa';
const STORAGE_KEY = 'dbot_ui_language';

const EN_FA: Record<string, string> = {
  'Main': 'اصلی',
  'Dashboard': 'داشبورد',
  'Dashboard 👋': 'داشبورد 👋',
  'Sales': 'فروش',
  'Users': 'کاربران',
  'System': 'سیستم',
  'Service Types': 'نوع سرویس‌ها',
  'Test Account': 'اکانت تست',
  'Profile OpenVPN': 'پروفایل OpenVPN',
  'Plans': 'پلن‌ها',
  'Payments': 'پرداخت‌ها',
  'Discount Codes': 'کدهای تخفیف',
  'Resellers': 'نمایندگان',
  'Servers': 'سرورها',
  'Categories': 'دسته‌بندی‌ها',
  'Backup & Restore': 'بکاپ و بازیابی',
  'Custom': 'سفارشی‌سازی',
  'Settings': 'تنظیمات',
  'Create and manage the service categories visible inside the bot.': 'دسته‌بندی سرویس‌هایی را که داخل ربات نمایش داده می‌شوند ایجاد و مدیریت کنید.',
  'Configure the trial account users can receive from the Telegram bot.': 'اکانت تستی را که کاربران از ربات تلگرام دریافت می‌کنند تنظیم کنید.',
  'Upload, edit, view and bind .ovpn server profiles for MikroTik / Custom plans.': 'پروفایل‌های .ovpn را برای پلن‌های MikroTik / Custom آپلود، ویرایش، مشاهده و متصل کنید.',
  'Public plans and reseller packages with real server bindings.': 'پلن‌های عمومی و بسته‌های نمایندگی با اتصال واقعی به سرورها.',
  'Card-to-card and account destinations for public and reseller payments.': 'مقصدهای کارت‌به‌کارت و حساب برای پرداخت‌های عمومی و نمایندگی.',
  'Filter, review, and export all recent orders.': 'سفارش‌های اخیر را فیلتر، بررسی و خروجی بگیرید.',
  'Percentage and fixed Toman discount codes with per-user limits.': 'کدهای تخفیف درصدی و مبلغ ثابت با محدودیت استفاده برای هر کاربر.',
  'Search all Telegram users, wallets, reseller access, referrals and purchases.': 'کاربران تلگرام، کیف پول، دسترسی نمایندگی، دعوت‌ها و خریدها را جست‌وجو کنید.',
  'Manage reseller capacity, used traffic, and expiry dates.': 'ظرفیت نمایندگان، حجم مصرف‌شده و تاریخ انقضا را مدیریت کنید.',
  'Sanaei / 3x-ui servers and dedicated MikroTik / Custom router connections.': 'سرورهای Sanaei / 3x-ui و اتصال اختصاصی روترهای MikroTik / Custom.',
  'Group servers and plans for a clean purchase flow.': 'سرورها و پلن‌ها را برای یک مسیر خرید مرتب دسته‌بندی کنید.',
  'Route Telegram traffic through direct, proxy, MikroTik SOCKS, or V2/Xray connections.': 'مسیر اتصال ربات به تلگرام را از طریق اتصال مستقیم، پروکسی، SOCKS میکروتیک یا V2/Xray تنظیم کنید.',
  'Telegram Gateway': 'درگاه تلگرام',
  'Telegram Connection': 'کانکشن تلگرام',
  'Choose how D Bot reaches Telegram when the bot server has restricted or filtered outbound access.': 'روش اتصال D Bot به تلگرام را زمانی که دسترسی خروجی سرور محدود یا فیلتر است انتخاب کنید.',
  'Last test': 'آخرین تست',
  'Connected': 'متصل',
  'Failed': 'ناموفق',
  'Not tested': 'تست نشده',
  'Connection Mode': 'حالت کانکشن',
  'Connection setup steps': 'مراحل راه‌اندازی کانکشن',
  'Choose route': 'انتخاب مسیر',
  'Configure': 'پیکربندی',
  'Test & Apply': 'تست و اعمال',
  'Traffic Source': 'مبدأ ترافیک',
  'D Bot Server': 'سرور D Bot',
  'Application traffic': 'ترافیک برنامه',
  'Selected gateway': 'درگاه انتخاب‌شده',
  'Destination': 'مقصد',
  'Telegram API': 'API تلگرام',
  'Bot polling & messages': 'Polling و پیام‌های ربات',
  'Step 1': 'مرحله ۱',
  'Choose connection method': 'روش اتصال را انتخاب کنید',
  'Select the route that should carry Telegram traffic.': 'مسیری را انتخاب کنید که ترافیک تلگرام از آن عبور کند.',
  'Active:': 'فعال:',
  'No tunnel': 'بدون تونل',
  'HTTP / SOCKS': 'HTTP / SOCKS',
  'Encrypted tunnel': 'تونل رمزگذاری‌شده',
  'Router gateway': 'درگاه روتر',
  'Step 2': 'مرحله ۲',
  'Selected method': 'روش انتخاب‌شده',
  'Route type': 'نوع مسیر',
  'Applied method': 'روش اعمال‌شده',
  'Ready': 'آماده',
  'Choose the proxy protocol exposed by your gateway.': 'پروتکل پروکسی ارائه‌شده توسط درگاه را انتخاب کنید.',
  'Domain or public IP reachable from this server.': 'دامنه یا IP عمومی که از این سرور قابل دسترسی است.',
  'Paste one share link': 'یک لینک اشتراک وارد کنید',
  'D Bot will build the local Xray route automatically.': 'D Bot مسیر محلی Xray را به‌صورت خودکار می‌سازد.',
  'Router address reachable from the D Bot server.': 'آدرس روتری که از سرور D Bot قابل دسترسی است.',
  'Step 3': 'مرحله ۳',
  'Test before applying': 'قبل از اعمال تست کنید',
  'Verify Telegram reachability, then save the selected route.': 'دسترسی به تلگرام را بررسی کنید و سپس مسیر انتخاب‌شده را ذخیره کنید.',
  'Applied mode': 'حالت اعمال‌شده',
  'Revision': 'نسخه تنظیمات',
  'Direct': 'مستقیم',
  'Proxy': 'پروکسی',
  'V2 / Xray': 'V2 / Xray',
  'MikroTik SOCKS': 'SOCKS میکروتیک',
  'Use the server network directly for Telegram.': 'برای تلگرام مستقیماً از اینترنت سرور استفاده می‌کند.',
  'Connect through HTTP, SOCKS4 or SOCKS5.': 'اتصال از طریق HTTP، SOCKS4 یا SOCKS5.',
  'Use a VLESS, VMess, Trojan or Shadowsocks share link.': 'استفاده از لینک VLESS، VMess، Trojan یا Shadowsocks.',
  'Route Telegram through a MikroTik SOCKS5 gateway.': 'عبور اتصال تلگرام از درگاه SOCKS5 میکروتیک.',
  'Connection Settings': 'تنظیمات کانکشن',
  'Only the Telegram bot traffic is routed through this connection.': 'فقط ترافیک تلگرام ربات از این کانکشن عبور می‌کند.',
  'Telegram-only route': 'مسیر اختصاصی تلگرام',
  'Bot polling, messages and Telegram API requests use this gateway. Other server traffic stays untouched.': 'Polling، پیام‌ها و درخواست‌های API تلگرام ربات از این درگاه عبور می‌کنند و سایر ترافیک سرور بدون تغییر باقی می‌ماند.',
  'Bot API': 'API ربات',
  'Polling': 'دریافت آپدیت',
  'Messages': 'پیام‌ها',
  'Gateway profile': 'پروفایل درگاه',
  'Endpoint': 'نقطه اتصال',
  'Credentials': 'اطلاعات ورود',
  'Server network': 'شبکه سرور',
  'Not required': 'نیازی ندارد',
  'Configured share link': 'لینک اشتراک تنظیم‌شده',
  'Encrypted share link': 'لینک اشتراک رمزگذاری‌شده',
  'Gateway Endpoint': 'نقطه اتصال درگاه',
  'Set where D Bot should connect and which protocol it should use.': 'محل اتصال D Bot و پروتکل مورد استفاده را مشخص کنید.',
  'Authentication': 'احراز هویت',
  'Optional credentials are encrypted when saved.': 'اطلاعات ورود اختیاری هنگام ذخیره رمزگذاری می‌شوند.',
  'Enter the MikroTik SOCKS gateway reachable from the D Bot server.': 'درگاه SOCKS میکروتیک قابل دسترسی از سرور D Bot را وارد کنید.',
  'No gateway required': 'نیازی به درگاه نیست',
  "D Bot will use the server's default internet connection.": 'D Bot از اینترنت پیش‌فرض سرور استفاده می‌کند.',
  'Proxy Protocol': 'پروتکل پروکسی',
  'Proxy Host': 'هاست پروکسی',
  'Proxy Port': 'پورت پروکسی',
  'Proxy Username': 'نام کاربری پروکسی',
  'Proxy Password': 'رمز عبور پروکسی',
  'Port': 'پورت',
  'Configured': 'تنظیم‌شده',
  'Endpoint Preview': 'پیش‌نمایش نقطه اتصال',
  'Waiting for gateway address': 'در انتظار آدرس درگاه',
  'Encrypted credentials': 'اطلاعات ورود رمزگذاری‌شده',
  'Secrets are stored encrypted and are never returned to the browser after saving.': 'اطلاعات محرمانه به‌صورت رمزگذاری‌شده ذخیره می‌شوند و پس از ذخیره دوباره به مرورگر برگردانده نمی‌شوند.',
  'Optional': 'اختیاری',
  'Configured — leave empty to keep current': 'تنظیم شده — برای حفظ مقدار فعلی خالی بگذارید',
  'V2 Share Link': 'لینک اشتراک V2',
  'Configured — paste a new link only to replace it': 'تنظیم شده — فقط برای جایگزینی، لینک جدید وارد کنید',
  'Supported protocols': 'پروتکل‌های پشتیبانی‌شده',
  'Saved protocol': 'پروتکل ذخیره‌شده',
  'Xray runtime': 'وضعیت Xray',
  'Available': 'در دسترس',
  'Not installed in image': 'در ایمیج نصب نشده',
  'Saved V2 link is configured and encrypted.': 'لینک V2 ذخیره و رمزگذاری شده است.',
  'Common TCP/RAW, WebSocket, gRPC, XHTTP/HTTPUpgrade transports plus TLS and REALITY share-link parameters are handled by the local Xray gateway.': 'ترنسپورت‌های رایج TCP/RAW، WebSocket، gRPC، XHTTP/HTTPUpgrade و پارامترهای TLS و REALITY توسط درگاه محلی Xray مدیریت می‌شوند.',
  'MikroTik Host / IP': 'هاست / IP میکروتیک',
  'SOCKS Port': 'پورت SOCKS',
  'SOCKS Username': 'نام کاربری SOCKS',
  'SOCKS Password': 'رمز عبور SOCKS',
  'RouterOS SOCKS/SOCKS5 must be enabled and reachable from the D Bot server. Restrict access to the bot server IP whenever possible.': 'SOCKS/SOCKS5 در RouterOS باید فعال و از سرور D Bot قابل دسترسی باشد. در صورت امکان دسترسی را فقط به IP سرور ربات محدود کنید.',
  'Testing…': 'در حال تست…',
  'Test Telegram Connection': 'تست اتصال تلگرام',
  'Saving…': 'در حال ذخیره…',
  'Save & Apply': 'ذخیره و اعمال',
  'Connection Status': 'وضعیت کانکشن',
  'Current mode': 'حالت فعلی',
  'Latency': 'تاخیر',
  'Last test time': 'زمان آخرین تست',
  'Secrets stay protected': 'اطلاعات محرمانه محافظت می‌شوند',
  'Saved passwords and V2 links are encrypted in the database and are never returned to the browser.': 'رمزهای ذخیره‌شده و لینک‌های V2 در دیتابیس رمزگذاری می‌شوند و دوباره به مرورگر برگردانده نمی‌شوند.',
  'Connection settings could not be loaded.': 'تنظیمات کانکشن بارگذاری نشد.',
  'Telegram connection test passed.': 'تست اتصال تلگرام موفق بود.',
  'Telegram connection test failed.': 'تست اتصال تلگرام ناموفق بود.',
  'Connection settings saved. The Telegram bot is reloading automatically.': 'تنظیمات کانکشن ذخیره شد و ربات تلگرام به‌صورت خودکار در حال بارگذاری مجدد است.',
  'Connection settings could not be saved.': 'تنظیمات کانکشن ذخیره نشد.',
  'Configure website and bot backups, test Telegram delivery, and restore local backup files safely.': 'بکاپ سایت و ربات را تنظیم، ارسال تلگرام را تست و فایل‌های بکاپ را با امنیت بازیابی کنید.',
  'View, search, edit and reset every detected Telegram bot message, prompt, caption and button label.': 'پیام‌ها، پرامپت‌ها، کپشن‌ها و متن دکمه‌های قابل مشاهده کاربر را ببینید، جست‌وجو، ویرایش یا بازنشانی کنید.',
  'General bot settings, website login, user-facing menu controls and installation tools.': 'تنظیمات عمومی ربات، ورود وب، کنترل منوهای کاربر و ابزارهای نصب.',

  'Search anything...': 'جست‌وجو در پنل...',
  'Admin': 'مدیر',
  'Owner': 'مالک',
  'Close sidebar': 'بستن نوار کناری',
  'Admin navigation': 'منوی مدیریت',
  'Open navigation': 'باز کردن منو',
  'Close navigation': 'بستن منو',
  'D Bot on GitHub': 'D Bot در GitHub',
  'GitHub Project': 'پروژه GitHub',
  'Language': 'زبان',
  'English': 'انگلیسی',
  'Persian': 'فارسی',
  'Refresh': 'بروزرسانی',
  'Apply': 'اعمال',
  'Save': 'ذخیره',
  'Cancel': 'انصراف',
  'Edit': 'ویرایش',
  'Delete': 'حذف',
  'Add': 'افزودن',
  'Back': 'بازگشت',
  'Next': 'بعدی',
  'Previous': 'قبلی',
  'Select': 'انتخاب',
  'Clear all': 'پاک‌کردن همه',
  'Select all': 'انتخاب همه',
  'Active': 'فعال',
  'Inactive': 'غیرفعال',
  'Enabled': 'فعال',
  'Disabled': 'غیرفعال',
  'Public': 'عمومی',
  'Reseller': 'نماینده',
  'Automatic': 'خودکار',
  'Manual': 'دستی',
  'Unlimited': 'نامحدود',
  'None': 'ندارد',
  'Status': 'وضعیت',
  'Date': 'تاریخ',
  'User': 'کاربر',
  'Plan': 'پلن',
  'Amount': 'مبلغ',
  'Payment': 'پرداخت',
  'Server': 'سرور',
  'Category': 'دسته‌بندی',
  'Type': 'نوع',
  'Value': 'مقدار',
  'Expires': 'انقضا',
  'Created': 'ایجاد شده',
  'Username': 'نام کاربری',
  'Password': 'رمز عبور',
  'Owner name': 'نام صاحب حساب',
  'Full name': 'نام کامل',
  'Telegram username': 'نام کاربری تلگرام',
  'Telegram ID': 'شناسه تلگرام',
  'Price': 'قیمت',
  'Volume': 'حجم',
  'Duration': 'مدت',
  'Usage': 'مصرف',
  'Remaining': 'باقی‌مانده',
  'Total': 'کل',
  'Used': 'مصرف‌شده',
  'Reserved': 'رزرو شده',
  'Source': 'منبع',
  'Action': 'عملیات',
  'Details': 'جزئیات',
  'Connection': 'کانکشن',
  'Profile': 'پروفایل',

  'Login required': 'ورود لازم است',
  'Your admin session is not active. Login again to open the D BOT admin panel.': 'نشست مدیریت شما فعال نیست. برای ورود به پنل D BOT دوباره وارد شوید.',
  'Open Login': 'رفتن به صفحه ورود',
  'Website login changed. Please login again.': 'اطلاعات ورود وب تغییر کرد. لطفاً دوباره وارد شوید.',
  'Web path changed successfully.': 'مسیر وب با موفقیت تغییر کرد.',
  'Saved successfully': 'با موفقیت ذخیره شد',
  'Please login again': 'لطفاً دوباره وارد شوید',
  'Action completed': 'عملیات با موفقیت انجام شد',
  'Are you sure?': 'آیا مطمئن هستید؟',
  'Please choose an image file': 'لطفاً یک فایل تصویر انتخاب کنید',
  'Profile photo updated': 'تصویر پروفایل بروزرسانی شد',
  'Profile photo removed': 'تصویر پروفایل حذف شد',
  'Admin Profile': 'پروفایل مدیر',
  'Role:': 'نقش:',
  'Upload profile image': 'آپلود تصویر پروفایل',
  'Remove photo': 'حذف تصویر',
  'Logout': 'خروج',

  'Total Revenue': 'درآمد کل',
  'New Orders': 'سفارش‌های جدید',
  'Total Users': 'کل کاربران',
  'Active Services': 'سرویس‌های فعال',
  'Revenue Overview': 'نمای کلی درآمد',
  'Export All Months': 'خروجی همه ماه‌ها',
  'View Report & Date Filters': 'مشاهده گزارش و فیلتر تاریخ',
  'Export Selected Dates': 'خروجی بازه انتخابی',
  'Export All History': 'خروجی کل سابقه',
  'Reset Display': 'شروع دوره جدید',
  'Resetting...': 'در حال بازنشانی...',
  'Start a new permanent 30-day display period? Previous sales remain in Export.': 'یک دوره نمایش ۳۰ روزه جدید شروع شود؟ فروش‌های قبلی در بخش خروجی باقی می‌مانند.',
  'A new 30-day period has started. Previous sales remain in Export.': 'دوره ۳۰ روزه جدید شروع شد. فروش‌های قبلی در بخش خروجی باقی ماندند.',
  'vs previous range': 'نسبت به بازه قبلی',
  'System Status': 'وضعیت سیستم',
  'Live resource usage': 'مصرف لحظه‌ای منابع',
  'Live': 'زنده',
  'CPU Usage': 'مصرف CPU',
  'RAM Usage': 'مصرف RAM',
  'Disk Usage': 'مصرف دیسک',
  'Network': 'شبکه',
  'Recent Orders': 'سفارش‌های اخیر',
  'View all': 'مشاهده همه',
  'Order ID': 'شناسه سفارش',
  'Dashboard could not be loaded.': 'داشبورد بارگذاری نشد.',
  'Users could not be loaded.': 'کاربران بارگذاری نشدند.',
  'Servers could not be loaded.': 'سرورها بارگذاری نشدند.',
  'Categories could not be loaded.': 'دسته‌بندی‌ها بارگذاری نشدند.',
  'Plans could not be loaded.': 'پلن‌ها بارگذاری نشدند.',
  'Payments could not be loaded.': 'پرداخت‌ها بارگذاری نشدند.',
  'Discounts could not be loaded.': 'کدهای تخفیف بارگذاری نشدند.',
  'Resellers could not be loaded.': 'نمایندگان بارگذاری نشدند.',
  'Orders could not be loaded.': 'سفارش‌ها بارگذاری نشدند.',
  'Settings could not be loaded.': 'تنظیمات بارگذاری نشد.',
  'Backup settings could not be loaded.': 'تنظیمات بکاپ بارگذاری نشد.',
  'Test account settings could not be loaded.': 'تنظیمات اکانت تست بارگذاری نشد.',
  'Service types could not be loaded.': 'نوع سرویس‌ها بارگذاری نشد.',
  'OpenVPN profiles could not be loaded.': 'پروفایل‌های OpenVPN بارگذاری نشدند.',

  'Add Profile': 'افزودن پروفایل',
  'Edit / View text': 'ویرایش / مشاهده متن',
  'Profile activated': 'پروفایل فعال شد',
  'Profile deactivated': 'پروفایل غیرفعال شد',
  'Profile deleted': 'پروفایل حذف شد',
  'Server ID': 'شناسه سرور',
  'Profile ID': 'شناسه پروفایل',
  'Content size': 'حجم محتوا',
  'Test connection and update server status?': 'اتصال تست و وضعیت سرور بروزرسانی شود؟',
  'Connection OK. Server updated.': 'اتصال موفق بود. سرور بروزرسانی شد.',
  'Add Server': 'افزودن سرور',
  'Edit Server': 'ویرایش سرور',
  'Test & Update': 'تست و بروزرسانی',
  'Duplicate': 'کپی',
  'Server activated': 'سرور فعال شد',
  'Server deactivated': 'سرور غیرفعال شد',
  'Server duplicated': 'سرور کپی شد',
  'Service badge': 'برچسب سرویس',
  'Circle color': 'رنگ دایره',
  'Router host': 'آدرس روتر',
  'Router port': 'پورت روتر',
  'PPP users': 'کاربران PPP',
  'Last sync': 'آخرین همگام‌سازی',
  'Login user': 'کاربر ورود',
  'MikroTik / OpenVPN': 'MikroTik / OpenVPN',
  'MikroTik / Custom': 'MikroTik / Custom',
  '3x-ui / Sanaei 3.8.0': '3x-ui / Sanaei 3.8.0',
  'Show this server for': 'نمایش این سرور برای',
  'Server name shown to users': 'نام سرور برای کاربران',
  'Display name': 'نام نمایشی',
  'Service badge text shown to users': 'متن برچسب سرویس برای کاربران',
  'Circle color in website': 'رنگ دایره در وب',
  'Circle emoji in bot (auto from color)': 'ایموجی دایره در ربات (خودکار از رنگ)',
  'Panel URL / Origin': 'آدرس پنل / Origin',
  'Panel Web Path': 'مسیر وب پنل',
  'Subscription URL': 'لینک سابسکریپشن',
  'Username (optional when API token is used)': 'نام کاربری (در صورت استفاده از API Token اختیاری)',
  'L2TP server shown in guides': 'سرور L2TP در راهنماها',
  'L2TP Secret shown in guides': 'L2TP Secret در راهنماها',
  'PasarGuard role': 'نقش PasarGuard',
  'User scope': 'محدوده کاربران',
  'Group source': 'منبع گروه‌ها',
  'Template ID': 'شناسه قالب',
  'API Token Panel': 'توکن API پنل',
  'Restricted': 'محدود',
  'Optional for restricted admins: 12,15,20': 'اختیاری برای ادمین محدود: 12,15,20',
  'Use only if Auto Fill cannot read groups, e.g. 12,15,20': 'فقط اگر تکمیل خودکار نتوانست گروه‌ها را بخواند وارد کنید؛ مثلاً 12,15,20',
  'Only if the owner role requires a user template': 'فقط وقتی نقش تعریف‌شده توسط مالک، قالب کاربر را اجباری کرده است',
  'Detected routers': 'روترهای شناسایی‌شده',
  'Auto-filled after Test & Auto Fill': 'بعد از Test & Auto Fill خودکار تکمیل می‌شود',
  'Test & Auto Fill': 'تست و تکمیل خودکار',
  'Public sales': 'فروش عمومی',
  'Public + Reseller': 'عمومی + نماینده',

  'Add Category': 'افزودن دسته‌بندی',
  'Edit Category': 'ویرایش دسته‌بندی',
  'Category name': 'نام دسته‌بندی',
  'Servers shown under this category': 'سرورهای نمایش‌داده‌شده در این دسته',
  'Category ID': 'شناسه دسته‌بندی',
  'Linked servers': 'سرورهای متصل',
  'Server IDs': 'شناسه سرورها',
  'Category activated': 'دسته‌بندی فعال شد',
  'Category deactivated': 'دسته‌بندی غیرفعال شد',
  'Category deleted': 'دسته‌بندی حذف شد',
  'Clear search to reorder.': 'برای تغییر ترتیب، جست‌وجو را پاک کنید.',
  'Saving...': 'در حال ذخیره...',
  'Drag': 'جابجایی',
  'Category order saved for the Telegram bot': 'ترتیب دسته‌بندی برای ربات تلگرام ذخیره شد',

  'Add Plan': 'افزودن پلن',
  'Edit Plan': 'ویرایش پلن',
  'Plan title': 'عنوان پلن',
  'Plan is for': 'پلن برای',
  'Public Plans Order': 'ترتیب پلن‌های عمومی',
  'Reseller Plans Order': 'ترتیب پلن‌های نمایندگی',
  'Bot Sales': 'فروش ربات',
  'Reseller Menu': 'منوی نماینده',
  'Public / Active': 'عمومی / فعال',
  'Public / Inactive': 'عمومی / غیرفعال',
  'Reseller / Active': 'نماینده / فعال',
  'Reseller / Inactive': 'نماینده / غیرفعال',
  'Pricing currency': 'واحد قیمت‌گذاری',
  'Toman — fixed price': 'تومان — قیمت ثابت',
  'USD — live Wallex rate at checkout': 'دلار — نرخ لحظه‌ای والکس هنگام خرید',
  'Price (Toman)': 'قیمت (تومان)',
  'Price (USD)': 'قیمت (دلار)',
  'Volume GB': 'حجم (GB)',
  'Duration days': 'مدت (روز)',
  'Validity days': 'اعتبار (روز)',
  'Reseller validity days': 'اعتبار نمایندگی (روز)',
  'HWID device limit (0 = unlimited)': 'محدودیت دستگاه HWID (۰ = نامحدود)',
  'Sanaei client group': 'گروه کاربر Sanaei',
  'Inbound selection mode': 'حالت انتخاب Inbound',
  'Automatic — use all active server inbounds': 'خودکار — استفاده از تمام Inboundهای فعال',
  'Manual — choose specific inbounds': 'دستی — انتخاب Inboundهای مشخص',
  'Inbounds included in this plan': 'Inboundهای این پلن',
  'Inbound mode': 'حالت Inbound',
  'All active': 'همه فعال‌ها',
  'Client group': 'گروه کاربر',
  'HWID devices': 'دستگاه‌های HWID',
  'Plan activated': 'پلن فعال شد',
  'Plan deactivated': 'پلن غیرفعال شد',
  'Plan deleted': 'پلن حذف شد',
  'Public plan order saved': 'ترتیب پلن‌های عمومی ذخیره شد',
  'Reseller plan order saved': 'ترتیب پلن‌های نمایندگی ذخیره شد',
  'Reseller plan activated': 'پلن نمایندگی فعال شد',
  'Reseller plan deactivated': 'پلن نمایندگی غیرفعال شد',
  'Reseller plan deleted': 'پلن نمایندگی حذف شد',
  'Drag and drop cards to change the order shown inside the Telegram bot sales list.': 'برای تغییر ترتیب نمایش در لیست فروش ربات تلگرام، کارت‌ها را بکشید و رها کنید.',

  'Add Payment': 'افزودن حساب پرداخت',
  'Card / Account': 'کارت / حساب',
  'Card / account number': 'شماره کارت / حساب',
  'Server Type': 'نوع سرور',
  'Receipt reviewer': 'بررسی‌کننده رسید',
  'Main admins': 'مدیران اصلی',
  'Where to show': 'محل نمایش',
  'Server for public payment': 'سرور برای پرداخت عمومی',
  'Server owner / receipt reviewer Telegram ID (0 = main admins)': 'شناسه تلگرام مالک سرور / بررسی‌کننده رسید (۰ = مدیران اصلی)',
  'Payment account deleted': 'حساب پرداخت حذف شد',
  'Card to Card': 'کارت به کارت',
  'Reseller Payment': 'پرداخت نمایندگی',
  'Crypto': 'ارز دیجیتال',

  'Add Discount': 'افزودن تخفیف',
  'Discount type': 'نوع تخفیف',
  'Percent (%)': 'درصد (%)',
  'Toman amount': 'مبلغ تومان',
  'Discount value': 'مقدار تخفیف',
  'Max uses': 'حداکثر استفاده',
  'Per user limit': 'محدودیت هر کاربر',
  'Allowed servers for this discount': 'سرورهای مجاز برای این تخفیف',
  'All servers': 'همه سرورها',
  'Per User': 'هر کاربر',
  'Allowed servers': 'سرورهای مجاز',
  'Discount deleted': 'کد تخفیف حذف شد',
  'Percent': 'درصد',
  'Toman': 'تومان',

  'Add Reseller': 'افزودن نماینده',
  'Assigned reseller server': 'سرور اختصاص‌یافته به نماینده',
  'Sanaei client group for new reseller configurations': 'گروه Sanaei برای کانفیگ‌های جدید نماینده',
  'Reseller inbound mode': 'حالت Inbound نماینده',
  'Manual — restrict this reseller to selected inbounds': 'دستی — محدود کردن نماینده به Inboundهای انتخابی',
  'Allowed inbounds for this reseller': 'Inboundهای مجاز برای نماینده',
  'Find user from database': 'پیدا کردن کاربر از دیتابیس',
  'Telegram numeric ID': 'شناسه عددی تلگرام',
  'Remaining days': 'روزهای باقی‌مانده',
  'Refresh Stats': 'بروزرسانی آمار',
  'Refreshing': 'در حال بروزرسانی',
  'List': 'لیست',
  'Reseller deleted': 'نماینده حذف شد',
  'Reseller accounting refreshed': 'حسابداری نماینده بروزرسانی شد',
  'Total configs': 'کل کانفیگ‌ها',
  'Active configs': 'کانفیگ‌های فعال',
  'Created orders': 'سفارش‌های ایجاد سرویس',
  'Renewal orders': 'سفارش‌های تمدید',
  'Quota recharges': 'شارژهای سهمیه',
  'Failed operations': 'عملیات ناموفق',
  'Loading reseller configs...': 'در حال بارگذاری کانفیگ‌های نماینده...',
  'Activity & renewal history': 'سابقه فعالیت و تمدید',
  'Current configs': 'کانفیگ‌های فعلی',
  'Service volume': 'حجم سرویس',
  'Reseller quota before': 'سهمیه نماینده قبل از عملیات',
  'Remaining after this operation': 'باقی‌مانده پس از این عملیات',
  'Historical remaining quota': 'سهمیه باقی‌مانده تاریخی',
  'Not stored in older version': 'در نسخه قدیمی ذخیره نشده',
  'Current reseller quota now': 'سهمیه فعلی نماینده',
  'Quota purchased': 'سهمیه خریداری‌شده',
  'Volume added to service': 'حجم افزوده‌شده به سرویس',
  'Quota change': 'تغییر سهمیه',
  'Days added to service': 'روز افزوده‌شده به سرویس',
  'No reseller activity has been recorded yet.': 'هنوز فعالیتی برای این نماینده ثبت نشده است.',
  'No error message was returned.': 'پیام خطایی برگردانده نشد.',

  'Rejection reason': 'دلیل رد',
  'Edit General': 'ویرایش عمومی',
  'Edit Bot Core': 'ویرایش هسته ربات',
  'Edit Setup': 'ویرایش راه‌اندازی',
  'Manage Buttons': 'مدیریت دکمه‌ها',
  'Bot Name': 'نام ربات',
  'Bot name': 'نام ربات',
  'Support username': 'نام کاربری پشتیبانی',
  'Bot description': 'توضیحات ربات',
  'Bot Off': 'ربات خاموش',
  'Bot On': 'ربات روشن',
  'Start Text': 'متن شروع',
  'Forced Channel': 'کانال اجباری',
  'Rules Text': 'متن قوانین',
  'Bot Status': 'وضعیت ربات',
  'Database Info': 'اطلاعات دیتابیس',
  'Website & SSL': 'وب‌سایت و SSL',
  'Website & SSL — Edit Setup': 'وب‌سایت و SSL — ویرایش راه‌اندازی',
  'Online links': 'لینک‌های آنلاین',
  'Web Path': 'مسیر وب',
  'Login link': 'لینک ورود',
  'Admin panel': 'پنل مدیریت',
  'Rename or enable/disable user-facing bot buttons': 'تغییر نام یا فعال/غیرفعال کردن دکمه‌های قابل مشاهده کاربر',
  'Applies to': 'اعمال برای',
  'Main menu, reseller/admin entry and wallet top-up': 'منوی اصلی، ورود نماینده/مدیر و شارژ کیف پول',
  'Update time': 'زمان اعمال',
  'Applied from database on the next menu view': 'در اولین نمایش بعدی منو از دیتابیس اعمال می‌شود',
  'Domain': 'دامنه',
  'Current Web Admin Username': 'نام کاربری فعلی مدیریت وب',
  'New password — leave empty to keep current': 'رمز جدید — برای حفظ رمز فعلی خالی بگذارید',
  'Session timeout (minutes)': 'زمان انقضای نشست (دقیقه)',
  'Start text': 'متن شروع',
  'Forced channel': 'کانال اجباری',
  'No — disabled': 'خیر — غیرفعال',
  'Yes — require membership': 'بله — عضویت اجباری',
  'Forced channel address': 'آدرس کانال اجباری',
  'Rules page': 'صفحه قوانین',
  'No — do not show rules': 'خیر — قوانین نمایش داده نشود',
  'Yes — users must accept rules': 'بله — کاربران باید قوانین را بپذیرند',
  'Rules text': 'متن قوانین',
  'Bot status': 'وضعیت ربات',
  'Database information text': 'متن اطلاعات دیتابیس',

  'Factory Reset': 'بازنشانی کارخانه',
  'Erase local D BOT data and return this installation to first-run setup.': 'تمام داده‌های محلی D BOT را پاک و نصب را به مرحله راه‌اندازی اولیه برگردانید.',
  'Danger Zone': 'منطقه خطر',
  'Fresh-install reset': 'بازنشانی کامل نصب',
  'Factory Reset will permanently erase ALL D BOT database data and settings. Continue?': 'بازنشانی کارخانه تمام داده‌ها و تنظیمات دیتابیس D BOT را برای همیشه حذف می‌کند. ادامه می‌دهید؟',
  'Type FACTORY RESET to confirm:': 'برای تأیید عبارت FACTORY RESET را وارد کنید:',
  'Factory Reset cancelled. Confirmation text did not match.': 'بازنشانی لغو شد. متن تأیید صحیح نبود.',
  'Factory Reset completed': 'بازنشانی کارخانه کامل شد',

  'Backup Delivery': 'ارسال بکاپ',
  'Sender bot': 'ربات ارسال‌کننده',
  'Current D BOT': 'D BOT فعلی',
  'Secondary backup bot': 'ربات بکاپ دوم',
  'Backup cycle': 'دوره بکاپ',
  'Every 1 hour': 'هر ۱ ساعت',
  'Every 3 hours': 'هر ۳ ساعت',
  'Every 6 hours': 'هر ۶ ساعت',
  'Every 12 hours': 'هر ۱۲ ساعت',
  'Every 24 hours': 'هر ۲۴ ساعت',
  'Every 7 days': 'هر ۷ روز',
  'Every 30 days': 'هر ۳۰ روز',
  'Secondary bot token': 'توکن ربات دوم',
  'Send backup to': 'ارسال بکاپ به',
  'Channel': 'کانال',
  'Group': 'گروه',
  'Owner / bot chat': 'مالک / چت ربات',
  'Owner chat ID': 'شناسه چت مالک',
  'Channel address': 'آدرس کانال',
  'Group address': 'آدرس گروه',
  'Database backup': 'بکاپ دیتابیس',
  'Files backup': 'بکاپ فایل‌ها',
  'Send Fresh Test Message': 'ارسال پیام تست جدید',
  'Send Backup Now': 'ارسال بکاپ الآن',
  'Send Sales Report Now': 'ارسال گزارش فروش الآن',
  'Download Portable JSON': 'دانلود JSON قابل انتقال',
  'Restore Portable Backup': 'بازیابی بکاپ قابل انتقال',
  'Cross-install Sync': 'همگام‌سازی بین نصب‌ها',
  'Restore an old format 1–3 backup': 'بازیابی بکاپ قدیمی نسخه ۱ تا ۳',
  'Source secret type': 'نوع کلید منبع',
  'Auto detect': 'تشخیص خودکار',
  'Old FERNET_KEY': 'FERNET_KEY قدیمی',
  'Old Telegram bot token': 'توکن قدیمی ربات تلگرام',
  'Old source secret': 'کلید منبع قدیمی',
  'Backup settings saved': 'تنظیمات بکاپ ذخیره شد',
  'Fresh test message sent': 'پیام تست جدید ارسال شد',
  'Manual backup created and sent': 'بکاپ دستی ساخته و ارسال شد',
  '30-day sales PDF report sent': 'گزارش PDF فروش ۳۰ روزه ارسال شد',
  'Choose a JSON backup file first': 'ابتدا یک فایل بکاپ JSON انتخاب کنید',
  'Enter the old source FERNET_KEY or old bot token first': 'ابتدا FERNET_KEY منبع قدیمی یا توکن قدیمی ربات را وارد کنید',
  'Restore and fully synchronize this backup? Current database data on this installation will be replaced.': 'این بکاپ بازیابی و کاملاً همگام شود؟ داده‌های فعلی دیتابیس این نصب جایگزین می‌شوند.',
  'Restore failed': 'بازیابی ناموفق بود',
  'Backup restored': 'بکاپ بازیابی شد',
  'Backup & Sales Reports': 'بکاپ و گزارش‌های فروش',
  'Sales PDF OK': 'PDF فروش سالم است',
  'Last backup OK': 'آخرین بکاپ موفق',
  'Last backup error': 'خطای آخرین بکاپ',
  'Last backup': 'آخرین بکاپ',
  'Last sales PDF': 'آخرین PDF فروش',
  'Sales PDF status': 'وضعیت PDF فروش',
  'Uses the same Telegram destination as backups': 'از همان مقصد تلگرام بکاپ‌ها استفاده می‌کند',
  'Choose portable backup file': 'انتخاب فایل بکاپ قابل انتقال',
  'Unlock, Restore & Sync': 'بازکردن، بازیابی و همگام‌سازی',
  'Restore & Sync': 'بازیابی و همگام‌سازی',

  'Telegram Trial Account': 'اکانت تست تلگرام',
  'Button': 'دکمه',
  'Used by users': 'استفاده‌شده توسط کاربران',
  'Reset usage history': 'پاک‌کردن سابقه استفاده',
  'Test Account Settings': 'تنظیمات اکانت تست',
  'Test account status': 'وضعیت اکانت تست',
  'Bot button visibility': 'نمایش دکمه در ربات',
  'Show button': 'نمایش دکمه',
  'Hide button': 'مخفی‌کردن دکمه',
  'Inbound IDs': 'شناسه‌های Inbound',
  'Use all automatically': 'استفاده خودکار از همه',
  'No inbound found. Use Servers → Test & Update first.': 'Inboundی پیدا نشد. ابتدا از Servers → Test & Update استفاده کنید.',
  'Trial volume': 'حجم تست',
  'Trial duration': 'مدت تست',
  'Save Test Account': 'ذخیره اکانت تست',
  'Users who used test account': 'کاربرانی که اکانت تست گرفته‌اند',
  'User Telegram ID': 'شناسه تلگرام کاربر',
  'Search and remove one user': 'جست‌وجو و حذف یک کاربر',
  'Remove this user': 'حذف این کاربر',
  'Service': 'سرویس',
  'Reset all test-account users': 'بازنشانی همه کاربران اکانت تست',
  'Test account settings saved': 'تنظیمات اکانت تست ذخیره شد',
  'Reset test account usage history? Users will be able to receive a test account again.': 'سابقه استفاده اکانت تست پاک شود؟ کاربران دوباره می‌توانند اکانت تست دریافت کنند.',
  'Usage history reset': 'سابقه استفاده پاک شد',
  'Enter User Telegram ID first': 'ابتدا شناسه تلگرام کاربر را وارد کنید',
  'User Telegram ID must be numeric': 'شناسه تلگرام کاربر باید عددی باشد',

  'Add Service Type': 'افزودن نوع سرویس',
  'Service name': 'نام سرویس',
  'Backend provider': 'ارائه‌دهنده بک‌اند',
  'Auto detect — compatible with existing types': 'تشخیص خودکار — سازگار با نوع‌های سرویس قبلی',
  'X-UI / 3x-ui / Sanaei': 'X-UI / 3x-ui / Sanaei',
  'MikroTik / OpenVPN / L2TP': 'MikroTik / OpenVPN / L2TP',
  'Each service type must route to the backend provider that owns its plans. Use PasarGuard for PasarGuard servers, X-UI for 3x-ui/Sanaei, or MikroTik for OpenVPN/L2TP. Auto mode keeps backward-compatible detection.': 'هر نوع سرویس باید به ارائه‌دهنده‌ای وصل شود که پلن‌های آن روی همان پنل هستند. برای سرورهای PasarGuard گزینه PasarGuard، برای 3x-ui/Sanaei گزینه X-UI و برای OpenVPN/L2TP گزینه MikroTik را انتخاب کنید. حالت Auto برای سازگاری با تنظیمات قبلی باقی مانده است.',
  'Display order': 'ترتیب نمایش',
  'Service type activated': 'نوع سرویس فعال شد',
  'Service type deactivated': 'نوع سرویس غیرفعال شد',
  'Service type deleted': 'نوع سرویس حذف شد',
  'Service type order saved': 'ترتیب نوع سرویس ذخیره شد',
  'No custom service type found. Add V2Ray, OpenVPN, or any other service from here.': 'نوع سرویس سفارشی پیدا نشد. V2Ray، OpenVPN یا هر سرویس دیگری را از اینجا اضافه کنید.',

  'Search name, numeric ID, or username': 'جست‌وجوی نام، شناسه عددی یا نام کاربری',
  'Searching...': 'در حال جست‌وجو...',
  'No items found.': 'موردی پیدا نشد.',
  'Not configured': 'تنظیم نشده',
  'Configured — leave empty to keep current token': 'تنظیم شده — برای حفظ توکن فعلی خالی بگذارید',
  'Enter token from @BotFather': 'توکن دریافتی از @BotFather را وارد کنید',
  'Leave empty to use first OWNER_ID': 'برای استفاده از اولین OWNER_ID خالی بگذارید',
  'No destination test yet': 'هنوز مقصد تست نشده',
  'Backup delivery test': 'تست ارسال بکاپ',

  'Preparing Custom Center…': 'در حال آماده‌سازی بخش سفارشی‌سازی…',
  'Loading user-visible bot messages and buttons.': 'در حال بارگذاری پیام‌ها و دکمه‌های قابل مشاهده کاربران.',
  'D Bot Custom Center': 'مرکز سفارشی‌سازی D Bot',
  'Shape every user-facing message around your brand': 'همه پیام‌های کاربر را مطابق برند خود تنظیم کنید',
  'Only real user journeys are shown here — from start and purchase to payment, receipt approval, service delivery, renewal, support, and service alerts.': 'فقط مسیرهای واقعی کاربر اینجا نمایش داده می‌شوند؛ از شروع و خرید تا پرداخت، تأیید رسید، تحویل سرویس، تمدید، پشتیبانی و هشدارهای سرویس.',
  'Reset All': 'بازنشانی همه',
  'Custom text statistics': 'آمار متن‌های سفارشی',
  'Total User Texts': 'کل متن‌های کاربر',
  'Customized': 'سفارشی‌شده',
  'Project Defaults': 'پیش‌فرض پروژه',
  'Search user-facing bot messages…': 'جست‌وجو در پیام‌های قابل مشاهده کاربر…',
  'Clear search': 'پاک‌کردن جست‌وجو',
  'matching items': 'مورد مطابق',
  'Text type': 'نوع متن',
  'All': 'همه',
  'Message': 'پیام',
  'All Categories': 'همه دسته‌بندی‌ها',
  'User stage': 'مرحله کاربر',
  'All User Stages': 'همه مراحل کاربر',
  'Text status': 'وضعیت متن',
  'All Statuses': 'همه وضعیت‌ها',
  'Customized Only': 'فقط سفارشی‌شده‌ها',
  'Default Only': 'فقط پیش‌فرض‌ها',
  'Syncing…': 'در حال همگام‌سازی…',
  'Editable User Texts': 'متن‌های قابل ویرایش کاربر',
  'Select an item to edit and preview it': 'یک مورد را برای ویرایش و پیش‌نمایش انتخاب کنید',
  'Bot texts': 'متن‌های ربات',
  'No matching text found': 'متن مطابقی پیدا نشد',
  'Try changing the search term or filters.': 'عبارت جست‌وجو یا فیلترها را تغییر دهید.',
  'Default': 'پیش‌فرض',
  'Select a text': 'یک متن انتخاب کنید',
  'The editor and live preview will appear here.': 'ویرایشگر و پیش‌نمایش زنده اینجا نمایش داده می‌شوند.',
  'Edit Button Text': 'ویرایش متن دکمه',
  'Edit Bot Message': 'ویرایش پیام ربات',
  'Project Default': 'پیش‌فرض پروژه',
  'Live Preview': 'پیش‌نمایش زنده',
  'This text is empty…': 'این متن خالی است…',
  'Button label': 'متن دکمه',
  'Dynamic Placeholders': 'متغیرهای پویا',
  'Keep these tokens so runtime values continue to work.': 'این متغیرها را حفظ کنید تا مقادیر پویا درست کار کنند.',
  'Editable Text': 'متن قابل ویرایش',
  'Maximum 64 characters for a Telegram button': 'حداکثر ۶۴ کاراکتر برای دکمه تلگرام',
  'Maximum 4096 characters for a Telegram message': 'حداکثر ۴۰۹۶ کاراکتر برای پیام تلگرام',
  'Show this button in the user menu': 'نمایش این دکمه در منوی کاربر',
  'Turn this off to hide the button from users.': 'برای مخفی کردن دکمه از کاربران، این گزینه را خاموش کنید.',
  'View Project Default': 'مشاهده متن پیش‌فرض پروژه',
  'Technical Details': 'جزئیات فنی',
  'Symbol': 'Symbol',
  'Save Changes': 'ذخیره تغییرات',
  'Reset to Default': 'بازگشت به پیش‌فرض',
  'Telegram button text cannot exceed 64 characters.': 'متن دکمه تلگرام نمی‌تواند بیشتر از ۶۴ کاراکتر باشد.',
  'Telegram message text cannot exceed 4096 characters.': 'متن پیام تلگرام نمی‌تواند بیشتر از ۴۰۹۶ کاراکتر باشد.',
  'Text saved successfully.': 'متن با موفقیت ذخیره شد.',
  'Please sign in to the panel again.': 'لطفاً دوباره وارد پنل شوید.',
  'Reset this text to the project default?': 'این متن به مقدار پیش‌فرض پروژه برگردد؟',
  'Text reset to the default value.': 'متن به مقدار پیش‌فرض بازگردانده شد.',
  'Reset all customized messages and buttons to their defaults?': 'همه پیام‌ها و دکمه‌های سفارشی به حالت پیش‌فرض برگردند؟',
  'All Custom texts were reset to their defaults.': 'همه متن‌های سفارشی به حالت پیش‌فرض برگشتند.',

  'Main Menu & Buttons': 'منوی اصلی و دکمه‌ها',
  'Start & Home': 'شروع و صفحه اصلی',
  'Purchase & Payment': 'خرید و پرداخت',
  'My Configs': 'کانفیگ‌های من',
  'Account & Wallet': 'حساب و کیف پول',
  'Support & Tickets': 'پشتیبانی و تیکت',
  'Private Messages': 'پیام‌های خصوصی',
  'Service Delivery': 'تحویل سرویس',
  'Profile & Connection Guide': 'پروفایل و راهنمای اتصال',
  'Service Renewal': 'تمدید سرویس',
  'General User Messages': 'پیام‌های عمومی کاربر',
  'Service Alerts': 'هشدارهای سرویس',
  'Expiration & Removal': 'انقضا و حذف سرویس',
  'Referral & Commission': 'دعوت و پورسانت',
  'User Interaction': 'تعامل کاربر',
  'Other User Messages': 'سایر پیام‌های کاربر',
  'Payment, Receipt & Approval': 'پرداخت، رسید و تأیید خرید',
  'Service Creation & Delivery': 'ساخت و تحویل سرویس',
  'Config Information': 'اطلاعات کانفیگ',
  'Service & Plan Selection': 'انتخاب سرویس و پلن',
  'Purchase Flow': 'فرآیند خرید',
  'Device & HWID Management': 'مدیریت دستگاه و HWID',
  'Config Removal': 'حذف کانفیگ',
  'Config Management': 'مدیریت کانفیگ',
  'View Configs': 'مشاهده کانفیگ‌ها',
  'Wallet & Payment Receipt': 'کیف پول و رسید پرداخت',
  'User Account': 'حساب کاربری',
  'Create & Track Tickets': 'ثبت و پیگیری تیکت',
  'Reseller Receipt & Balance': 'رسید و شارژ نمایندگی',
  'Reseller User Management': 'مدیریت کاربر نمایندگی',
  'Reseller Panel': 'پنل نمایندگی',
  'Create Test Account': 'ساخت اکانت تست',
  'Private Chat with Admin': 'گفتگوی خصوصی با مدیریت',
  'Service Card & Details': 'کارت و مشخصات سرویس',
  'OpenVPN Profile': 'پروفایل OpenVPN',
  'Renewal Result Message': 'پیام نتیجه تمدید',
  'Entry, Rules & Main Menu': 'ورود، قوانین و منوی اصلی',
  'User-visible Buttons': 'دکمه‌های قابل مشاهده کاربر',
  'Usage, Time & Disable Alerts': 'هشدار حجم، زمان و غیرفعال شدن',
  'Expiration & Removal Notice': 'اعلان انقضا و حذف',
  'Referral, Reward & Commission': 'دعوت، جایزه و پورسانت',
  'Input Errors & Guidance': 'خطا و راهنمای ورودی',

  'D Bot Panel': 'پنل D Bot',
  'Always by your side': 'همیشه همراه شما',
  'Sign in to Admin Panel': 'ورود به پنل مدیریت',
  'Professional bot management in a simple and secure workspace': 'مدیریت حرفه‌ای ربات در یک محیط ساده و امن',
  'Smart management': 'مدیریت هوشمند',
  'More peace of mind': 'آرامش بیشتر',
  'Incorrect username or password.': 'نام کاربری یا رمز عبور اشتباه است.',
  'Your session has expired. Please sign in again.': 'نشست شما منقضی شده است. لطفاً دوباره وارد شوید.',
  'Login credentials were updated. Sign in with the new credentials.': 'اطلاعات ورود بروزرسانی شد. با اطلاعات جدید وارد شوید.',
  'Hide password': 'مخفی کردن رمز',
  'Show password': 'نمایش رمز',
  'Signing in...': 'در حال ورود...',
  'Sign in': 'ورود',
  'Powered by Darvish Style': 'قدرت‌گرفته از Darvish Style',
  'Built to exceed expectations.': 'ساخته‌شده فراتر از انتظار.',
  'Select server': 'انتخاب سرور',
  'Select category': 'انتخاب دسته‌بندی',
  'No client group': 'بدون گروه کاربر',
  'Code': 'کد',
  'Expiry date': 'تاریخ انقضا',
  'Key': 'کلید',
  'Buy configuration': 'خرید کانفیگ',
  'My configurations': 'کانفیگ‌های من',
  'User account': 'حساب کاربری',
  'Test account': 'اکانت تست',
  'Tickets': 'تیکت‌ها',
  'Referral': 'دعوت دوستان',
  'Configuration lookup': 'استعلام کانفیگ',
  'Reseller request': 'درخواست نمایندگی',
  'Reseller menu': 'منوی نمایندگی',
  'Bot administration': 'مدیریت ربات',
  'Wallet top-up': 'شارژ کیف پول',
  'Profile name': 'نام پروفایل',
  'File name': 'نام فایل',
  'OVPN content': 'محتوای OVPN',
  'Backup channel': 'کانال بکاپ',
  'Backup time': 'زمان بکاپ',
  'Edit Reseller Plan': 'ویرایش پلن نمایندگی',
  'Backup Settings': 'تنظیمات بکاپ',
  'Optional bot/admin display name': 'نام نمایشی اختیاری در ربات/پنل',
  'Auto based on Circle color': 'خودکار بر اساس رنگ دایره',
  'Example: 4.99': 'مثال: 4.99',
  'Example: 1 device': 'مثال: ۱ دستگاه',
  '20 for percent or 50000 for Toman': 'برای درصد 20 یا برای مبلغ ثابت 50000 وارد کنید',
  'Leave empty to allow all servers': 'برای مجاز بودن همه سرورها خالی بگذارید',
  'to': 'تا',
  'Activity:': 'فعالیت:',
  'Service:': 'سرویس:',
  'Top-up request:': 'درخواست شارژ:',
  'Volume:': 'حجم:',
  'Previous service/quota:': 'سرویس/سهمیه قبلی:',
  'Old used:': 'مصرف قبلی:',
  'Returned from old cycle:': 'بازگشتی از دوره قبلی:',
  'Added to reseller quota:': 'افزوده‌شده به سهمیه نماینده:',
  'Deducted from reseller quota:': 'کسرشده از سهمیه نماینده:',
  'Quota before:': 'سهمیه قبل:',
  'Remaining after operation:': 'باقی‌مانده بعد از عملیات:',
  'Net quota change:': 'تغییر خالص سهمیه:',
  'Service total before:': 'حجم کل سرویس قبل:',
  'Service total after:': 'حجم کل سرویس بعد:',
  'Duration:': 'مدت:',
  'Expires:': 'انقضا:',
  'Server:': 'سرور:',
  'Source:': 'منبع:',
  'Legacy recharge: exact quota before/after was not stored in the old version.': 'شارژ قدیمی: مقدار دقیق سهمیه قبل/بعد در نسخه قدیمی ذخیره نشده است.',
  'dbot credentials': 'اطلاعات ورود D Bot',
  'Saving order...': 'در حال ذخیره ترتیب...',
  'Automatic (all active)': 'خودکار (همه فعال‌ها)',

};

const FA_EN = Object.fromEntries(Object.entries(EN_FA).map(([en, fa]) => [fa, en]));

function preserveWhitespace(raw: string, replacement: string): string {
  const start = raw.match(/^\s*/)?.[0] || '';
  const end = raw.match(/\s*$/)?.[0] || '';
  return `${start}${replacement}${end}`;
}

function translateDynamic(trimmed: string, lang: UiLanguage): string | null {
  const enToFa: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/^(\d[\d,]*) plans$/, m => `${m[1]} پلن`],
    [/^(\d[\d,]*) codes$/, m => `${m[1]} کد`],
    [/^(\d[\d,]*) resellers$/, m => `${m[1]} نماینده`],
    [/^(\d[\d,]*) operations$/, m => `${m[1]} عملیات`],
    [/^(\d[\d,]*) matching items$/, m => `${m[1]} مورد مطابق`],
    [/^(\d[\d,]*) server$/, m => `${m[1]} سرور`],
    [/^(\d[\d,]*) servers$/, m => `${m[1]} سرور`],
    [/^(\d[\d,]*) days$/, m => `${m[1]} روز`],
    [/^(\d[\d,]*) max$/, m => `حداکثر ${m[1]}`],
    [/^Show (\d[\d,]*) more$/, m => `نمایش ${m[1]} مورد بیشتر`],
    [/^Page (\d+) of (\d+)$/, m => `صفحه ${m[1]} از ${m[2]}`],
    [/^Remove test account usage for Telegram ID (\d+)\? This user will be able to receive a test account again\.$/, m => `سابقه اکانت تست برای شناسه تلگرام ${m[1]} حذف شود؟ این کاربر دوباره می‌تواند اکانت تست دریافت کند.`],
  ];
  const faToEn: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/^(\d[\d,]*) پلن$/, m => `${m[1]} plans`],
    [/^(\d[\d,]*) کد$/, m => `${m[1]} codes`],
    [/^(\d[\d,]*) نماینده$/, m => `${m[1]} resellers`],
    [/^(\d[\d,]*) عملیات$/, m => `${m[1]} operations`],
    [/^(\d[\d,]*) مورد مطابق$/, m => `${m[1]} matching items`],
    [/^(\d[\d,]*) سرور$/, m => `${m[1]} servers`],
    [/^(\d[\d,]*) روز$/, m => `${m[1]} days`],
    [/^حداکثر (\d[\d,]*)$/, m => `${m[1]} max`],
    [/^نمایش (\d[\d,]*) مورد بیشتر$/, m => `Show ${m[1]} more`],
    [/^صفحه (\d+) از (\d+)$/, m => `Page ${m[1]} of ${m[2]}`],
    [/^سابقه اکانت تست برای شناسه تلگرام (\d+) حذف شود\؟ این کاربر دوباره می‌تواند اکانت تست دریافت کند\.$/, m => `Remove test account usage for Telegram ID ${m[1]}? This user will be able to receive a test account again.`],
  ];
  const rules = lang === 'fa' ? enToFa : faToEn;
  for (const [regex, translate] of rules) {
    const match = trimmed.match(regex);
    if (match) return translate(match);
  }
  return null;
}

export function translateUiText(raw: string, lang: UiLanguage): string {
  const trimmed = raw.trim();
  if (!trimmed) return raw;
  const map = lang === 'fa' ? EN_FA : FA_EN;
  const direct = map[trimmed];
  if (direct) return preserveWhitespace(raw, direct);
  const dynamic = translateDynamic(trimmed, lang);
  return dynamic ? preserveWhitespace(raw, dynamic) : raw;
}

function isExcluded(node: Node): boolean {
  const el = node instanceof Element ? node : node.parentElement;
  if (!el) return false;
  if (el.closest('[data-no-i18n="true"]')) return true;
  const tag = el.tagName;
  return ['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(tag);
}

function translateElement(root: ParentNode, lang: UiLanguage) {
  if (root instanceof Element && root.closest('[data-no-i18n="true"]')) return;
  const doc = root instanceof Document ? root : root.ownerDocument;
  if (!doc) return;
  // Reject excluded subtrees at the walker level so large editors / user
  // content are never traversed node-by-node by the translation engine.
  const walker = doc.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (node instanceof Element && node.hasAttribute('data-no-i18n')) return NodeFilter.FILTER_REJECT;
        if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;
        return NodeFilter.FILTER_SKIP;
      },
    },
  );
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    nodes.push(current as Text);
    current = walker.nextNode();
  }
  for (const node of nodes) {
    const next = translateUiText(node.nodeValue || '', lang);
    if (next !== node.nodeValue) node.nodeValue = next;
  }

  const elementRoot = root instanceof Element ? root : (root instanceof Document ? root.documentElement : null);
  if (!elementRoot) return;
  const attributeElements = Array.from(elementRoot.querySelectorAll<HTMLElement>('[placeholder], [title], [aria-label]'));
  if (elementRoot.matches('[placeholder], [title], [aria-label]')) attributeElements.unshift(elementRoot as HTMLElement);
  for (const el of attributeElements) {
    if (el.closest('[data-no-i18n="true"]')) continue;
    for (const attr of ['placeholder', 'title', 'aria-label'] as const) {
      const raw = el.getAttribute(attr);
      if (!raw) continue;
      const next = translateUiText(raw, lang);
      if (next !== raw) el.setAttribute(attr, next);
    }
  }
}

type LanguageContextValue = {
  language: UiLanguage;
  setLanguage: (lang: UiLanguage) => void;
  toggleLanguage: () => void;
  t: (text: string) => string;
};

const LanguageContext = createContext<LanguageContextValue>({
  language: 'en',
  setLanguage: () => {},
  toggleLanguage: () => {},
  t: (text) => text,
});

export function UiLanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<UiLanguage>('en');

  const setLanguage = useCallback((lang: UiLanguage) => {
    setLanguageState(lang);
    if (typeof window !== 'undefined') localStorage.setItem(STORAGE_KEY, lang);
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'fa' || stored === 'en') setLanguageState(stored);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = language === 'fa' ? 'fa' : 'en';
    root.dir = language === 'fa' ? 'rtl' : 'ltr';
    document.body.dataset.uiLanguage = language;

    let translating = false;
    const translateNow = (target: ParentNode = document) => {
      if (translating) return;
      translating = true;
      try { translateElement(target, language); } finally { translating = false; }
    };

    translateNow(document);

    // Batch DOM translation work into a single animation frame. Large dynamic
    // screens such as Custom can add dozens of nodes in one React commit;
    // translating every mutation synchronously causes repeated subtree walks.
    const pendingNodes = new Set<Node>();
    let frameId = 0;

    const flushTranslations = () => {
      frameId = 0;
      if (translating || pendingNodes.size === 0) return;
      translating = true;
      try {
        const nodes = Array.from(pendingNodes);
        pendingNodes.clear();
        for (const node of nodes) {
          if (isExcluded(node)) continue;
          if (node instanceof Element) {
            translateElement(node, language);
          } else if (node.nodeType === Node.TEXT_NODE) {
            const textNode = node as Text;
            const next = translateUiText(textNode.nodeValue || '', language);
            if (next !== textNode.nodeValue) textNode.nodeValue = next;
          }
        }
      } finally {
        translating = false;
      }
    };

    const scheduleTranslation = (node: Node) => {
      if (isExcluded(node)) return;
      pendingNodes.add(node);
      if (!frameId) frameId = window.requestAnimationFrame(flushTranslations);
    };

    const observer = new MutationObserver((mutations) => {
      if (translating) return;
      for (const mutation of mutations) {
        if (mutation.type === 'characterData') scheduleTranslation(mutation.target);
        if (mutation.type === 'childList') mutation.addedNodes.forEach(scheduleTranslation);
        if (mutation.type === 'attributes') scheduleTranslation(mutation.target);
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });

    const originalConfirm = window.confirm.bind(window);
    const originalPrompt = window.prompt.bind(window);
    window.confirm = ((message?: string) => originalConfirm(translateUiText(String(message ?? ''), language))) as typeof window.confirm;
    window.prompt = ((message?: string, defaultValue?: string) => originalPrompt(translateUiText(String(message ?? ''), language), defaultValue)) as typeof window.prompt;

    return () => {
      observer.disconnect();
      if (frameId) window.cancelAnimationFrame(frameId);
      pendingNodes.clear();
      window.confirm = originalConfirm;
      window.prompt = originalPrompt;
    };
  }, [language]);

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage,
    toggleLanguage: () => setLanguage(language === 'en' ? 'fa' : 'en'),
    t: (text: string) => translateUiText(text, language),
  }), [language, setLanguage]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useUiLanguage() {
  return useContext(LanguageContext);
}

export function LanguageSwitch({ compact = false, className = '' }: { compact?: boolean; className?: string }) {
  const { language, setLanguage } = useUiLanguage();
  return (
    <div className={`language-switch ${compact ? 'compact' : ''} ${className}`.trim()} role="group" aria-label="Language">
      <button type="button" className={language === 'en' ? 'active' : ''} onClick={() => setLanguage('en')} aria-pressed={language === 'en'} title="English">EN</button>
      <button type="button" className={language === 'fa' ? 'active' : ''} onClick={() => setLanguage('fa')} aria-pressed={language === 'fa'} title="Persian">FA</button>
    </div>
  );
}
