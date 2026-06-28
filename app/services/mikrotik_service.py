from __future__ import annotations

import random
import string
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.core.security import decrypt_text
from app.database.models import Server, Plan


class MikroTikService:
    """Client for the external MikroTik PPP Secret Panel JSON API.

    This adapter intentionally uses only the documented REST API surface and
    never imports credentials/routers from the provided sample source. The
    admin must configure the API base URL, router name and API key per server.
    """

    timeout = httpx.Timeout(20.0, connect=8.0)

    def _base(self, server: Server) -> str:
        base = (getattr(server, 'panel_url', '') or '').strip().rstrip('/')
        if not base.endswith('/api'):
            base += '/api'
        return base

    def _router(self, server: Server) -> str:
        meta = getattr(server, 'meta', None) or {}
        return str(meta.get('router_name') or server.username or '').strip()

    def _api_key(self, server: Server) -> str:
        return decrypt_text(server.password_encrypted or '')

    def _headers(self, server: Server) -> dict[str, str]:
        return {'X-API-Key': self._api_key(server), 'Accept': 'application/json'}

    async def _request(self, server: Server, method: str, path: str, *, json: dict | None = None, auth: bool = True) -> dict[str, Any]:
        url = self._base(server) + path
        headers = self._headers(server) if auth else {'Accept': 'application/json'}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(method, url, headers=headers, json=json)
        try:
            data = resp.json()
        except Exception:
            data = {'ok': False, 'error': resp.text[:250]}
        if resp.status_code >= 400 or data.get('ok') is False:
            raise RuntimeError(str(data.get('error') or f'MikroTik API HTTP {resp.status_code}'))
        return data

    async def health(self, server: Server) -> dict[str, Any]:
        return await self._request(server, 'GET', '/health', auth=False)

    async def routers(self, server: Server) -> list[dict[str, Any]]:
        data = await self._request(server, 'GET', '/routers')
        return list(data.get('data') or [])

    async def test_server(self, server: Server) -> tuple[bool, list[dict[str, Any]]]:
        try:
            routers = await self.routers(server)
            router_name = self._router(server)
            if router_name:
                matched = [r for r in routers if str(r.get('name')).lower() == router_name.lower()]
                return bool(matched and matched[0].get('online', True)), matched or routers
            return bool(routers), routers
        except Exception:
            return False, []

    def generate_password(self, length: int = 12) -> str:
        alphabet = string.ascii_letters + string.digits
        return ''.join(random.choice(alphabet) for _ in range(length))

    async def create_user_on_plan(self, server: Server, plan: Plan, username: str, password: str | None = None) -> dict[str, Any]:
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        password = password or self.generate_password()
        payload = {
            'name': username,
            'password': password,
            'volume_gb': float(getattr(plan, 'volume_gb', 0) or 0),
            'expire_days': int(getattr(plan, 'duration_days', 0) or 0),
        }
        if not payload['volume_gb']:
            payload.pop('volume_gb', None); payload['volume_unlimited'] = True
        if not payload['expire_days']:
            payload.pop('expire_days', None); payload['expire_unlimited'] = True
        data = await self._request(server, 'POST', f'/routers/{quote(router)}/users', json=payload)
        user = data.get('data') or {}
        user['password'] = password
        return user

    async def get_user(self, server: Server, username: str) -> dict[str, Any] | None:
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        try:
            data = await self._request(server, 'GET', f'/routers/{quote(router)}/users/{quote(username)}')
            return data.get('data') or {}
        except RuntimeError as exc:
            msg = str(exc).lower()
            if any(s in msg for s in ('not found', 'not exist', '404')):
                return None
            raise

    async def update_user(self, server: Server, username: str, *, volume_gb: float | None = None, expire_days: int | None = None, password: str | None = None) -> dict[str, Any]:
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        payload: dict[str, Any] = {}
        if volume_gb is not None:
            payload['volume_gb'] = float(volume_gb or 0) if volume_gb else None
            if not volume_gb:
                payload.pop('volume_gb', None); payload['volume_unlimited'] = True
        if expire_days is not None:
            if expire_days:
                payload['expire_days'] = int(expire_days)
            else:
                payload['expire_unlimited'] = True
        if password:
            payload['password'] = password
        data = await self._request(server, 'PATCH', f'/routers/{quote(router)}/users/{quote(username)}', json=payload)
        out = data.get('data') or {}
        if password:
            out['password'] = password
        return out

    async def set_enabled(self, server: Server, username: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable a PPP secret via the panel API.

        Used on renewal so that a secret the panel disabled on expiry/quota is
        re-activated when the customer renews.
        """
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        action = 'enable' if enabled else 'disable'
        return await self._request(server, 'POST', f'/routers/{quote(router)}/users/{quote(username)}/{action}')

    async def enable_user(self, server: Server, username: str) -> dict[str, Any]:
        return await self.set_enabled(server, username, True)

    async def renew_user(self, server: Server, username: str, *, volume_gb: float | None = None, expire_days: int | None = None) -> dict[str, Any]:
        """Update volume/expiry then re-enable the secret (renewal helper)."""
        out = await self.update_user(server, username, volume_gb=volume_gb, expire_days=expire_days)
        try:
            await self.set_enabled(server, username, True)
        except RuntimeError:
            # If the secret was already enabled the panel may noop; ignore.
            pass
        return out

    async def rotate_password(self, server: Server, username: str) -> dict[str, Any]:
        password = self.generate_password()
        out = await self.update_user(server, username, password=password)
        out['password'] = password
        return out

    async def delete_user(self, server: Server, username: str) -> dict[str, Any]:
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        return await self._request(server, 'DELETE', f'/routers/{quote(router)}/users/{quote(username)}')
