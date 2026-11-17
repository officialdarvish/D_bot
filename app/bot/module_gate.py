"""Enforce module switches on old Telegram callbacks and state messages too."""
from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message, CallbackQuery
from app.database.session import SessionLocal
from app.services.features import capabilities


class ModuleGate(BaseMiddleware):
    def __init__(self,module):self.module=module
    async def __call__(self,handler,event,data):
        # An old module FSM can match navigation before the main router does.
        # Let dispatch continue to the real start handler and its normal checks.
        if (isinstance(event, Message) and event.text
                and (event.text.split(maxsplit=1) or [''])[0].split('@', 1)[0] == '/start'):
            raise SkipHandler
        if isinstance(event, CallbackQuery) and event.data == 'restart:start':
            raise SkipHandler
        async with SessionLocal() as session:enabled=(await capabilities(session)).get(self.module,False)
        if not enabled:
            if hasattr(event,'answer'):
                await event.answer('این بخش غیرفعال است.' )
            return
        return await handler(event,data)


def install_module_gate(router, module: str) -> None:
    # Inner middleware runs only AFTER this router's handler filters match.
    # Outer middleware would swallow unrelated commands in later routers.
    router.message.middleware(ModuleGate(module))
    router.callback_query.middleware(ModuleGate(module))
