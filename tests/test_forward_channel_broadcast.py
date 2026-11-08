"""Dependency-free regression tests for channel-post forwarding wiring."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEYBOARDS = (ROOT / 'app/bot/keyboards/common.py').read_text('utf-8')
HANDLERS = (ROOT / 'app/bot/handlers/admin/settings.py').read_text('utf-8')
STATES = (ROOT / 'app/bot/states/admin_states.py').read_text('utf-8')


class ForwardBroadcastTests(unittest.TestCase):
    def test_menu_exposes_forward_feature(self):
        self.assertIn("CB_FORWARD_BROADCAST = 'admin:forward_broadcast'", KEYBOARDS)
        self.assertIn('callback_data=CB_FORWARD_BROADCAST', KEYBOARDS)

    def test_state_and_channel_origin_validation(self):
        self.assertIn('class ForwardBroadcastFlow(StatesGroup):', STATES)
        self.assertIn('ForwardBroadcastFlow.channel_post', HANDLERS)
        self.assertIn("origin_type != 'channel'", HANDLERS)
        self.assertIn('message.has_protected_content', HANDLERS)
        self.assertIn('forward_origin_chat_id', HANDLERS)
        self.assertIn('forward_origin_message_id', HANDLERS)

    def test_uses_actual_forward_and_separate_restart_keyboard(self):
        tree = ast.parse(HANDLERS)
        methods = {node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
        self.assertIn('_forward_with_flood_wait', methods)
        self.assertIn('_forward_with_source_fallback', methods)
        self.assertIn('run_forward_broadcast', methods)
        forward_source = ast.get_source_segment(HANDLERS, methods['_forward_with_flood_wait'])
        fallback_source = ast.get_source_segment(HANDLERS, methods['_forward_with_source_fallback'])
        broadcast_source = ast.get_source_segment(HANDLERS, methods['run_forward_broadcast'])
        self.assertIn('bot.forward_message(', forward_source)
        self.assertNotIn('copy_message(', forward_source)
        self.assertIn('fallback_chat_id', fallback_source)
        self.assertIn("callback_data='restart:start'", broadcast_source)
        self.assertIn('bot.send_message(user_id', broadcast_source)
        self.assertIn('dict.fromkeys', broadcast_source)

    def test_confirmation_does_not_self_forward_admin_copy(self):
        tree = ast.parse(HANDLERS)
        method = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == 'forward_broadcast_send'
        )
        source = ast.get_source_segment(HANDLERS, method)
        self.assertIn('Never preflight the admin-forwarded copy back into the exact same private', source)
        self.assertIn("data.get('forward_origin_chat_id')", source)
        self.assertIn('fallback_chat_id=fallback_chat', source)
        self.assertIn('await state.clear()', source)
        self.assertNotIn("await callback.answer('فوروارد این پست ممکن نیست؛ پست دیگری ارسال کنید.'", source)


if __name__ == '__main__':
    unittest.main()
