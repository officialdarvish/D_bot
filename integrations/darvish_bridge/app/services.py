"""Core domain services. All financial mutations occur in the caller's DB transaction."""
import json
import secrets
from datetime import datetime, timezone
from sqlalchemy import select, func
from fastapi import HTTPException
from .config import settings, CURRENCY_SCALE
from .models import (Merchant, MerchantBot, ReceiveAccount, Order, Receipt, BuyerSession,
                     LedgerRow, Settlement, Refund, Dispute, AuditEvent, Outbox, uid, now)
from .security import issue_api_key, digest_key, permitted_callback_url


def err(status, message):
    raise HTTPException(status_code=status, detail=message)


def audit(db, actor, action, target_type, target_id, details=None):
    db.add(AuditEvent(actor=str(actor), action=action, target_type=target_type,
                      target_id=target_id, detail_json=json.dumps(details or {}, ensure_ascii=False)))


def queue(db, kind, target, payload):
    db.add(Outbox(kind=kind, target=str(target), payload_json=json.dumps(payload, ensure_ascii=False)))


def notify(db, tg_id, text):
    queue(db, "telegram_message", tg_id, {"text": text})


def journal(db, currency, reference_type, reference_id, postings):
    """postings = [{merchant_id, account, amount_minor}, ...], each journal must balance exactly."""
    if not postings or sum(row["amount_minor"] for row in postings) != 0:
        raise AssertionError("Unbalanced journal")
    j = uid()
    for row in postings:
        db.add(LedgerRow(journal_id=j, merchant_id=row.get("merchant_id"), currency=currency,
                         account=row["account"], amount_minor=row["amount_minor"],
                         reference_type=reference_type, reference_id=reference_id))
    db.flush()
    return j


def balance(db, merchant_id, currency, account="seller_available"):
    return int(db.scalar(select(func.coalesce(func.sum(LedgerRow.amount_minor), 0)).where(
        LedgerRow.merchant_id == merchant_id, LedgerRow.currency == currency,
        LedgerRow.account == account)) or 0)


def balances(db, merchant_id):
    rows = db.execute(select(LedgerRow.currency, LedgerRow.account, func.sum(LedgerRow.amount_minor))
        .where(LedgerRow.merchant_id == merchant_id)
        .group_by(LedgerRow.currency, LedgerRow.account)).all()
    result = {}
    for currency, account, amount in rows:
        result.setdefault(currency, {})[account] = amount
    return result


def owner_merchant(db, merchant_id, tg_id, require_approved=True):
    merchant = db.get(Merchant, merchant_id)
    if not merchant or merchant.owner_tg_id != tg_id:
        err(404, "فروشنده پیدا نشد یا دسترسی ندارید")
    if require_approved and merchant.status != "approved":
        err(403, "حساب فروشنده هنوز تأیید نشده است")
    return merchant


def create_merchant(db, tg_id, name):
    m = Merchant(owner_tg_id=tg_id, name=name)
    db.add(m)
    db.flush()
    audit(db, f"tg:{tg_id}", "merchant.created", "merchant", m.id)
    for admin in settings.admin_ids:
        notify(db, admin, f"🆕 درخواست ثبت فروشنده\nنام: {name}\nشناسه: {m.id}\nاز مینی‌اپ تأیید کنید.")
    return m


def review_merchant(db, merchant_id, admin_id, approved, fee_bps):
    m = db.get(Merchant, merchant_id, with_for_update=True)
    if not m:
        err(404, "فروشنده پیدا نشد")
    if m.status != "pending":
        err(409, "این درخواست قبلاً بررسی شده است")
    m.status = "approved" if approved else "rejected"
    m.fee_bps = fee_bps
    audit(db, f"admin:{admin_id}", "merchant.reviewed", "merchant", m.id, {"approved": approved})
    notify(db, m.owner_tg_id, "✅ حساب فروشنده تأیید شد." if approved else "❌ درخواست فروشندگی رد شد.")
    return m


