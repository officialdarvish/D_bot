from __future__ import annotations

import tempfile

from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.database.session import SessionLocal
from app.database.models import ClientService, Server, Plan, OpenVPNProfile


OPENVPN_PROFILE_CAPTION = """📥 پروفایل OpenVPN سرور شما

📲 آموزش اضافه کردن کانفیگ OpenVPN

1️⃣ برنامه <b>OpenVPN Connect</b> رو باز کنید
2️⃣ روی گزینه <b>Import Profile</b> یا <b>Upload File</b> بزنید
3️⃣ وارد بخش <b>File</b> بشید
4️⃣ فایل کانفیگ با فرمت <code>.ovpn</code> رو انتخاب کنید
5️⃣ روی گزینه <b>Add</b> بزنید
6️⃣ تیک گزینه <b>Save Password</b> رو فعال کنید
7️⃣ اطلاعات <b>Username / Password / Private Key</b> رو وارد کنید
8️⃣ دکمه اتصال رو فعال کنید ✅"""


def profile_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🏠 خانه', callback_data='home:main')]])


async def find_openvpn_profile(session, service: ClientService, server: Server | None, plan: Plan | None) -> OpenVPNProfile | None:
    pid = 0
    for source in ((plan.meta if plan else None) or {}, (server.meta if server else None) or {}):
        try:
            pid = int(source.get('openvpn_profile_id') or pid or 0)
        except Exception:
            pass
    prof = await session.get(OpenVPNProfile, pid) if pid else None
    if not prof and server:
        prof = (
            await session.execute(
                select(OpenVPNProfile)
                .where(OpenVPNProfile.server_id == server.id, OpenVPNProfile.is_active == True)
                .order_by(OpenVPNProfile.id.desc())
            )
        ).scalar_one_or_none()
    return prof


async def send_openvpn_profile_document(bot, chat_id: int, service_id: int, caption: str | None = None, reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    async with SessionLocal() as session:
        svc = await session.get(ClientService, int(service_id))
        if not svc:
            return False
        server = await session.get(Server, svc.server_id) if svc.server_id else None
        plan = await session.get(Plan, svc.plan_id) if svc.plan_id else None
        prof = await find_openvpn_profile(session, svc, server, plan)
        if not prof:
            return False
        path = tempfile.NamedTemporaryFile(delete=False, suffix='.ovpn').name
        with open(path, 'w', encoding='utf-8') as f:
            f.write(prof.content or '')
        file_name = prof.file_name or f'{prof.name}.ovpn'
    await bot.send_document(
        chat_id,
        FSInputFile(path, filename=file_name),
        caption=caption or OPENVPN_PROFILE_CAPTION,
        parse_mode='HTML',
        reply_markup=reply_markup or profile_home_keyboard(),
    )
    return True
