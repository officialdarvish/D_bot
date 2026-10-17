from pathlib import Path


def test_reseller_created_admin_notice_has_persistent_home_button():
    source = Path("app/bot/handlers/public/reseller.py").read_text(encoding="utf-8")
    assert "async def send_reseller_created_admin_notice" in source
    func = source.split("async def send_reseller_created_admin_notice", 1)[1].split("RESELLER_USERNAME_RE", 1)[0]
    assert "reply_markup=report_home_inline()" in func
    assert "callback_data='report:home'" in Path("app/bot/keyboards/common.py").read_text(encoding="utf-8")


def test_report_home_keeps_report_and_opens_new_main_menu():
    start = Path("app/bot/handlers/start.py").read_text(encoding="utf-8")
    block = start.split("async def persistent_report_home", 1)[1].split("async def profile_home_menu", 1)[0]
    assert "edit_reply_markup(reply_markup=None)" in block
    assert "force_new_message=True" in block
