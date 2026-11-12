from pydantic import BaseModel, Field
from typing import Literal


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class MerchantReview(BaseModel):
    approved: bool
    fee_bps: int = Field(default=500, ge=0, le=3000)


class MerchantSettings(BaseModel):
    fee_bps: int = Field(ge=0, le=3000)
    status: Literal["approved", "suspended"]


class RefundCreate(BaseModel):
    verified_actual_refund: bool
    payout_reference: str = Field(min_length=3, max_length=300)
    reason: str = Field(min_length=3, max_length=500)


class BotCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    webhook_url: str | None = None


class AccountCreate(BaseModel):
    currency: Literal["IRT", "USDT", "TON", "USD", "EUR", "UNIT"]
    label: str = Field(min_length=2, max_length=120)
    instructions: str = Field(min_length=5, max_length=2000)
    active: bool = True


class OrderCreate(BaseModel):
    external_order_id: str = Field(min_length=1, max_length=120)
    buyer_tg_id: int = Field(gt=0)
    product_title: str = Field(min_length=1, max_length=255)
    product_kind: Literal["physical", "offline_service", "digital"]
    amount_minor: int = Field(gt=0, le=10**16)
    currency: Literal["IRT", "USDT", "TON", "USD", "EUR", "UNIT"]
    delivery_message: str | None = Field(default=None, max_length=2000)


class OrderReview(BaseModel):
    verified_real_transfer: bool
    note: str = Field(default="", max_length=500)


class DeliveryUpdate(BaseModel):
    status: Literal["fulfilled", "failed"]
    message: str = Field(default="", max_length=500)


class SettlementCreate(BaseModel):
    amount_minor: int = Field(gt=0, le=10**16)
    currency: Literal["IRT", "USDT", "TON", "USD", "EUR", "UNIT"]
    destination: str = Field(min_length=5, max_length=300)


class SettlementReview(BaseModel):
    action: Literal["approve", "reject", "paid"]
    payout_reference: str | None = Field(default=None, max_length=300)
    note: str = Field(default="", max_length=500)


class DisputeCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=2000)


class DisputeReview(BaseModel):
    resolution: str = Field(min_length=3, max_length=1000)
