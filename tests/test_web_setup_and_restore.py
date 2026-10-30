from pathlib import Path


def test_restore_models_include_reseller_username_counter_import() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    import_block = source[source.index('from app.database.models import'):source.index('from app.jobs.server_sync import')]
    assert 'ResellerUsernameCounter' in import_block
    models_start = source.index('def _backup_models():')
    models_end = source.index('def _backup_format', models_start)
    assert "('reseller_username_counters', ResellerUsernameCounter)" in source[models_start:models_end]


def test_web_setup_wizard_is_first_login_gate() -> None:
    admin = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    api = Path('app/api/main.py').read_text(encoding='utf-8')
    bot = Path('app/bot/handlers/start.py').read_text(encoding='utf-8')
    assert "@router.get('/setup'" in admin
    assert "@router.post('/setup/save'" in admin
    assert "initial_setup_done" in admin
    assert 'web_path_middleware' in api
    assert 'read_web_path' in api
    assert '_send_web_setup_required' in bot
    assert 'راه‌اندازی اولیه D BOT باید از وب‌پنل انجام شود' in bot


def test_web_setup_has_opt_in_for_forced_channel_and_rules() -> None:
    admin = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    assert 'name="force_join_enabled" value="1"' in admin
    assert 'name="force_join_enabled" value="0"' in admin
    assert 'name="rules_enabled" value="1"' in admin
    assert 'name="rules_enabled" value="0"' in admin
    defaults = Path('app/database/defaults.py').read_text(encoding='utf-8')
    assert "'force_join_enabled': '0'" in defaults
    assert "'rules_enabled': '0'" in defaults


def test_installer_supports_web_path() -> None:
    main_install = Path('install.sh').read_text(encoding='utf-8')
    assert 'Auto-generate a private Web Path?' in main_install
    assert 'WEB_PATH=${WEB_PATH}' in main_install
    assert 'PUBLIC_BASE_URL=' in main_install
