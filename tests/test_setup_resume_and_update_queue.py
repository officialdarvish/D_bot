import ast
import json
import os
import stat
import tempfile
from pathlib import Path
import pytest
from app.services.setup_steps import staged
from app.services import tutorial_video


def test_wizard_has_real_conditional_forms_and_resume():
    source='<html><head></head><body><main><form><div class="steps"><section class="step"></section></div><div class="actions"><button class="btn" type="submit">Save</button></div></form></main></body></html>'
    result=staged(source,{'setup_step':'7'},'/private','csrf',[])
    assert 'let index=7' in result
    for section in ('plans','payments','servers','resellers','test-account','openvpn-profiles','settings','backup','miniapp','connection'):
        assert f'/private/setup/options/{section}' in result
    assert 'data-feature="resellers"' in result and 'data-feature="openvpn"' in result
    assert '/setup/progress' in result and 'dbot-setup-dirty' in result
    assert 'data-server="password"' in result and 'name="password"' not in result


def test_privileged_worker_rejects_symlinked_queue_files(tmp_path):
    tree=ast.parse(Path('scripts/web-update-worker.py').read_text())
    helpers=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'read_json','write_json'}]
    ns=dict(os=os,stat=stat,tempfile=tempfile,json=json,Path=Path,QUEUE=tmp_path)
    exec(compile(ast.Module(body=helpers,type_ignores=[]),'worker','exec'),ns)
    victim=tmp_path/'host-secret';victim.write_text('{"secret":"sensitive"}')
    request=tmp_path/'request.json';request.symlink_to(victim)
    with pytest.raises(OSError):ns['read_json'](request)
    status=tmp_path/'status.json';status.symlink_to(victim)
    ns['write_json'](status,{'state':'completed'})
    assert json.loads(victim.read_text())=={'secret':'sensitive'}
    assert not status.is_symlink() and json.loads(status.read_text())=={'state':'completed'}
    assert stat.S_IMODE(status.stat().st_mode)==0o600


def test_tutorial_media_urls_are_short_lived_and_user_bound(monkeypatch):
    monkeypatch.setattr(tutorial_video.settings,'BOT_TOKEN','123456:TEST_TOKEN')
    monkeypatch.setattr(tutorial_video.time,'time',lambda:1000)
    token=tutorial_video.signature('abc',5,1300)
    assert tutorial_video.validate('abc',5,1300,token)
    assert not tutorial_video.validate('abc',6,1300,token)
    assert not tutorial_video.validate('abc',5,1301,token)
    assert not tutorial_video.validate('abc',5,999,token)


def test_runtime_selection_is_allowlisted_and_skips_unchanged_build(tmp_path):
    import re,time
    app=tmp_path/'app';app.mkdir();queue=app/'.web-update';queue.mkdir()
    (app/'.env').write_text('BOT_TOKEN=keep\nXRAY_SOURCE=disabled\n')
    value={'id':'a'*32,'xray':True};(queue/'desired-runtime.json').write_text(json.dumps(value))
    tree=ast.parse(Path('scripts/web-update-worker.py').read_text())
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'read_json','write_json','write_env','apply_runtime'}]
    calls=[]
    ns=dict(os=os,stat=stat,tempfile=tempfile,json=json,Path=Path,QUEUE=queue,APP=app,re=re,time=time,state=lambda *a,**k:None,run=lambda *a,**k:calls.append(a[0]),healthy=lambda:True)
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'worker','exec'),ns)
    ns['apply_runtime']();ns['apply_runtime']()
    assert calls==[['docker','compose','build'],['docker','compose','up','-d']]
    assert (app/'.env').read_text()=='BOT_TOKEN=keep\nXRAY_SOURCE=image\n'
    value['id']='b'*32;(queue/'desired-runtime.json').write_text(json.dumps(value));ns['apply_runtime']()
    assert len(calls)==2
    value['xray']='image; touch /tmp/pwned';(queue/'desired-runtime.json').write_text(json.dumps(value))
    with pytest.raises(ValueError):ns['apply_runtime']()