def update_merchant_settings(db, merchant_id, admin_id, status, fee_bps):
    m = db.get(Merchant, merchant_id, with_for_update=True)
    if not m:
        err(404, "فروشنده پیدا نشد")
    if m.status not in ("approved", "suspended"):
        err(409, "ابتدا درخواست فروشندگی را تعیین تکلیف کنید")
    before = {"status": m.status, "fee_bps": m.fee_bps}
    m.status, m.fee_bps = status, fee_bps
    audit(db, f"admin:{admin_id}", "merchant.settings_updated", "merchant", m.id,
          {"before": before, "after": {"status": status, "fee_bps": fee_bps}})
    notify(db, m.owner_tg_id, f"⚙️ تنظیمات فروشندگی شما به‌روزرسانی شد. وضعیت: {status}، کارمزد: {fee_bps/100:.2f}٪")
    return m


def create_bot(db, m, label, webhook_url):
    url = permitted_callback_url(webhook_url)
    key, webhook_secret = issue_api_key(), secrets.token_urlsafe(32)
    b = MerchantBot(merchant_id=m.id, label=label, webhook_url=url, key_digest=digest_key(key), webhook_secret=webhook_secret)
    db.add(b)
    db.flush()
    audit(db, f"tg:{m.owner_tg_id}", "merchant_bot.created", "merchant_bot", b.id)
    return b, key, webhook_secret


def revoke_bot(db, m, bot_id):
    b = db.get(MerchantBot, bot_id)
    if not b or b.merchant_id != m.id:
        err(404, "ربات پیدا نشد")
    b.active = False
    audit(db, f"tg:{m.owner_tg_id}", "merchant_bot.revoked", "merchant_bot", b.id)
    return b


def create_order(db, bot, data):
    merchant = db.get(Merchant, bot.merchant_id)
    if not bot.active or merchant.status != "approved":
        err(403, "اتصال فروشنده فعال نیست")
    # Receipt-only in-bot checkout for digital services violates Telegram payment rules.
    if data.product_kind == "digital" and not settings.allow_digital_manual_receipts:
        err(422, "روش رسید دستی برای فروش محصولات دیجیتال داخل تلگرام فعال نیست")
    old = db.scalar(select(Order).where(Order.merchant_bot_id == bot.id, Order.external_order_id == data.external_order_id))
    if old:
        if (old.amount_minor, old.currency, old.buyer_tg_id, old.product_title, old.product_kind, old.delivery_message) != (
                data.amount_minor, data.currency, data.buyer_tg_id, data.product_title, data.product_kind, data.delivery_message):
            err(409, "شناسه سفارش تکراری با اطلاعات متفاوت")
        return old, False
    accounts = db.scalars(select(ReceiveAccount).where(ReceiveAccount.currency == data.currency,
                                                      ReceiveAccount.active.is_(True))).all()
    if not accounts:
        err(409, "برای این ارز حساب دریافت فعالی ثبت نشده است")
    account = secrets.choice(accounts)
    order = Order(merchant_id=merchant.id, merchant_bot_id=bot.id,
                  external_order_id=data.external_order_id, buyer_tg_id=data.buyer_tg_id,
                  product_title=data.product_title, product_kind=data.product_kind, delivery_message=data.delivery_message,
                  amount_minor=data.amount_minor, currency=data.currency, receive_account_id=account.id)
    db.add(order)
    db.flush()
    audit(db, f"bot:{bot.id}", "order.created", "order", order.id)
    notify(db, data.buyer_tg_id, f"🛒 سفارش ثبت شد\n{data.product_title}\nشناسه: {order.id}\nبرای ارسال رسید از دستور زیر استفاده کنید:\n/order {order.id}")
    return order, True


