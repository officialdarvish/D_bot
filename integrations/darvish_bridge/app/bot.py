"""Telegram long-polling bot + durable notification/webhook outbox worker.
No public webhook required; run one bot worker per bot token.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from fastapi import HTTPException

from .config import settings, CURRENCY_SCALE, validate_runtime_secrets
from .database import SessionLocal, init_db
from .models import (BuyerSession, Order, ReceiveAccount, Outbox, Merchant, Settlement,
                     MerchantBot)
from . import services as svc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("darvish.bot")
BASE = f"https://api.telegram.org/bot{settings.bot_token}"


async def telegram(client, method, payload=None):
    r = await client.post(f"{BASE}/{method}", json=payload or {}, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description', 'failed')}")
    return data.get("result")


async def send(client, chat_id, message, keyboard=None):
    payload = {"chat_id": chat_id, "text": message}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return await telegram(client, "sendMessage", payload)


def commit_action(fn):
    with SessionLocal() as db:
        result = fn(db)
        db.commit()
        return result


async def display_order(client, tg_id, order_id):
    def get(db):
        o = db.get(Order, order_id)
        if not o or o.buyer_tg_id != tg_id:
            svc.err(404, "سفارش متعلق به شما نیست")
        a = db.get(ReceiveAccount, o.receive_account_id)
        if o.status == "awaiting_receipt":
            sess = db.get(BuyerSession, tg_id)
            if sess:
                sess.order_id = o.id
            else:
                db.add(BuyerSession(telegram_id=tg_id, order_id=o.id))
        return o, a
    o, account = commit_action(get)
    await send(client, tg_id,
               f"🧾 سفارش: {o.product_title}\nشناسه: {o.id}\n"
               f"مبلغ: {svc.format_minor(o.amount_minor, o.currency)} {o.currency}\n"
               f"وضعیت: {o.status}\n\n"
               + (f"مقصد مجاز: {account.label}\n{account.instructions}\n\n"
                  "پس از انجام انتقال، عکس رسید را همین‌جا ارسال کنید. عکس به‌تنهایی اثبات واریز نیست."
                  if o.status == "awaiting_receipt" else "رسید این سفارش فعلاً قابل ثبت نیست."))


async def on_message(client, msg, payout_sessions):
    sender = msg.get("from", {})
    tg_id = sender.get("id")
    chat_id = msg.get("chat", {}).get("id")
    if not tg_id or not chat_id or msg.get("chat", {}).get("type") != "private":
        return
    if msg.get("photo"):
        images = msg["photo"]
        photo = images[-1]
        def add(db):
            sess = db.get(BuyerSession, tg_id)
            if not sess:
                svc.err(409, "ابتدا شناسه سفارش را با دستور /order مشخص کنید")
            return svc.submit_receipt(db, sess.order_id, tg_id, photo["file_id"], photo["file_unique_id"])
        try:
            receipt = commit_action(add)
            await send(client, chat_id, "✅ تصویر رسید ثبت شد و برای بررسی مدیر ارسال گردید. پس از بررسی نتیجه اعلام می‌شود.")
        except HTTPException as exc:
            await send(client, chat_id, f"⚠️ {exc.detail}")
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    parts = text.split()
    command = parts[0].split("@")[0].lower()
    try:
        if tg_id in payout_sessions and not text.startswith("/"):
            sid = payout_sessions.pop(tg_id)
            def approve_paid(db):
                return svc.review_settlement(db, sid, tg_id, "paid", text.strip())
            s = commit_action(approve_paid)
            await send(client, chat_id, f"✅ تسویه {s.id} با شناسه انتقال ثبت شد.")
            return
        if command in ("/start", "/help"):
            if len(parts) > 1 and parts[1].startswith("order_"):
                await display_order(client, tg_id, parts[1][6:])
            else:
                await send(client, chat_id,
                    "🌉 دارویش بریج | مدیریت سفارش و رسید\n\n"
                    "/order شناسه — مشاهده سفارش و ارسال عکس رسید\n"
                    "/register نام فروشگاه — درخواست فروشندگی\n"
                    "/merchants — مشاهده فروشگاه‌های شما\n"
                    "/wallet شناسه‌فروشنده — موجودی\n"
                    "/settle شناسه‌فروشنده مبلغ ارز مقصد — درخواست تسویه\n"
                    "/dispute شناسه‌سفارش شرح — ثبت اختلاف\n"
                    "/paysupport — راهنمای پیگیری\n\n"
                    f"مینی‌اپ: {settings.public_base_url}\n"
                    "⚠️ رسید فقط پس از بررسی دریافت واقعی تأیید می‌شود.",
                    keyboard=[[{"text":"📱 بازکردن پنل دارویش", "web_app":{"url":settings.public_base_url}}]]
                    if settings.public_base_url.startswith("https://") else None)
        elif command == "/order" and len(parts) == 2:
            await display_order(client, tg_id, parts[1])
        elif command == "/register" and len(parts) >= 2:
            name = text[len(parts[0]):].strip()
            m = commit_action(lambda db: svc.create_merchant(db, tg_id, name[:120]))
            await send(client, chat_id, f"✅ درخواست شما ثبت شد.\nشناسه فروشنده: {m.id}\nوضعیت: در انتظار بررسی")
        elif command == "/merchants":
            with SessionLocal() as db:
                merchants = db.scalars(select(Merchant).where(Merchant.owner_tg_id == tg_id)).all()
            msg_text = "\n".join(f"{m.name} | {m.status}\n{m.id}" for m in merchants) if merchants else "هنوز فروشنده‌ای ثبت نشده است."
            await send(client, chat_id, msg_text)
        elif command == "/wallet" and len(parts) == 2:
            with SessionLocal() as db:
                m = svc.owner_merchant(db, parts[1], tg_id)
                totals = svc.balances(db, m.id)
            lines = [f"{c}: آزاد {svc.format_minor(v.get('seller_available',0),c)} | رزرو {svc.format_minor(v.get('seller_reserved',0),c)}" for c,v in totals.items()]
            await send(client, chat_id, "💼 موجودی\n" + ("\n".join(lines) if lines else "موجودی ثبت نشده است"))
        elif command == "/settle" and len(parts) >= 5:
            merchant_id, str_amount, currency = parts[1], parts[2], parts[3].upper()
            destination = " ".join(parts[4:])
            scale = CURRENCY_SCALE.get(currency)
            if scale is None:
                svc.err(422, "ارز پشتیبانی نمی‌شود")
            decimal_amount = Decimal(str_amount)
            scaled = decimal_amount * (Decimal(10) ** scale)
            if scaled != scaled.to_integral_value() or scaled <= 0:
                svc.err(422, "مبلغ باید مثبت و دارای دقت مجاز باشد")
            amount_minor = int(scaled)
            def settle(db):
                m = svc.owner_merchant(db, merchant_id, tg_id)
                return svc.create_settlement(db, m, amount_minor, currency, destination)
            s = commit_action(settle)
            await send(client, chat_id, f"✅ درخواست تسویه ثبت شد.\nشناسه: {s.id}\nوضعیت: {s.status}")
        elif command == "/dispute" and len(parts) >= 3:
            order_id = parts[1]
            reason = " ".join(parts[2:])
            def dispute(db):
                o = db.get(Order, order_id)
                if not o:
                    svc.err(404, "سفارش پیدا نشد")
                return svc.open_dispute(db, o, tg_id, reason)
            d = commit_action(dispute)
            await send(client, chat_id, f"✅ اختلاف ثبت شد: {d.id}")
        elif command == "/paysupport":
            await send(client, chat_id, "برای پیگیری پرداخت یا اختلاف از /dispute شناسه‌سفارش شرح استفاده کنید. برای رسید معلق، شناسه سفارش را با /order ارسال کنید.")
        elif command == "/pending" and tg_id in settings.admin_ids:
            with SessionLocal() as db:
                rows = db.scalars(select(Order).where(Order.status == "receipt_submitted").limit(20)).all()
            await send(client, chat_id, "\n".join(f"{o.id} | {o.currency} {o.amount_minor}" for o in rows) or "رسید معلق وجود ندارد.")
        elif command == "/settlements" and tg_id in settings.admin_ids:
            with SessionLocal() as db:
                rows = db.scalars(select(Settlement).where(Settlement.status.in_(["requested", "approved"])).limit(15)).all()
            if not rows:
                await send(client, chat_id, "درخواست تسویه معلق وجود ندارد.")
            for s in rows:
                buttons = [[{"text":"✅ تأیید درخواست", "callback_data":f"sa:{s.id}"},
                            {"text":"❌ رد", "callback_data":f"sr:{s.id}"}],
                           [{"text":"🧾 ثبت انتقال انجام‌شده", "callback_data":f"sp:{s.id}"}]]
                await send(client, chat_id, f"تسویه: {s.id}\nمبلغ: {svc.format_minor(s.amount_minor,s.currency)} {s.currency}\nمقصد: {s.destination}\nوضعیت: {s.status}", buttons)
        elif command == "/paid" and tg_id in settings.admin_ids and len(parts) >= 3:
            sid = parts[1]
            ref = " ".join(parts[2:])
            s = commit_action(lambda db: svc.review_settlement(db, sid, tg_id, "paid", ref))
            await send(client, chat_id, f"✅ پرداخت تسویه {s.id} ثبت شد")
        else:
            await send(client, chat_id, "دستور نامعتبر است. برای راهنما /help را بفرستید.")
    except (HTTPException, InvalidOperation, ValueError) as exc:
        await send(client, chat_id, "⚠️ " + (exc.detail if isinstance(exc, HTTPException) else "ورودی نامعتبر است"))


async def on_callback(client, update, payout_sessions):
    query_id = update["id"]
    tg_id = update.get("from", {}).get("id")
    data = update.get("data", "")
    chat_id = update.get("message", {}).get("chat", {}).get("id")
    if tg_id not in settings.admin_ids:
        await telegram(client, "answerCallbackQuery", {"callback_query_id": query_id, "text": "دسترسی ندارید", "show_alert": True})
        return
    try:
        action, entity_id = data.split(":", 1)
        if action == "ra":
            o = commit_action(lambda db: svc.review_order(db, entity_id, tg_id, True, True, "مدیر دریافت واقعی را بررسی و تأیید کرد"))
            message = f"✅ پرداخت سفارش {o.id} ثبت شد؛ دستور تحویل برای فروشنده در صف است."
        elif action == "rr":
            o = commit_action(lambda db: svc.review_order(db, entity_id, tg_id, False, False, "مغایرت رسید / تأیید نشدن دریافت واقعی"))
            message = f"❌ رسید سفارش {o.id} رد شد."
        elif action in ("sa", "sr"):
            s = commit_action(lambda db: svc.review_settlement(db, entity_id, tg_id, "approve" if action == "sa" else "reject"))
            message = f"وضعیت درخواست {s.id}: {s.status}"
        elif action == "sp":
            payout_sessions[tg_id] = entity_id
            message = "شناسه واقعی انتقال انجام‌شده را در یک پیام جدا ارسال کنید. بدون انتقال واقعی تأیید نکنید."
        else:
            message = "دکمه ناشناخته است"
        await telegram(client, "answerCallbackQuery", {"callback_query_id": query_id, "text": "ثبت شد"})
        if chat_id:
            await send(client, chat_id, message)
    except (ValueError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else "داده نامعتبر"
        await telegram(client, "answerCallbackQuery", {"callback_query_id": query_id, "text": str(detail)[:180], "show_alert": True})


async def run_outbox(client):
    while True:
        try:
            with SessionLocal() as db:
                jobs = db.scalars(select(Outbox).where(Outbox.delivered.is_(False), Outbox.next_attempt_at <= datetime.now(timezone.utc))
                                  .order_by(Outbox.created_at).limit(15).with_for_update(skip_locked=True)).all()
                for j in jobs:
                    try:
                        payload = json.loads(j.payload_json)
                        if j.kind == "telegram_message":
                            await send(client, int(j.target), payload["text"])
                        elif j.kind == "telegram_photo":
                            content = {"chat_id": int(j.target), "photo": payload["file_id"], "caption":payload["caption"]}
                            if payload.get("buttons"):
                                content["reply_markup"] = {"inline_keyboard": payload["buttons"]}
                            await telegram(client, "sendPhoto", content)
                        elif j.kind == "merchant_webhook":
                            b = db.get(MerchantBot, j.target)
                            if not b or not b.active or not b.webhook_url:
                                raise RuntimeError("Merchant webhook inactive or missing")
                            body = json.dumps({**payload, "event_id": j.id}, ensure_ascii=False, separators=(",", ":"))
                            timestamp = str(int(time.time()))
                            sig = hmac.new(b.webhook_secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
                            res = await client.post(b.webhook_url, content=body.encode(),
                                headers={"Content-Type":"application/json", "X-Darvish-Timestamp": timestamp,
                                         "X-Darvish-Signature": sig, "X-Darvish-Event-ID": j.id}, timeout=10.0)
                            res.raise_for_status()
                        else:
                            raise RuntimeError("Unknown outbox kind")
                        j.delivered = True
                    except Exception as exc:
                        j.attempts += 1
                        j.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 2 ** min(j.attempts, 10)))
                        log.error("Outbox delivery failed kind=%s id=%s attempts=%s: %s", j.kind, j.id, j.attempts, type(exc).__name__)
                db.commit()
        except Exception:
            log.exception("Outbox worker error")
        await asyncio.sleep(3)


async def poll(client):
    offset = None
    payout_sessions = {}
    while True:
        try:
            payload = {"timeout": 15, "allowed_updates": ["message", "callback_query"]}
            if offset is not None:
                payload["offset"] = offset
            updates = await telegram(client, "getUpdates", payload)
            for item in updates:
                offset = item["update_id"] + 1
                try:
                    if "message" in item:
                        await on_message(client, item["message"], payout_sessions)
                    elif "callback_query" in item:
                        await on_callback(client, item["callback_query"], payout_sessions)
                except Exception:
                    log.exception("Failed processing update %s", item["update_id"])
        except Exception:
            log.exception("Telegram poll error")
            await asyncio.sleep(5)


async def main():
    validate_runtime_secrets()
    init_db()
    async with httpx.AsyncClient(trust_env=False) as client:
        await asyncio.gather(poll(client), run_outbox(client))


if __name__ == "__main__":
    asyncio.run(main())
