from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'app/main.py').read_text(encoding='utf-8')
TICKETS = (ROOT / 'app/bot/handlers/public/tickets.py').read_text(encoding='utf-8')
STATES = (ROOT / 'app/bot/states/public_states.py').read_text(encoding='utf-8')


def test_ticket_callbacks_bypass_stale_proactive_message_guard():
    assert "'ticket:'" in MAIN
    assert "'ticket_user:'" in MAIN
    assert "'ticket_admin:'" in MAIN
    assert "'menu:tickets'" in MAIN


def test_ticket_reply_uses_dedicated_shared_reply_state():
    assert 'class TicketReply(StatesGroup):' in STATES
    assert '@router.message(TicketReply.message)' in TICKETS
    assert "ticket_reply_role='user'" in TICKETS
    assert "ticket_reply_role='admin'" in TICKETS


def test_reply_buttons_create_fresh_active_prompt():
    assert 'async def user_reply_start' in TICKETS
    assert 'async def admin_reply_start' in TICKETS
    # Both proactive admin/user reply paths must use a fresh tracked UI prompt.
    section = TICKETS[TICKETS.index('async def user_reply_start'):TICKETS.index('@router.message(TicketReply.message)')]
    assert section.count('await send_single_message(') == 2


def test_user_ticket_actions_enforce_ownership():
    assert 'async def _owned_ticket' in TICKETS
    assert 'ticket.user_id != user.id' in TICKETS
    assert "متعلق به حساب شما نیست" in TICKETS
    # View, reply and close all use the ownership helper.
    assert TICKETS.count('_owned_ticket(session, callback.from_user.id, tid)') >= 3


def test_ticket_home_message_is_marked_active():
    assert 'async def send_home' in TICKETS
    assert 'remember_ui_message(sent.chat.id, sent.message_id)' in TICKETS


def test_reply_commit_is_role_checked_before_delivery():
    assert "if role == 'admin':" in TICKETS
    assert 'message.from_user.id not in settings.admin_ids' in TICKETS
    assert "elif role == 'user':" in TICKETS
    assert 'current_user.id != ticket.user_id' in TICKETS
    assert 'await state.clear()' in TICKETS


def test_closed_ticket_cannot_be_replied_to():
    assert TICKETS.count("ticket.status != 'open'") >= 3
