from pathlib import Path

from app.services.service_type_catalog import (
    infer_service_provider,
    resolve_service_provider,
    service_type_provider_key,
)


def test_explicit_pasarguard_mapping_wins_for_generic_label():
    assert resolve_service_provider(
        slug='germany',
        label='Germany Premium',
        configured='pasarguard',
        available_providers={'xui', 'pasarguard'},
    ) == 'pasarguard'


def test_old_generic_service_type_auto_routes_to_only_sellable_provider():
    assert resolve_service_provider(
        slug='vip',
        label='VIP Service',
        configured=None,
        available_providers={'pasarguard'},
    ) == 'pasarguard'


def test_old_named_pasarguard_service_keeps_name_inference():
    assert infer_service_provider('PasarGuard reseller') == 'pasarguard'
    assert resolve_service_provider(
        slug='pasarguard',
        label='Premium',
        configured=None,
        available_providers={'xui', 'pasarguard'},
    ) == 'pasarguard'


def test_provider_setting_key_does_not_collide_with_service_rows():
    assert service_type_provider_key('service_type:custom:vip') == 'service_type_provider:vip'


def test_purchase_flow_uses_real_plan_inventory_for_categories():
    root = Path(__file__).resolve().parents[1]
    buy = (root / 'app/bot/handlers/public/buy.py').read_text()
    assert 'sellable_plans=(await session.execute(' in buy
    assert 'Plan.server_id.in_(server_ids)' in buy
    assert 'sellable_category_ids' in buy


def test_plan_save_keeps_category_linked_to_selected_server():
    root = Path(__file__).resolve().parents[1]
    admin = (root / 'app/api/admin_web.py').read_text()
    assert 'def _ensure_category_server_link' in admin
    assert admin.count('_ensure_category_server_link(cat, server_id)') >= 2
