"""Regression checks for persisted revenue cycles and Jalali month-end export.

The isolated AST tests are intentionally independent of network/Telegram credentials.
"""
from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def functions():
    source = (ROOT / 'app/api/admin_web.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('revenue_cycle', 'jalali_month_comparison', 'revenue_period_history')]
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    env = {'datetime': datetime, 'timedelta': timedelta, 'Any': object, 'settings': SimpleNamespace(TZ='Asia/Tehran'), 'DASHBOARD_REVENUE_CYCLE_DAYS': 30,
           'JALALI_MONTH_NAMES': ('فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند')}
    exec(compile(module, '<revenue-cycle>', 'exec'), env)
    return env


def test_reset_cycle_remains_persisted_for_30_days():
    cycle = functions()['revenue_cycle']
    anchor = datetime(2026, 9, 1, 12, 30)
    assert cycle(anchor, datetime(2026, 9, 30, 12, 29))[0] == anchor
    assert cycle(anchor, datetime(2026, 10, 1, 12, 30))[0] == anchor + timedelta(days=30)
    assert cycle(anchor, datetime(2026, 10, 31, 12, 30))[0] == anchor + timedelta(days=60)


def test_jalali_month_end_totals_and_comparison():
    aggregate = functions()['jalali_month_comparison']
    orders = [
        SimpleNamespace(created_at=datetime(2026, 9, 18), amount_irt=100, status='completed'),
        SimpleNamespace(created_at=datetime(2026, 9, 23), amount_irt=250, status='paid'),
        SimpleNamespace(created_at=datetime(2026, 9, 25), amount_irt=999, status='pending'),
    ]
    rows = aggregate(orders)
    assert len(rows) == 2
    assert [r['revenue'] for r in rows] == [100, 250]
    assert rows[0]['period'].endswith('شهریور 1405')
    assert rows[1]['period'].endswith('مهر 1405')
    assert rows[1]['change_percent'] == 150.0


def test_reset_and_export_wired_to_persistent_backend():
    api = (ROOT / 'app/api/admin_web.py').read_text(encoding='utf-8')
    ui = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text(encoding='utf-8')
    assert "@router.post('/admin/api/v2/dashboard/revenue-reset')" in api
    assert 'dashboard_revenue_anchor_utc' in api
    assert 'monthly_rows=monthly_rows' in api
    assert "submitForm('/admin/api/v2/dashboard/revenue-reset', {})" in ui
    assert 'Export All Months' in ui
    assert 'Export Selected Dates' in ui
    assert 'displayReset' not in ui


def test_period_history_preserves_manual_reset_and_automatic_cycles():
    history = functions()['revenue_period_history']
    a = datetime(2026, 1, 1)
    orders = [SimpleNamespace(created_at=a + timedelta(days=2), amount_irt=100, status='paid'),
              SimpleNamespace(created_at=a + timedelta(days=20), amount_irt=200, status='completed'),
              SimpleNamespace(created_at=a + timedelta(days=33), amount_irt=300, status='paid'),
              SimpleNamespace(created_at=a + timedelta(days=46), amount_irt=999, status='pending')]
    rows = history(orders, a, a + timedelta(days=66), [a + timedelta(days=40)])
    assert [r['revenue'] for r in rows] == [300, 300, 0]
    assert rows[1]['change_percent'] == 0.0
    assert len(rows) == 3
    assert rows[0]['period'].startswith('2026-01-01')


def test_month_gap_zero_sales_appears_in_export():
    aggregate = functions()['jalali_month_comparison']
    orders = [SimpleNamespace(created_at=datetime(2026, 9, 18), amount_irt=100, status='paid'),
              SimpleNamespace(created_at=datetime(2026, 11, 10), amount_irt=200, status='paid')]
    rows = aggregate(orders)
    assert len(rows) == 3
    assert [r['revenue'] for r in rows] == [100, 0, 200]


def test_tehran_month_boundary_used_for_export():
    aggregate = functions()['jalali_month_comparison']
    # This UTC timestamp is already the next Jalali month in Tehran.
    orders = [SimpleNamespace(created_at=datetime(2026, 9, 22, 22, 30), amount_irt=50, status='paid')]
    rows = aggregate(orders)
    assert len(rows) == 1
    assert 'مهر 1405' in rows[0]['period']
