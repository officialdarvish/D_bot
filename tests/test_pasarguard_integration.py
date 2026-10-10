import asyncio
from types import SimpleNamespace

from app.services.pasarguard_service import PasarGuardService


def run(coro):
    return asyncio.run(coro)


def fake_server():
    return SimpleNamespace(
        panel_url='https://panel.example.com',
        username='admin',
        password_encrypted='',
    )


def test_pasarguard_create_maps_plan_groups_and_subscription(monkeypatch):
    svc = PasarGuardService()
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {
            'id': 12,
            'username': 'demo_1',
            'subscription_url': 'https://panel.example.com/sub/abc',
            'used_traffic': 0,
        }

    monkeypatch.setattr(svc, '_request', fake_request)
    plan = SimpleNamespace(volume_gb=25, duration_days=30, inbound_ids=[4, 7], hwid_limit=2)
    result = run(svc.create_user_on_plan(fake_server(), plan, 'demo_1'))
    assert result['sub_link'].endswith('/sub/abc')
    assert result['uuid'] == '12'
    assert result['inbound_ids'] == [4, 7]
    payload = calls[0][2]['json']
    assert payload['data_limit'] == 25 * 1024**3
    assert payload['group_ids'] == [4, 7]
    assert payload['hwid_limit'] == 2
    assert payload['status'] == 'active'


def test_pasarguard_get_user_normalizes_usage(monkeypatch):
    svc = PasarGuardService()

    async def fake_request(server, method, path, **kwargs):
        return {
            'username': 'demo_2',
            'status': 'active',
            'used_traffic': 123,
            'data_limit': 456,
            'subscription_url': 'https://example/sub',
        }

    monkeypatch.setattr(svc, '_request', fake_request)
    result = run(svc.get_user(fake_server(), 'demo_2'))
    assert result['used_bytes'] == 123
    assert result['total_bytes'] == 456
    assert result['enabled'] is True
    assert result['sub_link'] == 'https://example/sub'


def test_pasarguard_renew_resets_then_modifies(monkeypatch):
    svc = PasarGuardService()
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        return {'username': 'demo_3', 'status': 'active'}

    monkeypatch.setattr(svc, '_request', fake_request)
    plan = SimpleNamespace(volume_gb=50, duration_days=15, inbound_ids=[9], hwid_limit=1)
    result = run(svc.renew_user_on_plan(fake_server(), plan, 'demo_3'))
    assert calls[0][:2] == ('POST', '/api/user/by-username/demo_3/reset')
    assert calls[1][:2] == ('PUT', '/api/user/by-username/demo_3')
    assert calls[1][2]['data_limit'] == 50 * 1024**3
    assert calls[1][2]['group_ids'] == [9]
    assert result['inbound_ids'] == [9]


def test_source_wiring_contains_pasarguard_paths():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    buy = (root / 'app/bot/handlers/public/buy.py').read_text()
    renew = (root / 'app/bot/handlers/public/my_services.py').read_text()
    admin = (root / 'app/api/admin_web.py').read_text()
    frontend = (root / 'frontend/components/admin-dashboard.tsx').read_text()
    server_admin_bot = (root / 'app/bot/handlers/admin/servers.py').read_text()
    assert "server.server_type == 'pasarguard'" in buy
    assert "server.server_type == 'pasarguard'" in renew
    assert "server_type == 'pasarguard'" in admin
    assert "value: 'pasarguard'" in frontend
    assert 'API Token Panel' in frontend
    assert 'PasarGuard allowed / fallback group IDs' not in frontend
    assert 'PasarGuard template ID' not in frontend
    assert 'AddServer.pasarguard_group_ids' not in server_admin_bot
    assert 'AddServer.pasarguard_template_id' not in server_admin_bot
    assert "pasarguard_require_template" in admin


