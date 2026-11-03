"""Owner-only Telegram Mini App bridge to the complete existing admin panel."""
import secrets
from datetime import timedelta
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.services.miniapp_auth import validate_init_data
from app.services.web_access import read_web_path
from app.api.admin_web import _sessions, _now, db_setting, _request_is_same_origin

router=APIRouter()

@router.post('/api/miniapp/admin-session')
async def admin_session(request:Request,x_telegram_init_data:str=Header(default='')):
    if not _request_is_same_origin(request):raise HTTPException(403,'Cross-site request blocked')
    try:identity=validate_init_data(x_telegram_init_data,settings.BOT_TOKEN,max_age=600)
    except (ValueError,TypeError,KeyError):raise HTTPException(401,'مینی‌اپ مدیریت را دوباره از ربات باز کنید.')
    if identity['id'] not in settings.admin_ids:raise HTTPException(403,'این بخش فقط برای مالک ربات است.')
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);now=_now()
    version=await db_setting('web_credentials_updated_at','')
    _sessions[token]={'username':f'telegram-owner:{identity["id"]}','telegram_owner_id':identity['id'],
        'created_at':now,'expires_at':now+timedelta(minutes=20),'csrf':csrf,'credential_version':version}
    prefix='/'+await read_web_path()
    setup=await db_setting('initial_setup_done','0')
    res=JSONResponse({'ok':True,'url':prefix+('/admin' if setup=='1' else '/setup')+'?miniapp=1'},headers={'Cache-Control':'no-store'})
    secure=request.url.scheme=='https' or (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip()=='https'
    common=dict(max_age=1200,secure=secure,samesite='strict',path='/')
    res.set_cookie('dbot_admin_token',token,httponly=True,**common)
    res.set_cookie('dbot_csrf_token',csrf,httponly=False,**common)
    return res
