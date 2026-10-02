from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MultiVendorAndResellerRegressionTests(unittest.TestCase):
    def test_public_plus_reseller_server_scope_is_valid_for_resellers(self) -> None:
        reseller = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
        admin = (ROOT / 'app/bot/handlers/admin/resellers.py').read_text('utf-8')
        api = (ROOT / 'app/api/admin_web.py').read_text('utf-8')
        frontend = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text('utf-8')
        self.assertIn("in {'reseller', 'all'}", reseller)
        self.assertIn("in {'reseller', 'all'}", admin)
        self.assertIn("not in {'reseller', 'all'}", api)
        self.assertIn("server.scope === 'reseller' || server.scope === 'all'", frontend)

    def test_payment_card_has_vendor_reviewer_and_orders_snapshot_it(self) -> None:
        models = (ROOT / 'app/database/models/core.py').read_text('utf-8')
        buy = (ROOT / 'app/bot/handlers/public/buy.py').read_text('utf-8')
        renew = (ROOT / 'app/bot/handlers/public/my_services.py').read_text('utf-8')
        web = (ROOT / 'frontend/components/admin-dashboard.tsx').read_text('utf-8')
        self.assertIn('reviewer_telegram_id', models)
        self.assertIn('receipt_reviewer_telegram_id', models)
        self.assertIn('payment_card_id=card.id', buy)
        self.assertIn('receipt_reviewer_telegram_id=_positive_telegram_id', buy)
        self.assertIn('payment_card_id=card.id', renew)
        self.assertIn('receipt_reviewer_telegram_id=', renew)
        self.assertIn('Server owner / receipt reviewer Telegram ID', web)

    def test_only_assigned_vendor_or_main_admin_can_review_receipt(self) -> None:
        buy = (ROOT / 'app/bot/handlers/public/buy.py').read_text('utf-8')
        tree = ast.parse(buy)
        function_names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn('can_review_order', function_names)
        self.assertIn('order_receipt_targets', function_names)
        self.assertGreaterEqual(buy.count('can_review_order('), 4)
        self.assertIn('شما مسئول تایید این سفارش نیستید.', buy)
        self.assertIn('شما مسئول بررسی این سفارش نیستید.', buy)

    def test_reseller_creation_asks_and_applies_hwid_limit(self) -> None:
        states = (ROOT / 'app/bot/states/public_states.py').read_text('utf-8')
        reseller = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
        self.assertIn('hwid_limit = State()', states)
        self.assertIn('این کانفیگ چند کاربره باشد؟', reseller)
        self.assertIn('عدد 0 را وارد کنید', reseller)
        self.assertIn('عدد از 1 تا 10', reseller)
        self.assertIn('limit_hwid=hwid_limit', reseller)
        self.assertIn("'hwid_limit': hwid_limit", reseller)

    def test_reseller_user_facing_custom_name_text_uses_config_name(self) -> None:
        reseller = (ROOT / 'app/bot/handlers/public/reseller.py').read_text('utf-8')
        self.assertNotIn('اسم اختصاصی', reseller)
        self.assertIn('اسم کانفیگ مشتری', reseller)
        self.assertIn('👤 اسم کانفیگ:', reseller)


if __name__ == '__main__':
    unittest.main()
