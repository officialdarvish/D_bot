from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_private_message_is_delivered_with_user_reply_controls():
    text = (ROOT / 'app/bot/handlers/admin/settings.py').read_text()
    assert 'reply_markup=private_message_user_actions(callback.from_user.id)' in text
    assert "F.data.startswith('private_admin:reply:')" in text


def test_user_conversation_has_reply_and_end_buttons():
    text = (ROOT / 'app/bot/keyboards/common.py').read_text()
    assert "text='✍️ پاسخ به پیام'" in text
    assert "callback_data=f'private_chat:reply:{int(admin_id)}'" in text
    assert "text='✅ خاتمه گفتگو'" in text
    assert "callback_data='private_chat:end'" in text


def test_user_reply_is_forwarded_to_original_owner_and_can_be_answered_again():
    text = (ROOT / 'app/bot/handlers/public/private_messages.py').read_text()
    assert "F.data == 'private_chat:end'" in text
    assert '_open_main_menu_from_callback(callback, state, force_new_message=True)' in text
    assert 'PrivateMessageReply.message' in text
    assert 'private_message_admin_id' in text
    assert 'not is_owner(admin_id)' in text
    assert 'copy_message(' in text
    assert 'reply_markup=private_message_admin_actions(message.from_user.id)' in text
    assert 'await state.clear()' in text


def test_private_message_callbacks_bypass_stale_proactive_message_guard():
    text = (ROOT / 'app/main.py').read_text()
    assert "'private_chat:', 'private_admin:'," in text
    assert 'private_messages.router' in text
