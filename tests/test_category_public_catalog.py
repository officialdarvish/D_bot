"""Regression for the three-card screenshot: category 9 must not vanish.

The card may link to an inactive public X-UI server (5) while categories
6 and 7 link to an active X-UI server (1). The menu is a catalogue; only
plan purchasing requires an active server.
"""
from dataclasses import dataclass, field
from pathlib import Path

from app.services.category_visibility import (
    public_provider_servers, category_bot_status,
    eligible_category_ids_for_servers, sellable_category_groups,
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


def groups_for(servers, cats, provider='xui'):
    catalog = public_provider_servers(servers, provider, active_only=False)
    eligible = eligible_category_ids_for_servers(cats, [s.id for s in catalog])
    return sellable_category_groups(cats, eligible)


def test_image_example_all_three_categories_visible_with_offline_server5():
    servers = [Server(1), Server(4, server_type='mikrotik'), Server(5, is_active=False)]
    cats = [
        Category(6, '⚡ VIP حجمی پرسرعت', [4, 1]),
        Category(7, 'نامحدود پرسرعت ♾', [1]),
        Category(9, '⚡ حجمی اقتصادی', [5]),
    ]
    groups = groups_for(servers, cats)
    assert [g['ids'] for g in groups] == [[6], [7], [9]]
    active = public_provider_servers(servers, 'xui', active_only=True)
    assert [s.id for s in active] == [1]
    status = category_bot_status([cats[2]], servers)
    assert status['status'] == 'paused'
    assert status['inactive_public_server_ids'] == [5]


def test_legacy_sanaei_alias_is_in_same_provider_catalog():
    servers = [Server(1, server_type='xui'), Server(5, server_type='sanaei')]
    assert [g['ids'] for g in groups_for(servers, [Category(9, 'اقتصادی', [5])])] == [[9]]


def test_mismatched_provider_category_has_explicit_diagnostic():
    servers = [Server(1, server_type='xui'), Server(5, server_type='pasarguard')]
    cats = [Category(9, 'اقتصادی', [5])]
    assert not groups_for(servers, cats, 'xui')
    assert [g['ids'] for g in groups_for(servers, cats, 'pasarguard')] == [[9]]
    assert category_bot_status(cats, servers)['providers'] == ['pasarguard']


def test_reseller_only_server_never_becomes_public_purchase_inventory():
    servers = [Server(5, meta={'scope': 'reseller'})]
    cats = [Category(9, 'اقتصادی', [5])]
    assert not groups_for(servers, cats)
    assert category_bot_status(cats, servers)['status'] == 'reseller_only'


def test_disabled_category_stays_hidden_when_server_public():
    assert not groups_for([Server(5)], [Category(9, 'Disabled', [5], False)])


def test_missing_server_is_diagnosed():
    assert category_bot_status([Category(9, 'اقتصادی', [5])], [Server(1)])['status'] == 'missing_servers'


def test_bot_does_not_offer_inactive_server_for_buying_and_api_has_reason():
    base = Path(__file__).resolve().parents[1]
    bot = (base / 'app/bot/handlers/public/buy.py').read_text()
    web = (base / 'app/api/admin_web.py').read_text()
    frontend = (base / 'frontend/components/admin-dashboard.tsx').read_text()
    assert 'catalog_server_ids' in bot
    assert 'public_provider_servers(catalog_servers, stype, active_only=True)' in bot
    assert 'Plan.server_id.in_(server_ids)' in bot
    assert 'category_bot_status(related, servers, active_plan_pairs)' in web
    assert "['Bot visibility details', visibility?.detail || '-']" in frontend
