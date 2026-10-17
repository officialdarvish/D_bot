from __future__ import annotations

import ast
import asyncio
import hashlib
import re
import time
from functools import lru_cache
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from aiogram import Bot
from sqlalchemy import select

from app.database.models import Setting
from app.database.session import SessionLocal

CUSTOM_PREFIX = 'custom_text:'
_CACHE_TTL = 2.0


@dataclass(frozen=True)
class TextEntry:
    key: str
    default: str
    category: str
    section: str
    kind: str
    source: str
    line: int
    symbol: str = ''
    placeholders: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data['placeholders'] = list(self.placeholders)
        return data


_catalog_cache: list[TextEntry] | None = None
_override_cache: dict[str, str] = {}
_override_cache_until = 0.0
_override_lock = asyncio.Lock()


def invalidate_custom_text_cache() -> None:
    global _override_cache_until
    _override_cache.clear()
    _override_cache_until = 0.0


def _category_for(path: Path) -> str:
    """Return a user-journey category, not a source-code category."""
    rel = '/'.join(path.parts).lower()
    name = path.stem.lower()
    if rel.endswith('/bot/keyboards/common.py'):
        return 'منو و دکمه‌های اصلی'
    if rel.endswith('/bot/handlers/start.py'):
        return 'شروع و صفحه اصلی'
    if '/bot/handlers/public/' in rel:
        return {
            'buy': 'خرید و پرداخت',
            'my_services': 'کانفیگ‌های من',
            'account': 'حساب کاربری و کیف پول',
            'tickets': 'پشتیبانی و تیکت',
            'reseller': 'نمایندگی',
            'test_account': 'اکانت تست',
            'private_messages': 'پیام خصوصی',
        }.get(name, 'تعامل کاربر')
    if name == 'service_presenter':
        return 'تحویل سرویس'
    if name == 'profile_delivery':
        return 'پروفایل و آموزش اتصال'
    if name == 'renewal_delivery':
        return 'تمدید سرویس'
    if rel.endswith('/bot/utils.py'):
        return 'پیام‌های عمومی کاربر'
    if rel.endswith('/jobs/service_alerts.py'):
        return 'هشدارهای سرویس'
    if rel.endswith('/jobs/service_cleanup.py'):
        return 'انقضا و حذف سرویس'
    if rel.endswith('/services/referral_service.py'):
        return 'دعوت و پورسانت'
    return 'سایر پیام‌های کاربر'


def _section_for(path: Path, function_name: str = '', symbol: str = '') -> str:
    rel = '/'.join(path.parts).lower()
    name = path.stem.lower()
    fn = (function_name or '').lower()
    sym = (symbol or '').lower()
    token = f'{fn} {sym}'

    if name == 'buy':
        if any(x in token for x in ('receipt', 'approve', 'reject', 'payment', 'pay_', 'discount', 'wallet')):
            return 'پرداخت، رسید و تأیید خرید'
        if any(x in token for x in ('success', 'approved_order', 'build_service', 'service_building', 'create_admin_free')):
            return 'ساخت و تحویل سرویس'
        if any(x in token for x in ('username', 'password')):
            return 'اطلاعات کانفیگ'
        if any(x in token for x in ('plan', 'category', 'server', 'service_type')):
            return 'انتخاب سرویس و پلن'
        return 'فرآیند خرید'

    if name == 'my_services':
        if 'renew' in token:
            return 'تمدید سرویس'
        if any(x in token for x in ('hwid', 'device')):
            return 'مدیریت دستگاه و HWID'
        if 'delete' in token:
            return 'حذف کانفیگ'
        if any(x in token for x in ('refresh', 'profile', 'password', 'link')):
            return 'مدیریت کانفیگ'
        return 'مشاهده کانفیگ‌ها'

    if name == 'account':
        if any(x in token for x in ('receipt', 'wallet', 'card', 'amount')):
            return 'کیف پول و رسید پرداخت'
        return 'حساب کاربری'

    if name == 'tickets':
        return 'ثبت و پیگیری تیکت'
    if name == 'reseller':
        if 'receipt' in token:
            return 'رسید و شارژ نمایندگی'
        if any(x in token for x in ('create', 'user', 'username', 'renew')):
            return 'مدیریت یوزر نمایندگی'
        return 'پنل نمایندگی'
    if name == 'test_account':
        return 'ساخت اکانت تست'
    if name == 'private_messages':
        return 'گفتگوی خصوصی با مدیریت'
    if name == 'service_presenter':
        return 'کارت و مشخصات سرویس'
    if name == 'profile_delivery':
        return 'پروفایل OpenVPN'
    if name == 'renewal_delivery':
        return 'پیام نتیجه تمدید'
    if rel.endswith('/bot/handlers/start.py'):
        return 'ورود، قوانین و منوی اصلی'
    if rel.endswith('/bot/keyboards/common.py'):
        return 'دکمه‌های قابل مشاهده کاربر'
    if rel.endswith('/jobs/service_alerts.py'):
        return 'هشدار حجم، زمان و غیرفعال شدن'
    if rel.endswith('/jobs/service_cleanup.py'):
        return 'اعلان انقضا و حذف'
    if rel.endswith('/services/referral_service.py'):
        return 'دعوت، جایزه و پورسانت'
    if rel.endswith('/bot/utils.py'):
        return 'خطا و راهنمای ورودی'
    return 'تعامل کاربر'

