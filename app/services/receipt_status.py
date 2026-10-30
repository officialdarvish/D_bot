"""Receipt inbox presentation; never changes payment state or replays provisioning."""
ORDER_RECEIPT_OPEN_STATUSES = ('waiting_receipt', 'failed', 'processing')
PANEL_RECEIPT_OPEN_STATUSES = ('pending', 'processing', 'review_required', 'delivery_pending')


def receipt_status_label(status: str) -> str:
    return {
        'waiting_receipt': '🧾 در انتظار بررسی', 'pending': '🧾 در انتظار بررسی',
        'failed': '⚠️ خطای ساخت / تمدید', 'processing': '⏳ در حال پردازش',
        'review_required': '⚠️ نیازمند بررسی پنل', 'delivery_pending': '📨 در انتظار ارسال مشخصات',
    }.get(status, 'نیازمند بررسی')


def receipt_failure_reason(exc: Exception) -> str:
    """Persist a fixed safe explanation, never URLs, tokens or raw provider errors."""
    text = str(exc).lower()
    if 'inbound' in text or 'اینباند' in text:
        return 'اینباندهای معتبر پلن یا اتصال آن‌ها روی پنل را بررسی و اصلاح کنید؛ سپس تلاش مجدد را بزنید.'
    if 'group' in text or 'گروه' in text:
        return 'گروه‌های انتخاب‌شده در تنظیمات پلن و پنل را بررسی و اصلاح کنید؛ سپس دوباره اقدام کنید.'
    if type(exc).__name__ == 'PasarGuardCreateUnconfirmed':
        return 'نتیجه ساخت در پاسارگارد نامشخص است؛ قبل از تلاش مجدد وجود نام کاربری را در پنل بررسی کنید.'
    if 'timeout' in type(exc).__name__.lower() or 'timeout' in text or 'timed out' in text:
        return 'پاسخ پنل در زمان مجاز نرسید؛ قبل از تکرار، وضعیت سرویس را در پنل بررسی کنید.'
    return 'ساخت یا تمدید سرویس کامل نشد. تنظیمات پلن، اتصال پنل و لاگ خطا را بررسی کنید.'
