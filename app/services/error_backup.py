"""Forward runtime ERROR logs (including tracebacks) to the configured backup target."""
import asyncio,contextvars,hashlib,logging,os,re,tempfile,time,traceback

_delivering=contextvars.ContextVar('sending_error_backup',default=False)
_seen={}
_tasks=set()


def redact(text):
    from app.core.config import settings
    for value in [settings.BOT_TOKEN,settings.DATABASE_URL,settings.JWT_SECRET,settings.FERNET_KEY]:
        if value:text=text.replace(str(value),'[REDACTED]')
    text=re.sub(r'https?://[^\s\"\'<>]+','[URL REDACTED]',text)
    text=re.sub(r'happ://[^\s<>]+','[SUBSCRIPTION REDACTED]',text)
    text=re.sub(r'(?i)(password|authorization|api[_-]?key|token)([\s\"\']*[:=][\s\"\']*)[^\s,}\"\']+',r'\1\2[REDACTED]',text)
    return text

async def send_error_log(text):
    token=_delivering.set(True)
    path=''
    try:
        from app.api.admin_web import _settings_map,_effective_backup_chat_id,_telegram_token,_telegram_send_backup
        values=await _settings_map();destination=values.get('backup_destination') or 'channel'
        target=_effective_backup_chat_id(destination,values.get('backup_chat_id') or values.get('backup_channel') or '',values)
        bot_token=await _telegram_token(values)
        if not target or not bot_token:return
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.txt',delete=False) as f:
            f.write(redact(text));path=f.name
        await _telegram_send_backup(bot_token,target,path,destination,caption='🚨 گزارش خطای D Bot · جزئیات در فایل پیوست',filename='dbot-error-log.txt',content_type='text/plain')
    except Exception:
        # Never report a failure to report itself.
        pass
    finally:
        if path:
            try:os.unlink(path)
            except OSError:pass
        _delivering.reset(token)

class ErrorBackupHandler(logging.Handler):
    def __init__(self):super().__init__(logging.ERROR)
    def emit(self,record):
        if _delivering.get():return
        try:
            loop=asyncio.get_running_loop()
            text=self.format(record)
            signature=hashlib.sha256(text.encode()).hexdigest();now=time.monotonic()
            if now-_seen.get(signature,0)<30:return
            _seen[signature]=now
            if len(_seen)>2000:
                for key in list(_seen):
                    if now-_seen[key]>300:_seen.pop(key,None)
            if len(_tasks)>=100:return
            task=loop.create_task(send_error_log(text));_tasks.add(task);task.add_done_callback(_tasks.discard)
        except Exception:pass

def install_error_backup():
    root=logging.getLogger()
    if not any(isinstance(h,ErrorBackupHandler) for h in root.handlers):
        handler=ErrorBackupHandler();handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s\n%(message)s'));root.addHandler(handler)
