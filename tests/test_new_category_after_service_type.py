"""Newly added categories must show after selecting a matching service type."""
from dataclasses import dataclass, field
from pathlib import Path

from app.services.category_visibility import (
    eligible_category_ids_for_servers,
    sellable_category_groups,
)


@dataclass
class Category:
    id: int
    name: str
    server_ids: list[int] = field(default_factory=list)
    server_id: int | None = None
    is_active: bool = True


def visible(rows, server_ids, plan_cat_ids=()):
    return sellable_category_groups(rows, eligible_category_ids_for_servers(rows, server_ids, plan_cat_ids))


def test_new_category_is_visible_before_first_plan():
    rows = [Category(3, 'اقتصادی', [20]), Category(4, 'VIP ⚡', [22])]
    assert [g['name'] for g in visible(rows, [20])] == ['اقتصادی']
    assert [g['name'] for g in visible(rows, [22])] == ['VIP ⚡']


def test_category_linked_to_other_provider_not_visible():
    rows = [Category(1, 'Sanaei', [10]), Category(2, 'PasarGuard', [12])]
    assert [g['name'] for g in visible(rows, [10])] == ['Sanaei']
    assert not visible(rows, [13])


def test_unassigned_category_is_not_visible_without_plan():
    assert not visible([Category(7, 'draft')], [10])


def test_disabled_category_remains_hidden():
    assert not visible([Category(5, 'Disabled', [10], is_active=False)], [10])


def test_enabled_category_without_plan_but_on_legacy_server_id():
    assert [g['name'] for g in visible([Category(5, 'Legacy', server_id=10)], [10])] == ['Legacy']


def test_plan_backed_category_visible_if_link_is_stale():
    rows = [Category(5, 'Migrated', [15], is_active=True)]
    assert [g['name'] for g in visible(rows, [10], [5])] == ['Migrated']


def test_legacy_duplicate_ids_both_preserved_for_plan_selection():
    rows = [Category(16, 'VIP', [10]), Category(5, ' VIP ', [12], is_active=False)]
    groups = visible(rows, [10], [5])
    assert len(groups) == 1
    assert groups[0]['ids'] == [16, 5]


def test_string_server_ids_and_invalid_values_do_not_crash():
    rows = [Category(9, 'Legacy', '10, 12,foo')]
    assert [g['name'] for g in visible(rows, [10])] == ['Legacy']
    assert visible(rows, [13]) == []


def test_web_and_bot_use_link_and_validate_required_server():
    root = Path(__file__).resolve().parents[1]
    buy = (root / 'app/bot/handlers/public/buy.py').read_text()
    web = (root / 'app/api/admin_web.py').read_text()
    front = (root / 'frontend/components/admin-dashboard.tsx').read_text()
    assert 'eligible_category_ids_for_servers(cats, catalog_server_ids, sellable_category_ids)' in buy
    assert 'eligible_category_ids_for_servers(ordered, [sid], sellable)' in buy
    assert "'Select at least one public server for the category.'" in web
    assert "type: 'checkbox-group', options, full: true, required: true" in front
    assert "(field.type === 'multiselect' || field.type === 'checkbox-group')" in front


def test_bot_keeps_provider_with_active_linked_category_even_without_plans():
    buy = (Path(__file__).resolve().parents[1] / 'app/bot/handlers/public/buy.py').read_text()
    assert 'linked_categories = (await session.execute(' in buy
    assert 'linked_server_ids = {sid for category in linked_categories' in buy
    assert "sellable_providers.add(provider)" in buy
