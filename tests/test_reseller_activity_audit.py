from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_renewal_has_stable_operation_id_and_duplicate_guard():
    source = text('app/bot/handlers/public/reseller.py')
    assert "operation_id=uuid.uuid4().hex" in source
    assert "renew_event_key = f'renew:{sid}:op:{operation_id}'" in source
    assert "existing_success" in source
    guard_pos = source.index("existing_success")
    settle_pos = source.index("released_bytes = await refund_unused_volume", guard_pos)
    assert guard_pos < settle_pos
    assert "هیچ حجم اضافه‌ای دوباره از سهمیه شما کم نشد" in source


def test_failed_create_and_renew_are_persisted_after_rollback():
    source = text('app/bot/handlers/public/reseller.py')
    assert "action='create_failed'" in source
    assert "action='renew_failed'" in source
    assert "'quota_before_bytes'" in source
    assert "'quota_after_bytes'" in source
    assert "'error_type'" in source
    assert "'error_message'" in source
    assert "'rolled_back': True" in source


def test_topup_is_idempotent_and_audited():
    source = text('app/services/reseller_service.py')
    assert "if str(request.status or '').lower() == 'approved':" in source
    assert "action='topup'" in source
    assert "event_key = f'topup:{request.id}'" in source
    assert "'added_bytes': added_bytes" in source
    assert "'quota_before_bytes': before_total" in source
    assert "'quota_after_bytes': after_total" in source


def test_admin_topup_approval_locks_request_row():
    source = text('app/bot/handlers/admin/resellers.py')
    assert "ResellerTopupRequest.id == req_id).with_for_update()" in source
    assert "source='admin_topup_approval'" in source


def test_reseller_list_exposes_detailed_accounting_and_errors():
    api = text('app/api/admin_web.py')
    ui = text('frontend/components/admin-dashboard.tsx')
    for field in (
        'added_bytes', 'deducted_bytes', 'quota_before_bytes', 'quota_after_bytes',
        'quota_delta_bytes', 'error_type', 'error_message', 'failure_stage',
    ):
        assert f"'{field}'" in api
    assert 'Quota Recharged' in api
    assert 'Renew Failed' in api
    assert 'Create Failed' in api
    assert 'Deducted from reseller quota:' in ui
    assert 'Quota before:' in ui
    assert 'Remaining after operation:' in ui
    assert 'activity-order-error' in ui


def test_create_and_renew_freeze_exact_remaining_quota_snapshot():
    source = text('app/bot/handlers/public/reseller.py')
    assert source.count("'quota_snapshot_version': 2") >= 2
    assert source.count("'quota_remaining_after_bytes': quota_after_bytes") >= 2
    assert "quota_after_bytes = int(remaining_bytes(reseller))" in source
    assert 'same_size_capacity' not in source
    assert 'same_size_volume_bytes' not in source


def test_reseller_list_shows_only_exact_remaining_quota_inside_activity_card():
    api = text('app/api/admin_web.py')
    ui = text('frontend/components/admin-dashboard.tsx')
    assert "'quota_remaining_after_bytes'" in api
    assert "'quota_snapshot_version'" in api
    assert 'Remaining after this operation' in ui
    assert 'Reseller quota before' in ui
    assert 'Quota purchased' in ui
    assert 'Volume added to service' in ui
    assert 'Can create again' not in ui
    assert 'Needed for one more' not in ui
    assert 'same_size_capacity' not in api
    assert 'same_size_volume_bytes' not in api


def test_quota_affecting_activity_cards_keep_a_simple_remaining_snapshot():
    source = text('app/bot/handlers/public/reseller.py')
    ui = text('frontend/components/admin-dashboard.tsx')
    assert source.count("'quota_remaining_after_bytes':") >= 4
    assert 'Volume added to service' in ui
    assert 'Days added to service' in ui
    assert 'Remaining after this operation' in ui
    assert 'Can create again' not in ui
    assert 'Needed for one more' not in ui