def submit_receipt(db, order_id, telegram_id, file_id, unique_id):
    order = db.get(Order, order_id, with_for_update=True)
    if not order or order.buyer_tg_id != telegram_id:
        err(404, "سفارش متعلق به این کاربر نیست")
    if order.status != "awaiting_receipt":
        err(409, "برای این سفارش امکان ارسال رسید وجود ندارد")
    if db.scalar(select(Receipt).where(Receipt.order_id == order.id)):
        err(409, "رسید قبلاً ارسال شده است")
    receipt = Receipt(order_id=order_id, telegram_file_id=file_id,
                      telegram_file_unique_id=unique_id)
    db.add(receipt)
    order.status = "receipt_submitted"
    audit(db, f"tg:{telegram_id}", "receipt.submitted", "order", order.id)
    for admin_id in settings.admin_ids:
        queue(db, "telegram_photo", admin_id, {"file_id": file_id,
              "caption": f"📥 رسید جدید\nسفارش: {order.id}\nمبلغ: {order.amount_minor} کوچک‌ترین واحد {order.currency}\n⚠️ فقط پس از تطبیق واریز واقعی تأیید کنید.",
              "buttons": [[{"text":"✅ دریافت واقعی را تأیید می‌کنم", "callback_data": f"ra:{order.id}"},
                           {"text":"❌ رد رسید", "callback_data": f"rr:{order.id}"}]]})
    return receipt


def _webhook(db, order, event, extra=None):
    bot = db.get(MerchantBot, order.merchant_bot_id)
    if bot and bot.webhook_url:
        queue(db, "merchant_webhook", bot.id, {"event": event, "order_id": order.id,
             "external_order_id": order.external_order_id, "merchant_id": order.merchant_id,
             "amount_minor": order.amount_minor, "currency": order.currency,
             **(extra or {})})


def review_order(db, order_id, admin_id, approve, verified, note=""):
    order = db.get(Order, order_id, with_for_update=True)
    if not order:
        err(404, "سفارش پیدا نشد")
    if order.status != "receipt_submitted":
        err(409, "رسید در وضعیت قابل بررسی نیست")
    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if not receipt:
        err(409, "رسیدی موجود نیست")
    if approve and not verified:
        err(422, "پیش از تأیید، دریافت واقعی وجه را مستقل از تصویر رسید بررسی کنید")
    receipt.reviewer_tg_id = admin_id
    receipt.reviewed_at = now()
    receipt.review_note = note
    if approve:
        m = db.get(Merchant, order.merchant_id)
        fee = order.amount_minor * m.fee_bps // 10000
        order.fee_minor = fee  # freeze commission at confirmation for later refunds
        net = order.amount_minor - fee
        journal(db, order.currency, "order", order.id, [
            {"merchant_id": None, "account": "verified_inflow", "amount_minor": -order.amount_minor},
            {"merchant_id": m.id, "account": "seller_available", "amount_minor": net},
            {"merchant_id": None, "account": "platform_fee", "amount_minor": fee},
        ])
        if order.delivery_message:
            order.status = "fulfilled"
            notify(db, order.buyer_tg_id, f"✅ پرداخت سفارش {order.id} تأیید شد.\n📦 اطلاعات تحویل:\n{order.delivery_message}")
        else:
            order.status = "fulfillment_pending"
            notify(db, order.buyer_tg_id, f"✅ پرداخت سفارش {order.id} تأیید شد؛ در انتظار تحویل فروشنده.")
        _webhook(db, order, "order.approved")
        notify(db, m.owner_tg_id, f"✅ پرداخت سفارش {order.id} تأیید شد. سهم شما {net} کوچک‌ترین واحد {order.currency} ثبت شد.")
    else:
        order.status = "rejected"
        _webhook(db, order, "order.rejected", {"reason": note or "رسید تأیید نشد"})
        notify(db, order.buyer_tg_id, f"❌ رسید سفارش {order.id} رد شد. {note}")
    audit(db, f"admin:{admin_id}", "order.approved" if approve else "order.rejected", "order", order.id)
    return order


