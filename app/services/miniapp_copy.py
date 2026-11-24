"""Allowlisted, installation-scoped Mini App text overrides."""
import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from app.database.models import Setting

PREFIX = 'miniapp_copy:'
CATALOG_PATH = Path(__file__).resolve().parents[2] / 'frontend/lib/miniapp-copy-catalog.json'
TOKEN = re.compile(r'\{[A-Za-z][A-Za-z0-9_]*\}')


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))


def clean_overrides(values):
    fields = catalog()
    if not isinstance(values, dict) or not values or len(values) > len(fields):
        raise ValueError('Invalid Mini App text settings.')
    clean = {}
    for key, raw in values.items():
        field = fields.get(key)
        if field is None or not isinstance(raw, str):
            raise ValueError('Unknown Mini App text field.')
        value = raw.strip()
        if not value:
            clean[key] = ''
            continue
        limit = 96 if field['kind'] == 'button' else 700
        if len(value) > limit:
            raise ValueError('Mini App text exceeds its length limit.')
        default = field['text']
        if set(TOKEN.findall(value)) != set(TOKEN.findall(default)):
            raise ValueError('Keep the original variables in this text.')
        leading = default[:len(default) - len(default.lstrip())]
        trailing = default[len(default.rstrip()):]
        clean[key] = leading + value + trailing
    return clean


async def read_overrides(session):
    fields = catalog()
    rows = await session.execute(
        select(Setting.key, Setting.value).where(Setting.key.startswith(PREFIX, autoescape=True), Setting.value != '')
    )
    return {key.removeprefix(PREFIX): value for key, value in rows if key.removeprefix(PREFIX) in fields}
