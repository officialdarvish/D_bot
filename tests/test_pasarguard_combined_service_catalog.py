"""PasarGuard category 9 alongside X-UI categories 6/7 in V2Ray sale menu."""
from dataclasses import dataclass, field
from pathlib import Path

from app.services.service_type_catalog import (
    normalize_service_provider,
    normalize_service_type_mode,
    provider_members_for_service_type,
    public_service_type_provider,
    service_provider_label,
)
from app.services.category_visibility import (
    category_linked_server_ids, eligible_category_ids_for_servers,
    public_provider_servers, sellable_category_groups,
)


@dataclass
class Server:
    id: int
    server_type: str = 'xui'
    is_active: bool = True
    meta: dict = field(default_factory=lambda: {'scope': 'public'})


@dataclass
class Category:
    id: int
    name: str
    server_ids: list[int]
    is_active: bool = True
    server_id: int | None = None


def test_repro_real_image_pasarguard_server5_visible_with_sanaei_categories():
    servers = [Server(1), Server(4, server_type='mikrotik'), Server(5, server_type='pasarguard')]
    categories = [
        Category(6, '⚡ VIP حجمی پرسرعت', [1, 4]),
        Category(7, 'نامحدود ♾', [1]),
        Category(9, '⚡ حجمی اقتصادی', [5]),
    ]
    effective = public_service_type_provider(
        slug='v2ray', label='V2Ray', configured='xui',
        available_providers={'xui', 'pasarguard'}, has_dedicated_pasarguard_type=False,
    )
    assert effective == 'v2ray'
    catalogue = public_provider_servers(servers, effective, active_only=False)
    assert [server.id for server in catalogue] == [1, 5]
    category_ids = eligible_category_ids_for_servers(categories, [s.id for s in catalogue])
    assert [item['ids'] for item in sellable_category_groups(categories, category_ids)] == [[6], [7], [9]]


def test_explicit_combined_provider_works_even_if_pasarguard_has_own_service_type():
    result = public_service_type_provider(
        slug='both', label='VPN', configured='v2ray', available_providers={'xui', 'pasarguard'},
        has_dedicated_pasarguard_type=True,
    )
    assert result == 'v2ray'
    assert provider_members_for_service_type(result) == {'xui', 'pasarguard'}
    assert 'PasarGuard' in service_provider_label(result)


def test_explicit_separate_pasarguard_mode_remains_available():
    result = public_service_type_provider(
        slug='pasar', label='PasarGuard', configured='pasarguard',
        available_providers={'xui', 'pasarguard'}, has_dedicated_pasarguard_type=False,
    )
    assert result == 'pasarguard'
    assert provider_members_for_service_type(result) == {'pasarguard'}


def test_when_dedicated_pasarguard_type_exists_old_xui_menu_remains_separate():
    result = public_service_type_provider(
        slug='xui', label='Sanaei', configured='xui',
        available_providers={'xui', 'pasarguard'}, has_dedicated_pasarguard_type=True,
    )
    assert result == 'xui'
    assert provider_members_for_service_type(result) == {'xui'}


def test_public_scope_only_and_inactive_visible_but_not_buyable():
    servers = [Server(1), Server(5, 'pasarguard', False), Server(8, 'pasarguard', True, {'scope': 'reseller'})]
    catalogue = public_provider_servers(servers, 'v2ray', active_only=False)
    active = public_provider_servers(servers, 'v2ray', active_only=True)
    assert [s.id for s in catalogue] == [1, 5]
    assert [s.id for s in active] == [1]


def test_server_type_pasarguard_does_not_change_to_xui_for_provisioning():
    assert normalize_service_provider('pasarguard') == 'pasarguard'
    assert normalize_service_type_mode('v2ray') == 'v2ray'
    assert normalize_service_provider('v2ray') == 'xui'  # legacy provider inference stays intact


def test_category_server_ids_support_legacy_links():
    assert category_linked_server_ids(Category(9, 'اقتصادی', [5], server_id=1)) == [5, 1]


def test_web_and_bot_use_same_mixed_provider_logic():
    root = Path(__file__).resolve().parents[1]
    bot = (root / 'app/bot/handlers/public/buy.py').read_text()
    api = (root / 'app/api/main.py').read_text()
    admin = (root / 'app/api/admin_web.py').read_text()
    frontend = (root / 'frontend/components/admin-dashboard.tsx').read_text()
    assert 'public_service_type_provider(' in bot and 'public_service_type_provider(' in api
    assert 'provider_members_for_service_type(stype)' in bot
    assert "value: 'v2ray'" in frontend
    assert 'normalize_service_type_mode(value)' in admin
    assert 'Plan.server_id.in_(server_ids)' in bot  # no provider-crossed provisioning