def refund_order(db, order_id, admin_id, verified, payout_reference, reason):
    if not verified:
        err(422, "بازگشت واقعی وجه باید مستقل از وضعیت سفارش تأیید شده باشد")
    order = db.get(Order, order_id, with_for_update=True)
    if not order:
        err(404, "سفارش پیدا نشد")
    if order.status not in ("fulfillment_pending", "fulfilled", "delivery_failed"):
        err(409, "این سفارش واجد شرایط ثبت بازگشت وجه نیست")
    if db.scalar(select(Refund).where(Refund.order_id == order.id)):
        err(409, "وجه این سفارش قبلاً برگشت خورده است")
    m = db.get(Merchant, order.merchant_id, with_for_update=True)
    fee = order.fee_minor
    if fee is None:
        err(409, "کارمزد تأییدشده سفارش مشخص نیست")
    net = order.amount_minor - fee
    if balance(db, m.id, order.currency) < net:
        err(409, "موجودی آزاد فروشنده برای برگشت کافی نیست؛ نیازمند تسویه اختلاف به‌صورت جداگانه")
    r = Refund(order_id=order.id, payout_reference=payout_reference, reason=reason, admin_tg_id=admin_id)
    db.add(r)
    db.flush()
    journal(db, order.currency, "order_refund", r.id, [
        {"merchant_id": m.id, "account": "seller_available", "amount_minor": -net},
        {"merchant_id": None, "account": "platform_fee", "amount_minor": -fee},
        {"merchant_id": None, "account": "refund_outflow", "amount_minor": order.amount_minor},
    ])
    order.status = "refunded"
    audit(db, f"admin:{admin_id}", "order.refunded", "order", order.id,
          {"reference": payout_reference, "reason": reason})
    notify(db, order.buyer_tg_id, f"↩️ بازگشت وجه سفارش {order.id} ثبت شد. شناسه انتقال: {payout_reference}")
    notify(db, m.owner_tg_id, f"↩️ بازگشت وجه سفارش {order.id} ثبت شد و موجودی مربوط اصلاح گردید.")
    _webhook(db, order, "order.refunded", {"reference": payout_reference})
    return r


def resend_delivery_webhook(db, order_id, admin_id):
    order = db.get(Order, order_id, with_for_update=True)
    if not order:
        err(404, "سفارش پیدا نشد")
    if order.status not in ("fulfillment_pending", "delivery_failed"):
        err(409, "سفارش در انتظار تحویل نیست")
    bot = db.get(MerchantBot, order.merchant_bot_id)
    if not bot or not bot.active or not bot.webhook_url:
        err(409, "وب‌هوک فعال برای این سفارش موجود نیست")
    _webhook(db, order, "order.approved", {"retry": True})
    audit(db, f"admin:{admin_id}", "order.webhook_resent", "order", order.id)
    return order


def delivered(db, order_id, bot, status, message):
    order = db.get(Order, order_id, with_for_update=True)
    if not order or order.merchant_bot_id != bot.id:
        err(404, "سفارش پیدا نشد")
    target = "fulfilled" if status == "fulfilled" else "delivery_failed"
    if order.status == target:
        return order
    if order.status not in ("fulfillment_pending", "delivery_failed"):
        err(409, "وضعیت سفارش برای اعلام تحویل نامعتبر است")
    order.status = target
    audit(db, f"bot:{bot.id}", "order.delivery", "order", order.id, {"status": target, "message": message})
    notify(db, order.buyer_tg_id, ("📦 سفارش شما تحویل داده شد." if target == "fulfilled" else "⚠️ تحویل سفارش با مشکل مواجه شد؛ پشتیبانی پیگیری می‌کند.") + f"\nشناسه: {order.id}")
    return order


