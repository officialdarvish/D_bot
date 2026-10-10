from __future__ import annotations

from fastapi import APIRouter, Form
from sqlalchemy import select

from app.bot.custom_texts import (
    CUSTOM_PREFIX,
    build_catalog,
    invalidate_custom_text_cache,
    legacy_enabled_key,
    legacy_setting_key,
)
from app.database.models import Setting
from app.database.session import SessionLocal

router = APIRouter()


async def _setting_map(keys: list[str]) -> dict[str, str]:
    keys = [k for k in dict.fromkeys(keys) if k]
    if not keys:
        return {}
    async with SessionLocal() as session:
        rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
        return {str(row.key): str(row.value or '') for row in rows}


async def _upsert(session, key: str, value: str) -> None:
    row = await session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


@router.get('/api/admin/custom-texts', include_in_schema=False)
@router.get('/admin/api/v2/custom-texts', include_in_schema=False)
async def list_custom_texts():
    catalog = build_catalog()
    custom_keys = [entry.key for entry in catalog]
    legacy_keys = [k for entry in catalog for k in (legacy_setting_key(entry), legacy_enabled_key(entry)) if k]
    values = await _setting_map(custom_keys + legacy_keys)
    items = []
    modified = 0
    for entry in catalog:
        legacy_key = legacy_setting_key(entry)
        enabled_key = legacy_enabled_key(entry)
        custom = values.get(entry.key, '')
        legacy = values.get(legacy_key, '') if legacy_key else ''
        current = custom or legacy or entry.default
        customized = bool(custom or legacy)
        if customized:
            modified += 1
        enabled = None
        if enabled_key:
            enabled = values.get(enabled_key, '1').strip().lower() not in {'0', 'false', 'off', 'no', 'disabled'}
        data = entry.public()
        data.update({
            'current': current,
            'customized': customized,
            'enabled': enabled,
            'legacy_key': legacy_key,
        })
        items.append(data)
    return {
        'ok': True,
        'items': items,
        'total': len(items),
        'modified': modified,
        'categories': sorted({entry.category for entry in catalog}),
        'sections': sorted({entry.section for entry in catalog if entry.section}),
    }


@router.post('/api/admin/custom-texts', include_in_schema=False)
@router.post('/admin/api/v2/custom-texts', include_in_schema=False)
async def save_custom_text(
    key: str = Form(...),
    value: str = Form(''),
    enabled: str | None = Form(default=None),
):
    catalog = {entry.key: entry for entry in build_catalog()}
    entry = catalog.get(key)
    if not entry:
        return {'ok': False, 'message': 'Custom text entry was not found'}
    value = str(value or '')
    if entry.kind == 'button' and len(value) > 64:
        return {'ok': False, 'message': 'Telegram button text cannot be longer than 64 characters'}
    if entry.kind != 'button' and len(value) > 4096:
        return {'ok': False, 'message': 'Telegram message text cannot be longer than 4096 characters'}
    legacy_key = legacy_setting_key(entry)
    enabled_key = legacy_enabled_key(entry)
    async with SessionLocal() as session:
        if value.strip():
            await _upsert(session, entry.key, value)
            if legacy_key:
                await _upsert(session, legacy_key, value)
        else:
            row = await session.get(Setting, entry.key)
            if row:
                await session.delete(row)
            if legacy_key:
                row = await session.get(Setting, legacy_key)
                if row:
                    await session.delete(row)
        if enabled_key and enabled is not None:
            on = str(enabled).strip().lower() not in {'0', 'false', 'off', 'no', 'disabled'}
            await _upsert(session, enabled_key, '1' if on else '0')
        await session.commit()
    invalidate_custom_text_cache()
    return {'ok': True, 'message': 'Custom text saved successfully'}


@router.post('/api/admin/custom-texts/reset', include_in_schema=False)
@router.post('/admin/api/v2/custom-texts/reset', include_in_schema=False)
async def reset_custom_text(key: str = Form(''), reset_all: str = Form('0')):
    catalog = build_catalog()
    by_key = {entry.key: entry for entry in catalog}
    all_flag = str(reset_all).strip().lower() in {'1', 'true', 'yes', 'on'}
    targets = catalog if all_flag else ([by_key[key]] if key in by_key else [])
    if not targets:
        return {'ok': False, 'message': 'Custom text entry was not found'}
    async with SessionLocal() as session:
        for entry in targets:
            for setting_key in (entry.key, legacy_setting_key(entry), legacy_enabled_key(entry)):
                if not setting_key:
                    continue
                row = await session.get(Setting, setting_key)
                if row:
                    await session.delete(row)
        await session.commit()
    invalidate_custom_text_cache()
    return {'ok': True, 'message': 'Custom text reset to default'}