def _operator_profile(*, groups_read_simple=True, allowed_group_ids=None, require_template=False, allowed_template_ids=None):
    return {
        'username': 'reseller_admin',
        'status': 'active',
        'role': {
            'name': 'operator',
            'is_owner': False,
            'permissions': {
                'users': {
                    'create': True,
                    'read': {'scope': 1},
                    'update': {'scope': 1},
                    'delete': {'scope': 1},
                    'reset_usage': {'scope': 1},
                    'revoke_sub': {'scope': 1},
                },
                'groups': {'read_simple': groups_read_simple},
            },
            'access': {
                'allowed_group_ids': allowed_group_ids,
                'require_template': require_template,
                'allowed_template_ids': allowed_template_ids,
            },
            'limits': {'max_users': 100},
        },
    }


def test_pasarguard_operator_scope_is_supported():
    access = PasarGuardService.summarize_access(_operator_profile(groups_read_simple=True))
    assert access['restricted'] is True
    assert access['role_name'] == 'operator'
    assert access['capabilities']['users_create'] is True
    assert access['capabilities']['users_read'] is True
    assert access['capabilities']['users_read_scope'] == 'own'
    assert access['capabilities']['users_update_scope'] == 'own'
    assert access['capabilities']['users_delete_scope'] == 'own'
    assert access['capabilities']['groups_read_simple'] is True


def test_probe_falls_back_to_role_allowed_groups_when_group_listing_is_denied(monkeypatch):
    svc = PasarGuardService()

    async def fake_profile(server):
        return _operator_profile(groups_read_simple=False, allowed_group_ids=[7, 9])

    async def should_not_list(server):
        raise AssertionError('group endpoint must not be called when permission is denied')

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'list_groups', should_not_list)
    result = run(svc.probe_server(fake_server()))
    assert result['ok'] is True
    assert result['group_source'] == 'role-access'
    assert [x['id'] for x in result['groups']] == [7, 9]
    assert result['access']['capabilities']['users_read_scope'] == 'own'


def test_probe_auto_detects_groups_from_visible_templates(monkeypatch):
    svc = PasarGuardService()

    async def fake_profile(server):
        profile = _operator_profile(groups_read_simple=False, allowed_group_ids=None)
        profile['role']['permissions']['templates'] = {'read': True, 'read_simple': True}
        return profile

    async def fake_users(server):
        return True, [], ''

    async def denied_groups(server):
        raise RuntimeError('PasarGuard API GET /api/groups/simple failed (403): Permission denied')

    async def fake_templates(server):
        return [
            {'id': 41, 'name': 'Reseller 20GB', 'group_ids': [22, 23], 'data_limit': 20 * 1024**3, 'expire_duration': 30 * 86400}
        ]

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'probe_users_read', fake_users)
    monkeypatch.setattr(svc, 'list_groups', denied_groups)
    monkeypatch.setattr(svc, 'list_templates', fake_templates)
    result = run(svc.probe_server(fake_server()))
    assert result['ok'] is True
    assert result['group_source'] == 'templates'
    assert [x['id'] for x in result['groups']] == [22, 23]


def test_restricted_renew_uses_quota_extension_when_reset_is_denied(monkeypatch):
    svc = PasarGuardService()
    server = fake_server()
    server.meta = {'inbound_ids': [5]}
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if path.endswith('/reset'):
            raise RuntimeError('PasarGuard API POST reset failed (403): Permission denied')
        if method == 'GET' and '/api/user/by-username/' in path:
            return {'id': 1, 'username': 'demo', 'status': 'active', 'used_traffic': 1234, 'data_limit': 9999}
        if method == 'PUT' and path == '/api/user/by-username/demo':
            return {'id': 1, 'username': 'demo', 'subscription_url': 'https://example/same-sub'}
        raise AssertionError((method, path))

    monkeypatch.setattr(svc, '_request', fake_request)
    plan = SimpleNamespace(volume_gb=20, duration_days=30, inbound_ids=[5], hwid_limit=1)
    result = run(svc.renew_user_on_plan(server, plan, 'demo'))
    assert result['sub_link'] == 'https://example/same-sub'
    assert result['renewal_mode'] == 'quota-extension'
    put = next(row for row in calls if row[0] == 'PUT')
    assert put[2]['data_limit'] == 1234 + (20 * 1024**3)
    assert not any(method == 'DELETE' for method, _, _ in calls)