def create_settlement(db, m, amount_minor, currency, destination):
    # Merchant row lock serializes withdrawals for that merchant on PostgreSQL.
    m = db.get(Merchant, m.id, with_for_update=True)
    if m.status != "approved":
        err(403, "حساب فروشنده فعال نیست")
    if balance(db, m.id, currency) < amount_minor:
        err(409, "موجودی آزاد کافی نیست")
    seconds = settings.settlement_cycle_hours * 3600
    if seconds <= 0:
        raise RuntimeError("SETTLEMENT_CYCLE_HOURS must be positive")
    current = now()
    due = datetime.fromtimestamp((int(current.timestamp()) // seconds + 1) * seconds, timezone.utc)
    s = Settlement(merchant_id=m.id, currency=currency, amount_minor=amount_minor, destination=destination,
                   cycle_due_at=due)
    db.add(s)
    db.flush()
    journal(db, currency, "settlement_reserve", s.id, [
        {"merchant_id": m.id, "account": "seller_available", "amount_minor": -amount_minor},
        {"merchant_id": m.id, "account": "seller_reserved", "amount_minor": amount_minor}])
    audit(db, f"tg:{m.owner_tg_id}", "settlement.requested", "settlement", s.id)
    for admin in settings.admin_ids:
        notify(db, admin, f"💼 درخواست تسویه\nفروشنده: {m.name}\nمبلغ: {amount_minor} واحد خرد {currency}\nشناسه: {s.id}")
    return s


def review_settlement(db, settlement_id, admin_id, action, payout_reference=None, note=""):
    s = db.get(Settlement, settlement_id, with_for_update=True)
    if not s:
        err(404, "درخواست پیدا نشد")
    if action == "approve":
        if s.status != "requested":
            err(409, "درخواست قبلاً بررسی شده است")
        s.status = "approved"
    elif action == "reject":
        if s.status not in ("requested", "approved"):
            err(409, "درخواست قابل رد نیست")
        m = db.get(Merchant, s.merchant_id, with_for_update=True)
        journal(db, s.currency, "settlement_release", s.id, [
            {"merchant_id": m.id, "account": "seller_reserved", "amount_minor": -s.amount_minor},
            {"merchant_id": m.id, "account": "seller_available", "amount_minor": s.amount_minor}])
        s.status = "rejected"
    elif action == "paid":
        if s.status != "approved":
            err(409, "ابتدا درخواست را تأیید کنید")
        if not payout_reference or len(payout_reference.strip()) < 3:
            err(422, "شناسه انتقال واقعی الزامی است")
        journal(db, s.currency, "settlement_paid", s.id, [
            {"merchant_id": s.merchant_id, "account": "seller_reserved", "amount_minor": -s.amount_minor},
            {"merchant_id": None, "account": "settlement_outflow", "amount_minor": s.amount_minor}])
        s.status = "paid"
        s.payout_reference = payout_reference.strip()
    else:
        err(422, "عملیات ناشناخته")
    s.admin_note = note
    s.reviewed_at = now()
    audit(db, f"admin:{admin_id}", f"settlement.{action}", "settlement", s.id,
          {"payout_reference": payout_reference if action == "paid" else None})
    m = db.get(Merchant, s.merchant_id)
    notify(db, m.owner_tg_id, f"🔔 وضعیت تسویه {s.id}: {s.status}")
    return s


def open_dispute(db, order, tg_id, reason):
    if order.buyer_tg_id != tg_id:
        err(403, "فقط خریدار می‌تواند اختلاف ثبت کند")
    d = Dispute(order_id=order.id, opened_by_tg_id=tg_id, reason=reason)
    db.add(d)
    db.flush()
    audit(db, f"tg:{tg_id}", "dispute.open", "dispute", d.id)
    for admin in settings.admin_ids:
        notify(db, admin, f"⚠️ اختلاف سفارش {order.id}\nشناسه: {d.id}\nشرح: {reason}")
    return d


def format_minor(amount_minor, currency):
    scale = CURRENCY_SCALE.get(currency, 0)
    if scale == 0:
        return str(amount_minor)
    negative = amount_minor < 0
    n = abs(amount_minor)
    q, r = divmod(n, 10 ** scale)
    decimals = str(r).zfill(scale).rstrip("0")
    return ("-" if negative else "") + f"{q:,}" + (("." + decimals) if decimals else "")
