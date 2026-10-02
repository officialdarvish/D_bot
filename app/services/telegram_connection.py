from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decrypt_text, encrypt_text
from app.database.models import Setting
from app.database.session import SessionLocal

MODE_DIRECT = 'direct'
MODE_PROXY = 'proxy'
MODE_V2RAY = 'v2ray'
MODE_MIKROTIK = 'mikrotik'
VALID_MODES = {MODE_DIRECT, MODE_PROXY, MODE_V2RAY, MODE_MIKROTIK}
VALID_PROXY_SCHEMES = {'http', 'socks4', 'socks5'}
SUPPORTED_V2_SCHEMES = {'vless', 'vmess', 'trojan', 'ss'}
XRAY_BIN = os.environ.get('XRAY_BIN', '/usr/local/bin/xray')
DEFAULT_LOCAL_SOCKS_PORT = 10809

# Settings are stored in the existing key/value table so no migration is required.
KEY_MODE = 'telegram_connection_mode'
KEY_REVISION = 'telegram_connection_revision'
KEY_PROXY_SCHEME = 'telegram_connection_proxy_scheme'
KEY_PROXY_HOST = 'telegram_connection_proxy_host'
KEY_PROXY_PORT = 'telegram_connection_proxy_port'
KEY_PROXY_USERNAME = 'telegram_connection_proxy_username'
KEY_PROXY_PASSWORD = 'telegram_connection_proxy_password_secret'
KEY_V2_URI = 'telegram_connection_v2_uri_secret'
KEY_MIKROTIK_HOST = 'telegram_connection_mikrotik_host'
KEY_MIKROTIK_PORT = 'telegram_connection_mikrotik_port'
KEY_MIKROTIK_USERNAME = 'telegram_connection_mikrotik_username'
KEY_MIKROTIK_PASSWORD = 'telegram_connection_mikrotik_password_secret'
KEY_LAST_TEST_STATUS = 'telegram_connection_last_test_status'
KEY_LAST_TEST_MESSAGE = 'telegram_connection_last_test_message'
KEY_LAST_TEST_AT = 'telegram_connection_last_test_at'
KEY_LAST_TEST_LATENCY = 'telegram_connection_last_test_latency_ms'

SECRET_KEYS = {KEY_PROXY_PASSWORD, KEY_V2_URI, KEY_MIKROTIK_PASSWORD}


@dataclass
class RuntimeConnection:
    mode: str
    proxy_url: str | None = None
    xray_process: asyncio.subprocess.Process | None = None
    xray_tempdir: tempfile.TemporaryDirectory[str] | None = None
    description: str = 'Direct'

    async def close(self) -> None:
        if self.xray_process is not None and self.xray_process.returncode is None:
            try:
                self.xray_process.terminate()
                await asyncio.wait_for(self.xray_process.wait(), timeout=4)
            except Exception:
                try:
                    self.xray_process.kill()
                except Exception:
                    pass
        if self.xray_tempdir is not None:
            try:
                self.xray_tempdir.cleanup()
            except Exception:
                pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _decode_secret(raw: str | None) -> str:
    value = str(raw or '').strip()
    if not value:
        return ''
    try:
        return decrypt_text(value)
    except Exception:
        return ''


def _mask(value: str, left: int = 5, right: int = 4) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    if len(raw) <= left + right + 3:
        return '••••••••'
    return f'{raw[:left]}…{raw[-right:]}'


async def _read_settings_map() -> dict[str, str]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Setting).where(Setting.key.like('telegram_connection_%')))).scalars().all()
    return {str(row.key): str(row.value or '') for row in rows}


