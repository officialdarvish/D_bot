"""Regression tests for category quotas, absolute expiry and conversion isolation."""
from datetime import datetime, timedelta

import pytest

from app.services.plan_conversion import GIB, normalize_rules, quote_conversion, parse_panel_expiry, format_volume


def test_economic_to_vip_quota_preserves_expiry():
    expires = datetime(2026, 10, 20, 12, 30)
    q = quote_conversion(8 * GIB, 6000, 14000, expires, datetime(2026, 10, 14, 12, 30))
    assert q['source_remaining_bytes'] == 8 * GIB
    assert q['destination_bytes'] == (8 * GIB * 6000) // 14000
    assert abs(q['destination_bytes'] / GIB - 3.428571) < 0.000001
    assert q['expires_at'] == expires
    assert q['remaining_seconds'] == 6 * 86400
    assert q['value_irt'] == '48000.00'


def test_quote_requires_positive_quota_and_expiry():
    expiry = datetime(2026, 10, 14, 12)
    for remaining, source_rate, dest_rate, expires in [
        (0, 6000, 14000, expiry + timedelta(days=1)),
        (GIB, 0, 14000, expiry + timedelta(days=1)),
        (GIB, 6000, 0, expiry + timedelta(days=1)),
        (GIB, 6000, 14000, expiry),
        (1, 6000, 14000, expiry + timedelta(days=1)),
    ]:
        with pytest.raises(ValueError):
            quote_conversion(remaining, source_rate, dest_rate, expires, expiry)


def test_fractional_quota_is_truncated_not_rounded_up():
    expiry = datetime(2027, 1, 1)
    q = quote_conversion(GIB, 6000, 14000, expiry, datetime(2026, 12, 31))
    assert q['destination_bytes'] == (GIB * 6000) // 14000
    assert q['destination_bytes'] * 14000 <= GIB * 6000


def test_rules_reject_disabled_and_invalid_categories():
    rules = normalize_rules({
        '3': {'price_per_gb_irt': 6000, 'server_ids': ['1', 1, '2', 'invalid', -3]},
        '4': {'price_per_gb_irt': 14000, 'server_ids': [10]},
        '5': {'price_per_gb_irt': 0, 'server_ids': [1]},
        'bad': {'price_per_gb_irt': 8000, 'server_ids': [5]},
    })
    assert rules == {
        '3': {'price_per_gb_irt': 6000, 'server_ids': [1, 2]},
        '4': {'price_per_gb_irt': 14000, 'server_ids': [10]},
    }


def test_parser_understands_utc_epoch_ms_and_iso():
    dt = datetime(2026, 10, 14, 9, 30)
    assert parse_panel_expiry(1791970200000) == dt
    assert parse_panel_expiry('2026-10-14T09:30:00Z') == dt
    assert parse_panel_expiry(None) is None
    assert format_volume(GIB) == '1.000'


def test_unique_source_claim_is_declared_in_database_model():
    from app.database.models import ServiceConversion
    table = ServiceConversion.__table__
    column = table.c.source_service_id
    assert column.unique is True
    assert table.name == 'service_conversions'
    assert 'target_total_bytes' in table.c
    assert 'expires_at' in table.c


def test_convert_handlers_are_registered_and_ownership_checked():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    source = (base / 'app/bot/handlers/public/convert.py').read_text()
    main = (base / 'app/main.py').read_text()
    assert 'conversion_handler.router' in main
    assert 'svc.user_id != user.id' in source
    assert 'svc.reseller_id is not None' in source
    assert 'await _live_quote(' in source
    assert "status='reserved'" in source
    assert 'enqueue_service_deletion' in source
