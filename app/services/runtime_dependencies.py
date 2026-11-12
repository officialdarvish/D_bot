"""Declarative optional dependency selection; only the host worker can rebuild."""
import json,os,tempfile,uuid
from app.services.web_update import QUEUE


def request_runtime(xray: bool):
    if type(xray) is not bool:raise ValueError('Invalid runtime selection')
    QUEUE.mkdir(mode=0o700,parents=True,exist_ok=True)
    value={'id':uuid.uuid4().hex,'xray':xray}
    fd,name=tempfile.mkstemp(prefix='.runtime-',dir=QUEUE)
    try:
        with os.fdopen(fd,'w') as out:json.dump(value,out)
        os.replace(name,QUEUE/'desired-runtime.json')
    finally:
        if os.path.exists(name):os.unlink(name)
    return value
