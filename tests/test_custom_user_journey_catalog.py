from app.bot.custom_texts import build_catalog


def test_custom_catalog_is_user_journey_scoped():
    items = build_catalog(force=True)
    assert items

    # Core user-facing journeys must be present.
    assert any('✅ سرویس شما با موفقیت ساخته و ارسال شد.' in item.default for item in items)
    assert any('سرویس شما با موفقیت ساخته شد' in item.default for item in items)
    assert any('✅ تمدید سرویس با موفقیت انجام شد.' in item.default for item in items)
    assert any('❌ رسید شما رد شد.' in item.default for item in items)

    # Admin-only source trees must never enter the Custom catalog.
    assert all('/handlers/admin/' not in item.source for item in items)
    assert all(item.category and item.section for item in items)


def test_custom_catalog_uses_persian_category_tags():
    items = build_catalog(force=True)
    categories = {item.category for item in items}
    assert 'خرید و پرداخت' in categories
    assert 'کانفیگ‌های من' in categories
    assert 'حساب کاربری و کیف پول' in categories
    assert 'پشتیبانی و تیکت' in categories
