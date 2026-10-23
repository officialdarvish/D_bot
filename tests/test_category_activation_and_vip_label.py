"""Regressions: web category toggles, legacy duplicate plan IDs and VIP emoji."""
from dataclasses import dataclass
from pathlib import Path

from app.services.category_visibility import (
    category_button_label,
    category_group_rows,
    category_is_enabled,
    category_name_key,
    sellable_category_groups,
)


@dataclass
class Cat:
    id: int
    name: str
    is_active: bool = True


def test_legacy_duplicate_plan_id_is_sellable_when_group_enabled():
    rows = [Cat(13, 'VIP ⚡', True), Cat(5, '  vip   ⚡ ', False)]
    groups = sellable_category_groups(rows, {5})
    assert len(groups) == 1
    assert groups[0]['ids'] == [13, 5]
    assert groups[0]['has_plans']


def test_toggle_covers_all_same_name_rows_and_can_reactivate():
    rows = [Cat(10, 'اقتصادی', True), Cat(3, ' اقتصادی  ', False)]
    target = category_group_rows(rows, rows[-1])
    assert len(target) == 2
    next_value = not category_is_enabled(target)
    for row in target:
        row.is_active = next_value
    assert not sellable_category_groups(rows, {3})
    next_value = not category_is_enabled(target)
    for row in target:
        row.is_active = next_value
    assert sellable_category_groups(rows, {3})[0]['ids'] == [10, 3]


def test_disabled_group_is_hidden_even_with_active_plans():
    rows = [Cat(7, 'VIP', False), Cat(2, ' VIP ', False)]
    assert sellable_category_groups(rows, {2, 7}) == []


def test_enabled_group_without_active_plan_stays_hidden():
    rows = [Cat(1, 'اقتصادی', True), Cat(2, 'VIP', True)]
    assert [g['name'] for g in sellable_category_groups(rows, {1})] == ['اقتصادی']


def test_vip_lightning_is_moved_to_rtl_right():
    expected = '\u200f⚡ VIP حجمی پرسرعت'
    assert category_button_label('VIP حجمی پرسرعت ⚡') == expected
    assert category_button_label('⚡ VIP حجمی پرسرعت') == expected
    assert category_button_label('  VIP ⚡ حجمی پرسرعت   ') == expected
    assert category_button_label('نامحدود ♾') == 'نامحدود ♾'


def test_category_normalization_avoids_case_and_space_mismatch():
    assert category_name_key(' VIP  حجمی\nپرسرعت ') == category_name_key('vip حجمی پرسرعت')


def test_bot_validates_group_activation_and_loads_legacy_duplicates():
    source = (Path(__file__).resolve().parents[1] / 'app/bot/handlers/public/buy.py').read_text()
    assert 'eligible_category_ids_for_servers(cats, catalog_server_ids, sellable_category_ids)' in source
    assert 'sellable_category_groups(cats, eligible_ids)' in source
    assert 'category_button_label(group[' in source
    assert 'siblings=category_group_rows(categories, selected)' in source
    assert 'category_is_enabled(siblings)' in source
    assert 'cat_ids=[int(row.id) for row in siblings]' in source


def test_web_toggle_uses_logical_group_state_not_representative_row():
    source = (Path(__file__).resolve().parents[1] / 'app/api/admin_web.py').read_text()
    assert 'related=category_group_rows(rows, category)' in source
    assert 'new_value = not category_is_enabled(related)' in source
