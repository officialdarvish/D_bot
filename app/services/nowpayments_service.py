import hmac
import hashlib
import json
from typing import Any

import httpx

from app.core.config import settings


class NowPaymentsService:
    def __init__(self) -> None:
        self.base_url = settings.NOWPAYMENTS_API_URL.rstrip('/')
        self.api_key = settings.NOWPAYMENTS_API_KEY

    def enabled(self) -> bool:
        return bool(settings.NOWPAYMENTS_ENABLED and self.api_key)

    async def create_payment(self, *, order_id: int, amount_irt: int, description: str) -> dict[str, Any]:
        if not self.enabled():
            raise RuntimeError('NOWPayments is not enabled. Set NOWPAYMENTS_ENABLED=true and NOWPAYMENTS_API_KEY.')
        payload: dict[str, Any] = {
            'price_amount': float(amount_irt),
            'price_currency': 'irr',
            'pay_currency': settings.NOWPAYMENTS_PAY_CURRENCY.lower(),
            'order_id': str(order_id),
            'order_description': description[:255],
        }
        if settings.NOWPAYMENTS_IPN_CALLBACK_URL:
            payload['ipn_callback_url'] = settings.NOWPAYMENTS_IPN_CALLBACK_URL
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                f'{self.base_url}/payment',
                headers={'x-api-key': self.api_key, 'Content-Type': 'application/json'},
                json=payload,
            )
            r.raise_for_status()
            return r.json()

    @staticmethod
    def verify_ipn(raw_body: bytes, signature: str | None) -> bool:
        secret = settings.NOWPAYMENTS_IPN_SECRET or ''
        if not secret or not signature:
            return False
        try:
            parsed = json.loads(raw_body.decode('utf-8'))
            normalized = json.dumps(parsed, separators=(',', ':'), sort_keys=True)
        except Exception:
            normalized = raw_body.decode('utf-8', errors='ignore')
        digest = hmac.new(secret.encode(), normalized.encode(), hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest, signature)
