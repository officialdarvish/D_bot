"""Run established bot workflows without generating chat prompts for Mini App users.

Only the owner of the current request is silenced. Administrator notifications
continue through the actual bot; completed subscription delivery is explicit.
"""
from datetime import datetime, timezone
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Message,Chat,User,CallbackQuery

class NativeState:
    def __init__(self,data=None):self.data=dict(data or {})
    async def get_data(self):return dict(self.data)
    async def update_data(self,**kwargs):self.data.update(kwargs);return dict(self.data)
    async def set_state(self,value):pass
    async def clear(self):pass

class QuietSession(BaseSession):
    def __init__(self,real,tid):
        super().__init__();self.real=real;self.tid=tid;self.texts=[]
    async def close(self):pass
    async def stream_content(self,*args,**kwargs):
        async for chunk in self.real.session.stream_content(*args,**kwargs):yield chunk
    async def make_request(self,bot,method,timeout=None):
        target=getattr(method,'chat_id',None)
        if target in (self.tid,-self.tid) or method.__api_method__=='answerCallbackQuery':
            text=getattr(method,'text',None) or getattr(method,'caption',None)
            if text:self.texts.append(str(text))
            if method.__api_method__.startswith(('delete','answer')):return True
            return Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=-self.tid,type='private'),text=str(text or '')).as_(bot)
        return await self.real(method,request_timeout=timeout)

def native_event(real,user,text='',data=''):
    session=QuietSession(real,user.telegram_id)
    bot=Bot(real.token,session=session)
    actor=User(id=user.telegram_id,is_bot=False,first_name=user.full_name or 'Mini App',username=user.username)
    message=Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=-user.telegram_id,type='private'),from_user=actor,text=text).as_(bot)
    cb=CallbackQuery(id='miniapp',from_user=actor,chat_instance='miniapp',message=message,data=data).as_(bot)
    return message,cb,session


async def is_native_receipt(session,user_id,typ,rid):
    from sqlalchemy import select
    from app.database.models import MiniAppOperation
    return bool(await session.scalar(select(MiniAppOperation.id).where(MiniAppOperation.user_id==user_id,MiniAppOperation.result['target_type'].as_string()==typ,MiniAppOperation.result['target_id'].as_integer()==rid).limit(1)))
