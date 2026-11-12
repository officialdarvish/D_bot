import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, BigInteger, ForeignKey, DateTime, Text, Boolean, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    fee_bps: Mapped[int] = mapped_column(Integer, default=500)  # 5%
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MerchantBot(Base):
    __tablename__ = "merchant_bots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    key_digest: Mapped[str] = mapped_column(String(64), unique=True)
    webhook_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReceiveAccount(Base):
    __tablename__ = "receive_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    currency: Mapped[str] = mapped_column(String(12), index=True)
    label: Mapped[str] = mapped_column(String(120))
    instructions: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("merchant_bot_id", "external_order_id", name="uq_external_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    merchant_bot_id: Mapped[str] = mapped_column(ForeignKey("merchant_bots.id"), index=True)
    external_order_id: Mapped[str] = mapped_column(String(120))
    buyer_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    product_title: Mapped[str] = mapped_column(String(255))
    product_kind: Mapped[str] = mapped_column(String(32))
    delivery_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    fee_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(12))
    receive_account_id: Mapped[str] = mapped_column(ForeignKey("receive_accounts.id"))
    status: Mapped[str] = mapped_column(String(32), default="awaiting_receipt", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    telegram_file_id: Mapped[str] = mapped_column(Text)
    telegram_file_unique_id: Mapped[str] = mapped_column(String(200))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BuyerSession(Base):
    __tablename__ = "buyer_sessions"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class LedgerRow(Base):
    __tablename__ = "ledger_rows"
    __table_args__ = (Index("ix_ledger_balance", "merchant_id", "currency", "account"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    journal_id: Mapped[str] = mapped_column(String(36), index=True)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey("merchants.id"), nullable=True)
    currency: Mapped[str] = mapped_column(String(12))
    account: Mapped[str] = mapped_column(String(32))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    reference_type: Mapped[str] = mapped_column(String(24))
    reference_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    currency: Mapped[str] = mapped_column(String(12))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    destination: Mapped[str] = mapped_column(String(300))
    cycle_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    payout_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
    payout_reference: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    opened_by_tg_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(90))
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(36))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(24)) # telegram_message, telegram_photo, merchant_webhook
    target: Mapped[str] = mapped_column(String(400))
    payload_json: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
