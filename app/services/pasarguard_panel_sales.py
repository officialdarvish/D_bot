"""Strictly scoped PasarGuard dashboard reseller accounts.

The role is deliberately created on the PasarGuard server, not simulated with
Telegram permissions: ALL-user access would be a serious cross-tenant breach.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from app.services.pasarguard_service import PasarGuardService

ROLE_NAME = 'D_BOT_RESELLER_OWN_USERS_V1'
LEGACY_USER_RULES = {
    'create': True,
    'read': {'scope': 1},
    'update': {'scope': 1},
    'delete': {'scope': 1},
}
# Viewing group names is necessary for the user-creation form; it does not
# permit reading, modifying or deleting group contents.
GROUP_RULES = {'read_simple': True}
USER_RULES = {**LEGACY_USER_RULES, 'revoke_sub': {'scope': 1}}
HWID_RULES = {'read': {'scope': 1}, 'delete': {'scope': 1}}


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


def _verify_reseller_role(role: dict, *, legacy: bool = False) -> None:
    """Fail closed if an existing role has been widened or changed upstream."""
    if not isinstance(role, dict) or role.get('name') != ROLE_NAME or role.get('is_owner'):
        raise RuntimeError('Unsafe or unexpected PasarGuard reseller role')
    perms = role.get('permissions') or {}
    if set(perms) - {'users', 'groups', 'hwids'}:
        for name, actions in perms.items():
            if name in {'users', 'groups', 'hwids'}:
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
    wanted_rules = LEGACY_USER_RULES if legacy else USER_RULES
    for name, wanted in wanted_rules.items():
        value = users.get(name)
        if value != wanted:
            raise RuntimeError(f'Unsafe PasarGuard reseller permission: users.{name}')
    for name, value in users.items():
        if name not in wanted_rules and value not in (None, False, {'scope': 0}):
            raise RuntimeError(f'PasarGuard reseller role has extra user permission {name}')


    hwids = perms.get('hwids') or {}
    if not isinstance(hwids, dict): raise RuntimeError('Unsafe HWID permissions')
    if not legacy:
        for name, value in HWID_RULES.items():
            if hwids.get(name) != value: raise RuntimeError('Unsafe PasarGuard hwids.' + name)
    for name, value in hwids.items():
        if (legacy or name not in HWID_RULES) and value not in (None, False, {'scope': 0}):
            raise RuntimeError('Unsafe PasarGuard extra HWID permission')


class PanelResellerProvisioner:
    def __init__(self, client: PasarGuardService | None = None):
        self.client = client or PasarGuardService()

    async def require_provisioning_access(self, server) -> dict:
        """Do not require OWNER: support delegated administrator creation if RBAC permits.

        This does not grant rights in PasarGuard. Any forbidden API endpoint
        still fails with the panel's 403, never with a privileged fallback.
        """
        profile = await self.client.get_admin_profile(server)
        role = profile.get('role') if isinstance(profile, dict) else None
        owner = bool((isinstance(role, dict) and role.get('is_owner')) or profile.get('is_sudo'))
        permissions = role.get('permissions') if isinstance(role, dict) else None
        if not owner and isinstance(permissions, dict):
            admin_rules = permissions.get('admins', permissions.get('admin', {}))
            if isinstance(admin_rules, dict) and (admin_rules.get('create') is False or admin_rules.get('create') == {'scope': 0}):
                raise RuntimeError('This PasarGuard Admin cannot create sub-admins (admins.create is denied). Ask the upstream panel owner to delegate admin creation, or use owner-managed provisioning.')
        return profile

    # Compatibility with callers using the old method; now tests delegated rights.
    async def require_owner(self, server) -> dict:
        return await self.require_provisioning_access(server)

    async def username_available(self, server, username: str) -> bool:
        if not validate_panel_username(username):
            return False
        # Queried with the configured Admin token; the panel returns 409 if it races.
        data = await self.client._request(server, 'GET', '/api/admins', params={'username': username, 'limit': 100})
        admins = data.get('admins') if isinstance(data, dict) else None
        if not isinstance(admins, list):
            raise RuntimeError('Cannot confirm PasarGuard admin username availability')
        return not any(str(row.get('username') or '').lower() == username.lower() for row in admins if isinstance(row, dict))

    async def ensure_safe_role(self, server) -> int:
        await self.require_provisioning_access(server)
        data = await self.client._request(server, 'GET', '/api/admin-roles', params={'limit': 500})
        roles = data.get('roles') if isinstance(data, dict) else None
        if not isinstance(roles, list):
            raise RuntimeError('PasarGuard API cannot list safe reseller roles. Grant permission to read admin roles before enabling sales.')
        for role in roles:
            if isinstance(role, dict) and role.get('name') == ROLE_NAME:
                detail = await self.client._request(server, 'GET', f"/api/admin-role/{int(role['id'])}")
                await self.ensure_control_permissions(server, int(role['id']), detail=detail)
                return int(role['id'])
        # Non-owners may create roles only if their upstream permissions allow it.
        # A pre-existing matching role is preferred when role creation is forbidden.
        role = await self.client._request(server, 'POST', '/api/admin-role', json={
            'name': ROLE_NAME,
            'permissions': {'users': USER_RULES, 'groups': GROUP_RULES, 'hwids': HWID_RULES},
            'access': {'require_template': False},
        })
        _verify_reseller_role(role)
        return int(role['id'])

    async def ensure_control_permissions(self, server, role_id: int, *, detail=None) -> None:
        """Upgrade only the exact, safe D Bot legacy role, preserving role access.

        Configured admin rights must permit this update. No owner credential is
        substituted for a rejected purchased-admin user operation.
        """
        role = detail or await self.client._request(server, 'GET', f'/api/admin-role/{int(role_id)}')
        if not isinstance(role, dict) or int(role.get('id') or 0) != int(role_id):
            raise RuntimeError('PasarGuard reseller role ID could not be verified')
        try:
            _verify_reseller_role(role)
            return
        except RuntimeError:
            _verify_reseller_role(role, legacy=True)
        permissions = dict(role.get('permissions') or {})
        permissions['users'] = {**(permissions.get('users') or {}), **USER_RULES}
        permissions['hwids'] = dict(HWID_RULES)
        await self.client._request(server, 'PUT', f'/api/admin-role/{int(role_id)}', json={'permissions': permissions})
        verified = await self.client._request(server, 'GET', f'/api/admin-role/{int(role_id)}')
        _verify_reseller_role(verified)

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
