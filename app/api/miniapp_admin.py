import json
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import update
from app.api.admin_web import _auth_user, _telegram_validate_destination
from app.core.config import settings
from app.database.session import SessionLocal
from app.database.models import Setting, User
from app.bot.keyboards.common import invalidate_button_settings_cache
from app.database.settings_write import upsert_settings
from app.services.miniapp_copy import PREFIX, clean_overrides, read_overrides
from app.services.miniapp_settings import read_preferences, clean_config, support_username

router=APIRouter()


@router.get('/admin/api/v2/miniapp')
async def miniapp_settings(_:str=Depends(_auth_user)):
    async with SessionLocal() as s:
        config=await read_preferences(s)
        row=await s.get(Setting,'button_reseller_request_enabled')
        if row is not None:
            config['reseller_requests'] = row.value != '0'
    return {'ok':True,'config':config}


@router.post('/admin/miniapp/save')
async def save_miniapp(config_json:str=Form(...),_:str=Depends(_auth_user)):
    try:
        data=json.loads(config_json)
        if not isinstance(data,dict): raise ValueError('Invalid settings.')
        config=clean_config(data)
        name=support_username(data.get('support_username',''))
    except (ValueError,TypeError) as exc: raise HTTPException(400,str(exc))
    async with SessionLocal() as s:
        await upsert_settings(s, {
            'miniapp_config': json.dumps(config, ensure_ascii=False),
            'support_username': name,
            'button_reseller_request_enabled': '1' if config['reseller_requests'] else '0',
        })
        await s.commit()
    invalidate_button_settings_cache()
    warning=''
    try:
        from app.api.miniapp import telegram_bot
        from app.bot.miniapp import sync_menu_button
        async with telegram_bot() as bot:
            await sync_menu_button(bot)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Mini App menu sync will retry in bot')
        warning='Settings saved. Telegram menu will retry on /start or bot restart.'
    return {'ok':True,'message':warning or 'Mini App settings saved','menu_sync_pending':bool(warning)}


@router.get('/admin/api/v2/miniapp/texts')
async def miniapp_texts(_: str = Depends(_auth_user)):
    async with SessionLocal() as session:
        return {'ok': True, 'overrides': await read_overrides(session)}


@router.post('/admin/api/v2/miniapp/texts')
async def save_miniapp_texts(texts_json: str = Form(...), _: str = Depends(_auth_user)):
    try:
        changes = clean_overrides(json.loads(texts_json))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    async with SessionLocal() as session:
        await upsert_settings(session, {PREFIX + key: value for key, value in changes.items()})
        await session.commit()
    return {'ok': True, 'changes': changes}


@router.post('/admin/settings/rules')
async def save_rules(enabled:str=Form('0'),rules_text:str=Form(''),_:str=Depends(_auth_user)):
    text=rules_text.strip()
    if enabled=='1' and not text: raise HTTPException(400,'Rules text cannot be empty.')
    async with SessionLocal() as s:
        old=await s.get(Setting,'rules_text')
        changed=not old or old.value!=text
        await s.merge(Setting(key='rules_enabled',value='1' if enabled=='1' else '0'))
        await s.merge(Setting(key='rules_text',value=text))
        if changed and enabled=='1': await s.execute(update(User).values(accepted_rules=False))
        await s.commit()
    return {'ok':True,'message':'Rules saved'}


@router.post('/admin/settings/force-join')
async def save_force_join(enabled:str=Form('0'),channel_url:str=Form(''),_:str=Depends(_auth_user)):
    channel=channel_url.strip()
    if enabled=='1':
        if not channel: raise HTTPException(400,'Enter the channel address.')
        check=await _telegram_validate_destination(settings.BOT_TOKEN,channel,'channel',send_test=False)
        if not check.get('ok'): raise HTTPException(400,'The bot must be an administrator of the selected channel.')
    async with SessionLocal() as s:
        await s.merge(Setting(key='force_join_enabled',value='1' if enabled=='1' else '0'))
        await s.merge(Setting(key='channel_url',value=channel))
        await s.commit()
    return {'ok':True,'message':'Required membership saved'}
