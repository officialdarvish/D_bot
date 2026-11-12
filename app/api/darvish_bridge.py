"""Authenticated Bridge settings and signed payment events."""
import json
from fastapi import APIRouter,Depends,Request,HTTPException
from app.api.admin_web import _auth_user
from app.database.session import SessionLocal
from app.database.models import Setting
from app.core.security import encrypt_text
from app.services import darvish_bridge as bridge

router=APIRouter()


@router.get('/admin/api/v2/darvish-bridge')
async def bridge_settings(_:str=Depends(_auth_user)):
    async with SessionLocal() as session:value=await bridge.config(session)
    return {'ok':True,'config':{**{k:value.get(k,'') for k in ('enabled','url','bot_username')},'currency':'IRT'},'requires_toman_setup':bool(value.get('requires_toman_setup')),'key_saved':bool(value.get('key')),'secret_saved':bool(value.get('secret'))}


@router.post('/admin/darvish-bridge/save')
async def save_bridge(request:Request,_:str=Depends(_auth_user)):
    form=await request.form()
    async with SessionLocal() as session:
        try:
            value=bridge.normalize(dict(form),await bridge.config(session))
            if value['enabled']:
                capabilities=await bridge.request(value,'GET','/capabilities')
                if 'digital' not in capabilities.get('product_kinds',[]) or type(capabilities.get('currencies',{}).get('IRT')) is not int or capabilities.get('currencies',{}).get('IRT')!=0:raise ValueError('Bridge does not support the selected digital payment capability')
        except (ValueError,KeyError):raise HTTPException(422,'Bridge settings or capabilities are invalid; verify the companion configuration.')
        except Exception:raise HTTPException(502,'Bridge connection failed')
        await session.merge(Setting(key=bridge.KEY,value=encrypt_text(json.dumps(value))))
        await session.commit()
    return {'ok':True}


@router.post('/webhooks/darvish-bridge')
async def bridge_webhook(request:Request):
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>16384:raise HTTPException(413)
        chunks.append(chunk)
    async with SessionLocal() as session:
        try:return await bridge.receive_event(session,b''.join(chunks),request.headers.get('X-Darvish-Timestamp',''),request.headers.get('X-Darvish-Signature',''),request.headers.get('X-Darvish-Event-ID',''))
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'Bridge event not accepted')
        except Exception:raise HTTPException(503,'Bridge verification unavailable; retry later')
