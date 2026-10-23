from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, delete
from app.core.roles import is_owner
from app.database.session import SessionLocal
from app.database.models import Plan, Server, ServerCategory, Order, ClientService
from app.bot.states.admin_states import AddPlan, EditPlan
from app.bot.keyboards.common import CB_PLANS, back_button, main_menu_inline
from app.bot.utils import edit_or_answer, ui_message, ui_callback_message, state_prompt, delete_state_message
from app.services.plan_order import saved_plan_order, sort_by_saved_order
from app.services.xui_service import XuiService, schedule_plan_hwid_limit_sync as schedule_xui_plan_hwid_limit_sync
from app.services.pasarguard_service import schedule_plan_hwid_limit_sync as schedule_pasarguard_plan_hwid_limit_sync
from app.services.live_pricing import plan_currency, plan_price_label, update_plan_pricing_meta

router = Router()

def admin(uid):
    return is_owner(uid)


def money(v: int | None) -> str:
    try:
        return f"{int(v or 0):,} تومان"
    except Exception:
        return f"{v} تومان"


def plan_type_text(p: Plan) -> str:
    if bool(getattr(p, "is_unlimited", False)) or int(getattr(p, "volume_gb", 0) or 0) <= 0:
        return "نامحدود"
    return "حجمی"


def visibility_text(p: Plan) -> str:
    return "🟢 قابل نمایش" if p.is_active else "🔴 مخفی"


def plan_inbound_mode(p: Plan) -> str:
    return 'manual' if str((p.meta or {}).get('inbound_mode') or '').strip().lower() == 'manual' else 'automatic'

def inbounds_text(p: Plan) -> str:
    ids = p.inbound_ids or []
    return ", ".join(str(x) for x in ids) if ids else "ثبت نشده / OpenVPN"


def hwid_limit_text(p: Plan) -> str:
    try:
        limit = max(int(getattr(p, 'hwid_limit', 0) or 0), 0)
    except Exception:
        limit = 0
    return 'نامحدود' if limit <= 0 else f'{limit} دستگاه'


def plan_group_name(p: Plan | None) -> str:
    return str(((getattr(p, 'meta', None) or {}).get('group_name') if p else '') or '').strip()


