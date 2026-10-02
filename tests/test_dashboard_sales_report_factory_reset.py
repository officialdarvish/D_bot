from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
import unittest

os.environ.setdefault('BOT_TOKEN', '123456789:AA_TestTokenForUnitTests_1234567890')
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://dbot:test@localhost:5432/dbot')
os.environ.setdefault('FERNET_KEY', 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=')

from app.services.sales_report import build_accounting_sales_pdf

ROOT = Path(__file__).resolve().parents[1]


class DashboardSalesReportFactoryResetTests(unittest.TestCase):
    def test_accounting_pdf_is_generated(self) -> None:
        now = datetime.utcnow()
        daily = []
        for i in range(30):
            d = now - timedelta(days=29-i)
            daily.append({'date': d.date().isoformat(), 'label': d.strftime('%b %d'), 'sales': (i % 5) * 125000})
        payload = {
            'range_label': f'{(now-timedelta(days=30)).date()} to {now.date()}',
            'total_revenue': 2_400_000, 'order_count': 7, 'avg_order': 342_857, 'daily': daily,
            'plan_summary': [{'plan':'VIP 20GB / 30 Days','count':4,'revenue':1_400_000,'volume_gb':20,'duration_days':30}],
            'payment_summary': [{'payment':'card_to_card','count':7,'revenue':2_400_000}],
            'rows': [{'order':'#1','date':now.strftime('%Y-%m-%d %H:%M'),'user':'Test User','plan':'VIP 20GB / 30 Days','payment':'card_to_card','amount':'500,000 Toman'}],
        }
        pdf = build_accounting_sales_pdf(payload)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertGreater(len(pdf), 2000)

    def test_dashboard_ui_requested_changes_present(self) -> None:
        src = (ROOT/'frontend/components/admin-dashboard.tsx').read_text(encoding='utf-8')
        self.assertNotIn('RecentActivities', src)
        self.assertIn('index % 3 === 0', src)
        self.assertIn('Reset Display', src)
        self.assertIn('Send Sales Report Now', src)
        self.assertIn('Factory Reset', src)
        self.assertIn("daysAgoIso(29)", src)

    def test_scroll_fixes_and_plans_sidebar_behavior_present(self) -> None:
        css = (ROOT/'frontend/app/globals.css').read_text(encoding='utf-8')
        self.assertIn('.shell.section-plans .sidebar', css)
        self.assertIn('position:relative!important', css)
        self.assertIn('overflow-y:visible!important', css)
        self.assertIn('overscroll-behavior-y:auto', css)

    def test_monthly_job_and_factory_reset_endpoints_present(self) -> None:
        main = (ROOT/'app/main.py').read_text(encoding='utf-8')
        api = (ROOT/'app/api/admin_web.py').read_text(encoding='utf-8')
        self.assertIn('deliver_monthly_sales_report', main)
        self.assertIn("id='monthly_sales_report_delivery'", main)
        self.assertIn("@router.post('/admin/reports/monthly-sales/run')", api)
        self.assertIn("@router.post('/admin/settings/factory-reset')", api)
        self.assertIn("initial_setup_done", api)


if __name__ == '__main__':
    unittest.main()