async def get_connection_config(*, include_secrets: bool = False) -> dict[str, Any]:
    raw = await _read_settings_map()
    mode = raw.get(KEY_MODE, MODE_DIRECT).strip().lower() or MODE_DIRECT
    if mode not in VALID_MODES:
        mode = MODE_DIRECT
    proxy_password = _decode_secret(raw.get(KEY_PROXY_PASSWORD))
    v2_uri = _decode_secret(raw.get(KEY_V2_URI))
    mikrotik_password = _decode_secret(raw.get(KEY_MIKROTIK_PASSWORD))
    detected_protocol = ''
    if v2_uri:
        try:
            detected_protocol = detect_v2_protocol(v2_uri)
        except Exception:
            detected_protocol = ''
    return {
        'mode': mode,
        'revision': raw.get(KEY_REVISION, ''),
        'proxy': {
            'scheme': (raw.get(KEY_PROXY_SCHEME, 'socks5').lower() or 'socks5'),
            'host': raw.get(KEY_PROXY_HOST, ''),
            'port': raw.get(KEY_PROXY_PORT, '1080') or '1080',
            'username': raw.get(KEY_PROXY_USERNAME, ''),
            'password': proxy_password if include_secrets else '',
            'password_configured': bool(proxy_password),
        },
        'v2ray': {
            'uri': v2_uri if include_secrets else '',
            'uri_configured': bool(v2_uri),
            'uri_preview': _mask(v2_uri, 12, 8) if v2_uri else '',
            'protocol': detected_protocol,
            'xray_available': Path(XRAY_BIN).is_file() and os.access(XRAY_BIN, os.X_OK),
        },
        'mikrotik': {
            'host': raw.get(KEY_MIKROTIK_HOST, ''),
            'port': raw.get(KEY_MIKROTIK_PORT, '1080') or '1080',
            'username': raw.get(KEY_MIKROTIK_USERNAME, ''),
            'password': mikrotik_password if include_secrets else '',
            'password_configured': bool(mikrotik_password),
        },
        'last_test': {
            'status': raw.get(KEY_LAST_TEST_STATUS, ''),
            'message': raw.get(KEY_LAST_TEST_MESSAGE, ''),
            'at': raw.get(KEY_LAST_TEST_AT, ''),
            'latency_ms': raw.get(KEY_LAST_TEST_LATENCY, ''),
        },
    }


def _valid_port(value: Any, default: int = 1080) -> int:
    try:
        port = int(str(value or default).strip())
    except Exception:
        port = default
    if not (1 <= port <= 65535):
        raise ValueError('Port must be between 1 and 65535.')
    return port


def _validate_host(value: str, label: str = 'Host') -> str:
    host = str(value or '').strip()
    if not host:
        raise ValueError(f'{label} is required.')
    if any(ch.isspace() for ch in host) or '/' in host:
        raise ValueError(f'{label} is invalid.')
    return host


def _proxy_url(scheme: str, host: str, port: Any, username: str = '', password: str = '') -> str:
    normalized = str(scheme or '').strip().lower()
    if normalized not in VALID_PROXY_SCHEMES:
        raise ValueError('Proxy protocol must be HTTP, SOCKS4, or SOCKS5.')
    clean_host = _validate_host(host, 'Proxy host')
    clean_port = _valid_port(port)
    user = str(username or '').strip()
    pwd = str(password or '')
    auth = ''
    if user:
        auth = quote(user, safe='')
        if pwd:
            auth += ':' + quote(pwd, safe='')
        auth += '@'
    return f'{normalized}://{auth}{clean_host}:{clean_port}'


def detect_v2_protocol(uri: str) -> str:
    raw = str(uri or '').strip()
    if not raw:
        return ''
    scheme = raw.split('://', 1)[0].lower() if '://' in raw else ''
    if scheme not in SUPPORTED_V2_SCHEMES:
        raise ValueError('Supported V2 links: VLESS, VMess, Trojan, and Shadowsocks.')
    return {'ss': 'Shadowsocks'}.get(scheme, scheme.upper())


def _decode_b64(text: str) -> str:
    raw = text.strip().replace('-', '+').replace('_', '/')
    raw += '=' * (-len(raw) % 4)
    return base64.b64decode(raw).decode('utf-8')


def _query_one(query: dict[str, list[str]], *names: str, default: str = '') -> str:
    for name in names:
        vals = query.get(name)
        if vals:
            return str(vals[0] or '')
    return default