def _safe_placeholder(node: ast.AST, index: int) -> str:
    if isinstance(node, ast.Name):
        base = node.id
    elif isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        base = '_'.join(reversed(parts)) if parts else f'value{index}'
    else:
        base = f'value{index}'
    base = re.sub(r'[^a-zA-Z0-9_]+', '_', base).strip('_') or f'value{index}'
    return base[:48]


def _template_from_expr(node: ast.AST | None) -> tuple[str | None, tuple[str, ...]]:
    if node is None:
        return None, ()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        placeholders = tuple(dict.fromkeys(re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', node.value)))
        return node.value, placeholders
    if isinstance(node, ast.JoinedStr):
        out: list[str] = []
        placeholders: list[str] = []
        used: dict[str, int] = {}
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                base = _safe_placeholder(part.value, len(placeholders) + 1)
                used[base] = used.get(base, 0) + 1
                name = base if used[base] == 1 else f'{base}_{used[base]}'
                placeholders.append(name)
                out.append('{' + name + '}')
        return ''.join(out), tuple(placeholders)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, lp = _template_from_expr(node.left)
        right, rp = _template_from_expr(node.right)
        if left is not None and right is not None:
            return left + right, tuple(dict.fromkeys(lp + rp))
    return None, ()


def _contains_persian(value: str) -> bool:
    # Arabic/Persian script. Custom intentionally exposes only Persian Telegram UI text.
    return bool(re.search(r'[\u0600-\u06FF]', value or ''))


def _looks_technical(value: str) -> bool:
    s = value.strip()
    lower = s.lower()
    if not s:
        return True
    prefixes = (
        'admin:', 'menu:', 'buy:', 'back:', 'service:', 'reseller:', 'ticket:', 'wallet:',
        'http://', 'https://', 'postgresql', 'select ', 'update ', 'delete ', 'insert ',
        'alter ', 'create ', 'drop ', 'pragma ', 'sqlite', 'redis://', 'x-requested-with',
    )
    if lower.startswith(prefixes):
        return True
    if '\x00' in s:
        return True
    return False


def _looks_user_facing(value: str) -> bool:
    s = value.strip()
    if not s or len(s) > 4096 or _looks_technical(s):
        return False
    return _contains_persian(s)


def _nested_string_nodes(node: ast.AST | None) -> Iterable[ast.AST]:
    if node is None:
        return
    if isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Call)):
        yield node
        return
    if isinstance(node, ast.Dict):
        for value in node.values:
            yield from _nested_string_nodes(value)
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for value in node.elts:
            yield from _nested_string_nodes(value)


