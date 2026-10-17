from pathlib import Path


def test_private_message_confirmation_is_registered_as_active_ui():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'bot' / 'handlers' / 'admin' / 'settings.py').read_text()
    assert 'confirmation = await message.answer(' in source
    assert 'remember_ui_message(confirmation.chat.id, confirmation.message_id)' in source
    assert 'await delete_active_ui_message(message.bot, message.chat.id, exclude_message_id=message.message_id)' in source
