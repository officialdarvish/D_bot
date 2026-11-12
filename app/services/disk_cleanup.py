"""Bounded cleanup of disposable D BOT files; no database access or host commands."""
from __future__ import annotations
import os
import json
import re
import stat
import tempfile
import time
from pathlib import Path
ARTIFACT_DIR = Path('/tmp/dbot-artifacts')
RETENTION_SECONDS = 7 * 24 * 60 * 60
BACKUP_RETENTION_SECONDS = 24 * 60 * 60
QUEUE_DIR = Path(os.environ.get('DBOT_UPDATE_DIR','/var/lib/dbot/update'))
MAX_SCAN = 10000
SUFFIXES = {'.png', '.ovpn', '.pdf', '.txt', '.json', '.dbot'}

def artifact_directory() -> str:
    ARTIFACT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = ARTIFACT_DIR.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise OSError('Unsafe temporary artifact directory')
    return str(ARTIFACT_DIR)

def temporary_artifact(*args, **kwargs):
    kwargs.update(dir=artifact_directory(), prefix='dbot-artifact-')
    return tempfile.NamedTemporaryFile(*args, **kwargs)

def artifact_mkstemp(*args, **kwargs):
    kwargs.update(dir=artifact_directory(), prefix='dbot-artifact-')
    return tempfile.mkstemp(*args, **kwargs)

def _active_update_files():
    try:
        fd=os.open(QUEUE_DIR/'status.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'r') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):return set()
            value=json.loads(stream.read(8192))
        if not isinstance(value,dict):return set()
        if value.get('state') not in {'checking','preparing_recovery','switching_source','backing_up','building','restarting','refreshing_agent'}:return set()
        names={Path(str(value.get('backup') or '')).name,'database-'+str(value.get('id',''))+'.sql'}
        if isinstance(value.get('started_at'),(int,float)):names.add('database-'+str(int(value['started_at']))+'.sql')
        return names
    except (OSError,ValueError,TypeError):return set()


def cleanup_artifacts(*, delete: bool = False) -> dict:
    groups={name:{'files':0,'bytes':0} for name in ('temporary_files','temporary_backups','update_backups')}
    skipped=0;now=time.time();active=_active_update_files()
    def scan(directory,queue=False):
        nonlocal skipped
        try:fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        except FileNotFoundError:return
        info=os.fstat(fd)
        if info.st_uid!=os.geteuid() or info.st_mode&0o022:os.close(fd);return
        try:
            with os.scandir(fd) as entries:
                for index,entry in enumerate(entries):
                    if index>=MAX_SCAN:break
                    if queue:
                        if not re.fullmatch(r'database-[a-f0-9-]{10,40}\.sql',entry.name) or entry.name in active:continue
                        kind='update_backups';age=BACKUP_RETENTION_SECONDS
                    else:
                        if not entry.name.startswith('dbot-artifact-') or Path(entry.name).suffix not in SUFFIXES:continue
                        kind='temporary_backups' if Path(entry.name).suffix in {'.dbot','.json'} else 'temporary_files'
                        age=BACKUP_RETENTION_SECONDS if kind=='temporary_backups' else RETENTION_SECONDS
                    try:
                        info=entry.stat(follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid():continue
                        if max(info.st_mtime,info.st_ctime)>now-age:continue
                        if delete:
                            current=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                            if (current.st_ino,current.st_mtime_ns,current.st_ctime_ns)!=(info.st_ino,info.st_mtime_ns,info.st_ctime_ns):skipped+=1;continue
                            os.unlink(entry.name,dir_fd=fd)
                        groups[kind]['files']+=1;groups[kind]['bytes']+=info.st_size
                    except OSError:skipped+=1
        finally:os.close(fd)
    scan(artifact_directory())
    scan(QUEUE_DIR,queue=True)
    return {'ok':True,'files':sum(v['files'] for v in groups.values()),'bytes':sum(v['bytes'] for v in groups.values()),'skipped':skipped,'retention_days':7,'backup_retention_hours':24,'groups':groups,'host_cleanup_interval_days':45}
