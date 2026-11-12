import asyncio
import gc
import hashlib
import json
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.bot import ui_navigation as ui
from app.services.media_stream import MediaFile


@pytest.mark.asyncio
async def test_350_healthy_redis_users_do_not_keep_duplicate_local_histories(monkeypatch):
    store={}
    async def save(k,value,**kwargs):store[k]=value
    async def get(k):return store.get(k)
    monkeypatch.setattr(ui,'_redis',SimpleNamespace(set=save,get=get))
    monkeypatch.setattr(ui,'_memory',{})
    bot=SimpleNamespace(id=42)
    for user in range(350):
        record={'active':None,'terminal':[],'history':[]}
        await ui.save_ui(bot,user,record)
    assert len(store)==350 and not ui._memory
    assert (await ui.load_ui(bot,100))['active'] is None


@pytest.mark.asyncio
async def test_redis_outage_fallback_expires_and_recovers(monkeypatch):
    monkeypatch.setattr(ui,'_memory',{})
    redis=SimpleNamespace(set=AsyncMock(side_effect=ConnectionError),get=AsyncMock(side_effect=ConnectionError))
    monkeypatch.setattr(ui,'_redis',redis)
    bot=SimpleNamespace(id=42);record={'active':{'id':91},'terminal':[],'history':[]}
    await ui.save_ui(bot,5,record);assert (await ui.load_ui(bot,5))['active']['id']==91
    redis.set=AsyncMock();await ui.save_ui(bot,5,record);assert not ui._memory
    monkeypatch.setattr(ui,'_redis',None)
    await ui.save_ui(bot,6,record)
    for value in ui._memory.values():value['_saved_at']=1
    assert (await ui.load_ui(bot,6))['active'] is None and not ui._memory


@pytest.mark.asyncio
async def test_navigation_locks_serialize_waiters_then_release_memory():
    ui._locks.clear();value=0
    async def operation():
        nonlocal value
        lock=ui._locks.setdefault('memory-test',asyncio.Lock())
        async with lock:
            before=value;await asyncio.sleep(0);value=before+1
    await asyncio.gather(*(operation() for _ in range(100)))
    gc.collect();assert value==100 and 'memory-test' not in ui._locks


def test_video_storage_is_disk_backed_bounded_and_chunked():
    media=MediaFile(12*1024**2)
    block=b'x'*65536
    tracemalloc.start()
    for _ in range(192):media.write(block)
    media.seek(0);total=0
    for chunk in media.chunks():assert len(chunk)<=65536;total+=len(chunk)
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert total==12*1024**2 and peak<1024**2 and media.closed
    media=MediaFile(4)
    try:
        with pytest.raises(ValueError):media.write(b'12345')
        assert media.tell()==0
    finally:media.close()


def test_zero_overflow_is_respected_and_sqlite_omits_queue_pool_options(monkeypatch):
    from app.database import session as db
    monkeypatch.setattr(db.settings,'DATABASE_URL','postgresql+asyncpg://localhost/test')
    monkeypatch.setattr(db.settings,'DB_POOL_SIZE',3);monkeypatch.setattr(db.settings,'DB_MAX_OVERFLOW',0)
    options=db._engine_kwargs();assert options['pool_size']==3 and options['max_overflow']==0 and options['pool_use_lifo']
    monkeypatch.setattr(db.settings,'DATABASE_URL','sqlite+aiosqlite:///:memory:')
    assert 'pool_size' not in db._engine_kwargs()


def test_optimized_qr_has_identical_pixels_to_previous_release():
    from pathlib import Path
    from PIL import Image
    from app.bot.qr_card import make_qr_card
    path=Path(make_qr_card('https://example.com/sub/test-350'))
    try:
        with Image.open(path) as image:
            assert hashlib.sha256(image.tobytes()).hexdigest()=='5bfebae65a1f600010354dc88b8dc05ddd17b85a772067d3c28c68ce2de33485'
    finally:path.unlink(missing_ok=True)


def test_runtime_services_share_one_built_image():
    import yaml
    from pathlib import Path
    services=yaml.safe_load(Path('docker-compose.yml').read_text())['services']
    assert services['api']['image']==services['bot']['image']
    assert 'build' in services['api'] and 'build' not in services['bot']