def _transport_settings(params: dict[str, str]) -> dict[str, Any]:
    raw_type = (params.get('type') or params.get('net') or params.get('network') or 'tcp').strip().lower()
    method_map = {
        'tcp': 'raw', 'raw': 'raw',
        'ws': 'websocket', 'websocket': 'websocket',
        'grpc': 'grpc',
        'xhttp': 'xhttp', 'http': 'xhttp', 'h2': 'xhttp',
        'httpupgrade': 'httpupgrade',
        'kcp': 'mkcp', 'mkcp': 'mkcp',
    }
    method = method_map.get(raw_type, 'raw')
    stream: dict[str, Any] = {'method': method}
    host = params.get('host', '').strip()
    path = params.get('path', '').strip() or '/'
    if method == 'websocket':
        stream['wsSettings'] = {'path': path, **({'host': host} if host else {})}
    elif method == 'httpupgrade':
        stream['httpupgradeSettings'] = {'path': path, **({'host': host} if host else {})}
    elif method == 'grpc':
        service = params.get('serviceName', '').strip() or params.get('service_name', '').strip() or path.lstrip('/')
        stream['grpcSettings'] = {'serviceName': service}
        authority = params.get('authority', '').strip()
        if authority:
            stream['grpcSettings']['authority'] = authority
    elif method == 'xhttp':
        xh: dict[str, Any] = {'path': path}
        if host:
            xh['host'] = host
        mode = params.get('mode', '').strip()
        if mode:
            xh['mode'] = mode
        stream['xhttpSettings'] = xh
    elif method == 'mkcp':
        stream['kcpSettings'] = {'header': {'type': params.get('headerType', 'none') or 'none'}}
    else:
        stream['rawSettings'] = {'header': {'type': params.get('headerType', 'none') or 'none'}}

    security = (params.get('security') or params.get('tls') or 'none').strip().lower()
    if security in {'tls', 'reality'}:
        stream['security'] = security
        sni = params.get('sni', '').strip() or params.get('serverName', '').strip()
        fp = params.get('fp', '').strip() or params.get('fingerprint', '').strip() or 'chrome'
        if security == 'reality':
            public_key = params.get('pbk', '').strip() or params.get('publicKey', '').strip() or params.get('password', '').strip()
            reality: dict[str, Any] = {
                'serverName': sni,
                'fingerprint': fp,
                'password': public_key,
                'shortId': params.get('sid', '').strip() or params.get('shortId', '').strip(),
                'spiderX': unquote(params.get('spx', '').strip() or params.get('spiderX', '').strip()),
            }
            stream['realitySettings'] = {k: v for k, v in reality.items() if v != ''}
        else:
            tls: dict[str, Any] = {'allowInsecure': str(params.get('allowInsecure', '0')).lower() in {'1', 'true', 'yes'}}
            if sni:
                tls['serverName'] = sni
            if fp:
                tls['fingerprint'] = fp
            alpn = params.get('alpn', '').strip()
            if alpn:
                tls['alpn'] = [x.strip() for x in alpn.split(',') if x.strip()]
            stream['tlsSettings'] = tls
    else:
        stream['security'] = 'none'
    return stream


