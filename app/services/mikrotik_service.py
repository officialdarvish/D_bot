from __future__ import annotations

import json
import os
import glob
import random
import re
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.security import decrypt_text
from app.database.models import Server, Plan


class MikroTikService:
    """Client for the external MikroTik PPP Secret Panel JSON API.

    The panel API itself is based on `/api/*` endpoints. Authentication in the
    documented API is an API key (`X-API-Key` or `Authorization: Bearer`).

    For admin convenience this adapter also supports saving the normal panel
    login username/password in D BOT. In that mode it first tries the password as
    an API key, then tries common login endpoints and reuses the returned bearer
    token or session cookie for `/api/*` calls. This keeps old API-key setups
    working while allowing the Add Server form to work with panel login data
    when the MikroTik panel exposes session auth.
    """

    timeout = httpx.Timeout(20.0, connect=8.0)

    def _panel_origin(self, server: Server) -> str:
        raw = (getattr(server, 'panel_url', '') or '').strip().rstrip('/')
        if raw.endswith('/api'):
            raw = raw[:-4].rstrip('/')
        return raw

    def _base(self, server: Server) -> str:
        return self._panel_origin(server).rstrip('/') + '/api'

    def _router(self, server: Server) -> str:
        meta = getattr(server, 'meta', None) or {}
        return str(meta.get('router_name') or server.username or '').strip()

    def _auth_username(self, server: Server) -> str:
        meta = getattr(server, 'meta', None) or {}
        return str(meta.get('auth_username') or meta.get('panel_username') or '').strip()

    def _secret(self, server: Server) -> str:
        return decrypt_text(server.password_encrypted or '')

    def _local_api_key_candidates(self, server: Server | None = None) -> list[str]:
        """Return API keys configured outside the admin UI.

        The MikroTik / Custom API documentation requires `X-API-Key` / Bearer auth
        for `/api/routers`. D BOT never hardcodes the user's panel URL,
        username, password, or API key. It discovers the API key only from:
        - environment variables inside D BOT,
        - a mounted config.json from the same VPS, or
        - a server-specific config path stored in metadata.
        """
        candidates: list[str] = []

        def add_value(value: Any) -> None:
            value = str(value or '').strip()
            if value and value not in candidates:
                candidates.append(value)

        for env_name in ('CUSTOM_PANEL_API_KEY', 'MIKROTIK_PANEL_API_KEY', 'MIKROTIK_API_KEY'):
            add_value(os.getenv(env_name))

        meta = getattr(server, 'meta', None) or {} if server is not None else {}
        raw_paths = [
            str(meta.get('custom_panel_config_path') or ''),
            os.getenv('CUSTOM_PANEL_CONFIG_PATH') or '',
            os.getenv('MIKROTIK_PANEL_CONFIG_PATH') or '',
            '/opt/mikrotik-panel/config.json',
            '/host/opt/mikrotik-panel/config.json',
            '/run/secrets/mikrotik_panel_config.json',
            '/app/mikrotik-panel-config.json',
        ]

        paths: list[str] = []

        def add_path(raw_path: str) -> None:
            raw_path = (raw_path or '').strip()
            if not raw_path:
                return
            variants = [raw_path]
            # If the admin entered the host path (/opt/...), also try the
            # Docker-mounted host mirror (/host/opt/...). If an env points to
            # /host/opt, also try the direct path for non-Docker installs.
            if raw_path.startswith('/opt/'):
                variants.append('/host' + raw_path)
            if raw_path.startswith('/host/opt/'):
                variants.append(raw_path[5:])
            for item in variants:
                if item not in paths:
                    paths.append(item)

        for raw_path in raw_paths:
            add_path(raw_path)

        # Be forgiving when the folder name is slightly different. This only
        # searches mounted/local /opt config files and never fetches secrets from
        # the network or source code.
        for pattern in (
            '/host/opt/*/config.json',
            '/host/opt/*/*/config.json',
            '/opt/*/config.json',
            '/opt/*/*/config.json',
        ):
            for found in glob.glob(pattern):
                add_path(found)

        for raw_path in paths:
            try:
                data = json.loads(Path(raw_path).read_text(encoding='utf-8'))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            for key_name in ('api_key', 'API_KEY', 'x_api_key', 'token', 'access_token'):
                add_value(data.get(key_name))
        return candidates

    def _key_headers(self, secret: str) -> dict[str, str]:
        # The MikroTik / Custom API supports both headers. Sending both keeps the
        # adapter compatible with deployments that use either API-key header.
        headers = {'Accept': 'application/json'}
        if secret:
            headers['X-API-Key'] = secret
            headers['Authorization'] = f'Bearer {secret}'
        return headers

    def _extract_token(self, payload: Any) -> str:
        """Find an auth token/API key in common custom-panel login responses."""
        wanted = {'token', 'access_token', 'api_key', 'apikey', 'key', 'jwt', 'bearer'}
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key.lower() in wanted and value:
                    return str(value)
            for value in payload.values():
                found = self._extract_token(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = self._extract_token(value)
                if found:
                    return found
        return ''

    async def _login_auth_headers(self, client: httpx.AsyncClient, server: Server) -> dict[str, str]:
        username = self._auth_username(server)
        password = self._secret(server)
        if not username or not password:
            return {}

        origin = self._panel_origin(server)
        login_pages = ['/', '/login', '/admin/login', '/auth/login']
        csrf_fields: dict[str, str] = {}
        for page in login_pages:
            try:
                page_resp = await client.get(origin.rstrip('/') + page, headers={'Accept': 'text/html,application/json'})
                if page_resp.status_code < 400:
                    # Preserve any session/csrf cookies and collect common hidden csrf fields.
                    for name, value in re.findall(r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', page_resp.text or '', flags=re.I):
                        lname = name.lower()
                        if 'csrf' in lname or lname in {'_token', 'csrf_token'}:
                            csrf_fields[name] = value
                    action_match = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', page_resp.text or '', flags=re.I)
                    if action_match:
                        action = action_match.group(1).strip()
                        if action and action.startswith('/'):
                            csrf_fields.setdefault('__detected_login_action__', action)
            except Exception:
                continue

        login_paths = ['/api/auth/login', '/api/login', '/auth/login', '/admin/login', '/login']
        detected_action = csrf_fields.pop('__detected_login_action__', '')
        if detected_action and detected_action not in login_paths:
            login_paths.insert(0, detected_action)
        base_payloads = [
            {'username': username, 'password': password},
            {'user': username, 'password': password},
            {'login': username, 'password': password},
            {'email': username, 'password': password},
        ]
        payloads: list[tuple[str, dict[str, str]]] = []
        for payload in base_payloads:
            enriched = dict(payload)
            enriched.update(csrf_fields)
            enriched.setdefault('next', '/admin')
            enriched.setdefault('next_url', '/admin')
            payloads.append(('json', enriched))
            payloads.append(('form', enriched))

        for path in login_paths:
            for mode, payload in payloads:
                try:
                    if mode == 'json':
                        resp = await client.post(origin.rstrip('/') + path, json=payload, headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
                    else:
                        resp = await client.post(origin.rstrip('/') + path, data=payload, headers={'Accept': 'application/json, text/html'})
                    content_type = resp.headers.get('content-type', '')
                    data: Any = {}
                    if 'json' in content_type:
                        try:
                            data = resp.json()
                        except Exception:
                            data = {}
                    if resp.status_code >= 400:
                        continue

                    token = self._extract_token(data)
                    if token:
                        return {'Accept': 'application/json', 'Authorization': f'Bearer {token}', 'X-API-Key': token}

                    # Many custom admin panels authenticate with a normal HTTP
                    # session cookie. The AsyncClient keeps cookies from the GET
                    # login page and POST login response; the next /api/* request
                    # can reuse them with this generic header.
                    if client.cookies:
                        return {'Accept': 'application/json'}
                except Exception:
                    continue
        return {}

    async def _request(self, server: Server, method: str, path: str, *, json: dict | None = None, auth: bool = True) -> dict[str, Any]:
        url = self._base(server) + path
        secret = self._secret(server)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            header_attempts: list[dict[str, str]] = []
            seen_headers: set[tuple[tuple[str, str], ...]] = set()

            def add_headers(headers: dict[str, str]) -> None:
                marker = tuple(sorted((str(k), str(v)) for k, v in (headers or {}).items()))
                if marker not in seen_headers:
                    seen_headers.add(marker)
                    header_attempts.append(headers)

            if auth:
                # 1) Try the value saved in the server record. In older builds
                # this could be the panel password; in fixed builds it may be the
                # resolved API key.
                add_headers(self._key_headers(secret))
                # 2) Try env/config based keys so the UI can stay login-only when
                # the MikroTik / Custom lives on the same VPS.
                for candidate in self._local_api_key_candidates(server):
                    if candidate != secret:
                        add_headers(self._key_headers(candidate))
            else:
                add_headers({'Accept': 'application/json'})

            # Only try panel login after key/header auth fails or when this is a
            # protected request. `/api/health` remains no-auth.
            errors: list[str] = []
            idx = 0
            while idx < len(header_attempts):
                headers = header_attempts[idx]
                resp = await client.request(method, url, headers=headers, json=json)
                data = self._parse_response(resp)
                if resp.status_code < 400 and data.get('ok') is not False:
                    if auth:
                        success_key = str(headers.get('X-API-Key') or '').strip()
                        auth_header = str(headers.get('Authorization') or '').strip()
                        if not success_key and auth_header.lower().startswith('bearer '):
                            success_key = auth_header.split(' ', 1)[1].strip()
                        if success_key:
                            self.last_successful_auth_secret = success_key
                    return data
                errors.append(str(data.get('error') or data.get('detail') or f'HTTP {resp.status_code}'))

                if auth and idx == 0:
                    login_headers = await self._login_auth_headers(client, server)
                    if login_headers:
                        add_headers(login_headers)
                idx += 1

            msg = errors[-1] if errors else 'MikroTik API request failed'
            if str(msg).lower() in {'unauthorized', '401', 'http 401'} or 'unauthorized' in str(msg).lower():
                msg = (
                    'Unauthorized: /api/routers in this MikroTik / Custom requires X-API-Key / Bearer auth. '
                    'Use the API key from the panel config.json in Add Server > Profile: MikroTik / Custom, '
                    'or set CUSTOM_PANEL_API_KEY / mount the config file. Web login credentials are not hardcoded and only work if the panel itself exposes session API auth.'
                )
            raise RuntimeError(msg)

    def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            data = {'ok': False, 'error': resp.text[:250]}
        if not isinstance(data, dict):
            data = {'ok': True, 'data': data}
        if resp.status_code >= 400 and 'error' not in data:
            data['error'] = data.get('detail') or f'MikroTik API HTTP {resp.status_code}'
        return data

    async def health(self, server: Server) -> dict[str, Any]:
        return await self._request(server, 'GET', '/health', auth=False)

    async def routers(self, server: Server) -> list[dict[str, Any]]:
        data = await self._request(server, 'GET', '/routers')
        rows = data.get('data') or []
        if isinstance(rows, dict):
            rows = rows.get('routers') or rows.get('items') or []
        return list(rows or [])

    def pick_router(self, routers: list[dict[str, Any]], preferred: str = '') -> dict[str, Any] | None:
        preferred = (preferred or '').strip().lower()
        if preferred:
            for row in routers:
                if str(row.get('name') or '').strip().lower() == preferred:
                    return row
        for row in routers:
            if row.get('online', True):
                return row
        return routers[0] if routers else None

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

    @staticmethod
    def _as_bool(value: Any, default: bool | None = None) -> bool | None:
        """Convert common panel boolean representations without treating "false" as True."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if text in {'1', 'true', 'yes', 'on', 'enabled', 'active', 'online'}:
            return True
        if text in {'0', 'false', 'no', 'off', 'disabled', 'inactive', 'expired', 'blocked', ''}:
            return False
        return default

    def user_is_active(self, user: dict[str, Any] | None, fallback: bool = True) -> bool:
        """Return the authoritative enabled state returned by the MikroTik panel."""
        if not isinstance(user, dict):
            return bool(fallback)

        disabled = self._as_bool(user.get('disabled'))
        expired = self._as_bool(user.get('expired'))
        if disabled is True or expired is True:
            return False

        for key in ('enabled', 'enable', 'active', 'is_active'):
            parsed = self._as_bool(user.get(key))
            if parsed is not None:
                return parsed

        status = str(user.get('status') or '').strip().lower()
        if status in {'disabled', 'inactive', 'expired', 'blocked', 'suspended'}:
            return False
        if status in {'enabled', 'active', 'online'}:
            return True

        # MikroTik/custom panels commonly expose only ``disabled``. An explicit
        # false value is authoritative and must reactivate a locally stale row.
        if disabled is False:
            return True
        if expired is False and 'expired' in user:
            return True
        return bool(fallback)

    def generate_password(self, length: int = 12) -> str:
        alphabet = string.ascii_letters + string.digits
        return ''.join(random.choice(alphabet) for _ in range(length))

    async def create_user_on_plan(self, server: Server, plan: Plan, username: str, password: str | None = None) -> dict[str, Any]:
        router = self._router(server)
        if not router:
            routers = await self.routers(server)
            picked = self.pick_router(routers)
            router = str((picked or {}).get('name') or '').strip()
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
        router = self._router(server)
        if not router:
            raise RuntimeError('MikroTik router name is not configured')
        action = 'enable' if enabled else 'disable'
        return await self._request(server, 'POST', f'/routers/{quote(router)}/users/{quote(username)}/{action}')

    async def enable_user(self, server: Server, username: str) -> dict[str, Any]:
        return await self.set_enabled(server, username, True)

    async def renew_user(self, server: Server, username: str, *, volume_gb: float | None = None, expire_days: int | None = None) -> dict[str, Any]:
        out = await self.update_user(server, username, volume_gb=volume_gb, expire_days=expire_days)
        try:
            await self.set_enabled(server, username, True)
        except RuntimeError:
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
