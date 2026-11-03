from pathlib import Path


def test_backup_delivery_uses_new_document_messages_only() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    start = source.index('async def _telegram_send_backup')
    end = source.index('async def _restore_backup_payload', start)
    sender = source[start:end]
    assert '/sendDocument' in sender
    assert 'editMessage' not in sender


def test_destination_test_sends_a_fresh_text_message_each_time() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    validator_start = source.index('async def _telegram_validate_destination')
    validator_end = source.index('async def _telegram_send_backup', validator_start)
    validator = source[validator_start:validator_end]
    assert '/sendMessage' in validator
    assert 'Fresh test message' in validator
    assert "datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')" in validator

    start = source.index("@router.post('/admin/backup/test')")
    end = source.index("@router.post('/admin/backup/run')", start)
    endpoint = source[start:end]
    assert 'send_test=True' in endpoint
    assert 'await _telegram_validate_destination(' in endpoint


def test_backup_save_validates_channel_or_group_admin_access() -> None:
    source = Path('app/api/admin_web.py').read_text(encoding='utf-8')
    start = source.index("@router.post('/admin/backup/save')")
    end = source.index("@router.post('/admin/backup/test')", start)
    endpoint = source[start:end]
    assert "destination in {'channel', 'group'}" in endpoint
    assert 'send_test=False' in endpoint
    assert 'await _telegram_validate_destination(' in endpoint


def test_scheduled_backup_job_is_registered_and_interval_based() -> None:
    main_source = Path('app/main.py').read_text(encoding='utf-8')
    job_source = Path('app/jobs/backup_delivery.py').read_text(encoding='utf-8')
    assert 'deliver_scheduled_backup' in main_source
    assert "id='scheduled_backup_delivery'" in main_source
    assert 'await _telegram_send_backup(' in job_source
    assert 'backup_interval_minutes' in job_source
    assert 'backup_last_scheduled_at' in job_source
    assert 'timedelta(minutes=interval_minutes)' in job_source


def test_private_channel_can_be_detected_from_new_channel_post() -> None:
    source = Path('app/bot/handlers/admin/settings.py').read_text(encoding='utf-8')
    assert '@router.channel_post()' in source
    assert "'backup_chat_id': detected_id" in source
    assert 'never edits or deletes the channel post' in source
