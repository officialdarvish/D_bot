from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _pure_functions():
    source = (ROOT / 'app/jobs/revenue_cycle_summary.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {'_parse_utc', '_localize_utc', '_cycle_containing', '_is_aligned_cycle_end', '_summary_text'}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    env = {
        'datetime': datetime,
        'timedelta': timedelta,
        'timezone': timezone,
        'ZoneInfo': __import__('zoneinfo').ZoneInfo,
        'settings': SimpleNamespace(TZ='Asia/Tehran'),
        'fa_datetime': lambda value: value.strftime('%Y/%m/%d %H:%M'),
        'CYCLE_DAYS': 30,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), '<cycle-summary>', 'exec'), env)
    return env


def test_cycle_math_and_alignment():
    env = _pure_functions()
    anchor = datetime(2026, 9, 1, 0, 0)
    start, end = env['_cycle_containing'](anchor, datetime(2026, 10, 2, 0, 0))
    assert start == anchor + timedelta(days=30)
    assert end == anchor + timedelta(days=60)
    assert env['_is_aligned_cycle_end'](anchor, anchor + timedelta(days=30)) is True
    assert env['_is_aligned_cycle_end'](anchor, anchor + timedelta(days=29)) is False


def test_summary_message_contains_requested_period_count_and_total():
    env = _pure_functions()
    text = env['_summary_text'](datetime(2026, 9, 1), datetime(2026, 10, 1), 12, 4_250_000)
    assert 'گزارش پایان دوره ۳۰ روزه فروش' in text
    assert 'شروع دوره' in text
    assert 'پایان دوره' in text
    assert '12' in text
    assert '4,250,000 تومان' in text


def test_scheduler_and_primary_owner_delivery_are_wired():
    main = (ROOT / 'app/main.py').read_text(encoding='utf-8')
    job = (ROOT / 'app/jobs/revenue_cycle_summary.py').read_text(encoding='utf-8')
    api = (ROOT / 'app/api/admin_web.py').read_text(encoding='utf-8')
    assert 'deliver_revenue_cycle_summary' in main
    assert "id='revenue_cycle_summary'" in main
    assert 'minutes=10' in main
    assert 'primary_owner_id = owner_ids[0]' in job
    assert 'Order.amount_irt > 0' in job
    assert "dashboard_revenue_summary_next_end_utc" in job
    assert 'summary_next_value = (now + timedelta(days=DASHBOARD_REVENUE_CYCLE_DAYS)).isoformat()' in api
