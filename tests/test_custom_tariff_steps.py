"""Custom purchases gather and validate GB first, then days before pricing."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from test_miniapp import client
from test_modules_update_and_tariffs import template
from app.database.models import Plan, ResellerPackage, ResellerAccount
from app.bot.handlers.public import buy, reseller
from app.bot.states.public_states import BuyFlow


@pytest.mark.parametrize('kind', ['public', 'reseller'])
def test_custom_purchase_volume_then_days_without_early_snapshot(client, monkeypatch, kind):
    _, sessions = client
    module = buy if kind == 'public' else reseller
    model = Plan if kind == 'public' else ResellerPackage
    volume_handler = module.buy_custom_selection if kind == 'public' else module.reseller_custom_selection
    days_handler = module.buy_custom_days if kind == 'public' else module.reseller_custom_days
    volume_state = BuyFlow.custom_selection.state if kind == 'public' else 'reseller_custom_selection'
    days_state = BuyFlow.custom_days.state if kind == 'public' else 'reseller_custom_days'
    monkeypatch.setattr(module, 'SessionLocal', sessions)
    ui = AsyncMock()
    monkeypatch.setattr(module, 'ui_message', ui)
    async def run():
        async with sessions() as session:
            if kind == 'public':
                parent = await session.get(Plan, 1)
                parent.meta = {'custom_tariff': template().meta['custom_tariff']}
            else:
                parent = ResellerPackage(id=1, title='Custom', server_id=1, meta={'custom_tariff': template().meta['custom_tariff']})
                session.add(parent)
                session.add(ResellerAccount(user_id=1, server_id=1, allowed_server_ids=[1]))
            await session.commit()
            initial_count = await session.scalar(select(func.count(model.id)))
        storage = MemoryStorage()
        state = FSMContext(storage=storage, key=StorageKey(bot_id=123, chat_id=11, user_id=11))
        await state.set_state(volume_state)
        await state.update_data(**({'plan_id': 1, 'server_id': 1} if kind == 'public' else {'custom_package_id': 1}))
        def message(value):return SimpleNamespace(text=value, from_user=SimpleNamespace(id=11))
        async def count():
            async with sessions() as session:return await session.scalar(select(func.count(model.id)))
        for invalid in ('20 30', '0', '101', 'abc'):
            await volume_handler(message(invalid), state)
            assert await state.get_state() == volume_state
            assert await count() == initial_count
        await volume_handler(message('۲۰'), state)
        assert await state.get_state() == days_state
        assert (await state.get_data())['custom_volume_gb'] == 20
        assert 'تعداد روز' in ui.call_args.args[1]
        back = ui.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        assert back == ('buy:plan:1' if kind == 'public' else 'reseller:pkg:1')
        assert await count() == initial_count
        for invalid in ('20 30', '0', '91', '1.5'):
            await days_handler(message(invalid), state)
            assert await state.get_state() == days_state
            assert (await state.get_data())['custom_volume_gb'] == 20
            assert await count() == initial_count
        # Pricing is read from the server again at the final stage.
        async with sessions() as session:
            parent = await session.get(model, 1)
            policy = {**parent.meta['custom_tariff'], 'price_day': 2000}
            parent.meta = {'custom_tariff': policy}
            await session.commit()
        await days_handler(message('۳۰'), state)
        assert await count() == initial_count + 1
        assert await state.get_state() == (BuyFlow.username.state if kind == 'public' else None)
        async with sessions() as session:
            rows = (await session.execute(select(model))).scalars().all()
            concrete = next(row for row in rows if (row.meta or {}).get('custom_selection'))
            assert concrete.volume_gb == 20
            assert (concrete.duration_days if kind == 'public' else concrete.reseller_validity_days) == 30
            assert concrete.price_irt == 260000
            assert concrete.is_active is False
            assert (await session.get(model, 1)).is_active is True
        await storage.close()
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['public', 'reseller'])
def test_template_disabled_between_steps_does_not_create_purchase(client, monkeypatch, kind):
    _, sessions = client
    module = buy if kind == 'public' else reseller
    model = Plan if kind == 'public' else ResellerPackage
    monkeypatch.setattr(module, 'SessionLocal', sessions)
    monkeypatch.setattr(module, 'ui_message', AsyncMock())
    async def run():
        async with sessions() as session:
            if kind == 'public':
                parent = await session.get(Plan, 1)
                parent.meta = {'custom_tariff': template().meta['custom_tariff']}
            else:
                parent = ResellerPackage(id=1, title='Custom', server_id=1, meta={'custom_tariff': template().meta['custom_tariff']})
                session.add(parent)
            parent.is_active = False
            await session.commit()
            before = await session.scalar(select(func.count(model.id)))
        storage = MemoryStorage()
        state = FSMContext(storage=storage, key=StorageKey(bot_id=123, chat_id=11, user_id=11))
        await state.update_data(custom_volume_gb=20, **({'plan_id': 1} if kind == 'public' else {'custom_package_id': 1}))
        handler = module.buy_custom_days if kind == 'public' else module.reseller_custom_days
        await handler(SimpleNamespace(text='30', from_user=SimpleNamespace(id=11)), state)
        async with sessions() as session:
            assert await session.scalar(select(func.count(model.id))) == before
        assert 'نیست' in module.ui_message.call_args.args[1]
        await storage.close()
    asyncio.run(run())
