#!/usr/bin/env python3
"""Find public forks and indexed copies retaining the project marker.

Matches are evidence of shared origin, not proof of a license violation.
Copies with removed markers, private repositories and unindexed code can be missed.
"""
import base64,json,os,urllib.request,urllib.error,urllib.parse
from pathlib import Path

CANONICAL='officialdarvish/D_bot'


def get(path):
    token=os.getenv('GH_TOKEN','')
    headers={'Accept':'application/vnd.github+json','User-Agent':'D-BOT-origin-check'}
    if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com'+path,headers=headers),timeout=15) as r:return json.load(r)


def scan():
    origin=json.loads(Path('ORIGIN.json').read_text());marker=origin['source_identity']
    if not marker:raise ValueError('Origin marker missing')
    found={};warnings=[]
    for page in range(1,11):
        try:rows=get(f'/repos/{CANONICAL}/forks?per_page=100&page={page}&sort=newest')
        except (urllib.error.URLError,ValueError):warnings.append('Fork listing incomplete');break
        for row in rows:found[row['full_name']]={'repository':row['full_name'],'url':row['html_url'],'evidence':'GitHub fork relationship'}
        if len(rows)<100:break
    try:
        data=get('/search/code?q='+urllib.parse.quote('"'+marker+'" filename:ORIGIN.json')+'&per_page=100')
        for item in data.get('items',[]):
            repo=item['repository'];name=repo['full_name']
            if name!=CANONICAL:found[name]={'repository':name,'url':repo['html_url'],'evidence':'Indexed origin marker','file_url':item['html_url']}
        if data.get('incomplete_results') or data.get('total_count',0)>100:warnings.append('Code search incomplete')
    except (urllib.error.URLError,ValueError):warnings.append('Code search unavailable; fork results only')
    return {'canonical':CANONICAL,'matches':sorted(found.values(),key=lambda x:x['repository']),'warnings':warnings,'limitations':'Private, unindexed, and marker-removed copies may not be detected. A match is not proof of misuse.'}


if __name__=='__main__':
    report=scan();Path('source-origin-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(f'Found {len(report["matches"])} public origin match(es); {len(report["warnings"])} coverage warning(s).')