def test_restricted_renew_falls_back_to_delete_recreate_when_update_is_denied(monkeypatch):
    svc = PasarGuardService()
    server = fake_server()
    server.meta = {'inbound_ids': [5]}
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if path.endswith('/reset'):
            raise RuntimeError('PasarGuard API POST reset failed (403): Permission denied')
        if method == 'GET' and '/api/user/by-username/' in path:
            return {'id': 1, 'username': 'demo', 'status': 'active', 'used_traffic': 1, 'data_limit': 2}
        if method == 'PUT' and path == '/api/user/by-username/demo':
            raise RuntimeError('PasarGuard API PUT user failed (403): Permission denied')
        if method == 'DELETE':
            return {}
        if method == 'POST' and path == '/api/user':
            return {'id': 2, 'username': 'demo', 'subscription_url': 'https://example/new-sub'}
        raise AssertionError((method, path))

    monkeypatch.setattr(svc, '_request', fake_request)
    plan = SimpleNamespace(volume_gb=20, duration_days=30, inbound_ids=[5], hwid_limit=1)
    result = run(svc.renew_user_on_plan(server, plan, 'demo'))
    assert result['sub_link'] == 'https://example/new-sub'
    assert result['renewal_mode'] == 'recreate'
    assert ('DELETE', '/api/user/by-username/demo', None) in calls
    assert any(method == 'POST' and path == '/api/user' for method, path, _ in calls)



def test_probe_does_not_bypass_explicit_empty_allowed_groups(monkeypatch):
    svc = PasarGuardService()

    async def fake_profile(server):
        profile = _operator_profile(groups_read_simple=False, allowed_group_ids=[])
        profile['role']['permissions']['templates'] = {'read': True, 'read_simple': True}
        return profile

    async def fake_templates(server):
        return [{'id': 41, 'name': 'Template', 'group_ids': [22]}]

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'list_templates', fake_templates)
    result = run(svc.probe_server(fake_server()))
    assert result['ok'] is False
    assert result['group_source'] == 'none'
    assert result['groups'] == []
    assert any('usable PasarGuard group access' in item for item in result['missing'])


def test_required_template_can_auto_resolve_from_visible_templates(monkeypatch):
    svc = PasarGuardService()
    profile = _operator_profile(groups_read_simple=False, allowed_group_ids=None, require_template=True, allowed_template_ids=None)
    profile['role']['permissions']['templates'] = {'read_simple': True}

    async def fake_profile(server):
        return profile

    async def fake_templates(server):
        return [{'id': 41, 'name': 'Reseller Default'}]

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'list_templates', fake_templates)
    result = run(svc.probe_server(fake_server()))
    assert result['ok'] is True
    assert result['template_id'] == 41
    assert result['template_source'] == 'api'


def test_required_template_auto_fetches_role_allowed_template_without_manual_id(monkeypatch):
    svc = PasarGuardService()
    profile = _operator_profile(groups_read_simple=False, allowed_group_ids=None, require_template=True, allowed_template_ids=[41])
    profile['role']['permissions']['templates'] = {'read': False, 'read_simple': False}

    async def fake_profile(server):
        return profile

    async def no_template_list(server):
        raise RuntimeError('PasarGuard API GET /api/user_templates failed (403): Permission denied')

    async def fake_template(server, template_id):
        assert template_id == 41
        return {'id': 41, 'name': 'Owner Assigned', 'group_ids': [7], 'data_limit': 10 * 1024**3, 'expire_duration': 30 * 86400}

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'list_templates', no_template_list)
    monkeypatch.setattr(svc, 'get_template', fake_template)
    result = run(svc.probe_server(fake_server()))
    assert result['ok'] is True
    assert result['template_id'] == 41
    assert result['template_source'] == 'role-access'
    assert [x['id'] for x in result['groups']] == [7]

