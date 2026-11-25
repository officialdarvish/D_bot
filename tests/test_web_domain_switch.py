import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import admin_web
from app.core.web_domain import normalize_domain
from app.services import web_access, web_domain_jobs, web_update
from test_miniapp import client

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('value', ['a..example.com', '127.0.0.1', 'https://example.com:443',
                                   'example.com/x', 'https://person@example.com', 'exa\tmple.com', 'example.com?flag=1'])
def test_domain_jobs_reject_values_that_are_not_hostnames(value):
    with pytest.raises(ValueError):
        normalize_domain(value)


def test_web_panel_queues_then_publishes_domain_only_after_host_confirmation(client, tmp_path, monkeypatch):
    _, sessions = client
    monkeypatch.setattr(web_domain_jobs, 'QUEUE', tmp_path)
    monkeypatch.setattr(web_update, 'QUEUE', tmp_path)
    monkeypatch.setattr(web_access, '_new_session', sessions)
    monkeypatch.setattr(admin_web, 'SessionLocal', sessions)
    for marker in ('ready', 'domain-ready'):
        (tmp_path / marker).touch()
    asyncio.run(web_access.save_web_domain('old.example.com', 'https', 443))
    app = FastAPI()
    app.include_router(admin_web.router)
    app.dependency_overrides[admin_web._auth_user] = lambda: 'owner'
    api = TestClient(app)
    headers = {'X-Requested-With': 'XMLHttpRequest'}
    action = '/admin/settings/ssl/apply'
    status = '/admin/api/v2/settings/ssl'

    submitted = api.post(action, data={'domain': ' HTTPS://New.Example.com/ '}, headers=headers)
    assert submitted.status_code == 200, submitted.text
    job = json.loads((tmp_path / 'domain-request.json').read_text())
    assert job['domain'] == 'new.example.com'
    assert api.post(action, data={'domain': 'second.example.com'}, headers=headers).status_code == 400
    assert api.get(action).status_code == 405
    assert api.get(status).json()['job']['state'] == 'queued'
    assert (asyncio.run(web_access.read_web_access())).login_url == 'https://old.example.com/dbot/login'

    (tmp_path / 'domain-status.json').write_text(json.dumps({**job, 'state': 'failed', 'reason': 'certificate'}))
    (tmp_path / 'domain-request.json').unlink()
    assert api.get(status).json()['job']['reason'] == 'certificate'
    assert (asyncio.run(web_access.read_web_access())).login_url == 'https://old.example.com/dbot/login'
    assert api.post(action, data={'domain': 'new.example.com'}, headers=headers).status_code == 200
    job = json.loads((tmp_path / 'domain-request.json').read_text())
    asyncio.run(web_access.save_web_domain('new.example.com', 'https', 8443))
    (tmp_path / 'domain-status.json').write_text(json.dumps({**job, 'state': 'completed'}))
    (tmp_path / 'domain-request.json').unlink()
    assert api.get(status).json()['job']['login_url'] == 'https://new.example.com:8443/dbot/login'


@pytest.mark.parametrize('failure', [None, 'certificate', 'database'])
def test_vps_switch_keeps_old_env_and_nginx_when_any_stage_fails(tmp_path, monkeypatch, failure):
    host = load_script('apply-web-domain')
    monkeypatch.setattr(host, 'APP', tmp_path)
    nginx = tmp_path / 'nginx'
    monkeypatch.setattr(host, 'NGINX', nginx)
    for name in host.MANAGED:
        (nginx / name).parent.mkdir(parents=True, exist_ok=True)
    available, enabled, conf_d = [nginx / name for name in host.MANAGED]
    available.write_text('original nginx config')
    enabled.symlink_to(available)
    original_env = 'API_PORT=8123\nNGINX_HTTPS_PORT=8443\nDOMAIN_NAME=old.example.com\nENABLE_HTTPS=false\n# retain\n\n'
    env_file = tmp_path / '.env'
    env_file.write_text(original_env)
    events = []
    monkeypatch.setattr(host, 'compose', lambda: ['docker', 'compose'])
    monkeypatch.setattr(host, 'reload_nginx', lambda: events.append('restored'))

    def command(args, **kwargs):
        if args[-1] == 'web-url':
            events.append('database-available')
        elif args[0] == 'bash':
            assert env_file.read_text() == original_env
            assert args[-2:] == ['new.example.com', 'switch']
            assert kwargs['env']['API_PORT'] == '8123'
            available.write_text('new nginx config')
            enabled.unlink()
            conf_d.symlink_to(available)
            events.append('nginx')
            if failure == 'certificate':
                raise subprocess.CalledProcessError(1, args)
        else:
            assert args[-4:] == ['set-domain', 'new.example.com', 'https', '8443']
            events.append('db')
            if failure == 'database':
                raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout='')

    monkeypatch.setattr(host.subprocess, 'run', command)
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            host.apply('new.example.com', True)
        assert available.read_text() == 'original nginx config'
        assert enabled.is_symlink() and not conf_d.is_symlink()
        assert env_file.read_text() == original_env
        assert events[-1] == 'restored'
        assert ('db' in events) == (failure == 'database')
    else:
        host.apply('new.example.com', True)
        assert 'PUBLIC_BASE_URL=https://new.example.com:8443' in env_file.read_text()
        assert 'DOMAIN_NAME=new.example.com' in env_file.read_text()
        assert 'ENABLE_HTTPS=true' in env_file.read_text()
        assert events == ['database-available', 'nginx', 'db']