def parse_v2_link(uri: str) -> dict[str, Any]:
    raw = str(uri or '').strip()
    scheme = raw.split('://', 1)[0].lower() if '://' in raw else ''
    if scheme not in SUPPORTED_V2_SCHEMES:
        raise ValueError('Supported V2 links: VLESS, VMess, Trojan, and Shadowsocks.')

    if scheme == 'vmess':
        encoded = raw.split('://', 1)[1].split('#', 1)[0]
        try:
            payload = json.loads(_decode_b64(encoded))
        except Exception as exc:
            raise ValueError('Invalid VMess link.') from exc
        host = _validate_host(str(payload.get('add') or payload.get('address') or ''), 'VMess host')
        port = _valid_port(payload.get('port'), 443)
        user_id = str(payload.get('id') or '').strip()
        if not user_id:
            raise ValueError('VMess UUID is missing.')
        params = {
            'type': str(payload.get('net') or 'tcp'),
            'host': str(payload.get('host') or ''),
            'path': str(payload.get('path') or '/'),
            'security': 'tls' if str(payload.get('tls') or '').lower() in {'tls', '1', 'true'} else 'none',
            'sni': str(payload.get('sni') or ''),
            'fp': str(payload.get('fp') or 'chrome'),
            'serviceName': str(payload.get('path') or '').lstrip('/'),
        }
        outbound = {
            'protocol': 'vmess',
            'settings': {
                'address': host,
                'port': port,
                'id': user_id,
                'security': str(payload.get('scy') or 'auto'),
                'level': 0,
            },
            'streamSettings': _transport_settings(params),
            'tag': 'telegram-proxy',
        }
        return outbound

    if scheme == 'ss':
        body = raw.split('://', 1)[1].split('#', 1)[0]
        query_part = ''
        if '?' in body:
            body, query_part = body.split('?', 1)
        method = password = host = ''
        port = 0
        if '@' in body:
            creds, server = body.rsplit('@', 1)
            try:
                decoded_creds = _decode_b64(creds) if ':' not in unquote(creds) else unquote(creds)
            except Exception:
                decoded_creds = unquote(creds)
            if ':' not in decoded_creds:
                raise ValueError('Invalid Shadowsocks credentials.')
            method, password = decoded_creds.split(':', 1)
            parsed_server = urlsplit(f'ss://x@{server}')
            host = parsed_server.hostname or ''
            port = parsed_server.port or 0
        else:
            try:
                decoded = _decode_b64(body)
            except Exception as exc:
                raise ValueError('Invalid Shadowsocks link.') from exc
            if '@' not in decoded or ':' not in decoded.split('@', 1)[0]:
                raise ValueError('Invalid Shadowsocks link.')
            creds, server = decoded.rsplit('@', 1)
            method, password = creds.split(':', 1)
            parsed_server = urlsplit(f'ss://x@{server}')
            host = parsed_server.hostname or ''
            port = parsed_server.port or 0
        host = _validate_host(host, 'Shadowsocks host')
        port = _valid_port(port, 443)
        return {
            'protocol': 'shadowsocks',
            'settings': {'address': host, 'port': port, 'method': method, 'password': password, 'level': 0},
            'tag': 'telegram-proxy',
        }

    parsed = urlsplit(raw)
    host = _validate_host(parsed.hostname or '', f'{scheme.upper()} host')
    port = _valid_port(parsed.port, 443)
    query = parse_qs(parsed.query, keep_blank_values=True)
    params = {k: _query_one(query, k) for k in query}
    params.setdefault('type', _query_one(query, 'type', 'net', default='tcp'))
    params.setdefault('security', _query_one(query, 'security', default='none'))
    params.setdefault('host', _query_one(query, 'host'))
    params.setdefault('path', _query_one(query, 'path', default='/'))
    params.setdefault('sni', _query_one(query, 'sni', 'serverName'))
    params.setdefault('fp', _query_one(query, 'fp', 'fingerprint', default='chrome'))
    params.setdefault('serviceName', _query_one(query, 'serviceName', 'service_name'))
    params.setdefault('pbk', _query_one(query, 'pbk', 'publicKey'))
    params.setdefault('sid', _query_one(query, 'sid', 'shortId'))
    params.setdefault('spx', _query_one(query, 'spx', 'spiderX'))
    params.setdefault('flow', _query_one(query, 'flow'))
    params.setdefault('encryption', _query_one(query, 'encryption', default='none'))

    if scheme == 'vless':
        user_id = unquote(parsed.username or '').strip()
        if not user_id:
            raise ValueError('VLESS UUID is missing.')
        settings_obj: dict[str, Any] = {
            'address': host,
            'port': port,
            'id': user_id,
            'encryption': params.get('encryption') or 'none',
            'level': 0,
        }
        if params.get('flow'):
            settings_obj['flow'] = params['flow']
        return {'protocol': 'vless', 'settings': settings_obj, 'streamSettings': _transport_settings(params), 'tag': 'telegram-proxy'}

    if scheme == 'trojan':
        password = unquote(parsed.username or '').strip()
        if not password:
            raise ValueError('Trojan password is missing.')
        return {
            'protocol': 'trojan',
            'settings': {'address': host, 'port': port, 'password': password, 'level': 0},
            'streamSettings': _transport_settings(params),
            'tag': 'telegram-proxy',
        }

    raise ValueError('Unsupported V2 link.')


