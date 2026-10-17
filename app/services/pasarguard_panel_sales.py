"""Owner-provisioned, strictly scoped PasarGuard dashboard reseller accounts.

The role is deliberately created on the PasarGuard server, not simulated with
Telegram permissions: ALL-user access would be a serious cross-tenant breach.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from app.services.pasarguard_service import PasarGuardService

ROLE_NAME = 'D_BOT_RESELLER_OWN_USERS_V1'
USER_RULES = {
    'create': True,
    'read': {'scope': 1},
    'update': {'scope': 1},
    'delete': {'scope': 1},
}
# Viewing group names is necessary for the user-creation form; it does not
# permit reading, modifying or deleting group contents.
GROUP_RULES = {'read_simple': True}


def validate_panel_username(value: str) -> bool:
    return bool(re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{3,31}', (value or '').strip()))


def validate_panel_password(value: str) -> bool:
    """Mirror PasarGuard's actual AdminCreate PasswordValidator policy."""
    return bool(value and len(value) >= 12 and len(value.encode('utf-8')) <= 72
                and len(re.findall(r'[a-z]', value)) >= 2
                and len(re.findall(r'[A-Z]', value)) >= 2
                and len(re.findall(r'[0-9]', value)) >= 2
                and re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?/~`]', value)
                and '"' not in value and not any(c.isspace() for c in value))



def login_url(server) -> str:
    configured = str(server.panel_url or '').strip().rstrip('/')
    parsed = urlsplit(configured)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError('PasarGuard dashboard must have an HTTPS login URL')
    path = parsed.path.rstrip('/')
    # Respect reverse-proxy dashboard URLs (e.g. /hub/); otherwise use the
    # documented /dashboard/ route. Never expose the internal API URL.
    if path.endswith('/dashboard') or path and path != '/api':
        path = path + '/'
    else:
        path = '/dashboard/'
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def _verify_reseller_role(role: dict) -> None:
    """Fail closed if an existing role has been widened or changed upstream."""
    if not isinstance(role, dict) or role.get('name') != ROLE_NAME or role.get('is_owner'):
        raise RuntimeError('Unsafe or unexpected PasarGuard reseller role')
    perms = role.get('permissions') or {}
    if set(perms) - {'users', 'groups'}:
        for name, actions in perms.items():
            if name in {'users', 'groups'}:
                continue
            if not isinstance(actions, dict):
                if actions not in (None, False):
                    raise RuntimeError(f'PasarGuard reseller role unexpectedly grants {name} access')
            elif any(v not in (None, False, {'scope': 0}) for v in actions.values()):
                raise RuntimeError(f'PasarGuard reseller role unexpectedly grants {name} access')
    groups = perms.get('groups') or {}
    if not isinstance(groups, dict) or groups.get('read_simple') is not True:
        raise RuntimeError('PasarGuard reseller requires read-only group-name access')
    for action, value in groups.items():
        if action != 'read_simple' and value not in (None, False, {'scope': 0}):
            raise RuntimeError(f'PasarGuard reseller role has extra groups permission {action}')
    users = perms.get('users') or {}
    for name, wanted in USER_RULES.items():
        value = users.get(name)
        if value != wanted:
            raise RuntimeError(f'Unsafe PasarGuard reseller permission: users.{name}')
    for name, value in users.items():
        if name not in USER_RULES and value not in (None, False, {'scope': 0}):
            raise RuntimeError(f'PasarGuard reseller role has extra user permission {name}')


class PanelResellerProvisioner:
    def __init__(self, client: PasarGuardService | None = None):
        self.client = client or PasarGuardService()

    async def require_owner(self, server) -> dict:
        profile = await self.client.get_admin_profile(server)
        role = profile.get('role') if isinstance(profile, dict) else {}
        if not isinstance(role, dict) or role.get('is_owner') is not True:
            raise RuntimeError('Panel reseller sales require a PasarGuard OWNER connection with admin/role creation rights')
        return profile

    async def username_available(self, server, username: str) -> bool:
        if not validate_panel_username(username):
            return False
        # Queried with owner credentials. The panel returns 409 if it races.
        data = await self.client._request(server, 'GET', '/api/admins', params={'username': username, 'limit': 100})
        admins = data.get('admins') if isinstance(data, dict) else None
        if not isinstance(admins, list):
            raise RuntimeError('Cannot confirm PasarGuard admin username availability')
        return not any(str(row.get('username') or '').lower() == username.lower() for row in admins if isinstance(row, dict))

    async def ensure_safe_role(self, server) -> int:
        await self.require_owner(server)
        data = await self.client._request(server, 'GET', '/api/admin-roles', params={'limit': 500})
        roles = data.get('roles') if isinstance(data, dict) else None
        if not isinstance(roles, list):
            raise RuntimeError('Cannot validate PasarGuard reseller roles')
        for role in roles:
            if isinstance(role, dict) and role.get('name') == ROLE_NAME:
                detail = await self.client._request(server, 'GET', f"/api/admin-role/{int(role['id'])}")
                _verify_reseller_role(detail)
                return int(role['id'])
        role = await self.client._request(server, 'POST', '/api/admin-role', json={
            'name': ROLE_NAME,
            'permissions': {'users': USER_RULES, 'groups': GROUP_RULES},
            'access': {'require_template': False},
        })
        _verify_reseller_role(role)
        return int(role['id'])

    async def create_account(self, server, username: str, password: str, max_users: int = 0) -> dict:
        if not validate_panel_username(username) or not validate_panel_password(password):
            raise ValueError('Username or password violates the reseller panel policy')
        role_id = await self.ensure_safe_role(server)
        if not await self.username_available(server, username):
            raise RuntimeError('Username is already registered on the PasarGuard panel')
        result = await self.client._request(server, 'POST', '/api/admin', json={
            'username': username, 'password': password, 'role_id': role_id,
            'status': 'active',
            **({'permission_overrides': {'max_users': int(max_users)}} if max_users > 0 else {}),
        })
        if not isinstance(result, dict) or str(result.get('username') or '').lower() != username.lower():
            raise RuntimeError('PasarGuard did not confirm the reseller account creation')
        assigned = result.get('role') or {}
        if not isinstance(assigned, dict) or int(assigned.get('id') or 0) != role_id:
            # API may omit role in create response; query the freshly created admin.
            result = await self.client._request(server, 'GET', '/api/admins', params={'username': username})
            matches = [a for a in result.get('admins', []) if str(a.get('username') or '').lower() == username.lower()]
            if len(matches) != 1 or int((matches[0].get('role') or {}).get('id') or 0) != role_id:
                raise RuntimeError('Created admin role could not be verified; operator action required')
            result = matches[0]
        if max_users > 0:
            detail = await self.client._request(server, 'GET', f"/api/admins", params={'username': username})
            found = [r for r in detail.get('admins', []) if r.get('username', '').lower() == username.lower()]
            overrides = (found[0].get('permission_overrides') or {}) if len(found) == 1 else {}
            if int(overrides.get('max_users') or 0) != int(max_users):
                raise RuntimeError('PasarGuard did not enforce the purchased user-count limit')
        return {'username': username, 'role_id': role_id, 'admin_id': result.get('id'), 'login_url': login_url(server)}
