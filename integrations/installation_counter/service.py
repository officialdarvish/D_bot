"""Anonymous active-installation aggregate. Never expose installation records."""
from contextlib import closing
import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import JSONResponse
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
DATABASE=Path(os.environ.get('COUNTER_DATABASE','/data/count.sqlite'))
ACTIVE_SECONDS=900

def connect():
    DATABASE.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATABASE,timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS installations (token_hash TEXT PRIMARY KEY, seen INTEGER NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS seen_idx ON installations(seen)')
    return db

@app.post('/heartbeat')
async def heartbeat(request:Request):
    # Bounded body: no personal or server metadata accepted or persisted.
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>128:raise HTTPException(413,'Body too large')
    try:token=data.decode('ascii')
    except UnicodeDecodeError:raise HTTPException(422,'Invalid token')
    if not re.fullmatch(r'[0-9a-f]{64}',token):raise HTTPException(422,'Invalid token')
    now=int(time.time());digest=hashlib.sha256(token.encode()).hexdigest()
    with closing(connect()) as db:
        db.execute('INSERT INTO installations VALUES (?,?) ON CONFLICT(token_hash) DO UPDATE SET seen=excluded.seen',(digest,now))
        db.execute('DELETE FROM installations WHERE seen<?',(now-86400,))
        db.commit()
    return {'ok':True}

@app.get('/count')
def count():
    with closing(connect()) as db:
        n=db.execute('SELECT COUNT(*) FROM installations WHERE seen>=?',(int(time.time())-ACTIVE_SECONDS,)).fetchone()[0]
    return JSONResponse({'ok':True,'count':n,'active_window_seconds':ACTIVE_SECONDS},headers={'Cache-Control':'public, max-age=60'})