async def _group_selection_keyboard(server: Server, *, prefix: str, back_callback: str) -> tuple[InlineKeyboardMarkup, list[str]]:
    try:
        groups = await XuiService().live_client_groups(server)
    except Exception:
        groups = []
    names = [str(row.get('name') or '').strip() for row in groups if isinstance(row, dict) and str(row.get('name') or '').strip()]
    rows = [[InlineKeyboardButton(text='بدون گروه', callback_data=f'{prefix}:-1')]]
    for idx, name in enumerate(names):
        rows.append([InlineKeyboardButton(text=f'👥 {name[:45]}', callback_data=f'{prefix}:{idx}')])
    rows.append([back_button(back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows), names


def _server_inbounds(server: Server | None) -> list[int]:
    ids = []
    raw = (server.meta or {}).get("inbound_ids") if server else []
    for item in (raw or []):
        if isinstance(item, dict):
            item = item.get("id") or item.get("inbound_id") or item.get("inboundId")
        try:
            iid = int(item)
        except Exception:
            continue
        if iid > 0 and iid not in ids:
            ids.append(iid)
    return ids


async def plans_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📋 پلن عمومی", callback_data="plan:list")],
        [InlineKeyboardButton(text="➕ اضافه کردن پلن", callback_data="plan:add_fixed")],
        [InlineKeyboardButton(text="➕ پلن Open VPN", callback_data="plan:add_openvpn")],
        [back_button("back:admin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def plans_list_keyboard() -> InlineKeyboardMarkup:
    async with SessionLocal() as session:
        plans = (await session.execute(select(Plan))).scalars().all()
        plans = sort_by_saved_order(plans, await saved_plan_order(session, 'public'))
    rows = []
    rows.append([InlineKeyboardButton(text="➕ اضافه کردن پلن", callback_data="plan:add_fixed")])
    if plans:
        for p in plans:
            rows.append([InlineKeyboardButton(text=f"{visibility_text(p)} | 📦 {p.title[:28]}", callback_data=f"plan:detail:{p.id}")])
    else:
        rows.append([InlineKeyboardButton(text="هنوز پلنی ثبت نشده", callback_data="noop")])
    rows.append([back_button("admin:plans")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def plan_detail_text(plan_id: int) -> str:
    async with SessionLocal() as session:
        p = await session.get(Plan, plan_id)
        cat = await session.get(ServerCategory, p.category_id) if p else None
    if not p:
        return "❌ پلن پیدا نشد."
    return (
        "✅ مدیریت پلن فروش\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🆔 شناسه: {p.id}\n"
        f"📦 عنوان: {p.title}\n"
        f"⚙️ نوع سرویس: {plan_type_text(p)}\n"
        f"👁 وضعیت نمایش: {visibility_text(p)}\n"
        f"📁 دسته: {cat.name if cat else 'نامشخص'}\n"
        f"🖥 سرور ID: {p.server_id}\n"
        f"⚙️ حالت Inbound: {'دستی' if plan_inbound_mode(p) == 'manual' else 'خودکار'}\n"
        f"🔢 Inbound ID ها: {inbounds_text(p)}\n"
        f"👥 گروه پنل: {plan_group_name(p) or 'بدون گروه'}\n"
        f"💱 نوع قیمت: {'دلار / Wallex' if plan_currency(p) == 'USD' else 'تومان ثابت'}\n"
        f"🖥 محدودیت HWID: {hwid_limit_text(p)}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💾 حجم: {p.volume_gb} گیگ\n"
        f"📅 مدت: {p.duration_days} روز\n"
        f"💰 قیمت: {plan_price_label(p)}"
    )


def plan_detail_keyboard(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ تغییر عنوان", callback_data=f"plan:edit:title:{pid}"), InlineKeyboardButton(text="💰 تغییر قیمت", callback_data=f"plan:edit:price:{pid}")],
        [InlineKeyboardButton(text="💾 تغییر حجم", callback_data=f"plan:edit:volume:{pid}"), InlineKeyboardButton(text="📅 تغییر مدت", callback_data=f"plan:edit:duration:{pid}")],
        [InlineKeyboardButton(text="📁 تغییر دسته", callback_data=f"plan:edit:category:{pid}"), InlineKeyboardButton(text="🖥 محدودیت HWID", callback_data=f"plan:edit:hwid:{pid}")],
        [InlineKeyboardButton(text="💱 نوع قیمت", callback_data=f"plan:edit:currency:{pid}"), InlineKeyboardButton(text="👥 تغییر گروه پنل", callback_data=f"plan:edit:group:{pid}")],
        [InlineKeyboardButton(text="👁 نمایش / عدم نمایش", callback_data=f"plan:toggle:{pid}")],
        [InlineKeyboardButton(text="🗑 حذف پلن", callback_data=f"plan:delete:{pid}")],
        [back_button("admin:plans")],
    ])


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == CB_PLANS)
async def plan_menu(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    await edit_or_answer(callback, "✅ مدیریت پلن‌های فروش:", reply_markup=await plans_keyboard())
    await callback.answer()


@router.callback_query(F.data == "plan:list")
async def plan_list(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    await edit_or_answer(callback, "📋 پلن عمومی:\n\nیکی از پلن‌ها را انتخاب کنید:", reply_markup=await plans_list_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("plan:detail:"))
async def plan_detail(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[-1])
    await edit_or_answer(callback, await plan_detail_text(pid), reply_markup=plan_detail_keyboard(pid))
    await callback.answer()


@router.callback_query(F.data.startswith("plan:toggle:"))
async def toggle_plan(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[-1])
    async with SessionLocal() as session:
        p = await session.get(Plan, pid)
        if p:
            p.is_active = not p.is_active
            await session.commit()
    await edit_or_answer(callback, await plan_detail_text(pid), reply_markup=plan_detail_keyboard(pid))
    await callback.answer("وضعیت نمایش تغییر کرد.")


@router.callback_query(F.data.startswith("plan:delete:"))
async def delete_plan(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[-1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، حذف شود", callback_data=f"plan:delete_confirm:{pid}")],
        [back_button(f"plan:detail:{pid}")],
    ])
    await edit_or_answer(callback, "⚠️ مطمئنی می‌خواهی این پلن حذف شود؟\n\nاگر سفارش یا سرویس به این پلن وصل باشد، اتصال آن‌ها به پلن پاک می‌شود ولی خود سرویس کاربر حذف نمی‌شود.", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("plan:delete_confirm:"))
async def delete_plan_confirm(callback: CallbackQuery):
    if not admin(callback.from_user.id):
        return
    pid = int(callback.data.split(":")[-1])
    deleted_info = None
    async with SessionLocal() as session:
        p = await session.get(Plan, pid)
        if p:
            cat = await session.get(ServerCategory, p.category_id) if p.category_id else None
            deleted_info = {
                "title": p.title,
                "type": plan_type_text(p),
                "category": cat.name if cat else "نامشخص",
                "volume": int(p.volume_gb or 0),
                "duration": int(p.duration_days or 0),
                "price_label": plan_price_label(p),
            }
        await session.execute(delete(Order).where(Order.plan_id == pid))
        services = (await session.execute(select(ClientService).where(ClientService.plan_id == pid))).scalars().all()
        for s in services:
            s.plan_id = None
        if p:
            await session.delete(p)
        await session.commit()
    if deleted_info:
        msg = (
            "✅ پلن با موفقیت حذف شد.\n\n"
            f"📦 عنوان: {deleted_info['title']}\n"
            f"⚙️ نوع: {deleted_info['type']}\n"
            f"📁 دسته: {deleted_info['category']}\n"
            f"💾 حجم: {deleted_info['volume']} گیگ\n"
            f"📅 مدت: {deleted_info['duration']} روز\n"
            f"💰 قیمت: {deleted_info['price_label']}"
        )
    else:
        msg = "✅ پلن با موفقیت حذف شد."
    await edit_or_answer(callback, msg + "\n\n📋 پلن عمومی:", reply_markup=await plans_list_keyboard())
    await callback.answer()


@router.callback_query(F.data.in_({"plan:add_fixed", "plan:add_openvpn"}))
async def add_plan(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    await state.clear()
    await state.update_data(is_openvpn=callback.data == "plan:add_openvpn")
    await state.set_state(AddPlan.title)
    sent = await ui_callback_message(callback, "عنوان پلن را وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@router.message(AddPlan.title)
async def plan_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddPlan.volume)
    await state_prompt(message, state, "حجم پلن را به گیگ وارد کنید. برای نامحدود عدد 0 بزنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))


@router.message(AddPlan.volume)
async def plan_volume(message: Message, state: FSMContext):
    try:
        volume = int(message.text.strip())
    except ValueError:
        await state_prompt(message, state, "❌ فقط عدد وارد کنید. حجم پلن را به گیگ وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        return
    await state.update_data(volume=volume)
    await state.set_state(AddPlan.duration)
    await state_prompt(message, state, "مدت انقضا را به روز وارد کنید. برای نامحدود/بدون انقضا عدد 0 بزنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))


@router.message(AddPlan.duration)
async def plan_duration(message: Message, state: FSMContext):
    try:
        duration = int(message.text.strip())
    except ValueError:
        await state_prompt(message, state, "❌ فقط عدد وارد کنید. مدت انقضا را به روز وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        return
    await state.update_data(duration=duration)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 تومان ثابت", callback_data="plan:add_currency:IRT")],
        [InlineKeyboardButton(text="💵 دلار / نرخ لحظه‌ای Wallex", callback_data="plan:add_currency:USD")],
        [back_button("admin:plans")],
    ])
    await state_prompt(message, state, "💱 نوع قیمت‌گذاری این پلن را انتخاب کنید:", reply_markup=kb)


@router.callback_query(F.data.startswith("plan:add_currency:"))
async def plan_add_currency(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    currency = callback.data.rsplit(":", 1)[-1].upper()
    if currency not in {"IRT", "USD"}:
        await callback.answer("نوع قیمت معتبر نیست.", show_alert=True)
        return
    await state.update_data(pricing_currency=currency)
    await state.set_state(AddPlan.price)
    prompt = "💵 قیمت پلن را به دلار وارد کنید. مثال: 4.99" if currency == "USD" else "💰 قیمت پلن را به تومان وارد کنید:"
    await edit_or_answer(callback, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
    await callback.answer()


@router.message(AddPlan.price)
async def plan_price(message: Message, state: FSMContext):
    data = await state.get_data()
    currency = str(data.get("pricing_currency") or "IRT").upper()
    raw = (message.text or "").replace(",", "").strip()
    try:
        if currency == "USD":
            normalized = update_plan_pricing_meta({}, pricing_currency="USD", price_usd=raw)
            await state.update_data(price=0, price_usd=normalized.get("price_usd"), pricing_currency="USD")
        else:
            price = int(raw)
            if price < 0:
                raise ValueError
            await state.update_data(price=price, price_usd=None, pricing_currency="IRT")
    except (ValueError, TypeError):
        prompt = "❌ قیمت دلاری معتبر نیست. مثال: 4.99" if currency == "USD" else "❌ فقط عدد معتبر وارد کنید. قیمت پلن را به تومان وارد کنید:"
        await state_prompt(message, state, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        return
    data = await state.get_data()
    if data.get("is_openvpn"):
        await state.update_data(hwid_limit=0)
        await _prompt_plan_category(message, state)
        return
    await state.set_state(AddPlan.hwid_limit)
    await state_prompt(
        message, state,
        "🖥 محدودیت دستگاه بر اساس HWID را وارد کنید.\n\n"
        "مثال: 1 یعنی فقط یک دستگاه ثبت‌شده می‌تواند از اشتراک استفاده کند.\n"
        "برای نامحدود عدد 0 را وارد کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]])
    )


async def _prompt_plan_category(message: Message, state: FSMContext):
    async with SessionLocal() as session:
        cats = (await session.execute(select(ServerCategory))).scalars().all()
    if not cats:
        await delete_state_message(message.bot, message.chat.id, state)
        await ui_message(message, "هیچ دسته‌ای ثبت نشده است. اول دسته بسازید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        await state.clear()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c.name, callback_data=f"plan:cat:{c.id}")] for c in cats] + [[back_button("admin:plans")]])
    await state.set_state(AddPlan.category_id)
    await state_prompt(message, state, "دسته پلن را انتخاب کنید:", reply_markup=kb)


@router.message(AddPlan.hwid_limit)
async def plan_hwid_limit(message: Message, state: FSMContext):
    try:
        limit = int((message.text or '').strip())
        if limit < 0:
            raise ValueError
    except ValueError:
        await state_prompt(message, state, "❌ محدودیت HWID باید عدد صفر یا بزرگ‌تر باشد. مثال: 1", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        return
    await state.update_data(hwid_limit=limit)
    await _prompt_plan_category(message, state)


@router.callback_query(F.data.startswith("plan:cat:"))
async def plan_category(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[-1])
    data = await state.get_data()
    async with SessionLocal() as session:
        cat = await session.get(ServerCategory, cid)
    if not cat or not cat.server_id:
        await edit_or_answer(callback, "این دسته به سرور وصل نیست.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        await callback.answer()
        return
    if data.get("edit_field") == "category":
        pid = int(data["plan_id"])
        async with SessionLocal() as session:
            p = await session.get(Plan, pid)
            server = await session.get(Server, cat.server_id)
            if p:
                previous_server_id = p.server_id
                p.category_id = cid
                p.server_id = cat.server_id
                p.inbound_ids = [] if (server and server.server_type == "openvpn") else _server_inbounds(server)
                meta = dict(p.meta or {})
                meta['inbound_mode'] = 'automatic'
                # A real server move must not carry a client-group name from the
                # previous panel. Keeping the same server preserves the policy.
                if previous_server_id != cat.server_id:
                    meta.pop('group_name', None)
                p.meta = meta
                await session.commit()
        await state.clear()
        await edit_or_answer(callback, await plan_detail_text(pid), reply_markup=plan_detail_keyboard(pid))
        await callback.answer("دسته تغییر کرد.")
        return

    async with SessionLocal() as session:
        server = await session.get(Server, cat.server_id)
    # Public sales plans should not ask for inbound IDs. The sales server already
    # stores every inbound discovered when it was added/edited; use all of them.
    inbound_ids = [] if data.get("is_openvpn") else _server_inbounds(server)
    await state.update_data(category_id=cid, server_id=cat.server_id, available_inbounds=inbound_ids, group_name='')
    if server and str(server.server_type or '').lower() == 'xui' and not data.get("is_openvpn"):
        kb, group_names = await _group_selection_keyboard(
            server, prefix='plan:add_group', back_callback='admin:plans'
        )
        await state.update_data(available_group_names=group_names)
        await state.set_state(AddPlan.group_name)
        note = 'گروه Sanaei این پلن را انتخاب کنید:'
        if not group_names:
            note += '\n\nℹ️ گروهی از پنل دریافت نشد؛ می‌توانید پلن را بدون گروه بسازید.'
        await edit_or_answer(callback, note, reply_markup=kb)
        await callback.answer()
        return
    await _create_plan_from_state(callback, state, inbound_ids)
    return


@router.callback_query(F.data.startswith('plan:add_group:'))
async def add_plan_group(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    data = await state.get_data()
    names = list(data.get('available_group_names') or [])
    try:
        idx = int(callback.data.rsplit(':', 1)[-1])
    except Exception:
        idx = -1
    selected = names[idx] if 0 <= idx < len(names) else ''
    await state.update_data(group_name=selected)
    await _create_plan_from_state(callback, state, list(data.get('available_inbounds') or []))


async def _create_plan_from_state(event, state: FSMContext, inbound_ids: list[int]):
    data = await state.get_data()
    currency = str(data.get('pricing_currency') or 'IRT').upper()
    plan_meta = {
        'inbound_mode': 'automatic',
        **({'group_name': str(data.get('group_name') or '').strip()} if str(data.get('group_name') or '').strip() else {}),
    }
    plan_meta = update_plan_pricing_meta(plan_meta, pricing_currency=currency, price_usd=data.get('price_usd') or '0')
    stored_price = int(data.get('price') or 0) if currency != 'USD' else 0
    async with SessionLocal() as session:
        plan = Plan(
            title=data["title"], volume_gb=data["volume"], duration_days=data["duration"],
            price_irt=stored_price, category_id=data["category_id"], server_id=data["server_id"],
            inbound_ids=inbound_ids,
            hwid_limit=(0 if data.get("is_openvpn") else max(int(data.get("hwid_limit") or 0), 0)),
            is_unlimited=(not data.get("is_openvpn") and int(data["volume"] or 0) <= 0),
            is_active=True,
            meta=plan_meta,
        )
        session.add(plan)
        await session.commit()
    await state.clear()
    msg = (
        "✅ پلن با این مشخصات با موفقیت اضافه شد.\n\n"
        f"📦 عنوان: {data['title']}\n"
        f"💾 حجم: {data['volume']} گیگ\n"
        f"📅 مدت: {data['duration']} روز\n"
        f"💰 قیمت: {'$' + str(data.get('price_usd')) if currency == 'USD' else money(data.get('price'))}\n"
        f"🖥 محدودیت HWID: {'نامحدود' if int(data.get('hwid_limit') or 0) <= 0 else str(int(data.get('hwid_limit') or 0)) + ' دستگاه'}\n"
        f"👥 گروه پنل: {str(data.get('group_name') or '').strip() or 'بدون گروه'}\n"
        f"🔢 Inbound ID ها: {', '.join(map(str, inbound_ids)) if inbound_ids else 'OpenVPN / ثبت نشده'}"
    )
    if isinstance(event, CallbackQuery):
        await edit_or_answer(event, msg + "\n\n📋 پلن عمومی:", reply_markup=await plans_list_keyboard())
        await event.answer()
    else:
        await delete_state_message(event.bot, event.chat.id, state)
        try:
            await event.delete()
        except Exception:
            pass
        await ui_message(event, msg + "\n\n📋 پلن عمومی:", reply_markup=await plans_list_keyboard())


@router.message(AddPlan.inbound_ids)
async def plan_inbounds(message: Message, state: FSMContext):
    data = await state.get_data()
    available = [int(x) for x in (data.get("available_inbounds") or [])]
    raw = (message.text or "").strip().lower()
    if raw in {"all", "همه"}:
        selected = available
    else:
        selected = []
        for part in raw.replace("،", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                iid = int(part)
            except ValueError:
                await state_prompt(message, state, "❌ فقط ID عددی اینباندها را با کاما وارد کنید یا all بفرستید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
                return
            if iid in available and iid not in selected:
                selected.append(iid)
    if not selected:
        await state_prompt(message, state, "❌ حداقل یک Inbound معتبر انتخاب کنید. مثال: 1,2,3", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button("admin:plans")]]))
        return
    await _create_plan_from_state(message, state, selected)


@router.callback_query(F.data.startswith("plan:edit:"))
async def edit_plan_field(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    _, _, field, pid = callback.data.split(":")
    pid = int(pid)
    await state.clear()
    await state.update_data(plan_id=pid, edit_field=field)
    if field == "hwid":
        async with SessionLocal() as session:
            plan = await session.get(Plan, pid)
            server = await session.get(Server, plan.server_id) if plan and plan.server_id else None
        if not plan or not server or str(server.server_type or '').lower() not in {'xui', 'pasarguard'}:
            await state.clear()
            await callback.answer("HWID فقط برای پلن‌های 3x-ui و PasarGuard قابل تنظیم است.", show_alert=True)
            return
    if field == "currency":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 تومان ثابت", callback_data=f"plan:set_currency:{pid}:IRT")],
            [InlineKeyboardButton(text="💵 دلار / نرخ لحظه‌ای Wallex", callback_data=f"plan:set_currency:{pid}:USD")],
            [back_button(f"plan:detail:{pid}")],
        ])
        await edit_or_answer(callback, "💱 نوع قیمت‌گذاری پلن را انتخاب کنید:\nبعد از انتخاب، قیمت جدید را وارد می‌کنید.", reply_markup=kb)
        await callback.answer()
        return
    if field == "group":
        async with SessionLocal() as session:
            plan = await session.get(Plan, pid)
            server = await session.get(Server, plan.server_id) if plan and plan.server_id else None
        if not plan or not server or str(server.server_type or '').lower() != 'xui':
            await state.clear()
            await callback.answer("گروه فقط برای پلن‌های 3x-ui قابل تنظیم است.", show_alert=True)
            return
        kb, group_names = await _group_selection_keyboard(
            server, prefix=f'plan:set_group:{pid}', back_callback=f'plan:detail:{pid}'
        )
        await state.update_data(available_group_names=group_names)
        note = "👥 گروه Sanaei این پلن را انتخاب کنید:"
        if not group_names:
            note += "\n\nℹ️ گروهی از پنل دریافت نشد؛ می‌توانید گزینه بدون گروه را انتخاب کنید."
        await edit_or_answer(callback, note, reply_markup=kb)
        await callback.answer()
        return
    if field == "category":
        async with SessionLocal() as session:
            cats = (await session.execute(select(ServerCategory))).scalars().all()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c.name, callback_data=f"plan:cat:{c.id}")] for c in cats] + [[back_button(f"plan:detail:{pid}")]])
        await state.set_state(AddPlan.category_id)
        await edit_or_answer(callback, "📁 دسته جدید پلن را انتخاب کنید:", reply_markup=kb)
        await callback.answer()
        return
    prompts = {
        "title": "✏️ عنوان جدید پلن را وارد کنید:",
        "price": "💰 قیمت جدید را وارد کنید (برای پلن دلاری مقدار USD و برای پلن تومانی مقدار تومان):",
        "volume": "💾 حجم جدید را به گیگ وارد کنید:",
        "duration": "📅 مدت جدید را به روز وارد کنید:",
        "hwid": "🖥 محدودیت جدید HWID را وارد کنید. 0 = نامحدود، 1 = یک دستگاه و ...:",
        "inbounds": "🔢 Inbound ID های جدید را با کاما وارد کنید. برای OpenVPN عدد 0 بزنید:\nمثال: 1,2,3,100",
    }
    await state.set_state(EditPlan.value)
    sent = await ui_callback_message(callback, prompts.get(field, "مقدار جدید را وارد کنید:"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f"plan:detail:{pid}")]]))
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith('plan:set_currency:'))
async def set_plan_pricing_currency(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    parts = callback.data.split(':')
    try:
        pid = int(parts[2])
        currency = str(parts[3]).upper()
    except Exception:
        await callback.answer('انتخاب نوع قیمت معتبر نیست.', show_alert=True)
        return
    if currency not in {'IRT', 'USD'}:
        await callback.answer('انتخاب نوع قیمت معتبر نیست.', show_alert=True)
        return
    await state.clear()
    await state.update_data(plan_id=pid, edit_field='pricing_currency_price', target_pricing_currency=currency)
    await state.set_state(EditPlan.value)
    prompt = '💵 قیمت جدید پلن را به دلار وارد کنید. مثال: 4.99' if currency == 'USD' else '💰 قیمت جدید پلن را به تومان وارد کنید:'
    sent = await ui_callback_message(callback, prompt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f'plan:detail:{pid}')]]))
    await state.update_data(last_bot_message_id=sent.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith('plan:set_group:'))
async def set_plan_group(callback: CallbackQuery, state: FSMContext):
    if not admin(callback.from_user.id):
        return
    parts = callback.data.split(':')
    try:
        pid = int(parts[2])
        idx = int(parts[3])
    except Exception:
        await callback.answer("انتخاب گروه معتبر نیست.", show_alert=True)
        return
    data = await state.get_data()
    names = list(data.get('available_group_names') or [])
    selected = names[idx] if 0 <= idx < len(names) else ''
    async with SessionLocal() as session:
        plan = await session.get(Plan, pid)
        if not plan:
            await state.clear()
            await callback.answer("پلن پیدا نشد.", show_alert=True)
            return
        meta = dict(plan.meta or {})
        if selected:
            meta['group_name'] = selected
        else:
            meta.pop('group_name', None)
        plan.meta = meta
        await session.commit()
    await state.clear()
    await edit_or_answer(callback, "✅ گروه پلن ذخیره شد.\n\n" + await plan_detail_text(pid), reply_markup=plan_detail_keyboard(pid))
    await callback.answer("گروه پلن تغییر کرد.")


@router.message(EditPlan.value)
async def save_plan_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = int(data["plan_id"])
    field = data["edit_field"]
    raw = message.text.strip()
    try:
        async with SessionLocal() as session:
            p = await session.get(Plan, pid)
            if not p:
                await state.clear()
                await ui_message(message, "❌ پلن پیدا نشد.", reply_markup=await plans_keyboard())
                return
            if field == "title":
                p.title = raw
            elif field == "price":
                if plan_currency(p) == 'USD':
                    meta = update_plan_pricing_meta(dict(p.meta or {}), pricing_currency='USD', price_usd=raw.replace(',', ''))
                    p.meta = meta
                    p.price_irt = 0
                else:
                    value = int(raw.replace(",", ""))
                    if value < 0:
                        raise ValueError
                    p.price_irt = value
            elif field == "pricing_currency_price":
                target_currency = str(data.get('target_pricing_currency') or 'IRT').upper()
                if target_currency == 'USD':
                    p.meta = update_plan_pricing_meta(dict(p.meta or {}), pricing_currency='USD', price_usd=raw.replace(',', ''))
                    p.price_irt = 0
                else:
                    value = int(raw.replace(",", ""))
                    if value < 0:
                        raise ValueError
                    p.meta = update_plan_pricing_meta(dict(p.meta or {}), pricing_currency='IRT', price_usd='0')
                    p.price_irt = value
            elif field == "volume":
                p.volume_gb = int(raw)
                p.is_unlimited = (p.volume_gb <= 0)
            elif field == "duration":
                p.duration_days = int(raw)
            elif field == "hwid":
                value = int(raw)
                if value < 0:
                    raise ValueError
                server = await session.get(Server, p.server_id) if p.server_id else None
                if not server or str(server.server_type or '').lower() not in {'xui', 'pasarguard'}:
                    await state.clear()
                    await ui_message(message, "❌ HWID فقط برای پلن‌های 3x-ui و PasarGuard قابل تنظیم است.", reply_markup=plan_detail_keyboard(pid))
                    return
                old_hwid_limit = max(int(getattr(p, 'hwid_limit', 0) or 0), 0)
                p.hwid_limit = value
            elif field == "inbounds":
                p.inbound_ids = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit() and int(x.strip()) != 0]
                meta = dict(p.meta or {})
                meta['inbound_mode'] = 'manual'
                p.meta = meta
            await session.commit()
        if field == "hwid" and value != old_hwid_limit:
            schedule_xui_plan_hwid_limit_sync(pid)
            schedule_pasarguard_plan_hwid_limit_sync(pid)
    except ValueError:
        await state_prompt(message, state, "❌ مقدار وارد شده معتبر نیست. دوباره فقط عدد/فرمت درست را وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_button(f"plan:detail:{pid}")]]))
        return
    await delete_state_message(message.bot, message.chat.id, state)
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await ui_message(message, "✅ تغییرات پلن ذخیره شد.\n\n" + await plan_detail_text(pid), reply_markup=plan_detail_keyboard(pid))