def test_pasarguard_plan_group_resolver_accepts_pasarguard_servers():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    admin = (root / 'app/api/admin_web.py').read_text()
    frontend = (root / 'frontend/components/admin-dashboard.tsx').read_text()
    assert "server.server_type not in {'xui', 'pasarguard'}" in admin
    assert "m.get('inbound_ids')" in admin
    assert 'PasarGuard allowed / fallback group IDs' not in frontend
    assert 'PasarGuard template ID' not in frontend


def test_pasarguard_subpath_login_falls_back_to_origin(monkeypatch):
    import httpx
    import app.services.pasarguard_service as pg_module

    svc = PasarGuardService()
    server = SimpleNamespace(
        panel_url='https://p.rain.rest/hub/',
        username='restricted_admin',
        password_encrypted='encrypted',
        meta={},
    )
    monkeypatch.setattr(pg_module, 'decrypt_text', lambda value: 'secret')
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == '/hub/api/admin/token':
            return httpx.Response(405, json={'detail': 'Method Not Allowed'})
        if request.url.path == '/api/admin/token':
            return httpx.Response(200, json={'access_token': 'ok-token', 'token_type': 'bearer'})
        return httpx.Response(404, json={'detail': 'Not Found'})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return await svc._token(client, server)

    token, api_base = run(scenario())
    assert token == 'ok-token'
    assert api_base == 'https://p.rain.rest'
    assert seen[0].endswith('/hub/api/admin/token')
    assert seen[1].endswith('/api/admin/token')
    assert svc._resolved_api_base(server) == 'https://p.rain.rest'


def test_pasarguard_candidate_bases_support_nested_ui_paths():
    server = SimpleNamespace(
        panel_url='https://example.com/company/hub/',
        username='admin',
        meta={},
    )
    assert PasarGuardService._candidate_api_bases(server) == [
        'https://example.com/company/hub',
        'https://example.com/company',
        'https://example.com',
    ]


def test_legacy_pasarguard_profile_does_not_fake_missing_create_delete(monkeypatch):
    svc = PasarGuardService()

    async def fake_profile(server):
        # Pre-RBAC PasarGuard style: no role.permissions payload.
        return {'username': 'legacy_reseller', 'status': 'active', 'is_sudo': False}

    async def fake_users(server):
        return True, [31], ''

    async def no_groups(server):
        raise RuntimeError('PasarGuard API GET /api/groups/simple failed (403): Permission denied')

    async def no_templates(server):
        raise RuntimeError('PasarGuard API GET /api/user_templates/simple failed (404): Not Found')

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'probe_users_read', fake_users)
    monkeypatch.setattr(svc, 'list_groups', no_groups)
    monkeypatch.setattr(svc, 'list_templates', no_templates)
    result = run(svc.probe_server(fake_server()))

    assert result['ok'] is True
    assert result['access']['compat_mode'] == 'legacy'
    assert result['group_source'] == 'observed-users'
    assert [x['id'] for x in result['groups']] == [31]
    assert 'users.create' not in result['missing']
    assert 'users.delete' not in result['missing']
    assert any('first service creation' in x for x in result['warnings'])


def test_legacy_pasarguard_uses_only_previously_auto_synced_group_cache(monkeypatch):
    svc = PasarGuardService()
    server = fake_server()
    server.meta = {'inbound_ids': [77]}

    async def fake_profile(server):
        return {'username': 'legacy_reseller', 'status': 'active'}

    async def fake_users(server):
        return True, [], ''

    async def no_groups(server):
        raise RuntimeError('PasarGuard API GET /api/groups/simple failed (403): Permission denied')

    async def no_templates(server):
        raise RuntimeError('PasarGuard API GET /api/user_templates/simple failed (404): Not Found')

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'probe_users_read', fake_users)
    monkeypatch.setattr(svc, 'list_groups', no_groups)
    monkeypatch.setattr(svc, 'list_templates', no_templates)
    result = run(svc.probe_server(server))

    assert result['ok'] is True
    assert result['group_source'] == 'cached-auto'
    assert [x['id'] for x in result['groups']] == [77]


