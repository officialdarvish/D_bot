from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_free_service_card_uses_persistent_report_home():
    source = (ROOT / 'app/bot/handlers/public/buy.py').read_text(encoding='utf-8')
    assert "reply_markup=report_home_inline()" in source
    assert "return report_home_inline()" in source


def test_service_presenter_preserves_custom_keyboard_and_merges_mikrotik_profile():
    source = (ROOT / 'app/bot/service_presenter.py').read_text(encoding='utf-8')
    assert 'markup = reply_markup' in source
    assert "rows.extend(list(getattr(reply_markup, 'inline_keyboard', []) or []))" in source
