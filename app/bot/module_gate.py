"""Enforce module switches on old Telegram callbacks and state messages too."""
from aiogram import BaseMiddleware
from app.database.session import SessionLocal
from app.services.features import capabilities


class ModuleGate(BaseMiddleware):
    def __init__(self,module):self.module=module
    async def __call__(self,handler,event,data):
        async with SessionLocal() as session:enabled=(await capabilities(session)).get(self.module,False)
        if not enabled:
            if hasattr(event,'answer'):
                await event.answer('این بخش غیرفعال است.' )
            return
        return await handler(event,data)