def test_explicit_modern_create_denial_still_blocks(monkeypatch):
    svc = PasarGuardService()
    profile = _operator_profile(groups_read_simple=True)
    profile['role']['permissions']['users']['create'] = None

    async def fake_profile(server):
        return profile

    async def fake_users(server):
        return True, [], ''

    async def fake_groups(server):
        return [{'id': 1, 'name': 'Sell'}]

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'probe_users_read', fake_users)
    monkeypatch.setattr(svc, 'list_groups', fake_groups)
    result = run(svc.probe_server(fake_server()))

    assert result['ok'] is False
    assert 'users.create' in result['missing']


def test_delete_permission_is_optional_for_server_registration(monkeypatch):
    svc = PasarGuardService()
    profile = _operator_profile(groups_read_simple=True)
    profile['role']['permissions']['users']['delete'] = None

    async def fake_profile(server):
        return profile

    async def fake_users(server):
        return True, [], ''

    async def fake_groups(server):
        return [{'id': 1, 'name': 'Sell'}]

    monkeypatch.setattr(svc, 'get_admin_profile', fake_profile)
    monkeypatch.setattr(svc, 'probe_users_read', fake_users)
    monkeypatch.setattr(svc, 'list_groups', fake_groups)
    result = run(svc.probe_server(fake_server()))

    assert result['ok'] is True
    assert 'users.delete' not in result['missing']
    assert any('users.delete is not granted' in x for x in result['warnings'])


def test_pasarguard_api_token_panel_uses_official_x_api_key(monkeypatch):
    import httpx
    import app.services.pasarguard_service as pg_module

    svc = PasarGuardService()
    server = SimpleNamespace(
        panel_url='https://panel.example.com/hub/',
        username='api-token',
        password_encrypted='encrypted',
        meta={'auth_mode': 'api_key'},
    )
    monkeypatch.setattr(pg_module, 'decrypt_text', lambda value: 'pg_key_demo')
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get('X-Api-Key')))
        if request.url.path == '/hub/api/admin':
            return httpx.Response(404, json={'detail': 'Not Found'})
        if request.url.path == '/api/admin':
            return httpx.Response(200, json={'username': 'api-admin'})
        return httpx.Response(404, json={'detail': 'Not Found'})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return await svc._auth_headers(client, server)

    headers, api_base = run(scenario())
    assert headers['X-Api-Key'] == 'pg_key_demo'
    assert api_base == 'https://panel.example.com'
    assert seen == [('/hub/api/admin', 'pg_key_demo'), ('/api/admin', 'pg_key_demo')]


def test_required_template_is_selected_automatically_per_plan():
    svc = PasarGuardService()
    server = fake_server()
    server.meta = {
        'pasarguard_require_template': True,
        'pasarguard_allowed_template_ids': [41, 42],
        'pasarguard_templates': [
            {'id': 41, 'name': '10 GB / 30 d', 'group_ids': [7], 'data_limit': 10 * 1024**3, 'expire_duration': 30 * 86400, 'hwid_limit': 1},
            {'id': 42, 'name': '20 GB / 30 d', 'group_ids': [7], 'data_limit': 20 * 1024**3, 'expire_duration': 30 * 86400, 'hwid_limit': 1},
        ],
    }
    plan = SimpleNamespace(volume_gb=20, duration_days=30, inbound_ids=[7], hwid_limit=1, is_unlimited=False)
    assert svc._effective_template_id(server, plan) == 42


def test_group_listing_falls_back_to_legacy_full_endpoint(monkeypatch):
    svc = PasarGuardService()
    calls = []

    async def fake_request(server, method, path, **kwargs):
        calls.append(path)
        if path == '/api/groups/simple':
            raise RuntimeError('PasarGuard API GET /api/groups/simple failed (404): Not Found')
        if path == '/api/groups':
            return {'groups': [{'id': 8, 'name': 'Legacy group'}], 'total': 1}
        raise AssertionError(path)

    monkeypatch.setattr(svc, '_request', fake_request)
    groups = run(svc.list_groups(fake_server()))
    assert groups == [{'id': 8, 'name': 'Legacy group'}]
    assert calls == ['/api/groups/simple', '/api/groups']