class _CatalogVisitor(ast.NodeVisitor):
    # Calls that visibly send/edit Telegram text or surface an alert/message.
    MESSAGE_CALLS = {
        'answer', 'send_message', 'edit_text', 'edit_caption', 'edit_message_text',
        'edit_message_caption', 'edit_or_answer', 'ui_message', 'ui_callback_message',
        'ui_page', '_safe_send_start_page', 'send_photo', 'send_document', 'send_video',
        'send_animation', 'answer_photo', 'answer_document', 'answer_video',
        'send_single_message', 'state_prompt', 'safe_callback_answer', 'send_buyer_notice',
        '_send_menu',
    }
    BUTTON_CALLS = {'InlineKeyboardButton', 'KeyboardButton'}
    # Text containers frequently used before a Telegram send call.
    SEMANTIC_SYMBOL = re.compile(
        r'(^BTN_|BUTTON|_TEXT$|_TEXT_DEFAULT$|_PROMPT$|_CAPTION$|_MESSAGE$|_MSG$|'
        r'WELCOME|RULES|NOTICE|ALERT|ERROR|SUCCESS|LABELS?$|TITLES?$)',
        re.IGNORECASE,
    )

    def __init__(self, path: Path, root: Path, tree: ast.AST):
        self.path = path
        self.root = root
        self.category = _category_for(path)
        self.entries: list[TextEntry] = []
        self._seen_local: set[tuple[str, int, str]] = set()
        self.module_scope = id(tree)
        self.scope_for: dict[int, int] = {}
        self.bindings: dict[tuple[int, str], list[tuple[int, ast.AST]]] = {}
        self._function_stack: list[str] = []
        self._collect_bindings(tree)

    def _collect_bindings(self, tree: ast.AST) -> None:
        owner = self

        class Collector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope = owner.module_scope

            def visit(self, node: ast.AST) -> Any:
                owner.scope_for[id(node)] = self.scope
                return super().visit(node)

            def _record(self, name: str, value: ast.AST, line: int) -> None:
                owner.bindings.setdefault((self.scope, name), []).append((line, value))

            def visit_Assign(self, node: ast.Assign) -> Any:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._record(target.id, node.value, int(getattr(node, 'lineno', 0) or 0))
                self.generic_visit(node)

            def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
                if isinstance(node.target, ast.Name) and node.value is not None:
                    self._record(node.target.id, node.value, int(getattr(node, 'lineno', 0) or 0))
                self.generic_visit(node)

            def _visit_function(self, node: ast.AST) -> None:
                previous = self.scope
                self.scope = id(node)
                owner.scope_for[id(node)] = previous
                for child in ast.iter_child_nodes(node):
                    self.visit(child)
                self.scope = previous

            def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
                self._visit_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
                self._visit_function(node)

            def visit_Lambda(self, node: ast.Lambda) -> Any:
                self._visit_function(node)

        Collector().visit(tree)
        for values in self.bindings.values():
            values.sort(key=lambda pair: pair[0])

    def _binding_for(self, name: str, use_node: ast.AST) -> ast.AST | None:
        scope = self.scope_for.get(id(use_node), self.module_scope)
        line = int(getattr(use_node, 'lineno', 10**9) or 10**9)
        for candidate_scope in (scope, self.module_scope):
            values = self.bindings.get((candidate_scope, name), [])
            eligible = [value for bind_line, value in values if bind_line <= line]
            if eligible:
                return eligible[-1]
        return None

    def _resolved_template(self, node: ast.AST | None, seen: set[tuple[int, str]] | None = None) -> tuple[str | None, tuple[str, ...]]:
        if node is None:
            return None, ()
        seen = seen or set()
        if isinstance(node, ast.Name):
            scope = self.scope_for.get(id(node), self.module_scope)
            marker = (scope, node.id)
            bound = self._binding_for(node.id, node)
            if bound is not None and marker not in seen:
                return self._resolved_template(bound, seen | {marker})
            return None, ()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            placeholders = tuple(dict.fromkeys(re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', node.value)))
            return node.value, placeholders
        if isinstance(node, ast.JoinedStr):
            out: list[str] = []
            placeholders: list[str] = []
            used: dict[str, int] = {}
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    base = _safe_placeholder(part.value, len(placeholders) + 1)
                    used[base] = used.get(base, 0) + 1
                    name = base if used[base] == 1 else f'{base}_{used[base]}'
                    placeholders.append(name)
                    out.append('{' + name + '}')
            return ''.join(out), tuple(placeholders)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, lp = self._resolved_template(node.left, seen)
            right, rp = self._resolved_template(node.right, seen)
            if left is not None and right is not None:
                return left + right, tuple(dict.fromkeys(lp + rp))
            return None, ()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
            base, bp = self._resolved_template(node.func.value, seen)
            if base is not None:
                placeholders = list(bp)
                for kw in node.keywords:
                    if kw.arg and kw.arg not in placeholders:
                        placeholders.append(kw.arg)
                return base, tuple(placeholders)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'replace' and len(node.args) >= 2:
            base, bp = self._resolved_template(node.func.value, seen)
            old, _ = self._resolved_template(node.args[0], seen)
            new, np = self._resolved_template(node.args[1], seen)
            if base is not None and old is not None and new is not None:
                return base.replace(old, new), tuple(dict.fromkeys(bp + np))
        return _template_from_expr(node)

    @property
    def current_function(self) -> str:
        return self._function_stack[-1] if self._function_stack else ''

    def _admin_only_function(self) -> bool:
        fn = self.current_function.lower()
        if not fn:
            return False
        if fn.startswith('admin_') or 'ticket_admin' in fn or fn.startswith('send_admin_'):
            return True
        if fn in {
            'approve_order_cb', 'reject_order_cb',
            'replace_admin_receipt_buttons', 'edit_admin_receipt_keyboard',
            'mark_message_status',
        }:
            return True
        return False

    @staticmethod
    def _recipient_looks_admin(node: ast.AST | None) -> bool:
        if node is None:
            return False
        names: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.append(child.id.lower())
            elif isinstance(child, ast.Attribute):
                names.append(child.attr.lower())
        joined = ' '.join(names)
        return any(token in joined for token in ('admin', 'reviewer', 'receipt_chat', 'receipt_target')) or any(n in {'aid'} for n in names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._function_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._function_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._function_stack.pop()

    def _entry(self, node: ast.AST, *, kind: str = 'message', symbol: str = '') -> None:
        default, placeholders = self._resolved_template(node)
        if default is None or not _looks_user_facing(default):
            return
        line = int(getattr(node, 'lineno', 0) or 0)
        # If a referenced variable resolved to its definition, report the definition line where possible.
        if isinstance(node, ast.Name):
            bound = self._binding_for(node.id, node)
            if bound is not None:
                line = int(getattr(bound, 'lineno', line) or line)
                symbol = symbol or node.id
        local_id = (default, line, kind)
        if local_id in self._seen_local:
            return
        self._seen_local.add(local_id)
        rel = str(self.path.relative_to(self.root)).replace('\\', '/')
        digest = hashlib.sha1(default.encode('utf-8')).hexdigest()[:18]
        self.entries.append(TextEntry(
            key=CUSTOM_PREFIX + digest,
            default=default,
            category=self.category,
            section=_section_for(self.path, self.current_function, symbol),
            kind=kind,
            source=rel,
            line=line,
            symbol=symbol,
            placeholders=placeholders,
        ))

    def _semantic_assignment(self, symbol: str, value: ast.AST | None) -> None:
        if self._admin_only_function():
            return
        if not symbol or not self.SEMANTIC_SYMBOL.search(symbol):
            return
        kind = 'button' if ('BTN_' in symbol.upper() or 'BUTTON' in symbol.upper() or 'KEYBOARD' in symbol.upper()) else 'message'
        for text_node in _nested_string_nodes(value):
            self._entry(text_node, kind=kind, symbol=symbol)

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._semantic_assignment(target.id, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if isinstance(node.target, ast.Name):
            self._semantic_assignment(node.target.id, node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        fn = ''
        if isinstance(node.func, ast.Name):
            fn = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fn = node.func.attr

        if self._admin_only_function():
            self.generic_visit(node)
            return

        generic_target_is_admin = bool(
            fn in {'send_message', 'send_photo', 'send_document', 'send_video', 'send_animation'}
            and node.args
            and self._recipient_looks_admin(node.args[0])
        )
        current_fn = self.current_function.lower()
        admin_interaction_call = bool(
            any(token in current_fn for token in ('approve', 'reject'))
            and fn in {'answer', 'edit_or_answer', 'ui_message', 'ui_callback_message', 'safe_callback_answer'}
        )

        if fn in self.BUTTON_CALLS or fn == 'button':
            # InlineKeyboardBuilder/ReplyKeyboardBuilder .button(text=...) and normal Telegram buttons.
            for kw in node.keywords:
                if kw.arg == 'text':
                    self._entry(kw.value, kind='button')
            if fn in self.BUTTON_CALLS and node.args:
                self._entry(node.args[0], kind='button')

        if fn == 'append' and node.args and isinstance(node.func, ast.Attribute):
            target = node.func.value
            target_name = target.id.lower() if isinstance(target, ast.Name) else ''
            if target_name in {'lines', 'parts', 'chunks', 'message_lines', 'caption_lines', 'text_lines'}:
                self._entry(node.args[0], kind='message', symbol=target_name)

        if fn in self.MESSAGE_CALLS and not generic_target_is_admin and not admin_interaction_call:
            for kw in node.keywords:
                if kw.arg in {'text', 'caption'}:
                    self._entry(kw.value, kind='message')
            if node.args:
                # Bound methods such as message.answer(text) use index 0.
                # bot.send_message(chat_id, text) and helpers with target first use index 1.
                if fn in {'send_message', 'edit_message_text', 'send_photo', 'send_document', 'send_video', 'send_animation'} and len(node.args) > 1:
                    index = 1
                elif fn in {'edit_or_answer', 'ui_message', 'ui_callback_message', 'ui_page', '_safe_send_start_page'} and len(node.args) > 1:
                    index = 1
                else:
                    index = 0
                if index < len(node.args):
                    self._entry(node.args[index], kind='message')
        self.generic_visit(node)


def _source_files() -> list[Path]:
    """Only scan surfaces that can produce content visible to a normal bot user."""
    root = Path(__file__).resolve().parents[2]
    app = root / 'app'
    candidates: list[Path] = []

    explicit = [
        app / 'bot' / 'handlers' / 'start.py',
        app / 'bot' / 'keyboards' / 'common.py',
        app / 'bot' / 'service_presenter.py',
        app / 'bot' / 'profile_delivery.py',
        app / 'bot' / 'renewal_delivery.py',
        app / 'bot' / 'utils.py',
        app / 'jobs' / 'service_alerts.py',
        app / 'jobs' / 'service_cleanup.py',
        app / 'services' / 'referral_service.py',
    ]
    candidates.extend(path for path in explicit if path.exists())

    public_root = app / 'bot' / 'handlers' / 'public'
    if public_root.exists():
        candidates.extend(sorted(public_root.glob('*.py')))

    # Keep stable order and never scan admin/web/database/internal service modules.
    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        if path.name == '__init__.py' or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result

def build_catalog(force: bool = False) -> list[TextEntry]:
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache
    root = Path(__file__).resolve().parents[2]
    by_default: dict[str, TextEntry] = {}
    for path in _source_files():
        try:
            source = path.read_text(encoding='utf-8')
            tree = ast.parse(source, filename=str(path))
        except Exception:
            continue
        visitor = _CatalogVisitor(path, root, tree)
        visitor.visit(tree)
        for entry in visitor.entries:
            current = by_default.get(entry.default)
            # Prefer explicit button/default symbols over anonymous fragments.
            if current is None or (entry.symbol and not current.symbol) or (entry.kind == 'button' and current.kind != 'button'):
                by_default[entry.default] = entry
    _catalog_cache = sorted(by_default.values(), key=lambda e: (e.category, e.section, e.kind != 'button', e.source, e.line, e.default))
    return _catalog_cache


def catalog_by_key() -> dict[str, TextEntry]:
    return {entry.key: entry for entry in build_catalog()}


def legacy_setting_key(entry: TextEntry) -> str | None:
    if entry.symbol == 'WELCOME_TEXT_DEFAULT':
        return 'welcome_text'
    if entry.symbol == 'RULES_TEXT_DEFAULT':
        return 'rules_text'
    try:
        from app.bot.keyboards.common import BUTTON_DEFAULTS, button_text_key
        for name, (default_text, _enabled) in BUTTON_DEFAULTS.items():
            if str(default_text) == entry.default:
                return button_text_key(name)
    except Exception:
        pass
    return None


def legacy_enabled_key(entry: TextEntry) -> str | None:
    try:
        from app.bot.keyboards.common import BUTTON_DEFAULTS, button_enabled_key
        for name, (default_text, _enabled) in BUTTON_DEFAULTS.items():
            if str(default_text) == entry.default:
                return button_enabled_key(name)
    except Exception:
        pass
    return None


async def _load_overrides() -> dict[str, str]:
    global _override_cache, _override_cache_until
    now = time.monotonic()
    if _override_cache_until > now:
        return dict(_override_cache)
    async with _override_lock:
        now = time.monotonic()
        if _override_cache_until <= now:
            async with SessionLocal() as session:
                rows = (await session.execute(select(Setting).where(Setting.key.like(CUSTOM_PREFIX + '%')))).scalars().all()
                _override_cache = {str(row.key): str(row.value or '') for row in rows if str(row.value or '')}
            _override_cache_until = time.monotonic() + _CACHE_TTL
    return dict(_override_cache)


@lru_cache(maxsize=4096)
def _template_pattern(template: str) -> tuple[re.Pattern[str] | None, list[str]]:
    names: list[str] = []
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', template):
        parts.append(re.escape(template[pos:match.start()]))
        name = match.group(1)
        if name in names:
            parts.append(f'(?P={name})')
        else:
            names.append(name)
            parts.append(f'(?P<{name}>.*?)')
        pos = match.end()
    if not names:
        return None, []
    parts.append(re.escape(template[pos:]))
    try:
        return re.compile('^' + ''.join(parts) + '$', re.DOTALL), names
    except re.error:
        return None, []


def _apply_template(custom: str, values: dict[str, str]) -> str:
    result = custom
    for name, value in values.items():
        result = result.replace('{' + name + '}', value)
    return result


async def customize_text(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return value
    overrides = await _load_overrides()
    if not overrides:
        return value
    catalog = catalog_by_key()
    active = [(catalog[k], v) for k, v in overrides.items() if k in catalog and v]
    active.sort(key=lambda pair: len(pair[0].default), reverse=True)

    # Exact/static and rendered-template matches first.
    for entry, custom in active:
        if value == entry.default:
            return custom
        pattern, names = _template_pattern(entry.default)
        if pattern and names:
            match = pattern.match(value)
            if match:
                return _apply_template(custom, {name: match.group(name) for name in names})

    # Then replace customized default fragments inside a larger composed message.
    result = value
    for entry, custom in active:
        default = entry.default
        if len(default.strip()) >= 4 and default in result:
            result = result.replace(default, custom)
    return result


async def _transform_button(button: Any) -> Any:
    text = getattr(button, 'text', None)
    if not isinstance(text, str):
        return button
    new_text = await customize_text(text)
    if new_text == text:
        return button
    if hasattr(button, 'model_copy'):
        return button.model_copy(update={'text': new_text})
    try:
        button.text = new_text
    except Exception:
        pass
    return button


async def _transform_markup(markup: Any) -> Any:
    if markup is None:
        return markup
    updates: dict[str, Any] = {}
    for field in ('inline_keyboard', 'keyboard'):
        rows = getattr(markup, field, None)
        if not rows:
            continue
        new_rows = []
        changed = False
        for row in rows:
            new_row = []
            for button in row:
                new_button = await _transform_button(button)
                changed = changed or (new_button is not button)
                new_row.append(new_button)
            new_rows.append(new_row)
        if changed:
            updates[field] = new_rows
    if not updates:
        return markup
    if hasattr(markup, 'model_copy'):
        return markup.model_copy(update=updates)
    for key, val in updates.items():
        try:
            setattr(markup, key, val)
        except Exception:
            pass
    return markup


async def customize_method(method: Any) -> Any:
    updates: dict[str, Any] = {}
    for field in ('text', 'caption'):
        value = getattr(method, field, None)
        if isinstance(value, str) and value:
            new_value = await customize_text(value)
            if new_value != value:
                updates[field] = new_value
    markup = getattr(method, 'reply_markup', None)
    if markup is not None:
        new_markup = await _transform_markup(markup)
        if new_markup is not markup:
            updates['reply_markup'] = new_markup
    if not updates:
        return method
    if hasattr(method, 'model_copy'):
        return method.model_copy(update=updates)
    for key, val in updates.items():
        try:
            setattr(method, key, val)
        except Exception:
            pass
    return method


class CustomizableBot(Bot):
    """Bot subclass that applies Admin Web > Custom text overrides to outgoing UI text."""

    async def __call__(self, method: Any, request_timeout: int | None = None) -> Any:
        try:
            method = await customize_method(method)
        except Exception:
            # Customization must never block a real Telegram action.
            pass
        return await super().__call__(method, request_timeout=request_timeout)
