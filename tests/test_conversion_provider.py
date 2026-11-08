"""Provider safety checks for quota conversion."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import conversion_provider as provider


def fake_server(kind):
    return SimpleNamespace(id=3, name='Dest', server_type=kind, meta={})


def fake_plan():
    return SimpleNamespace(id=11, volume_gb=10, duration_days=30,
        hwid_limit=1, inbound_ids=[2], meta={'inbound_mode': 'manual'},
        server_id=3, is_unlimited=False)


def test_convert_creates_exact_pasarguard_quota_using_real_plan():
    server, plan = fake_server('pasarguard'), fake_plan()
    expiry = datetime.utcnow() + timedelta(days=6, hours=3)
    service = SimpleNamespace(create_user_on_plan=AsyncMock(return_value={'uuid': '42', 'sub_link': 'https://example.net/x'}))
    quota = 3 * provider.GIB + 3000
    with patch.object(provider, 'PasarGuardService', return_value=service), patch.object(provider, 'set_exact_quota_and_expiry', new_callable=AsyncMock) as set_exact:
        created = asyncio.run(provider.create_converted(server, plan, 'cv123_11', quota, expiry))
    service.create_user_on_plan.assert_awaited_once_with(server, plan, 'cv123_11')
    set_exact.assert_awaited_once_with(server, 'cv123_11', quota, expiry)
    assert created['uuid'] == '42'


def test_source_disabling_is_readback_verified():
    server = fake_server('xui')
    service = SimpleNamespace(
        set_client_enabled=AsyncMock(),
        find_client_any=AsyncMock(return_value={'client': {'enable': True}}),
    )
    with patch.object(provider, 'XuiService', return_value=service):
        with pytest.raises(RuntimeError, match='did not confirm'):
            asyncio.run(provider.set_enabled(server, 'source', False))


def test_no_conversion_when_sanaei_usage_unavailable():
    server = fake_server('xui')
    src = SimpleNamespace(xui_email='src', client_username='src')
    service = SimpleNamespace(
        find_client_any=AsyncMock(return_value={'client': {'totalGB': provider.GIB, 'expiryTime': 2000000000000, 'enable': True}}),
        query_client=AsyncMock(return_value=None),
    )
    with patch.object(provider, 'XuiService', return_value=service):
        with pytest.raises(ValueError, match='usage endpoint'):
            asyncio.run(provider.live_source(server, src))
