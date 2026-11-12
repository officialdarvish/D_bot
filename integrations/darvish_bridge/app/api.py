"""FastAPI backend for Telegram Mini App, admin, seller, and merchant bot connectors."""
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import httpx
from .config import settings, CURRENCY_SCALE, validate_runtime_secrets
from .database import init_db, get_db
from .models import Merchant, MerchantBot, ReceiveAccount, Order, Receipt, Settlement, Dispute, AuditEvent
from .schemas import (MerchantCreate, MerchantReview, MerchantSettings, RefundCreate, BotCreate, AccountCreate, OrderCreate,
                      OrderReview, DeliveryUpdate, SettlementCreate, SettlementReview,
                      DisputeCreate, DisputeReview)
from .security import verify_telegram_init_data, digest_key
from . import services as svc

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    validate_runtime_secrets()
    init_db()  # Demo bootstrap; production should use Alembic migrations.
    yield


app = FastAPI(title="Darvish Bridge", version="1.0.0-mvp", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


def user_from_telegram(x_telegram_init_data: str = Header(default="")):
    return verify_telegram_init_data(x_telegram_init_data)


def require_admin(user=Depends(user_from_telegram)):
    if user["id"] not in settings.admin_ids:
        raise HTTPException(403, "فقط مدیر اصلی مجاز است")
    return user


def merchant_key(x_darvish_key: str = Header(default=""), db: Session = Depends(get_db)):
    if not x_darvish_key:
        raise HTTPException(401, "کلید اتصال ارائه نشده است")
    b = db.scalar(select(MerchantBot).where(MerchantBot.key_digest == digest_key(x_darvish_key), MerchantBot.active.is_(True)))
    if not b:
        raise HTTPException(401, "کلید اتصال معتبر نیست")
    return b


def result(obj, *fields):
    return {name: getattr(obj, name) for name in fields}


def order_json(db, o, include_instructions=False):
    r = result(o, "id", "merchant_id", "merchant_bot_id", "external_order_id", "buyer_tg_id", "product_title", "product_kind", "amount_minor", "currency", "status", "created_at")
    if include_instructions:
        account = db.get(ReceiveAccount, o.receive_account_id)
        r["receiver"] = result(account, "id", "label", "instructions", "currency")
    return r


def merchant_json(m):
    return result(m, "id", "owner_tg_id", "name", "status", "fee_bps", "created_at")


def settlement_json(s):
    return result(s, "id", "merchant_id", "amount_minor", "currency", "destination", "status", "payout_reference", "admin_note", "cycle_due_at", "created_at")


@app.get("/health")
def health():
    return {"ok": True, "service": "Darvish Bridge"}


@app.get("/")
async def homepage():
    return FileResponse("web/index.html")


@app.get("/api/v1/meta")
def meta():
    return {"brand": "Darvish Bridge", "currencies": CURRENCY_SCALE,
            "manual_eligible_product_kinds": ["physical", "offline_service"]+(["digital"] if settings.allow_digital_manual_receipts else []), "receipt_only": True}


@app.get("/api/v1/me")
def me(user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    merchants = db.scalars(select(Merchant).where(Merchant.owner_tg_id == user["id"])).all()
    return {"user": user, "is_admin": user["id"] in settings.admin_ids,
            "merchants": [merchant_json(m) for m in merchants]}


@app.post("/api/v1/merchants")
def register_merchant(payload: MerchantCreate, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    m = svc.create_merchant(db, user["id"], payload.name)
    db.commit()
    return merchant_json(m)


@app.get("/api/v1/merchants/{merchant_id}/dashboard")
def seller_dashboard(merchant_id: str, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    m = svc.owner_merchant(db, merchant_id, user["id"], require_approved=False)
    orders = db.scalars(select(Order).where(Order.merchant_id == merchant_id).order_by(Order.created_at.desc()).limit(30)).all()
    settlements = db.scalars(select(Settlement).where(Settlement.merchant_id == merchant_id).order_by(Settlement.created_at.desc()).limit(30)).all()
    bots = db.scalars(select(MerchantBot).where(MerchantBot.merchant_id == merchant_id)).all()
    return {"merchant": merchant_json(m), "balances": svc.balances(db, merchant_id),
            "orders": [order_json(db, o) for o in orders],
            "settlements": [settlement_json(s) for s in settlements],
            "bots": [result(b, "id", "label", "webhook_url", "active", "created_at") for b in bots]}


@app.post("/api/v1/merchants/{merchant_id}/bots")
def add_bot(merchant_id: str, payload: BotCreate, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    m = svc.owner_merchant(db, merchant_id, user["id"])
    b, key, secret = svc.create_bot(db, m, payload.label, payload.webhook_url)
    db.commit()
    return {"bot_id": b.id, "api_key_once": key, "webhook_secret_once": secret,
            "warning": "این دو مقدار فقط یک بار نمایش داده می‌شوند؛ در سرور امن ذخیره کنید."}


@app.post("/api/v1/merchants/{merchant_id}/bots/{bot_id}/revoke")
def revoke_bot(merchant_id: str, bot_id: str, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    m = svc.owner_merchant(db, merchant_id, user["id"])
    b = svc.revoke_bot(db, m, bot_id)
    db.commit()
    return {"id": b.id, "active": False}


@app.post("/api/v1/merchants/{merchant_id}/settlements")
def seller_settle(merchant_id: str, payload: SettlementCreate, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    m = svc.owner_merchant(db, merchant_id, user["id"])
    s = svc.create_settlement(db, m, payload.amount_minor, payload.currency, payload.destination)
    db.commit()
    return settlement_json(s)


@app.get("/api/v1/admin/overview")
def admin_overview(user=Depends(require_admin), db: Session = Depends(get_db)):
    merchants = db.scalars(select(Merchant).order_by(Merchant.created_at.desc()).limit(100)).all()
    orders = db.scalars(select(Order).order_by(Order.created_at.desc()).limit(100)).all()
    settlements = db.scalars(select(Settlement).order_by(Settlement.created_at.desc()).limit(100)).all()
    accounts = db.scalars(select(ReceiveAccount).order_by(ReceiveAccount.created_at.desc())).all()
    disputes = db.scalars(select(Dispute).order_by(Dispute.created_at.desc()).limit(50)).all()
    return {"merchants": [merchant_json(m) for m in merchants],
            "orders": [order_json(db, o) for o in orders],
            "settlements": [settlement_json(s) for s in settlements],
            "accounts": [result(a, "id", "currency", "label", "instructions", "active") for a in accounts],
            "disputes": [result(d, "id", "order_id", "reason", "status", "resolution") for d in disputes],
            "totals": {"merchants": db.scalar(select(func.count(Merchant.id))),
                       "pending_receipts": db.scalar(select(func.count(Order.id)).where(Order.status == "receipt_submitted")),
                       "pending_settlements": db.scalar(select(func.count(Settlement.id)).where(Settlement.status.in_(["requested", "approved"])))}}


@app.post("/api/v1/admin/merchants/{merchant_id}/review")
def admin_review_merchant(merchant_id: str, payload: MerchantReview, admin=Depends(require_admin), db: Session = Depends(get_db)):
    m = svc.review_merchant(db, merchant_id, admin["id"], payload.approved, payload.fee_bps)
    db.commit()
    return merchant_json(m)


@app.post("/api/v1/admin/merchants/{merchant_id}/settings")
def admin_merchant_settings(merchant_id: str, payload: MerchantSettings, admin=Depends(require_admin), db: Session = Depends(get_db)):
    m = svc.update_merchant_settings(db, merchant_id, admin["id"], payload.status, payload.fee_bps)
    db.commit()
    return merchant_json(m)


@app.post("/api/v1/admin/accounts")
def admin_add_account(payload: AccountCreate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    a = ReceiveAccount(**payload.model_dump())
    db.add(a)
    db.flush()
    svc.audit(db, f"admin:{admin['id']}", "receive_account.created", "receive_account", a.id)
    db.commit()
    return result(a, "id", "currency", "label", "instructions", "active")


@app.post("/api/v1/admin/accounts/{account_id}/toggle")
def admin_toggle_account(account_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(ReceiveAccount, account_id, with_for_update=True)
    if not a:
        raise HTTPException(404, "حساب دریافت پیدا نشد")
    a.active = not a.active
    svc.audit(db, f"admin:{admin['id']}", "receive_account.toggled", "receive_account", a.id, {"active": a.active})
    db.commit()
    return {"active": a.active}


@app.post("/api/v1/admin/orders/{order_id}/approve")
def admin_approve_order(order_id: str, payload: OrderReview, admin=Depends(require_admin), db: Session = Depends(get_db)):
    o = svc.review_order(db, order_id, admin["id"], True, payload.verified_real_transfer, payload.note)
    db.commit()
    return order_json(db, o)


@app.post("/api/v1/admin/orders/{order_id}/reject")
def admin_reject_order(order_id: str, payload: OrderReview, admin=Depends(require_admin), db: Session = Depends(get_db)):
    o = svc.review_order(db, order_id, admin["id"], False, False, payload.note)
    db.commit()
    return order_json(db, o)


@app.post("/api/v1/admin/orders/{order_id}/refund")
def admin_refund_order(order_id: str, payload: RefundCreate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    r = svc.refund_order(db, order_id, admin["id"], payload.verified_actual_refund,
                         payload.payout_reference, payload.reason)
    db.commit()
    return {"id": r.id, "order_id": r.order_id}


@app.post("/api/v1/admin/orders/{order_id}/retry-delivery")
def admin_retry_delivery(order_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    o = svc.resend_delivery_webhook(db, order_id, admin["id"])
    db.commit()
    return order_json(db, o)


@app.get("/api/v1/admin/orders/{order_id}/receipt-photo")
async def admin_receipt_photo(order_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order_id))
    if not receipt or not settings.bot_token:
        raise HTTPException(404, "تصویر رسید پیدا نشد")
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        response = await client.get(f"https://api.telegram.org/bot{settings.bot_token}/getFile", params={"file_id": receipt.telegram_file_id})
        response.raise_for_status()
        data = response.json()
        if not data.get("ok") or not data["result"].get("file_path") or data["result"].get("file_size", 0) > 20 * 1024 * 1024:
            raise HTTPException(422, "فایل قابل دریافت نیست")
        file_response = await client.get(f"https://api.telegram.org/file/bot{settings.bot_token}/{data['result']['file_path']}")
        file_response.raise_for_status()
    return Response(content=file_response.content, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/api/v1/admin/settlements/{settlement_id}/review")
def admin_review_settlement(settlement_id: str, payload: SettlementReview, admin=Depends(require_admin), db: Session = Depends(get_db)):
    s = svc.review_settlement(db, settlement_id, admin["id"], payload.action, payload.payout_reference, payload.note)
    db.commit()
    return settlement_json(s)


@app.post("/api/v1/admin/disputes/{dispute_id}/resolve")
def resolve_dispute(dispute_id: str, payload: DisputeReview, admin=Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Dispute, dispute_id, with_for_update=True)
    if not d or d.status != "open":
        raise HTTPException(409, "اختلاف باز پیدا نشد")
    d.status, d.resolution = "resolved", payload.resolution
    svc.audit(db, f"admin:{admin['id']}", "dispute.resolved", "dispute", d.id)
    svc.notify(db, d.opened_by_tg_id, f"✅ بررسی اختلاف {d.id} انجام شد:\n{payload.resolution}")
    db.commit()
    return {"status": d.status}


@app.get("/api/v1/admin/audit")
def admin_audit(admin=Depends(require_admin), db: Session = Depends(get_db)):
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)).all()
    return [result(a, "actor", "action", "target_type", "target_id", "detail_json", "created_at") for a in events]


@app.get("/api/v1/connect/capabilities")
def connector_capabilities(bot=Depends(merchant_key)):
    return {"product_kinds":["physical","offline_service"]+(["digital"] if settings.allow_digital_manual_receipts else []),"currencies":CURRENCY_SCALE,"receipt_only":True}


@app.post("/api/v1/connect/orders")
def connector_create_order(payload: OrderCreate, bot=Depends(merchant_key), db: Session = Depends(get_db)):
    o, created = svc.create_order(db, bot, payload)
    db.commit()
    return {"created": created, "order": order_json(db, o, include_instructions=True),
            "telegram_deep_link_parameter": f"order_{o.id}"}


@app.get("/api/v1/connect/orders/{order_id}")
def connector_get_order(order_id: str, bot=Depends(merchant_key), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o or o.merchant_bot_id != bot.id:
        raise HTTPException(404, "سفارش پیدا نشد")
    return order_json(db, o)


@app.post("/api/v1/connect/orders/{order_id}/delivery")
def connector_set_delivery(order_id: str, payload: DeliveryUpdate, bot=Depends(merchant_key), db: Session = Depends(get_db)):
    o = svc.delivered(db, order_id, bot, payload.status, payload.message)
    db.commit()
    return order_json(db, o)


@app.get("/api/v1/buyer/orders/{order_id}")
def buyer_order(order_id: str, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o or o.buyer_tg_id != user["id"]:
        raise HTTPException(404, "سفارش پیدا نشد")
    return order_json(db, o, include_instructions=True)


@app.post("/api/v1/buyer/orders/{order_id}/disputes")
def buyer_dispute(order_id: str, payload: DisputeCreate, user=Depends(user_from_telegram), db: Session = Depends(get_db)):
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "سفارش پیدا نشد")
    d = svc.open_dispute(db, o, user["id"], payload.reason)
    db.commit()
    return {"dispute_id": d.id, "status": d.status}


app.mount("/assets", StaticFiles(directory="web/assets"), name="assets")
