#!/usr/bin/env python3
"""Read-only VPS/container memory diagnostics. Never reads .env or user data."""
import json,subprocess
from pathlib import Path


def report():
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,_,value=line.partition(':')
        if key in {'MemTotal','MemAvailable','SwapTotal','SwapFree'}:memory[key+'_MiB']=round(int(value.split()[0])/1024,1)
    result={'scope':'whole VPS; container figures below are separate','host':memory,'containers':[]}
    try:
        ids=subprocess.run(['docker','compose','ps','-q'],check=True,capture_output=True,text=True,timeout=15).stdout.split()
        if ids:
            rows=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',*ids],check=True,capture_output=True,text=True,timeout=20).stdout
            for line in rows.splitlines():
                value=json.loads(line)
                result['containers'].append({k:value.get(k) for k in ('Name','ID','MemUsage','MemPerc','CPUPerc','PIDs')})
            for container in ids:
                # Report inspect state independently: docker stats may reorder rows.
                state=subprocess.run(['docker','inspect','--format','{{json .State}}',container],check=True,capture_output=True,text=True,timeout=10)
                value=json.loads(state.stdout)
                result.setdefault('states',[]).append({'container':container[:12],'oom_killed':bool(value.get('OOMKilled')),'exit_code':value.get('ExitCode')})
    except (OSError,ValueError,subprocess.SubprocessError):result['docker_error']='Docker statistics unavailable; run as root from the D BOT directory.'
    return result


if __name__=='__main__':print(json.dumps(report(),ensure_ascii=False,indent=2))
