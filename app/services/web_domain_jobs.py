"""Send a hostname-only job to the existing VPS worker."""
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from app.core.web_domain import normalize_domain
from app.services.web_update import QUEUE, host_ready, queue_json

REQUEST = 'domain-request.json'
STATUS = 'domain-status.json'


def host_supports_domains():
    try:
        return host_ready() and 0 <= time.time() - (QUEUE / 'domain-ready').stat().st_mtime < 60
    except OSError:
        return False


def status():
    try:
        current = queue_json(QUEUE / STATUS)
    except (OSError, ValueError):
        current = {'state': 'idle'}
    try:
        pending = queue_json(QUEUE / REQUEST)
        if pending.get('id') != current.get('id'):
            return {**pending, 'state': 'queued'}
    except (OSError, ValueError):
        pass
    return current


def enqueue(domain):
    domain = normalize_domain(domain)
    if not host_supports_domains():
        raise ValueError('VPS SSL worker is unavailable. Run sudo dbot update on the VPS / اجراکننده SSL در دسترس نیست؛ روی VPS دستور sudo dbot update را اجرا کنید')
    job = {'id': uuid.uuid4().hex, 'domain': domain}
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix='.domain-', dir=QUEUE)
        with os.fdopen(fd, 'w') as out:
            json.dump(job, out)
            out.flush()
            os.fsync(out.fileno())
        os.link(name, QUEUE / REQUEST, follow_symlinks=False)
    except FileExistsError:
        raise ValueError('A domain change is already queued or running / یک تغییر دامنه در صف یا در حال اجراست') from None
    except OSError:
        raise ValueError('Could not send domain request to the VPS / ارسال درخواست دامنه به VPS انجام نشد') from None
    finally:
        if name:
            Path(name).unlink(missing_ok=True)
    return {**job, 'state': 'queued'}
