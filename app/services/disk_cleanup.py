"""Bounded cleanup of disposable D BOT files; no database access or host commands."""
from __future__ import annotations
import os
import stat
import tempfile
import time
from pathlib import Path
ARTIFACT_DIR = Path('/tmp/dbot-artifacts')
RETENTION_SECONDS = 7 * 24 * 60 * 60
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

def cleanup_artifacts(*, delete: bool = False) -> dict:
    count = size = skipped = 0
    deadline = time.time() - RETENTION_SECONDS
    fd = os.open(artifact_directory(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with os.scandir(fd) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_SCAN: break
                if not entry.name.startswith('dbot-artifact-') or Path(entry.name).suffix not in SUFFIXES: continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid(): continue
                    if max(info.st_mtime, info.st_ctime) > deadline: continue
                    if delete:
                        current = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                        if (current.st_ino,current.st_mtime_ns,current.st_ctime_ns)!=(info.st_ino,info.st_mtime_ns,info.st_ctime_ns):
                            skipped += 1; continue
                        os.unlink(entry.name,dir_fd=fd)
                    count += 1; size += info.st_size
                except OSError: skipped += 1
    finally: os.close(fd)
    return {'ok':True,'files':count,'bytes':size,'skipped':skipped,'retention_days':7}
