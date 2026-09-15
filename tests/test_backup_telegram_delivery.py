from pathlib import Path


def test_backup_delivery_uses_new_document_messages_only() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    start = source.index('async def _telegram_send_backup')
    end = source.index('async def _restore_backup_payload', start)
    sender = source[start:end]
    assert "/sendDocument" in sender
    assert "/sendMessage" not in sender
    assert "editMessage" not in sender


def test_destination_test_creates_a_real_portable_backup() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    start = source.index("@router.post('/admin/backup/test')")
    end = source.index("@router.post('/admin/backup/run')", start)
    test_endpoint = source[start:end]
    assert 'path = await _write_backup_file()' in test_endpoint
    assert 'await _telegram_send_backup(' in test_endpoint
    assert 'dbot_test_backup_' in test_endpoint


def test_scheduled_backup_job_is_registered() -> None:
    main_source = Path('app/main.py').read_text(encoding='utf-8')
    job_source = Path('app/jobs/backup_delivery.py').read_text(encoding='utf-8')
    assert 'deliver_scheduled_backup' in main_source
    assert "id='scheduled_backup_delivery'" in main_source
    assert 'await _telegram_send_backup(' in job_source
    assert 'backup_last_scheduled_date' in job_source


def test_private_channel_can_be_detected_from_new_channel_post() -> None:
    source = Path('app/bot/handlers/admin/settings.py').read_text(encoding='utf-8')
    assert '@router.channel_post()' in source
    assert "'backup_chat_id': detected_id" in source
    assert 'never edits or deletes the channel post' in source
