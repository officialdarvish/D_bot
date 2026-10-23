"""Regression tests for fully identified pending receipts and paid-order notices."""
import asyncio
import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _code(path):
    return (ROOT / path).read_text(encoding='utf-8')


def test_receipt_details_include_identity_item_amount_and_utc_date():
    code = _code('app/bot/handlers/admin/pending_receipts.py')
    assert 'order_summary(order, user, plan, server, service' in code
    assert "date_label(order.created_at)" in code
    assert '🆔 یوزرنیم تلگرام' in code
    assert '🔢 آیدی عددی' in code
    assert '🧾' in code and '💰 مبلغ' in code
    assert "plan.title" in code and "package.title" in code
    assert "[InlineKeyboardButton(text='🔄 بروزرسانی', callback_data='pending_receipts:list')]" in code
    assert "rows.append([back_button('back:main')])" in code
    assert "callback_data='pending_receipts:list'" in code


def test_payment_notifications_cover_all_paid_paths_and_only_after_commit():
    cases = {
        'app/bot/handlers/public/buy.py': ['await notify_paid_order(callback.message.bot, paid_order_id',
                                                'await notify_paid_order(bot, order_id'],
        'app/bot/handlers/public/my_services.py': ['await notify_paid_order(callback.message.bot, renewed_order.id',
                                                       'await notify_paid_order(callback.message.bot, order_discount.id'],
        'app/bot/handlers/public/account.py': ["await notify_paid_order(callback.message.bot, oid"],
        'app/api/main.py': ['await notify_paid_order(bot, order.id'],
        'app/bot/handlers/admin/resellers.py': ['await notify_receipt_review(callback.message.bot, summary'],
        'app/bot/handlers/admin/panel_reseller_sale.py': ['await notify_receipt_review(callback.message.bot, summary'],
    }
    for file, needles in cases.items():
        content = _code(file)
        for n in needles:
            assert n in content, f'{file}: {n}'
    # Don't leak user-selected connection passwords to an admin receipt.
    assert "f'🔐 پسورد انتخابی: {data.get(" not in _code('app/bot/handlers/public/buy.py')
    # No automatic debug text or bot tokens in the audit payload.
    assert 'password' not in _code('app/bot/payment_audit.py')[_code('app/bot/payment_audit.py').find('def order_summary'):]


def test_receipt_audit_formats_all_buyer_details_and_escapes_names():
    # Import only the audited pure functions (no aiogram/DB connection required).
    src = _code('app/bot/payment_audit.py')
    tree = ast.parse(src)
    picked = [x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
              and x.name in {'_text', 'date_label', 'payment_label', 'order_service_name', 'order_summary'}]
    ns = {'escape': __import__('html').escape, 'datetime': datetime,
          'Order': object, 'User': object, 'Plan': object, 'Server': object,
          'ClientService': object}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *picked], type_ignores=[])), '<audit>', 'exec'), ns)
    mock_order = SimpleNamespace(id=615, user_id=1, payment_method='card:Client123', amount_irt=60000,
                                 created_at=datetime(2026, 10, 18, 12, 20), status='waiting_receipt')
    mock_user = SimpleNamespace(full_name='Ali <Tester>', telegram_id=1234567, username='ali_123')
    mock_plan = SimpleNamespace(title='اقتصادی ۱۰ گیگ')
    mock_server = SimpleNamespace(name='Sanaei DE')
    summary = ns['order_summary'](mock_order, mock_user, mock_plan, mock_server)
    for fragment in ['#615', 'Ali &lt;Tester&gt;', '1234567', '@ali_123', 'اقتصادی ۱۰ گیگ',
                     'Client123', '60,000 تومان', '2026-10-18 12:20 UTC', 'Sanaei DE']:
        assert fragment in summary


def test_convert_button_is_only_on_selected_service():
    common = _code('app/bot/keyboards/common.py')
    services = _code('app/bot/handlers/public/my_services.py')
    assert "callback_data=f'svcconvert:source:{svc.id}'" in services
    start = common.index('async def main_menu_inline(')
    end = common.index('def admin_panel_inline()', start)
    assert "callback_data='menu:convert'" not in common[start:end]
