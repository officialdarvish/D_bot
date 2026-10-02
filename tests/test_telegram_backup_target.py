from app.services.telegram_target import (
    is_private_invite_link,
    normalize_telegram_target,
    resolve_telegram_target,
)


def test_public_channel_link_is_normalized() -> None:
    assert normalize_telegram_target('channel', 'https://t.me/example_channel') == '@example_channel'
    assert normalize_telegram_target('channel', 'https://t.me/example_channel/42') == '@example_channel'


def test_private_channel_post_link_is_converted_to_bot_api_chat_id() -> None:
    assert normalize_telegram_target('channel', 'https://t.me/c/1234567890/25') == '-1001234567890'
    assert normalize_telegram_target('group', 't.me/c/99887766/4?single') == '-10099887766'


def test_numeric_chat_id_is_preserved() -> None:
    assert normalize_telegram_target('channel', '-1001234567890') == '-1001234567890'


def test_private_invite_link_is_detected_and_not_misparsed() -> None:
    invite = 'https://t.me/+AbCdEf123456'
    assert normalize_telegram_target('channel', invite) == invite
    assert is_private_invite_link(invite)
    assert is_private_invite_link('https://t.me/joinchat/AbCdEf123456')


def test_bot_destination_uses_owner_default_when_empty() -> None:
    assert normalize_telegram_target('bot', '', default_bot_chat_id='1234') == '1234'


def test_private_invite_uses_auto_detected_channel_id() -> None:
    assert resolve_telegram_target(
        'channel',
        'https://t.me/+InviteCode',
        detected_chat_id='-100778899',
        detected_chat_type='channel',
    ) == '-100778899'


def test_detected_chat_type_must_match_destination() -> None:
    invite = 'https://t.me/+InviteCode'
    assert resolve_telegram_target(
        'channel',
        invite,
        detected_chat_id='-100778899',
        detected_chat_type='supergroup',
    ) == invite
