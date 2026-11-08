"""Regression checks: plan selection must not crash after a user row is removed."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUY_SOURCE = (ROOT / 'app/bot/handlers/public/buy.py').read_text(encoding='utf-8')


class BuyPlanRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(BUY_SOURCE)
        cls.handler = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'buy_plan')
        cls.code = ast.unparse(cls.handler)

    def test_missing_user_does_not_raise_no_result_found(self):
        self.assertIn('scalar_one_or_none()', self.code)
        self.assertIn('if user is None:', self.code)
        self.assertIn('get_or_create_user(callback)', self.code)

    def test_rules_cannot_be_bypassed_when_recovering_user(self):
        self.assertIn("get_setting_value('rules_enabled', '0')", self.code)
        self.assertIn('not user.accepted_rules', self.code)
        self.assertIn('rules_keyboard()', self.code)
        self.assertIn('await state.clear()', self.code)

    def test_unavailable_plan_or_server_is_handled(self):
        self.assertIn('if plan is None or not plan.is_active:', self.code)
        self.assertIn('if server is None or not server.is_active:', self.code)


if __name__ == '__main__':
    unittest.main()