def build_xray_config(uri: str, local_port: int) -> dict[str, Any]:
    outbound = parse_v2_link(uri)
    return {
        'log': {'loglevel': 'warning'},
        'inbounds': [{
            'listen': '127.0.0.1',
            'port': int(local_port),
            'protocol': 'socks',
            'settings': {'auth': 'noauth', 'udp': False},
            'tag': 'telegram-local-socks',
        }],
        'outbounds': [outbound],
    }


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


async def _wait_port(host: str, port: int, timeout: float = 4.0) -> None:
    end = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < end:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.6)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        except Exception as exc:
            last = exc
            await asyncio.sleep(0.12)
    raise RuntimeError(f'Local Xray SOCKS port did not become ready: {last or "timeout"}')


async def start_xray_gateway(uri: str, local_port: int | None = None) -> RuntimeConnection:
    if not Path(XRAY_BIN).is_file() or not os.access(XRAY_BIN, os.X_OK):
        raise RuntimeError('Xray core is not installed in this image. Rebuild D BOT with the updated Dockerfile.')
    port = int(local_port or _free_local_port())
    config = build_xray_config(uri, port)
    tempdir = tempfile.TemporaryDirectory(prefix='dbot-xray-')
    config_path = Path(tempdir.name) / 'config.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    process = await asyncio.create_subprocess_exec(
        XRAY_BIN, 'run', '-c', str(config_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await _wait_port('127.0.0.1', port, timeout=5.0)
    except Exception:
        stderr = ''
        if process.returncode is None:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            _, err = await asyncio.wait_for(process.communicate(), timeout=2)
            stderr = err.decode('utf-8', errors='replace').strip()[-800:]
        except Exception:
            pass
        tempdir.cleanup()
        raise RuntimeError(stderr or 'Xray could not start with this V2 link.')
    return RuntimeConnection(
        mode=MODE_V2RAY,
        proxy_url=f'socks5://127.0.0.1:{port}',
        xray_process=process,
        xray_tempdir=tempdir,
        description=f'{detect_v2_protocol(uri)} via local Xray',
    )


async def prepare_runtime_connection(config: dict[str, Any] | None = None, *, test_mode: bool = False) -> RuntimeConnection:
    cfg = config or await get_connection_config(include_secrets=True)
    mode = str(cfg.get('mode') or MODE_DIRECT).lower()
    if mode == MODE_DIRECT:
        return RuntimeConnection(mode=MODE_DIRECT, description='Direct Telegram connection')
    if mode == MODE_PROXY:
        proxy = cfg.get('proxy') or {}
        url = _proxy_url(proxy.get('scheme', 'socks5'), proxy.get('host', ''), proxy.get('port', '1080'), proxy.get('username', ''), proxy.get('password', ''))
        return RuntimeConnection(mode=mode, proxy_url=url, description=f'{str(proxy.get("scheme") or "proxy").upper()} proxy')
    if mode == MODE_MIKROTIK:
        mt = cfg.get('mikrotik') or {}
        url = _proxy_url('socks5', mt.get('host', ''), mt.get('port', '1080'), mt.get('username', ''), mt.get('password', ''))
        return RuntimeConnection(mode=mode, proxy_url=url, description='MikroTik SOCKS5')
    if mode == MODE_V2RAY:
        uri = str((cfg.get('v2ray') or {}).get('uri') or '').strip()
        if not uri:
            raise ValueError('V2 share link is required.')
        # Fixed port in the bot container; random port for one-off tests in the API container.
        return await start_xray_gateway(uri, None if test_mode else DEFAULT_LOCAL_SOCKS_PORT)
    raise ValueError('Unknown Telegram connection mode.')


async def prepare_shared_runtime_connection(config: dict[str, Any] | None = None) -> RuntimeConnection:
    """Build a session route for additional bots in the main bot process.

    The primary bot owns the V2/Xray process on 127.0.0.1:10809. Secondary bots
    reuse that SOCKS endpoint instead of trying to launch another Xray instance.
    """
    cfg = config or await get_connection_config(include_secrets=True)
    mode = str(cfg.get('mode') or MODE_DIRECT).lower()
    if mode == MODE_V2RAY:
        return RuntimeConnection(
            mode=MODE_V2RAY,
            proxy_url=f'socks5://127.0.0.1:{DEFAULT_LOCAL_SOCKS_PORT}',
            description='V2 via shared local Xray',
        )
    return await prepare_runtime_connection(cfg, test_mode=False)


async def build_telegram_session(runtime: RuntimeConnection) -> AiohttpSession:
    return AiohttpSession(
        proxy=runtime.proxy_url,
        timeout=max(float(settings.TELEGRAM_HTTP_TIMEOUT_SECONDS or 20.0), 5.0),
        limit=max(int(settings.TELEGRAM_HTTP_CONNECTION_LIMIT or 100), 20),
    )


async def test_telegram_connection(config: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    runtime = await prepare_runtime_connection(config, test_mode=True)
    session: AiohttpSession | None = None
    bot: Bot | None = None
    try:
        session = await build_telegram_session(runtime)
        bot = Bot(token=settings.BOT_TOKEN, session=session)
        me = await asyncio.wait_for(bot.get_me(), timeout=max(float(settings.TELEGRAM_HTTP_TIMEOUT_SECONDS or 20.0), 8.0))
        latency = int((time.monotonic() - started) * 1000)
        return {
            'ok': True,
            'latency_ms': latency,
            'message': f'Telegram connected as @{me.username or me.id} via {runtime.description}.',
            'bot_username': me.username or '',
            'mode': runtime.mode,
        }
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
        elif session is not None:
            try:
                await session.close()
            except Exception:
                pass
        await runtime.close()


async def merge_connection_payload(payload: dict[str, str]) -> dict[str, Any]:
    """Overlay form values on saved connection settings without persisting them."""
    current = await get_connection_config(include_secrets=True)
    mode = str(payload.get('mode') or current.get('mode') or MODE_DIRECT).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError('Invalid connection mode.')

    proxy = dict(current.get('proxy') or {})
    for form_key, target_key in (
        ('proxy_scheme', 'scheme'), ('proxy_host', 'host'), ('proxy_port', 'port'),
        ('proxy_username', 'username'), ('proxy_password', 'password'),
    ):
        if form_key in payload and str(payload.get(form_key) or '').strip():
            proxy[target_key] = str(payload.get(form_key) or '').strip()

    v2 = dict(current.get('v2ray') or {})
    if 'v2_uri' in payload and str(payload.get('v2_uri') or '').strip():
        v2['uri'] = str(payload.get('v2_uri') or '').strip()

    mt = dict(current.get('mikrotik') or {})
    for form_key, target_key in (
        ('mikrotik_host', 'host'), ('mikrotik_port', 'port'),
        ('mikrotik_username', 'username'), ('mikrotik_password', 'password'),
    ):
        if form_key in payload and str(payload.get(form_key) or '').strip():
            mt[target_key] = str(payload.get(form_key) or '').strip()

    return {'mode': mode, 'proxy': proxy, 'v2ray': v2, 'mikrotik': mt}


async def save_connection_settings(payload: dict[str, str]) -> dict[str, Any]:
    current = await get_connection_config(include_secrets=True)
    mode = str(payload.get('mode') or current.get('mode') or MODE_DIRECT).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError('Invalid connection mode.')

    proxy = dict(current.get('proxy') or {})
    proxy.update({
        'scheme': str(payload.get('proxy_scheme') or proxy.get('scheme') or 'socks5').strip().lower(),
        'host': str(payload.get('proxy_host') or proxy.get('host') or '').strip(),
        'port': str(payload.get('proxy_port') or proxy.get('port') or '1080').strip(),
        'username': str(payload.get('proxy_username') or proxy.get('username') or '').strip(),
    })
    if 'proxy_password' in payload and str(payload.get('proxy_password') or ''):
        proxy['password'] = str(payload.get('proxy_password') or '')

    v2 = dict(current.get('v2ray') or {})
    if 'v2_uri' in payload and str(payload.get('v2_uri') or '').strip():
        v2['uri'] = str(payload.get('v2_uri') or '').strip()

    mt = dict(current.get('mikrotik') or {})
    mt.update({
        'host': str(payload.get('mikrotik_host') or mt.get('host') or '').strip(),
        'port': str(payload.get('mikrotik_port') or mt.get('port') or '1080').strip(),
        'username': str(payload.get('mikrotik_username') or mt.get('username') or '').strip(),
    })
    if 'mikrotik_password' in payload and str(payload.get('mikrotik_password') or ''):
        mt['password'] = str(payload.get('mikrotik_password') or '')

    candidate = {'mode': mode, 'proxy': proxy, 'v2ray': v2, 'mikrotik': mt}
    # Validate only the currently selected mode. This keeps saved fallback profiles intact.
    if mode == MODE_PROXY:
        _proxy_url(proxy.get('scheme', ''), proxy.get('host', ''), proxy.get('port', ''), proxy.get('username', ''), proxy.get('password', ''))
    elif mode == MODE_MIKROTIK:
        _proxy_url('socks5', mt.get('host', ''), mt.get('port', ''), mt.get('username', ''), mt.get('password', ''))
    elif mode == MODE_V2RAY:
        uri = str(v2.get('uri') or '').strip()
        if not uri:
            raise ValueError('V2 share link is required.')
        parse_v2_link(uri)

    revision = f'{int(time.time() * 1000)}'
    pairs = {
        KEY_MODE: mode,
        KEY_REVISION: revision,
        KEY_PROXY_SCHEME: str(proxy.get('scheme') or 'socks5'),
        KEY_PROXY_HOST: str(proxy.get('host') or ''),
        KEY_PROXY_PORT: str(proxy.get('port') or '1080'),
        KEY_PROXY_USERNAME: str(proxy.get('username') or ''),
        KEY_MIKROTIK_HOST: str(mt.get('host') or ''),
        KEY_MIKROTIK_PORT: str(mt.get('port') or '1080'),
        KEY_MIKROTIK_USERNAME: str(mt.get('username') or ''),
    }
    async with SessionLocal() as session:
        for key, value in pairs.items():
            await session.merge(Setting(key=key, value=value))
        if str(proxy.get('password') or ''):
            await session.merge(Setting(key=KEY_PROXY_PASSWORD, value=encrypt_text(str(proxy.get('password') or ''))))
        if str(v2.get('uri') or ''):
            await session.merge(Setting(key=KEY_V2_URI, value=encrypt_text(str(v2.get('uri') or ''))))
        if str(mt.get('password') or ''):
            await session.merge(Setting(key=KEY_MIKROTIK_PASSWORD, value=encrypt_text(str(mt.get('password') or ''))))
        await session.commit()
    return await get_connection_config(include_secrets=False)


async def save_test_result(status: str, message: str, latency_ms: int | None = None) -> None:
    async with SessionLocal() as session:
        await session.merge(Setting(key=KEY_LAST_TEST_STATUS, value=str(status or '')))
        await session.merge(Setting(key=KEY_LAST_TEST_MESSAGE, value=str(message or '')[:1000]))
        await session.merge(Setting(key=KEY_LAST_TEST_AT, value=_utc_now_iso()))
        await session.merge(Setting(key=KEY_LAST_TEST_LATENCY, value='' if latency_ms is None else str(int(latency_ms))))
        await session.commit()


async def connection_revision() -> str:
    async with SessionLocal() as session:
        item = await session.get(Setting, KEY_REVISION)
        return str(item.value or '') if item else ''


async def connection_revision_watcher(dispatcher: Any, initial_revision: str, interval_seconds: float = 4.0) -> None:
    """Stop polling when Connection settings change.

    Docker's restart policy then starts the bot process again, which rebuilds the
    Telegram client session with the newly selected direct/proxy/Xray route.
    """
    baseline = str(initial_revision or '')
    while True:
        await asyncio.sleep(max(interval_seconds, 2.0))
        try:
            current = await connection_revision()
            if current and current != baseline:
                await dispatcher.stop_polling()
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection reload monitoring must never interrupt the bot.
            continue
