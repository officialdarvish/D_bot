#!/usr/bin/env python3
"""Read-only disk inventory; no user records or secrets are read."""
import json,shutil,subprocess
from pathlib import Path


def report():
    usage=shutil.disk_usage('.')
    result={'filesystem':{'total_bytes':usage.total,'used_bytes':usage.used,'free_bytes':usage.free},'update_files':{},'docker':[]}
    queue=Path('.web-update')
    for pattern,label in [('database-*.sql','temporary_update_backups'),('update-*.log','update_logs')]:
        files=[p for p in queue.glob(pattern) if p.is_file() and not p.is_symlink()]
        result['update_files'][label]={'files':len(files),'bytes':sum(p.stat().st_size for p in files)}
    try:
        raw=subprocess.run(['docker','system','df','--format','{{json .}}'],capture_output=True,text=True,check=True,timeout=30).stdout
        result['docker']=[json.loads(line) for line in raw.splitlines()]
    except Exception:result['docker_error']='Docker disk inventory unavailable'
    return result


if __name__=='__main__':print(json.dumps(report(),indent=2))
