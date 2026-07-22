
from __future__ import annotations

import html, secrets, subprocess, re, json, os, shutil, tempfile, asyncio, logging, hmac, hashlib
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile, File, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from sqlalchemy import select, func, update, delete, String, text

from app.core.config import settings
from app.core.security import encrypt_text, decrypt_text, hash_password, verify_password, is_password_hash
from app.database.session import SessionLocal
from app.database.models import (
    User, Server, ServerCategory, Plan, PaymentCard, DiscountCode,
    ResellerAccount, ResellerAccessRequest, Ticket, TicketMessage, Order, ClientService, ResellerPackage, Setting, DiscountUsage,
    ResellerBuildConfig, ResellerTopupRequest, WalletTransaction, TestAccountUsage, OpenVPNProfile, ResellerServiceActivity
)
from app.jobs.server_sync import refresh_server_inbounds
from app.services.xui_service import XuiService
from app.services.mikrotik_service import MikroTikService
from app.services.reseller_service import reconcile_reseller_accounting, remaining_bytes, repair_reseller_services_from_panels
from app.database.defaults import WELCOME_TEXT_DEFAULT
from app.bot.keyboards.common import BUTTON_DEFAULTS, button_text_key, button_enabled_key

router = APIRouter(tags=['web-admin'])
logger = logging.getLogger(__name__)
PAGE_SIZE = 50
SESSION_MINUTES = 30
WARN_BEFORE_MINUTES = 5
_sessions: dict[str, dict[str, Any]] = {}
_failed_logins: dict[str, dict[str, Any]] = {}


def _safe_next_url(value: str | None) -> str:
    raw = (value or '/admin').strip() or '/admin'
    # Avoid protocol-relative redirects such as //attacker.example and any absolute URL.
    if raw.startswith('//') or raw.startswith('\\') or '://' in raw:
        return '/admin'
    if not raw.startswith('/'):
        return '/admin'
    if raw.startswith('/login'):
        return '/admin'
    return raw


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
    return forwarded or (request.client.host if request.client else 'unknown')


def _login_key(request: Request, username: str) -> str:
    return f"{_client_ip(request)}:{(username or '').strip().lower()}"


def _login_blocked(request: Request, username: str) -> bool:
    data = _failed_logins.get(_login_key(request, username))
    if not data:
        return False
    until = data.get('locked_until')
    if until and until > _now():
        return True
    if until and until <= _now():
        _failed_logins.pop(_login_key(request, username), None)
    return False


def _record_login_failure(request: Request, username: str) -> None:
    key = _login_key(request, username)
    data = _failed_logins.setdefault(key, {'count': 0, 'first_at': _now(), 'locked_until': None})
    data['count'] = int(data.get('count') or 0) + 1
    attempts = max(3, int(settings.ADMIN_MAX_LOGIN_ATTEMPTS or 8))
    if data['count'] >= attempts:
        data['locked_until'] = _now() + timedelta(seconds=max(60, int(settings.ADMIN_LOGIN_LOCK_SECONDS or 900)))
    logger.warning('Admin login failed ip=%s username=%s count=%s', _client_ip(request), username, data['count'])


def _record_login_success(request: Request, username: str) -> None:
    _failed_logins.pop(_login_key(request, username), None)


def _request_is_same_origin(request: Request) -> bool:
    host = (request.headers.get('host') or '').split(':')[0].lower()
    for header in ('origin', 'referer'):
        value = request.headers.get(header) or ''
        if not value:
            continue
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(value)
            if parsed.netloc and parsed.netloc.split(':')[0].lower() != host:
                return False
        except Exception:
            return False
    sec_fetch_site = (request.headers.get('sec-fetch-site') or '').lower()
    if sec_fetch_site in {'cross-site', 'same-site'}:
        return False
    return True


def _session_csrf_token(request: Request) -> str:
    token = request.cookies.get('dbot_admin_token')
    if not token or token not in _sessions:
        return ''
    return str(_sessions[token].get('csrf') or '')


def _verify_csrf(request: Request) -> None:
    # HTML form posts and JS actions must carry a session-bound token. GET read-only
    # requests are protected by SameSite=Strict + same-origin checks in _auth_user.
    expected = _session_csrf_token(request)
    supplied = request.headers.get('x-csrf-token') or request.query_params.get('csrf') or ''
    if expected and hmac.compare_digest(expected, supplied):
        return
    raise HTTPException(status_code=403, detail='CSRF validation failed')


def _backup_secret() -> str:
    return (settings.BACKUP_SIGNING_SECRET or settings.FERNET_KEY or settings.BOT_TOKEN or '').strip()


def _canonical_backup(data: dict[str, Any]) -> bytes:
    clone = dict(data)
    meta = dict(clone.get('meta') or {})
    meta.pop('signature', None)
    clone['meta'] = meta
    return json.dumps(clone, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _sign_backup(data: dict[str, Any]) -> str:
    secret = _backup_secret()
    if not secret:
        return ''
    return hmac.new(secret.encode('utf-8'), _canonical_backup(data), hashlib.sha256).hexdigest()


def _validate_backup_payload(data: Any) -> None:
    if not isinstance(data, dict):
        raise ValueError('Invalid backup structure')
    meta = data.get('meta') or {}
    if not isinstance(meta, dict) or meta.get('app') != 'D BOT':
        raise ValueError('This file is not a D BOT backup')
    allowed = {key for key, _ in _backup_models()} | {'meta'}
    unknown = set(data.keys()) - allowed
    if unknown:
        raise ValueError('Backup contains unsupported sections')
    for key, model in _backup_models():
        rows = data.get(key, [])
        if rows is None:
            continue
        if not isinstance(rows, list):
            raise ValueError(f'Backup section {key} must be a list')
        allowed_cols = set(model.__table__.columns.keys())
        for row in rows[:5_000]:
            if not isinstance(row, dict):
                raise ValueError(f'Backup section {key} contains invalid rows')
            if len(set(row.keys()) - allowed_cols) > 25:
                raise ValueError(f'Backup section {key} has invalid columns')
    if settings.BACKUP_REQUIRE_SIGNATURE:
        sig = str(meta.get('signature') or '')
        if not sig or not hmac.compare_digest(sig, _sign_backup(data)):
            raise ValueError('Backup signature is missing or invalid')


def _now() -> datetime:
    return datetime.utcnow()


def _login_url(next_url: str = '/admin') -> str:
    return '/login?next=' + _safe_next_url(next_url)


def _cleanup_sessions() -> None:
    now = _now()
    expired = [token for token, data in _sessions.items() if data['expires_at'] <= now]
    for token in expired:
        _sessions.pop(token, None)


def _auth_user(request: Request) -> str:
    _cleanup_sessions()
    is_api = request.url.path.startswith('/api/') or request.url.path.startswith('/admin/api/')
    if not _request_is_same_origin(request):
        raise HTTPException(status_code=403, detail='Cross-site admin request blocked')
    token = request.cookies.get('dbot_admin_token')
    if not token or token not in _sessions:
        if is_api:
            raise HTTPException(status_code=401, detail='Admin session expired')
        raise HTTPException(status_code=307, headers={'Location': _login_url(str(request.url.path))})
    data = _sessions[token]
    if data['expires_at'] <= _now():
        _sessions.pop(token, None)
        if is_api:
            raise HTTPException(status_code=401, detail='Admin session expired')
        raise HTTPException(status_code=307, headers={'Location': _login_url(str(request.url.path))})
    if request.method.upper() in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        _verify_csrf(request)
    return data['username']


def e(v: Any) -> str:
    return html.escape(str(v if v is not None else '-'))


def gb(bytes_value: int | None) -> str:
    return f'{(int(bytes_value or 0)/1024**3):,.1f} GB'


def money(v: int | None) -> str:
    return f'{int(v or 0):,}'


def percent_change(current: Any, previous: Any) -> float:
    """Return safe percentage change for dashboards."""
    try:
        cur = float(current or 0)
        prev = float(previous or 0)
    except Exception:
        return 0.0
    if prev == 0:
        return 100.0 if cur > 0 else 0.0
    return round(((cur - prev) / abs(prev)) * 100, 1)


def user_wallet_total(u: Any) -> int:
    return int(getattr(u, 'wallet_balance', 0) or 0)




def _service_type_active_key(key: str) -> str:
    return f"{key}:active"


def _is_service_type_row(row: Any) -> bool:
    key = str(getattr(row, 'key', row) or '')
    return key.startswith('service_type:custom:') and not key.endswith(':active')


def _service_type_is_active(settings_map: dict[str, str], key: str) -> bool:
    return str(settings_map.get(_service_type_active_key(key), '1')) != '0'


def _ordered_service_types(rows: list[Any], order_value: str = '') -> list[Any]:
    order = [x for x in (order_value or '').split('|') if x]
    rank = {k: i for i, k in enumerate(order)}
    return sorted(rows, key=lambda x: (rank.get(str(x.key), 10_000), str(x.key)))

def pdf_escape(v: Any) -> str:
    return str(v if v is not None else '').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def _pdf_display_text(value: Any) -> str:
    """Prepare mixed Persian/English text for ReportLab. Falls back safely."""
    raw = str(value if value is not None else '')
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(raw))
    except Exception:
        return raw


def unicode_pdf(title: str, lines: list[str]) -> bytes:
    """Unicode PDF generator for Persian/English sales reports."""
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm

        font_candidates = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/local/share/fonts/DejaVuSans.ttf',
        ]
        font_name = 'Helvetica'
        for font_path in font_candidates:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
                    font_name = 'DejaVuSans'
                    break
                except Exception:
                    pass
        buff = BytesIO()
        c = canvas.Canvas(buff, pagesize=A4)
        width, height = A4
        margin_x = 16 * mm
        y = height - 18 * mm
        c.setTitle(title)
        c.setFont(font_name, 15)
        c.drawString(margin_x, y, _pdf_display_text(title))
        y -= 11 * mm
        c.setFont(font_name, 8.5)
        for line in lines:
            text_line = _pdf_display_text(line)
            if y < 18 * mm:
                c.showPage()
                c.setFont(font_name, 8.5)
                y = height - 18 * mm
            c.drawString(margin_x, y, text_line[:185])
            y -= 5.7 * mm
        c.save()
        return buff.getvalue()
    except Exception:
        return simple_pdf(title, lines)



def sales_report_pdf(title: str, range_label: str, total: int, rows: list[dict[str, Any]]) -> bytes:
    """Create a styled Unicode PDF report for sales/orders."""
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.lib import colors

        font_candidates = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/local/share/fonts/DejaVuSans.ttf',
        ]
        font_name = 'Helvetica'
        for font_path in font_candidates:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
                    font_name = 'DejaVuSans'
                    break
                except Exception:
                    pass

        buff = BytesIO()
        page_w, page_h = landscape(A4)
        c = canvas.Canvas(buff, pagesize=(page_w, page_h))
        c.setTitle(title)
        margin = 12 * mm
        row_h = 9.4 * mm
        header_h = 9.6 * mm
        cols = [20*mm, 32*mm, 45*mm, 65*mm, 33*mm, 26*mm, 42*mm]
        headers = ['Order', 'Date', 'User', 'Plan', 'Payment', 'Status', 'Amount']
        table_x = margin
        table_w = sum(cols)

        def fit_text(text: Any, max_chars: int) -> str:
            raw = str(text if text is not None else '-')
            return raw if len(raw) <= max_chars else raw[:max_chars - 1] + '…'

        def draw_header(page_no: int):
            c.setFillColor(colors.HexColor('#020617'))
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
            c.setFillColor(colors.HexColor('#0f172a'))
            c.roundRect(margin, page_h - 28*mm, table_w, 18*mm, 5*mm, fill=1, stroke=0)
            c.setFillColor(colors.HexColor('#7c3aed'))
            c.roundRect(margin, page_h - 28*mm, 42*mm, 18*mm, 5*mm, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont(font_name, 16)
            c.drawString(margin + 6*mm, page_h - 18*mm, _pdf_display_text(title))
            c.setFont(font_name, 8.5)
            c.setFillColor(colors.HexColor('#cbd5e1'))
            c.drawRightString(margin + table_w - 6*mm, page_h - 16.2*mm, _pdf_display_text(f'Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}'))
            c.drawRightString(margin + table_w - 6*mm, page_h - 22.0*mm, _pdf_display_text(f'Page {page_no}'))

            card_y = page_h - 43*mm
            card_w = (table_w - 8*mm) / 3
            cards = [('Range', range_label), ('Total sales', f'{money(total)} Toman'), ('Orders', str(len(rows)))]
            for idx, (k, v) in enumerate(cards):
                x = margin + idx * (card_w + 4*mm)
                c.setFillColor(colors.HexColor('#0b1120'))
                c.roundRect(x, card_y, card_w, 11*mm, 3*mm, fill=1, stroke=0)
                c.setStrokeColor(colors.HexColor('#334155'))
                c.roundRect(x, card_y, card_w, 11*mm, 3*mm, fill=0, stroke=1)
                c.setFillColor(colors.HexColor('#94a3b8'))
                c.setFont(font_name, 7.6)
                c.drawString(x + 4*mm, card_y + 6.8*mm, _pdf_display_text(k))
                c.setFillColor(colors.white)
                c.setFont(font_name, 9.5)
                c.drawString(x + 4*mm, card_y + 2.7*mm, _pdf_display_text(fit_text(v, 42)))

            th_y = page_h - 58*mm
            c.setFillColor(colors.HexColor('#312e81'))
            c.roundRect(table_x, th_y, table_w, header_h, 3*mm, fill=1, stroke=0)
            c.setFont(font_name, 8.2)
            c.setFillColor(colors.white)
            x = table_x
            for i, h in enumerate(headers):
                c.drawString(x + 2.5*mm, th_y + 3.2*mm, _pdf_display_text(h))
                x += cols[i]
            return th_y - row_h

        y = draw_header(1)
        page_no = 1
        max_y = 14 * mm
        for idx, row in enumerate(rows):
            if y < max_y:
                c.showPage()
                page_no += 1
                y = draw_header(page_no)
            c.setFillColor(colors.HexColor('#0f172a') if idx % 2 == 0 else colors.HexColor('#111827'))
            c.rect(table_x, y, table_w, row_h, fill=1, stroke=0)
            c.setStrokeColor(colors.HexColor('#1e293b'))
            c.line(table_x, y, table_x + table_w, y)
            values = [row.get('order'), row.get('date'), row.get('user'), row.get('plan'), row.get('payment'), row.get('status'), row.get('amount')]
            limits = [10, 17, 24, 38, 18, 14, 22]
            x = table_x
            c.setFont(font_name, 7.6)
            for i, val in enumerate(values):
                c.setFillColor(colors.HexColor('#e5e7eb') if i != 5 else (colors.HexColor('#86efac') if str(val).lower() in {'paid','approved','completed'} else colors.HexColor('#fde68a')))
                c.drawString(x + 2.5*mm, y + 3.1*mm, _pdf_display_text(fit_text(val, limits[i])))
                x += cols[i]
            y -= row_h
        c.save()
        return buff.getvalue()
    except Exception:
        lines = [f'Range: {range_label}', f'Total: {money(total)} Toman | Orders: {len(rows)}']
        for r in rows:
            lines.append(f"{r.get('order')} | {r.get('date')} | {r.get('user')} | {r.get('plan')} | Payment: {r.get('payment')} | {r.get('status')} | {r.get('amount')}")
        return unicode_pdf(title, lines)

def simple_pdf(title: str, lines: list[str]) -> bytes:
    # ASCII-safe fallback. Unicode reports use unicode_pdf() when ReportLab is available.
    per_page = 44
    pages = []
    all_lines = [title, ''] + [str(x).encode('ascii', 'replace').decode('ascii') for x in lines]
    for idx in range(0, len(all_lines), per_page):
        chunk = all_lines[idx:idx + per_page]
        text_chunks = ['BT', '/F1 10 Tf', '45 795 Td']
        for line in chunk:
            text_chunks.append(f'({pdf_escape(line)[:160]}) Tj')
            text_chunks.append('0 -16 Td')
        text_chunks.append('ET')
        pages.append('\n'.join(text_chunks).encode('latin-1', 'replace'))
    if not pages:
        pages = [b'BT /F1 10 Tf 45 795 Td (No data) Tj ET']

    objects: list[bytes] = []
    page_count = len(pages)
    page_obj_ids = []
    for i in range(page_count):
        page_obj_ids.append(4 + i * 2)
    kids = ' '.join(f'{pid} 0 R' for pid in page_obj_ids)
    objects.append(b'<< /Type /Catalog /Pages 2 0 R >>')
    objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {page_count} >>'.encode())
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    for i, stream in enumerate(pages):
        page_id = 4 + i * 2
        content_id = page_id + 1
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>'.encode())
        objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream')

    out = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    for off in offsets[1:]:
        out += f'{off:010d} 00000 n \n'.encode()
    out += f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return bytes(out)


def _resource_read_meminfo():
    data = {}
    try:
        with open('/proc/meminfo', 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    data[parts[0].rstrip(':')] = int(parts[1]) * 1024
    except Exception:
        pass
    return data

def _resource_fmt_bytes(value):
    try:
        size = float(int(value or 0))
    except Exception:
        size = 0.0
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024
    return f'{size:.1f} TB'

def _resource_stats():
    mem = _resource_read_meminfo()
    ram_total = int(mem.get('MemTotal', 0) or 0)
    ram_avail = int(mem.get('MemAvailable', mem.get('MemFree', 0)) or 0)
    ram_used = max(ram_total - ram_avail, 0)
    ram_pct = round((ram_used / ram_total) * 100, 1) if ram_total else 0.0

    swap_total = int(mem.get('SwapTotal', 0) or 0)
    swap_free = int(mem.get('SwapFree', 0) or 0)
    swap_used = max(swap_total - swap_free, 0)
    swap_pct = round((swap_used / swap_total) * 100, 1) if swap_total else 0.0

    try:
        load1 = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        cpu_pct = round(min(max((load1 / cores) * 100, 0), 100), 1)
        cpu_detail = f'Load {load1:.2f} / {cores} cores'
    except Exception:
        cpu_pct = 0.0
        cpu_detail = 'Load unavailable'

    try:
        disk = shutil.disk_usage('/')
        ssd_total = int(disk.total or 0)
        ssd_used = int(disk.used or 0)
        ssd_pct = round((ssd_used / ssd_total) * 100, 1) if ssd_total else 0.0
    except Exception:
        ssd_total = 0
        ssd_used = 0
        ssd_pct = 0.0

    return [
        {'title': 'Ram', 'value': f'{ram_pct:.1f}%', 'detail': f'{_resource_fmt_bytes(ram_used)} / {_resource_fmt_bytes(ram_total)}', 'percent': ram_pct, 'icon': '🧠', 'cls': 'purple'},
        {'title': 'CPU', 'value': f'{cpu_pct:.1f}%', 'detail': cpu_detail, 'percent': cpu_pct, 'icon': '⚙️', 'cls': 'blue'},
        {'title': 'Swap', 'value': f'{swap_pct:.1f}%', 'detail': f'{_resource_fmt_bytes(swap_used)} / {_resource_fmt_bytes(swap_total)}', 'percent': swap_pct, 'icon': '🔁', 'cls': 'orange'},
        {'title': 'SSD', 'value': f'{ssd_pct:.1f}%', 'detail': f'{_resource_fmt_bytes(ssd_used)} / {_resource_fmt_bytes(ssd_total)}', 'percent': ssd_pct, 'icon': '💾', 'cls': 'green'},
    ]

def _resource_card(metric):
    try:
        pct = max(0, min(100, float(metric.get('percent') or 0)))
    except Exception:
        pct = 0
    title = e(metric.get('title') or '')
    value = e(metric.get('value') or '0.0%')
    detail = e(metric.get('detail') or '-')
    icon = e(metric.get('icon') or '•')
    cls = e(metric.get('cls') or 'blue')
    return (
        f'<div class="resource-card {cls}" style="--p:{pct:.1f}">'
        f'<div class="resource-title">{title}</div>'
        f'<div class="resource-ring" aria-label="{title} {pct:.1f}%"><span>{pct:.0f}%</span></div>'
        f'<div class="resource-detail">{detail}</div>'
        f'<div class="resource-bar"><span style="width:{pct:.1f}%"></span></div>'
        f'</div>'
    )

def dashboard_resource_cards():
    try:
        return ''.join(_resource_card(m) for m in _resource_stats())
    except Exception:
        return '<div class="empty-state">Server resources could not be loaded.</div>'


async def db_setting(key: str, default: str = '') -> str:
    async with SessionLocal() as s:
        row = await s.get(Setting, key)
        return row.value if row else default


async def set_db_setting(session, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def _parse_id_order(value: str | None) -> list[int]:
    ids: list[int] = []
    for part in str(value or '').replace('[', '').replace(']', '').replace(' ', '').split(','):
        if not part:
            continue
        try:
            iid = int(part)
        except Exception:
            continue
        if iid > 0 and iid not in ids:
            ids.append(iid)
    return ids


def _sort_by_saved_order(items, order_value: str | None):
    saved = _parse_id_order(order_value)
    rank = {item_id: idx for idx, item_id in enumerate(saved)}
    return sorted(items, key=lambda x: (rank.get(getattr(x, 'id', 0), 10_000_000), int(getattr(x, 'price_irt', 0) or 0), int(getattr(x, 'id', 0) or 0)))


def is_ajax(request: Request) -> bool:
    return (request.headers.get('x-requested-with') == 'fetch'
            or 'application/json' in request.headers.get('accept','')
            or request.query_params.get('ajax') == '1')


def ok(request: Request, redirect: str, message: str = 'Done'):
    if is_ajax(request):
        return JSONResponse({'ok': True, 'message': message, 'redirect': redirect})
    return RedirectResponse(redirect, 303)


def fail(request: Request, message: str, status: int = 400):
    if is_ajax(request):
        return JSONResponse({'ok': False, 'message': message}, status_code=status)
    raise HTTPException(status_code=status, detail=message)


def field(name: str, label: str, typ: str = 'text', value: Any = '', extra: str = '') -> str:
    return f'<div class="{extra}"><label data-fa="{e(label)}" data-en="{e(label)}">{e(label)}</label><input type="{typ}" name="{e(name)}" value="{e(value)}"></div>'



def option_rows(items, selected=None, empty_label='Select') -> str:
    html_out = f'<option value="0">{e(empty_label)}</option>'
    for item in items:
        val = getattr(item, 'id', item)
        label = getattr(item, 'name', None) or getattr(item, 'title', None) or str(val)
        sel = ' selected' if str(val) == str(selected or '') else ''
        html_out += f'<option value="{e(val)}"{sel}>{e(label)}</option>'
    return html_out


def select_field(name: str, label: str, options: list[tuple[str, str]], selected: Any='', extra: str='') -> str:
    opts = ''.join(
        f'<option value="{e(v)}" {"selected" if str(v)==str(selected) else ""}>{e(t)}</option>'
        for v, t in options
    )
    return f'<div class="{extra}"><label data-fa="{e(label)}" data-en="{e(label)}">{e(label)}</label><select name="{e(name)}">{opts}</select></div>'

def server_scope(server) -> str:
    return str((getattr(server, "meta", None) or {}).get("scope") or "public")

def server_scope_text(server) -> str:
    scope = server_scope(server)
    if scope == "reseller":
        return "Reseller"
    if scope == "all":
        return "Public + Reseller"
    return "Public"


def modal(mid: str, title_fa: str, title_en: str, inner: str) -> str:
    return f'''<div class="modal" id="{mid}"><div class="modal-card"><div class="modal-head"><h2 data-fa="{e(title_fa)}" data-en="{e(title_en)}">{e(title_fa)}</h2><button type="button" class="ghost" onclick="closeModal('{mid}')">✕</button></div>{inner}</div></div>'''


def jalali_month_end_label(now: datetime):
    def gregorian_to_jalali(gy:int, gm:int, gd:int):
        gdm=[0,31,59,90,120,151,181,212,243,273,304,334]
        if gy>1600: jy=979; gy-=1600
        else: jy=0; gy-=621
        gy2=gy+1 if gm>2 else gy
        days=365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400-80+gd+gdm[gm-1]
        jy+=33*(days//12053); days%=12053; jy+=4*(days//1461); days%=1461
        if days>365: jy+=(days-1)//365; days=(days-1)%365
        if days<186: jm=1+days//31; jd=1+days%31
        else: jm=7+(days-186)//30; jd=1+(days-186)%30
        return jy,jm,jd
    jy,jm,_=gregorian_to_jalali(now.year,now.month,now.day)
    end_day=31 if jm<=6 else (30 if jm<=11 else 29)
    return f'{jy}/{jm:02d}/{end_day:02d}'

NAV=[('/admin','🏠','Dashboard','Dashboard'),('/admin/service-types','🧬','Service Types','Service Types'),('/admin/openvpn-profiles','📄','Profile OpenVPN','Profile OpenVPN'),('/admin/servers','🖥','Servers','Servers'),('/admin/categories','🗂','Categories','Categories'),('/admin/plans','📦','Plans','Plans'),('/admin/payments','💳','Payments','Payments'),('/admin/orders-report','📄','Orders Report','Orders Report'),('/admin/discounts','🎟','Discount Codes','Discount Codes'),('/admin/resellers','🤝','Resellers','Resellers'),('/admin/backup','🧰','Backup','Backup'),('/admin/settings','⚙️','Settings','Settings')]

STYLE = r'''
:root{--bg:#070b16;--bg-soft:#0b1220;--panel:#0f172a;--panel-2:#111c31;--card:#111827;--card-2:#172033;--text:#f8fafc;--muted:#94a3b8;--line:rgba(148,163,184,.16);--primary:#7c3aed;--primary-2:#2563eb;--accent:#06b6d4;--success:#22c55e;--warning:#f59e0b;--danger:#f43f5e;--shadow:0 24px 70px rgba(0,0,0,.34);--soft-shadow:0 14px 38px rgba(2,6,23,.24);--radius:22px}
body[data-theme="theme-1"]{--bg:#070b16;--bg-soft:#0b1220;--panel:#0f172a;--panel-2:#111c31;--card:#111827;--card-2:#172033;--text:#f8fafc;--muted:#94a3b8;--line:rgba(148,163,184,.16);--primary:#7c3aed;--primary-2:#2563eb;--accent:#06b6d4;--success:#22c55e;--warning:#f59e0b;--danger:#f43f5e}
body[data-theme="theme-2"]{--bg:#f6f8fc;--bg-soft:#eef4ff;--panel:#fff;--panel-2:#f8fafc;--card:#fff;--card-2:#f7fbff;--text:#0f172a;--muted:#64748b;--line:rgba(15,23,42,.10);--primary:#2563eb;--primary-2:#7c3aed;--accent:#0ea5e9;--success:#16a34a;--warning:#d97706;--danger:#e11d48;--shadow:0 20px 70px rgba(15,23,42,.11);--soft-shadow:0 12px 34px rgba(15,23,42,.08)}
body[data-theme="theme-3"]{--bg:#080d12;--bg-soft:#0c141c;--panel:#111827;--panel-2:#141f2d;--card:#121a25;--card-2:#172230;--text:#f3f4f6;--muted:#9ca3af;--line:rgba(156,163,175,.16);--primary:#10b981;--primary-2:#14b8a6;--accent:#38bdf8;--success:#22c55e;--warning:#eab308;--danger:#fb7185}
body[data-theme="theme-4"]{--bg:#160b2d;--bg-soft:#1d123a;--panel:#241547;--panel-2:#2b1858;--card:#27164f;--card-2:#321c68;--text:#fff7ff;--muted:#c4b5fd;--line:rgba(196,181,253,.18);--primary:#a855f7;--primary-2:#ec4899;--accent:#22d3ee;--success:#34d399;--warning:#fbbf24;--danger:#fb7185}
body[data-theme="theme-5"]{--bg:#020b1b;--bg-soft:#061529;--panel:#071a33;--panel-2:#0a2242;--card:#081b36;--card-2:#0b274d;--text:#eff6ff;--muted:#93c5fd;--line:rgba(147,197,253,.16);--primary:#2563eb;--primary-2:#0ea5e9;--accent:#38bdf8;--success:#22c55e;--warning:#f97316;--danger:#f43f5e}
body[data-theme="theme-6"]{--bg:#fbfcfe;--bg-soft:#f1f5f9;--panel:#fff;--panel-2:#fff;--card:#fff;--card-2:#f8fafc;--text:#111827;--muted:#64748b;--line:rgba(15,23,42,.12);--primary:#111827;--primary-2:#2563eb;--accent:#14b8a6;--success:#16a34a;--warning:#d97706;--danger:#dc2626;--shadow:0 18px 60px rgba(15,23,42,.09);--soft-shadow:0 10px 28px rgba(15,23,42,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-height:100vh;background:radial-gradient(circle at 15% -10%,color-mix(in srgb,var(--primary) 30%,transparent),transparent 31%),radial-gradient(circle at 90% 5%,color-mix(in srgb,var(--accent) 22%,transparent),transparent 28%),linear-gradient(135deg,var(--bg) 0%,var(--bg-soft) 100%);color:var(--text);font-family:Tahoma,Arial,sans-serif;overflow-x:hidden}body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,rgba(0,0,0,.34),transparent 65%)}a{color:inherit}.shell{min-height:100vh;display:flex;direction:ltr}.sidebar{width:286px;min-width:286px;height:100vh;position:sticky;top:0;background:color-mix(in srgb,var(--panel) 86%,transparent);border-inline-end:1px solid var(--line);box-shadow:18px 0 60px rgba(0,0,0,.18);backdrop-filter:blur(22px);padding:22px 18px;direction:rtl;z-index:20}.brand{display:flex;align-items:center;gap:14px;padding:4px 10px 28px;font-weight:900}.brand .gift{width:48px;height:48px;border-radius:16px;display:grid;place-items:center;background:linear-gradient(145deg,var(--primary),var(--primary-2));box-shadow:0 14px 34px color-mix(in srgb,var(--primary) 34%,transparent);font-size:26px}.brand strong{font-size:26px;line-height:1}.brand small{display:block;color:var(--muted);font-size:13px;margin-top:4px}.nav-group{margin:16px 0}.nav-label{display:flex;align-items:center;justify-content:space-between;color:var(--muted);font-size:12px;padding:0 8px 8px}.navitem{display:flex;align-items:center;gap:12px;text-decoration:none;border-radius:16px;padding:12px 13px;margin:5px 0;color:var(--muted);border:1px solid transparent;transition:.22s ease;font-size:14px}.navitem span{width:28px;height:28px;display:grid;place-items:center;border-radius:10px;background:rgba(148,163,184,.08);color:var(--text)}.navitem b{font-weight:700}.navitem:hover{color:var(--text);background:color-mix(in srgb,var(--card-2) 85%,transparent);border-color:var(--line);transform:translateX(-2px)}.navitem.active{color:#fff;background:linear-gradient(135deg,var(--primary),color-mix(in srgb,var(--primary-2) 76%,transparent));border-color:color-mix(in srgb,var(--primary) 55%,transparent);box-shadow:0 16px 38px color-mix(in srgb,var(--primary) 28%,transparent)}.navitem.active span{background:rgba(255,255,255,.16)}.sidebar-footer{position:absolute;left:18px;right:18px;bottom:18px}.theme-dots{display:flex;gap:9px;align-items:center;background:color-mix(in srgb,var(--card) 74%,transparent);border:1px solid var(--line);border-radius:18px;padding:10px}.theme-btn{width:30px;height:30px;border-radius:50%;border:1px solid var(--line);padding:0;min-width:30px;cursor:pointer}.theme-btn:nth-child(1){background:linear-gradient(135deg,#7c3aed,#2563eb)}.theme-btn:nth-child(2){background:linear-gradient(135deg,#fff,#dbeafe)}.theme-btn:nth-child(3){background:linear-gradient(135deg,#10b981,#111827)}.theme-btn:nth-child(4){background:linear-gradient(135deg,#a855f7,#ec4899)}.theme-btn:nth-child(5){background:linear-gradient(135deg,#020b1b,#38bdf8)}.theme-btn:nth-child(6){background:linear-gradient(135deg,#ffffff,#111827)}.theme-btn.primary,.theme-btn.active{outline:3px solid color-mix(in srgb,var(--primary) 38%,transparent);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 16%,transparent)}.langbox{display:flex;gap:8px;margin-top:12px}.main{direction:rtl;flex:1;min-width:0}.topbar{height:76px;position:sticky;top:0;z-index:15;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:0 30px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 72%,transparent);backdrop-filter:blur(20px)}.top-left,.top-actions{display:flex;align-items:center;gap:12px}.menu-square,.icon-btn{width:46px;height:46px;border-radius:14px;border:1px solid var(--line);background:color-mix(in srgb,var(--card) 74%,transparent);display:grid;place-items:center;box-shadow:var(--soft-shadow)}.searchbox{height:46px;width:min(440px,42vw);display:flex;align-items:center;gap:10px;padding:0 14px;border:1px solid var(--line);border-radius:14px;background:color-mix(in srgb,var(--card) 72%,transparent);color:var(--muted)}.searchbox input{border:0;background:transparent;color:var(--text);outline:0;flex:1;padding:0}.kbd{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:4px 7px}.adminchip{display:flex;align-items:center;gap:12px;border-inline-start:1px solid var(--line);padding-inline-start:18px}.avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(145deg,var(--primary),var(--primary-2));display:grid;place-items:center;box-shadow:0 10px 30px color-mix(in srgb,var(--primary) 26%,transparent);position:relative}.avatar:after{content:"";position:absolute;right:1px;bottom:3px;width:12px;height:12px;background:var(--success);border-radius:50%;border:2px solid var(--panel)}.content{padding:32px;max-width:none;margin:0;width:100%}.page-head{display:flex;align-items:end;justify-content:space-between;margin-bottom:22px}.breadcrumbs{color:var(--muted);font-size:13px;margin-top:8px}h1{font-size:26px;margin:0;letter-spacing:-.5px}h2{font-size:21px;margin:0}h3{margin:0 0 10px}.grid4{display:grid;grid-template-columns:repeat(6,minmax(150px,1fr));gap:18px;margin-bottom:20px}.metric{min-height:168px;padding:20px;border-radius:22px;background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.018)),color-mix(in srgb,var(--card) 92%,transparent);border:1px solid var(--line);box-shadow:var(--soft-shadow);display:flex;flex-direction:column;justify-content:space-between;position:relative;overflow:hidden}.metric:before{content:"";position:absolute;inset:auto -28px -34px auto;width:110px;height:110px;background:radial-gradient(circle,color-mix(in srgb,var(--metric-color,var(--primary)) 30%,transparent),transparent 66%);border-radius:50%}.metric .top{display:flex;align-items:center;justify-content:space-between;gap:12px}.metric .icon{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,var(--metric-color,var(--primary)),color-mix(in srgb,var(--metric-color,var(--primary)) 70%,#111));color:#fff;font-size:22px;box-shadow:0 12px 28px color-mix(in srgb,var(--metric-color,var(--primary)) 28%,transparent)}.metric.purple{--metric-color:#8b5cf6}.metric.blue{--metric-color:#2563eb}.metric.green{--metric-color:#22c55e}.metric.orange{--metric-color:#f59e0b}.metric.pink{--metric-color:#ec4899}.metric.cyan{--metric-color:#06b6d4}.metric .label{font-weight:800;color:var(--text);font-size:14px}.value{font-size:clamp(23px,2vw,32px);font-weight:900;letter-spacing:-.7px;line-height:1.15}.muted{color:var(--muted);font-size:13px}.trend{color:var(--warning);font-size:12px;font-weight:900;display:inline-flex;align-items:center;width:max-content}.trend.up{color:var(--success)}.trend.down{color:var(--danger)}.trend.neutral{color:var(--warning)}.metric .value.monthly-value{font-size:clamp(17px,1.45vw,25px)}.dashboard-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}.panel,.card,.tablebox{border:1px solid var(--line);border-radius:22px;background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.018)),color-mix(in srgb,var(--card) 92%,transparent);box-shadow:var(--soft-shadow);backdrop-filter:blur(18px)}.panel{padding:18px}.panel-head,.headrow{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:16px}.chart-wrap{height:300px;position:relative}.chart-svg{width:100%;height:100%;overflow:visible}.chart-grid line{stroke:var(--line);stroke-dasharray:4 6}.chart-line{fill:none;stroke:var(--primary);stroke-width:4;filter:drop-shadow(0 0 10px color-mix(in srgb,var(--primary) 62%,transparent))}.chart-area{fill:url(#salesGradient);opacity:.65}.orders{display:grid;gap:0}.order-row{display:grid;grid-template-columns:1fr 120px 100px 110px;align-items:center;gap:12px;padding:13px 0;border-bottom:1px solid var(--line)}.order-row:last-child{border-bottom:0}.pill{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:800}.pill.ok{background:color-mix(in srgb,var(--success) 16%,transparent);color:var(--success)}.pill.warn{background:color-mix(in srgb,var(--warning) 17%,transparent);color:var(--warning)}.pill.bad{background:color-mix(in srgb,var(--danger) 17%,transparent);color:var(--danger)}.tablebox{padding:18px;overflow:hidden}.table-scroll{overflow:auto;border-radius:16px}table{width:100%;border-collapse:separate;border-spacing:0;min-width:850px}th,td{padding:15px 14px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-size:12px;background:color-mix(in srgb,var(--card-2) 76%,transparent);font-weight:900}tr:hover td{background:color-mix(in srgb,var(--primary) 5%,transparent)}.card{padding:18px}.gridcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:22px;align-items:stretch}.gridcards:empty:after{content:"No records yet";color:var(--muted);border:1px dashed var(--line);border-radius:22px;padding:30px;display:block}.kvs{display:grid;gap:8px;margin:12px 0}.kv{display:flex;justify-content:space-between;gap:10px;border-bottom:1px dashed var(--line);padding-bottom:8px}.rowactions{display:flex;gap:8px;flex-wrap:wrap}.btn,button{border:1px solid var(--line);background:color-mix(in srgb,var(--card-2) 78%,transparent);color:var(--text);border-radius:13px;padding:10px 14px;font:inherit;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;transition:.2s ease}.btn:hover,button:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--primary) 55%,var(--line));box-shadow:0 12px 28px color-mix(in srgb,var(--primary) 18%,transparent)}.primary{background:linear-gradient(135deg,var(--primary),var(--primary-2));border-color:transparent;color:#fff}.danger{color:#fff;background:linear-gradient(135deg,var(--danger),#be123c);border-color:transparent}.success{color:#fff;background:linear-gradient(135deg,var(--success),#059669);border-color:transparent}.ghost{background:transparent}.badge,.ui-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;background:color-mix(in srgb,var(--card-2) 65%,transparent);padding:7px 11px;color:var(--muted);font-size:12px}.pager{display:flex;justify-content:center;align-items:center;gap:9px;margin-top:18px}.modal{display:none;position:fixed;inset:0;background:rgba(2,6,23,.72);z-index:80;align-items:center;justify-content:center;padding:22px;backdrop-filter:blur(10px)}.modal.open{display:flex}.modal-card{width:min(760px,96vw);max-height:90vh;overflow:auto;border:1px solid var(--line);background:linear-gradient(180deg,rgba(255,255,255,.08),rgba(255,255,255,.025)),var(--panel);border-radius:24px;box-shadow:var(--shadow);padding:22px}.modal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px}label{display:block;color:var(--muted);font-size:13px;margin-bottom:7px}input,select,textarea{width:100%;border:1px solid var(--line);background:color-mix(in srgb,var(--panel-2) 88%,transparent);color:var(--text);border-radius:14px;padding:12px 13px;font:inherit;outline:0}input:focus,select:focus,textarea:focus{border-color:var(--primary);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 14%,transparent)}textarea{min-height:96px}.full{grid-column:1/-1}.toast{position:fixed;left:22px;bottom:22px;z-index:120;display:none;max-width:min(440px,92vw);border:1px solid var(--line);background:var(--panel);border-radius:18px;padding:14px 16px;box-shadow:var(--shadow);transition:opacity 1.1s ease,transform 1.1s ease}.login-wrap{min-height:100vh;display:grid;place-items:center;padding:22px}.login-card{width:min(470px,96vw);border:1px solid var(--line);border-radius:28px;background:linear-gradient(180deg,rgba(255,255,255,.08),rgba(255,255,255,.025)),var(--panel);box-shadow:var(--shadow);padding:32px}.logo{font-size:34px;font-weight:900}.logo span{background:linear-gradient(135deg,var(--primary),var(--accent));-webkit-background-clip:text;color:transparent}[dir="ltr"] .main,[dir="ltr"] .sidebar{direction:ltr}[dir="ltr"] th,[dir="ltr"] td{text-align:left}[dir="ltr"] .kv{direction:ltr}body.sidebar-collapsed .sidebar{display:none} .card{min-height:160px;display:flex;flex-direction:column;justify-content:space-between}.page-head+.gridcards,.headrow+.gridcards{margin-top:16px}@media(max-width:1500px){.grid4{grid-template-columns:repeat(3,minmax(160px,1fr))}.dashboard-grid{grid-template-columns:1fr}}@media(max-width:980px){.shell{display:block}.sidebar{position:relative;width:100%;min-width:0;height:auto}.sidebar-footer{position:static;margin-top:16px}.topbar{position:relative;padding:14px;height:auto;flex-wrap:wrap}.searchbox{width:100%}.content{padding:18px}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))}.order-row{grid-template-columns:1fr 90px}}@media(max-width:640px){.grid4,.gridcards,.formgrid{grid-template-columns:1fr}.metric{aspect-ratio:auto;min-height:150px}.content{padding:14px}.top-actions{display:none}.dashboard-grid{gap:14px}.order-row{grid-template-columns:1fr}.tablebox{padding:12px}}
.server-card{position:relative;overflow:hidden;min-height:290px;background:linear-gradient(145deg,color-mix(in srgb,var(--card) 92%,transparent),color-mix(in srgb,var(--primary) 8%,var(--card-2)))}.server-glow{position:absolute;inset:auto -50px -70px auto;width:170px;height:170px;border-radius:50%;background:radial-gradient(circle,color-mix(in srgb,var(--primary) 42%,transparent),transparent 65%)}.server-flag{font-size:30px;margin-inline-end:8px}.service-dot{display:inline-block;width:12px;height:12px;border-radius:999px;vertical-align:middle;margin-inline-end:7px;box-shadow:0 0 0 3px rgba(255,255,255,.08)}.server-meta{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.server-meta div{background:color-mix(in srgb,var(--panel-2) 78%,transparent);border:1px solid var(--line);border-radius:16px;padding:12px;text-align:center}.server-meta span{display:block;color:var(--muted);font-size:12px}.server-meta b{display:block;margin-top:4px;font-size:18px}.chart-label{fill:var(--muted);font-size:12px}.metric{min-height:150px;aspect-ratio:1.25/1}.metric .icon{box-shadow:0 16px 35px color-mix(in srgb,var(--primary) 28%,transparent)}

/* === v1.3.3 premium SaaS dashboard refinement === */
:root{--ease:cubic-bezier(.2,.8,.2,1)}
body{font-feature-settings:"ss01" 1;}
.sidebar{transition:width .24s var(--ease),transform .24s var(--ease);}
.navitem,.metric,.panel,.card,.tablebox,.modal-card,.btn,button,input,select,textarea{transition:transform .22s var(--ease),box-shadow .22s var(--ease),border-color .22s var(--ease),background .22s var(--ease),opacity .22s var(--ease)}
.metric{aspect-ratio:1.08/1;min-height:unset;padding:18px;border-radius:26px;isolation:isolate}
.metric:after{content:"";position:absolute;inset:1px;border-radius:25px;background:linear-gradient(135deg,color-mix(in srgb,var(--metric-color,var(--primary)) 15%,transparent),transparent 42%);z-index:-1;opacity:.65}
.metric:hover,.card:hover{transform:translateY(-4px);box-shadow:0 24px 70px color-mix(in srgb,var(--metric-color,var(--primary)) 18%,rgba(0,0,0,.18))}
.metric .label{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.metric .value{margin-top:10px;max-width:100%;overflow:hidden;text-overflow:ellipsis}.metric .muted{font-size:12px}.trend{display:inline-flex;align-items:center;gap:6px;align-self:flex-start;border:1px solid color-mix(in srgb,var(--success) 35%,transparent);background:color-mix(in srgb,var(--success) 12%,transparent);border-radius:999px;padding:6px 9px}.trend.down{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 35%,transparent);background:color-mix(in srgb,var(--danger) 12%,transparent)}.trend.neutral{color:var(--muted);border-color:var(--line);background:color-mix(in srgb,var(--card-2) 45%,transparent)}
.grid4{grid-template-columns:repeat(auto-fit,minmax(178px,1fr));align-items:stretch}
.panel,.tablebox,.card{border-radius:28px;background:linear-gradient(180deg,color-mix(in srgb,#fff 7%,transparent),color-mix(in srgb,#fff 2%,transparent)),color-mix(in srgb,var(--card) 91%,transparent)}
.chart-wrap{min-height:330px}.apex-chart{height:330px;width:100%;position:relative}.range-tabs{display:flex;gap:8px;flex-wrap:wrap}.range-tabs button{padding:8px 12px;border-radius:999px}.range-tabs button.active{background:linear-gradient(135deg,var(--primary),var(--primary-2));color:#fff;border-color:transparent}.skeleton{position:relative;overflow:hidden;background:linear-gradient(90deg,color-mix(in srgb,var(--card-2) 75%,transparent),color-mix(in srgb,#fff 12%,transparent),color-mix(in srgb,var(--card-2) 75%,transparent));background-size:240% 100%;animation:skeleton 1.2s infinite linear}.chart-skeleton{height:100%;border-radius:22px}@keyframes skeleton{0%{background-position:200% 0}100%{background-position:-200% 0}}
.table-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0 14px}.table-tools input{max-width:280px}.sortable{cursor:pointer;user-select:none}.sortable:after{content:" ↕";opacity:.45}.export-btn{font-size:13px}.empty-state{border:1px dashed var(--line);border-radius:22px;padding:24px;text-align:center;color:var(--muted);background:color-mix(in srgb,var(--card-2) 45%,transparent)}
.btn.loading,button.loading{pointer-events:none;opacity:.68}.btn.loading:after,button.loading:after{content:"";width:14px;height:14px;border-radius:50%;border:2px solid currentColor;border-top-color:transparent;animation:spin .7s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.btn.rippled,button.rippled{position:relative;overflow:hidden}.ripple{position:absolute;border-radius:50%;background:rgba(255,255,255,.35);transform:none;animation:none;pointer-events:none}@keyframes ripple{to{transform:scale(4);opacity:0}}
.modal.open .modal-card{animation:modalIn .22s var(--ease)}@keyframes modalIn{from{transform:translateY(14px);opacity:0}to{transform:none;opacity:1}}
input:invalid:not(:placeholder-shown),select:invalid:not(:placeholder-shown),textarea:invalid:not(:placeholder-shown){border-color:var(--danger)}
@media(max-width:720px){.metric{aspect-ratio:auto}.grid4{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.metric .icon{width:46px;height:46px}.value{font-size:22px}.range-tabs{width:100%}.range-tabs button{flex:1}.table-tools input{max-width:none;width:100%}}
@media(max-width:460px){.grid4{grid-template-columns:1fr}.metric{min-height:148px}}

.resource-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin:0 0 22px}
.resource-card{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:30px;padding:24px;min-height:190px;background:linear-gradient(180deg,color-mix(in srgb,#fff 8%,transparent),color-mix(in srgb,#fff 2%,transparent)),var(--card);box-shadow:var(--soft-shadow);isolation:isolate}
.resource-card:before{content:"";position:absolute;right:-34px;bottom:-44px;width:150px;height:150px;border-radius:50%;filter:blur(18px);opacity:.36;background:var(--metric-color,var(--primary));z-index:-1}
.resource-card.purple{--metric-color:var(--primary)}
.resource-card.blue{--metric-color:var(--primary-2)}
.resource-card.orange{--metric-color:var(--warning)}
.resource-card.green{--metric-color:var(--success)}
.resource-top{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}
.resource-title{font-size:18px;font-weight:950;letter-spacing:.02em}
.resource-value{font-size:38px;font-weight:1000;line-height:1.05;margin-top:16px}
.resource-icon{width:58px;height:58px;border-radius:20px;display:grid;place-items:center;background:linear-gradient(135deg,var(--metric-color),color-mix(in srgb,var(--metric-color) 45%,#111827));box-shadow:0 18px 42px color-mix(in srgb,var(--metric-color) 35%,transparent);font-size:25px}
.resource-detail{margin-top:18px;color:var(--muted);font-size:13px;font-weight:700}
.resource-bar{height:10px;border-radius:999px;background:color-mix(in srgb,var(--card-2) 72%,transparent);border:1px solid var(--line);overflow:hidden;margin-top:20px}
.resource-bar span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--metric-color),color-mix(in srgb,var(--metric-color) 52%,#fff));box-shadow:0 0 24px color-mix(in srgb,var(--metric-color) 45%,transparent)}
@media(max-width:1100px){.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.resource-grid{grid-template-columns:1fr}.resource-card{min-height:160px}.resource-value{font-size:32px}}

.resource-live-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 10px}
.resource-live-head span{font-weight:950;font-size:18px}
.resource-live-head small{color:var(--muted);font-weight:800}
.resource-grid.updating{opacity:.72;transform:translateY(1px);transition:opacity .18s ease,transform .18s ease}

/* === v1.3.24 responsive card optimization ===
   All dashboard/site cards now scale with viewport width instead of keeping fixed desktop sizes. */
:root{
  --fluid-gap:clamp(10px,1.35vw,22px);
  --fluid-pad:clamp(12px,1.45vw,22px);
  --fluid-radius:clamp(14px,1.4vw,22px);
  --fluid-card-min:clamp(210px,24vw,330px);
}
.content{padding:clamp(14px,2.2vw,32px)}
.grid4{grid-template-columns:repeat(auto-fit,minmax(clamp(135px,15vw,180px),1fr));gap:var(--fluid-gap)}
.dashboard-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:var(--fluid-gap)}
.gridcards{grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--fluid-card-min)),1fr));gap:var(--fluid-gap)}
.resource-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:var(--fluid-gap)}
.metric,.card,.panel,.tablebox,.resource-card,.server-card,.login-card,.modal-card{border-radius:var(--fluid-radius);padding:var(--fluid-pad);max-width:100%;min-width:0}
.metric{min-height:clamp(118px,13.8vw,168px)}
.metric .icon,.resource-icon{width:clamp(38px,4.4vw,54px);height:clamp(38px,4.4vw,54px);font-size:clamp(17px,1.8vw,23px)}
.metric .label,.muted,.kv,.pill,.badge{font-size:clamp(11px,.9vw,14px)}
.value,.resource-value{font-size:clamp(22px,3.1vw,34px);line-height:1.1;overflow-wrap:anywhere}
h1{font-size:clamp(20px,2vw,26px)}h2{font-size:clamp(17px,1.55vw,21px)}h3{font-size:clamp(15px,1.25vw,18px)}
.chart-wrap,.apex-chart{height:clamp(220px,30vw,330px);min-height:220px}
.rowactions{gap:clamp(6px,.8vw,10px)}.btn,button{padding:clamp(8px,.85vw,11px) clamp(10px,1vw,15px);font-size:clamp(12px,.95vw,14px);min-width:0}.btn{white-space:normal;text-align:center}
.kvs{min-width:0}.kv{align-items:flex-start;min-width:0}.kv span,.kv b,.card p,.panel p{min-width:0;overflow-wrap:anywhere;word-break:break-word}.headrow,.panel-head,.page-head{gap:var(--fluid-gap);flex-wrap:wrap}.table-scroll{max-width:100%;overflow:auto;-webkit-overflow-scrolling:touch}
.topbar{height:auto;min-height:clamp(58px,6vw,76px);padding:clamp(10px,1.8vw,30px);gap:clamp(8px,1vw,18px)}.searchbox{width:clamp(180px,32vw,440px);height:clamp(38px,4vw,46px)}.menu-square,.icon-btn{width:clamp(38px,4vw,46px);height:clamp(38px,4vw,46px)}.avatar{width:clamp(38px,4vw,48px);height:clamp(38px,4vw,48px)}
@media(max-width:1280px){.grid4{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.sidebar{width:248px;min-width:248px}.brand strong{font-size:22px}}
@media(max-width:920px){.shell{display:block}.sidebar{position:relative;width:100%;min-width:0;height:auto;padding:14px}.sidebar-footer{position:static;margin-top:12px}.nav-group{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:6px;margin:10px 0}.topbar{position:relative}.top-left{flex:1;min-width:0}.adminchip small,.kbd{display:none}.searchbox{flex:1;width:auto}.dashboard-grid,.gridcards,.resource-grid{grid-template-columns:1fr 1fr}.order-row{grid-template-columns:1fr 80px;align-items:start}.order-row>*{min-width:0;overflow-wrap:anywhere}.modal-card{width:min(94vw,720px);max-height:86vh;overflow:auto}}
@media(max-width:640px){.content{padding:12px}.page-head{align-items:flex-start}.grid4,.dashboard-grid,.gridcards,.resource-grid{grid-template-columns:1fr}.metric{min-height:112px}.metric .top{align-items:flex-start}.topbar{flex-wrap:wrap}.top-actions{width:100%;justify-content:space-between}.searchbox{order:3;width:100%;flex-basis:100%}.adminchip{padding-inline-start:0;border-inline-start:0}.rowactions .btn,.rowactions button{flex:1 1 calc(50% - 8px)}.formgrid{grid-template-columns:1fr}.modal{padding:10px}.modal-card{width:96vw;border-radius:16px}.tablebox{padding:10px}.card,.panel,.resource-card{padding:12px}.chart-wrap,.apex-chart{height:230px}.resource-value,.value{font-size:24px}}
@media(max-width:390px){.rowactions .btn,.rowactions button{flex-basis:100%}.nav-group{grid-template-columns:1fr}.brand .gift{width:40px;height:40px}.brand strong{font-size:20px}.theme-dots{overflow:auto}.chart-wrap,.apex-chart{height:210px}.metric .icon{width:36px;height:36px}}


/* === v1.3.25 deep responsive content scaling ===
   Cards + every inner element now shrink by viewport and by each card's own width. */
:root{
  --card-gap:clamp(8px,1.05vw,18px);
  --card-pad:clamp(9px,1.05vw,20px);
  --card-radius:clamp(12px,1.15vw,24px);
  --text-xs:clamp(8.5px,.64vw,12px);
  --text-sm:clamp(10px,.78vw,13px);
  --text-md:clamp(11px,.9vw,15px);
  --text-lg:clamp(14px,1.15vw,19px);
  --text-xl:clamp(16px,1.65vw,32px);
}
body{font-size:var(--text-md)}
.content{padding:clamp(10px,1.8vw,32px)}
.grid4{grid-template-columns:repeat(auto-fit,minmax(min(100%,clamp(112px,13.2vw,180px)),1fr));gap:var(--card-gap)}
.resource-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,clamp(170px,24vw,310px)),1fr));gap:var(--card-gap)}
.dashboard-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,clamp(270px,43vw,640px)),1fr));gap:var(--card-gap)}
.gridcards{grid-template-columns:repeat(auto-fit,minmax(min(100%,clamp(210px,24vw,340px)),1fr));gap:var(--card-gap)}
.metric,.card,.panel,.tablebox,.resource-card,.server-card,.modal-card,.login-card{container-type:inline-size;min-width:0;max-width:100%;padding:var(--card-pad);border-radius:var(--card-radius)}
.metric{min-height:clamp(96px,11.5vw,168px);gap:clamp(6px,.8vw,12px)}
.metric .top,.resource-top,.server-meta,.order-row,.kv,.headrow,.panel-head{min-width:0}
.metric .top>div:first-child,.resource-top>div:first-child,.card>*,.panel>*,.tablebox>*{min-width:0;max-width:100%}
.metric .label,.resource-label,.card h3,.panel h2,.headrow h2{font-size:var(--text-sm);line-height:1.12;overflow-wrap:anywhere;word-break:break-word}
.metric .label{letter-spacing:-.2px;text-transform:none}.value,.resource-value{font-size:var(--text-xl);line-height:1.02;letter-spacing:-.75px;overflow-wrap:anywhere;word-break:break-word}
.metric .muted,.resource-sub,.muted,.kv span,.kv b,.card p,.panel p,.order-row,.pill,.badge{font-size:var(--text-xs);line-height:1.22;overflow-wrap:anywhere;word-break:break-word}
.trend{display:inline-flex;align-items:center;max-width:100%;width:max-content;font-size:var(--text-xs);line-height:1.12;padding:clamp(3px,.45vw,6px) clamp(5px,.6vw,9px);border-radius:999px;white-space:normal;overflow-wrap:anywhere}
.metric .icon,.resource-icon{flex:0 0 auto;width:clamp(28px,3.6vw,54px);height:clamp(28px,3.6vw,54px);font-size:clamp(13px,1.45vw,22px);box-shadow:0 8px 18px color-mix(in srgb,var(--metric-color,var(--primary)) 22%,transparent)}
.metric:before{width:clamp(70px,8vw,110px);height:clamp(70px,8vw,110px)}
.resource-card{min-height:clamp(118px,15vw,180px)}.resource-bar{height:clamp(5px,.55vw,8px)}
.server-meta{grid-template-columns:repeat(auto-fit,minmax(70px,1fr));gap:clamp(6px,.8vw,10px)}
.kvs{gap:clamp(5px,.65vw,8px);margin:clamp(8px,1vw,12px) 0}.kv{gap:clamp(6px,.8vw,10px)}
.rowactions{gap:clamp(5px,.65vw,8px)}.btn,button,select,input,textarea{font-size:var(--text-sm)}
.btn,button{padding:clamp(6px,.65vw,10px) clamp(8px,.85vw,14px);border-radius:clamp(9px,.9vw,13px);line-height:1.15;min-height:clamp(30px,3vw,40px);min-width:0;white-space:normal;text-align:center}
.range-tabs{gap:clamp(5px,.65vw,8px)}.range-tabs button{font-size:var(--text-xs);padding:clamp(5px,.55vw,8px) clamp(7px,.75vw,12px)}
.chart-wrap,.apex-chart{height:clamp(190px,28vw,330px);min-height:clamp(190px,28vw,330px)}
.apexcharts-text,.apexcharts-legend-text,.apexcharts-tooltip{font-size:var(--text-xs)!important}.apexcharts-xaxis-label,.apexcharts-yaxis-label{font-size:clamp(8px,.62vw,12px)!important}
.order-row{grid-template-columns:minmax(0,1fr) auto auto auto;gap:clamp(6px,.75vw,12px);padding:clamp(8px,.9vw,13px) 0}.order-row b{font-size:var(--text-sm)}
table{min-width:min(850px,160vw)}th,td{font-size:var(--text-xs);padding:clamp(8px,.8vw,15px) clamp(8px,.8vw,14px)}
@container (max-width: 180px){
  .metric .top{gap:5px;align-items:flex-start}.metric .icon{width:28px;height:28px;font-size:13px}.metric .label{font-size:9px}.value{font-size:16px}.metric .muted,.trend{font-size:8.5px}.trend{padding:3px 5px}.card h3{font-size:12px}.btn,button{font-size:10px;padding:6px 7px}
}
@container (max-width: 145px){
  .metric{padding:8px;min-height:88px}.metric .icon{width:24px;height:24px;font-size:12px}.metric .label{font-size:8px}.value{font-size:14px}.metric .muted,.trend{font-size:7.8px}.trend{border-radius:8px;line-height:1.05}
}
@media(max-width:980px){
  .grid4{grid-template-columns:repeat(auto-fit,minmax(min(100%,120px),1fr))}.resource-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr))}.dashboard-grid{grid-template-columns:1fr}.panel-head{align-items:flex-start}.chart-wrap,.apex-chart{height:240px;min-height:240px}.order-row{grid-template-columns:minmax(0,1fr) auto}
}
@media(max-width:640px){
  .grid4{grid-template-columns:repeat(2,minmax(0,1fr))}.resource-grid,.dashboard-grid,.gridcards{grid-template-columns:1fr}.metric{min-height:100px}.metric .icon{width:32px;height:32px}.top-actions{display:flex;flex-wrap:wrap}.chart-wrap,.apex-chart{height:215px;min-height:215px}.order-row{grid-template-columns:1fr}.rowactions .btn,.rowactions button{flex:1 1 calc(50% - 8px)}
}
@media(max-width:390px){
  .grid4{grid-template-columns:1fr 1fr}.metric{padding:8px}.value{font-size:15px}.resource-value{font-size:18px}.metric .label{font-size:8.5px}.metric .muted,.trend{font-size:8px}.chart-wrap,.apex-chart{height:200px;min-height:200px}.range-tabs button{font-size:8.5px;padding:5px 6px}
}


/* === v1.3.26 mobile-first sidebar + compact cards === */
.mobile-sidebar-backdrop{display:none;position:fixed;inset:0;background:rgba(2,6,23,.58);backdrop-filter:blur(4px);z-index:39;opacity:0;transition:opacity .22s ease}
body.sidebar-open .mobile-sidebar-backdrop{display:block;opacity:1}
.menu-square{cursor:pointer;flex:0 0 auto}.sidebar{transition:transform .26s ease,width .22s ease,min-width .22s ease}

/* === v1.3.33 desktop hamburger fixed === */
@media(min-width:761px){
  body.sidebar-desktop-hidden .sidebar{width:0!important;min-width:0!important;padding:0!important;border:0!important;overflow:hidden!important;transform:translateX(-110%)!important;box-shadow:none!important}
  body.sidebar-desktop-hidden .main{flex:1 1 100%;width:100%}
  body.sidebar-desktop-hidden .content{max-width:1800px;margin:0 auto}
}
@media(max-width:760px){body.sidebar-desktop-hidden .sidebar{transform:translateX(-105%)!important}}

body.sidebar-collapsed .sidebar{width:86px;min-width:86px;padding-inline:12px}body.sidebar-collapsed .brand strong,body.sidebar-collapsed .brand small,body.sidebar-collapsed .navitem b,body.sidebar-collapsed .nav-label,body.sidebar-collapsed .sidebar-footer{display:none}body.sidebar-collapsed .navitem{justify-content:center;padding:12px 8px}body.sidebar-collapsed .navitem span{width:36px;height:36px}
.card,.panel,.tablebox,.metric,.resource-card,.server-card{contain:layout paint;overflow:hidden}.card *, .panel *, .tablebox *, .metric *, .resource-card *, .server-card *{max-width:100%;min-width:0}.card h3,.panel h2,.panel h3,.metric .label,.value,.muted,.badge,.pill,.kv b,.kv span,.resource-title,.resource-value{overflow-wrap:anywhere;word-break:break-word}.gridcards{align-items:start}.card{height:auto}.server-card{height:auto}.rowactions{display:flex;flex-wrap:wrap}.rowactions .btn,.rowactions button{flex:1 1 auto}.kvs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,135px),1fr))}.kv{overflow:hidden}.tablebox{overflow:auto;-webkit-overflow-scrolling:touch}.chart-wrap,.apex-chart{overflow:hidden}
@media(max-width:1120px){.grid4{grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr))}.gridcards{grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))}.content{padding:20px}.topbar{padding-inline:18px}}
@media(max-width:760px){
  html{font-size:14px}.shell{display:block}.main{width:100%;min-height:100vh}.content{padding:12px;width:100%;overflow:hidden}.topbar{height:auto;min-height:64px;padding:10px 12px;gap:10px;flex-wrap:wrap}.top-left{width:100%;justify-content:space-between}.top-actions{width:100%;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.adminchip{grid-column:1/-1;justify-content:space-between;border-inline-start:0;padding-inline-start:0}.searchbox{order:2;flex:1;width:auto;min-width:0}.searchbox .kbd{display:none}.menu-square{order:1;width:42px;height:42px}.icon-btn{width:100%;height:40px}.sidebar{position:fixed;top:0;bottom:0;left:0;right:auto;width:min(82vw,320px);min-width:0;height:100dvh;z-index:40;transform:translateX(-105%);border-inline-end:1px solid var(--line);box-shadow:22px 0 70px rgba(0,0,0,.42);overflow-y:auto;padding:18px 14px 120px}body.sidebar-open .sidebar{transform:translateX(0)}body.sidebar-collapsed .sidebar{width:min(82vw,320px);min-width:0;padding:18px 14px 120px}body.sidebar-collapsed .brand strong,body.sidebar-collapsed .brand small,body.sidebar-collapsed .navitem b,body.sidebar-collapsed .nav-label,body.sidebar-collapsed .sidebar-footer{display:block}body.sidebar-collapsed .navitem{justify-content:flex-start;padding:11px 12px}body.sidebar-collapsed .navitem span{width:28px;height:28px}.sidebar-footer{position:static;margin-top:16px}.brand{padding-bottom:14px}.nav-group{margin:10px 0}.navitem{font-size:13px;padding:11px 12px}.page-head{display:block;margin-bottom:14px}h1{font-size:19px}h2{font-size:17px}h3{font-size:14px}.grid4{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.gridcards{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.dashboard-grid,.resource-grid{grid-template-columns:1fr;gap:10px}.metric,.card,.panel,.tablebox,.resource-card,.server-card{padding:10px;border-radius:15px}.metric{min-height:92px}.metric .top{gap:7px}.metric .icon,.resource-icon{width:30px;height:30px;font-size:14px}.metric .label{font-size:9px}.value{font-size:16px}.muted,.trend,.badge,.pill,.card p,.kv span,.kv b{font-size:9px;line-height:1.22}.btn,button,select,input,textarea{font-size:10px}.btn,button{min-height:32px;padding:7px 8px}.server-meta{grid-template-columns:repeat(2,minmax(0,1fr))}.kvs{grid-template-columns:1fr}.chart-wrap,.apex-chart{height:205px!important;min-height:205px!important}.range-tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.range-tabs button{font-size:9px;padding:6px 4px}.modal-card{width:calc(100vw - 22px);max-height:88dvh;overflow:auto;padding:14px}.formgrid{grid-template-columns:1fr}.order-row{grid-template-columns:1fr;gap:6px}}
@media(max-width:430px){.content{padding:9px}.topbar{padding:8px}.grid4,.gridcards{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.metric,.card,.panel,.resource-card,.server-card{padding:8px;border-radius:13px}.metric{min-height:86px}.card h3{font-size:11px}.value{font-size:14px}.muted,.trend,.badge,.pill,.card p,.kv span,.kv b{font-size:8px}.btn,button{font-size:9px;min-height:29px;padding:6px}.metric .icon,.resource-icon{width:26px;height:26px;font-size:12px}.headrow{gap:8px}.rowactions{gap:5px}.chart-wrap,.apex-chart{height:190px!important;min-height:190px!important}.apexcharts-text,.apexcharts-legend-text,.apexcharts-tooltip{font-size:8px!important}}
@media(max-width:340px){.grid4,.gridcards{grid-template-columns:1fr}.top-actions{grid-template-columns:repeat(3,minmax(0,1fr))}.adminchip{grid-column:1/-1}.metric{min-height:74px}.metric .top{align-items:flex-start}.value{font-size:13px}.chart-wrap,.apex-chart{height:180px!important;min-height:180px!important}}


/* === v1.3.27 true mobile UX layout fixes === */
.search-toggle{display:none}
.topbar .menu-square,.topbar .icon-btn,.search-toggle{width:clamp(34px,4.2vw,46px);height:clamp(34px,4.2vw,46px);font-size:clamp(14px,1.9vw,20px)}
.avatar{width:clamp(34px,4.4vw,48px);height:clamp(34px,4.4vw,48px);font-size:clamp(14px,2vw,20px)}
.resource-card,.metric{height:auto;align-self:stretch}.resource-card *,.metric *{min-width:0}.resource-title,.metric .label{font-size:clamp(10px,1.65vw,14px);line-height:1.2}.resource-value,.value{font-size:clamp(15px,2.4vw,32px);line-height:1.15}.resource-sub,.muted{font-size:clamp(9px,1.55vw,13px);line-height:1.25}.resource-icon,.metric .icon{width:clamp(26px,4.5vw,54px);height:clamp(26px,4.5vw,54px);font-size:clamp(12px,2.1vw,22px);flex:0 0 auto}.resource-bar{margin-top:auto}.trend{font-size:clamp(8px,1.35vw,12px);padding:clamp(4px,.9vw,7px) clamp(5px,1.3vw,10px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

@media(max-width:760px){
  body{overflow-x:hidden}.topbar{position:sticky;top:0;z-index:32;display:flex;flex-wrap:nowrap;justify-content:space-between;align-items:center;min-height:56px;height:56px;padding:8px 10px;gap:8px}.top-left{width:auto;display:flex;align-items:center;gap:8px;flex:0 0 auto}.top-actions{width:auto!important;display:flex!important;grid-template-columns:none!important;gap:6px;align-items:center;justify-content:flex-end;min-width:0}.adminchip{border:0!important;padding:0!important;gap:7px;flex:0 1 auto;max-width:42vw}.adminchip .muted,.adminchip .btn.ghost{display:none}.adminchip b{font-size:clamp(11px,3.2vw,14px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.icon-btn{flex:0 0 auto}.top-actions .icon-btn:not(:first-child){display:none}.search-toggle{display:grid;place-items:center;flex:0 0 auto}.searchbox{position:fixed;left:10px;right:10px;top:64px;width:auto!important;height:44px;z-index:60;display:flex;opacity:0;pointer-events:none;transform:translateY(-8px);transition:.18s ease;box-shadow:var(--shadow)}body.search-open .searchbox{opacity:1;pointer-events:auto;transform:translateY(0)}.searchbox input{font-size:14px}.searchbox .kbd{display:none!important}.content{padding:10px;overflow:visible}.page-head{margin-bottom:12px}.breadcrumbs{font-size:11px}h1{font-size:20px}.resource-live-head{font-size:18px;align-items:center}.resource-live-head small{font-size:10px}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important;margin-bottom:12px}.resource-card{min-height:112px!important;padding:10px!important;border-radius:16px!important}.resource-card:before{width:86px;height:86px;right:-22px;bottom:-26px;filter:blur(12px)}.resource-head{gap:6px}.resource-value{font-size:clamp(17px,5vw,22px)!important}.resource-title{font-size:clamp(12px,3.5vw,15px)!important}.resource-sub{font-size:clamp(10px,2.8vw,12px)!important}.resource-icon{width:clamp(28px,8vw,36px)!important;height:clamp(28px,8vw,36px)!important;font-size:clamp(13px,4vw,17px)!important}.resource-bar{height:5px!important}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}.metric{min-height:106px!important;padding:10px!important;border-radius:16px!important;aspect-ratio:auto!important}.metric:before{width:82px;height:82px;right:-22px;bottom:-24px}.metric .top{align-items:flex-start}.metric .icon{width:clamp(28px,8vw,38px)!important;height:clamp(28px,8vw,38px)!important;font-size:clamp(13px,4vw,18px)!important}.metric .label{font-size:clamp(10px,3.2vw,13px)!important;text-transform:none;letter-spacing:0}.metric .value,.value{font-size:clamp(16px,4.8vw,22px)!important}.metric .muted{font-size:clamp(9px,2.8vw,12px)!important}.dashboard-grid{grid-template-columns:1fr!important;gap:12px!important}.panel,.tablebox{border-radius:18px!important;padding:12px!important}.panel-head{gap:10px;align-items:flex-start}.panel-head h2{font-size:16px}.range-tabs{width:100%;grid-template-columns:repeat(4,minmax(0,1fr))!important}.range-tabs button{min-height:34px;font-size:10px!important;padding:6px 4px!important}.chart-wrap,.apex-chart{height:220px!important;min-height:220px!important}.order-row{grid-template-columns:1fr!important}.orders{gap:8px}.table-scroll{overflow-x:auto}.tablebox table{min-width:680px}.headrow{align-items:center}.headrow h2{font-size:16px}.headrow form label{font-size:11px}.headrow select{height:38px;max-width:84px}.mobile-sidebar-backdrop{z-index:35}.sidebar{z-index:50!important}.main{min-width:0;width:100%}
}

@media(max-width:430px){
  .topbar{height:52px;min-height:52px;padding:7px 8px}.searchbox{top:60px}.content{padding:8px}.resource-grid,.grid4{gap:8px!important}.resource-card{min-height:102px!important;padding:9px!important;border-radius:15px!important}.metric{min-height:98px!important;padding:9px!important;border-radius:15px!important}.metric .value,.value{font-size:clamp(15px,4.6vw,19px)!important}.trend{font-size:8px!important;padding:4px 5px}.panel,.tablebox{padding:10px!important}.chart-wrap,.apex-chart{height:205px!important;min-height:205px!important}.adminchip{max-width:39vw}.menu-square,.icon-btn,.search-toggle{width:36px!important;height:36px!important}.avatar{width:34px!important;height:34px!important}
}

@media(max-width:340px){
  .resource-grid,.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:6px!important}.resource-card,.metric{min-height:90px!important;padding:7px!important}.resource-title,.metric .label{font-size:10px!important}.resource-value,.metric .value,.value{font-size:14px!important}.resource-sub,.metric .muted,.muted{font-size:8px!important}.resource-icon,.metric .icon{width:24px!important;height:24px!important;font-size:11px!important}.trend{display:none}.adminchip b{max-width:72px}.chart-wrap,.apex-chart{height:185px!important;min-height:185px!important}
}



/* === v1.3.28 Mobile search + customizable admin profile === */
.search-toggle{display:grid!important;place-items:center}
.admin-avatar-btn{border:0!important;background:transparent!important;padding:0!important;margin:0!important;display:grid!important;place-items:center!important;cursor:pointer!important;min-width:auto!important;box-shadow:none!important}
.admin-avatar-btn:hover{transform:none!important;box-shadow:none!important;border-color:transparent!important}
.admin-avatar-btn .avatar,.avatar{overflow:hidden;background-size:cover!important;background-position:center!important;background-repeat:no-repeat!important}
.admin-avatar-btn .avatar.has-photo,#profileAvatarPreview.has-photo{color:transparent!important;font-size:0!important}
.logout-icon-btn{width:clamp(34px,4.2vw,46px);height:clamp(34px,4.2vw,46px);border-radius:14px;border:1px solid var(--line);background:color-mix(in srgb,var(--card) 74%,transparent);display:grid;place-items:center;text-decoration:none;box-shadow:var(--soft-shadow);font-size:clamp(15px,2vw,20px);color:var(--text);flex:0 0 auto}
.logout-icon-btn:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--danger) 55%,var(--line));color:var(--danger)}
.profile-modal{position:fixed;inset:0;display:none;align-items:flex-start;justify-content:flex-end;padding:70px 18px 18px;background:rgba(2,6,23,.42);backdrop-filter:blur(8px);z-index:80}
.profile-modal.open{display:flex}
.profile-card{width:min(330px,calc(100vw - 24px));border:1px solid var(--line);border-radius:22px;background:linear-gradient(180deg,rgba(255,255,255,.08),rgba(255,255,255,.025)),color-mix(in srgb,var(--card) 96%,transparent);box-shadow:var(--shadow);padding:18px;display:grid;gap:12px;position:relative}
.profile-close{position:absolute;top:10px;right:10px;width:34px;height:34px;border-radius:12px;padding:0}
.profile-avatar-preview{width:96px;height:96px;border-radius:50%;margin:6px auto 8px;display:grid;place-items:center;background:linear-gradient(145deg,var(--primary),var(--primary-2));box-shadow:0 12px 35px color-mix(in srgb,var(--primary) 28%,transparent);background-size:cover!important;background-position:center!important;font-size:42px;overflow:hidden}
.profile-upload-label,.profile-logout{width:100%}
.search-result-hidden{display:none!important}
.search-empty-state{display:none;margin:10px 0;padding:12px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);text-align:center}.search-empty-state.show{display:block}
@media(max-width:760px){
  .top-actions .icon-btn:not(:first-child){display:grid!important}
  .top-actions{gap:clamp(4px,1.5vw,8px)!important}
  .admin-avatar-btn .avatar{width:clamp(32px,8vw,40px)!important;height:clamp(32px,8vw,40px)!important}
  .logout-icon-btn{display:none!important}
  .searchbox{left:10px!important;right:10px!important;top:calc(env(safe-area-inset-top,0px) + 62px)!important;display:flex!important;max-width:none!important}
  body.search-open .searchbox{opacity:1!important;pointer-events:auto!important;transform:translateY(0)!important}
  body:not(.search-open) .searchbox{opacity:0!important;pointer-events:none!important;transform:translateY(-8px)!important}
  .profile-modal{align-items:flex-start;justify-content:center;padding-top:calc(env(safe-area-inset-top,0px) + 64px)}
}
@media(min-width:761px){.searchbox{opacity:1!important;pointer-events:auto!important;transform:none!important}.search-toggle{display:none!important}}


/* D BOT v1.3.32 - Full HD dashboard sizing + unified metric numbers */
:root{
  --dashboard-max-width:1800px;
  --dashboard-gap-fhd:20px;
  --dashboard-card-value:clamp(17px,1.45vw,25px);
}
.content{
  width:100%;
  max-width:var(--dashboard-max-width);
  margin:0 auto;
  padding:24px clamp(20px,1.55vw,32px);
}
.grid4 .metric .value,
.grid4 .metric .value.monthly-value{
  font-size:var(--dashboard-card-value)!important;
  line-height:1.12!important;
  font-weight:900!important;
  letter-spacing:-.45px!important;
  max-width:100%;
  overflow-wrap:anywhere;
  word-break:break-word;
}
.grid4 .metric .muted{font-size:12px!important}.grid4 .metric .label{font-size:14px!important}

@media(min-width:1800px){
  .content{max-width:1800px;padding:24px 30px!important}
  .resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:20px!important;margin-bottom:20px!important}
  .grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:20px!important;margin-bottom:20px!important}
  .metric{min-height:150px!important;padding:18px!important;border-radius:22px!important}
  .metric .icon{width:48px!important;height:48px!important;font-size:20px!important}
  .dashboard-grid{grid-template-columns:minmax(0,1.35fr) minmax(380px,.65fr)!important;gap:20px!important;margin-bottom:20px!important}
  .panel{padding:18px!important;border-radius:22px!important}
  .chart-wrap,.apex-chart{height:400px!important;min-height:400px!important}
  .orders{max-height:400px!important;overflow-y:auto!important;padding-inline-end:4px!important}
  .tablebox{padding:18px!important;border-radius:22px!important}
  th,td{padding:13px 14px!important}
}
@media(min-width:1600px) and (max-width:1799px){
  .content{max-width:1560px;padding:22px 26px!important}
  .resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:18px!important}
  .grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:18px!important}
  .metric{min-height:145px!important;padding:17px!important}
  .dashboard-grid{grid-template-columns:minmax(0,1.3fr) minmax(360px,.7fr)!important;gap:18px!important}
  .chart-wrap,.apex-chart{height:370px!important;min-height:370px!important}
  .orders{max-height:370px!important;overflow-y:auto!important}
}
@media(min-width:1366px) and (max-width:1599px){
  .content{max-width:1320px;padding:20px 24px!important}
  .grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:16px!important}
  .metric{min-height:138px!important;padding:16px!important}
  .dashboard-grid{grid-template-columns:minmax(0,1.25fr) minmax(340px,.75fr)!important;gap:16px!important}
  .chart-wrap,.apex-chart{height:340px!important;min-height:340px!important}
  .orders{max-height:340px!important;overflow-y:auto!important}
}
@media(min-width:1200px) and (max-width:1365px){
  .content{max-width:1180px;padding:20px!important}
  .grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:14px!important}
  .metric{min-height:132px!important;padding:15px!important}
  .dashboard-grid{grid-template-columns:1.2fr .8fr!important}
  .chart-wrap,.apex-chart{height:315px!important;min-height:315px!important}
}
@media(max-width:760px){
  .grid4 .metric .value,.grid4 .metric .value.monthly-value{font-size:clamp(14px,4.3vw,19px)!important}
}

'''
STYLE += r'''

/* === v1.3.34 video-based final UI fixes === */
html,body{width:100%;max-width:100%;}
.shell{width:100%;max-width:100vw;}
.main{transition:width .22s ease, margin .22s ease;}
.content{max-width:1800px;margin:0 auto;padding:clamp(18px,1.35vw,32px);}
.metric .value{font-size:clamp(17px,1.45vw,25px)!important;}
.metric .value.monthly-value{font-size:clamp(17px,1.45vw,25px)!important;}
.metric .trend{font-size:clamp(10px,.7vw,12px)!important;line-height:1;}
.grid4{grid-template-columns:repeat(6,minmax(145px,1fr));align-items:stretch;}
.dashboard-grid{grid-template-columns:minmax(0,1.2fr) minmax(340px,.8fr);align-items:start;}
.panel{min-width:0;}
.orders{max-height:430px;overflow:auto;padding-inline-end:4px;}
.order-row{grid-template-columns:minmax(0,1fr) minmax(70px,auto) minmax(80px,auto) minmax(85px,auto);}
.table-scroll{width:100%;overflow:auto;-webkit-overflow-scrolling:touch;}
.logout-icon-btn{display:grid!important;place-items:center;width:clamp(34px,4vw,46px);height:clamp(34px,4vw,46px);border-radius:14px;border:1px solid var(--line);background:color-mix(in srgb,var(--card) 74%,transparent);text-decoration:none;color:var(--text);box-shadow:var(--soft-shadow);}
body.sidebar-desktop-hidden .sidebar{display:none!important;width:0!important;min-width:0!important;max-width:0!important;padding:0!important;margin:0!important;border:0!important;overflow:hidden!important;transform:none!important;}
body.sidebar-desktop-hidden .shell{display:block!important;}
body.sidebar-desktop-hidden .main{width:100%!important;max-width:100%!important;}
body.sidebar-desktop-hidden .content{max-width:1800px;margin:0 auto;}
body.sidebar-desktop-hidden .topbar{width:100%;}
@media(min-width:1800px){
  .content{max-width:1800px;padding:24px;}
  .grid4{gap:18px;margin-bottom:18px;}
  .metric{min-height:142px;padding:18px;}
  .metric .icon{width:48px;height:48px;font-size:20px;}
  .dashboard-grid{gap:18px;}
  .chart-wrap,.apex-chart{height:330px!important;min-height:330px!important;}
  .orders{max-height:330px;}
}
@media(min-width:1400px) and (max-width:1799px){
  .content{max-width:calc(100vw - 24px);padding:18px;}
  .grid4{grid-template-columns:repeat(6,minmax(130px,1fr));gap:14px;}
  .metric{min-height:126px;padding:14px;}
  .metric .icon{width:42px;height:42px;font-size:18px;}
  .dashboard-grid{gap:14px;}
  .chart-wrap,.apex-chart{height:300px!important;min-height:300px!important;}
}
@media(max-width:1399px) and (min-width:981px){
  .content{max-width:calc(100vw - 18px);padding:16px;}
  .grid4{grid-template-columns:repeat(3,minmax(160px,1fr));gap:14px;}
  .dashboard-grid{grid-template-columns:1fr;}
}
@media(max-width:760px){
  .content{max-width:100%;margin:0;padding:10px;}
  .resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
  .grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
  .dashboard-grid{grid-template-columns:1fr!important;}
  .metric .value,.metric .value.monthly-value{font-size:clamp(14px,4.2vw,18px)!important;}
  .logout-icon-btn{display:none!important;}
  .top-actions .icon-btn[data-ui-action="fullscreen"]{display:none!important;}
}
/* === v1.3.36 NO-SCALE TEMPLATE PREVIEW ===
   Removed fluid scale from the site skin. The layout now uses stable fixed sizes per breakpoint
   instead of viewport-based scale/clamp rules. */
:root{
  --fluid-gap:18px;
  --fluid-pad:18px;
  --fluid-radius:22px;
  --fluid-card-min:330px;
  --card-gap:18px;
  --card-pad:18px;
  --card-radius:22px;
  --text-xs:12px;
  --text-sm:13px;
  --text-md:14px;
  --text-lg:18px;
  --text-xl:25px;
}
html,body{font-size:14px!important;zoom:1!important}
.content{padding:28px!important;max-width:1800px;margin:0 auto;width:100%}
.topbar{height:76px!important;min-height:76px!important;padding:0 30px!important;gap:18px!important}
.menu-square,.icon-btn{width:46px!important;height:46px!important}
.searchbox{width:440px!important;height:46px!important}
.avatar{width:48px!important;height:48px!important}
.grid4{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:18px!important;margin-bottom:20px!important}
.dashboard-grid{grid-template-columns:1.2fr .8fr!important;gap:18px!important;margin-bottom:18px!important}
.gridcards{grid-template-columns:repeat(auto-fill,minmax(330px,1fr))!important;gap:22px!important}
.resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:18px!important;margin-bottom:20px!important}
.metric,.card,.panel,.tablebox,.resource-card,.server-card,.login-card,.modal-card{padding:18px!important;border-radius:22px!important;container-type:normal!important;contain:none!important;max-width:100%;min-width:0}
.metric{min-height:160px!important;gap:12px!important}
.resource-card{min-height:168px!important}
.metric .icon,.resource-icon{width:54px!important;height:54px!important;font-size:22px!important}
.metric .label,.resource-label,.card h3,.panel h2,.headrow h2{font-size:13px!important;line-height:1.2!important}
.value,.resource-value,.metric .value{font-size:25px!important;line-height:1.1!important;letter-spacing:-.5px!important}
.metric .value.monthly-value{font-size:25px!important}
.metric .muted,.resource-sub,.muted,.kv span,.kv b,.card p,.panel p,.order-row,.pill,.badge{font-size:12px!important;line-height:1.25!important}
.trend{font-size:12px!important;padding:5px 8px!important;line-height:1.1!important}
.btn,button,select,input,textarea{font-size:13px!important}
.btn,button{padding:10px 14px!important;border-radius:13px!important;line-height:1.15!important;min-height:40px!important}
.chart-wrap,.apex-chart{height:320px!important;min-height:320px!important}
.apexcharts-text,.apexcharts-legend-text,.apexcharts-tooltip{font-size:12px!important}.apexcharts-xaxis-label,.apexcharts-yaxis-label{font-size:12px!important}
.order-row{grid-template-columns:1fr 120px 100px 110px!important;gap:12px!important;padding:13px 0!important}
th,td{font-size:12px!important;padding:15px 14px!important}
h1{font-size:26px!important}h2{font-size:21px!important}h3{font-size:18px!important}
.metric:hover,.card:hover,.btn:hover,button:hover{transform:none!important}
@media(min-width:1600px){
  .content{padding:30px!important;max-width:1800px!important}
  .grid4{grid-template-columns:repeat(4,minmax(0,1fr))!important}
  .resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}
  .chart-wrap,.apex-chart{height:340px!important;min-height:340px!important}
}
@media(max-width:1399px){
  .content{padding:24px!important}.grid4{grid-template-columns:repeat(3,minmax(0,1fr))!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}.searchbox{width:360px!important}
}
@media(max-width:992px){
  .content{padding:18px!important}.topbar{height:64px!important;min-height:64px!important;padding:0 18px!important}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.metric{min-height:135px!important}.resource-card{min-height:135px!important}.chart-wrap,.apex-chart{height:260px!important;min-height:260px!important}.searchbox{width:280px!important}
}
@media(max-width:760px){
  .content{padding:12px!important}.topbar{height:56px!important;min-height:56px!important;padding:8px 10px!important}.searchbox{position:fixed!important;left:10px!important;right:10px!important;top:64px!important;width:auto!important;height:44px!important}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}.dashboard-grid,.gridcards{grid-template-columns:1fr!important;gap:12px!important}.metric{min-height:108px!important;padding:10px!important;border-radius:16px!important}.resource-card{min-height:112px!important;padding:10px!important;border-radius:16px!important}.metric .icon,.resource-icon{width:34px!important;height:34px!important;font-size:16px!important}.metric .label,.resource-label{font-size:11px!important}.value,.resource-value,.metric .value,.metric .value.monthly-value{font-size:18px!important}.metric .muted,.resource-sub,.muted,.trend,.pill,.badge{font-size:10px!important}.trend{padding:3px 5px!important}.panel,.tablebox,.card{padding:12px!important;border-radius:18px!important}.chart-wrap,.apex-chart{height:220px!important;min-height:220px!important}.order-row{grid-template-columns:1fr!important}.menu-square,.icon-btn{width:38px!important;height:38px!important}.avatar{width:38px!important;height:38px!important}
}
@media(max-width:390px){
  .content{padding:10px!important}.metric{min-height:100px!important;padding:8px!important}.resource-card{min-height:104px!important;padding:8px!important}.value,.resource-value,.metric .value,.metric .value.monthly-value{font-size:16px!important}.metric .label,.resource-label{font-size:10px!important}.metric .muted,.resource-sub,.muted,.trend,.pill,.badge{font-size:9px!important}.chart-wrap,.apex-chart{height:200px!important;min-height:200px!important}
}


/* === v1.3.37 Premium SaaS Admin UI final pass ===
   Real stack detected: FastAPI server-rendered admin panel + aiogram Telegram bot.
   This layer keeps backend/routes/forms intact and only normalizes UI/UX behavior. */
:root{--dbot-sidebar:286px;--dbot-header:72px;--dbot-max:1800px;--dbot-gap:20px}
body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,Arial,sans-serif!important;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased}
.content{max-width:var(--dbot-max)!important;margin:0 auto!important;padding:clamp(18px,1.45vw,30px)!important}
.topbar{height:var(--dbot-header)!important;padding:0 clamp(18px,1.35vw,28px)!important}
.sidebar{transition:width .22s ease,min-width .22s ease,transform .24s ease,opacity .2s ease!important;will-change:width,transform}
body.sidebar-desktop-hidden .sidebar{width:82px!important;min-width:82px!important;padding-inline:12px!important}
body.sidebar-desktop-hidden .brand strong,body.sidebar-desktop-hidden .brand small,body.sidebar-desktop-hidden .navitem b,body.sidebar-desktop-hidden .nav-label,body.sidebar-desktop-hidden .sidebar-footer{display:none!important}
body.sidebar-desktop-hidden .brand{justify-content:center;padding-bottom:18px!important}
body.sidebar-desktop-hidden .brand .gift{width:46px!important;height:46px!important}
body.sidebar-desktop-hidden .navitem{justify-content:center;padding:12px!important}
body.sidebar-desktop-hidden .navitem span{margin:0!important}
.menu-square,.search-toggle,.icon-btn,.logout-icon-btn,.admin-avatar-btn{cursor:pointer!important;user-select:none!important;transition:transform .18s ease,background .18s ease,border-color .18s ease!important}
.menu-square:hover,.search-toggle:hover,.icon-btn:hover,.logout-icon-btn:hover,.admin-avatar-btn:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--primary) 34%,var(--line))!important}
.logout-icon-btn{width:46px;height:46px;border-radius:14px;border:1px solid var(--line);background:color-mix(in srgb,var(--card) 74%,transparent);display:grid;place-items:center;text-decoration:none;box-shadow:var(--soft-shadow)}
.admin-avatar-btn{border:0;background:transparent;padding:0;display:grid;place-items:center}.admin-avatar-btn .avatar{overflow:hidden}.admin-avatar-btn img,.profile-avatar-preview img{width:100%;height:100%;object-fit:cover;border-radius:inherit}
.search-toggle{display:none;width:46px;height:46px;border-radius:14px;border:1px solid var(--line);background:color-mix(in srgb,var(--card) 74%,transparent);place-items:center;box-shadow:var(--soft-shadow)}
.searchbox{transition:opacity .18s ease,transform .18s ease,width .2s ease!important}.searchbox.search-open{display:flex!important;opacity:1!important;transform:none!important}
.page-head{margin-bottom:clamp(14px,1.2vw,22px)!important}.page-head h1{font-size:clamp(24px,1.55vw,31px)!important;font-weight:800!important;letter-spacing:-.04em}
.resource-live-head{max-width:100%;display:flex;justify-content:space-between;align-items:center;margin:0 0 12px;gap:14px}.resource-live-head span{font-size:clamp(20px,1.35vw,28px);font-weight:850}.resource-live-head small{color:var(--muted);font-weight:650}
.resource-grid{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:var(--dbot-gap)!important;margin-bottom:var(--dbot-gap)!important}
.resource-card{min-height:clamp(142px,9.2vw,176px)!important;padding:clamp(15px,1vw,21px)!important;border-radius:22px!important;display:flex!important;flex-direction:column!important;justify-content:space-between!important;overflow:hidden!important}
.resource-top{display:flex!important;align-items:flex-start!important;justify-content:space-between!important;gap:12px!important}.resource-title{font-size:clamp(13px,.82vw,16px)!important;font-weight:800!important;color:var(--text)!important}.resource-value{font-size:clamp(21px,1.65vw,30px)!important;font-weight:850!important;line-height:1.05!important;margin-top:8px!important}.resource-detail{font-size:clamp(12px,.75vw,15px)!important;color:var(--muted)!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.resource-icon{width:clamp(34px,2.4vw,48px)!important;height:clamp(34px,2.4vw,48px)!important;font-size:clamp(16px,1.25vw,23px)!important;flex:0 0 auto!important}.resource-bar{height:7px!important;border-radius:999px!important;overflow:hidden!important;background:rgba(148,163,184,.18)!important}.resource-bar span{height:100%!important;display:block!important;border-radius:inherit!important}
.grid4{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:var(--dbot-gap)!important;margin-bottom:var(--dbot-gap)!important}.metric{min-height:clamp(136px,8.4vw,162px)!important;padding:clamp(15px,.95vw,20px)!important;border-radius:22px!important}.metric .top{align-items:flex-start!important}.metric .label{font-size:clamp(12px,.74vw,14px)!important;line-height:1.2!important;font-weight:800!important;color:var(--muted)!important}.metric .value,.metric .value.monthly-value{font-size:clamp(22px,1.55vw,30px)!important;line-height:1.05!important;font-weight:850!important;letter-spacing:-.045em!important}.metric .muted{font-size:clamp(11px,.7vw,13px)!important}.metric .icon{width:clamp(38px,2.55vw,52px)!important;height:clamp(38px,2.55vw,52px)!important;font-size:clamp(16px,1.25vw,22px)!important;flex:0 0 auto!important}.trend{width:max-content!important;max-width:100%!important;font-size:clamp(11px,.75vw,13px)!important;font-weight:800!important;padding:6px 10px!important;border-radius:999px!important;line-height:1!important}.trend.up{color:var(--success)!important}.trend.down{color:var(--danger)!important}.trend.neutral{color:var(--warning)!important}
.dashboard-grid{display:grid!important;grid-template-columns:minmax(0,1.45fr) minmax(360px,.75fr)!important;gap:var(--dbot-gap)!important;align-items:stretch!important}.panel,.tablebox,.card,.modal-card{border-radius:24px!important;background:linear-gradient(180deg,rgba(255,255,255,.055),rgba(255,255,255,.018)),color-mix(in srgb,var(--panel) 94%,transparent)!important;border:1px solid var(--line)!important;box-shadow:var(--soft-shadow)!important}.panel{min-height:0!important;padding:clamp(18px,1vw,24px)!important}.panel-head{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:14px!important;margin-bottom:16px!important}.panel h2,.tablebox h2{font-size:clamp(17px,1.05vw,22px)!important;font-weight:850!important}.range-tabs{display:flex!important;gap:10px!important;flex-wrap:wrap!important}.range-tabs button{min-width:clamp(92px,5.8vw,130px)!important;height:42px!important;border-radius:999px!important}.chart-wrap,.apex-chart,#revenueChart{height:clamp(300px,22vw,430px)!important;min-height:300px!important;max-height:430px!important;overflow:hidden!important;touch-action:pan-y!important}.apexcharts-canvas,.apexcharts-svg{max-width:100%!important}
.orders{max-height:430px!important;overflow:auto!important;padding-inline-end:4px}.order-row{padding:14px 0!important;border-bottom:1px solid var(--line)!important}.order-row:last-child{border-bottom:0!important}.badge,.pill{font-size:12px!important;border-radius:999px!important;padding:7px 10px!important;white-space:nowrap!important}.tablebox{padding:clamp(18px,1vw,24px)!important;margin-top:var(--dbot-gap)!important}.headrow{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:14px!important;flex-wrap:wrap}.table-scroll{overflow:auto!important;border-radius:18px!important;border:1px solid var(--line)!important}table{width:100%!important;border-collapse:separate!important;border-spacing:0!important;min-width:880px!important}th{position:sticky;top:0;background:color-mix(in srgb,var(--panel-2) 96%,transparent)!important;z-index:1}th,td{padding:14px 16px!important;font-size:clamp(12px,.78vw,14px)!important;vertical-align:middle!important}.btn,button,input,select,textarea{font-family:inherit!important}.btn,button{min-height:40px;border-radius:12px;border:1px solid var(--line);transition:transform .16s ease,opacity .16s ease,background .16s ease}.btn:hover,button:hover{transform:translateY(-1px)}input,select,textarea{border-radius:13px!important;border:1px solid var(--line)!important;background:color-mix(in srgb,var(--card) 74%,transparent)!important;color:var(--text)!important;outline:none!important}input:focus,select:focus,textarea:focus{border-color:color-mix(in srgb,var(--primary) 60%,var(--line))!important;box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 14%,transparent)!important}.empty-state{border:1px dashed var(--line);border-radius:18px;padding:18px;color:var(--muted);text-align:center;background:rgba(148,163,184,.045)}
@media (min-width:1800px){:root{--dbot-gap:22px}.content{padding:26px 34px!important}.resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}.grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:minmax(0,1.5fr) minmax(420px,.75fr)!important}.orders{max-height:430px!important}}
@media (max-width:1599px){.resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}.grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}.orders{max-height:360px!important}}
@media (max-width:1199px){.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.grid4{grid-template-columns:repeat(3,minmax(0,1fr))!important}.searchbox{width:min(360px,34vw)!important}}
@media (max-width:760px){body{overflow-x:hidden!important}.shell{display:block!important}.sidebar{position:fixed!important;top:0;bottom:0;left:0!important;right:auto!important;width:min(82vw,320px)!important;min-width:0!important;height:100dvh!important;transform:translateX(-106%)!important;z-index:80!important;opacity:.98!important}.sidebar-footer{position:static!important;margin-top:18px!important}body.sidebar-open .sidebar{transform:translateX(0)!important}.mobile-sidebar-backdrop{display:none;position:fixed;inset:0;background:rgba(2,6,23,.56);backdrop-filter:blur(4px);z-index:70}body.sidebar-open .mobile-sidebar-backdrop{display:block}.main{width:100%!important}.topbar{height:64px!important;padding:0 12px!important;gap:8px!important}.top-left,.top-actions{gap:8px!important}.menu-square,.search-toggle,.icon-btn,.logout-icon-btn{width:40px!important;height:40px!important;border-radius:12px!important;font-size:16px!important}.search-toggle{display:grid!important}.searchbox{position:fixed!important;top:70px!important;left:12px!important;right:12px!important;width:auto!important;height:50px!important;z-index:65!important;display:none!important;opacity:0!important;transform:translateY(-8px)!important;box-shadow:var(--shadow)!important}.searchbox.search-open{display:flex!important}.kbd{display:none!important}.top-actions .icon-btn[data-ui-action="fullscreen"],.top-actions .icon-btn[data-ui-action="cycle-theme"],.top-actions .icon-btn[data-ui-action="notify"]{display:none!important}.logout-icon-btn{display:none!important}.avatar{width:40px!important;height:40px!important}.content{padding:16px 12px 84px!important}.page-head h1{font-size:28px!important}.resource-live-head span{font-size:22px!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:12px!important}.resource-card{min-height:126px!important;padding:13px!important;border-radius:18px!important}.resource-title{font-size:12px!important}.resource-value{font-size:20px!important}.resource-detail{font-size:11px!important}.resource-icon{width:34px!important;height:34px!important;font-size:16px!important}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:12px!important}.metric{min-height:124px!important;padding:13px!important;border-radius:18px!important}.metric .label{font-size:11px!important}.metric .value,.metric .value.monthly-value{font-size:20px!important}.metric .icon{width:34px!important;height:34px!important;font-size:16px!important}.trend{font-size:10px!important;padding:5px 8px!important}.dashboard-grid{grid-template-columns:1fr!important;gap:14px!important}.panel,.tablebox{padding:14px!important;border-radius:20px!important}.panel-head{align-items:flex-start!important;flex-direction:column!important}.range-tabs{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important;width:100%!important}.range-tabs button{min-width:0!important;width:100%!important;height:38px!important}.chart-wrap,.apex-chart,#revenueChart{height:235px!important;min-height:235px!important}.orders{max-height:360px!important}.headrow{align-items:flex-start!important}.table-scroll{border:0!important;overflow:visible!important}table{min-width:720px!important}th,td{padding:12px!important;font-size:12px!important}}
@media (max-width:420px){.content{padding-inline:10px!important}.resource-grid,.grid4{gap:10px!important}.resource-card,.metric{min-height:116px!important;padding:11px!important}.resource-value,.metric .value,.metric .value.monthly-value{font-size:18px!important}.resource-detail,.metric .muted{font-size:10px!important}.resource-icon,.metric .icon{width:30px!important;height:30px!important}.chart-wrap,.apex-chart,#revenueChart{height:215px!important;min-height:215px!important}}

'''


STYLE += r'''

/* === v1.3.39 centered login content === */
.login-wrap{
  min-height:100vh!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
  padding:24px!important;
  text-align:center!important;
}
.login-card{
  width:min(450px,94vw)!important;
  margin:0 auto!important;
  text-align:center!important;
  display:flex!important;
  flex-direction:column!important;
  align-items:center!important;
}
.login-card .logo{
  width:100%!important;
  text-align:center!important;
  margin:0 0 8px!important;
  line-height:1.1!important;
}
.login-card .muted,
.login-card .copyright{
  width:100%!important;
  text-align:center!important;
  margin-left:auto!important;
  margin-right:auto!important;
  line-height:1.75!important;
}
.login-card label{
  width:100%!important;
  text-align:center!important;
  margin-top:14px!important;
  margin-bottom:8px!important;
}
.login-card input{
  width:100%!important;
  text-align:center!important;
}
.login-card button.primary{
  width:100%!important;
  justify-content:center!important;
  text-align:center!important;
}
@media(max-width:520px){
  .login-wrap{padding:16px!important;}
  .login-card{width:100%!important;max-width:94vw!important;padding:24px 18px!important;}
  .login-card .logo{font-size:30px!important;}
  .login-card .copyright{font-size:12px!important;}
}

'''


STYLE += r'''

/* === v1.3.40 Premium Cyberpunk SaaS Rebuild Layer === */
:root{
  --cyber-bg:#020818;
  --cyber-bg-2:#06122b;
  --cyber-panel:rgba(7,18,42,.70);
  --cyber-panel-strong:rgba(10,24,52,.86);
  --cyber-line:rgba(94,234,212,.18);
  --cyber-line-strong:rgba(56,189,248,.38);
  --cyber-cyan:#22d3ee;
  --cyber-blue:#2563eb;
  --cyber-indigo:#7c3aed;
  --cyber-text:#e6f7ff;
  --cyber-muted:#8fb6ca;
  --cyber-shadow:0 24px 90px rgba(0,0,0,.42),0 0 0 1px rgba(34,211,238,.08),inset 0 1px 0 rgba(255,255,255,.08);
}
html{background:var(--cyber-bg)!important;color-scheme:dark;}
body{
  background-color:var(--cyber-bg)!important;
  background-image:url('/admin/assets/cyber-bg.svg'),radial-gradient(circle at 14% 8%,rgba(34,211,238,.18),transparent 28%),radial-gradient(circle at 84% 12%,rgba(124,58,237,.17),transparent 30%),linear-gradient(135deg,#020818 0%,#04152d 55%,#020617 100%)!important;
  background-size:cover,auto,auto,auto!important;
  background-attachment:fixed!important;
  color:var(--cyber-text)!important;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,Arial,sans-serif!important;
}
body:before{opacity:.75!important;background:linear-gradient(rgba(34,211,238,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(34,211,238,.035) 1px,transparent 1px)!important;background-size:44px 44px!important;}
body:after{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;background:radial-gradient(circle at 50% 120%,rgba(37,99,235,.22),transparent 36%),linear-gradient(180deg,rgba(2,8,24,.14),rgba(2,6,23,.82));animation:cyberPulse 9s ease-in-out infinite alternate;}
@keyframes cyberPulse{from{filter:saturate(1) brightness(1)}to{filter:saturate(1.22) brightness(1.08)}}
.shell,.main,.content{background:transparent!important;}
.sidebar,.topbar,.panel,.card,.tablebox,.metric,.resource-card,.server-card,.modal-card,.profile-card,.login-card,.order-row,.kv,.empty-state{
  background:linear-gradient(180deg,rgba(255,255,255,.075),rgba(255,255,255,.022)),var(--cyber-panel)!important;
  border:1px solid var(--cyber-line)!important;
  box-shadow:var(--cyber-shadow)!important;
  backdrop-filter:blur(22px) saturate(1.24)!important;
}
.sidebar{background:linear-gradient(180deg,rgba(4,16,40,.92),rgba(3,10,26,.78))!important;}
.topbar{background:rgba(2,8,24,.72)!important;}
.content{max-width:1840px!important;margin:0 auto!important;width:100%!important;padding:clamp(18px,1.8vw,34px)!important;}
.langbox,[data-ui-action="cycle-theme"],.theme-dots+.langbox{display:none!important;}
.brand .gift,.metric .icon,.resource-icon,.avatar{background:linear-gradient(135deg,#08356a,#0ea5e9 48%,#7c3aed)!important;box-shadow:0 0 28px rgba(34,211,238,.28),0 18px 45px rgba(37,99,235,.25)!important;}
.navitem{border-radius:16px!important;color:var(--cyber-muted)!important;}
.navitem span{background:rgba(34,211,238,.08)!important;border:1px solid rgba(34,211,238,.10)!important;}
.navitem:hover{background:rgba(34,211,238,.09)!important;border-color:rgba(34,211,238,.18)!important;color:#fff!important;}
.navitem.active{background:linear-gradient(135deg,rgba(14,165,233,.92),rgba(37,99,235,.86),rgba(124,58,237,.82))!important;box-shadow:0 0 34px rgba(34,211,238,.22),0 18px 52px rgba(37,99,235,.32)!important;}
button,.btn,a.btn,.primary,.ghost,.danger,.range-tabs button,.profile-upload-label,.logout-icon-btn,.menu-square,.search-toggle,.icon-btn,.admin-avatar-btn{
  color:#eafaff!important;
  border:1px solid rgba(34,211,238,.24)!important;
  border-radius:14px!important;
  background-image:url('/admin/assets/cyber-bg.svg'),linear-gradient(135deg,rgba(5,24,56,.92),rgba(7,47,92,.84) 48%,rgba(4,16,40,.92))!important;
  background-size:260px 180px,auto!important;
  box-shadow:0 0 0 1px rgba(34,211,238,.07),0 12px 34px rgba(0,0,0,.30),inset 0 1px 0 rgba(255,255,255,.10)!important;
  text-shadow:0 0 12px rgba(34,211,238,.28)!important;
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease,filter .18s ease!important;
}
button:hover,.btn:hover,a.btn:hover,.range-tabs button:hover,.profile-upload-label:hover,.logout-icon-btn:hover,.menu-square:hover,.search-toggle:hover,.icon-btn:hover,.admin-avatar-btn:hover{transform:translateY(-1px)!important;border-color:rgba(94,234,212,.58)!important;box-shadow:0 0 30px rgba(34,211,238,.22),0 18px 42px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.14)!important;filter:brightness(1.08)!important;}
button:active,.btn:active,a.btn:active{transform:translateY(0) scale(.985)!important;}
button .icon,.btn .icon{display:none!important;}
input,select,textarea,.searchbox{background:rgba(2,8,24,.55)!important;border:1px solid rgba(34,211,238,.18)!important;color:var(--cyber-text)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.06)!important;}
input:focus,select:focus,textarea:focus,.searchbox:focus-within{outline:none!important;border-color:rgba(94,234,212,.58)!important;box-shadow:0 0 0 4px rgba(34,211,238,.10),inset 0 1px 0 rgba(255,255,255,.08)!important;}
.table-scroll,.orders,.modal-card{background:transparent!important;scrollbar-color:rgba(34,211,238,.55) rgba(2,8,24,.35);}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-track{background:rgba(2,8,24,.30);border-radius:99px}::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#22d3ee,#2563eb);border-radius:99px;border:2px solid rgba(2,8,24,.55)}
.grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:clamp(14px,1.15vw,22px)!important;}
.metric{min-height:clamp(132px,14vh,172px)!important;padding:clamp(16px,1.15vw,22px)!important;}
.metric .value,.value{font-size:clamp(20px,1.35vw,28px)!important;letter-spacing:-.55px!important;}
.metric .value.monthly-value{font-size:clamp(18px,1.15vw,24px)!important;}
.metric .label{font-size:clamp(12px,.75vw,14px)!important;color:#dff8ff!important;}
.trend{font-size:clamp(10px,.62vw,12px)!important;border:1px solid currentColor;border-radius:999px;padding:4px 8px;background:rgba(255,255,255,.035)}
.dashboard-grid{grid-template-columns:minmax(0,1.35fr) minmax(340px,.65fr)!important;gap:clamp(16px,1.25vw,24px)!important;}
.chart-wrap,.apex-chart{height:clamp(300px,34vh,430px)!important;min-height:0!important;}
.apexcharts-canvas,.apexcharts-svg{max-width:100%!important;}
.resource-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:clamp(14px,1vw,20px)!important;}
.resource-card{min-height:clamp(132px,14vh,178px)!important;padding:clamp(16px,1.2vw,24px)!important;}
.resource-value{font-size:clamp(24px,2vw,38px)!important;}
.resource-detail{color:var(--cyber-muted)!important;}
.resource-bar{background:rgba(2,8,24,.55)!important;border-color:rgba(34,211,238,.14)!important;}
.resource-bar span{background:linear-gradient(90deg,#22d3ee,#2563eb,#7c3aed)!important;}
.panel-head,.headrow{gap:16px!important;}
table{background:transparent!important;}th{color:#c8f6ff!important;background:rgba(34,211,238,.055)!important;}td,th{border-color:rgba(34,211,238,.11)!important;}
.login-wrap{min-height:100dvh!important;display:grid!important;place-items:center!important;padding:clamp(18px,4vw,48px)!important;background:transparent!important;position:relative;overflow:hidden;}
.login-wrap:before{content:"";position:absolute;inset:0;background:radial-gradient(circle at 50% 36%,rgba(34,211,238,.16),transparent 30%),radial-gradient(circle at 50% 72%,rgba(124,58,237,.12),transparent 28%);pointer-events:none;}
.login-card{position:relative;z-index:1;width:min(94vw,460px)!important;max-width:460px!important;min-height:auto!important;padding:clamp(26px,3.2vw,42px)!important;text-align:center!important;border-radius:30px!important;animation:loginRise .72s cubic-bezier(.16,1,.3,1) both;overflow:hidden;}
.login-card:before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(34,211,238,.85),rgba(37,99,235,.18),rgba(124,58,237,.72));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;}
.login-card:after{content:"";position:absolute;inset:auto 12% -55px 12%;height:110px;background:radial-gradient(ellipse,rgba(34,211,238,.33),transparent 68%);filter:blur(16px);pointer-events:none;}
@keyframes loginRise{from{opacity:0;transform:translateY(22px) scale(.98);filter:blur(8px)}to{opacity:1;transform:none;filter:none}}
.login-card .logo{display:flex!important;align-items:center!important;justify-content:center!important;gap:12px!important;font-size:clamp(34px,4vw,48px)!important;font-weight:950!important;letter-spacing:-1px!important;text-align:center!important;margin:0 auto 8px!important;}
.login-card .logo span{display:inline-grid;place-items:center;width:58px;height:58px;border-radius:20px;background:linear-gradient(135deg,#22d3ee,#2563eb,#7c3aed);box-shadow:0 0 34px rgba(34,211,238,.45);}
.login-card label{display:block!important;text-align:center!important;margin:16px 0 8px!important;color:#dff8ff!important;font-weight:800!important;}
.login-card input{width:100%!important;height:52px!important;border-radius:16px!important;text-align:center!important;font-size:16px!important;}
.login-card button.primary{width:100%!important;height:52px!important;margin-top:18px!important;font-weight:900!important;letter-spacing:.02em!important;}
.login-password-wrap{position:relative;display:flex;align-items:center;}
.login-password-wrap input{padding-inline-end:84px!important;}
.login-password-toggle{position:absolute;right:8px;top:50%;transform:translateY(-50%)!important;min-height:36px!important;height:36px!important;padding:0 12px!important;font-size:12px!important;border-radius:12px!important;}
.login-password-toggle:hover{transform:translateY(-50%)!important;}
.login-helper{margin:14px 0 0!important;color:var(--cyber-muted)!important;font-size:12px!important;text-align:center!important;}
.login-card .muted,.login-card .copyright,.login-card p,.login-card b{text-align:center!important;}
.login-card .copyright{max-width:360px;margin:22px auto 0!important;line-height:1.6!important;}
@media(min-width:1900px){.content{max-width:1840px!important}.grid4{grid-template-columns:repeat(5,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1.35fr .65fr!important}.chart-wrap,.apex-chart{height:420px!important}}
@media(min-width:2560px){.content{max-width:2280px!important}.metric .value,.value{font-size:clamp(24px,1vw,34px)!important}.chart-wrap,.apex-chart{height:500px!important}}
@media(max-width:1440px){.grid4{grid-template-columns:repeat(3,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}}
@media(max-width:920px){.content{padding:14px!important}.sidebar{position:fixed!important;top:0!important;bottom:0!important;left:0!important;width:min(84vw,330px)!important;height:100dvh!important;transform:translateX(-108%)!important;transition:transform .24s cubic-bezier(.16,1,.3,1)!important;z-index:80!important;overflow:auto!important}.sidebar.open,body.sidebar-open .sidebar{transform:translateX(0)!important}.mobile-sidebar-backdrop{display:block!important;position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(4px);opacity:0;pointer-events:none;transition:.2s ease;z-index:70}body.sidebar-open .mobile-sidebar-backdrop{opacity:1;pointer-events:auto}.topbar{height:62px!important;min-height:62px!important;flex-wrap:nowrap!important}.searchbox{position:fixed!important;left:12px!important;right:12px!important;top:72px!important;width:auto!important;opacity:0;pointer-events:none;transform:translateY(-8px);z-index:90!important}body.search-open .searchbox{opacity:1;pointer-events:auto;transform:translateY(0)}.searchbox .kbd{display:none!important}.top-actions .icon-btn{display:none!important}.logout-icon-btn{display:none!important}.admin-avatar-btn{display:grid!important}.grid4{grid-template-columns:repeat(2,minmax(0,1fr))!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.metric,.resource-card{min-height:112px!important}.dashboard-grid{grid-template-columns:1fr!important}.chart-wrap,.apex-chart{height:245px!important}.table-scroll{overflow-x:auto!important}table{min-width:760px!important}}
@media(max-width:520px){.topbar{padding:8px!important}.content{padding:10px!important}.grid4,.resource-grid{gap:9px!important}.metric,.resource-card,.panel,.tablebox,.card{border-radius:18px!important;padding:10px!important}.metric .icon,.resource-icon{width:32px!important;height:32px!important;font-size:14px!important}.metric .label,.resource-title{font-size:10px!important}.metric .value,.value,.resource-value{font-size:17px!important}.muted,.trend,.badge,.pill{font-size:9px!important}.chart-wrap,.apex-chart{height:220px!important}.panel-head{align-items:flex-start!important;flex-direction:column!important}.range-tabs{width:100%;display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important}.range-tabs button{font-size:9px!important;padding:6px 4px!important}.login-card{border-radius:24px!important;padding:24px 18px!important}.login-card input,.login-card button.primary{height:48px!important}.login-card .logo span{width:48px;height:48px;border-radius:16px}}

'''



STYLE += r'''
/* === v1.3.41 visual reference rebuild: premium cyber SaaS UI === */
:root{--cyber-bg:#020712;--cyber-bg-2:#06162d;--cyber-panel:rgba(4,18,43,.68);--cyber-panel-2:rgba(7,24,54,.56);--cyber-line:rgba(56,189,248,.22);--cyber-line-2:rgba(139,92,246,.28);--cyber-text:#f8fbff;--cyber-muted:#9bb0cc;--cyber-blue:#0ea5ff;--cyber-cyan:#22d3ee;--cyber-purple:#8b5cf6;--cyber-pink:#d946ef;--cyber-green:#22c55e;--cyber-amber:#f59e0b;--cyber-red:#fb3f69;--cyber-radius:22px;--cyber-shadow:0 24px 90px rgba(0,0,0,.48),0 0 40px rgba(14,165,255,.08);--cyber-glow:0 0 22px rgba(34,211,238,.26),0 0 48px rgba(139,92,246,.14)}
*{scrollbar-width:thin;scrollbar-color:rgba(34,211,238,.88) rgba(3,10,26,.18)}::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:rgba(3,10,26,.18);border-radius:999px}::-webkit-scrollbar-thumb{background:linear-gradient(180deg,var(--cyber-blue),var(--cyber-purple));border-radius:999px;box-shadow:0 0 18px rgba(34,211,238,.45)}
body[data-theme]{background:#020712!important;color:var(--cyber-text)!important;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,Arial,sans-serif!important}body[data-theme]:before{content:""!important;position:fixed!important;inset:0!important;z-index:-3!important;pointer-events:none!important;background:radial-gradient(circle at 12% 10%,rgba(124,58,237,.22),transparent 26%),radial-gradient(circle at 88% 3%,rgba(34,211,238,.18),transparent 25%),radial-gradient(circle at 50% 105%,rgba(14,165,233,.22),transparent 34%),linear-gradient(135deg,#020712 0%,#05122a 52%,#020712 100%)!important;mask-image:none!important}body[data-theme]:after{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;opacity:.56;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1600' height='1000' viewBox='0 0 1600 1000'%3E%3Cdefs%3E%3CradialGradient id='g' cx='50%25' cy='50%25' r='50%25'%3E%3Cstop stop-color='%2322d3ee' stop-opacity='.85'/%3E%3Cstop offset='1' stop-color='%2322d3ee' stop-opacity='0'/%3E%3C/radialGradient%3E%3ClinearGradient id='l' x1='0' x2='1'%3E%3Cstop stop-color='%230ea5ff' stop-opacity='.42'/%3E%3Cstop offset='.5' stop-color='%238b5cf6' stop-opacity='.55'/%3E%3Cstop offset='1' stop-color='%2322d3ee' stop-opacity='.38'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='1600' height='1000' fill='%23020712'/%3E%3Cg opacity='.25'%3E%3Cpath d='M0 775 C280 660 410 900 700 760 C960 635 1160 760 1600 610' stroke='url(%23l)' fill='none' stroke-width='2'/%3E%3Cpath d='M0 835 C310 720 560 835 820 710 C1100 575 1260 720 1600 540' stroke='url(%23l)' fill='none' stroke-width='2'/%3E%3Cg stroke='%2322d3ee' stroke-opacity='.16' stroke-width='1'%3E%3Cpath d='M0 850h1600M0 900h1600M0 950h1600M140 1000L800 590M380 1000L890 590M620 1000L980 590M860 1000L1070 590M1100 1000L1160 590M1340 1000L1250 590'/%3E%3C/g%3E%3C/g%3E%3Cg opacity='.78'%3E%3Ccircle cx='270' cy='180' r='3' fill='url(%23g)'/%3E%3Ccircle cx='480' cy='110' r='2' fill='url(%23g)'/%3E%3Ccircle cx='890' cy='190' r='3' fill='url(%23g)'/%3E%3Ccircle cx='1260' cy='130' r='2' fill='url(%23g)'/%3E%3Ccircle cx='1460' cy='320' r='3' fill='url(%23g)'/%3E%3C/g%3E%3C/svg%3E");background-size:cover;background-position:center;animation:cyberDrift 24s ease-in-out infinite alternate}@keyframes cyberDrift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(-18px,-12px,0) scale(1.035)}}
.shell{background:transparent!important}.main{background:transparent!important}.content{max-width:1840px!important;margin-inline:auto!important;padding:clamp(20px,1.5vw,34px)!important}.sidebar{background:linear-gradient(180deg,rgba(3,12,30,.86),rgba(4,18,43,.62))!important;border-right:1px solid var(--cyber-line)!important;border-left:0!important;box-shadow:24px 0 90px rgba(0,0,0,.36),inset -1px 0 0 rgba(255,255,255,.04)!important;backdrop-filter:blur(28px) saturate(150%)!important;border-radius:0 28px 28px 0!important}.brand{padding-bottom:24px!important}.brand .gift,.login-logo-mark{background:linear-gradient(145deg,rgba(14,165,255,.95),rgba(139,92,246,.92))!important;border:1px solid rgba(94,234,212,.35)!important;color:white!important;box-shadow:0 0 26px rgba(14,165,255,.32),0 0 44px rgba(139,92,246,.22)!important;border-radius:18px!important}.brand strong{letter-spacing:.2px!important}.brand small{color:var(--cyber-muted)!important}.nav-label{color:#8ea5c7!important;letter-spacing:.02em!important;text-transform:none!important}.nav-label span:last-child{display:none!important}.navitem{border:0!important;background:transparent!important;color:#c7d2e9!important;border-radius:16px!important;min-height:46px!important;margin:7px 0!important;position:relative!important;overflow:hidden!important}.navitem span{background:rgba(14,165,255,.08)!important;border:1px solid rgba(34,211,238,.12)!important;color:#dff8ff!important}.navitem:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(14,165,255,.13),rgba(139,92,246,.12));opacity:0;transition:.22s ease}.navitem:hover:before,.navitem.active:before{opacity:1}.navitem:hover{transform:translateX(2px)!important;color:white!important;box-shadow:0 0 24px rgba(34,211,238,.09)!important}.navitem.active{background:linear-gradient(90deg,rgba(14,165,255,.28),rgba(139,92,246,.34))!important;color:#fff!important;box-shadow:inset 3px 0 0 var(--cyber-cyan),0 0 28px rgba(14,165,255,.22)!important}.navitem b,.navitem span{position:relative;z-index:1}.langbox{display:none!important}.sidebar-footer .nav-label{display:none!important}.theme-dots{background:rgba(7,24,54,.34)!important;border:1px solid var(--cyber-line)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.06)!important}.topbar{height:74px!important;background:rgba(3,10,26,.55)!important;border-bottom:1px solid rgba(56,189,248,.14)!important;backdrop-filter:blur(28px) saturate(150%)!important;box-shadow:0 18px 60px rgba(0,0,0,.18)!important}.menu-square,.search-toggle,.icon-btn,.admin-avatar-btn,.logout-icon-btn{background:linear-gradient(180deg,rgba(15,35,70,.76),rgba(7,20,48,.52))!important;border:1px solid var(--cyber-line)!important;color:white!important;box-shadow:var(--cyber-glow)!important}.searchbox{background:linear-gradient(180deg,rgba(8,25,56,.72),rgba(5,15,38,.52))!important;border:1px solid rgba(56,189,248,.22)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 0 36px rgba(14,165,255,.08)!important}.searchbox input{color:white!important}.avatar{background:linear-gradient(145deg,var(--cyber-blue),var(--cyber-purple))!important;box-shadow:0 0 26px rgba(34,211,238,.25)!important}.avatar img,.profile-avatar-preview img{width:100%;height:100%;object-fit:cover;border-radius:inherit}
.panel,.card,.tablebox,.metric,.resource-card,.server-card,.modal-card,.profile-card,.login-card{background:linear-gradient(180deg,rgba(13,33,68,.64),rgba(4,15,36,.45))!important;border:1px solid rgba(56,189,248,.22)!important;box-shadow:var(--cyber-shadow),inset 0 1px 0 rgba(255,255,255,.07)!important;backdrop-filter:blur(24px) saturate(155%)!important;border-radius:var(--cyber-radius)!important;position:relative}.panel:after,.card:after,.tablebox:after,.metric:after,.resource-card:after,.server-card:after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:linear-gradient(135deg,rgba(34,211,238,.11),transparent 35%,rgba(139,92,246,.12));opacity:.72}.panel>*,.card>*,.tablebox>*,.metric>*,.resource-card>*,.server-card>*{position:relative;z-index:1}.metric{min-height:154px!important}.metric .icon{display:none!important}.metric .label{font-size:clamp(12px,.8vw,14px)!important;color:#aabbd8!important}.metric .value,.value{font-size:clamp(20px,1.35vw,28px)!important;line-height:1.05!important}.metric .value.monthly-value{font-size:clamp(18px,1.15vw,24px)!important}.trend{border:0!important;background:transparent!important;padding:0!important;font-size:clamp(11px,.72vw,13px)!important}.trend.up{color:#22e584!important}.trend.down{color:#ff4d79!important}.trend.neutral{color:#fbbf24!important}.muted{color:var(--cyber-muted)!important}.grid4{grid-template-columns:repeat(5,minmax(170px,1fr))!important;gap:clamp(14px,1vw,22px)!important}.dashboard-grid{grid-template-columns:minmax(0,1.55fr) minmax(360px,.75fr)!important;gap:clamp(16px,1.1vw,24px)!important}.chart-wrap,.apex-chart,#revenueChart{height:clamp(320px,22vw,440px)!important;min-height:300px!important;max-height:460px!important;overflow:hidden!important;touch-action:pan-y!important}.apexcharts-canvas{max-width:100%!important}.resource-grid{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:clamp(14px,1vw,22px)!important;margin-bottom:clamp(18px,1.2vw,26px)!important}.resource-card{min-height:170px!important;overflow:hidden!important}.resource-card .resource-icon{display:none!important}.resource-title{font-size:clamp(13px,.85vw,15px)!important;color:#aabbd8!important}.resource-value{font-size:clamp(22px,1.55vw,32px)!important}.resource-detail{font-size:clamp(12px,.78vw,14px)!important;color:var(--cyber-muted)!important}.resource-bar{height:8px!important;background:rgba(148,163,184,.13)!important;border-radius:999px!important;overflow:hidden!important}.resource-bar span{background:linear-gradient(90deg,var(--cyber-blue),var(--cyber-cyan),var(--cyber-purple))!important;box-shadow:0 0 22px rgba(34,211,238,.42)!important;border-radius:999px!important}.resource-card:before{content:"";position:absolute;right:18px;top:18px;width:70px;height:70px;border-radius:50%;background:conic-gradient(var(--cyber-cyan) calc(var(--p,60)*1%),rgba(148,163,184,.13) 0);mask:radial-gradient(farthest-side,transparent 62%,#000 64%);opacity:.85}
button,.btn,a.btn,.primary,.ghost,.danger,.success,.range-tabs button,.profile-upload-label,.login-password-toggle,.login-submit{border:0!important;background:linear-gradient(135deg,rgba(14,165,255,.92),rgba(139,92,246,.88))!important;color:#fff!important;border-radius:14px!important;box-shadow:0 0 24px rgba(14,165,255,.22),0 16px 34px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.18)!important;transition:transform .18s ease,filter .18s ease,box-shadow .18s ease!important;text-shadow:0 1px 10px rgba(0,0,0,.2)!important}button:hover,.btn:hover,a.btn:hover,.range-tabs button:hover,.login-password-toggle:hover{transform:translateY(-2px)!important;filter:brightness(1.12)!important;box-shadow:0 0 34px rgba(34,211,238,.34),0 20px 46px rgba(0,0,0,.38)!important}button:active,.btn:active{transform:translateY(0) scale(.985)!important}.ghost{background:linear-gradient(135deg,rgba(8,30,68,.82),rgba(24,18,62,.68))!important;border:1px solid rgba(56,189,248,.22)!important}.danger{background:linear-gradient(135deg,#ff2d6f,#7c2dff)!important}.success{background:linear-gradient(135deg,#0fbd7a,#0ea5ff)!important}.range-tabs button.active,.range-tabs button.primary{background:linear-gradient(135deg,var(--cyber-blue),var(--cyber-purple))!important;color:#fff!important}.btn svg,button svg{display:none!important}input,select,textarea{background:rgba(4,18,43,.66)!important;border:1px solid rgba(56,189,248,.22)!important;color:#eff6ff!important;border-radius:14px!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)!important}input:focus,select:focus,textarea:focus{border-color:rgba(34,211,238,.68)!important;box-shadow:0 0 0 4px rgba(34,211,238,.11),0 0 28px rgba(14,165,255,.18)!important}label{color:#aabbd8!important}.table-scroll{background:transparent!important;border-color:rgba(56,189,248,.16)!important}table{background:transparent!important}th{background:rgba(4,18,43,.78)!important;color:#9fb5d5!important;border-bottom:1px solid rgba(56,189,248,.16)!important}td{border-bottom:1px solid rgba(56,189,248,.1)!important}tr:hover td{background:rgba(14,165,255,.055)!important}.pill,.badge,.ui-chip{border:0!important;background:rgba(14,165,255,.12)!important;color:#bfefff!important}.pill.ok{background:rgba(34,197,94,.14)!important;color:#22e584!important}.pill.warn{background:rgba(245,158,11,.16)!important;color:#fbbf24!important}.pill.bad{background:rgba(251,63,105,.15)!important;color:#ff6b8f!important}.orders{background:transparent!important}.order-row{border-bottom:1px solid rgba(56,189,248,.12)!important}.empty-state{background:rgba(4,18,43,.35)!important;border:1px dashed rgba(56,189,248,.24)!important;color:var(--cyber-muted)!important}.toast{background:rgba(4,18,43,.88)!important;border:1px solid rgba(56,189,248,.22)!important;color:white!important;backdrop-filter:blur(18px)!important}.modal{background:rgba(2,6,23,.76)!important}.modal-card{background:linear-gradient(180deg,rgba(13,33,68,.92),rgba(4,15,36,.88))!important}
.login-wrap{min-height:100dvh!important;display:grid!important;place-items:center!important;padding:clamp(20px,4vw,64px)!important;overflow:hidden!important}.login-card{width:min(460px,92vw)!important;min-height:auto!important;text-align:center!important;padding:clamp(26px,3vw,44px)!important;border-radius:30px!important;animation:loginFloat .72s cubic-bezier(.16,1,.3,1) both}.login-card:before{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(34,211,238,.9),rgba(139,92,246,.85),rgba(217,70,239,.7));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}.login-logo-mark{width:64px;height:64px;margin:0 auto 14px;display:grid;place-items:center;font-size:36px}.login-card .logo{font-size:clamp(32px,3vw,44px)!important;text-align:center!important}.login-subtitle{margin:8px 0 26px!important;text-align:center!important}.login-field{text-align:left!important;margin-bottom:14px!important}.login-field label{font-size:13px!important;margin:0 0 8px!important}.login-card input{height:48px!important;text-align:left!important}.login-password-wrap{display:flex!important;align-items:center!important;gap:8px!important;background:rgba(4,18,43,.66)!important;border:1px solid rgba(56,189,248,.22)!important;border-radius:14px!important;padding:0 6px 0 0!important}.login-password-wrap input{border:0!important;background:transparent!important;box-shadow:none!important}.login-password-toggle{min-height:36px!important;padding:0 12px!important;font-size:12px!important;white-space:nowrap!important}.login-submit{width:100%!important;margin-top:12px!important;height:50px!important}.login-helper,.copyright{text-align:center!important}.login-orb{position:absolute;border-radius:50%;filter:blur(18px);opacity:.52;pointer-events:none}.login-orb-a{width:260px;height:260px;left:8%;top:18%;background:rgba(14,165,255,.25);animation:orbMove 11s ease-in-out infinite alternate}.login-orb-b{width:320px;height:320px;right:7%;bottom:12%;background:rgba(139,92,246,.22);animation:orbMove 13s ease-in-out infinite alternate-reverse}@keyframes loginFloat{from{opacity:0;transform:translateY(18px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}@keyframes orbMove{to{transform:translate3d(28px,-18px,0) scale(1.08)}}
@media(min-width:1900px){.content{max-width:1900px!important}.grid4{grid-template-columns:repeat(5,minmax(190px,1fr))!important}.resource-card{min-height:185px!important}.metric{min-height:170px!important}.chart-wrap,.apex-chart,#revenueChart{height:430px!important}.orders{max-height:430px!important}}@media(max-width:1500px){.grid4{grid-template-columns:repeat(3,minmax(0,1fr))!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}}@media(max-width:920px){.sidebar{border-radius:0 26px 26px 0!important}.content{padding:16px 12px 80px!important}.grid4,.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.resource-card,.metric{min-height:126px!important}.dashboard-grid{grid-template-columns:1fr!important}.chart-wrap,.apex-chart,#revenueChart{height:245px!important}.topbar{padding:0 12px!important}.searchbox{position:fixed!important;left:12px!important;right:12px!important;top:72px!important;width:auto!important;display:flex!important;opacity:0;pointer-events:none;transform:translateY(-8px);transition:.18s ease}body.search-open .searchbox,.searchbox.search-open{opacity:1!important;pointer-events:auto!important;transform:translateY(0)!important}}@media(max-width:560px){.grid4,.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:10px!important}.metric,.resource-card{padding:12px!important;border-radius:18px!important;min-height:118px!important}.metric .value,.resource-value{font-size:20px!important}.metric .label,.resource-title{font-size:11px!important}.dashboard-grid{gap:12px!important}.range-tabs{grid-template-columns:repeat(2,minmax(0,1fr))!important}.login-card{width:94vw!important;padding:24px 18px!important}.login-logo-mark{width:56px;height:56px;font-size:30px}.order-row{grid-template-columns:1fr!important}.table-scroll{overflow-x:auto!important}}

/* === v1.3.42 cyber reference UI final pass === */
:root{--cyber-bg:#020617;--cyber-panel:rgba(3,18,45,.56);--cyber-panel-2:rgba(8,29,70,.62);--cyber-line:rgba(57,210,255,.23);--cyber-line-strong:rgba(155,92,255,.42);--cyber-text:#f7fbff;--cyber-muted:#9fb3d9;--cyber-blue:#0ea5ff;--cyber-cyan:#22d3ee;--cyber-purple:#8b5cf6;--cyber-pink:#d946ef;--cyber-green:#22e584;--cyber-red:#ff4d79;--cyber-yellow:#fbbf24;--cyber-radius:18px;--cyber-shadow:0 28px 90px rgba(0,0,0,.44),0 0 80px rgba(14,165,255,.08)}
html,body{background:#020617!important;color:var(--cyber-text)!important;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,Arial,sans-serif!important}body:before{content:""!important;position:fixed!important;inset:0!important;z-index:-3!important;pointer-events:none!important;background:radial-gradient(circle at 50% 35%,rgba(34,211,238,.20),transparent 24%),radial-gradient(circle at 80% 12%,rgba(139,92,246,.24),transparent 28%),radial-gradient(circle at 13% 10%,rgba(14,165,255,.18),transparent 30%),linear-gradient(180deg,#04091d 0%,#020617 46%,#020617 100%)!important;mask-image:none!important}body:after{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:linear-gradient(rgba(57,210,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(57,210,255,.035) 1px,transparent 1px),radial-gradient(ellipse at bottom,rgba(14,165,255,.22),transparent 38%);background-size:64px 64px,64px 64px,100% 100%;animation:cyberGrid 18s linear infinite}.login-wrap:after,.shell:after{content:"";position:fixed;left:0;right:0;bottom:0;height:48vh;z-index:-1;pointer-events:none;background:linear-gradient(to top,rgba(1,8,24,.96),transparent 76%),linear-gradient(90deg,transparent 0 4%,rgba(14,165,255,.38) 4.4% 4.7%,transparent 5.1% 13%,rgba(139,92,246,.34) 13.4% 13.8%,transparent 14.2% 23%,rgba(34,211,238,.32) 23.3% 23.65%,transparent 24% 33%,rgba(217,70,239,.28) 33.2% 33.6%,transparent 34% 46%,rgba(14,165,255,.24) 46.5% 47%,transparent 47.4% 58%,rgba(139,92,246,.30) 58.3% 58.8%,transparent 59.2% 72%,rgba(34,211,238,.22) 72.4% 72.8%,transparent 73.2%),linear-gradient(to top,rgba(6,22,60,.96),rgba(4,13,36,.25));clip-path:polygon(0 100%,0 54%,4% 54%,4% 29%,8% 29%,8% 62%,12% 62%,12% 40%,17% 40%,17% 69%,23% 69%,23% 33%,27% 33%,27% 64%,35% 64%,35% 43%,40% 43%,40% 76%,48% 76%,48% 35%,53% 35%,53% 67%,60% 67%,60% 28%,64% 28%,64% 72%,72% 72%,72% 46%,78% 46%,78% 75%,86% 75%,86% 38%,91% 38%,91% 64%,100% 64%,100% 100%);opacity:.75;filter:drop-shadow(0 -20px 45px rgba(14,165,255,.16))}@keyframes cyberGrid{from{background-position:0 0,0 0,0 0}to{background-position:0 64px,64px 0,0 0}}
.langbox{display:none!important}.sidebar-footer .nav-label{display:none!important}.theme-dots{background:transparent!important;border:0!important;padding:0!important}.shell{direction:ltr!important}.main{direction:ltr!important}.content{max-width:1840px!important;margin:0 auto!important;padding:clamp(18px,1.55vw,34px)!important}.sidebar{direction:ltr!important;width:300px!important;min-width:300px!important;background:linear-gradient(180deg,rgba(5,20,50,.86),rgba(2,10,28,.78))!important;border:1px solid rgba(57,210,255,.22)!important;border-radius:0 28px 28px 0!important;box-shadow:24px 0 90px rgba(0,0,0,.35),0 0 55px rgba(14,165,255,.12)!important;backdrop-filter:blur(24px) saturate(160%)!important;padding:22px 16px!important;overflow:auto!important}.brand{padding:6px 10px 24px!important;justify-content:flex-start!important}.brand .gift,.login-logo-mark{border-radius:18px!important;background:linear-gradient(145deg,#19c7ff,#7434ff 52%,#d946ef)!important;box-shadow:0 0 28px rgba(34,211,238,.34),0 0 48px rgba(139,92,246,.24)!important;color:white!important}.brand .gift{font-size:0!important}.brand .gift:before,.login-logo-mark:before{content:"◇";font-size:30px}.brand strong{font-size:25px!important;letter-spacing:.02em!important}.brand small{display:none!important}.nav-label{font-size:12px!important;text-transform:none!important;letter-spacing:.02em!important;color:#8da6cf!important;padding:12px 12px 8px!important}.nav-label span:last-child{display:none!important}.navitem{background:transparent!important;border:0!important;box-shadow:none!important;border-radius:14px!important;color:#d6e4ff!important;margin:4px 0!important;padding:11px 12px!important;gap:12px!important}.navitem span{background:transparent!important;border-radius:0!important;width:20px!important;height:20px!important;font-size:14px!important;opacity:.78}.navitem:hover{background:rgba(14,165,255,.08)!important;box-shadow:inset 0 0 0 1px rgba(57,210,255,.13)!important;transform:none!important;color:#fff!important}.navitem.active{background:linear-gradient(90deg,rgba(14,165,255,.78),rgba(139,92,246,.86))!important;border:0!important;box-shadow:0 10px 30px rgba(14,165,255,.20),0 0 28px rgba(139,92,246,.22)!important;color:#fff!important}.topbar{height:72px!important;background:rgba(2,8,25,.52)!important;border-bottom:1px solid rgba(57,210,255,.13)!important;backdrop-filter:blur(18px)!important}.menu-square,.icon-btn,.search-toggle,.admin-avatar-btn,.logout-icon-btn{background:rgba(6,22,55,.64)!important;border:1px solid rgba(57,210,255,.22)!important;color:#dff7ff!important;box-shadow:0 0 22px rgba(14,165,255,.08)!important}.searchbox{background:rgba(4,18,43,.66)!important;border:1px solid rgba(57,210,255,.23)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 0 30px rgba(14,165,255,.07)!important}.page-head{direction:ltr!important}.breadcrumbs{color:#8da6cf!important}h1,h2,h3{letter-spacing:-.03em!important}.panel,.card,.tablebox,.metric,.resource-card,.server-card,.modal-card,.profile-card,.login-card{background:linear-gradient(180deg,rgba(10,32,74,.62),rgba(3,13,34,.50))!important;border:1px solid rgba(57,210,255,.23)!important;border-radius:22px!important;box-shadow:var(--cyber-shadow),inset 0 1px 0 rgba(255,255,255,.06)!important;backdrop-filter:blur(24px) saturate(160%)!important;position:relative!important;overflow:hidden!important}.panel:before,.card:before,.tablebox:before,.metric:before,.resource-card:before,.server-card:before,.modal-card:before,.profile-card:before,.login-card:before{content:""!important;position:absolute!important;inset:0!important;border-radius:inherit!important;background:linear-gradient(135deg,rgba(34,211,238,.10),transparent 38%,rgba(139,92,246,.12))!important;pointer-events:none!important}.panel>*,.card>*,.tablebox>*,.metric>*,.resource-card>*,.server-card>*,.login-card>*{position:relative!important;z-index:1!important}.grid4{grid-template-columns:repeat(5,minmax(180px,1fr))!important;gap:clamp(14px,1vw,22px)!important}.metric{min-height:154px!important;padding:20px!important}.metric .icon{display:none!important}.metric .label{font-size:clamp(12px,.78vw,14px)!important;color:#aabbd8!important}.metric .value,.value{font-size:clamp(19px,1.28vw,27px)!important}.metric .value.monthly-value{font-size:clamp(17px,1.05vw,23px)!important}.trend{background:transparent!important;border:0!important;padding:0!important;font-size:clamp(11px,.7vw,13px)!important}.resource-grid{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:clamp(14px,1vw,22px)!important;margin-bottom:clamp(18px,1.2vw,26px)!important}.resource-card{min-height:172px!important;padding:16px!important;text-align:center!important;display:flex!important;flex-direction:column!important;align-items:center!important;justify-content:space-between!important}.resource-title{font-size:13px!important;color:#cde4ff!important;font-weight:800!important;align-self:flex-start!important}.resource-value,.resource-icon{display:none!important}.resource-ring{width:86px!important;height:86px!important;border-radius:50%!important;display:grid!important;place-items:center!important;background:conic-gradient(var(--cyber-cyan) calc(var(--p,0)*1%),rgba(77,113,171,.24) 0)!important;box-shadow:0 0 28px rgba(14,165,255,.18)!important;position:relative!important}.resource-ring:after{content:"";position:absolute;inset:10px;border-radius:50%;background:linear-gradient(180deg,rgba(5,18,45,.96),rgba(5,12,30,.92));box-shadow:inset 0 0 22px rgba(14,165,255,.08)}.resource-ring span{position:relative;z-index:1;font-weight:900;font-size:22px;color:white}.resource-detail{font-size:12px!important;color:#9fb3d9!important}.resource-bar{height:5px!important;width:100%!important;background:rgba(77,113,171,.24)!important;border-radius:999px!important;overflow:hidden!important}.resource-bar span{display:block!important;height:100%!important;background:linear-gradient(90deg,var(--cyber-blue),var(--cyber-purple))!important;border-radius:inherit!important;box-shadow:0 0 18px rgba(139,92,246,.36)!important}.dashboard-grid{grid-template-columns:minmax(0,1.52fr) minmax(360px,.78fr)!important;gap:clamp(16px,1.1vw,24px)!important}.chart-wrap,.apex-chart,#revenueChart{height:clamp(310px,21vw,430px)!important;overflow:hidden!important;touch-action:pan-y!important;overscroll-behavior:contain!important}.orders{max-height:clamp(300px,21vw,430px)!important;overflow:auto!important;padding-right:6px!important}.order-row{grid-template-columns:1fr 90px 72px 110px!important;border-bottom:1px solid rgba(57,210,255,.11)!important}.btn,button,a.btn,.primary,.danger,.ghost{border:0!important;border-radius:14px!important;background:linear-gradient(135deg,rgba(14,165,255,.78),rgba(139,92,246,.80))!important;color:white!important;box-shadow:0 12px 32px rgba(14,165,255,.18),inset 0 1px 0 rgba(255,255,255,.14)!important;transition:transform .18s ease,box-shadow .18s ease,filter .18s ease!important;text-decoration:none!important}.btn:hover,button:hover,a.btn:hover{transform:translateY(-2px)!important;box-shadow:0 18px 42px rgba(14,165,255,.24),0 0 34px rgba(139,92,246,.22)!important;filter:saturate(1.12)!important}.danger,.btn.danger{background:linear-gradient(135deg,rgba(217,70,239,.70),rgba(244,63,94,.72))!important}.ghost,.btn.ghost{background:linear-gradient(135deg,rgba(14,165,255,.25),rgba(139,92,246,.20))!important}input,select,textarea{background:rgba(3,16,43,.66)!important;border:1px solid rgba(57,210,255,.23)!important;color:white!important;border-radius:14px!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.05)!important}input:focus,select:focus,textarea:focus{outline:0!important;border-color:rgba(34,211,238,.7)!important;box-shadow:0 0 0 4px rgba(34,211,238,.10),0 0 30px rgba(14,165,255,.18)!important}label{color:#d8e7ff!important}.table-scroll{background:transparent!important}table,th,td{background:transparent!important}th{color:#9fb5d5!important;border-bottom:1px solid rgba(57,210,255,.15)!important}td{border-bottom:1px solid rgba(57,210,255,.10)!important}.pill,.badge{border:0!important}.pill.ok{background:rgba(34,229,132,.14)!important;color:var(--cyber-green)!important}.pill.warn{background:rgba(251,191,36,.14)!important;color:var(--cyber-yellow)!important}.pill.bad{background:rgba(255,77,121,.14)!important;color:var(--cyber-red)!important}::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:rgba(3,16,43,.42);border-radius:999px}::-webkit-scrollbar-thumb{background:linear-gradient(180deg,var(--cyber-blue),var(--cyber-purple));border-radius:999px;box-shadow:0 0 16px rgba(14,165,255,.25)}
.login-wrap{min-height:100dvh!important;display:grid!important;place-items:center!important;padding:clamp(20px,4vw,64px)!important;overflow:hidden!important}.login-card{width:min(480px,92vw)!important;text-align:center!important;padding:clamp(28px,3vw,46px)!important;border-radius:30px!important;animation:loginFloat .7s cubic-bezier(.16,1,.3,1) both}.login-card .logo{font-size:clamp(34px,3vw,46px)!important;text-align:center!important;font-weight:950!important}.login-subtitle,.login-helper,.copyright{text-align:center!important}.login-field{display:grid!important;grid-template-columns:92px minmax(0,1fr)!important;align-items:center!important;gap:14px!important;text-align:left!important;margin-bottom:14px!important}.login-field label{margin:0!important;font-weight:800!important}.login-card input{height:48px!important;text-align:left!important}.login-password-wrap{display:flex!important;align-items:center!important;background:rgba(3,16,43,.66)!important;border:1px solid rgba(57,210,255,.23)!important;border-radius:14px!important}.login-password-wrap input{border:0!important;background:transparent!important;box-shadow:none!important}.login-password-toggle{min-height:36px!important;padding:0 12px!important;font-size:12px!important;background:transparent!important;box-shadow:none!important;color:#dff7ff!important}.login-submit{width:100%!important;height:52px!important;margin-top:12px!important}.login-orb{filter:blur(22px)!important;opacity:.55!important}@keyframes loginFloat{from{opacity:0;transform:translateY(18px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
@media(min-width:1900px){.content{max-width:1900px!important}.resource-card{min-height:185px!important}.resource-ring{width:96px!important;height:96px!important}.metric{min-height:166px!important}.chart-wrap,.apex-chart,#revenueChart{height:430px!important}}@media(max-width:1500px){.grid4{grid-template-columns:repeat(3,minmax(0,1fr))!important}.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}}@media(max-width:920px){.sidebar{position:fixed!important;transform:translateX(-110%)!important;height:100dvh!important;z-index:80!important}.sidebar.open,body.sidebar-open .sidebar{transform:translateX(0)!important}.mobile-sidebar-backdrop{display:block!important}.grid4,.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.dashboard-grid{grid-template-columns:1fr!important}.content{padding:14px 10px 80px!important}.topbar{height:62px!important;padding:0 10px!important}.chart-wrap,.apex-chart,#revenueChart{height:245px!important}.resource-card{min-height:145px!important}.resource-ring{width:72px!important;height:72px!important}.resource-ring span{font-size:18px!important}.searchbox{position:fixed!important;left:12px!important;right:12px!important;top:72px!important;width:auto!important;opacity:0;pointer-events:none;transform:translateY(-8px);transition:.18s ease;z-index:90!important}body.search-open .searchbox{opacity:1;pointer-events:auto;transform:translateY(0)}}@media(max-width:560px){.grid4,.resource-grid{gap:9px!important}.metric,.resource-card,.panel,.tablebox,.card{border-radius:18px!important;padding:10px!important}.resource-card{min-height:132px!important}.resource-ring{width:64px!important;height:64px!important}.resource-ring:after{inset:8px!important}.resource-ring span{font-size:16px!important}.resource-title{font-size:11px!important}.resource-detail{font-size:10px!important}.metric .value,.value{font-size:17px!important}.metric .label{font-size:10px!important}.range-tabs{grid-template-columns:repeat(2,minmax(0,1fr))!important}.login-field{grid-template-columns:1fr!important;gap:6px!important}.login-card{width:94vw!important;padding:24px 18px!important}.order-row{grid-template-columns:1fr!important}}

'''
SCRIPT = r'''

// === v1.3.33 robust sidebar toggle ===
function dbotIsMobileSidebar(){return window.matchMedia('(max-width: 760px)').matches;}
function dbotOpenMobileSidebar(){document.body.classList.add('sidebar-open');document.body.classList.remove('sidebar-collapsed','sidebar-desktop-hidden');}
function dbotCloseMobileSidebar(){document.body.classList.remove('sidebar-open');}
function dbotToggleSidebar(){
  if(dbotIsMobileSidebar()){
    document.body.classList.contains('sidebar-open') ? dbotCloseMobileSidebar() : dbotOpenMobileSidebar();
  }else{
    document.body.classList.remove('sidebar-open','sidebar-collapsed');
    document.body.classList.toggle('sidebar-desktop-hidden');
  }
}
let pendingDeleteUrl=null;
function openModal(id){document.getElementById(id)?.classList.add('open')}
function closeModal(id){document.getElementById(id)?.classList.remove('open')}
function notify(msg, ok=true){let t=document.getElementById('session-toast')||document.createElement('div');t.id='session-toast';t.className='toast';document.body.appendChild(t);t.style.borderColor=ok?'var(--success)':'var(--danger)';t.style.display='block';t.style.opacity='1';t.style.transform='translateY(0)';t.textContent=String(msg||'');clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>{t.style.opacity='0';t.style.transform='translateY(10px)';setTimeout(()=>{t.style.display='none'},1200)},4000)}
async function readJsonOrError(r){let text=await r.text();try{return JSON.parse(text)}catch(e){let clean=text.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();return {ok:false,message:clean||('HTTP '+r.status)}}}
function csrfToken(){return (document.cookie.split('; ').find(x=>x.startsWith('dbot_csrf_token='))||'').split('=').slice(1).join('=')}
function secureHeaders(){return {'X-Requested-With':'fetch','Accept':'application/json','X-CSRF-Token':decodeURIComponent(csrfToken()||'')}}
async function postForm(form){const btn=form.querySelector('button[type=submit],button:not([type])'); if(btn)btn.classList.add('loading'); try{let r=await fetch(form.action,{method:(form.method||'POST').toUpperCase(),body:new FormData(form),headers:secureHeaders()});let ct=(r.headers.get('content-type')||'').toLowerCase();if(r.redirected||ct.includes('text/html')){location.href=r.url||location.href;return false;}let j=await readJsonOrError(r);if(!j.ok){notify(j.message||'Error',false);return false;}notify(j.message||'Saved',true);setTimeout(()=>{location.href=j.redirect||location.href},700);return false}catch(e){notify('Request failed',false);return false}}
async function callAction(url){try{let join=url.includes('?')?'&':'?';let r=await fetch(url+join+'ajax=1',{method:'POST',headers:secureHeaders()});let j=await readJsonOrError(r);if(!j.ok){notify(j.message||'Error',false);return}notify(j.message||'Done',true);setTimeout(()=>{location.href=j.redirect||location.href},700)}catch(e){notify('Request failed',false)}}
function askDelete(url){pendingDeleteUrl=url;openModal('confirmDeleteModal')}
function confirmDelete(){let u=pendingDeleteUrl;pendingDeleteUrl=null;closeModal('confirmDeleteModal');if(u)callAction(u)}
const DBOT_I18N={};
function setLang(lang){localStorage.setItem('dbot_lang',lang);document.documentElement.lang=lang==='en'?'en':'fa';document.documentElement.dir=lang==='en'?'ltr':'rtl';document.querySelectorAll('[data-fa]').forEach(el=>{let v=el.getAttribute(lang==='en'?'data-en':'data-fa'); if(v) el.textContent=v});document.querySelectorAll('[data-fa-placeholder]').forEach(el=>{let v=el.getAttribute(lang==='en'?'data-en-placeholder':'data-fa-placeholder'); if(v) el.placeholder=v}); if(lang==='en'){document.querySelectorAll('body *').forEach(el=>{if(el.children.length===0){let t=(el.textContent||'').trim(); if(DBOT_I18N[t]) el.textContent=DBOT_I18N[t];}})} }
function setTheme(t){document.body.dataset.theme=t;localStorage.setItem('dbot_theme',t);document.querySelectorAll('[data-theme-btn]').forEach(b=>b.classList.toggle('primary',b.dataset.themeBtn===t));}
/* submit handled by dbot v1.3.11 patch */
document.addEventListener('click',e=>{let a=e.target.closest('a[data-action]');if(a){e.preventDefault();callAction(a.href)}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.querySelectorAll('.modal.open').forEach(m=>m.classList.remove('open'))}});
document.addEventListener('DOMContentLoaded',()=>{setLang(localStorage.getItem('dbot_lang')||'en');setTheme(localStorage.getItem('dbot_theme')||'theme-1');let timeout=parseInt(document.documentElement.dataset.timeout||document.body.dataset.timeout||'1800');let warn=Math.max(1,timeout-300)*1000;setTimeout(()=>notify(localStorage.getItem('dbot_lang')==='en'?'You will be logged out automatically in 5 minutes.':'You will be logged out automatically in 5 minutes.',false),warn)});


// D BOT UI active controls
(function(){
  function qs(s,root=document){return root.querySelector(s)}
  function qsa(s,root=document){return [...root.querySelectorAll(s)]}
  window.dbotFilterPage=function(term){
    term=(term||'').toString().trim().toLowerCase();
    qsa('.card,.tablebox tbody tr,.orders .order-row').forEach(el=>{
      if(!term){el.style.display='';return}
      el.style.display=el.textContent.toLowerCase().includes(term)?'':'none';
    });
  }
  document.addEventListener('input',e=>{if(e.target && e.target.id==='globalSearch') dbotFilterPage(e.target.value)});
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='/'){e.preventDefault();let i=qs('#globalSearch'); if(i){i.focus(); i.select();}}});
  document.addEventListener('click',e=>{
    let b=e.target.closest('[data-ui-action]'); if(!b) return;
    let a=b.dataset.uiAction;
    if(a==='toggle-sidebar'){dbotToggleSidebar();}
    if(a==='notify'){notify(localStorage.getItem('dbot_lang')==='en'?'No new notification.':'No new notification.',true);}
    if(a==='cycle-theme'){
      let cur=localStorage.getItem('dbot_theme')||document.body.dataset.theme||'theme-1';
      let n=(parseInt((cur.match(/\d+/)||['1'])[0])%6)+1; setTheme('theme-'+n);
    }
    if(a==='fullscreen'){
      if(!document.fullscreenElement){document.documentElement.requestFullscreen?.();}else{document.exitFullscreen?.();}
    }
    if(a==='profile'){notify(localStorage.getItem('dbot_lang')==='en'?'Profile menu is ready. Use Logout to exit.':'Profile menu is ready. Use Logout to exit.',true);}
  });
})();

// Real Monthly Sales chart - uses only database API data, no fake/mock values. Metric compares current calendar month with last month.
(function(){
  let chart=null;
  function fmt(v){try{return new Intl.NumberFormat('en-US').format(v||0)}catch(e){return String(v||0)}}
  function chartFont(el){const w=(el&&el.clientWidth)||360; return w<300?'8px':(w<430?'9px':'11px');}
  function chartHeight(el){const w=(el&&el.clientWidth)||360; return Math.max(190, Math.min(330, Math.round(w*0.56)));}

  function labelStep(days){days=parseInt(days||30,10); if(days===14) return 2; if(days===30) return 5; if(days===90) return 10; return 1;}
  async function loadDashboard(days){
    const el=document.getElementById('revenueChart'); if(!el) return;
    days=parseInt(days||30); if(![7,14,30,90].includes(days)) days=30;
    const res=await fetch('/admin/api/dashboard?days='+days,{headers:{'Accept':'application/json','X-Requested-With':'fetch'}});
    const data=await res.json();
    const rows=(data.revenue||[]).slice(-days);
    const labels=rows.map(x=>x.label);
    const values=rows.map(x=>Number(x.revenue||0));
    el.innerHTML='';
    if(window.ApexCharts){
      if(chart){chart.destroy(); chart=null;}
      chart=new ApexCharts(el,{chart:{type:'area',height:chartHeight(el),toolbar:{show:false},zoom:{enabled:false,allowMouseWheelZoom:false},selection:{enabled:false},animations:{enabled:true,easing:'easeinout',speed:700},background:'transparent'},series:[{name:'Monthly Sales',data:values}],xaxis:{categories:labels,labels:{rotate:0,hideOverlappingLabels:true,trim:true,style:{colors:'var(--muted)',fontSize:chartFont(el)},formatter:function(value, timestamp, opts){const step=labelStep(days); const i=opts && typeof opts.i==='number'?opts.i:(labels.indexOf(value)); return (i===0 || i===labels.length-1 || i%step===0)?value:'';}}},yaxis:{labels:{formatter:fmt,style:{colors:'var(--muted)',fontSize:chartFont(el)}}},dataLabels:{enabled:false},stroke:{curve:'smooth',width:3},grid:{borderColor:'rgba(148,163,184,.14)',strokeDashArray:5},fill:{type:'gradient',gradient:{shadeIntensity:1,opacityFrom:.38,opacityTo:.04,stops:[0,90,100]}},tooltip:{theme:'dark',y:{formatter:(v)=>fmt(v)+' Toman'}}});
      chart.render();
    }else{
      el.innerHTML='<div class="muted" style="padding:20px">ApexCharts is not loaded.</div>';
    }
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const buttons=[...document.querySelectorAll('[data-chart-range]')];
    const active=buttons.find(b=>b.classList.contains('active'))||buttons[0];
    loadDashboard(active?active.dataset.chartRange:30);
    buttons.forEach(b=>b.addEventListener('click',()=>{buttons.forEach(x=>x.classList.remove('active')); b.classList.add('active'); loadDashboard(b.dataset.chartRange);}));
  });
})();



// Prevent Monthly Sales chart from using mouse wheel for zoom. Page scrolling remains normal.
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('#revenueChart,.apex-chart,.chart-wrap').forEach(el=>{
    el.addEventListener('wheel',(ev)=>{
      // Do not prevent default; just stop ApexCharts wheel handlers from receiving it.
      ev.stopPropagation();
    },{passive:true,capture:true});
  });
});

// === v1.3.8 button connection + chart fallback patch ===
(function(){
  function $(s,r){return (r||document).querySelector(s)}
  function $all(s,r){return Array.from((r||document).querySelectorAll(s))}
  function fallbackLabelStep(days){days=parseInt(days||30,10); if(days===14) return 2; if(days===30) return 5; if(days===90) return 10; return 1;}
  function responsiveChartFont(el){const w=(el&&el.clientWidth)||360; return w<300?'8px':(w<430?'9px':'11px');}
  function responsiveChartHeight(el){const w=(el&&el.clientWidth)||360; return Math.max(190, Math.min(330, Math.round(w*0.56)));}
  function toast(msg, ok){
    if(typeof notify === 'function'){ notify(msg, ok!==false); return; }
    alert(String(msg||'Done'));
  }
  function ajaxHeaders(){return {'X-Requested-With':'fetch','Accept':'application/json','X-CSRF-Token':decodeURIComponent((document.cookie.split('; ').find(x=>x.startsWith('dbot_csrf_token='))||'').split('=').slice(1).join('=')||'')}}

  window.dbotPostForm = async function(form){
    try{
      const btn=form.querySelector('button[type=submit],button:not([type])');
      if(btn) btn.classList.add('loading');
      const res=await fetch(form.action || location.href, {
        method:(form.method||'POST').toUpperCase(),
        body:new FormData(form),
        headers:ajaxHeaders()
      });
      const ct=(res.headers.get('content-type')||'').toLowerCase();
      if(res.redirected || ct.includes('text/html')){
        location.href=res.url || location.href;
        return false;
      }
      const data=await res.json().catch(()=>({ok:res.ok,message:res.ok?'Saved':'Request failed'}));
      toast(data.message || (data.ok?'Saved':'Error'), data.ok!==false && res.ok);
      setTimeout(()=>{ location.href=data.redirect || location.href; }, 650);
    }catch(err){ toast(err.message || String(err), false); }
    return false;
  };

  window.dbotCallAction = async function(url){
    try{
      const join = url.includes('?') ? '&' : '?';
      const res=await fetch(url + join + 'ajax=1', {method:'POST',headers:ajaxHeaders()});
      const ct=(res.headers.get('content-type')||'').toLowerCase();
      if(res.redirected || ct.includes('text/html')){
        location.href=res.url || location.href;
        return;
      }
      const data=await res.json().catch(()=>({ok:res.ok,message:res.ok?'Done':'Request failed'}));
      toast(data.message || (data.ok?'Done':'Error'), data.ok!==false && res.ok);
      setTimeout(()=>{ location.href=data.redirect || location.href; }, 650);
    }catch(err){ toast(err.message || String(err), false); }
  };

  function drawFallbackChart(el, rows){
    rows = rows || [];
    const w = Math.max(el.clientWidth || 720, 260), h = responsiveChartHeight(el), pad = Math.max(24, Math.min(34, Math.round(w*.055)));
    const values = rows.map(r => Number(r.revenue || 0));
    const max = Math.max(1, ...values);
    const step = values.length > 1 ? (w - pad*2) / (values.length - 1) : 1;
    const pts = values.map((v,i)=>{
      const x = pad + i*step;
      const y = h - pad - ((v/max) * (h - pad*2));
      return [x,y];
    });
    const line = pts.map(p=>p.join(',')).join(' ');
    const area = pts.length ? `${pad},${h-pad} ${line} ${pad+(pts.length-1)*step},${h-pad}` : '';
    const lstep = fallbackLabelStep(rows.__rangeDays || rows.length);
    const labels = rows.filter((_,i)=> i===0 || i===rows.length-1 || i%lstep===0)
      .map((r,i)=>{
        const idx = rows.indexOf(r);
        const x = pad + idx*step;
        return `<text x="${x}" y="${h-8}" text-anchor="middle" font-size="${parseInt(responsiveChartFont(el),10)}" fill="currentColor" opacity=".55">${String(r.label||'').slice(5)}</text>`;
      }).join('');
    el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" role="img" aria-label="Monthly Sales chart">
      <defs><linearGradient id="dbotChartGrad" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="currentColor" stop-opacity=".28"/><stop offset="100%" stop-color="currentColor" stop-opacity=".02"/></linearGradient></defs>
      <g opacity=".18">${[0,1,2,3,4].map(i=>`<line x1="${pad}" x2="${w-pad}" y1="${pad+i*(h-pad*2)/4}" y2="${pad+i*(h-pad*2)/4}" stroke="currentColor"/>`).join('')}</g>
      ${area ? `<polygon points="${area}" fill="url(#dbotChartGrad)"></polygon><polyline points="${line}" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>` : ''}
      ${pts.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="currentColor"></circle>`).join('')}
      ${labels}
    </svg>`;
  }

  window.dbotLoadDashboardChart = async function(days){
    const el = document.getElementById('revenueChart');
    if(!el) return;
    days = parseInt(days || 30, 10);
    if(![7,14,30,90].includes(days)) days = 30;
    el.innerHTML = '<div class="chart-skeleton skeleton"></div>';
    try{
      const res = await fetch('/admin/api/dashboard?days=' + days, {headers:ajaxHeaders()});
      const data = await res.json();
      const rows = (data.revenue || []).slice(-days);
      rows.__rangeDays = days;
      const labels = rows.map(x=>x.label);
      const values = rows.map(x=>Number(x.revenue || 0));
      if(window.__dbotApexChart){ try{ window.__dbotApexChart.destroy(); }catch(e){} window.__dbotApexChart=null; }
      if(window.ApexCharts){
        el.innerHTML='';
        window.__dbotApexChart = new ApexCharts(el,{
          chart:{type:'area',height:responsiveChartHeight(el),toolbar:{show:false},zoom:{enabled:false,allowMouseWheelZoom:false},selection:{enabled:false},animations:{enabled:true},background:'transparent',parentHeightOffset:0},
          series:[{name:'Monthly Sales',data:values}],
          xaxis:{categories:labels,labels:{rotate:0,hideOverlappingLabels:true,trim:true,style:{colors:'var(--muted)',fontSize:responsiveChartFont(el)},formatter:function(value, timestamp, opts){const step=fallbackLabelStep(days); const i=opts && typeof opts.i==='number'?opts.i:(labels.indexOf(value)); return (i===0 || i===labels.length-1 || i%step===0)?value:'';}}},
          yaxis:{labels:{formatter:(v)=>new Intl.NumberFormat('en-US').format(v||0),style:{colors:'var(--muted)',fontSize:responsiveChartFont(el)}}},
          dataLabels:{enabled:false},
          stroke:{curve:'smooth',width:3},
          grid:{borderColor:'rgba(148,163,184,.14)',strokeDashArray:5},
          fill:{type:'gradient',gradient:{shadeIntensity:1,opacityFrom:.38,opacityTo:.04,stops:[0,90,100]}},
          tooltip:{theme:'dark',y:{formatter:(v)=>new Intl.NumberFormat('en-US').format(v||0)+' Toman'}}
        });
        window.__dbotApexChart.render();
      }else{
        drawFallbackChart(el, rows);
      }
    }catch(err){
      el.innerHTML = '<div class="empty-state">Chart data could not be loaded.</div>';
      toast(err.message || String(err), false);
    }
  };

  document.addEventListener('submit', function(e){
    const form = e.target.closest('form');
    if(!form || form.dataset.native || String(form.action||'').endsWith('/login')) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if(form.dataset.dbotSubmitting === '1') return;
    form.dataset.dbotSubmitting = '1';
    const p = window.dbotPostForm(form);
    if(p && p.finally) p.finally(()=>{form.dataset.dbotSubmitting='0'});
    else setTimeout(()=>{form.dataset.dbotSubmitting='0'}, 2000);
  }, true);

  document.addEventListener('click', function(e){
    const deleteBtn = e.target.closest('[data-delete-url]');
    if(deleteBtn){
      e.preventDefault();
      window.pendingDeleteUrl = deleteBtn.dataset.deleteUrl;
      if(typeof openModal === 'function') openModal('confirmDeleteModal');
      else if(confirm('Delete this item?')) window.dbotCallAction(window.pendingDeleteUrl);
      return;
    }

    const actionLink = e.target.closest('a[data-action]');
    if(actionLink){
      e.preventDefault();
      window.dbotCallAction(actionLink.href);
      return;
    }

    const ui = e.target.closest('[data-ui-action]');
    if(ui){
      const a = ui.dataset.uiAction;
      if(a==='toggle-sidebar') dbotToggleSidebar();
      if(a==='notify') toast('No new notification.', true);
      if(a==='cycle-theme'){
        const cur = localStorage.getItem('dbot_theme') || document.body.dataset.theme || 'theme-1';
        const n = (parseInt((cur.match(/\d+/)||['1'])[0],10) % 6) + 1;
        if(typeof setTheme === 'function') setTheme('theme-'+n);
      }
      if(a==='fullscreen'){
        if(!document.fullscreenElement) document.documentElement.requestFullscreen?.();
        else document.exitFullscreen?.();
      }
      return;
    }

    const range = e.target.closest('[data-chart-range]');
    if(range){
      e.preventDefault();
      $all('[data-chart-range]').forEach(b=>b.classList.remove('active'));
      range.classList.add('active');
      window.dbotLoadDashboardChart(range.dataset.chartRange);
      return;
    }
  }, true);

  document.addEventListener('DOMContentLoaded', function(){
    const active = $('[data-chart-range].active') || $('[data-chart-range]');
    if(active) window.dbotLoadDashboardChart(active.dataset.chartRange || 30);
    $all('button, .btn').forEach(b=>b.classList.add('rippled'));
  });
})();


// === v1.3.17 live server resources: refresh every 5 seconds ===
(function(){
  let resourceTimer=null;
  let resourceBusy=false;

  async function refreshServerResources(){
    const grid=document.getElementById('serverResourceGrid');
    if(!grid || resourceBusy) return;
    resourceBusy=true;
    grid.classList.add('updating');
    try{
      const res=await fetch('/admin/api/resources',{headers:{'Accept':'application/json','X-Requested-With':'fetch'},cache:'no-store'});
      const data=await res.json();
      if(data && data.ok && typeof data.html === 'string'){
        grid.innerHTML=data.html;
        const stamp=document.getElementById('resourceUpdated');
        if(stamp){
          const now=new Date();
          stamp.textContent='Live update: '+now.toLocaleTimeString();
        }
      }
    }catch(e){
      const stamp=document.getElementById('resourceUpdated');
      if(stamp) stamp.textContent='Live update paused';
    }finally{
      grid.classList.remove('updating');
      resourceBusy=false;
    }
  }

  document.addEventListener('DOMContentLoaded',function(){
    if(!document.getElementById('serverResourceGrid')) return;
    refreshServerResources();
    resourceTimer=setInterval(refreshServerResources,5000);
    document.addEventListener('visibilitychange',function(){
      if(document.hidden){
        if(resourceTimer){clearInterval(resourceTimer); resourceTimer=null;}
      }else if(!resourceTimer){
        refreshServerResources();
        resourceTimer=setInterval(refreshServerResources,5000);
      }
    });
  });
})();

// v1.3.26: real mobile drawer sidebar. Button opens from left; tap page/backdrop/link closes it.
(function(){
  function closeSidebar(){document.body.classList.remove('sidebar-open');}
  function openSidebar(){document.body.classList.add('sidebar-open');document.body.classList.remove('sidebar-collapsed');}
  document.addEventListener('DOMContentLoaded',function(){
    if(!document.querySelector('.mobile-sidebar-backdrop')){
      const b=document.createElement('div');b.className='mobile-sidebar-backdrop';b.setAttribute('data-close-sidebar','1');document.body.appendChild(b);
    }
  });
  document.addEventListener('click',function(e){
    const toggle=e.target.closest('[data-ui-action="toggle-sidebar"]');
    if(toggle){
      e.preventDefault();e.stopImmediatePropagation();
      if(window.matchMedia('(max-width: 760px)').matches){document.body.classList.contains('sidebar-open')?closeSidebar():openSidebar();}
      else{dbotToggleSidebar();}
      return false;
    }
    if(e.target.closest('[data-close-sidebar]')){closeSidebar();return;}
    if(window.matchMedia('(max-width: 760px)').matches){
      if(e.target.closest('.sidebar .navitem')) closeSidebar();
      const main=e.target.closest('.main');
      if(main && document.body.classList.contains('sidebar-open')) closeSidebar();
    }
  },true);
  document.addEventListener('keydown',function(e){if(e.key==='Escape') closeSidebar();});
  window.addEventListener('resize',function(){if(!window.matchMedia('(max-width: 760px)').matches) closeSidebar();});
})();



window.addEventListener('resize',function(){
  if(dbotIsMobileSidebar()) document.body.classList.remove('sidebar-desktop-hidden','sidebar-collapsed');
  else document.body.classList.remove('sidebar-open');
});

// === v1.3.28 search toggle + functional page search + profile photo ===
(function(){
  function qs(s,r){return (r||document).querySelector(s)}
  function qsa(s,r){return Array.from((r||document).querySelectorAll(s))}
  function openSearch(){document.body.classList.add('search-open');setTimeout(function(){var i=qs('#globalSearch');if(i){i.focus();i.select();}},30)}
  function closeSearch(){document.body.classList.remove('search-open')}
  function getSearchTargets(){
    var selectors=['.resource-card','.metric','.panel','.card','.tablebox tbody tr','.orders .order-row','.server-card'];
    var set=new Set();
    selectors.forEach(function(sel){qsa(sel).forEach(function(el){ if(!el.closest('.sidebar,.topbar,.modal,.profile-modal')) set.add(el); });});
    return Array.from(set);
  }
  function ensureEmpty(){var c=qs('.content'); if(!c) return null; var e=qs('#globalSearchEmpty'); if(!e){e=document.createElement('div');e.id='globalSearchEmpty';e.className='search-empty-state';e.textContent='No result found'; c.prepend(e);} return e;}
  window.dbotFilterPage=function(term){
    term=(term||'').toString().trim().toLowerCase();
    var targets=getSearchTargets(), visible=0;
    targets.forEach(function(el){
      if(!term){el.classList.remove('search-result-hidden'); visible++; return;}
      var ok=(el.textContent||'').toLowerCase().indexOf(term)>-1;
      el.classList.toggle('search-result-hidden',!ok); if(ok) visible++;
    });
    var empty=ensureEmpty(); if(empty) empty.classList.toggle('show',!!term && visible===0);
  };
  function applyAvatar(dataUrl){
    qsa('#adminAvatar,.admin-avatar-btn .avatar').forEach(function(el){
      if(dataUrl){el.style.backgroundImage='url('+dataUrl+')';el.classList.add('has-photo');el.textContent='';}
      else{el.style.backgroundImage='';el.classList.remove('has-photo');el.textContent='👤';}
    });
    var p=qs('#profileAvatarPreview'); if(p){ if(dataUrl){p.style.backgroundImage='url('+dataUrl+')';p.classList.add('has-photo');p.textContent='';}else{p.style.backgroundImage='';p.classList.remove('has-photo');p.textContent='👤';}}
  }
  function openProfile(){var m=qs('#profileModal'); if(m){m.classList.add('open');m.setAttribute('aria-hidden','false');}}
  function closeProfile(){var m=qs('#profileModal'); if(m){m.classList.remove('open');m.setAttribute('aria-hidden','true');}}
  document.addEventListener('DOMContentLoaded',function(){
    applyAvatar(localStorage.getItem('dbot_admin_avatar')||'');
    var i=qs('#globalSearch'); if(i){i.addEventListener('input',function(){window.dbotFilterPage(i.value);});}
    var up=qs('#adminAvatarUpload'); if(up){up.addEventListener('change',function(){var f=up.files&&up.files[0]; if(!f) return; if(!f.type || !f.type.startsWith('image/')){notify('Please upload an image file.',false);return;} var r=new FileReader(); r.onload=function(){var data=String(r.result||''); localStorage.setItem('dbot_admin_avatar',data); applyAvatar(data); notify('Profile photo updated.',true);}; r.readAsDataURL(f);});}
    var rm=qs('#removeAdminAvatar'); if(rm){rm.addEventListener('click',function(){localStorage.removeItem('dbot_admin_avatar');applyAvatar('');notify('Profile photo removed.',true);});}
  });
  document.addEventListener('click',function(e){
    var searchBtn=e.target.closest('[data-ui-action="toggle-search"]');
    if(searchBtn){e.preventDefault();e.stopPropagation(); document.body.classList.contains('search-open')?closeSearch():openSearch(); return;}
    var prof=e.target.closest('[data-ui-action="profile"]');
    if(prof){e.preventDefault();e.stopPropagation();openProfile();return;}
    if(e.target.closest('[data-profile-close]')){e.preventDefault();closeProfile();return;}
    var m=qs('#profileModal'); if(m && m.classList.contains('open') && e.target===m){closeProfile();return;}
    if(document.body.classList.contains('search-open') && !e.target.closest('.searchbox') && !e.target.closest('[data-ui-action="toggle-search"]')){closeSearch();}
  },true);
  document.addEventListener('keydown',function(e){
    if((e.ctrlKey||e.metaKey)&&e.key==='/'){e.preventDefault();openSearch();}
    if(e.key==='Escape'){closeSearch();closeProfile();}
  },true);
})();



// === v1.3.31 dashboard fixes: force mobile hamburger drawer ===
(function(){
  function isMobile(){return window.matchMedia('(max-width: 760px)').matches;}
  function openSidebar(){document.body.classList.add('sidebar-open');document.body.classList.remove('sidebar-collapsed');}
  function closeSidebar(){document.body.classList.remove('sidebar-open');}
  document.addEventListener('click',function(e){
    var btn=e.target.closest('[data-ui-action="toggle-sidebar"]');
    if(btn){e.preventDefault();e.stopImmediatePropagation(); if(isMobile()){document.body.classList.contains('sidebar-open')?closeSidebar():openSidebar();}else{dbotToggleSidebar();} return false;}
    if(isMobile() && document.body.classList.contains('sidebar-open')){
      if(e.target.closest('[data-close-sidebar]') || e.target.closest('.main') || e.target.closest('.sidebar .navitem')) closeSidebar();
    }
  }, true);
})();


// === v1.3.34 final hamburger/search stabilizer ===
(function(){
  function isMobile(){return window.matchMedia('(max-width: 760px)').matches;}
  function setExpanded(v){document.querySelectorAll('[data-ui-action="toggle-sidebar"]').forEach(function(b){b.setAttribute('aria-expanded', v?'true':'false');});}
  window.dbotForceToggleSidebar=function(){
    if(isMobile()){
      var open=!document.body.classList.contains('sidebar-open');
      document.body.classList.toggle('sidebar-open',open);
      document.body.classList.remove('sidebar-desktop-hidden','sidebar-collapsed');
      setExpanded(open);
    }else{
      var hidden=!document.body.classList.contains('sidebar-desktop-hidden');
      document.body.classList.toggle('sidebar-desktop-hidden',hidden);
      document.body.classList.remove('sidebar-open','sidebar-collapsed');
      setExpanded(!hidden);
      setTimeout(function(){window.dispatchEvent(new Event('resize'));},30);
    }
  };
  window.dbotToggleSidebar=window.dbotForceToggleSidebar;
  document.addEventListener('DOMContentLoaded',function(){
    document.querySelectorAll('[data-ui-action="toggle-sidebar"]').forEach(function(btn){
      btn.onclick=function(ev){ev.preventDefault();ev.stopPropagation();window.dbotForceToggleSidebar();return false;};
    });
    if(!document.querySelector('.mobile-sidebar-backdrop')){
      var b=document.createElement('div');b.className='mobile-sidebar-backdrop';b.setAttribute('data-close-sidebar','1');document.body.appendChild(b);
    }
  });
  document.addEventListener('pointerdown',function(e){
    var btn=e.target.closest('[data-ui-action="toggle-sidebar"]');
    if(btn){e.preventDefault();e.stopImmediatePropagation();window.dbotForceToggleSidebar();return false;}
    if(isMobile() && document.body.classList.contains('sidebar-open') && (e.target.closest('[data-close-sidebar]') || e.target.closest('.main'))){
      document.body.classList.remove('sidebar-open');setExpanded(false);
    }
  },true);
  window.addEventListener('resize',function(){
    if(!isMobile()){document.body.classList.remove('sidebar-open');}
    else{document.body.classList.remove('sidebar-desktop-hidden','sidebar-collapsed');}
    setTimeout(function(){window.dispatchEvent(new Event('resize'));},60);
  },{passive:true});
})();

'''

SCRIPT += r'''

// === v1.3.40 Premium UI behavior layer ===
(function(){
  function $(sel,root){return (root||document).querySelector(sel)}
  function $all(sel,root){return Array.from((root||document).querySelectorAll(sel))}
  function closeSidebar(){document.body.classList.remove('sidebar-open'); const b=$('[data-ui-action="toggle-sidebar"]'); if(b)b.setAttribute('aria-expanded','false')}
  function openSidebar(){document.body.classList.add('sidebar-open'); const b=$('[data-ui-action="toggle-sidebar"]'); if(b)b.setAttribute('aria-expanded','true')}
  document.addEventListener('click',function(e){
    const toggle=e.target.closest('[data-ui-action="toggle-sidebar"]');
    if(toggle){e.preventDefault(); document.body.classList.contains('sidebar-open')?closeSidebar():openSidebar(); return;}
    if(e.target.closest('[data-close-sidebar]')){closeSidebar();return;}
    const search=e.target.closest('[data-ui-action="toggle-search"]');
    if(search){e.preventDefault(); document.body.classList.toggle('search-open'); const input=$('#globalSearch'); if(document.body.classList.contains('search-open')&&input)setTimeout(()=>input.focus(),80); return;}
    const pass=e.target.closest('[data-ui-action="toggle-password"]');
    if(pass){e.preventDefault(); const input=document.getElementById(pass.getAttribute('aria-controls')||'loginPassword'); if(input){const show=input.type==='password'; input.type=show?'text':'password'; pass.textContent=show?'Hide':'Show';} return;}
    if(window.innerWidth<=920 && document.body.classList.contains('sidebar-open') && !e.target.closest('.sidebar') && !e.target.closest('[data-ui-action="toggle-sidebar"]')) closeSidebar();
  },true);
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){closeSidebar();document.body.classList.remove('search-open')}
    if((e.ctrlKey||e.metaKey)&&e.key==='/'){e.preventDefault();document.body.classList.add('search-open');const input=$('#globalSearch');if(input)input.focus();}
  });
  document.addEventListener('input',function(e){
    if(e.target && e.target.id==='globalSearch'){
      const q=e.target.value.trim().toLowerCase();
      $all('table tbody tr,.order-row,.card,.metric,.resource-card').forEach(el=>{el.style.display=(!q||el.textContent.toLowerCase().includes(q))?'':'none'});
    }
  });
  document.addEventListener('DOMContentLoaded',function(){
    $all('.langbox,[onclick^="setLang"]').forEach(el=>el.remove());
    $all('button,a.btn,.btn').forEach(el=>{if(!el.getAttribute('aria-label') && el.textContent.trim()) el.setAttribute('aria-label',el.textContent.trim());});
  });
})();

'''



SCRIPT += r'''
// === v1.3.41 cyber SaaS interaction hardening ===
(function(){function qs(s,r){return (r||document).querySelector(s)}function qsa(s,r){return Array.from((r||document).querySelectorAll(s))}function stripLeadingEmoji(txt){return String(txt||'').replace(/^[\s\u200d\ufe0f]*(?:[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\ufe0f?\s*)+/gu,'').trim()}document.addEventListener('DOMContentLoaded',function(){document.documentElement.lang='en';document.documentElement.dir='ltr';qsa('.langbox').forEach(el=>el.remove());qsa('button,.btn,a.btn').forEach(el=>{if(el.closest('.navitem')||el.classList.contains('theme-btn')||el.classList.contains('admin-avatar-btn'))return;if(el.childElementCount===0)el.textContent=stripLeadingEmoji(el.textContent)||el.textContent});const searchToggle=qs('[data-ui-action="toggle-search"]'),searchBox=qs('.searchbox'),searchInput=qs('#globalSearch');if(searchToggle&&searchBox){searchToggle.addEventListener('click',function(ev){ev.preventDefault();document.body.classList.toggle('search-open');searchBox.classList.toggle('search-open');if(document.body.classList.contains('search-open'))setTimeout(()=>searchInput&&searchInput.focus(),60)})}document.addEventListener('click',function(ev){if(document.body.classList.contains('search-open')&&!ev.target.closest('.searchbox')&&!ev.target.closest('[data-ui-action="toggle-search"]')){document.body.classList.remove('search-open');searchBox&&searchBox.classList.remove('search-open')}});qsa('.resource-card').forEach(card=>{let txt=(card.querySelector('.resource-value')||{}).textContent||'';let n=parseFloat(txt);if(!Number.isNaN(n))card.style.setProperty('--p',String(Math.max(0,Math.min(100,n))))});const saved=localStorage.getItem('dbot_admin_avatar'),av=qs('#adminAvatar'),prev=qs('#profileAvatarPreview');function setAvatar(data){if(data){if(av)av.innerHTML='<img alt="Admin" src="'+data+'">';if(prev)prev.innerHTML='<img alt="Admin" src="'+data+'">'}}setAvatar(saved);const file=qs('#adminAvatarUpload');if(file){file.addEventListener('change',function(){const f=this.files&&this.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{localStorage.setItem('dbot_admin_avatar',rd.result);setAvatar(rd.result)};rd.readAsDataURL(f)})}const rem=qs('#removeAdminAvatar');if(rem){rem.addEventListener('click',function(){localStorage.removeItem('dbot_admin_avatar');if(av)av.textContent='';if(prev)prev.textContent=''})}document.addEventListener('click',function(ev){if(ev.target.closest('[data-ui-action="profile"]')){const m=qs('#profileModal');if(m){m.classList.add('open');m.setAttribute('aria-hidden','false')}}if(ev.target.closest('[data-profile-close]')){const m=qs('#profileModal');if(m){m.classList.remove('open');m.setAttribute('aria-hidden','true')}}});document.addEventListener('click',function(ev){const b=ev.target.closest('[data-ui-action="toggle-password"]');if(!b)return;const id=b.getAttribute('aria-controls')||'loginPassword';const input=qs('#'+id);if(input){input.type=input.type==='password'?'text':'password';b.textContent=input.type==='password'?'Show':'Hide'}});qsa('#revenueChart,.apex-chart,.chart-wrap').forEach(el=>el.addEventListener('wheel',function(ev){ev.stopPropagation()},{passive:true,capture:true}))})})();
'''
def layout(title_fa: str, title_en: str, body: str, active: str = '/admin') -> str:
    groups = [
        ('', [('/admin','🏠','Dashboard','Dashboard')]),
        ('Sales', [('/admin/service-types','🧬','Service Types','Service Types'),('/admin/plans','📦','Plans','Plans'),('/admin/payments','💳','Payments','Payments'),('/admin/orders-report','📄','Orders Report','Orders Report'),('/admin/discounts','🎟','Discount Codes','Discount Codes')]),
        ('Users', [('/admin/resellers','🤝','Resellers','Resellers')]),
        ('System', [('/admin/servers','🖥','Servers','Servers'),('/admin/categories','🗂','Categories','Categories'),('/admin/backup','🧰','Backup','Backup'),('/admin/settings','⚙️','Settings','Settings')]),
    ]
    nav_parts=[]
    for label, items in groups:
        links=''.join(f'<a class="navitem {"active" if u==active else ""}" href="{u}"><span>{ic}</span><b data-fa="{fa}" data-en="{en}">{fa}</b></a>' for u,ic,fa,en in items)
        nav_parts.append(f'<div class="nav-group">' + (f'<div class="nav-label"><span>{label}</span><span>⌃</span></div>' if label else '') + links + '</div>')
    nav=''.join(nav_parts)
    themes=''.join(f'<button type="button" class="theme-btn" title="Theme {i}" data-theme-btn="theme-{i}" onclick="setTheme(\'theme-{i}\')"></button>' for i in range(1,7))
    confirm_modal='<div class="modal" id="confirmDeleteModal"><div class="modal-card" style="max-width:480px"><div class="modal-head"><h2 data-fa="Confirm delete" data-en="Confirm delete">Confirm delete</h2><button type="button" class="ghost" onclick="closeModal(\'confirmDeleteModal\')">×</button></div><p class="muted" data-fa="Are you sure? This action cannot be undone." data-en="Are you sure? This action cannot be undone." >Are you sure? This action cannot be undone.</p><div class="rowactions" style="justify-content:flex-end;margin-top:18px"><button type="button" class="btn ghost" onclick="closeModal(\'confirmDeleteModal\')" data-fa="Cancel" data-en="Cancel">Cancel</button><button type="button" class="btn danger" onclick="confirmDelete()" data-fa="Delete" data-en="Delete">Delete</button></div></div></div>'
    return f"""<!doctype html><html lang='en' dir='ltr' data-timeout='1800'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>D BOT - {e(title_en)}</title><style>{STYLE}</style><script src='https://cdn.jsdelivr.net/npm/apexcharts'></script><script>{SCRIPT}</script></head><body data-theme='theme-1'><div class='shell'><aside class='sidebar'><div class='brand'><div class='gift'>◇</div><div><strong>D BOT</strong><small data-fa='Admin panel' data-en='Admin panel'>Admin panel</small></div></div><nav>{nav}</nav><div class='sidebar-footer'><div class='nav-label'><span data-fa='Panel theme' data-en='Panel theme'>Panel theme</span><span>☼</span></div><div class='theme-dots'>{themes}</div><div class='langbox'><button onclick='setLang(\"fa\")'>IR 🇮🇷</button><button onclick='setLang(\"en\")'>US 🇺🇸</button></div></div></aside><main class='main'><div class='topbar'><div class='top-left'><button class='menu-square' type='button' data-ui-action='toggle-sidebar' aria-label='Menu' aria-expanded='false'>☰</button><button class='search-toggle' type='button' data-ui-action='toggle-search' aria-label='Search'>🔎</button><div class='searchbox'>🔎 <input id='globalSearch' placeholder='Search...' data-fa-placeholder='Search...' data-en-placeholder='Search...' autocomplete='off'><span class='kbd'>Ctrl + /</span></div></div><div class='top-actions'><button type='button' class='icon-btn' data-ui-action='notify'>🔔</button><button type='button' class='icon-btn' data-ui-action='cycle-theme'>🌙</button><button type='button' class='icon-btn' data-ui-action='fullscreen'>⛶</button><button type='button' class='admin-avatar-btn' data-ui-action='profile' aria-label='Profile'><div class='avatar' id='adminAvatar'>👤</div></button><a class='logout-icon-btn' href='/logout' aria-label='Logout' title='Logout'>⏻</a></div></div><div class='content'>{body}</div></main></div><div class='mobile-sidebar-backdrop' data-close-sidebar='1'></div><div id='session-toast' class='toast'></div><div class='profile-modal' id='profileModal' aria-hidden='true'><div class='profile-card'><button type='button' class='profile-close' data-profile-close='1'>×</button><div class='profile-avatar-preview' id='profileAvatarPreview'>👤</div><label class='btn primary profile-upload-label'><input id='adminAvatarUpload' type='file' accept='image/*' hidden>Upload profile photo</label><button type='button' class='btn ghost' id='removeAdminAvatar'>Remove photo</button><a class='btn danger profile-logout' href='/logout'>Logout</a></div></div>{confirm_modal}</body></html>"""


@router.get('/admin/assets/style.css')
async def admin_style_asset():
    return Response(STYLE, media_type='text/css; charset=utf-8')


@router.get('/admin/assets/app.js')
async def admin_script_asset():
    return Response(SCRIPT, media_type='application/javascript; charset=utf-8')



CYBER_BG_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000"><defs><radialGradient id="a" cx="20%" cy="10%" r="60%"><stop offset="0" stop-color="#22d3ee" stop-opacity=".34"/><stop offset="1" stop-color="#020818" stop-opacity="0"/></radialGradient><radialGradient id="b" cx="86%" cy="18%" r="48%"><stop offset="0" stop-color="#7c3aed" stop-opacity=".30"/><stop offset="1" stop-color="#020818" stop-opacity="0"/></radialGradient><linearGradient id="c" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#020818"/><stop offset=".56" stop-color="#061a3d"/><stop offset="1" stop-color="#020617"/></linearGradient><filter id="g"><feGaussianBlur stdDeviation="3"/></filter></defs><rect width="1600" height="1000" fill="url(#c)"/><rect width="1600" height="1000" fill="url(#a)"/><rect width="1600" height="1000" fill="url(#b)"/><g opacity=".26" stroke="#22d3ee" stroke-width="1"><path d="M-40 730 C230 610 390 820 620 690 S1070 480 1640 560" fill="none"/><path d="M-20 280 C250 240 420 390 630 315 S1120 150 1640 240" fill="none"/><path d="M210 -20 C300 210 310 430 520 560 S790 760 700 1040" fill="none"/><path d="M1050 -40 C930 230 980 410 1210 590 S1380 760 1340 1060" fill="none"/></g><g opacity=".42" filter="url(#g)"><circle cx="210" cy="160" r="3" fill="#67e8f9"/><circle cx="340" cy="320" r="2" fill="#38bdf8"/><circle cx="560" cy="220" r="3" fill="#a78bfa"/><circle cx="830" cy="130" r="2" fill="#22d3ee"/><circle cx="1040" cy="260" r="3" fill="#818cf8"/><circle cx="1210" cy="420" r="2" fill="#67e8f9"/><circle cx="1360" cy="180" r="3" fill="#22d3ee"/><circle cx="460" cy="650" r="2" fill="#38bdf8"/><circle cx="760" cy="760" r="3" fill="#a78bfa"/><circle cx="1160" cy="720" r="2" fill="#67e8f9"/></g><g opacity=".08" stroke="#67e8f9"><path d="M0 120h1600M0 240h1600M0 360h1600M0 480h1600M0 600h1600M0 720h1600M0 840h1600M160 0v1000M320 0v1000M480 0v1000M640 0v1000M800 0v1000M960 0v1000M1120 0v1000M1280 0v1000M1440 0v1000"/></g></svg>'

@router.get('/admin/assets/cyber-bg.svg')
async def cyber_bg_asset():
    return Response(CYBER_BG_SVG, media_type='image/svg+xml; charset=utf-8')


@router.get('/assets/style.css')
async def admin_style_asset_short():
    return Response(STYLE, media_type='text/css; charset=utf-8')


@router.get('/assets/app.js')
async def admin_script_asset_short():
    return Response(SCRIPT, media_type='application/javascript; charset=utf-8')

@router.get('/login', response_class=HTMLResponse)
async def login_page(request: Request, next: str = '/admin'):
    next = _safe_next_url(next)
    err = request.query_params.get('error')
    timeout = request.query_params.get('timeout')
    updated = request.query_params.get('updated')
    note = '<div class="login-alert bad">Invalid username or password.</div>' if err else ('<div class="login-alert">Your session has expired. Please login again.</div>' if timeout else ('<div class="login-alert">Website login was changed. Please login again with the new username/password.</div>' if updated else ''))
    return f"""<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>D BOT Owner Login</title><style>
:root{{--bg:#030814;--panel:rgba(15,23,42,.82);--line:rgba(148,163,184,.18);--text:#f8fafc;--muted:#9aa7bd;--primary:#7c3aed;--primary2:#2563eb;--red:#ef4444}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Tahoma,sans-serif;background:radial-gradient(circle at 12% 0%,rgba(124,58,237,.34),transparent 32%),radial-gradient(circle at 88% 8%,rgba(14,165,233,.22),transparent 26%),linear-gradient(145deg,#020617 0%,#06101f 52%,#040812 100%);display:grid;place-items:center;padding:24px;overflow:hidden}}body:before{{content:'';position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);background-size:64px 64px;mask-image:linear-gradient(to bottom,rgba(0,0,0,.8),transparent 70%)}}body:after{{content:'';position:fixed;inset:-20%;background:conic-gradient(from 120deg,transparent,rgba(124,58,237,.13),transparent,rgba(14,165,233,.08),transparent);animation:spin 18s linear infinite;pointer-events:none}}@keyframes spin{{to{{transform:rotate(360deg)}}}}
.login-wrap{{position:relative;z-index:1;width:min(480px,100%)}}.login-card{{position:relative;overflow:hidden;background:linear-gradient(180deg,rgba(15,23,42,.86),rgba(8,13,27,.78));border:1px solid var(--line);border-radius:28px;box-shadow:0 34px 120px rgba(0,0,0,.58);padding:30px;backdrop-filter:blur(20px)}}.login-card:before{{content:'';position:absolute;inset:0;background:radial-gradient(circle at 80% 0%,rgba(124,58,237,.22),transparent 36%);pointer-events:none}}.login-logo{{width:72px;height:72px;margin:0 auto 18px;border-radius:22px;display:grid;place-items:center;background:linear-gradient(135deg,rgba(14,165,233,.95),rgba(124,58,237,.95));box-shadow:0 0 0 8px rgba(124,58,237,.13),0 22px 60px rgba(37,99,235,.28);font-weight:1000;font-size:30px;position:relative}}h1{{margin:0;text-align:center;font-size:29px;letter-spacing:-.05em}}p{{margin:8px 0 20px;text-align:center;color:var(--muted)}}label{{display:grid;gap:8px;margin:13px 0;color:#cbd5e1;font-size:13px}}input{{width:100%;min-height:48px;border:1px solid rgba(148,163,184,.16);border-radius:14px;background:linear-gradient(180deg,rgba(15,23,42,.95),rgba(2,6,23,.7));color:#fff;outline:none;padding:0 13px;color-scheme:dark}}input:focus{{border-color:rgba(139,92,246,.58);box-shadow:0 0 0 4px rgba(124,58,237,.14)}}.password-row{{position:relative}}.password-row button{{position:absolute;right:8px;top:8px;min-height:32px;border:1px solid rgba(148,163,184,.18);border-radius:10px;background:rgba(15,23,42,.84);color:#dbeafe;padding:0 10px;cursor:pointer}}.btn{{width:100%;min-height:48px;border-radius:14px;border:1px solid rgba(139,92,246,.4);background:linear-gradient(135deg,#7c3aed,#4f46e5);box-shadow:0 18px 42px rgba(99,102,241,.24);color:white;font-weight:800;cursor:pointer;margin-top:10px}}.btn:hover{{filter:brightness(1.13);transform:translateY(-1px)}}.btn:active{{transform:scale(.99);filter:brightness(1.25)}}.login-alert{{border:1px solid rgba(148,163,184,.16);background:rgba(15,23,42,.7);border-radius:14px;padding:11px 13px;text-align:center;color:#dbeafe;margin:14px 0}}.login-alert.bad{{border-color:rgba(239,68,68,.36);color:#fecaca;background:rgba(127,29,29,.18)}}.copyright{{font-size:12px;margin-top:18px}}a{{color:#a78bfa}}
</style><script>function togglePassword(){{const i=document.getElementById('loginPassword'),b=document.getElementById('togglePass');if(i){{i.type=i.type==='password'?'text':'password';b.textContent=i.type==='password'?'Show':'Hide';}}}}</script></head><body><main class="login-wrap"><form class="login-card" method="post" action="/login"><input type="hidden" name="next_url" value="{e(next)}"><div class="login-logo">D</div><h1>D BOT Owner Login</h1><p>Secure owner access</p>{note}<label>Username<input name="username" autocomplete="username" required placeholder="Enter owner username"></label><label>Password<div class="password-row"><input id="loginPassword" name="password" type="password" autocomplete="current-password" required placeholder="Enter password"><button id="togglePass" type="button" onclick="togglePassword()">Show</button></div></label><button class="btn" type="submit">Login</button><p class="copyright">All design and development belongs to <b>D Bot</b>.</p></form></main></body></html>"""


@router.post('/login')
async def do_login(request: Request, response: Response, username: str = Form(...), password: str = Form(...), next_url: str = Form('/admin')):
    user = await db_setting('web_admin_username', settings.WEB_ADMIN_USERNAME or '')
    pwd = await db_setting('web_admin_password', settings.WEB_ADMIN_PASSWORD or '')
    timeout_min = int(await db_setting('web_token_timeout_minutes', str(SESSION_MINUTES)) or SESSION_MINUTES)
    if not user or not pwd:
        user = settings.WEB_ADMIN_USERNAME or 'admin'
        pwd = settings.WEB_ADMIN_PASSWORD or ''
    if _login_blocked(request, username):
        return RedirectResponse('/login?error=1', status_code=303)
    ok_login = bool(pwd and secrets.compare_digest(username, user) and verify_password(password, pwd))
    if not ok_login:
        _record_login_failure(request, username)
        return RedirectResponse('/login?error=1', status_code=303)
    _record_login_success(request, username)
    if pwd and not is_password_hash(pwd):
        # One-time migration from legacy plaintext admin passwords.
        async with SessionLocal() as s:
            await s.merge(Setting(key='web_admin_password', value=hash_password(password)))
            await s.commit()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    _sessions[token] = {'username': username, 'created_at': _now(), 'expires_at': _now() + timedelta(minutes=timeout_min), 'csrf': csrf}
    res = RedirectResponse(_safe_next_url(next_url), status_code=303)
    res.set_cookie('dbot_admin_token', token, max_age=timeout_min*60, httponly=True, secure=True, samesite='strict')
    res.set_cookie('dbot_csrf_token', csrf, max_age=timeout_min*60, httponly=False, secure=True, samesite='strict')
    return res


@router.get('/logout')
async def logout(request: Request, timeout: int = 0):
    token = request.cookies.get('dbot_admin_token')
    if token: _sessions.pop(token, None)
    res = RedirectResponse('/login' + ('?timeout=1' if timeout else ''), status_code=303)
    res.delete_cookie('dbot_admin_token')
    res.delete_cookie('dbot_csrf_token')
    return res




async def _dashboard_payload(days: int = 30) -> dict[str, Any]:
    now = datetime.utcnow()
    days = days if days in {7, 14, 30, 90} else 30
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # Monthly Sales must be real and calendar-based:
    # current month total compared with the previous calendar month.
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    chart_start = now - timedelta(days=days)
    chart_90_start = now - timedelta(days=90)

    paid_statuses = ['paid','approved','completed']
    async with SessionLocal() as s:
        users_total = await s.scalar(select(func.count(User.id))) or 0
        users_today = await s.scalar(select(func.count(User.id)).where(User.joined_at >= today_start)) or 0
        users_yesterday = await s.scalar(select(func.count(User.id)).where(User.joined_at >= yesterday_start, User.joined_at < today_start)) or 0
        resellers_total = await s.scalar(select(func.count(ResellerAccount.id))) or 0
        resellers_today = await s.scalar(select(func.count(ResellerAccount.id)).where(ResellerAccount.created_at >= today_start)) or 0
        resellers_yesterday = await s.scalar(select(func.count(ResellerAccount.id)).where(ResellerAccount.created_at >= yesterday_start, ResellerAccount.created_at < today_start)) or 0
        open_tickets = await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open')) or 0
        tickets_today = await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open', Ticket.created_at >= today_start)) or 0
        tickets_yesterday = await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open', Ticket.created_at >= yesterday_start, Ticket.created_at < today_start)) or 0
        sales = await s.scalar(select(func.coalesce(func.sum(Order.amount_irt),0)).where(Order.status.in_(paid_statuses), Order.created_at >= current_month_start)) or 0
        previous_sales = await s.scalar(select(func.coalesce(func.sum(Order.amount_irt),0)).where(Order.status.in_(paid_statuses), Order.created_at >= previous_month_start, Order.created_at < current_month_start)) or 0
        today_orders = await s.scalar(select(func.count(Order.id)).where(Order.created_at >= today_start)) or 0
        yesterday_orders = await s.scalar(select(func.count(Order.id)).where(Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        wallet_expr = func.coalesce(User.wallet_balance,0)
        wallet_total = await s.scalar(select(func.coalesce(func.sum(wallet_expr),0))) or 0
        wallet_today = await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt),0)).where(WalletTransaction.amount_irt > 0, WalletTransaction.created_at >= today_start)) or 0
        wallet_yesterday = await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt),0)).where(WalletTransaction.amount_irt > 0, WalletTransaction.created_at >= yesterday_start, WalletTransaction.created_at < today_start)) or 0
        active_users = await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True)) or 0
        active_today = await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True, ClientService.created_at >= today_start)) or 0
        active_yesterday = await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True, ClientService.created_at >= yesterday_start, ClientService.created_at < today_start)) or 0
        total_orders = await s.scalar(select(func.count(Order.id))) or 0
        completed_orders = await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses))) or 0
        today_completed = await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses), Order.created_at >= today_start)) or 0
        yesterday_total = await s.scalar(select(func.count(Order.id)).where(Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        yesterday_completed = await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses), Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        conversion_rate = round((completed_orders / total_orders * 100), 2) if total_orders else 0
        today_conversion = round((today_completed / today_orders * 100), 2) if today_orders else 0
        yesterday_conversion = round((yesterday_completed / yesterday_total * 100), 2) if yesterday_total else 0
        start = chart_90_start
        rows = (await s.execute(select(func.date(Order.created_at), func.coalesce(func.sum(Order.amount_irt),0)).where(Order.status.in_(paid_statuses), Order.created_at >= start).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at)))).all()
        user_rows = (await s.execute(select(func.date(User.joined_at), func.count(User.id)).where(User.joined_at >= start).group_by(func.date(User.joined_at)).order_by(func.date(User.joined_at)))).all()
    sales_map = {str(d): int(v or 0) for d, v in rows}
    users_map = {str(d): int(v or 0) for d, v in user_rows}
    revenue=[]; new_users=[]
    for i in range(91):
        d = (start + timedelta(days=i)).date()
        key = d.isoformat()
        revenue.append({'date': key, 'label': d.strftime('%b %d'), 'revenue': sales_map.get(key, 0)})
        new_users.append({'date': key, 'label': d.strftime('%b %d'), 'users': users_map.get(key, 0)})
    return {'ok': True, 'range_days': days, 'metrics': {
        'monthly_sales': int(sales), 'total_users': int(users_total), 'total_resellers': int(resellers_total), 'open_tickets': int(open_tickets),
        'today_orders': int(today_orders), 'wallet_balance': int(wallet_total), 'active_users': int(active_users), 'conversion_rate': conversion_rate,
        'sales_trend': percent_change(sales, previous_sales), 'users_trend': percent_change(users_today, users_yesterday),
        'resellers_trend': percent_change(resellers_today, resellers_yesterday), 'tickets_trend': percent_change(tickets_today, tickets_yesterday),
        'orders_trend': percent_change(today_orders, yesterday_orders), 'wallet_trend': percent_change(wallet_today, wallet_yesterday),
        'active_users_trend': percent_change(active_today, active_yesterday), 'conversion_trend': percent_change(today_conversion, yesterday_conversion)
    }, 'revenue': revenue, 'new_users': new_users}


@router.get('/admin/api/resources')
async def dashboard_resources_api(request: Request, _: str = Depends(_auth_user)):
    try:
        return JSONResponse({'ok': True, 'html': dashboard_resource_cards(), 'updated_at': datetime.utcnow().isoformat()})
    except Exception:
        return JSONResponse({'ok': False, 'html': '<div class="empty-state">Server resources could not be loaded.</div>'}, status_code=200)

@router.get('/admin/api/dashboard')
async def dashboard_api(request: Request, days: int = 30, _: str = Depends(_auth_user)):
    return JSONResponse(await _dashboard_payload(days))

@router.get('/admin-legacy', response_class=HTMLResponse)
async def dashboard(request: Request, page: int = 1, page_size: int = 50, _: str = Depends(_auth_user)):
    page_size = page_size if page_size in {20,50} else 50
    page=max(page,1); offset=(page-1)*page_size
    async with SessionLocal() as s:
        users_total=await s.scalar(select(func.count(User.id))) or 0
        resellers_total=await s.scalar(select(func.count(ResellerAccount.id))) or 0
        open_tickets=await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open')) or 0
        paid_statuses=['paid','approved','completed']
        now=datetime.utcnow(); today_start=now.replace(hour=0, minute=0, second=0, microsecond=0); yesterday_start=today_start-timedelta(days=1)
        current_month_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month_start=(current_month_start-timedelta(days=1)).replace(day=1)
        sales=await s.scalar(select(func.coalesce(func.sum(Order.amount_irt),0)).where(Order.status.in_(paid_statuses), Order.created_at >= current_month_start)) or 0
        previous_sales=await s.scalar(select(func.coalesce(func.sum(Order.amount_irt),0)).where(Order.status.in_(paid_statuses), Order.created_at >= previous_month_start, Order.created_at < current_month_start)) or 0
        today_orders=await s.scalar(select(func.count(Order.id)).where(Order.created_at >= today_start)) or 0
        yesterday_orders=await s.scalar(select(func.count(Order.id)).where(Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        wallet_expr = func.coalesce(User.wallet_balance,0)
        wallet_total=await s.scalar(select(func.coalesce(func.sum(wallet_expr),0))) or 0
        wallet_today=await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt),0)).where(WalletTransaction.amount_irt > 0, WalletTransaction.created_at >= today_start)) or 0
        wallet_yesterday=await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt),0)).where(WalletTransaction.amount_irt > 0, WalletTransaction.created_at >= yesterday_start, WalletTransaction.created_at < today_start)) or 0
        users_today=await s.scalar(select(func.count(User.id)).where(User.joined_at >= today_start)) or 0
        users_yesterday=await s.scalar(select(func.count(User.id)).where(User.joined_at >= yesterday_start, User.joined_at < today_start)) or 0
        resellers_today=await s.scalar(select(func.count(ResellerAccount.id)).where(ResellerAccount.created_at >= today_start)) or 0
        resellers_yesterday=await s.scalar(select(func.count(ResellerAccount.id)).where(ResellerAccount.created_at >= yesterday_start, ResellerAccount.created_at < today_start)) or 0
        tickets_today=await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open', Ticket.created_at >= today_start)) or 0
        tickets_yesterday=await s.scalar(select(func.count(Ticket.id)).where(Ticket.status=='open', Ticket.created_at >= yesterday_start, Ticket.created_at < today_start)) or 0
        active_users=await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True)) or 0
        active_today=await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True, ClientService.created_at >= today_start)) or 0
        active_yesterday=await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True, ClientService.created_at >= yesterday_start, ClientService.created_at < today_start)) or 0
        total_orders=await s.scalar(select(func.count(Order.id))) or 0
        completed_orders=await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses))) or 0
        today_completed=await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses), Order.created_at >= today_start)) or 0
        yesterday_total=await s.scalar(select(func.count(Order.id)).where(Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        yesterday_completed=await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses), Order.created_at >= yesterday_start, Order.created_at < today_start)) or 0
        conversion_rate=round((completed_orders/total_orders*100),2) if total_orders else 0
        today_conversion=round((today_completed/today_orders*100),2) if today_orders else 0
        yesterday_conversion=round((yesterday_completed/yesterday_total*100),2) if yesterday_total else 0
        users=(await s.execute(select(User).order_by(User.id.desc()).offset(offset).limit(page_size))).scalars().all()
        page_user_ids=[u.id for u in users]
        purchases={}
        if page_user_ids:
            purchases=dict((await s.execute(select(Order.user_id, func.count(Order.id)).where(Order.user_id.in_(page_user_ids)).group_by(Order.user_id))).all())
        recent_orders=(await s.execute(select(Order).where(Order.created_at >= now - timedelta(days=30)).order_by(Order.id.desc()).limit(5))).scalars().all()
        recent_user_ids=[o.user_id for o in recent_orders]
        recent_users={}
        if recent_user_ids:
            recent_users={u.id:u for u in (await s.execute(select(User).where(User.id.in_(recent_user_ids)))).scalars().all()}
    
    row_parts=[]
    user_modals=[]
    for i,u in enumerate(users,1):
        mid=f'userView{u.id}'
        row_parts.append(f'<tr><td>{offset+i}</td><td><b>{e(u.full_name)}</b><div class="muted">ID: {e(u.telegram_id)}</div></td><td>{e(u.username)} <span style="color:#3b82f6">✈</span></td><td>{e(getattr(u,"referral_code",None) or "-")}</td><td>{purchases.get(u.id,0)}</td><td>{money(user_wallet_total(u))} Toman</td><td><button class="btn ghost" onclick="openModal(\'{mid}\')">•••</button></td></tr>')
        referral_code = getattr(u, 'referral_code', None) or '-'
        user_details_html = (
            f'<div class="kvs">'
            f'<div class="kv"><span>Name</span><b>{e(u.full_name)}</b></div>'
            f'<div class="kv"><span>Numeric ID</span><b>{e(u.telegram_id)}</b></div>'
            f'<div class="kv"><span>Username</span><b>{e(u.username)}</b></div>'
            f'<div class="kv"><span>Referral code</span><b>{e(referral_code)}</b></div>'
            f'<div class="kv"><span>Purchases</span><b>{purchases.get(u.id, 0)}</b></div>'
            f'<div class="kv"><span>Wallet</span><b>{money(user_wallet_total(u))} Toman</b></div>'
            f'</div>'
        )
        user_modals.append(modal(mid, 'User details', 'User details', user_details_html))
    rows=''.join(row_parts)
    user_modals_html=''.join(user_modals)
    if not rows:
        rows='<tr><td colspan="7" class="muted">No users found.</td></tr>'
    order_rows=''
    for o in recent_orders:
        status=getattr(o,'status','') or '-'
        cls='ok' if status in {'paid','approved','completed'} else ('warn' if status in {'pending','review'} else 'bad')
        ou=recent_users.get(o.user_id)
        oname=(ou.full_name or ou.username or str(ou.telegram_id)) if ou else 'User'
        order_rows += f'<div class="order-row"><div><b>{e(oname)}</b><div class="muted">User ID: {e(getattr(ou,"telegram_id","-"))} | Order #{e(o.id)}</div></div><div class="pill {cls}">{e(status)}</div><div>#{e(o.id)}</div><div style="color:var(--success);font-weight:900">{money(o.amount_irt)} Toman</div></div>'
    if not order_rows:
        order_rows='<div class="muted" style="padding:20px">No orders found.</div>'
    max_page=max(1,(users_total+page_size-1)//page_size)
    pager='<div class="pager">'+('' if page<=1 else f'<a class="btn" href="/admin?page={page-1}&page_size={page_size}">Previous</a>')+f'<span class="badge">{page} / {max_page}</span>'+('' if page>=max_page else f'<a class="btn primary" href="/admin?page={page+1}&page_size={page_size}">Next page</a>')+'</div>'
    chart='<div id="revenueChart" class="apex-chart" role="img" aria-label="Monthly Sales chart"><div class="skeleton chart-skeleton"></div></div>'
    resource_cards=dashboard_resource_cards()
    sales_trend=trend_badge(percent_change(sales, previous_sales), 'from last month')
    users_trend=trend_badge(percent_change(users_today, users_yesterday), 'vs yesterday')
    resellers_trend=trend_badge(percent_change(resellers_today, resellers_yesterday), 'vs yesterday')
    tickets_trend=trend_badge(percent_change(tickets_today, tickets_yesterday), 'vs yesterday')
    orders_trend=trend_badge(percent_change(today_orders, yesterday_orders), 'vs yesterday')
    wallet_trend=trend_badge(percent_change(wallet_today, wallet_yesterday), 'wallet topups')
    active_trend=trend_badge(percent_change(active_today, active_yesterday), 'vs yesterday')
    conversion_trend=trend_badge(percent_change(today_conversion, yesterday_conversion), 'vs yesterday')
    body=f'''<div class="page-head"><div><h1 data-fa="Dashboard" data-en="Dashboard">Dashboard</h1><div class="breadcrumbs" data-fa="Home / Dashboard" data-en="Home / Dashboard">Home / Dashboard</div></div></div><div class="resource-live-head"><span>Server Status</span><small id="resourceUpdated">Live update: 5s</small></div><div id="serverResourceGrid" class="resource-grid">{resource_cards}</div><div class="grid4"><div class="metric purple"><div class="top"><div><div class="label" data-fa="Monthly Sales" data-en="Monthly Sales">Monthly Sales</div><div class="value monthly-value">{money(sales)}</div><div class="muted">Toman</div></div><div class="icon">$</div></div>{sales_trend}</div><div class="metric blue"><div class="top"><div><div class="label" data-fa="Total users" data-en="Total users">Total users</div><div class="value">{users_total}</div><div class="muted">users</div></div><div class="icon">👥</div></div>{users_trend}</div><div class="metric green"><div class="top"><div><div class="label" data-fa="Total resellers" data-en="Total resellers">Total resellers</div><div class="value">{resellers_total}</div><div class="muted">resellers</div></div><div class="icon">🤝</div></div>{resellers_trend}</div><div class="metric pink"><div class="top"><div><div class="label" data-fa="Today orders" data-en="Today orders">Today orders</div><div class="value">{today_orders}</div><div class="muted">orders</div></div><div class="icon">🛍</div></div>{orders_trend}</div><div class="metric cyan"><div class="top"><div><div class="label" data-fa="Wallet balance" data-en="Wallet balance">Wallet balance</div><div class="value">{money(wallet_total)}</div><div class="muted">Toman</div></div><div class="icon">💳</div></div>{wallet_trend}</div></div><div class="dashboard-grid"><section class="panel"><div class="panel-head"><h2 data-fa="Monthly Sales" data-en="Monthly Sales">Monthly Sales</h2><div class="range-tabs"><button type="button" class="active" data-chart-range="7">7 Days</button><button type="button" data-chart-range="14">14 Days</button><button type="button" data-chart-range="30">30 Days</button><button type="button" data-chart-range="90">90 Days</button></div></div><div class="chart-wrap">{chart}</div></section><section class="panel"><div class="panel-head"><h2 data-fa="Latest orders" data-en="Latest orders">Latest orders</h2><span class="badge">Last 30 days</span></div><div class="orders">{order_rows}</div></section></div><div class="tablebox"><div class="headrow"><h2 data-fa="Users list" data-en="Users list">Users list</h2><form data-native="1" method="get" action="/admin" style="display:flex;align-items:center;gap:8px"><label data-fa="Rows" data-en="Rows">Rows</label><select name="page_size" onchange="this.form.submit()"><option value="20" {'selected' if page_size==20 else ''}>20</option><option value="50" {'selected' if page_size==50 else ''}>50</option></select></form></div><div class="table-scroll"><table><thead><tr><th>#</th><th data-fa="users" data-en="User">users</th><th data-fa="Telegram username" data-en="Telegram username">Telegram username</th><th data-fa="Referral code" data-en="Referral code">Referral code</th><th data-fa="Purchases" data-en="Purchases">Purchases</th><th data-fa="Wallet balance" data-en="Wallet">Wallet balance</th><th data-fa="Actions" data-en="Actions">Actions</th></tr></thead><tbody>{rows}</tbody></table></div>{pager}</div>{user_modals_html}'''
    return layout('Dashboard','Dashboard',body,'/admin')



@router.get('/admin-legacy/orders-report', response_class=HTMLResponse)
async def orders_report(request: Request, start_date: str | None = None, end_date: str | None = None, _: str = Depends(_auth_user)):
    now = datetime.utcnow()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) if end_date else now + timedelta(days=1)
    start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else (now - timedelta(days=30))
    async with SessionLocal() as s:
        orders = (await s.execute(select(Order).where(Order.created_at >= start_dt, Order.created_at < end_dt).order_by(Order.created_at.desc()).limit(500))).scalars().all()
        user_ids = [o.user_id for o in orders]
        users_map = {}
        if user_ids:
            users_map = {u.id: u for u in (await s.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()}
    rows = ''
    total = 0
    for o in orders:
        total += int(o.amount_irt or 0)
        u = users_map.get(o.user_id)
        uname = (u.full_name or u.username or str(u.telegram_id)) if u else 'User'
        rows += f'<tr><td>#{e(o.id)}</td><td>{e(o.created_at.strftime("%Y-%m-%d"))}</td><td>{e(uname)}</td><td>{e(o.status)}</td><td>{money(o.amount_irt)} Toman</td><td>{e(o.payment_method)}</td></tr>'
    if not rows:
        rows = '<tr><td colspan="6" class="muted">No orders in this date range.</td></tr>'
    sd = start_dt.date().isoformat()
    ed = (end_dt - timedelta(days=1)).date().isoformat()
    body = f'''<div class="headrow"><h2>Orders Report</h2><a class="btn primary" href="/admin/orders-report/pdf?start_date={sd}&end_date={ed}">Download PDF</a></div>
    <form data-native="1" method="get" action="/admin/orders-report" class="formgrid" style="margin-bottom:18px">
      <label>Start date<input type="date" name="start_date" value="{sd}" required></label>
      <label>End date<input type="date" name="end_date" value="{ed}" required></label>
      <div class="full"><button class="btn primary">Filter report</button></div>
    </form>
    <div class="card" style="margin-bottom:14px"><b>Total:</b> {money(total)} Toman <span class="muted">| {len(orders)} orders</span></div>
    <div class="tablebox"><div class="table-scroll"><table><thead><tr><th>Order</th><th>Date</th><th>User</th><th>Status</th><th>Amount</th><th>Payment</th></tr></thead><tbody>{rows}</tbody></table></div></div>'''
    return layout('Orders Report','Orders Report',body,'/admin/orders-report')

@router.get('/admin/orders-report/pdf')
async def orders_report_pdf(request: Request, start_date: str | None = None, end_date: str | None = None, all: int = 0, _: str = Depends(_auth_user)):
    now = datetime.utcnow()
    if all:
        start_dt = datetime(1970, 1, 1)
        end_dt = now + timedelta(days=1)
        range_label = 'All sales from bot start'
    else:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) if end_date else now + timedelta(days=1)
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else (now - timedelta(days=30))
        range_label = f'{start_dt.date().isoformat()} to {(end_dt-timedelta(days=1)).date().isoformat()}'
    async with SessionLocal() as s:
        orders = (await s.execute(select(Order).where(Order.created_at >= start_dt, Order.created_at < end_dt).order_by(Order.created_at.asc()))).scalars().all()
        user_ids = [o.user_id for o in orders]
        plan_ids = [o.plan_id for o in orders if o.plan_id]
        users_map = {u.id: u for u in (await s.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
        plans_map = {p.id: p for p in (await s.execute(select(Plan).where(Plan.id.in_(plan_ids)))).scalars().all()} if plan_ids else {}
    rows_payload = []
    total = 0
    for o in orders:
        total += int(o.amount_irt or 0)
        u = users_map.get(o.user_id)
        p = plans_map.get(o.plan_id)
        uname = (u.full_name or u.username or str(u.telegram_id)) if u else 'User'
        plan_title = p.title if p else ('Wallet' if 'wallet' in str(o.payment_method or '').lower() else 'Custom Order')
        rows_payload.append({
            'order': f'#{o.id}',
            'date': o.created_at.strftime('%Y-%m-%d %H:%M') if o.created_at else '-',
            'user': uname,
            'plan': plan_title,
            'payment': _payment_label(o.payment_method),
            'status': o.status or '-',
            'amount': f'{money(o.amount_irt)} Toman',
        })
    return Response(sales_report_pdf('D BOT Complete Sales Report', range_label, total, rows_payload), media_type='application/pdf', headers={'Content-Disposition':'attachment; filename="dbot-complete-sales-report.pdf"'})


@router.get('/admin-legacy/service-types', response_class=HTMLResponse)
async def service_types(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        # Show everything related to service types, including items created by the bot settings page.
        all_items=(await s.execute(select(Setting).where(Setting.key.like('service_type:custom:%')))).scalars().all(); order_row=await s.get(Setting, 'service_type_order'); items=_ordered_service_types([x for x in all_items if _is_service_type_row(x)], order_row.value if order_row else '')
    form='<form method="post" action="/admin/service-types/add" class="formgrid">'+field('name','Service name')+'<div class="full"><button class="btn primary">Save</button></div></form>'
    cards=''
    for x in items:
        title=x.value if not x.key.endswith('_enabled') else ('Enabled' if x.value=='1' else 'Disabled')
        safe=x.key.replace(':','_').replace('-','_')
        cards += f"<div class='card'><h3>🧬 {e(title)}</h3><p class='muted'>Service Type</p><div class='rowactions'><button class='btn' onclick=\"openModal('stEdit{safe}')\">Edit</button><button class='btn danger' onclick=\"askDelete('/admin/service-types/delete?key={e(x.key)}')\">Delete</button></div></div>" + modal('stEdit'+safe,'Edit','Edit','<form method="post" action="/admin/service-types/edit" class="formgrid"><input type="hidden" name="key" value="'+e(x.key)+'">'+field('name','Value','text',x.value)+'<div class="full"><button class="btn primary">Save</button></div></form>')
    empty='<div class="card"><h3>🧬 No service type</h3><p class="muted">Database is raw. Add service types from here or from the bot.</p></div>' if not cards else ''
    return layout('Service Types','Service Types',"<div class='headrow'><h2 data-fa='Service Types' data-en='Service Types'>Service Types</h2><button class='btn primary' onclick=\"openModal('stAdd')\">+ Add Service Type</button></div>"+modal('stAdd','Add Service Type','Add Service Type',form)+"<div class='gridcards'>"+(cards or empty)+"</div>",'/admin/service-types')

@router.post('/admin/service-types/add')
async def st_add(request: Request, name: str = Form(...), _: str = Depends(_auth_user)):
    clean_name = (name or '').strip()
    if not clean_name:
        return fail(request, 'Enter service type name')
    safe_key = re.sub(r'[^a-zA-Z0-9_]+', '_', clean_name.lower()).strip('_') or secrets.token_hex(4)
    key = 'service_type:custom:' + safe_key
    async with SessionLocal() as s:
        existing = await s.get(Setting, key)
        if existing:
            existing.value = clean_name
        else:
            s.add(Setting(key=key, value=clean_name))
            s.add(Setting(key=_service_type_active_key(key), value='1'))
        order_row = await s.get(Setting, 'service_type_order')
        order = [x for x in ((order_row.value if order_row else '') or '').split('|') if x]
        if key not in order:
            order.append(key)
        await s.merge(Setting(key='service_type_order', value='|'.join(order)))
        await s.commit()
    return ok(request, '/admin/service-types', 'Service Types اضافه شد')
@router.post('/admin/service-types/edit')
async def st_edit(request: Request, key: str = Form(...), name: str = Form(...), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(Setting,key)
        if obj: obj.value=name; await s.commit()
    return ok(request, '/admin/service-types', 'Done')
@router.post('/admin/service-types/delete')
@router.get('/admin/service-types/delete')
async def st_del(request: Request, key: str, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(Setting,key)
        active=await s.get(Setting,_service_type_active_key(key))
        if obj: await s.delete(obj)
        if active: await s.delete(active)
        order_row = await s.get(Setting, 'service_type_order')
        if order_row:
            order_row.value = '|'.join([x for x in (order_row.value or '').split('|') if x and x != key])
        await s.commit()
    return ok(request, '/admin/service-types', 'Done')

@router.post('/admin/service-types/toggle')
@router.get('/admin/service-types/toggle')
async def st_toggle(request: Request, key: str, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj = await s.get(Setting, key)
        if not obj or not _is_service_type_row(obj):
            return fail(request, 'Service type not found', 404)
        active_key = _service_type_active_key(key)
        current = await s.get(Setting, active_key)
        next_value = '0' if (not current or current.value != '0') else '1'
        await s.merge(Setting(key=active_key, value=next_value))
        await s.commit()
    return ok(request, '/admin/service-types', 'Service type status changed')

@router.post('/admin/service-types/reorder')
async def st_reorder(request: Request, keys: str = Form(''), _: str = Depends(_auth_user)):
    wanted = [x for x in (keys or '').split('|') if x.startswith('service_type:custom:') and not x.endswith(':active')]
    async with SessionLocal() as s:
        existing = [x.key for x in (await s.execute(select(Setting).where(Setting.key.like('service_type:custom:%')))).scalars().all() if _is_service_type_row(x)]
        clean = [x for x in wanted if x in existing]
        clean += [x for x in existing if x not in clean]
        await s.merge(Setting(key='service_type_order', value='|'.join(clean)))
        await s.commit()
    return ok(request, '/admin/service-types', 'Service type order saved')




def _normalize_panel_parts(panel_url: str, panel_path: str | None = None) -> tuple[str, str, str]:
    from urllib.parse import urlsplit, urlunsplit
    raw = (panel_url or '').strip().rstrip('/')
    supplied_path = (panel_path or '').strip()
    if supplied_path == '-':
        supplied_path = '/'
    try:
        parsed = urlsplit(raw)
        base = urlunsplit((parsed.scheme, parsed.netloc, '', '', '')).rstrip('/') if parsed.scheme and parsed.netloc else raw
        url_path = (parsed.path or '').strip()
    except Exception:
        base, url_path = raw, ''
    for marker in ('/panel/api/openapi.json','/panel/api/inbounds/list','/panel/api/inbounds','/panel/api/clients','/panel/api/server','/panel/api','/panel/inbound','/panel','/login'):
        idx = url_path.find(marker)
        if idx >= 0:
            url_path = url_path[:idx]
            break
    path = supplied_path or url_path or '/'
    if not path.startswith('/'):
        path = '/' + path
    if path != '/' and not path.endswith('/'):
        path += '/'
    final = base.rstrip('/') + ('' if path == '/' else path.rstrip('/'))
    return base.rstrip('/'), path, final.rstrip('/')



def _xui_credentials_from_form(username: str = '', password: str = '', api_key: str = '') -> tuple[str, str, str]:
    """Return username, secret and auth mode for 3x-ui/Sanaei.

    Newer 3x-ui builds support API tokens through Authorization: Bearer.
    Keep session login as a fallback, but allow adding a server with only an API token.
    """
    user = (username or '').strip()
    pwd = (password or '').strip()
    token = (api_key or '').strip()
    if token:
        lowered = token.lower()
        if lowered.startswith('bearer:') or lowered.startswith('token:'):
            secret = token
        else:
            secret = f'bearer:{token}'
        return user or 'api-token', secret, 'api_token'
    return user, pwd, 'session'


def _normalize_custom_panel_origin(panel_url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    raw = (panel_url or '').strip().rstrip('/')
    if not raw:
        return ''
    if raw.endswith('/api'):
        raw = raw[:-4].rstrip('/')
    try:
        parsed = urlsplit(raw)
        if parsed.scheme and parsed.netloc:
            return urlunsplit((parsed.scheme, parsed.netloc, '', '', '')).rstrip('/')
    except Exception:
        pass
    return raw.rstrip('/')




def _circle_emoji_for_color(color: str = '') -> str:
    raw = (color or '').strip().lower()
    presets = {
        '#ef4444': '🔴', '#dc2626': '🔴', '#ff0000': '🔴',
        '#f97316': '🟠', '#ea580c': '🟠', '#ff7a00': '🟠',
        '#eab308': '🟡', '#facc15': '🟡', '#ffff00': '🟡',
        '#22c55e': '🟢', '#16a34a': '🟢', '#00ff00': '🟢',
        '#2563eb': '🔵', '#3b82f6': '🔵', '#0000ff': '🔵',
        '#7c3aed': '🟣', '#9333ea': '🟣', '#8000ff': '🟣',
        '#111827': '⚫', '#000000': '⚫',
        '#ffffff': '⚪', '#f8fafc': '⚪',
        '#92400e': '🟤', '#a16207': '🟤', '#8b4513': '🟤',
    }
    if raw in presets:
        return presets[raw]
    m = re.match(r'^#([0-9a-f]{6})$', raw)
    if not m:
        return '🔵'
    value = m.group(1)
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    if max(r, g, b) < 50:
        return '⚫'
    if min(r, g, b) > 220:
        return '⚪'
    if r > 120 and g > 65 and b < 80:
        return '🟤' if r < 190 and g < 130 else '🟠'
    if r >= 190 and g >= 150 and b < 110:
        return '🟡'
    if g >= r and g >= b:
        return '🟢'
    if b >= r and b >= g:
        return '🔵' if r < 130 else '🟣'
    if r >= g and r >= b:
        return '🔴'
    return '🔵'



def _default_service_badge(server_type: str = 'xui', protocol: str = '') -> tuple[str, str, str]:
    st = (server_type or '').lower()
    pr = (protocol or '').lower()
    if st == 'mikrotik' or pr in ('openvpn', 'ovpn', 'l2tp', 'mikrotik'):
        return '#f97316', '🟠', 'MikroTik / OpenVPN'
    return '#2563eb', '🔵', 'V2Ray'

def _server_badge_meta(server_type: str = 'xui', badge_color: str = '', badge_label: str = '', badge_emoji: str = '', protocol: str = '') -> dict[str, str]:
    color, emoji, label = _default_service_badge(server_type, protocol)
    submitted_color = (badge_color or '').strip()
    # Add Server has one shared form. If the user switches to MikroTik / Custom
    # and leaves the default V2 blue untouched, use the MikroTik orange default.
    if (server_type or '').lower() == 'mikrotik' and submitted_color.lower() == '#2563eb' and not badge_label and not badge_emoji:
        submitted_color = ''
    color = (submitted_color or color).strip()
    if not re.match(r'^#[0-9a-fA-F]{6}$', color):
        color = _default_service_badge(server_type, protocol)[0]
    # Circle emoji in the bot is intentionally derived from the website circle color.
    # This keeps admin cards and Telegram buttons/lists visually consistent.
    emoji = _circle_emoji_for_color(color)
    label = (badge_label or label).strip()[:80]
    return {'badge_color': color, 'badge_emoji': emoji, 'badge_label': label}

def _router_display_name(row: dict[str, Any]) -> str:
    name = str(row.get('name') or '').strip()
    return f'MikroTik / Custom - {name}' if name else 'MikroTik / Custom'


def _custom_panel_server_payload(origin: str, auth_username: str, password: str, scope: str, router: dict[str, Any], display_name: str = '', default_protocol: str = 'openvpn', openvpn_profile_id: int = 0, l2tp_server: str = '', l2tp_ipsec_secret: str = '', badge_color: str = '', badge_label: str = '', badge_emoji: str = '') -> dict[str, Any]:
    name = str(router.get('name') or '').strip()
    safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '-', name or 'router').strip('-').lower() or 'router'
    router_display = _router_display_name(router)
    custom_display = (display_name or '').strip()
    display = f'{custom_display} ({name})' if custom_display and name and custom_display.lower() != name.lower() else (custom_display or router_display)
    meta = {
        'display_name': display,
        'scope': scope if scope in ('public','reseller','all') else 'all',
        'panel_base_url': origin,
        'panel_path': '/',
        'custom_panel': True,
        'custom_panel_name': 'MikroTik / Custom',
        'router_name': name,
        'auth_username': auth_username,
        'panel_username': auth_username,
        'default_protocol': default_protocol or 'openvpn',
        'openvpn_profile_id': int(openvpn_profile_id or 0),
        'l2tp_server': l2tp_server or 'vpn.example.com',
        'l2tp_ipsec_secret': l2tp_ipsec_secret or 'CHANGE_ME_IPSEC_SECRET',
        'inbound_ids': [],
        'inbounds': [],
        'router_host': router.get('host') or '',
        'router_port': router.get('port') or '',
        'router_online': bool(router.get('online', True)),
        'router_identity': router.get('identity') or '',
        'router_version': router.get('version') or '',
        'router_uptime': router.get('uptime') or '',
        'router_secrets': int(router.get('secrets') or 0),
        'router_active': int(router.get('active') or 0),
        'router_error': router.get('error') or '',
        'routers_snapshot': [router],
        'last_router_sync_at': datetime.utcnow().isoformat(timespec='seconds'),
    }
    meta.update(_server_badge_meta('mikrotik', badge_color, badge_label, badge_emoji, default_protocol))
    return {
        'name': (re.sub(r'[^a-zA-Z0-9_-]+', '-', (custom_display or f'mikrotik-{safe_name}')).strip('-').lower() or f'mikrotik-{safe_name}') + (f'-{safe_name}' if custom_display else ''),
        'display_name': display,
        'router_name': name,
        'meta': meta,
    }


async def _test_custom_panel_connection(panel_url: str, username: str, password: str, api_key: str = '') -> tuple[str, list[dict[str, Any]], str]:
    origin = _normalize_custom_panel_origin(panel_url)
    if not origin:
        raise RuntimeError('MikroTik / Custom URL is required.')
    username = (username or '').strip()
    password = password or ''
    api_key = (api_key or '').strip()
    if not username:
        raise RuntimeError('MikroTik / Custom username is required.')
    if not password and not api_key:
        raise RuntimeError('MikroTik / Custom login password is required.')

    # The documented API accepts API-key headers only. The form still accepts the
    # normal panel login so the service can try session login where supported,
    # and can auto-load the API key from env or `/opt/mikrotik-panel/config.json`
    # when D BOT is installed beside the MikroTik / Custom. If an optional API key is
    # supplied, test that directly and save it as the server secret.
    secret_for_test = api_key or password
    fake = Server(
        name='custom-panel-test',
        server_type='mikrotik',
        panel_url=origin,
        subscription_url=None,
        username='',
        password_encrypted=encrypt_text(secret_for_test),
        is_active=True,
        meta={'auth_username': username, 'panel_username': username, 'panel_base_url': origin, 'custom_panel': True},
    )
    service = MikroTikService()
    try:
        routers = await service.routers(fake)
    except Exception as exc:
        msg = str(exc)
        if 'unauthorized' in msg.lower():
            msg = (
                'Unauthorized: /api/routers needs X-API-Key / Bearer auth according to this MikroTik / Custom API. '
                'Enter the API key from config.json in Add Server > Profile: MikroTik / Custom, or set CUSTOM_PANEL_API_KEY in .env / mount the config file. '
                'Panel URL, username, and login password are never stored as source-code defaults.'
            )
        raise RuntimeError(msg) from exc
    routers = [r for r in routers if isinstance(r, dict) and str(r.get('name') or '').strip()]
    if not routers:
        raise RuntimeError('MikroTik / Custom connected, but no routers were returned from /api/routers.')
    resolved_secret = str(getattr(service, 'last_successful_auth_secret', '') or api_key or secret_for_test).strip()
    return origin, routers, resolved_secret

@router.get('/admin-legacy/servers', response_class=HTMLResponse)
async def servers(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
        counts=dict((await s.execute(select(ClientService.server_id,func.count(ClientService.id)).group_by(ClientService.server_id))).all())
    scope_select = select_field('scope','Show for',[('public','Public sales'),('reseller','Reseller'),('all','Public + Reseller')],'public')
    add_form='<form method="post" action="/admin/servers/add" class="formgrid"><div><label>Profile</label><select name="server_type"><option value="xui">3x-ui Sanaei</option><option value="mikrotik">MikroTik / Custom</option></select></div>'+scope_select+field('name','Server name')+field('display_name','Display name')+field('panel_url','Panel URL / Origin')+field('panel_path','Panel Web Path','text','/')+field('subscription_url','Subscription URL')+field('username','Username')+field('password','Password','password')+field('api_key','MikroTik / Custom API Key','password')+field('badge_label','Service badge text','text','')+field('badge_color','Service badge color','color','#2563eb')+field('badge_emoji','Bot circle emoji','text','')+field('l2tp_server','L2TP Server','text','vpn.example.com')+field('l2tp_ipsec_secret','L2TP Secret','text','CHANGE_ME_IPSEC_SECRET')+'<div class="full"><button class="btn primary">Save</button></div></form>'
    cards=[]
    for sv in items:
        m=sv.meta or {}; inbs=m.get('inbound_ids') or []
        edit='<form method="post" action="/admin/servers/'+str(sv.id)+'/edit" class="formgrid">'+field('name','Server name','text',sv.name)+select_field('scope','Show for',[('public','Public sales'),('reseller','Reseller'),('all','Public + Reseller')],server_scope(sv))+field('display_name','Display name','text',m.get('display_name') or sv.name)+field('panel_url','Panel URL / Origin','text',m.get('panel_base_url') or sv.panel_url)+field('panel_path','Panel Web Path','text',m.get('panel_path') or '/')+field('subscription_url','Subscription URL','text',sv.subscription_url or '')+field('username','Username','text',sv.username)+field('password','New password','password')+field('api_key','New MikroTik / Custom API Key','password')+field('badge_label','Service badge text','text',m.get('badge_label') or ('MikroTik / OpenVPN' if sv.server_type == 'mikrotik' else 'V2Ray'))+field('badge_color','Service badge color','color',m.get('badge_color') or ('#f97316' if sv.server_type == 'mikrotik' else '#2563eb'))+field('badge_emoji','Bot circle emoji','text',m.get('badge_emoji') or ('🟠' if sv.server_type == 'mikrotik' else '🔵'))+field('l2tp_server','L2TP Server','text',m.get('l2tp_server') or 'vpn.example.com')+field('l2tp_ipsec_secret','L2TP Secret','text',m.get('l2tp_ipsec_secret') or 'CHANGE_ME_IPSEC_SECRET')+'<div class="full"><button class="btn primary">Save</button></div></form>'
        cards.append(f'''<div class="card server-card"><div class="server-glow"></div><div class="headrow"><h3><span class="service-dot" style="background:{e(m.get('badge_color') or ('#f97316' if sv.server_type == 'mikrotik' else '#2563eb'))}"></span> {e(m.get('display_name') or sv.name)} <small class="muted">{e(m.get('badge_label') or ('MikroTik / OpenVPN' if sv.server_type == 'mikrotik' else 'V2Ray'))}</small></h3><span class="badge status" data-fa="Online" data-en="Online">Online</span></div><div class="server-meta"><div><span>Panel</span><b>{e(sv.server_type)}</b></div><div><span>Users</span><b>{counts.get(sv.id,0)}</b></div><div><span>Inbound</span><b>{len(inbs)}</b></div><div><span>Status</span><b>ON</b></div></div><div class="kvs"><div class="kv"><span>Server name</span><b>{e(sv.name)}</b></div><div class="kv"><span>Panel type</span><b>{e(sv.server_type)}</b></div><div class="kv"><span>Usage</span><b>Public sales / Resellers</b></div><div class="kv"><span>Users</span><b>{counts.get(sv.id,0)}</b></div><div class="kv"><span>Inbound</span><b>{len(inbs)}</b></div></div><div class="rowactions"><a data-action="1" class="btn success" href="/admin/servers/{sv.id}/refresh">Refresh</a><button class="btn" onclick="openModal('srvEdit{sv.id}')">Edit</button><a data-action="1" class="btn {'danger' if sv.is_active else 'success'}" href="/admin/toggle/servers/{sv.id}">{'Deactivate' if sv.is_active else 'Activate'}</a><a data-action="1" class="btn" href="/admin/servers/{sv.id}/duplicate">Duplicate</a><button class="btn danger" onclick="askDelete('/admin/servers/{sv.id}/delete')">Delete</button></div></div>{modal('srvEdit'+str(sv.id),'Edit Server','Edit Server',edit)}''')
    return layout('Servers','Servers','<div class="headrow"><h2>Servers</h2><button class="btn primary" onclick="openModal(\'srvAdd\')">+ Add Server</button></div>'+modal('srvAdd','Add Server','Add Server',add_form)+'<div class="gridcards">'+''.join(cards)+'</div>','/admin/servers')

@router.post('/admin/servers/test')
async def server_test(request: Request, server_type:str=Form('xui'), panel_url:str=Form(...), panel_path:str=Form('/'), username:str=Form(''), password:str=Form(''), api_key:str=Form(''), router_name:str=Form(''), _: str = Depends(_auth_user)):
    if server_type == 'mikrotik':
        try:
            origin, routers, _secret_to_save = await _test_custom_panel_connection(panel_url, username, password, api_key)
        except Exception as exc:
            logger.warning('MikroTik / Custom connection test failed from Add Server: %s', exc)
            return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
        auto_fill = {
            'panel_url': origin,
            'detected_routers': ', '.join(str(r.get('name') or '') for r in routers if r.get('name')),
        }
        online = sum(1 for r in routers if bool(r.get('online', True)))
        return JSONResponse({'ok': True, 'message': f'MikroTik / Custom connected. {len(routers)} router(s) found, {online} online.', 'routers': routers, 'auto_fill': auto_fill})
    if server_type != 'xui':
        return JSONResponse({'ok': True, 'message': 'Connection OK.', 'inbound_ids': []})
    xui_username, xui_secret, xui_auth_mode = _xui_credentials_from_form(username, password, api_key)
    if not xui_secret:
        return fail(request, '3x-ui API token or panel password is required to test the connection.', 400)
    if xui_auth_mode == 'session' and not xui_username:
        return fail(request, '3x-ui username is required when using panel username/password login. API token mode does not need username.', 400)
    base_url, web_path, final_url = _normalize_panel_parts(panel_url, panel_path)
    fake = Server(name='test', server_type=server_type, panel_url=final_url, subscription_url=None, username=xui_username, password_encrypted=encrypt_text(xui_secret), is_active=True, meta={'panel_base_url': base_url, 'panel_path': web_path, 'auth_mode': xui_auth_mode})
    try:
        ok_conn, rows = await XuiService().test_server(fake)
    except Exception:
        logger.exception('X-UI connection test failed')
        return fail(request, 'Connection test failed. Check server logs.', 400)
    if not ok_conn:
        return fail(request, '3x-ui connection failed. Check panel URL/path and API token, or username/password if using session login.', 400)
    inbounds = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            iid = int(row.get('id'))
        except Exception:
            continue
        inbounds.append({'id': iid, 'remark': row.get('remark') or row.get('tag') or row.get('name') or f'Inbound {iid}', 'protocol': row.get('protocol') or row.get('proto') or ''})
    autofill = {
        'panel_url': base_url,
        'panel_path': web_path,
        'name': 'xui-' + (base_url.split('//')[-1].split('/')[0].split(':')[0].replace('.', '-') or 'server'),
        'display_name': base_url.split('//')[-1].split('/')[0],
    }
    return JSONResponse({'ok': True, 'message': f'Connection OK. {len(inbounds)} inbound(s) found.', 'inbound_ids': [x['id'] for x in inbounds], 'inbounds': inbounds, 'auto_fill': autofill})

@router.post('/admin/custom-panel/test')
async def custom_panel_test(request: Request, panel_url: str = Form(...), username: str = Form(...), password: str = Form(...), api_key: str = Form(''), _: str = Depends(_auth_user)):
    try:
        origin, routers, secret_to_save = await _test_custom_panel_connection(panel_url, username, password, api_key)
    except Exception as exc:
        logger.warning('MikroTik / Custom connection test failed: %s', exc)
        return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
    auto_fill = {
        'panel_url': origin,
        'name': 'custom-panel',
        'display_name': 'MikroTik / Custom',
        'router_names': ', '.join(str(r.get('name') or '') for r in routers if r.get('name')),
    }
    online = sum(1 for r in routers if bool(r.get('online', True)))
    return JSONResponse({'ok': True, 'message': f'MikroTik / Custom connected. {len(routers)} router(s) found, {online} online.', 'routers': routers, 'auto_fill': auto_fill})


@router.post('/admin/custom-panel/add')
async def custom_panel_add(request: Request, panel_url: str = Form(...), username: str = Form(...), password: str = Form(...), api_key: str = Form(''), scope: str = Form('all'), _: str = Depends(_auth_user)):
    try:
        origin, routers, secret_to_save = await _test_custom_panel_connection(panel_url, username, password, api_key)
    except Exception as exc:
        logger.warning('MikroTik / Custom add failed: %s', exc)
        return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
    saved = 0
    async with SessionLocal() as s:
        for router_row in routers:
            payload = _custom_panel_server_payload(origin, username.strip(), secret_to_save, scope, router_row)
            router_name = payload['router_name']
            existing = (await s.execute(select(Server).where(Server.server_type == 'mikrotik', Server.username == router_name, Server.panel_url == origin))).scalars().first()
            if not existing:
                existing = (await s.execute(select(Server).where(Server.server_type == 'mikrotik', Server.name == payload['name']))).scalars().first()
            if existing:
                existing.name = payload['name']
                existing.panel_url = origin
                existing.subscription_url = None
                existing.username = router_name
                existing.password_encrypted = encrypt_text(secret_to_save)
                existing.is_active = bool(router_row.get('online', True))
                meta = dict(existing.meta or {})
                meta.update(payload['meta'])
                existing.meta = meta
            else:
                existing = Server(
                    name=payload['name'],
                    server_type='mikrotik',
                    panel_url=origin,
                    subscription_url=None,
                    username=router_name,
                    password_encrypted=encrypt_text(secret_to_save),
                    is_active=bool(router_row.get('online', True)),
                    meta=payload['meta'],
                )
                s.add(existing)
            saved += 1
        await s.commit()
    return ok(request, '/admin/servers', f'MikroTik / Custom saved. {saved} router server(s) created/updated.')


@router.post('/admin/custom-panel/{sid}/edit')
async def custom_panel_edit(request: Request, sid: int, panel_url: str = Form(...), username: str = Form(...), password: str = Form(''), api_key: str = Form(''), scope: str = Form('all'), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        current = await s.get(Server, sid)
        if not current:
            raise HTTPException(404)
        if current.server_type != 'mikrotik':
            return fail(request, 'This is not a MikroTik / Custom server.', 400)
        current_username = current.username
        stored_password = (api_key or password or decrypt_text(current.password_encrypted or ''))
    try:
        origin, routers, secret_to_save = await _test_custom_panel_connection(panel_url, username, stored_password, api_key)
    except Exception as exc:
        logger.warning('MikroTik / Custom edit failed: %s', exc)
        return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
    saved = 0
    async with SessionLocal() as s:
        # Update/create one internal server per router returned by the panel.
        for router_row in routers:
            payload = _custom_panel_server_payload(origin, username.strip(), secret_to_save, scope, router_row)
            router_name = payload['router_name']
            existing = (await s.execute(select(Server).where(Server.server_type == 'mikrotik', Server.username == router_name, Server.panel_url == origin))).scalars().first()
            if not existing:
                existing = await s.get(Server, sid) if router_name == current_username else None
            if existing:
                existing.name = payload['name']
                existing.panel_url = origin
                existing.subscription_url = None
                existing.username = router_name
                existing.password_encrypted = encrypt_text(secret_to_save)
                existing.is_active = bool(router_row.get('online', True))
                meta = dict(existing.meta or {})
                meta.update(payload['meta'])
                existing.meta = meta
            else:
                existing = Server(
                    name=payload['name'], server_type='mikrotik', panel_url=origin,
                    subscription_url=None, username=router_name,
                    password_encrypted=encrypt_text(secret_to_save),
                    is_active=bool(router_row.get('online', True)), meta=payload['meta']
                )
                s.add(existing)
            saved += 1
        await s.commit()
    return ok(request, '/admin/servers', f'MikroTik / Custom updated. {saved} router server(s) synchronized.')


@router.post('/admin/servers/add')
async def server_add(request: Request, server_type:str=Form('xui'), scope:str=Form('public'), name:str=Form(''), display_name:str=Form(''), panel_url:str=Form(...), panel_path:str=Form('/'), subscription_url:str=Form(''), username:str=Form(''), password:str=Form(''), api_key:str=Form(''), router_name:str=Form(''), default_protocol:str=Form('openvpn'), openvpn_profile_id:int=Form(0), l2tp_server:str=Form(''), l2tp_ipsec_secret:str=Form(''), badge_color:str=Form(''), badge_label:str=Form(''), badge_emoji:str=Form(''), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        if server_type == 'mikrotik':
            if not ((display_name or name or '').strip()):
                return fail(request, 'Server name is required for MikroTik / Custom servers.', 400)
            try:
                origin, routers, secret_to_save = await _test_custom_panel_connection(panel_url, username, password, api_key)
            except Exception as exc:
                logger.warning('MikroTik / Custom add failed from Add Server: %s', exc)
                return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
            saved = 0
            for router_row in routers:
                payload = _custom_panel_server_payload(origin, username.strip(), secret_to_save, scope, router_row, display_name=(display_name or name), default_protocol=default_protocol, openvpn_profile_id=openvpn_profile_id, l2tp_server=l2tp_server, l2tp_ipsec_secret=l2tp_ipsec_secret, badge_color=badge_color, badge_label=badge_label, badge_emoji=badge_emoji)
                router_name_saved = payload['router_name']
                existing = (await s.execute(select(Server).where(Server.server_type == 'mikrotik', Server.username == router_name_saved, Server.panel_url == origin))).scalars().first()
                if not existing:
                    existing = (await s.execute(select(Server).where(Server.server_type == 'mikrotik', Server.name == payload['name']))).scalars().first()
                if existing:
                    existing.name = payload['name']
                    existing.panel_url = origin
                    existing.subscription_url = None
                    existing.username = router_name_saved
                    existing.password_encrypted = encrypt_text(secret_to_save)
                    existing.is_active = bool(router_row.get('online', True))
                    meta = dict(existing.meta or {})
                    meta.update(payload['meta'])
                    existing.meta = meta
                else:
                    s.add(Server(
                        name=payload['name'],
                        server_type='mikrotik',
                        panel_url=origin,
                        subscription_url=None,
                        username=router_name_saved,
                        password_encrypted=encrypt_text(secret_to_save),
                        is_active=bool(router_row.get('online', True)),
                        meta=payload['meta'],
                    ))
                saved += 1
            await s.commit()
            return ok(request, '/admin/servers', f'MikroTik / Custom saved. {saved} router server(s) created/updated.')
        if not (name or '').strip():
            return fail(request, 'Server name is required for 3x-ui servers.', 400)
        xui_username, xui_secret, xui_auth_mode = _xui_credentials_from_form(username, password, api_key)
        if not xui_secret:
            return fail(request, '3x-ui API token or panel password is required.', 400)
        if xui_auth_mode == 'session' and not xui_username:
            return fail(request, '3x-ui username is required when using panel username/password login. API token mode does not need username.', 400)
        base_url, web_path, final_url = _normalize_panel_parts(panel_url, panel_path)
        srv=Server(name=name,server_type=server_type,panel_url=final_url,subscription_url=subscription_url or None,username=xui_username,password_encrypted=encrypt_text(xui_secret),is_active=True,meta={**{'display_name':display_name or name,'inbound_ids':[],'inbounds':[],'scope':scope if scope in ('public','reseller','all') else 'public','panel_base_url':base_url,'panel_path':web_path,'auth_mode':xui_auth_mode}, **_server_badge_meta('xui', badge_color, badge_label, badge_emoji)})
        s.add(srv); await s.commit(); await s.refresh(srv)
        ok_sync, old_ids, new_ids, err = await refresh_server_inbounds(s,srv,force_plan_update=True)
        await s.commit()
        if not ok_sync:
            logger.warning('Server saved but inbound sync failed: %s', err)
            return fail(request, 'Server saved, but panel test/inbound sync failed. Check server logs.')
    return ok(request, '/admin/servers', f'Server added and {len(new_ids)} inbound(s) synchronized')
@router.post('/admin/servers/{sid}/edit')
async def server_edit(request: Request, sid:int, name:str=Form(...), scope:str=Form('public'), display_name:str=Form(''), panel_url:str=Form(...), panel_path:str=Form('/'), subscription_url:str=Form(''), username:str=Form(''), password:str=Form(''), api_key:str=Form(''), router_name:str=Form(''), default_protocol:str=Form('openvpn'), openvpn_profile_id:int=Form(0), l2tp_server:str=Form(''), l2tp_ipsec_secret:str=Form(''), badge_color:str=Form(''), badge_label:str=Form(''), badge_emoji:str=Form(''), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        srv=await s.get(Server,sid)
        if not srv: raise HTTPException(404)
        server_type = getattr(srv, 'server_type', None)
        if server_type == 'mikrotik':
            meta=dict(srv.meta or {})
            router=(router_name or meta.get('router_name') or srv.username or '').strip()
            auth_username=(username or meta.get('auth_username') or '').strip()
            srv.name=name or srv.name; srv.panel_url=(panel_url or '').strip().rstrip('/'); srv.subscription_url=None; srv.username=router
            if api_key or password: srv.password_encrypted=encrypt_text(api_key or password)
            meta.update({'display_name':display_name or name or srv.name,'scope':scope if scope in ('public','reseller','all') else 'public','panel_base_url':srv.panel_url,'router_name':router,'auth_username':auth_username,'default_protocol':default_protocol or meta.get('default_protocol') or 'openvpn','openvpn_profile_id':int(openvpn_profile_id or 0),'l2tp_server':l2tp_server or meta.get('l2tp_server') or 'vpn.example.com','l2tp_ipsec_secret':l2tp_ipsec_secret or meta.get('l2tp_ipsec_secret') or 'CHANGE_ME_IPSEC_SECRET'}); meta.update(_server_badge_meta('mikrotik', badge_color, badge_label, badge_emoji, default_protocol)); srv.meta=meta
            await s.commit()
            return ok(request, '/admin/servers', 'MikroTik server updated')
        base_url, web_path, final_url = _normalize_panel_parts(panel_url, panel_path)
        xui_username, xui_secret, xui_auth_mode = _xui_credentials_from_form(username, password, api_key)
        if xui_secret and xui_auth_mode == 'session' and not xui_username:
            return fail(request, '3x-ui username is required when using panel username/password login. API token mode does not need username.', 400)
        srv.name=name; srv.panel_url=final_url; srv.subscription_url=subscription_url or None
        if xui_secret:
            srv.username=xui_username
            srv.password_encrypted=encrypt_text(xui_secret)
        elif username:
            srv.username=username
        meta=dict(srv.meta or {}); meta['display_name']=display_name or name; meta['scope']=scope if scope in ('public','reseller','all') else 'public'; meta['panel_base_url']=base_url; meta['panel_path']=web_path
        if xui_secret:
            meta['auth_mode']=xui_auth_mode
        meta.update(_server_badge_meta('xui', badge_color, badge_label, badge_emoji))
        srv.meta=meta
        await s.flush()
        ok_sync, old_ids, new_ids, err = await refresh_server_inbounds(s,srv,force_plan_update=True)
        await s.commit()
        if not ok_sync:
            logger.warning('Server updated but inbound sync failed: %s', err)
            return fail(request, 'Server updated, but panel test/inbound sync failed. Check server logs.')
    return ok(request, '/admin/servers', f'Server updated and {len(new_ids)} inbound(s) synchronized')
@router.post('/admin/servers/{sid}/refresh')
@router.get('/admin/servers/{sid}/refresh')
async def server_refresh(request: Request, sid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        srv=await s.get(Server,sid)
        if not srv: raise HTTPException(404)
        if srv.server_type == 'mikrotik':
            try:
                routers = await MikroTikService().routers(srv)
            except Exception as exc:
                return fail(request, 'MikroTik / Custom connection failed: ' + str(exc), 400)
            meta = dict(srv.meta or {})
            router_name = str(meta.get('router_name') or srv.username or '').strip()
            matched = None
            for row in routers:
                if str(row.get('name') or '').strip().lower() == router_name.lower():
                    matched = row
                    break
            matched = matched or (routers[0] if routers else {})
            if matched:
                meta.update({
                    'custom_panel': True,
                    'custom_panel_name': 'MikroTik / Custom',
                    'router_name': str(matched.get('name') or router_name).strip(),
                    'router_host': matched.get('host') or '',
                    'router_port': matched.get('port') or '',
                    'router_online': bool(matched.get('online', True)),
                    'router_identity': matched.get('identity') or '',
                    'router_version': matched.get('version') or '',
                    'router_uptime': matched.get('uptime') or '',
                    'router_secrets': int(matched.get('secrets') or 0),
                    'router_active': int(matched.get('active') or 0),
                    'router_error': matched.get('error') or '',
                    'routers_snapshot': routers,
                    'last_router_sync_at': datetime.utcnow().isoformat(timespec='seconds'),
                })
                srv.username = str(matched.get('name') or router_name).strip()
                srv.is_active = bool(matched.get('online', True))
                srv.meta = meta
            await s.commit()
            return ok(request, '/admin/servers', f'MikroTik / Custom OK. {len(routers)} router(s) found.')
        ok_sync, old_ids, new_ids, err = await refresh_server_inbounds(s,srv,force_plan_update=True)
        await s.commit()
        if not ok_sync:
            return fail(request, 'Panel connection/inbound refresh failed: ' + (err or 'Unknown error'))
    return ok(request, '/admin/servers', f'Connection OK. {len(new_ids)} inbound(s) synchronized')
@router.post('/admin/servers/{sid}/duplicate')
@router.get('/admin/servers/{sid}/duplicate')
async def server_dup(request: Request, sid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        srv=await s.get(Server,sid)
        if not srv: raise HTTPException(404)
        meta=dict(srv.meta or {}); meta['display_name']=f"{meta.get('display_name') or srv.name} 2"
        s.add(Server(name=f'{srv.name} 2',server_type=srv.server_type,panel_url=srv.panel_url,subscription_url=srv.subscription_url,username=srv.username,password_encrypted=srv.password_encrypted,category_id=srv.category_id,is_active=srv.is_active,meta=meta)); await s.commit()
    return ok(request, '/admin/servers', 'Done')
@router.post('/admin/servers/{sid}/delete')
@router.get('/admin/servers/{sid}/delete')
async def server_delete(request: Request, sid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        srv=await s.get(Server,sid)
        if not srv: return fail(request, 'Server not found', 404)
        # Keep existing users/services alive, but detach them from the deleted server record.
        # This prevents foreign-key errors and removes the server from the admin database list.
        await s.execute(update(ClientService).where(ClientService.server_id==sid).values(server_id=None))
        await s.execute(update(Plan).where(Plan.server_id==sid).values(server_id=None, is_active=False))
        await s.execute(update(ServerCategory).where(ServerCategory.server_id==sid).values(server_id=None))
        await s.execute(update(PaymentCard).where(PaymentCard.server_id==sid).values(server_id=None))
        await s.execute(update(ResellerAccount).where(ResellerAccount.server_id==sid).values(server_id=None))
        await s.execute(update(ResellerBuildConfig).where(ResellerBuildConfig.server_id==sid).values(server_id=None, is_active=False))
        package_ids = [row[0] for row in (await s.execute(select(ResellerPackage.id).where(ResellerPackage.server_id==sid))).all()]
        if package_ids:
            await s.execute(delete(ResellerTopupRequest).where(ResellerTopupRequest.package_id.in_(package_ids)))
            await s.execute(delete(ResellerPackage).where(ResellerPackage.id.in_(package_ids)))
        await s.delete(srv); await s.commit()
    return ok(request, '/admin/servers', 'Server deleted and user services were kept.')



def _parse_id_list(raw_value: Any = '', fallback: int = 0) -> list[int]:
    values: list[str] = []
    if raw_value is None:
        raw_value = ''
    if isinstance(raw_value, (list, tuple, set)):
        for item in raw_value:
            values.extend(str(item or '').split(','))
    else:
        values.extend(str(raw_value or '').split(','))
    ids: list[int] = []
    for part in values:
        part = str(part or '').strip()
        if not part:
            continue
        try:
            sid = int(part)
        except Exception:
            continue
        if sid > 0 and sid not in ids:
            ids.append(sid)
    try:
        fb = int(fallback or 0)
    except Exception:
        fb = 0
    if not ids and fb > 0:
        ids.append(fb)
    return ids


def _category_linked_server_ids(cat: ServerCategory | None) -> list[int]:
    if not cat:
        return []
    ids = _parse_id_list(getattr(cat, 'server_ids', None) or [])
    try:
        sid = int(getattr(cat, 'server_id', 0) or 0)
    except Exception:
        sid = 0
    if sid > 0 and sid not in ids:
        ids.append(sid)
    return ids


async def _category_form_values(request: Request) -> tuple[str, list[int]]:
    form = await request.form()
    name = str(form.get('name') or '').strip()
    raw_values = []
    for key in ('server_ids', 'server_id'):
        try:
            raw_values.extend(form.getlist(key))
        except Exception:
            pass
        if form.get(key) not in (None, ''):
            raw_values.append(form.get(key))
    server_ids = _parse_id_list(raw_values)
    return name, server_ids


async def _save_category_single(session, *, name: str, server_ids: list[int], category_id: int | None = None) -> ServerCategory:
    clean_name = (name or '').strip()
    if not clean_name:
        raise ValueError('Category name is required.')
    obj = await session.get(ServerCategory, int(category_id)) if category_id else None
    old_name = obj.name if obj else clean_name
    if obj is None:
        obj = (await session.execute(
            select(ServerCategory).where(func.lower(ServerCategory.name) == clean_name.lower()).order_by(ServerCategory.id.asc())
        )).scalars().first()
    if obj is None:
        obj = ServerCategory(name=clean_name, server_id=(server_ids[0] if server_ids else None), server_ids=server_ids, is_active=True)
        session.add(obj)
        await session.flush()
    else:
        obj.name = clean_name
        obj.server_id = server_ids[0] if server_ids else None
        obj.server_ids = server_ids
        obj.is_active = True
        await session.flush()

    rows = (await session.execute(
        select(ServerCategory).where(func.lower(ServerCategory.name) == (old_name or clean_name).strip().lower(), ServerCategory.id != obj.id)
    )).scalars().all()
    for dup in rows:
        await session.execute(update(Plan).where(Plan.category_id == dup.id).values(category_id=obj.id))
        dup.name = clean_name
        dup.server_ids = []
        dup.is_active = False
    await session.flush()
    return obj


def _server_options_html(servers, selected: list[int] | None = None, field_name: str = 'server_ids') -> str:
    selected = selected or []
    return ''.join(f'<label class="checkline"><input type="checkbox" name="{field_name}" value="{x.id}" {"checked" if x.id in selected else ""}> {e((x.meta or {}).get("display_name") or x.name)}</label>' for x in servers)


def _discount_allowed_server_ids(d: DiscountCode | None) -> list[int]:
    if not d:
        return []
    return _parse_id_list(getattr(d, 'allowed_server_ids', None) or [])


async def _discount_form_values(request: Request) -> tuple[str, str, int, int, int, list[int]]:
    form = await request.form()
    code = str(form.get('code') or '').strip().upper().replace(' ', '')
    discount_type = str(form.get('discount_type') or 'percent')
    value = int(form.get('value') or 0)
    max_uses = int(form.get('max_uses') or 1)
    per_user_limit = int(form.get('per_user_limit') or 1)
    raw_values = []
    try:
        raw_values.extend(form.getlist('allowed_server_ids'))
    except Exception:
        pass
    if form.get('allowed_server_ids') not in (None, ''):
        raw_values.append(form.get('allowed_server_ids'))
    server_ids = _parse_id_list(raw_values)
    return code, discount_type, value, max_uses, per_user_limit, server_ids


@router.get('/admin-legacy/categories', response_class=HTMLResponse)
async def categories(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        raw_items=(await s.execute(select(ServerCategory).order_by(ServerCategory.id.desc()))).scalars().all(); srvs=(await s.execute(select(Server))).scalars().all()
    items=[]; seen=set()
    for c in raw_items:
        key=(c.name or '').strip().lower()
        if key in seen:
            continue
        seen.add(key); items.append(c)
    form='<form method="post" action="/admin/categories/add" class="formgrid">'+field('name','Category name')+f'<div class="full"><label>Servers</label><div class="checkbox-grid">{_server_options_html(srvs)}</div><small class="muted">هر سروری که می‌خواهید این کتگوری داخلش نمایش داده شود را تیک بزنید.</small></div><div class="full"><button class="btn primary">Save</button></div></form>'
    cards=''
    for c in items:
        selected=_category_linked_server_ids(c)
        names=[((srv.meta or {}).get('display_name') or srv.name) for srv in srvs if srv.id in selected]
        edit='<form method="post" action="/admin/categories/'+str(c.id)+'/edit" class="formgrid">'+field('name','Category name','text',c.name)+f'<div class="full"><label>Servers</label><div class="checkbox-grid">{_server_options_html(srvs, selected)}</div><small class="muted">برای انتخاب چند سرور فقط تیک بزنید.</small></div><div class="full"><button class="btn primary">Save</button></div></form>'
        linked = ', '.join(names) if names else '-'
        cards+=f'<div class="card"><h3>🗂 {e(c.name)}</h3><p class="muted">Servers: {e(linked)}</p><p class="muted">Status: {"Active" if getattr(c,"is_active",True) else "Inactive"}</p><div class="rowactions"><button class="btn" onclick="openModal(\'catEdit{c.id}\')">Edit</button><button class="btn danger" onclick="askDelete(\'/admin/categories/{c.id}/delete\')">Delete</button></div></div>'+modal('catEdit'+str(c.id),'Edit Category','Edit Category',edit)
    return layout('Categories','Categories','<div class="headrow"><h2>Categories</h2><button class="btn primary" onclick="openModal(\'catAdd\')">+ Add Category</button></div>'+modal('catAdd','Add Category','Add Category',form)+'<div class="gridcards">'+cards+'</div>','/admin/categories')

@router.post('/admin/categories/add')
async def cat_add(request: Request, _: str = Depends(_auth_user)):
    name, server_ids = await _category_form_values(request)
    if not name:
        return fail(request, 'Category name is required.', 400)
    async with SessionLocal() as s:
        await _save_category_single(s, name=name, server_ids=server_ids)
        await s.commit()
    return ok(request, '/admin/categories', 'Category saved')

@router.post('/admin/categories/{cid}/edit')
async def cat_edit(request: Request, cid:int, _: str = Depends(_auth_user)):
    name, server_ids = await _category_form_values(request)
    if not name:
        return fail(request, 'Category name is required.', 400)
    async with SessionLocal() as s:
        await _save_category_single(s, name=name, server_ids=server_ids, category_id=cid)
        await s.commit()
    return ok(request, '/admin/categories', 'Category saved')

@router.post('/admin/categories/{cid}/delete')
@router.get('/admin/categories/{cid}/delete')
async def cat_del(request: Request, cid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(ServerCategory,cid)
        if not obj: return fail(request, 'Category not found', 404)
        await s.execute(update(Plan).where(Plan.category_id==cid).values(category_id=None))
        await s.execute(update(Server).where(Server.category_id==cid).values(category_id=None))
        await s.delete(obj); await s.commit()
    return ok(request, '/admin/categories', 'Category deleted')



def _clean_plan_inbound_ids(value) -> list[int]:
    result: list[int] = []
    if isinstance(value, str):
        items = re.split(r'[,\s]+', value.strip())
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    elif value is None:
        items = []
    else:
        items = [value]
    for item in items:
        if isinstance(item, dict):
            item = item.get('id') or item.get('inbound_id') or item.get('inboundId')
        try:
            iid = int(item)
        except Exception:
            continue
        if iid > 0 and iid not in result:
            result.append(iid)
    return result


def _plan_inbound_mode(plan_or_meta) -> str:
    meta = plan_or_meta if isinstance(plan_or_meta, dict) else (getattr(plan_or_meta, 'meta', None) or {})
    return 'manual' if str(meta.get('inbound_mode') or '').strip().lower() == 'manual' else 'automatic'


def _server_available_inbound_ids(server: Server | None) -> list[int]:
    if not server or server.server_type != 'xui':
        return []
    meta = server.meta or {}
    rows = meta.get('inbounds') or meta.get('inbound_ids') or []
    enabled_ids: list[int] = []
    for row in rows:
        if isinstance(row, dict) and row.get('enable') is False:
            continue
        item = row.get('id') if isinstance(row, dict) else row
        try:
            iid = int(item)
        except Exception:
            continue
        if iid > 0 and iid not in enabled_ids:
            enabled_ids.append(iid)
    return enabled_ids


def _resolve_plan_inbound_config(server: Server, inbound_mode: str, inbound_ids) -> tuple[str, list[int], str | None]:
    if server.server_type != 'xui':
        return 'automatic', [], None
    mode = 'manual' if str(inbound_mode or '').strip().lower() == 'manual' else 'automatic'
    available = _server_available_inbound_ids(server)
    if not available:
        return mode, [], 'Selected server has no active inbound. Refresh the server connection first.'
    if mode == 'automatic':
        return mode, available, None
    selected = _clean_plan_inbound_ids(inbound_ids)
    invalid = [iid for iid in selected if iid not in available]
    if invalid:
        return mode, [], 'Invalid or inactive inbound IDs: ' + ', '.join(str(x) for x in invalid)
    if not selected:
        return mode, [], 'Manual mode requires at least one inbound.'
    return mode, selected, None


@router.get('/admin-legacy/plans', response_class=HTMLResponse)
async def plans(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(Plan).order_by(Plan.id.desc()))).scalars().all(); cats=(await s.execute(select(ServerCategory))).scalars().all(); srvs=(await s.execute(select(Server))).scalars().all(); rp=(await s.execute(select(ResellerPackage).order_by(ResellerPackage.id.desc()))).scalars().all()
    catopts=''.join(f'<option value="{c.id}">{e(c.name)}</option>' for c in cats); srvopts=''.join(f'<option value="{srv.id}">{e(srv.name)}</option>' for srv in srvs)
    cat_select_options = '<option value="0">Category is required</option>' + catopts
    srv_select_options = '<option value="0">Server is required</option>' + srvopts
    form='<form method="post" action="/admin/plans/add" class="formgrid"><div><label data-fa="Plan type" data-en="Plan type">Plan type</label><select name="plan_kind"><option value="public">Public Plan</option><option value="reseller">Reseller Plan</option></select></div>'+field('title','Plan title')+field('price_irt','Price','number')+field('volume_gb','Volume GB','number')+field('duration_days','Duration days','number')+field('reseller_validity_days','Reseller validity days','number',365)+f'<div><label>Category</label><select name="category_id" required>{cat_select_options}</select></div><div><label>Server</label><select name="server_id" required>{srv_select_options}</select></div><div class="full"><button class="btn primary">Save</button></div></form>'
    cards=''
    for p in items:
        edit='<form method="post" action="/admin/plans/'+str(p.id)+'/edit" class="formgrid">'+field('title','Plan title','text',p.title)+field('price_irt','Price','number',p.price_irt)+field('volume_gb','Volume GB','number',p.volume_gb)+field('duration_days','Duration days','number',p.duration_days)+f'<div><label>Category</label><select name="category_id" required>{option_rows(cats, p.category_id)}</select></div><div><label>Server</label><select name="server_id" required>{option_rows(srvs, p.server_id)}</select></div><div class="full"><button class="btn primary">Save</button></div></form>'
        status_label = 'Active' if p.is_active else 'Inactive'
        toggle_class = 'danger' if p.is_active else 'success'
        toggle_label = 'Deactivate' if p.is_active else 'Activate'
        cards += f'<div class="card"><h3>📦 {e(p.title)}</h3><div class="value">{money(p.price_irt)}</div><p>{p.volume_gb}GB / {p.duration_days} days</p><p class="muted">Server: {p.server_id} | Status: {status_label}</p><div class="rowactions"><button class="btn" onclick="openModal(\'planEdit{p.id}\')">Edit</button><a data-action="1" class="btn {toggle_class}" href="/admin/toggle/plans/{p.id}">{toggle_label}</a><button class="btn danger" onclick="askDelete(\'/admin/plans/{p.id}/delete\')">Delete</button></div></div>' + modal('planEdit'+str(p.id),'Edit Plan','Edit Plan',edit)
    reseller_form='<form method="post" action="/admin/plans/reseller/add" class="formgrid">'+field('title','Plan title')+field('price_irt','Price','number')+field('volume_gb','Volume GB','number')+field('reseller_validity_days','Validity days','number',365)+f'<div class="full"><label>Server</label><select name="server_id" required>{srv_select_options}</select></div><div class="full"><button class="btn primary">Save reseller plan</button></div></form>'
    reseller=''
    for x in rp:
        rp_edit='<form method="post" action="/admin/plans/reseller/'+str(x.id)+'/edit" class="formgrid">'+field('title','Plan title','text',x.title)+field('price_irt','Price','number',x.price_irt)+field('volume_gb','Volume GB','number',x.volume_gb)+field('reseller_validity_days','Validity days','number',x.reseller_validity_days)+f'<div class="full"><label>Server</label><select name="server_id" required>{option_rows(srvs, x.server_id)}</select></div><div class="full"><button class="btn primary">Save</button></div></form>'
        x_status_label = 'Active' if x.is_active else 'Inactive'
        x_toggle_class = 'danger' if x.is_active else 'success'
        x_toggle_label = 'Deactivate' if x.is_active else 'Activate'
        reseller += f'<div class="card"><h3>🤝 {e(x.title)}</h3><div class="value">{money(x.price_irt)}</div><p>{x.volume_gb}GB / {x.reseller_validity_days} days</p><p class="muted">Reseller Plan | Server: {e(x.server_id or "-")} | Status: {x_status_label}</p><div class="rowactions"><button class="btn" onclick="openModal(\'resellerPlanEdit{x.id}\')">Edit</button><a data-action="1" class="btn {x_toggle_class}" href="/admin/toggle/reseller-plans/{x.id}">{x_toggle_label}</a><button class="btn danger" onclick="askDelete(\'/admin/plans/reseller/{x.id}/delete\')">Delete</button></div></div>' + modal('resellerPlanEdit'+str(x.id),'Edit Reseller Plan','Edit Reseller Plan',rp_edit)
    notice = ''
    if not cats or not srvs:
        notice = '<div class="card" style="margin-bottom:16px"><b>⚠️ To create a plan, add at least one server and one category first.</b></div>'
    return layout('Plans','Plans',notice + '<div class="headrow"><h2>Plans</h2><div class="rowactions"><button class="btn primary" onclick="openModal(\'planAdd\')" data-fa="Add Plan" data-en="Add plan">Add Plan</button></div></div>'+modal('planAdd','Add Plan','Add Plan',form)+'<div class="tabs"><span class="badge">Public Plans</span><span class="badge">Reseller Plans</span></div><div class="gridcards">'+cards+reseller+'</div>','/admin/plans')
@router.post('/admin/plans/add')
async def plan_add(request: Request, plan_kind:str=Form('public'), title:str=Form(...), volume_gb:int=Form(0), duration_days:int=Form(0), reseller_validity_days:int=Form(365), price_irt:int=Form(0), category_id:int=Form(0), server_id:int=Form(0), inbound_mode:str=Form('automatic'), inbound_ids:str=Form(''), _: str = Depends(_auth_user)):
    if not server_id:
        return fail(request, 'Server is required to create a plan.')
    async with SessionLocal() as s:
        srv = await s.get(Server, server_id)
        if not srv:
            return fail(request, 'Selected server was not found.', 404)
        if plan_kind == 'reseller':
            s.add(ResellerPackage(title=title, volume_gb=volume_gb, reseller_validity_days=reseller_validity_days or 365, price_irt=price_irt, server_id=server_id, is_active=True, meta={}))
            await s.commit()
            return ok(request, '/admin/plans', 'Reseller plan added')
        if not category_id:
            return fail(request, 'Category is required for public plans.')
        cat = await s.get(ServerCategory, category_id)
        if not cat:
            return fail(request, 'Selected category was not found.', 404)
        mode, inbs, inbound_error = _resolve_plan_inbound_config(srv, inbound_mode, inbound_ids)
        if inbound_error:
            return fail(request, inbound_error)
        s.add(Plan(title=title,volume_gb=volume_gb,duration_days=duration_days,price_irt=price_irt,category_id=category_id,server_id=server_id,inbound_ids=inbs,is_active=True, meta={'inbound_mode': mode})); await s.commit()
    return ok(request, '/admin/plans', 'Public plan added')
@router.post('/admin/plans/{pid}/edit')
async def plan_edit(request: Request, pid:int, title:str=Form(...), volume_gb:int=Form(0), duration_days:int=Form(0), price_irt:int=Form(0), category_id:int=Form(0), server_id:int=Form(0), inbound_mode:str|None=Form(None), inbound_ids:str=Form(''), _: str = Depends(_auth_user)):
    if not category_id:
        return fail(request, 'Category is required to edit the plan.')
    if not server_id:
        return fail(request, 'Server is required to edit the plan.')
    async with SessionLocal() as s:
        obj=await s.get(Plan,pid)
        cat = await s.get(ServerCategory, category_id)
        srv=await s.get(Server,server_id)
        if not obj:
            return fail(request, 'Plan not found', 404)
        if not cat:
            return fail(request, 'Selected category was not found.', 404)
        if not srv:
            return fail(request, 'Selected server was not found.', 404)
        requested_mode = inbound_mode if inbound_mode is not None else (_plan_inbound_mode(obj) if obj.server_id == server_id else 'automatic')
        requested_ids = inbound_ids if inbound_mode is not None else obj.inbound_ids
        mode, inbs, inbound_error = _resolve_plan_inbound_config(srv, requested_mode, requested_ids)
        if inbound_error:
            return fail(request, inbound_error)
        obj.title=title; obj.volume_gb=volume_gb; obj.duration_days=duration_days; obj.price_irt=price_irt; obj.category_id=category_id; obj.server_id=server_id; obj.inbound_ids=inbs
        meta = dict(obj.meta or {})
        meta['inbound_mode'] = mode
        obj.meta = meta
        await s.commit()
    return ok(request, '/admin/plans', 'Plan updated')
@router.post('/admin/plans/{pid}/delete')
@router.get('/admin/plans/{pid}/delete')
async def plan_del(request: Request, pid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(Plan,pid)
        if not obj: return fail(request, 'Plan not found', 404)
        await s.execute(update(Order).where(Order.plan_id==pid).values(plan_id=None))
        await s.execute(update(ClientService).where(ClientService.plan_id==pid).values(plan_id=None))
        await s.delete(obj); await s.commit()
    return ok(request, '/admin/plans', 'Plan deleted')


@router.post('/admin/plans/reseller/add')
async def reseller_plan_add(request: Request, title:str=Form(...), volume_gb:int=Form(0), reseller_validity_days:int=Form(365), price_irt:int=Form(0), server_id:int=Form(0), _: str = Depends(_auth_user)):
    if not server_id:
        return fail(request, 'Server is required to create reseller plan.')
    async with SessionLocal() as s:
        srv = await s.get(Server, server_id)
        if not srv:
            return fail(request, 'Selected server was not found.', 404)
        s.add(ResellerPackage(title=title, volume_gb=volume_gb, reseller_validity_days=reseller_validity_days, price_irt=price_irt, server_id=server_id, is_active=True, meta={}))
        await s.commit()
    return ok(request, '/admin/plans', 'Reseller plan added')

@router.post('/admin/plans/reseller/{pid}/edit')
async def reseller_plan_edit(request: Request, pid:int, title:str=Form(...), volume_gb:int=Form(0), reseller_validity_days:int=Form(365), price_irt:int=Form(0), server_id:int=Form(0), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(ResellerPackage,pid)
        if not obj:
            return fail(request, 'Reseller plan not found', 404)
        try:
            obj.title=title
            obj.volume_gb=volume_gb
            obj.reseller_validity_days=reseller_validity_days
            obj.price_irt=price_irt
            if not server_id:
                return fail(request, 'Server is required to edit reseller plan.')
            srv = await s.get(Server, server_id)
            if not srv:
                return fail(request, 'Selected server was not found.', 404)
            obj.server_id=server_id
            obj.meta={}
            await s.commit()
        except Exception:
            await s.rollback()
            logger.exception('Reseller plan update failed')
            return fail(request, 'Reseller plan update failed. Check server logs.', 500)
    return ok(request, '/admin/plans', 'Reseller plan updated')

@router.post('/admin/plans/reseller/{pid}/delete')
@router.get('/admin/plans/reseller/{pid}/delete')
async def reseller_plan_del(request: Request, pid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(ResellerPackage,pid)
        if not obj:
            return fail(request, 'Reseller plan not found', 404)
        try:
            await s.execute(update(ResellerTopupRequest).where(ResellerTopupRequest.package_id==pid).values(package_id=None))
            await s.delete(obj)
            await s.commit()
        except Exception:
            await s.rollback()
            logger.exception('Reseller plan delete failed')
            return fail(request, 'Reseller plan delete failed. Check server logs.', 500)
    return ok(request, '/admin/plans', 'Reseller plan deleted')


def simple_section(route,title_fa,title_en,button_fa,modal_id,form,cards_html):
    return layout(
        title_fa,
        title_en,
        f'<div class="headrow"><h2>{title_fa}</h2><button class="btn primary" onclick="openModal(\'{modal_id}\')">+ {button_fa}</button></div>'
        + modal(modal_id, button_fa, title_en, form)
        + '<div class="gridcards">' + (cards_html or '<div class="card muted">No items found.</div>') + '</div>',
        route,
    )

@router.get('/admin-legacy/payments', response_class=HTMLResponse)
async def payments(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(PaymentCard).order_by(PaymentCard.id.desc()))).scalars().all()
        srvs=(await s.execute(select(Server).where(Server.is_active == True).order_by(Server.id.desc()))).scalars().all()
    server_options=[('0','Select server')] + [(str(s.id), f'{s.name} ({s.server_type})') for s in srvs]
    form='<form method="post" action="/admin/payments/add" class="formgrid">'+field('card_number','Card / account number')+field('owner_name','Owner name')+select_field('show_for','Where to show',[('public','Public'),('reseller','Reseller')],'public')+select_field('server_id','Server for public payment',server_options,'0','full')+'<div class="full"><button class="btn primary">Save</button></div></form>'
    cards=''
    for p in items:
        edit='<form method="post" action="/admin/payments/'+str(p.id)+'/edit" class="formgrid">'+field('card_number','Card / account number','text',p.card_number)+field('owner_name','Owner name','text',p.owner_name)+select_field('show_for','Where to show',[('public','Public'),('reseller','Reseller')],'reseller' if p.server_type=='reseller' else 'public')+select_field('server_id','Server for public payment',server_options,str(p.server_id or 0),'full')+'<div class="full"><button class="btn primary">Save</button></div></form>'
        show_text = 'Reseller' if p.server_type == 'reseller' else 'Public'
        cards+=f'<div class="card"><h3>💳 {e(p.owner_name)}</h3><p class="muted">{e(show_text)} • Server #{p.server_id or "-"}</p><p>{e(p.card_number)}</p><div class="rowactions"><button class="btn" onclick="openModal(\'payEdit{p.id}\')">Edit</button><button class="btn danger" onclick="askDelete(\'/admin/payments/{p.id}/delete\')">Delete</button></div></div>'+modal('payEdit'+str(p.id),'Edit Payment','Edit Payment',edit)
    return simple_section('/admin/payments','Payments','Payments','Add Account','payAdd',form,cards)
@router.post('/admin/payments/add')
async def pay_add(request: Request, card_number:str=Form(...), owner_name:str=Form(...), show_for:str=Form('public'), server_id:int=Form(0), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        if show_for == 'reseller':
            server_type='reseller'; server_id = 0
        else:
            if not server_id:
                return fail(request,'Please select the server for public payment.',400)
            srv=await s.get(Server,server_id)
            if not srv: return fail(request,'Selected server was not found.',404)
            server_type=srv.server_type
        s.add(PaymentCard(card_number=card_number,owner_name=owner_name,server_type=server_type,server_id=server_id or None,is_active=True)); await s.commit()
    return ok(request, '/admin/payments', 'Payment account added')
@router.post('/admin/payments/{pid}/edit')
async def pay_edit(request: Request, pid:int, card_number:str=Form(...), owner_name:str=Form(...), show_for:str=Form('public'), server_id:int=Form(0), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(PaymentCard,pid)
        if obj:
            if show_for == 'reseller':
                server_type='reseller'; server_id = 0
            else:
                if not server_id:
                    return fail(request,'Please select the server for public payment.',400)
                srv=await s.get(Server,server_id)
                if not srv: return fail(request,'Selected server was not found.',404)
                server_type=srv.server_type
            obj.card_number=card_number; obj.owner_name=owner_name; obj.server_type=server_type; obj.server_id=server_id or None; await s.commit()
    return ok(request, '/admin/payments', 'Payment account updated')
@router.post('/admin/payments/{pid}/delete')
@router.get('/admin/payments/{pid}/delete')
async def pay_del(request: Request, pid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(PaymentCard,pid)
        if obj: await s.delete(obj); await s.commit()
    return ok(request, '/admin/payments', 'Done')

@router.get('/admin-legacy/discounts', response_class=HTMLResponse)
async def discounts(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(DiscountCode).order_by(DiscountCode.id.desc()))).scalars().all()
        srvs=(await s.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
    form='<form method="post" action="/admin/discounts/add" class="formgrid">'+field('code','Code')+'<div><label>Type</label><select name="discount_type"><option value="percent">Percent</option><option value="fixed">Fixed</option></select></div>'+field('value','Value','number')+field('max_uses','Max uses','number')+field('per_user_limit','Per user limit','number')+f'<div class="full"><label>Allowed servers</label><div class="checkbox-grid">{_server_options_html(srvs, field_name="allowed_server_ids")}</div><small class="muted">خالی باشد یعنی برای همه سرورها فعال است.</small></div><div class="full"><button class="btn primary">Save</button></div></form>'
    cards=''
    srv_by_id={s.id:s for s in srvs}
    for d in items:
        selected=_discount_allowed_server_ids(d)
        names=[((srv_by_id[sid].meta or {}).get('display_name') or srv_by_id[sid].name) for sid in selected if sid in srv_by_id]
        edit='<form method="post" action="/admin/discounts/'+str(d.id)+'/edit" class="formgrid">'+field('code','Code','text',d.code)+'<div><label>Type</label><select name="discount_type"><option value="percent">Percent</option><option value="fixed">Fixed</option></select></div>'+field('value','Value','number',d.value)+field('max_uses','Max uses','number',d.max_uses)+field('per_user_limit','Per user limit','number',d.per_user_limit)+f'<div class="full"><label>Allowed servers</label><div class="checkbox-grid">{_server_options_html(srvs, selected, field_name="allowed_server_ids")}</div><small class="muted">خالی باشد یعنی برای همه سرورها فعال است.</small></div><div class="full"><button class="btn primary">Save</button></div></form>'
        scope=', '.join(names) if names else 'All servers'
        cards+=f'<div class="card"><h3>🎟 {e(d.code)}</h3><p>{e(d.discount_type)}: {d.value}</p><p class="muted">used {d.used_count}/{d.max_uses} | per user {d.per_user_limit}</p><p class="muted">Allowed: {e(scope)}</p><div class="rowactions"><button class="btn" onclick="openModal(\'discEdit{d.id}\')">Edit</button><button class="btn danger" onclick="askDelete(\'/admin/discounts/{d.id}/delete\')">Delete</button></div></div>'+modal('discEdit'+str(d.id),'Edit Discount','Edit Discount',edit)
    return simple_section('/admin/discounts','Discount Codes','Discount Codes','Add Discount Code','discAdd',form,cards)

@router.post('/admin/discounts/add')
async def disc_add(request: Request, _: str = Depends(_auth_user)):
    code, discount_type, value, max_uses, per_user_limit, server_ids = await _discount_form_values(request)
    if not code: return fail(request, 'Code required', 400)
    async with SessionLocal() as s:
        s.add(DiscountCode(code=code,discount_type=discount_type,value=value,max_uses=max_uses,per_user_limit=per_user_limit,allowed_server_ids=server_ids,is_active=True)); await s.commit()
    return ok(request, '/admin/discounts', 'Done')

@router.post('/admin/discounts/{did}/edit')
async def disc_edit(request: Request, did:int, _: str = Depends(_auth_user)):
    code, discount_type, value, max_uses, per_user_limit, server_ids = await _discount_form_values(request)
    async with SessionLocal() as s:
        obj=await s.get(DiscountCode,did)
        if obj:
            obj.code=code; obj.discount_type=discount_type; obj.value=value; obj.max_uses=max_uses; obj.per_user_limit=per_user_limit; obj.allowed_server_ids=server_ids
            await s.commit()
    return ok(request, '/admin/discounts', 'Done')
@router.post('/admin/discounts/{did}/delete')
@router.get('/admin/discounts/{did}/delete')
async def disc_del(request: Request, did:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(DiscountCode,did)
        if obj:
            await s.execute(delete(DiscountUsage).where(DiscountUsage.discount_id==did))
            await s.delete(obj); await s.commit()
    return ok(request, '/admin/discounts', 'Discount code deleted')

@router.get('/admin-legacy/resellers', response_class=HTMLResponse)
async def resellers(request: Request, _: str = Depends(_auth_user)):
    cards=''
    async with SessionLocal() as s:
        rows=(await s.execute(select(ResellerAccount,User).join(User,User.id==ResellerAccount.user_id).order_by(ResellerAccount.id.desc()))).all()
        for r,u in rows:
            await reconcile_reseller_accounting(s, r)
            remain=remaining_bytes(r)
            days='-' if not r.expires_at else max(0,(r.expires_at-datetime.utcnow()).days)
            expiry_value = r.expires_at.date().isoformat() if r.expires_at else ''
            edit='<form method="post" action="/admin/resellers/'+str(r.id)+'/edit" class="formgrid">'+field('total_gb','Total GB','number',int((r.total_bytes or 0)/1024**3))+field('expires_at','Expiry date','date',expiry_value)+'<div class="full muted">Used and Reserved are calculated automatically. Total GB is the reseller current sellable volume.</div><div class="full"><button class="btn primary">Save</button></div></form>'
            cards+=f"""<div class="card"><h3>🤝 {e(u.full_name or u.username or u.telegram_id)}</h3><p class="muted">ID: {u.telegram_id}</p><div class="kvs"><div class="kv"><span>Total / sellable</span><b>{gb(r.total_bytes)}</b></div><div class="kv"><span>Used</span><b>{gb(r.used_bytes)}</b></div><div class="kv"><span>Reserved / remaining</span><b>{gb(r.reserved_bytes)} / {gb(remain)}</b></div><div class="kv"><span>Remaining days</span><b>{days}</b></div></div><a class="btn success" href="/admin/resellers/{r.id}/refresh">Refresh Stats</a><button class="btn" onclick="openModal('resEdit{r.id}')">Edit</button><button class="btn danger" onclick="askDelete('/admin/resellers/{r.id}/delete')">Delete</button></div>"""+modal('resEdit'+str(r.id),'Edit resellers','Edit Reseller',edit)
        await s.commit()
    add_form='<form method="post" action="/admin/resellers/add" class="formgrid">'+field('telegram_id','Telegram numeric ID','number')+field('full_name','Full name','text')+field('username','Telegram username','text')+field('total_gb','Total GB','number',0)+field('days','Remaining days','number',30)+'<div class="full"><button class="btn primary">Save</button></div></form>'
    return layout('Resellers','Resellers','<div class="headrow"><h2>Resellers</h2><button class="btn primary" onclick="openModal(\'resAdd\')">+ Add Reseller</button></div>'+modal('resAdd','Add Reseller','Add Reseller',add_form)+'<div class="gridcards">'+cards+'</div>','/admin/resellers')
@router.post('/admin/resellers/add')
async def reseller_add(request: Request, telegram_id:int=Form(...), full_name:str=Form(''), username:str=Form(''), total_gb:int=Form(0), days:int=Form(30), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        user=(await s.execute(select(User).where(User.telegram_id==telegram_id))).scalar_one_or_none()
        if not user:
            user=User(telegram_id=telegram_id, full_name=full_name or None, username=username.replace('@','') or None)
            s.add(user); await s.flush()
        elif full_name or username:
            if full_name: user.full_name=full_name
            if username: user.username=username.replace('@','')
        existing=(await s.execute(select(ResellerAccount).where(ResellerAccount.user_id==user.id))).scalar_one_or_none()
        if existing: return fail(request, 'This user is already a reseller.')
        s.add(ResellerAccount(user_id=user.id,total_bytes=total_gb*1024**3,used_bytes=0,reserved_bytes=0,expires_at=datetime.utcnow()+timedelta(days=days) if days else None,is_active=True))
        await s.commit()
    return ok(request, '/admin/resellers', 'Reseller added')

@router.post('/admin/resellers/{rid}/delete')
@router.get('/admin/resellers/{rid}/delete')
async def reseller_delete(request: Request, rid:int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(ResellerAccount,rid)
        if not obj: return fail(request, 'Reseller not found', 404)
        active=await s.scalar(select(func.count(ClientService.id)).where(ClientService.reseller_id==rid)) or 0
        if active:
            await s.execute(update(ClientService).where(ClientService.reseller_id==rid).values(reseller_id=None))
        await s.execute(delete(ResellerAccessRequest).where(ResellerAccessRequest.user_id==obj.user_id))
        await s.delete(obj); await s.commit()
    return ok(request, '/admin/resellers', 'Reseller deleted')

@router.post('/admin/resellers/{rid}/edit')
async def reseller_edit(request: Request, rid:int, total_gb:int=Form(0), expires_at:str=Form(''), days:int=Form(0), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        obj=await s.get(ResellerAccount,rid)
        if obj:
            obj.total_bytes=max(0, int(total_gb or 0))*1024**3
            # Used and Reserved are accounting fields; never edit them manually from the website.
            # They are recalculated/updated from reseller services and traffic sync.
            if expires_at:
                try:
                    obj.expires_at = datetime.strptime(expires_at.strip(), '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=0)
                except ValueError:
                    return fail(request, 'Invalid expiry date format. Use YYYY-MM-DD.')
            elif days:
                obj.expires_at=datetime.utcnow()+timedelta(days=days)
            else:
                obj.expires_at=None
            await reconcile_reseller_accounting(s, obj)
            await s.commit()
    return ok(request, '/admin/resellers', 'Reseller updated')


# -----------------------------------------------------------------------------
# Website-only backup & restore helpers
# -----------------------------------------------------------------------------

def _backup_models():
    return [
        ('users', User), ('settings', Setting), ('servers', Server), ('categories', ServerCategory),
        ('payment_cards', PaymentCard), ('plans', Plan), ('discount_codes', DiscountCode),
        ('discount_usages', DiscountUsage), ('reseller_accounts', ResellerAccount),
        ('reseller_access_requests', ResellerAccessRequest), ('reseller_packages', ResellerPackage),
        ('reseller_build_configs', ResellerBuildConfig), ('reseller_topup_requests', ResellerTopupRequest),
        ('services', ClientService), ('orders', Order), ('wallet_transactions', WalletTransaction),
        ('tickets', Ticket), ('ticket_messages', TicketMessage), ('test_account_usages', TestAccountUsage), ('openvpn_profiles', OpenVPNProfile),
    ]


def _restore_delete_order():
    return [
        TicketMessage, Ticket, WalletTransaction, Order,
        ClientService, TestAccountUsage, DiscountUsage, ResellerTopupRequest, ResellerBuildConfig,
        ResellerPackage, ResellerAccessRequest, ResellerAccount, DiscountCode, Plan, PaymentCard,
        ServerCategory, Server, Setting, User,
    ]


def _restore_insert_order():
    return [
        ('users', User), ('settings', Setting), ('servers', Server), ('categories', ServerCategory),
        ('payment_cards', PaymentCard), ('plans', Plan), ('discount_codes', DiscountCode),
        ('discount_usages', DiscountUsage), ('reseller_accounts', ResellerAccount),
        ('reseller_access_requests', ResellerAccessRequest), ('reseller_packages', ResellerPackage),
        ('reseller_build_configs', ResellerBuildConfig), ('reseller_topup_requests', ResellerTopupRequest),
        ('services', ClientService), ('orders', Order), ('wallet_transactions', WalletTransaction),
        ('tickets', Ticket), ('ticket_messages', TicketMessage), ('test_account_usages', TestAccountUsage), ('openvpn_profiles', OpenVPNProfile),
    ]


def _parse_backup_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def _payment_label(value: Any) -> str:
    pm = str(value or '').lower()
    if 'wallet' in pm or 'balance' in pm:
        return 'Wallet'
    if any(x in pm for x in ['card', 'cart', 'receipt', 'manual', 'bank']):
        return 'Card to Card'
    if any(x in pm for x in ['crypto', 'nowpayments', 'trx']):
        return 'Crypto'
    if 'reseller' in pm:
        return 'Reseller Payment'
    return str(value or '-')


async def _settings_map() -> dict[str, str]:
    async with SessionLocal() as s:
        rows = (await s.execute(select(Setting))).scalars().all()
    return {x.key: x.value for x in rows}


async def _save_settings_map(values: dict[str, Any]) -> None:
    async with SessionLocal() as s:
        for key, value in values.items():
            await s.merge(Setting(key=key, value=str(value if value is not None else '')))
        await s.commit()


async def _export_backup_payload() -> dict[str, Any]:
    async with SessionLocal() as session:
        async def rows(model):
            result = (await session.execute(select(model))).scalars().all()
            out = []
            for obj in result:
                item = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
                for k, v in list(item.items()):
                    if hasattr(v, 'isoformat'):
                        item[k] = v.isoformat()
                out.append(item)
            return out
        data = {'meta': {'app': 'D BOT', 'created_at': datetime.utcnow().isoformat(), 'format': 3}}
        for key, model in _backup_models():
            data[key] = await rows(model)
        sig = _sign_backup(data)
        if sig:
            data['meta']['signature'] = sig
        return data


async def _write_backup_file() -> str:
    data = await _export_backup_payload()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8')
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return tmp.name


async def _telegram_token(settings_map: dict[str, str] | None = None, supplied: str = '') -> str:
    if supplied.strip():
        return supplied.strip()
    settings_map = settings_map or await _settings_map()
    return (settings_map.get('backup_bot_token') or settings.BOT_TOKEN or '').strip()


def _default_backup_chat_id() -> str:
    try:
        owner_ids = settings.owner_ids
        if owner_ids:
            return str(owner_ids[0])
    except Exception:
        pass
    return ''


def _normalize_telegram_target(destination: str, value: str) -> str:
    raw = (value or '').strip()
    if destination == 'bot' and not raw:
        return _default_backup_chat_id()
    if raw.startswith('https://t.me/') or raw.startswith('http://t.me/'):
        slug = raw.rstrip('/').split('/')[-1].strip()
        return ('@' + slug) if slug and not slug.startswith('+') else raw
    return raw


async def _telegram_test(token: str, chat_id: str, destination: str) -> dict[str, Any]:
    import httpx
    if not token:
        return {'ok': False, 'admin_ok': False, 'message': 'Bot token is empty'}
    chat_id = _normalize_telegram_target(destination, chat_id)
    if not chat_id and destination != 'bot':
        return {'ok': False, 'admin_ok': False, 'message': 'Chat ID / username is empty'}
    base = f'https://api.telegram.org/bot{token}'
    async with httpx.AsyncClient(timeout=20) as client:
        me = (await client.get(base + '/getMe')).json()
        if not me.get('ok'):
            return {'ok': False, 'admin_ok': False, 'message': 'Telegram bot token is invalid'}
        bot_id = me['result']['id']
        if destination == 'bot' and not chat_id:
            return {'ok': True, 'admin_ok': True, 'message': 'Backup bot token tested successfully'}
        chat = (await client.get(base + '/getChat', params={'chat_id': chat_id})).json()
        if not chat.get('ok'):
            return {'ok': False, 'admin_ok': False, 'message': 'Cannot access target chat/channel/group'}
        admin_ok = True
        if destination in {'channel', 'group'}:
            member = (await client.get(base + '/getChatMember', params={'chat_id': chat_id, 'user_id': bot_id})).json()
            status = (member.get('result') or {}).get('status') if member.get('ok') else None
            admin_ok = status in {'administrator', 'creator'}
            if not admin_ok:
                return {'ok': False, 'admin_ok': False, 'message': 'Bot is not admin in this channel/group'}
        msg = (await client.post(base + '/sendMessage', data={'chat_id': chat_id, 'text': '✅ D BOT backup destination test successful.'})).json()
        if not msg.get('ok'):
            return {'ok': False, 'admin_ok': admin_ok, 'message': 'Test message could not be sent'}
        return {'ok': True, 'admin_ok': admin_ok, 'message': 'Backup destination tested successfully'}


async def _telegram_send_backup(token: str, chat_id: str, path: str, destination: str = 'channel') -> dict[str, Any]:
    import httpx
    chat_id = _normalize_telegram_target(destination, chat_id)
    if not token or not chat_id:
        return {'ok': False, 'message': 'Backup destination is not configured'}
    base = f'https://api.telegram.org/bot{token}'
    async with httpx.AsyncClient(timeout=60) as client:
        with open(path, 'rb') as fh:
            res = await client.post(base + '/sendDocument', data={'chat_id': chat_id, 'caption': '📦 D BOT website backup'}, files={'document': ('dbot_backup.json', fh, 'application/json')})
        data = res.json()
    return {'ok': bool(data.get('ok')), 'message': 'Backup file sent successfully' if data.get('ok') else str(data)[:1000]}


async def _restore_backup_payload(data: dict[str, Any]) -> dict[str, int]:
    _validate_backup_payload(data)
    restored: dict[str, int] = {}
    async with SessionLocal() as session:
        async with session.begin():
            for model in _restore_delete_order():
                await session.execute(delete(model))
            for key, model in _restore_insert_order():
                colnames = set(model.__table__.columns.keys())
                count = 0
                for item in data.get(key, []) or []:
                    clean = {}
                    for k, v in dict(item).items():
                        if k not in colnames:
                            continue
                        col = model.__table__.columns[k]
                        if 'DateTime' in type(col.type).__name__:
                            v = _parse_backup_dt(v)
                        clean[k] = v
                    session.add(model(**clean))
                    count += 1
                restored[key] = count
                await session.flush()
            for _, model in _backup_models():
                if 'id' in model.__table__.columns.keys():
                    table = model.__tablename__
                    try:
                        await session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1), true)"))
                    except Exception:
                        pass
    return restored



async def _restart_site_and_bot_via_docker(reason: str = '') -> tuple[bool, str]:
    """Best-effort restart for the Compose api/bot services from inside the panel.

    This uses the Docker Engine socket when it is mounted into the API container.
    It avoids requiring docker CLI inside the image. If the socket is not mounted,
    the panel still stores a restart request status so admins can restart manually.
    """
    if not settings.DBOT_ALLOW_DOCKER_RESTART:
        return False, 'Docker restart from web panel is disabled. Run docker compose restart api bot manually.'
    sock = '/var/run/docker.sock'
    if not os.path.exists(sock):
        return False, 'Docker socket is not mounted. Run docker compose restart api bot manually.'
    try:
        import httpx
        transport = httpx.AsyncHTTPTransport(uds=sock)
        async with httpx.AsyncClient(transport=transport, base_url='http://docker', timeout=12) as client:
            current_name = os.uname().nodename
            cur = (await client.get(f'/containers/{current_name}/json')).json()
            labels = ((cur.get('Config') or {}).get('Labels') or {})
            project = labels.get('com.docker.compose.project')
            if not project:
                return False, 'Could not detect Docker Compose project label from current container.'
            restarted: list[str] = []
            for service in ('bot', 'api'):
                filters = json.dumps({'label': [f'com.docker.compose.project={project}', f'com.docker.compose.service={service}']})
                items = (await client.get('/containers/json', params={'all': 'true', 'filters': filters})).json()
                for item in items:
                    cid = item.get('Id')
                    if not cid:
                        continue
                    await client.post(f'/containers/{cid}/restart', params={'t': 2})
                    restarted.append(service)
            if not restarted:
                return False, f'No api/bot containers found for project {project}.'
            return True, 'Restarted services: ' + ', '.join(restarted)
    except Exception:
        logger.exception('Docker restart failed')
        return False, 'Restart failed. Run docker compose restart api bot manually.'


def _schedule_site_and_bot_restart(reason: str = '') -> None:
    async def runner():
        await asyncio.sleep(1.5)
        ok_restart, msg = await _restart_site_and_bot_via_docker(reason)
        try:
            await _save_settings_map({
                'web_restart_status': 'ok' if ok_restart else 'manual_required',
                'web_restart_message': msg,
                'web_restart_requested_at': datetime.utcnow().isoformat(),
            })
        except Exception:
            pass
    try:
        asyncio.create_task(runner())
    except Exception:
        pass

async def _apply_ssl_for_domain(domain: str) -> tuple[bool, str]:
    domain = domain.strip().replace('https://','').replace('http://','').strip('/')
    if not domain:
        return False, 'Domain is empty'
    if not re.match(r'^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$', domain):
        return False, 'Invalid domain'
    try:
        proc = subprocess.run(['bash', 'scripts/setup_web_ssl.sh', domain], capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            logger.warning('SSL apply failed for %s: stdout=%s stderr=%s', domain, (proc.stdout or '')[-2000:], (proc.stderr or '')[-2000:])
            return False, 'SSL command failed. Check server logs.'
        return True, 'SSL applied successfully'
    except Exception:
        logger.exception('SSL apply crashed for %s', domain)
        return False, 'SSL command failed. Check server logs.'

@router.get('/admin-legacy/backup', response_class=HTMLResponse)
async def backup(request: Request, _: str = Depends(_auth_user)):
    form='<form method="post" action="/admin/backup/save" class="formgrid">'+field('channel','Backup channel','text','@dbot_backup_channel')+field('time','Backup time','time','03:00')+'<div><label>Database</label><select name="db"><option value="yes">Yes</option></select></div><div><label>Files</label><select name="files"><option value="yes">Yes</option></select></div><div class="full"><button class="btn primary">Save</button></div></form>'
    cards='<div class="card"><h3>🧰 Backup Settings</h3><p class="muted">Channel, send time, database and bot files</p><button class="btn primary" onclick="openModal(\'backupEdit\')">Backup Settings</button><button class="btn success" onclick="askDelete(\'/admin/backup/run\')">Run Manual Backup</button></div>'
    return layout('Backup','Backup',modal('backupEdit','Backup Settings','Backup Settings',form)+'<div class="gridcards">'+cards+'</div>','/admin/backup')
@router.post('/admin/backup/save')
async def backup_save(
    request: Request,
    destination: str = Form('channel'),
    bot_token: str = Form(''),
    chat_id: str = Form(''),
    bot_username: str = Form(''),
    time: str = Form('03:00'),
    include_database: str = Form('1'),
    include_files: str = Form('1'),
    _: str = Depends(_auth_user),
):
    destination = destination if destination in {'channel', 'group', 'bot'} else 'channel'
    await _save_settings_map({
        'backup_destination': destination,
        'backup_bot_token': bot_token.strip(),
        'backup_chat_id': _normalize_telegram_target(destination, chat_id.strip()),
        'backup_bot_username': bot_username.strip(),
        'backup_time': time or '03:00',
        'backup_include_database': '1' if include_database == '1' else '0',
        'backup_include_files': '1' if include_files == '1' else '0',
    })
    return ok(request, '/admin/backup', 'Backup settings saved')


@router.post('/admin/backup/test')
async def backup_test(
    request: Request,
    destination: str = Form('channel'),
    bot_token: str = Form(''),
    chat_id: str = Form(''),
    bot_username: str = Form(''),
    time: str = Form('03:00'),
    include_database: str = Form('1'),
    include_files: str = Form('1'),
    _: str = Depends(_auth_user),
):
    destination = destination if destination in {'channel', 'group', 'bot'} else 'channel'
    token = await _telegram_token(supplied=bot_token)
    normalized_chat_id = _normalize_telegram_target(destination, chat_id.strip())
    result = await _telegram_test(token, normalized_chat_id, destination)
    await _save_settings_map({
        'backup_destination': destination,
        'backup_bot_token': bot_token.strip(),
        'backup_chat_id': normalized_chat_id,
        'backup_bot_username': bot_username.strip(),
        'backup_time': time or '03:00',
        'backup_include_database': '1' if include_database == '1' else '0',
        'backup_include_files': '1' if include_files == '1' else '0',
        'backup_last_test_status': 'ok' if result.get('ok') else 'error',
        'backup_last_test_message': result.get('message', ''),
        'backup_admin_ok': '1' if result.get('admin_ok') else '0',
    })
    status = 200 if result.get('ok') else 400
    return JSONResponse({'ok': bool(result.get('ok')), 'message': result.get('message'), 'admin_ok': result.get('admin_ok')}, status_code=status)


@router.post('/admin/backup/run')
@router.get('/admin/backup/run')
async def backup_run(request: Request, _: str = Depends(_auth_user)):
    m = await _settings_map()
    destination = (m.get('backup_destination') or 'channel').strip()
    chat_id = _normalize_telegram_target(destination, (m.get('backup_chat_id') or m.get('backup_channel') or '').strip())
    token = await _telegram_token(m)
    path = await _write_backup_file()
    try:
        result = await _telegram_send_backup(token, chat_id, path, destination)
        await _save_settings_map({
            'backup_last_backup_status': 'ok' if result.get('ok') else 'error',
            'backup_last_backup_message': result.get('message', ''),
            'backup_last_backup_at': datetime.utcnow().isoformat(),
        })
        if not result.get('ok'):
            return fail(request, result.get('message', 'Backup could not be sent'))
        return ok(request, '/admin/backup', 'Manual backup created and sent')
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


@router.get('/admin/backup/download')
async def backup_download(_: str = Depends(_auth_user)):
    path = await _write_backup_file()
    return FileResponse(path, media_type='application/json', filename='dbot_backup.json')


@router.post('/admin/backup/restore')
async def backup_restore(request: Request, file: UploadFile = File(...), _: str = Depends(_auth_user)):
    if not (file.filename or '').lower().endswith('.json'):
        return fail(request, 'Only JSON backup files are supported')
    raw = await file.read(max(1024, int(settings.BACKUP_MAX_UPLOAD_BYTES or 5_242_880)) + 1)
    if len(raw) > int(settings.BACKUP_MAX_UPLOAD_BYTES or 5_242_880):
        return fail(request, 'Backup file is too large')
    try:
        data = json.loads(raw.decode('utf-8'))
        restored = await _restore_backup_payload(data)
    except Exception:
        logger.exception('Backup restore rejected or failed')
        return fail(request, 'Restore failed. The backup file is invalid or not trusted.', 400)
    total = sum(restored.values())
    await _save_settings_map({'backup_last_restore_at': datetime.utcnow().isoformat(), 'backup_last_restore_count': str(total)})
    return ok(request, '/admin/backup', f'Restore completed. {total} rows synchronized.')


@router.get('/admin/api/v2/backup/settings')
async def api_v2_backup_settings(_: str = Depends(_auth_user)):
    m = await _settings_map()
    settings_payload = {
        'backup_destination': m.get('backup_destination', 'channel'),
        'backup_bot_token': '',
        'backup_chat_id': m.get('backup_chat_id', m.get('backup_channel', '')),
        'backup_bot_username': m.get('backup_bot_username', ''),
        'backup_time': m.get('backup_time', '03:00'),
        'backup_include_database': m.get('backup_include_database', '1'),
        'backup_include_files': m.get('backup_include_files', '1'),
    }
    return {'ok': True, 'settings': settings_payload, 'status': {
        'configured': bool(settings_payload['backup_chat_id'] or settings_payload['backup_bot_token']),
        'last_test_status': m.get('backup_last_test_status', ''),
        'last_test_message': m.get('backup_last_test_message', ''),
        'admin_ok': m.get('backup_admin_ok') == '1',
        'last_backup_status': m.get('backup_last_backup_status', ''),
        'last_backup_message': m.get('backup_last_backup_message', ''),
        'last_backup_at': m.get('backup_last_backup_at', ''),
    }}


@router.get('/admin/api/v2/test-account')
async def api_v2_test_account(_: str = Depends(_auth_user)):
    m = await _settings_map()
    async with SessionLocal() as s:
        servers = (await s.execute(select(Server).where(Server.is_active == True).order_by(Server.id.desc()))).scalars().all()
        usage_count = await s.scalar(select(func.count(TestAccountUsage.id))) or 0
        usage_rows = (await s.execute(
            select(TestAccountUsage, User)
            .join(User, User.id == TestAccountUsage.user_id, isouter=True)
            .order_by(TestAccountUsage.id.desc())
            .limit(25)
        )).all()
    selected_id = m.get('test_account_server_id', '')
    return {'ok': True, 'settings': {
        'enabled': m.get('test_account_enabled', '1'),
        'button_visible': m.get('test_account_button_visible', '1'),
        'server_id': selected_id,
        'inbound_ids': m.get('test_account_inbound_ids', ''),
        'volume_gb': m.get('test_account_volume_gb', '1'),
        'duration_days': m.get('test_account_duration_days', '1'),
    }, 'usage_count': int(usage_count), 'usage_items': [
        {'id': u.id, 'telegram_id': u.telegram_id, 'created_at': dt_iso(u.created_at), 'service_id': u.service_id, 'user': user_json(user) if user else None}
        for u, user in usage_rows
    ], 'servers': [srv_json(x) for x in servers]}


@router.post('/admin/test-account/save')
async def test_account_save(
    request: Request,
    enabled: str = Form('1'),
    button_visible: str = Form('1'),
    server_id: int = Form(0),
    inbound_ids: str = Form(''),
    volume_gb: str = Form('1'),
    duration_days: int = Form(1),
    _: str = Depends(_auth_user),
):
    if not server_id:
        return fail(request, 'Server is required for test account.')
    try:
        volume = float(str(volume_gb).replace(',', '.'))
    except Exception:
        return fail(request, 'Volume GB is not valid.')
    if volume <= 0:
        return fail(request, 'Volume GB must be greater than zero.')
    if duration_days <= 0:
        return fail(request, 'Duration days must be greater than zero.')
    async with SessionLocal() as s:
        srv = await s.get(Server, server_id)
        if not srv or not srv.is_active:
            return fail(request, 'Selected server was not found or inactive.', 404)
        parsed = []
        for chunk in re.split(r'[,\s]+', inbound_ids.strip()):
            if chunk.isdigit():
                parsed.append(int(chunk))
        if not parsed:
            parsed = [int(x.get('id') if isinstance(x, dict) else x) for x in ((srv.meta or {}).get('inbound_ids') or []) if str(x.get('id') if isinstance(x, dict) else x).isdigit()]
        if not parsed:
            return fail(request, 'Selected server does not have active inbound IDs. Refresh the server first.')
        for key, value in {
            'test_account_enabled': '1' if str(enabled) == '1' else '0',
            'test_account_button_visible': '1' if str(button_visible) == '1' else '0',
            'test_account_server_id': str(server_id),
            'test_account_inbound_ids': ','.join(str(x) for x in parsed),
            'test_account_volume_gb': str(volume).rstrip('0').rstrip('.') if '.' in str(volume) else str(volume),
            'test_account_duration_days': str(duration_days),
        }.items():
            await s.merge(Setting(key=key, value=value))
        await s.commit()
    return ok(request, '/admin/test-account', 'Test account settings saved')


@router.post('/admin/test-account/reset-usages')
@router.get('/admin/test-account/reset-usages')
async def test_account_reset_usages(request: Request, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        await s.execute(delete(TestAccountUsage))
        await s.commit()
    return ok(request, '/admin/test-account', 'Test account usage history reset')


@router.post('/admin/test-account/delete-usage')
@router.get('/admin/test-account/delete-usage')
async def test_account_delete_usage(request: Request, telegram_id: str = '', _: str = Depends(_auth_user)):
    raw = str(telegram_id or '').strip()
    if not raw:
        return fail(request, 'User Telegram ID is required')
    try:
        tg_id = int(raw)
    except Exception:
        return fail(request, 'User Telegram ID must be numeric')
    async with SessionLocal() as s:
        result = await s.execute(delete(TestAccountUsage).where(TestAccountUsage.telegram_id == tg_id))
        await s.commit()
    deleted = int(getattr(result, 'rowcount', 0) or 0)
    if deleted <= 0:
        return fail(request, f'No test account usage found for Telegram ID {tg_id}', 404)
    return ok(request, '/admin/test-account', f'Test account usage removed for Telegram ID {tg_id}')


@router.get('/admin-legacy/settings', response_class=HTMLResponse)
async def settings_page(request: Request, _: str = Depends(_auth_user)):
    web_domain = await db_setting('web_domain', getattr(settings, 'DOMAIN_NAME', '') or '')
    web_user = await db_setting('web_admin_username', settings.WEB_ADMIN_USERNAME or '')
    token_timeout = await db_setting('web_token_timeout_minutes', str(SESSION_MINUTES))
    force_channel = await db_setting('channel_url', '')
    form='<form method="post" action="/admin/settings/save" class="formgrid">'+field('bot_name','Bot name','text',await db_setting('bot_name','D BOT'))+field('support','Support username','text',await db_setting('support_username','@support'))+'<div class="full"><label>Description</label><textarea name="description">'+e(await db_setting('admin_description','VPN management bot'))+'</textarea></div><div class="full"><button class="btn primary">Save</button></div></form>'
    website_form='<form method="post" action="/admin/settings/website" class="formgrid">'+field('domain','Domain','text',web_domain)+field('username','Username','text',web_user)+field('password','New password','password','')+field('token_timeout','Token timeout minutes','number',token_timeout)+'<div class="full"><button class="btn primary">Save website settings</button></div></form>'
    channel_form='<form method="post" action="/admin/settings/channel" class="formgrid">'+field('channel_url','Forced join channel','text',force_channel)+'<div class="full"><button class="btn primary">Save channel</button></div></form>'
    body=(modal('settingsEdit','General Settings','General Settings',form)+modal('websiteEdit','Website Settings','Website Settings',website_form)+modal('channelEdit','Forced Join Channel','Forced Join Channel',channel_form)+
          '<div class="gridcards"><div class="card"><h3>⚙️ General Settings</h3><p class="muted">Bot name, texts and support</p><button class="btn primary" onclick="openModal(\'settingsEdit\')">Edit Settings</button></div>' +
          f'<div class="card"><h3>🌐 Website</h3><p class="muted">Domain, username, password and token timeout</p><p>{e(web_domain or "Not set")}</p><span class="badge status">Session: {e(token_timeout)}m</span><br><br><button class="btn primary" onclick="openModal(\'websiteEdit\')">Edit Website</button></div>' +
          f'<div class="card"><h3>📢 Forced Join Channel</h3><p class="muted">Users must join this channel before using the bot.</p><p>{e(force_channel or "Not set")}</p><button class="btn primary" onclick="openModal(\'channelEdit\')">Edit Channel</button></div></div>')
    return layout('Settings','Settings',body,'/admin/settings')
@router.post('/admin/settings/save')
async def settings_save(request: Request, bot_name:str=Form(...), support:str=Form(...), description:str=Form(''), _: str = Depends(_auth_user)):
    bot_name = bot_name.strip() or 'D BOT'
    support = support.strip()
    description = description.strip()
    async with SessionLocal() as s:
        # AsyncSession.merge is awaitable. Older versions called it without await,
        # so General Settings appeared to save but never changed in the database.
        await s.merge(Setting(key='bot_name', value=bot_name))
        await s.merge(Setting(key='support_username', value=support))
        await s.merge(Setting(key='admin_description', value=description))
        legacy_welcome = '''Welcome to D BOT 🚀

Use this bot to buy services, manage your configs, check service details, open tickets, and access reseller/referral features.

Tap a button below to continue.'''.strip()
        current_welcome = await s.get(Setting, 'welcome_text')
        if current_welcome is None or str(current_welcome.value or '').strip() == legacy_welcome:
            await s.merge(Setting(key='welcome_text', value=WELCOME_TEXT_DEFAULT))
        await s.commit()
    return ok(request, '/admin/settings', 'General settings saved successfully')


@router.post('/admin/settings/buttons')
async def settings_buttons_save(
    request: Request,
    button_buy_text: str = Form(''), button_buy_enabled: str = Form('1'),
    button_my_services_text: str = Form(''), button_my_services_enabled: str = Form('1'),
    button_account_text: str = Form(''), button_account_enabled: str = Form('1'),
    button_test_account_text: str = Form(''), button_test_account_enabled: str = Form('1'),
    button_tickets_text: str = Form(''), button_tickets_enabled: str = Form('1'),
    button_referral_text: str = Form(''), button_referral_enabled: str = Form('1'),
    button_query_text: str = Form(''), button_query_enabled: str = Form('1'),
    button_reseller_request_text: str = Form(''), button_reseller_request_enabled: str = Form('1'),
    button_reseller_menu_text: str = Form(''), button_reseller_menu_enabled: str = Form('1'),
    button_admin_text: str = Form(''), button_admin_enabled: str = Form('1'),
    button_wallet_topup_text: str = Form(''), button_wallet_topup_enabled: str = Form('1'),
    _: str = Depends(_auth_user),
):
    submitted = locals()
    async with SessionLocal() as session:
        for name, (default_text, default_enabled) in BUTTON_DEFAULTS.items():
            text_value = str(submitted.get(button_text_key(name), '') or '').strip() or default_text
            if len(text_value) > 64:
                return fail(request, f'Button text for {name} is too long. Maximum length is 64 characters.')
            enabled_value = '1' if str(submitted.get(button_enabled_key(name), '1' if default_enabled else '0')) == '1' else '0'
            await session.merge(Setting(key=button_text_key(name), value=text_value))
            await session.merge(Setting(key=button_enabled_key(name), value=enabled_value))
        await session.commit()
    return ok(request, '/admin/settings', 'Bottom button settings saved successfully')




@router.post('/admin/settings/bot-core')
async def bot_core_settings_save(request: Request, welcome_text: str = Form(''), rules_text: str = Form(''), bot_enabled: str = Form('1'), database_info: str = Form(''), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        await s.merge(Setting(key='welcome_text', value=welcome_text.strip()))
        await s.merge(Setting(key='rules_text', value=rules_text.strip()))
        await s.merge(Setting(key='bot_enabled', value='1' if str(bot_enabled) == '1' else '0'))
        await s.merge(Setting(key='database_info', value=database_info.strip() or 'Connected'))
        await s.commit()
    return ok(request, '/admin/settings', 'Bot texts, bot status, and database info saved')


@router.post('/admin/settings/channel')
async def channel_settings_save(request: Request, channel_url:str=Form(''), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        await s.merge(Setting(key='channel_url', value=channel_url.strip()))
        await s.commit()
    return ok(request, '/admin/settings', 'Forced join channel saved')


@router.post('/admin/settings/website')
async def website_settings_save(request: Request, domain:str=Form(''), username:str=Form(''), password:str=Form(''), token_timeout:int=Form(30), _: str = Depends(_auth_user)):
    domain = domain.strip().replace('https://','').replace('http://','').strip('/')
    username = username.strip()
    password = password.strip()
    credentials_changed = bool(username or password)
    async with SessionLocal() as s:
        if domain: await s.merge(Setting(key='web_domain', value=domain))
        if username: await s.merge(Setting(key='web_admin_username', value=username))
        if password: await s.merge(Setting(key='web_admin_password', value=hash_password(password)))
        await s.merge(Setting(key='web_token_timeout_minutes', value=str(max(5, token_timeout))))
        await s.commit()
    if domain:
        ssl_ok, ssl_msg = await _apply_ssl_for_domain(domain)
        await _save_settings_map({'web_ssl_status': 'active' if ssl_ok else 'error', 'web_ssl_message': ssl_msg})
        if not ssl_ok:
            return fail(request, 'SSL request failed: ' + ssl_msg)
        _schedule_site_and_bot_restart('website_settings_ssl_success')
    if credentials_changed:
        _sessions.clear()
        if is_ajax(request):
            res = JSONResponse({'ok': True, 'message': 'Website login changed. Please login again with the new credentials.', 'redirect': '/login?updated=1', 'logout': True})
            res.delete_cookie('dbot_admin_token')
            res.delete_cookie('dbot_csrf_token')
            return res
        res = RedirectResponse('/login?updated=1', status_code=303)
        res.delete_cookie('dbot_admin_token')
        res.delete_cookie('dbot_csrf_token')
        return res
    return ok(request, '/admin/settings', 'Website settings saved and SSL applied')


@router.post('/admin/settings/ssl/apply')
@router.get('/admin/settings/ssl/apply')
async def website_ssl_apply(request: Request, _: str = Depends(_auth_user)):
    m = await _settings_map()
    domain = (m.get('web_domain') or '').strip()
    ssl_ok, ssl_msg = await _apply_ssl_for_domain(domain)
    await _save_settings_map({'web_ssl_status': 'active' if ssl_ok else 'error', 'web_ssl_message': ssl_msg})
    if not ssl_ok:
        return fail(request, 'SSL apply failed: ' + ssl_msg)
    _schedule_site_and_bot_restart('manual_ssl_apply_success')
    return ok(request, '/admin/settings', 'SSL applied successfully. Site and bot restart requested.')


# -----------------------------------------------------------------------------
# React/Next.js Admin API v2
# These endpoints expose the same database-backed business data used by the
# Telegram bot and legacy admin panel. They intentionally reuse existing models
# and existing mutation routes so bot synchronization and database behavior stay
# unchanged.
# -----------------------------------------------------------------------------

def dt_iso(v):
    try:
        return v.isoformat() if v else None
    except Exception:
        return None

def srv_json(sv):
    m = sv.meta or {}
    return {
        'id': sv.id, 'name': sv.name, 'display_name': m.get('display_name') or sv.name,
        'server_type': sv.server_type, 'server_type_label': 'MikroTik / Custom' if sv.server_type == 'mikrotik' else sv.server_type, 'panel_url': sv.panel_url,
        'panel_base_url': m.get('panel_base_url') or '', 'panel_path': m.get('panel_path') or '/',
        'subscription_url': sv.subscription_url,
        'username': (m.get('auth_username') or sv.username) if sv.server_type == 'mikrotik' else sv.username,
        'auth_username': m.get('auth_username') or '',
        'category_id': sv.category_id, 'is_active': sv.is_active,
        'scope': m.get('scope') or 'public', 'inbound_ids': m.get('inbound_ids') or [],
        'inbounds': m.get('inbounds') or [{'id': x, 'remark': f'Inbound {x}', 'protocol': ''} for x in (m.get('inbound_ids') or [])],
        'last_inbound_sync_at': m.get('last_inbound_sync_at') or '',
        'router_name': m.get('router_name') or sv.username or '',
        'router_host': m.get('router_host') or '',
        'router_port': m.get('router_port') or '',
        'router_online': bool(m.get('router_online', sv.is_active)),
        'router_identity': m.get('router_identity') or '',
        'router_version': m.get('router_version') or '',
        'router_uptime': m.get('router_uptime') or '',
        'router_secrets': int(m.get('router_secrets') or 0),
        'router_active': int(m.get('router_active') or 0),
        'router_error': m.get('router_error') or '',
        'last_router_sync_at': m.get('last_router_sync_at') or '',
        'default_protocol': m.get('default_protocol') or 'openvpn',
        'openvpn_profile_id': int(m.get('openvpn_profile_id') or 0),
        'l2tp_server': m.get('l2tp_server') or '',
        'l2tp_ipsec_secret': m.get('l2tp_ipsec_secret') or '',
        'badge_color': m.get('badge_color') or ('#f97316' if sv.server_type == 'mikrotik' else '#2563eb'),
        'badge_emoji': m.get('badge_emoji') or ('🟠' if sv.server_type == 'mikrotik' else '🔵'),
        'badge_label': m.get('badge_label') or ('MikroTik / OpenVPN' if sv.server_type == 'mikrotik' else 'V2Ray'),
        'created_at': dt_iso(sv.created_at)
    }

def user_json(u, purchases=0):
    return {
        'id': u.id, 'telegram_id': u.telegram_id, 'username': u.username,
        'full_name': u.full_name, 'wallet_balance': int(getattr(u,'wallet_balance',0) or 0),
        'wallet_v2ray_balance': int(getattr(u,'wallet_v2ray_balance',0) or 0),
        'wallet_openvpn_balance': int(getattr(u,'wallet_openvpn_balance',0) or 0),
        'wallet_total': user_wallet_total(u), 'accepted_rules': u.accepted_rules,
        'is_blocked': u.is_blocked, 'referral_code': getattr(u,'referral_code',None),
        'purchases': int(purchases or 0), 'joined_at': dt_iso(getattr(u,'joined_at',None))
    }

def plan_json(p):
    return {
        'id': p.id, 'title': p.title, 'volume_gb': p.volume_gb,
        'duration_days': p.duration_days, 'price_irt': int(p.price_irt or 0),
        'category_id': p.category_id, 'server_id': p.server_id,
        'inbound_ids': p.inbound_ids or [],
        'inbound_mode': _plan_inbound_mode(p),
        'is_unlimited': p.is_unlimited,
        'is_active': p.is_active, 'meta': p.meta or {}
    }

def order_json(o, user=None, plan=None):
    return {
        'id': o.id, 'user_id': o.user_id, 'plan_id': o.plan_id, 'service_id': o.service_id,
        'amount_irt': int(o.amount_irt or 0), 'payment_method': o.payment_method,
        'status': o.status, 'receipt_file_id': o.receipt_file_id,
        'external_payment_id': o.external_payment_id, 'external_invoice_url': o.external_invoice_url,
        'rejection_reason': getattr(o, 'rejection_reason', None),
        'rejected_by': getattr(o, 'rejected_by', None),
        'rejected_at': dt_iso(getattr(o, 'rejected_at', None)),
        'created_at': dt_iso(o.created_at),
        'user': user_json(user) if user else None,
        'plan': plan_json(plan) if plan else None,
    }

@router.get('/admin/api/v2/dashboard')
async def api_v2_dashboard(start_date: str | None = None, end_date: str | None = None, _: str = Depends(_auth_user)):
    now = datetime.utcnow()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1) if end_date else now + timedelta(days=1)
    start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else now - timedelta(days=30)
    span_days = max(1, min(365, (end_dt.date() - start_dt.date()).days))
    previous_start = start_dt - timedelta(days=span_days)
    previous_end = start_dt
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    paid_statuses = {'paid', 'approved', 'completed'}
    async with SessionLocal() as s:
        sales = await s.scalar(select(func.coalesce(func.sum(Order.amount_irt), 0)).where(Order.status.in_(paid_statuses), Order.created_at >= start_dt, Order.created_at < end_dt)) or 0
        prev_sales = await s.scalar(select(func.coalesce(func.sum(Order.amount_irt), 0)).where(Order.status.in_(paid_statuses), Order.created_at >= previous_start, Order.created_at < previous_end)) or 0
        users_total = await s.scalar(select(func.count(User.id))) or 0
        users_today = await s.scalar(select(func.count(User.id)).where(User.joined_at >= today)) or 0
        users_yesterday = await s.scalar(select(func.count(User.id)).where(User.joined_at >= yesterday, User.joined_at < today)) or 0
        wallet_total = await s.scalar(select(func.coalesce(func.sum(User.wallet_balance), 0))) or 0
        wallet_today = await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt), 0)).where(WalletTransaction.created_at >= today)) or 0
        wallet_yesterday = await s.scalar(select(func.coalesce(func.sum(WalletTransaction.amount_irt), 0)).where(WalletTransaction.created_at >= yesterday, WalletTransaction.created_at < today)) or 0
        resellers_total = await s.scalar(select(func.count(ResellerAccount.id))) or 0
        active_services = await s.scalar(select(func.count(ClientService.id)).where(ClientService.is_active == True)) or 0
        today_orders = await s.scalar(select(func.count(Order.id)).where(Order.created_at >= start_dt, Order.created_at < end_dt)) or 0
        previous_orders = await s.scalar(select(func.count(Order.id)).where(Order.created_at >= previous_start, Order.created_at < previous_end)) or 0
        total_orders = await s.scalar(select(func.count(Order.id))) or 0
        completed_orders = await s.scalar(select(func.count(Order.id)).where(Order.status.in_(paid_statuses))) or 0
        recent = (await s.execute(select(Order).where(Order.created_at >= start_dt, Order.created_at < end_dt).order_by(Order.id.desc()).limit(8))).scalars().all()
        user_ids = [o.user_id for o in recent]
        plan_ids = [o.plan_id for o in recent if o.plan_id]
        users = {u.id: u for u in (await s.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
        plans = {p.id: p for p in (await s.execute(select(Plan).where(Plan.id.in_(plan_ids)))).scalars().all()} if plan_ids else {}
        rows = (await s.execute(select(func.date(Order.created_at), func.coalesce(func.sum(Order.amount_irt), 0)).where(Order.status.in_(paid_statuses), Order.created_at >= start_dt, Order.created_at < end_dt).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at)))).all()
        mapped = {str(d): int(v or 0) for d, v in rows}
        chart_data = []
        for i in range(span_days):
            d = (start_dt + timedelta(days=i)).date()
            chart_data.append({'date': d.isoformat(), 'label': d.strftime('%b %d'), 'sales': mapped.get(d.isoformat(), 0)})
    conversion = round((completed_orders / total_orders * 100), 2) if total_orders else 0
    return {'ok': True, 'stats': {
        'monthly_sales': int(sales), 'monthly_sales_change': percent_change(sales, prev_sales),
        'wallet_balance': int(wallet_total), 'wallet_change': percent_change(wallet_today, wallet_yesterday),
        'users_total': int(users_total), 'users_change': percent_change(users_today, users_yesterday),
        'resellers_total': int(resellers_total), 'active_services': int(active_services),
        'today_orders': int(today_orders), 'orders_change': percent_change(today_orders, previous_orders),
        'conversion_rate': conversion},
        'resources': _resource_stats(), 'chart_ranges': [{'range': span_days, 'data': chart_data}],
        'latest_orders': [order_json(o, users.get(o.user_id), plans.get(o.plan_id)) for o in recent]}


@router.get('/admin/api/v2/users')
async def api_v2_users(page:int=1, page_size:int=50, q:str='', _: str = Depends(_auth_user)):
    page=max(1,page); page_size=max(1,min(page_size,200)); offset=(page-1)*page_size
    async with SessionLocal() as s:
        stmt=select(User)
        if q:
            like=f'%{q}%'
            stmt=stmt.where((User.username.ilike(like)) | (User.full_name.ilike(like)) | (func.cast(User.telegram_id,String).ilike(like)))
        total=await s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        users=(await s.execute(stmt.order_by(User.id.desc()).offset(offset).limit(page_size))).scalars().all()
        ids=[u.id for u in users]
        purchases=dict((await s.execute(select(Order.user_id, func.count(Order.id)).where(Order.user_id.in_(ids)).group_by(Order.user_id))).all()) if ids else {}
        reseller_ids=set((await s.execute(select(ResellerAccount.user_id).where(ResellerAccount.user_id.in_(ids)))).scalars().all()) if ids else set()
    items=[]
    for u in users:
        row=user_json(u,purchases.get(u.id,0)); row['is_reseller']=u.id in reseller_ids; items.append(row)
    return {'ok':True,'total':int(total),'page':page,'page_size':page_size,'items':items}


@router.get('/admin/api/v2/servers')
async def api_v2_servers(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(Server).order_by(Server.id.desc()))).scalars().all()
        counts=dict((await s.execute(select(ClientService.server_id,func.count(ClientService.id)).group_by(ClientService.server_id))).all())
    data=[]
    for sv in items:
        row=srv_json(sv); row['user_count']=int(counts.get(sv.id,0)); data.append(row)
    return {'ok':True,'items':data}

@router.get('/admin/api/v2/categories')
async def api_v2_categories(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        rows=(await s.execute(select(ServerCategory).order_by(ServerCategory.id.desc()))).scalars().all()
        servers=(await s.execute(select(Server))).scalars().all()
        category_order_row = await s.get(Setting, 'category_order_public')
        category_order = _parse_id_order(category_order_row.value if category_order_row else '')
    server_by_id={x.id:x for x in servers}
    grouped=[]; seen=set()
    for c in rows:
        key=(c.name or '').strip().lower()
        if key in seen:
            continue
        seen.add(key)
        related=[x for x in rows if (x.name or '').strip().lower()==key]
        server_ids=[]; active=False
        for row in related:
            active = active or bool(getattr(row, 'is_active', True))
            for sid in _category_linked_server_ids(row):
                if sid not in server_ids:
                    server_ids.append(sid)
        server_names=[]
        for sid in server_ids:
            srv=server_by_id.get(sid)
            server_names.append(((srv.meta or {}).get('display_name') or srv.name) if srv else f'Server #{sid}')
        grouped.append({'id':c.id,'name':c.name,'server_id':server_ids[0] if server_ids else None,'server_ids':server_ids,'server_names':server_names,'is_active': active})
    category_rank = {cid: idx for idx, cid in enumerate(category_order)}
    grouped.sort(key=lambda row: (category_rank.get(int(row['id']), 10_000_000), int(row['id'])))
    return {'ok':True,'items':grouped}

@router.get('/admin/api/v2/plans')
async def api_v2_plans(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        plans=(await s.execute(select(Plan))).scalars().all()
        reseller=(await s.execute(select(ResellerPackage))).scalars().all()
        public_order_row = await s.get(Setting, 'plan_order_public')
        reseller_order_row = await s.get(Setting, 'plan_order_reseller')
        public_order = public_order_row.value if public_order_row else ''
        reseller_order = reseller_order_row.value if reseller_order_row else ''
    plans = _sort_by_saved_order(plans, public_order)
    reseller = _sort_by_saved_order(reseller, reseller_order)
    return {'ok':True,'plans':[plan_json(p) for p in plans], 'reseller_packages':[{'id':r.id,'title':r.title,'server_id':r.server_id,'volume_gb':r.volume_gb,'price_irt':int(r.price_irt or 0),'reseller_validity_days':r.reseller_validity_days,'is_active':r.is_active,'created_at':dt_iso(r.created_at)} for r in reseller]}




@router.get('/admin/api/v2/openvpn-profiles')
async def api_v2_openvpn_profiles(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        profiles = (await s.execute(select(OpenVPNProfile).order_by(OpenVPNProfile.id.desc()))).scalars().all()
        servers = (await s.execute(select(Server).where(Server.server_type == 'mikrotik').order_by(Server.id.desc()))).scalars().all()
    return {'ok': True, 'items': [
        {'id': p.id, 'name': p.name, 'server_id': p.server_id, 'file_name': p.file_name, 'content': p.content, 'is_active': p.is_active, 'created_at': dt_iso(p.created_at)}
        for p in profiles
    ], 'servers': [srv_json(x) for x in servers]}

@router.post('/admin/openvpn-profiles/add')
async def openvpn_profile_add(request: Request, name: str = Form(...), server_id: int = Form(0), file_name: str = Form('profile.ovpn'), content: str = Form(''), upload: UploadFile | None = File(None), _: str = Depends(_auth_user)):
    text_content = content or ''
    fn = file_name or 'profile.ovpn'
    if upload and upload.filename:
        raw = await upload.read()
        if len(raw) > 512 * 1024:
            return fail(request, 'OpenVPN profile is too large.', 400)
        text_content = raw.decode('utf-8', errors='replace')
        fn = upload.filename
    if not text_content.strip():
        return fail(request, 'Profile content is required.', 400)
    async with SessionLocal() as s:
        p = OpenVPNProfile(name=name.strip(), server_id=(server_id or None), file_name=fn, content=text_content, is_active=True)
        s.add(p); await s.commit()
    return ok(request, '/admin/openvpn-profiles', 'OpenVPN profile added')

@router.post('/admin/openvpn-profiles/{pid}/edit')
async def openvpn_profile_edit(request: Request, pid: int, name: str = Form(...), server_id: int = Form(0), file_name: str = Form('profile.ovpn'), content: str = Form(''), upload: UploadFile | None = File(None), _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        p = await s.get(OpenVPNProfile, pid)
        if not p:
            raise HTTPException(404)
        text_content = content or p.content or ''
        fn = file_name or p.file_name or 'profile.ovpn'
        if upload and upload.filename:
            raw = await upload.read()
            if len(raw) > 512 * 1024:
                return fail(request, 'OpenVPN profile is too large.', 400)
            text_content = raw.decode('utf-8', errors='replace')
            fn = upload.filename
        if not text_content.strip():
            return fail(request, 'Profile content is required.', 400)
        p.name = name.strip(); p.server_id = server_id or None; p.file_name = fn; p.content = text_content
        await s.commit()
    return ok(request, '/admin/openvpn-profiles', 'OpenVPN profile updated')

@router.post('/admin/openvpn-profiles/{pid}/delete')
@router.get('/admin/openvpn-profiles/{pid}/delete')
async def openvpn_profile_delete(request: Request, pid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        p = await s.get(OpenVPNProfile, pid)
        if p:
            await s.delete(p); await s.commit()
    return ok(request, '/admin/openvpn-profiles', 'OpenVPN profile deleted')


@router.post('/admin/toggle/plans/{pid}')
@router.get('/admin/toggle/plans/{pid}')
async def toggle_public_plan(request: Request, pid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        plan = await s.get(Plan, pid)
        if not plan:
            return fail(request, 'Plan not found', 404)
        plan.is_active = not bool(plan.is_active)
        await s.commit()
        status = 'activated' if plan.is_active else 'deactivated'
    return ok(request, '/admin/plans', f'Plan {status}')

@router.post('/admin/toggle/reseller-plans/{pid}')
@router.get('/admin/toggle/reseller-plans/{pid}')
async def toggle_reseller_plan(request: Request, pid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        plan = await s.get(ResellerPackage, pid)
        if not plan:
            return fail(request, 'Reseller plan not found', 404)
        plan.is_active = not bool(plan.is_active)
        await s.commit()
        status = 'activated' if plan.is_active else 'deactivated'
    return ok(request, '/admin/plans', f'Reseller plan {status}')

@router.post('/admin/toggle/servers/{sid}')
@router.get('/admin/toggle/servers/{sid}')
async def toggle_server(request: Request, sid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        server = await s.get(Server, sid)
        if not server:
            return fail(request, 'Server not found', 404)
        server.is_active = not bool(server.is_active)
        await s.commit()
        status = 'activated' if server.is_active else 'deactivated'
    return ok(request, '/admin/servers', f'Server {status}')

@router.post('/admin/toggle/categories/{cid}')
@router.get('/admin/toggle/categories/{cid}')
async def toggle_category(request: Request, cid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        category = await s.get(ServerCategory, cid)
        if not category:
            return fail(request, 'Category not found', 404)
        new_value = not bool(getattr(category, 'is_active', True))
        category_name = (category.name or '').strip()
        if category_name:
            rows = (await s.execute(select(ServerCategory).where(func.lower(ServerCategory.name) == category_name.lower()))).scalars().all()
            for row in rows:
                row.is_active = new_value
        else:
            category.is_active = new_value
        await s.commit()
        status = 'activated' if new_value else 'deactivated'
    return ok(request, '/admin/categories', f'Category {status}')

@router.post('/admin/toggle/openvpn-profiles/{pid}')
@router.get('/admin/toggle/openvpn-profiles/{pid}')
async def toggle_openvpn_profile(request: Request, pid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        profile = await s.get(OpenVPNProfile, pid)
        if not profile:
            return fail(request, 'OpenVPN profile not found', 404)
        profile.is_active = not bool(profile.is_active)
        await s.commit()
        status = 'activated' if profile.is_active else 'deactivated'
    return ok(request, '/admin/openvpn-profiles', f'OpenVPN profile {status}')

@router.post('/admin/categories/reorder')
async def categories_reorder(request: Request, ids: str = Form(''), _: str = Depends(_auth_user)):
    wanted = _parse_id_order(ids)
    async with SessionLocal() as s:
        rows = (await s.execute(select(ServerCategory).order_by(ServerCategory.id.desc()))).scalars().all()
        representatives = []
        seen = set()
        for row in rows:
            key = ' '.join((row.name or '').strip().lower().split())
            if not key or key in seen:
                continue
            seen.add(key)
            representatives.append(row.id)
        existing_set = set(representatives)
        clean = [cid for cid in wanted if cid in existing_set]
        clean += [cid for cid in representatives if cid not in clean]
        await set_db_setting(s, 'category_order_public', ','.join(map(str, clean)))
        await s.commit()
    return ok(request, '/admin/categories', 'Category order saved')


@router.post('/admin/plans/reorder')
async def plans_reorder(request: Request, kind: str = Form('public'), ids: str = Form(''), _: str = Depends(_auth_user)):
    kind = 'reseller' if kind == 'reseller' else 'public'
    wanted = _parse_id_order(ids)
    async with SessionLocal() as s:
        if kind == 'reseller':
            existing = [x.id for x in (await s.execute(select(ResellerPackage))).scalars().all()]
            key = 'plan_order_reseller'
        else:
            existing = [x.id for x in (await s.execute(select(Plan))).scalars().all()]
            key = 'plan_order_public'
        existing_set = set(existing)
        clean = [x for x in wanted if x in existing_set]
        clean += [x for x in existing if x not in clean]
        await set_db_setting(s, key, ','.join(map(str, clean)))
        await s.commit()
    return ok(request, '/admin/plans', 'Plan order saved')

@router.get('/admin/api/v2/payments')
async def api_v2_payments(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(PaymentCard).order_by(PaymentCard.id.desc()))).scalars().all()
    return {'ok':True,'items':[{'id':p.id,'server_type':p.server_type,'server_id':p.server_id,'card_number':p.card_number,'owner_name':p.owner_name,'is_active':p.is_active} for p in items]}

@router.get('/admin/api/v2/discounts')
async def api_v2_discounts(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(DiscountCode).order_by(DiscountCode.id.desc()))).scalars().all()
        servers=(await s.execute(select(Server))).scalars().all()
    srv_by_id={srv.id:srv for srv in servers}
    out=[]
    for d in items:
        server_ids=_discount_allowed_server_ids(d)
        server_names=[]
        for sid in server_ids:
            srv=srv_by_id.get(sid)
            server_names.append(((srv.meta or {}).get('display_name') or srv.name) if srv else f'Server #{sid}')
        out.append({'id':d.id,'code':d.code,'discount_type':d.discount_type,'value':int(d.value or 0),'max_uses':d.max_uses,'per_user_limit':d.per_user_limit,'used_count':d.used_count,'expires_at':dt_iso(d.expires_at),'is_active':d.is_active,'allowed_server_ids':server_ids,'allowed_server_names':server_names})
    return {'ok':True,'items':out}

@router.get('/admin/api/v2/resellers')
async def api_v2_resellers(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        rows=(await s.execute(select(ResellerAccount, User).join(User, User.id==ResellerAccount.user_id).order_by(ResellerAccount.id.desc()))).all()
        items=[]
        for r,u in rows:
            await reconcile_reseller_accounting(s, r)
            items.append({'id':r.id,'user_id':r.user_id,'user':user_json(u),'server_id':r.server_id,'total_bytes':int(r.total_bytes or 0),'used_bytes':int(r.used_bytes or 0),'reserved_bytes':int(r.reserved_bytes or 0),'remaining_bytes':remaining_bytes(r),'expires_at':dt_iso(r.expires_at),'is_active':r.is_active,'created_at':dt_iso(r.created_at)})
        await s.commit()
    return {'ok':True,'items':items}


@router.get('/admin/resellers/{rid}/refresh')
@router.post('/admin/resellers/{rid}/refresh')
async def reseller_refresh_accounting(request: Request, rid: int, _: str = Depends(_auth_user)):
    """Refresh panel snapshots and rebuild all reseller counters safely.

    Used is rebuilt from per-service lifetime usage, Reserved contains active
    services only, and Total remains the current sellable pool.
    """
    async with SessionLocal() as s:
        reseller = (await s.execute(
            select(ResellerAccount).where(ResellerAccount.id == rid).with_for_update()
        )).scalar_one_or_none()
        if not reseller:
            return fail(request, 'Reseller not found', 404)
        try:
            # Reuse the same live panel sync used by the reseller bot pages.
            from app.bot.handlers.public.reseller import sync_all_reseller_services
            await sync_all_reseller_services(s, reseller, commit=False)
        except Exception as exc:
            logger.warning('Reseller panel refresh failed rid=%s: %s', rid, exc)
        stats = await reconcile_reseller_accounting(s, reseller, force_used_rebuild=True)
        await s.commit()
    return JSONResponse({
        'ok': True,
        'message': 'Reseller accounting refreshed',
        'item': {
            'id': rid,
            'total_bytes': int((stats or {}).get('total_bytes', 0)),
            'used_bytes': int((stats or {}).get('used_bytes', 0)),
            'reserved_bytes': int((stats or {}).get('reserved_bytes', 0)),
            'remaining_bytes': int((stats or {}).get('remaining_bytes', 0)),
        },
    })


@router.get('/admin/api/v2/resellers/{rid}/services')
async def api_v2_reseller_services(rid: int, _: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        reseller_row = (await s.execute(select(ResellerAccount, User).join(User, User.id == ResellerAccount.user_id).where(ResellerAccount.id == rid))).first()
        if not reseller_row:
            raise HTTPException(status_code=404, detail='Reseller not found')
        reseller, reseller_user = reseller_row
        await reconcile_reseller_accounting(s, reseller)
        services = (await s.execute(select(ClientService).where(ClientService.reseller_id == rid).order_by(ClientService.id.desc()))).scalars().all()
        server_ids = [svc.server_id for svc in services if svc.server_id]
        existing_server_ids = set()
        if server_ids:
            existing_server_ids = set((await s.execute(select(Server.id).where(Server.id.in_(server_ids)))).scalars().all())
        if any((not svc.server_id) or (svc.server_id not in existing_server_ids) for svc in services):
            await repair_reseller_services_from_panels(s, reseller)
            services = (await s.execute(select(ClientService).where(ClientService.reseller_id == rid).order_by(ClientService.id.desc()))).scalars().all()
        await reconcile_reseller_accounting(s, reseller)

        # Create one historical "created" event for pre-existing services.
        # Renewals performed before this feature cannot be reconstructed reliably.
        existing_create_ids = set((await s.execute(
            select(ResellerServiceActivity.service_id).where(
                ResellerServiceActivity.reseller_id == rid,
                ResellerServiceActivity.action == 'create',
                ResellerServiceActivity.service_id.is_not(None),
            )
        )).scalars().all())
        for svc in services:
            username = svc.client_username or svc.xui_email or '-'
            if svc.id in existing_create_ids or username.startswith('deleted_'):
                continue
            duration_days = 0
            if svc.created_at and svc.expires_at:
                duration_days = max((svc.expires_at.date() - svc.created_at.date()).days, 0)
            s.add(ResellerServiceActivity(
                reseller_id=rid,
                service_id=svc.id,
                server_id=svc.server_id,
                action='create',
                event_key=f'create:{svc.id}',
                username=username,
                volume_bytes=int(svc.total_bytes or svc.reseller_reserved_bytes or 0),
                previous_volume_bytes=0,
                duration_days=duration_days,
                expires_at=svc.expires_at,
                meta={'source': 'backfill'},
                created_at=svc.created_at or datetime.utcnow(),
            ))
        await s.flush()

        activities = (await s.execute(
            select(ResellerServiceActivity)
            .where(ResellerServiceActivity.reseller_id == rid)
            .order_by(ResellerServiceActivity.created_at.desc(), ResellerServiceActivity.id.desc())
            .limit(500)
        )).scalars().all()

        server_ids = list({sid for sid in ([svc.server_id for svc in services] + [a.server_id for a in activities]) if sid})
        plan_ids = [svc.plan_id for svc in services if svc.plan_id]
        servers = {srv.id: srv for srv in (await s.execute(select(Server).where(Server.id.in_(server_ids)))).scalars().all()} if server_ids else {}
        plans = {pl.id: pl for pl in (await s.execute(select(Plan).where(Plan.id.in_(plan_ids)))).scalars().all()} if plan_ids else {}
        await s.commit()

    items = []
    for svc in services:
        total = int(svc.total_bytes or 0)
        used = int(svc.used_bytes or 0)
        remaining = max(0, total - used)
        srv = servers.get(svc.server_id)
        plan = plans.get(svc.plan_id)
        title = plan.title if plan else 'نمایندگی'
        items.append({
            'id': svc.id,
            'username': svc.client_username or svc.xui_email or '-',
            'panel_username': svc.xui_email or svc.client_username or '-',
            'server_id': svc.server_id,
            'server_name': ((srv.meta or {}).get('display_name') or srv.name) if srv else '-',
            'server_type': srv.server_type if srv else '-',
            'plan_title': title,
            'total_bytes': total,
            'used_bytes': used,
            'remaining_bytes': remaining,
            'used_percent': round((used / total * 100), 2) if total else 0,
            'expires_at': dt_iso(svc.expires_at),
            'created_at': dt_iso(svc.created_at),
            'is_active': bool(svc.is_active),
            'disabled_reason': svc.disabled_reason or '',
        })

    activity_items = []
    for activity in activities:
        srv = servers.get(activity.server_id)
        details = dict(activity.meta or {})
        activity_items.append({
            'id': activity.id,
            'action': activity.action,
            'action_label': 'Renewed' if activity.action == 'renew' else 'Created',
            'service_id': activity.service_id,
            'username': activity.username or '-',
            'server_id': activity.server_id,
            'server_name': ((srv.meta or {}).get('display_name') or srv.name) if srv else '-',
            'volume_bytes': int(activity.volume_bytes or 0),
            'previous_volume_bytes': int(activity.previous_volume_bytes or 0),
            'duration_days': int(activity.duration_days or 0),
            'expires_at': dt_iso(activity.expires_at),
            'created_at': dt_iso(activity.created_at),
            'released_bytes': int(details.get('released_bytes') or 0),
            'old_used_bytes': int(details.get('old_used_bytes') or 0),
            'source': str(details.get('source') or ''),
        })
    return {
        'ok': True,
        'reseller': {'id': reseller.id, 'user': user_json(reseller_user), 'total_bytes': int(reseller.total_bytes or 0), 'used_bytes': int(reseller.used_bytes or 0), 'reserved_bytes': int(reseller.reserved_bytes or 0), 'remaining_bytes': remaining_bytes(reseller), 'expires_at': dt_iso(reseller.expires_at), 'created_at': dt_iso(reseller.created_at), 'is_active': reseller.is_active},
        'items': items,
        'activities': activity_items,
        'total': len(items),
        'activity_total': len(activity_items),
    }


@router.get('/admin/api/v2/settings')
async def api_v2_settings(_: str = Depends(_auth_user)):
    async with SessionLocal() as s:
        items=(await s.execute(select(Setting).order_by(Setting.key))).scalars().all()
    raw_map = {it.key: str(it.value or '') for it in items}
    removed_message_keys = {
        'user_home_text', 'user_rules_text',
        'user_purchase_xui_template', 'user_purchase_openvpn_template',
        'user_test_xui_template', 'user_test_openvpn_template',
        'user_renewal_xui_template', 'user_renewal_openvpn_template',
        'user_openvpn_profile_caption',
    }
    safe=[]
    for it in items:
        if it.key in removed_message_keys:
            continue
        val=it.value
        if any(k in it.key.lower() for k in ['password','token','secret']): val='••••••••'
        safe.append({'key':it.key,'value':val})
    # Synthetic safe values used by the read-only Website & SSL card.
    safe.append({'key':'web_password_configured','value':'1' if raw_map.get('web_admin_password') else '0'})
    for name, (default_text, default_enabled) in BUTTON_DEFAULTS.items():
        if button_text_key(name) not in raw_map:
            safe.append({'key':button_text_key(name),'value':default_text})
        if button_enabled_key(name) not in raw_map:
            safe.append({'key':button_enabled_key(name),'value':'1' if default_enabled else '0'})
    return {'ok':True,'items':safe}
