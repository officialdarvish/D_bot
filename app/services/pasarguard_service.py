from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.security import decrypt_text
from app.database.models import Plan, Server

logger = logging.getLogger(__name__)
_PLAN_HWID_SYNC_TASKS: set[asyncio.Task] = set()


def schedule_plan_hwid_limit_sync(plan_id: int) -> None:
    """Propagate a changed plan HWID limit to active PasarGuard subscribers."""
    try:
        task = asyncio.create_task(PasarGuardService().sync_plan_hwid_limit(int(plan_id)))
    except RuntimeError:
        return
    _PLAN_HWID_SYNC_TASKS.add(task)

    def _finished(done: asyncio.Task) -> None:
        _PLAN_HWID_SYNC_TASKS.discard(done)
        if done.cancelled():
            return
        try:
            result = done.result()
            errors = list((result or {}).get('errors') or [])
            if errors:
                logger.warning('PasarGuard plan HWID sync completed with errors: plan_id=%s errors=%s', plan_id, errors)
        except Exception:
            logger.exception('PasarGuard plan HWID sync failed: plan_id=%s', plan_id)

    task.add_done_callback(_finished)


class PasarGuardService:
    """Adapter for the official PasarGuard REST API.

    PasarGuard is RBAC aware: non-owner admins may only be allowed to manage
    their own users and may not be allowed to list groups/settings. D Bot keeps
    those restrictions intact and only uses the permissions granted to the
    configured PasarGuard admin.

    PasarGuard groups are mapped to ``Plan.inbound_ids`` so the existing D Bot
    plan model can select one or more allowed groups without a schema migration.
    """

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._api_base_cache: dict[str, str] = {}

    @staticmethod
    def _cache_key(server: Server) -> str:
        return f"{str(getattr(server, 'panel_url', '') or '').strip()}|{str(getattr(server, 'username', '') or '').strip()}"

    @staticmethod
    def _base(server: Server) -> str:
        raw = str(server.panel_url or '').strip().rstrip('/')
        for suffix in ('/dashboard', '/dashboard/'):
            if raw.endswith(suffix.rstrip('/')):
                raw = raw[: -len(suffix.rstrip('/'))].rstrip('/')
        return raw

    @staticmethod
    def _clean_ids(values: Any) -> list[int]:
        if values is None:
            return []
        if isinstance(values, str):
            values = values.replace(';', ',').split(',')
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        result: list[int] = []
        for raw in values:
            if isinstance(raw, dict):
                raw = raw.get('id')
            try:
                value = int(raw)
            except Exception:
                continue
            if value > 0 and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _permission_allowed(value: Any, *, owner: bool = False) -> bool:
        if owner:
            return True
        if value is True:
            return True
        if isinstance(value, dict):
            try:
                return int(value.get('scope') or 0) > 0
            except Exception:
                return False
        return False

    @staticmethod
    def _permission_scope(value: Any, *, owner: bool = False) -> str:
        if owner:
            return 'all'
        if value is True:
            return 'all'
        if isinstance(value, dict):
            try:
                scope = int(value.get('scope') or 0)
            except Exception:
                scope = 0
            return 'all' if scope >= 2 else ('own' if scope == 1 else 'none')
        return 'none'

    @staticmethod
    def _permission_known(resource: Any, action: str, *, owner: bool = False) -> bool:
        """Whether an RBAC action is explicitly described by the API profile.

        PasarGuard releases before the RBAC-role migration do not expose the
        modern ``role.permissions`` object. Treating an absent action as denied
        makes perfectly valid reseller accounts fail Test & Auto Fill.  A
        modern profile, on the other hand, includes the action with ``null``/
        ``false`` when it is explicitly denied.
        """
        if owner:
            return True
        return isinstance(resource, dict) and action in resource

    @classmethod
    def _cached_group_ids(cls, server: Server) -> list[int]:
        """Return only previously auto-discovered groups.

        PasarGuard group IDs are intentionally not accepted as manual server
        input anymore.  The cached ``inbound_ids`` value is populated only by
        Test & Auto Fill / server sync and is used as a resilience fallback if
        the panel temporarily hides its group-list endpoint later.
        """
        meta = dict(getattr(server, 'meta', None) or {})
        return cls._clean_ids(meta.get('inbound_ids'))

    @staticmethod
    def _auth_mode(server: Server) -> str:
        meta = dict(getattr(server, 'meta', None) or {})
        return str(meta.get('auth_mode') or meta.get('pasarguard_auth_mode') or '').strip().lower()

    @staticmethod
    def _secret(server: Server) -> str:
        return str(decrypt_text(server.password_encrypted or '') or '').strip()

    @classmethod
    def _candidate_api_bases(cls, server: Server) -> list[str]:
        """Return safe API-base candidates for normal and reverse-proxied panels.

        PasarGuard dashboards are often published behind a UI path such as
        ``/hub/`` while the REST API remains mounted at the domain root. D Bot
        accepts the dashboard URL and discovers the real API base automatically.
        """
        candidates: list[str] = []

        def add(value: str | None) -> None:
            value = str(value or '').strip().rstrip('/')
            if value and value not in candidates:
                candidates.append(value)

        meta = dict(getattr(server, 'meta', None) or {})
        add(meta.get('pasarguard_api_base'))

        configured = cls._base(server)
        add(configured)
        try:
            parts = urlsplit(configured)
        except Exception:
            parts = None
        if parts and parts.scheme and parts.netloc:
            origin = urlunsplit((parts.scheme, parts.netloc, '', '', '')).rstrip('/')
            path = (parts.path or '').rstrip('/')
            # Walk parents from the configured UI path to the origin. This
            # supports /hub/, /panel/, /foo/hub/, and similar reverse proxies.
            while path:
                path = path.rsplit('/', 1)[0] if '/' in path else ''
                add(origin + path)
            add(origin)
        return candidates

    def _resolved_api_base(self, server: Server) -> str:
        return self._api_base_cache.get(self._cache_key(server), '')

    async def _auth_headers(self, client: httpx.AsyncClient, server: Server) -> tuple[dict[str, str], str]:
        """Resolve PasarGuard authentication and the real REST API base.

        PasarGuard supports both the normal admin OAuth password flow and panel
        API keys (``pg_key_...``) via ``X-Api-Key``.  D Bot exposes both through
        the generic "API Token Panel" field while keeping username/password as
        a fallback for reseller admins.
        """
        username = str(server.username or '').strip()
        secret = self._secret(server)
        auth_mode = self._auth_mode(server)
        use_api_key = auth_mode in {'api_key', 'api-token', 'api_token', 'panel_token'} or secret.startswith('pg_key_')
        if use_api_key:
            if not secret:
                raise RuntimeError('PasarGuard API Token Panel is not configured')
        elif not username or not secret:
            raise RuntimeError('PasarGuard username/password or API Token Panel is required')

        cache_key = self._cache_key(server)
        candidates = self._candidate_api_bases(server)
        cached = self._api_base_cache.get(cache_key)
        if cached and cached in candidates:
            candidates = [cached] + [x for x in candidates if x != cached]

        attempted: list[str] = []
        last_route_error = ''
        for api_base in candidates:
            if use_api_key:
                probe_url = api_base + '/api/admin'
                attempted.append(probe_url)
                headers = {'X-Api-Key': secret, 'Accept': 'application/json'}
                try:
                    response = await client.get(probe_url, headers=headers)
                except httpx.HTTPError as exc:
                    last_route_error = f'{type(exc).__name__}: {exc}'
                    continue
                if response.status_code < 400:
                    self._api_base_cache[cache_key] = api_base
                    return headers, api_base
            else:
                login_url = api_base + '/api/admin/token'
                attempted.append(login_url)
                try:
                    response = await client.post(
                        login_url,
                        data={'username': username, 'password': secret},
                        headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    )
                except httpx.HTTPError as exc:
                    last_route_error = f'{type(exc).__name__}: {exc}'
                    continue
                if response.status_code < 400:
                    try:
                        body = response.json() or {}
                    except Exception:
                        body = {}
                    token = str(body.get('access_token') or '').strip()
                    if not token:
                        raise RuntimeError('PasarGuard login returned no access token')
                    self._api_base_cache[cache_key] = api_base
                    return {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}, api_base

            detail = response.text[:300]
            try:
                body = response.json() or {}
                detail = str(body.get('detail') or body.get('message') or detail)
            except Exception:
                pass
            if response.status_code in (404, 405):
                last_route_error = f'{response.status_code}: {detail}'
                continue
            if response.status_code in (400, 401, 403, 422):
                mode = 'API Token Panel' if use_api_key else 'login'
                raise RuntimeError(f'PasarGuard {mode} failed ({response.status_code}): {detail}')
            last_route_error = f'{response.status_code}: {detail}'

        attempted_text = ', '.join(attempted) if attempted else '(no valid URL candidates)'
        suffix = f' Last response: {last_route_error}' if last_route_error else ''
        raise RuntimeError('PasarGuard API path could not be detected. Tried: ' + attempted_text + '.' + suffix)

    async def _token(self, client: httpx.AsyncClient, server: Server) -> tuple[str, str]:
        """Backward-compatible bearer-token helper used by older tests/tools.

        API-key mode intentionally uses ``_auth_headers`` directly because an
        API key is not a bearer token.
        """
        headers, api_base = await self._auth_headers(client, server)
        auth = str(headers.get('Authorization') or '')
        if auth.lower().startswith('bearer '):
            return auth.split(' ', 1)[1], api_base
        raise RuntimeError('PasarGuard API Token Panel authentication does not produce a bearer token')

    async def _request(
        self,
        server: Server,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, verify=True) as client:
            headers, api_base = await self._auth_headers(client, server)
            response = await client.request(
                method,
                api_base + path,
                json=json,
                params=params,
                headers=headers,
            )
            if response.status_code == 204:
                return {}
            if response.status_code >= 400:
                detail = response.text[:500]
                try:
                    body = response.json()
                    detail = body.get('detail') or body.get('message') or detail
                except Exception:
                    pass
                raise RuntimeError(f'PasarGuard API {method} {path} failed ({response.status_code}): {detail}')
            if not response.content:
                return {}
            try:
                return response.json()
            except Exception:
                return {'text': response.text}

    async def get_admin_profile(self, server: Server) -> dict:
        data = await self._request(server, 'GET', '/api/admin')
        if not isinstance(data, dict):
            raise RuntimeError('PasarGuard returned an invalid admin profile')
        return data

    @classmethod
    def summarize_access(cls, profile: dict) -> dict:
        profile = profile if isinstance(profile, dict) else {}
        role_raw = profile.get('role')
        role = role_raw if isinstance(role_raw, dict) else {}
        role_present = bool(role)

        # Current PasarGuard exposes ``role.is_owner``.  Older releases used
        # ``is_sudo`` and did not publish the full RBAC map in /api/admin.
        owner = bool(role.get('is_owner')) if role_present else bool(profile.get('is_sudo'))
        permissions = role.get('permissions') if isinstance(role.get('permissions'), dict) else {}
        user_permissions = permissions.get('users') if isinstance(permissions.get('users'), dict) else {}
        group_permissions = permissions.get('groups') if isinstance(permissions.get('groups'), dict) else {}
        template_permissions = permissions.get('templates') if isinstance(permissions.get('templates'), dict) else {}
        access = role.get('access') if isinstance(role.get('access'), dict) else {}
        limits = role.get('limits') if isinstance(role.get('limits'), dict) else {}

        def allowed(resource: dict, action: str) -> bool:
            return cls._permission_allowed(resource.get(action), owner=owner)

        def known(resource: dict, action: str) -> bool:
            return cls._permission_known(resource, action, owner=owner)

        def scope(resource: dict, action: str) -> str:
            return cls._permission_scope(resource.get(action), owner=owner)

        allowed_group_ids_raw = access.get('allowed_group_ids')
        allowed_template_ids_raw = access.get('allowed_template_ids')
        allowed_group_ids = None if allowed_group_ids_raw is None else cls._clean_ids(allowed_group_ids_raw)
        allowed_template_ids = None if allowed_template_ids_raw is None else cls._clean_ids(allowed_template_ids_raw)

        capabilities = {
            'users_create': allowed(user_permissions, 'create'),
            'users_read': allowed(user_permissions, 'read'),
            'users_read_scope': scope(user_permissions, 'read'),
            'users_update': allowed(user_permissions, 'update'),
            'users_update_scope': scope(user_permissions, 'update'),
            'users_delete': allowed(user_permissions, 'delete'),
            'users_delete_scope': scope(user_permissions, 'delete'),
            'users_reset_usage': allowed(user_permissions, 'reset_usage'),
            'users_revoke_sub': allowed(user_permissions, 'revoke_sub'),
            'groups_read_simple': allowed(group_permissions, 'read_simple'),
            'groups_read': allowed(group_permissions, 'read'),
            'templates_read_simple': allowed(template_permissions, 'read_simple'),
            'templates_read': allowed(template_permissions, 'read'),
        }
        capability_known = {
            'users_create': known(user_permissions, 'create'),
            'users_read': known(user_permissions, 'read'),
            'users_update': known(user_permissions, 'update'),
            'users_delete': known(user_permissions, 'delete'),
            'users_reset_usage': known(user_permissions, 'reset_usage'),
            'users_revoke_sub': known(user_permissions, 'revoke_sub'),
            'groups_read_simple': known(group_permissions, 'read_simple'),
            'groups_read': known(group_permissions, 'read'),
            'templates_read_simple': known(template_permissions, 'read_simple'),
            'templates_read': known(template_permissions, 'read'),
        }

        compat_mode = 'rbac' if role_present else 'legacy'
        role_name = str(role.get('name') or '') if role_present else ''
        if not role_name:
            role_name = 'owner' if owner else ('legacy-admin' if compat_mode == 'legacy' else 'custom')

        return {
            'username': str(profile.get('username') or ''),
            'status': str(profile.get('status') or 'active'),
            'role_name': role_name,
            'is_owner': owner,
            'restricted': not owner,
            'compat_mode': compat_mode,
            'rbac_metadata_available': role_present and bool(permissions),
            'capabilities': capabilities,
            'capability_known': capability_known,
            'allowed_group_ids': allowed_group_ids,
            'require_template': bool(access.get('require_template')),
            'allowed_template_ids': allowed_template_ids,
            'limits': limits,
        }

    async def list_groups(self, server: Server) -> list[dict]:
        """Return groups visible to the configured admin.

        New PasarGuard exposes the lightweight ``/api/groups/simple`` route.
        Older reseller panels may only expose ``/api/groups``; use it as a
        compatibility fallback when the lightweight route does not exist.
        """
        last_error: RuntimeError | None = None
        for path, params in (
            ('/api/groups/simple', {'all': 'true'}),
            ('/api/groups', {'limit': 500}),
        ):
            try:
                data = await self._request(server, 'GET', path, params=params)
                rows = data.get('groups') if isinstance(data, dict) else data
                result: list[dict] = []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    try:
                        gid = int(row.get('id'))
                    except Exception:
                        continue
                    if gid <= 0:
                        continue
                    result.append({'id': gid, 'name': str(row.get('name') or f'Group {gid}')})
                return result
            except RuntimeError as exc:
                last_error = exc
                text = str(exc)
                if '(404)' in text or '(405)' in text:
                    continue
                raise
        if last_error:
            raise last_error
        return []

    @classmethod
    def _normalize_template(cls, row: dict) -> dict | None:
        if not isinstance(row, dict):
            return None
        try:
            tid = int(row.get('id'))
        except Exception:
            return None
        if tid <= 0:
            return None
        result = {
            'id': tid,
            'name': str(row.get('name') or f'Template {tid}'),
            'group_ids': cls._clean_ids(row.get('group_ids')),
            'data_limit': row.get('data_limit'),
            'expire_duration': row.get('expire_duration'),
            'hwid_limit': row.get('hwid_limit'),
            'is_disabled': bool(row.get('is_disabled')),
        }
        return result

    async def get_template(self, server: Server, template_id: int) -> dict | None:
        try:
            data = await self._request(server, 'GET', f'/api/user_template/{int(template_id)}')
        except RuntimeError as exc:
            if any(code in str(exc) for code in ('(403)', '(404)', '(405)')):
                return None
            raise
        return self._normalize_template(data) if isinstance(data, dict) else None

    async def list_templates(self, server: Server) -> list[dict]:
        """List visible PasarGuard templates, preferring full template data.

        Full template rows include ``group_ids``, quota and expiry information.
        D Bot uses those fields to auto-detect groups and, when a reseller role
        requires templates, automatically select the template that matches a D
        Bot plan. No Template ID is entered while adding a server.
        """
        last_error: RuntimeError | None = None
        for path, params in (
            ('/api/user_templates', {'limit': 500}),
            ('/api/user_templates/simple', {'all': 'true'}),
        ):
            try:
                data = await self._request(server, 'GET', path, params=params)
                rows = data.get('templates') if isinstance(data, dict) else data
                result: list[dict] = []
                for row in rows or []:
                    normalized = self._normalize_template(row)
                    if normalized:
                        result.append(normalized)
                return result
            except RuntimeError as exc:
                last_error = exc
                text = str(exc)
                if '(403)' in text or '(404)' in text or '(405)' in text:
                    continue
                raise
        if last_error:
            raise last_error
        return []

    async def probe_users_read(self, server: Server) -> tuple[bool | None, list[int], str]:
        """Non-destructively verify user-list access and observe group IDs.

        ``True`` means GET /api/users succeeded, ``False`` means PasarGuard
        explicitly returned 403, and ``None`` means the panel version does not
        expose a compatible list route.  Observed group IDs are useful for a
        legacy reseller whose group-list endpoint is hidden but who already has
        at least one owned user.
        """
        try:
            data = await self._request(server, 'GET', '/api/users', params={'limit': 20})
        except RuntimeError as exc:
            text = str(exc)
            if '(403)' in text:
                return False, [], text
            if '(404)' in text or '(405)' in text:
                return None, [], text
            raise

        rows = data.get('users') if isinstance(data, dict) else data
        group_ids: list[int] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            for gid in self._clean_ids(row.get('group_ids')):
                if gid not in group_ids:
                    group_ids.append(gid)
        return True, group_ids, ''

    async def probe_server(self, server: Server) -> dict:
        """Authenticate and auto-discover reseller scope, groups and templates.

        Group/template IDs are discovered only from PasarGuard itself: visible
        group APIs, role ``allowed_group_ids``, owned users, visible/allowed
        templates, or a previously auto-synced cache. Manual IDs are not part of
        server setup anymore.
        """
        profile = await self.get_admin_profile(server)
        api_base = self._resolved_api_base(server)
        access = self.summarize_access(profile)
        caps = access['capabilities']
        known = access.get('capability_known') if isinstance(access.get('capability_known'), dict) else {}
        warnings: list[str] = []

        users_read_probe: bool | None = None
        observed_group_ids: list[int] = []
        users_read_error = ''
        if known.get('users_read'):
            users_read_probe = bool(caps.get('users_read'))
        else:
            users_read_probe, observed_group_ids, users_read_error = await self.probe_users_read(server)
            if users_read_probe is True:
                caps['users_read'] = True
                known['users_read'] = True
                if caps.get('users_read_scope') == 'none' and access.get('restricted'):
                    caps['users_read_scope'] = 'own'
            elif users_read_probe is False:
                caps['users_read'] = False
                known['users_read'] = True

        groups: list[dict] = []
        group_source = 'none'
        group_error = ''
        group_permission_known = bool(known.get('groups_read_simple'))
        should_probe_groups = bool(access.get('is_owner') or caps.get('groups_read_simple') or not group_permission_known)
        if should_probe_groups:
            try:
                groups = await self.list_groups(server)
                if groups:
                    group_source = 'api'
                    caps['groups_read_simple'] = True
            except RuntimeError as exc:
                group_error = str(exc)
                if '(403)' not in group_error and '(404)' not in group_error and '(405)' not in group_error:
                    raise
        else:
            group_error = 'groups.read_simple is explicitly denied by this PasarGuard role'

        allowed_group_ids = access.get('allowed_group_ids')
        if groups and allowed_group_ids is not None:
            allowed_set = set(allowed_group_ids)
            groups = [row for row in groups if int(row.get('id') or 0) in allowed_set]
        if not groups and allowed_group_ids:
            group_source = 'role-access'
            groups = [{'id': gid, 'name': f'Allowed Group {gid}'} for gid in allowed_group_ids]
            warnings.append('Group listing is restricted; groups were auto-detected from role allowed_group_ids.')
        elif not groups and allowed_group_ids is None and observed_group_ids:
            group_source = 'observed-users'
            groups = [{'id': gid, 'name': f'Observed Group {gid}'} for gid in observed_group_ids]
            warnings.append('Group listing is unavailable; group IDs were auto-detected from users owned by this admin.')

        require_template = bool(access.get('require_template'))
        allowed_template_ids = access.get('allowed_template_ids')
        templates: list[dict] = []
        template_source = 'none'
        template_error = ''
        template_permission_known = bool(known.get('templates_read_simple') or known.get('templates_read'))
        should_probe_templates = bool(
            (require_template or not groups or access.get('compat_mode') == 'legacy')
            and (
                access.get('is_owner')
                or caps.get('templates_read_simple')
                or caps.get('templates_read')
                or not template_permission_known
                or bool(allowed_template_ids)
            )
        )
        if should_probe_templates:
            try:
                templates = await self.list_templates(server)
                if templates:
                    template_source = 'api'
            except RuntimeError as exc:
                template_error = str(exc)
                if '(403)' not in template_error and '(404)' not in template_error and '(405)' not in template_error:
                    raise

        if allowed_template_ids is not None:
            allowed_template_set = set(allowed_template_ids)
            if templates:
                templates = [row for row in templates if int(row.get('id') or 0) in allowed_template_set]
            # If listing is restricted but the role publishes allowed IDs, try
            # safe per-template reads so group/quota metadata can still be found.
            if not templates and allowed_template_ids:
                fetched: list[dict] = []
                for tid in allowed_template_ids:
                    row = await self.get_template(server, tid)
                    if row:
                        fetched.append(row)
                if fetched:
                    templates = fetched
                    template_source = 'role-access'

        # A template includes its group_ids in PasarGuard's official API model.
        # Use them as another automatic source when direct group listing is hidden.
        if not groups and allowed_group_ids != [] and templates:
            template_group_ids: list[int] = []
            for row in templates:
                for gid in self._clean_ids(row.get('group_ids')):
                    if allowed_group_ids is not None and gid not in set(allowed_group_ids):
                        continue
                    if gid not in template_group_ids:
                        template_group_ids.append(gid)
            if template_group_ids:
                group_source = 'templates'
                groups = [{'id': gid, 'name': f'Template Group {gid}'} for gid in template_group_ids]
                warnings.append('Group listing is restricted; groups were auto-detected from visible PasarGuard templates.')

        # Last-resort resilience uses only IDs previously discovered by D Bot,
        # never user-entered fallback IDs.
        if not groups and allowed_group_ids is None:
            cached_group_ids = self._cached_group_ids(server)
            if cached_group_ids:
                group_source = 'cached-auto'
                groups = [{'id': gid, 'name': f'Cached Group {gid}'} for gid in cached_group_ids]
                warnings.append('Using the last automatically synchronized PasarGuard group IDs.')

        if not groups and allowed_group_ids == []:
            warnings.append('This PasarGuard role explicitly has no allowed groups.')

        template_candidates = self._clean_ids([row.get('id') for row in templates])
        if allowed_template_ids:
            for tid in allowed_template_ids:
                if tid not in template_candidates:
                    template_candidates.append(tid)
        resolved_template_id = template_candidates[0] if len(template_candidates) == 1 else 0
        if require_template:
            warnings.append('This PasarGuard role requires template-based user creation; D Bot will select the matching template automatically per plan.')
            if template_error:
                warnings.append(template_error)

        if str(access.get('status') or '').lower() == 'limited':
            warnings.append('This PasarGuard admin is currently limited; PasarGuard may reject new users until the owner quota is increased.')

        essential_missing: list[str] = []
        if known.get('users_create') and not caps.get('users_create'):
            essential_missing.append('users.create')
        elif not known.get('users_create'):
            warnings.append('users.create is not advertised by this panel version; D Bot will verify it on the first service creation.')

        if users_read_probe is False or (users_read_probe is None and known.get('users_read') and not caps.get('users_read')):
            essential_missing.append('users.read')
        elif users_read_probe is None and not known.get('users_read'):
            warnings.append('User-list permission could not be advertised or probed; service reads will be verified when used.')

        if known.get('users_delete') and not caps.get('users_delete'):
            warnings.append('users.delete is not granted; service deletion and delete/recreate renewal fallback will be unavailable.')
        elif not known.get('users_delete'):
            warnings.append('users.delete is not advertised by this panel version; D Bot will verify it only when deletion is requested.')

        renew_supported = bool(
            caps.get('users_update')
            or (known.get('users_create') and caps.get('users_create') and known.get('users_delete') and caps.get('users_delete'))
            or (require_template and caps.get('users_update') and bool(template_candidates))
        )
        if not renew_supported and access.get('compat_mode') != 'legacy':
            warnings.append('Renewal capabilities could not be fully confirmed with the current permissions.')
        elif access.get('compat_mode') == 'legacy':
            warnings.append('Legacy PasarGuard compatibility mode is active; action permissions are validated by the API when each operation runs.')

        if caps.get('users_read_scope') == 'own':
            warnings.append('User access is scoped to OWN. D Bot will only manage users created by this PasarGuard admin.')

        if not require_template and not groups:
            essential_missing.append('usable PasarGuard group access (automatic detection failed)')
        if require_template and not template_candidates:
            essential_missing.append('usable PasarGuard template access (automatic detection failed)')

        if group_error and groups:
            warnings.append(group_error)
        if users_read_error and users_read_probe is None:
            warnings.append(users_read_error)

        return {
            'ok': not essential_missing,
            'api_base': api_base,
            'profile': profile,
            'access': access,
            'groups': groups,
            'group_source': group_source,
            'group_error': group_error,
            'warnings': warnings,
            'missing': essential_missing,
            'renew_supported': renew_supported,
            'templates': templates,
            'template_candidates': template_candidates,
            'template_source': template_source,
            'template_id': resolved_template_id,
        }

    @staticmethod
    def probe_meta(probe: dict) -> dict:
        access = probe.get('access') if isinstance(probe.get('access'), dict) else {}
        caps = access.get('capabilities') if isinstance(access.get('capabilities'), dict) else {}
        groups = probe.get('groups') if isinstance(probe.get('groups'), list) else []
        templates = probe.get('templates') if isinstance(probe.get('templates'), list) else []
        group_ids = PasarGuardService._clean_ids([x.get('id') for x in groups if isinstance(x, dict)])
        template_rows = []
        for row in templates:
            normalized = PasarGuardService._normalize_template(row)
            if normalized:
                template_rows.append(normalized)
        return {
            'pasarguard_api_base': str(probe.get('api_base') or ''),
            'pasarguard_role_name': access.get('role_name') or '',
            'pasarguard_admin_username': access.get('username') or '',
            'pasarguard_admin_status': access.get('status') or '',
            'pasarguard_restricted': bool(access.get('restricted')),
            'pasarguard_compat_mode': access.get('compat_mode') or 'rbac',
            'pasarguard_rbac_metadata_available': bool(access.get('rbac_metadata_available')),
            'pasarguard_capability_known': access.get('capability_known') or {},
            'pasarguard_group_source': probe.get('group_source') or '',
            'pasarguard_allowed_group_ids': access.get('allowed_group_ids'),
            'pasarguard_require_template': bool(access.get('require_template')),
            'pasarguard_allowed_template_ids': access.get('allowed_template_ids'),
            'pasarguard_template_id': int(probe.get('template_id') or 0),
            'pasarguard_template_source': probe.get('template_source') or '',
            'pasarguard_visible_template_ids': PasarGuardService._clean_ids([x.get('id') for x in template_rows]),
            'pasarguard_templates': template_rows,
            'pasarguard_capabilities': caps,
            'pasarguard_limits': access.get('limits') or {},
            'pasarguard_warnings': list(probe.get('warnings') or []),
            'inbound_ids': group_ids,
            'inbounds': [
                {
                    'id': int(row.get('id')),
                    'remark': str(row.get('name') or f"Group {row.get('id')}"),
                    'protocol': 'group',
                    'enable': True,
                }
                for row in groups
                if isinstance(row, dict) and str(row.get('id') or '').isdigit()
            ],
        }

    async def test_server(self, server: Server) -> tuple[bool, list[dict]]:
        try:
            probe = await self.probe_server(server)
            return bool(probe.get('ok')), list(probe.get('groups') or [])
        except Exception:
            return False, []

    @staticmethod
    def _expire_iso(days: int) -> str | int:
        if int(days or 0) <= 0:
            return 0
        when = datetime.now(timezone.utc) + timedelta(days=int(days))
        return when.isoformat()

    @classmethod
    def _effective_group_ids(cls, server: Server, plan: Plan) -> list[int]:
        requested = cls._clean_ids(getattr(plan, 'inbound_ids', None))
        if not requested:
            requested = cls._cached_group_ids(server)
        meta = dict(getattr(server, 'meta', None) or {})
        allowed_raw = meta.get('pasarguard_allowed_group_ids')
        if allowed_raw is not None:
            allowed = cls._clean_ids(allowed_raw)
            if requested:
                invalid = [gid for gid in requested if gid not in set(allowed)]
                if invalid:
                    raise RuntimeError('PasarGuard group is outside this admin role access: ' + ', '.join(map(str, invalid)))
            elif allowed:
                requested = allowed
        return requested

    @classmethod
    def _effective_template_id(cls, server: Server, plan: Plan) -> int:
        meta = dict(getattr(server, 'meta', None) or {})
        if not bool(meta.get('pasarguard_require_template')):
            return 0

        allowed_raw = meta.get('pasarguard_allowed_template_ids')
        allowed = cls._clean_ids(allowed_raw) if allowed_raw is not None else None
        rows = meta.get('pasarguard_templates') if isinstance(meta.get('pasarguard_templates'), list) else []
        templates: list[dict] = []
        for row in rows:
            normalized = cls._normalize_template(row) if isinstance(row, dict) else None
            if not normalized:
                continue
            if allowed is not None and normalized['id'] not in set(allowed):
                continue
            if normalized.get('is_disabled'):
                continue
            templates.append(normalized)

        candidate_ids = cls._clean_ids([row.get('id') for row in templates])
        if allowed:
            for tid in allowed:
                if tid not in candidate_ids:
                    candidate_ids.append(tid)
        if len(candidate_ids) == 1:
            return candidate_ids[0]

        if not templates:
            raise RuntimeError(
                'PasarGuard requires templates, but D Bot could not auto-detect one unique usable template. '
                'Ask the panel owner to expose allowed templates to this admin.'
            )

        target_bytes = 0 if bool(getattr(plan, 'is_unlimited', False)) else max(int(getattr(plan, 'volume_gb', 0) or 0), 0) * 1024 ** 3
        target_seconds = max(int(getattr(plan, 'duration_days', 0) or 0), 0) * 86400
        target_groups = set(cls._clean_ids(getattr(plan, 'inbound_ids', None)))
        target_hwid = max(int(getattr(plan, 'hwid_limit', 0) or 0), 0)

        scored: list[tuple[int, int]] = []
        for row in templates:
            score = 0
            data_limit = row.get('data_limit')
            expire_duration = row.get('expire_duration')
            group_ids = set(cls._clean_ids(row.get('group_ids')))
            hwid_limit = row.get('hwid_limit')
            try:
                if data_limit is not None and int(data_limit or 0) == target_bytes:
                    score += 5
            except Exception:
                pass
            try:
                if expire_duration is not None and int(expire_duration or 0) == target_seconds:
                    score += 5
            except Exception:
                pass
            if target_groups:
                if group_ids == target_groups:
                    score += 4
                elif group_ids & target_groups:
                    score += 1
            try:
                if hwid_limit is not None and int(hwid_limit or 0) == target_hwid:
                    score += 1
            except Exception:
                pass
            scored.append((score, int(row['id'])))

        scored.sort(reverse=True)
        if scored:
            best_score = scored[0][0]
            best = [tid for score, tid in scored if score == best_score]
            # Volume + duration exact match is enough to select deterministically.
            if best_score >= 10 and len(best) == 1:
                return best[0]
        raise RuntimeError(
            'PasarGuard requires template-based creation and multiple templates are available. '
            'D Bot could not uniquely match this D Bot plan by volume/duration/groups. '
            'Create or expose a PasarGuard template that matches the plan.'
        )

    async def create_user_on_plan(self, server: Server, plan: Plan, username: str) -> dict:
        template_id = self._effective_template_id(server, plan)
        if template_id:
            created = await self._request(
                server,
                'POST',
                '/api/user/from_template',
                json={'username': username, 'user_template_id': int(template_id)},
            )
            if not isinstance(created, dict):
                raise RuntimeError('PasarGuard returned an invalid create-user response')
            target_hwid = max(int(getattr(plan, 'hwid_limit', 0) or 0), 0)
            try:
                current_hwid = created.get('hwid_limit')
                current_hwid = int(current_hwid) if current_hwid is not None else None
            except Exception:
                current_hwid = None
            if current_hwid != target_hwid:
                try:
                    updated = await self.update_user(server, username, hwid_limit=target_hwid)
                    if isinstance(updated, dict):
                        created.update(updated)
                except Exception:
                    # Never leave a newly-created template user with a silently
                    # different device policy from the D Bot plan. Best-effort
                    # cleanup is attempted before surfacing the provisioning error.
                    try:
                        await self.delete_user(server, username)
                    except Exception:
                        pass
                    raise
            group_ids = self._clean_ids(created.get('group_ids'))
            return {
                **created,
                'sub_link': created.get('subscription_url') or '',
                'uuid': str(created.get('id') or ''),
                'inbound_ids': group_ids,
                'template_id': int(template_id),
            }

        group_ids = self._effective_group_ids(server, plan)
        if not group_ids:
            raise RuntimeError(
                'PasarGuard has no usable group for this restricted admin. '
                'Ask the panel owner to grant groups.read_simple or set role allowed_group_ids so D Bot can auto-detect groups.'
            )
        payload: dict[str, Any] = {
            'username': username,
            'status': 'active',
            'expire': self._expire_iso(int(plan.duration_days or 0)),
            'data_limit': max(int(plan.volume_gb or 0), 0) * 1024 ** 3,
            'group_ids': group_ids,
            'hwid_limit': max(int(getattr(plan, 'hwid_limit', 0) or 0), 0),
        }
        created = await self._request(server, 'POST', '/api/user', json=payload)
        if not isinstance(created, dict):
            raise RuntimeError('PasarGuard returned an invalid create-user response')
        return {
            **created,
            'sub_link': created.get('subscription_url') or '',
            'uuid': str(created.get('id') or ''),
            'inbound_ids': group_ids,
        }

    async def get_user(self, server: Server, username: str) -> dict | None:
        try:
            data = await self._request(server, 'GET', f'/api/user/by-username/{username}')
        except RuntimeError as exc:
            if '(404)' in str(exc):
                return None
            raise
        if not isinstance(data, dict):
            return None
        data['used_bytes'] = int(data.get('used_traffic') or 0)
        data['total_bytes'] = int(data.get('data_limit') or 0)
        data['sub_link'] = data.get('subscription_url') or ''
        status = str(data.get('status') or '').lower()
        data['enabled'] = status == 'active'
        return data

    @staticmethod
    def _normalize_hwid_row(row: dict) -> dict:
        row = row if isinstance(row, dict) else {}
        hwid = str(row.get('hwid') or '').strip()
        return {
            **row,
            'fingerprint': hwid,
            'deviceModel': row.get('device_model') or row.get('deviceModel') or '',
            'deviceOs': row.get('device_os') or row.get('deviceOs') or '',
            'osVersion': row.get('os_version') or row.get('osVersion') or '',
            'userAgent': row.get('user_agent') or row.get('userAgent') or '',
            'firstSeen': row.get('first_used_at') or row.get('created_at') or row.get('firstSeen'),
            'lastSeen': row.get('last_used_at') or row.get('updated_at') or row.get('lastSeen'),
        }

    async def get_user_hwids(self, server: Server, username: str) -> dict:
        """Return PasarGuard HWID/device state using the current ID-based API."""
        user = await self.get_user(server, username)
        if not user:
            raise RuntimeError('PasarGuard user not found')
        try:
            user_id = int(user.get('id') or 0)
        except Exception:
            user_id = 0
        if user_id <= 0:
            raise RuntimeError('PasarGuard user ID is unavailable for HWID management')
        data = await self._request(server, 'GET', f'/api/user/{user_id}/hwids')
        if not isinstance(data, dict):
            data = {}
        raw_rows = data.get('hwids') if isinstance(data.get('hwids'), list) else []
        devices = [self._normalize_hwid_row(row) for row in raw_rows if isinstance(row, dict)]
        raw_limit = user.get('hwid_limit')
        try:
            limit = max(int(raw_limit), 0) if raw_limit is not None else 0
        except Exception:
            limit = 0
        used = int(data.get('count') or len(devices) or 0)
        return {
            'limit': limit,
            'limit_raw': raw_limit,
            'used': used,
            'remaining': None if limit <= 0 else max(limit - used, 0),
            'devices': devices,
            'user_id': user_id,
        }

    async def clear_user_hwids(self, server: Server, username: str) -> dict:
        """Reset every registered HWID for a PasarGuard user."""
        user = await self.get_user(server, username)
        if not user:
            raise RuntimeError('PasarGuard user not found')
        try:
            user_id = int(user.get('id') or 0)
        except Exception:
            user_id = 0
        if user_id <= 0:
            raise RuntimeError('PasarGuard user ID is unavailable for HWID reset')
        data = await self._request(server, 'POST', f'/api/user/{user_id}/hwids/reset')
        return data if isinstance(data, dict) else {'ok': True}

    async def renew_user_on_plan(self, server: Server, plan: Plan, username: str) -> dict:
        template_id = self._effective_template_id(server, plan)
        if template_id:
            data = await self._request(
                server,
                'PUT',
                f'/api/user/from_template/by-username/{username}',
                json={'user_template_id': int(template_id)},
            )
            data = data if isinstance(data, dict) else {}
            target_hwid = max(int(getattr(plan, 'hwid_limit', 0) or 0), 0)
            try:
                current_hwid = data.get('hwid_limit')
                current_hwid = int(current_hwid) if current_hwid is not None else None
            except Exception:
                current_hwid = None
            if current_hwid != target_hwid:
                updated = await self.update_user(server, username, hwid_limit=target_hwid)
                if isinstance(updated, dict):
                    data.update(updated)
            return {
                **data,
                'sub_link': data.get('subscription_url') or '',
                'uuid': str(data.get('id') or ''),
                'inbound_ids': self._clean_ids(data.get('group_ids')),
                'template_id': int(template_id),
            }

        group_ids = self._effective_group_ids(server, plan)
        if not group_ids:
            raise RuntimeError('PasarGuard renewal has no usable group for this admin role')

        target_bytes = max(int(plan.volume_gb or 0), 0) * 1024 ** 3
        payload = {
            'status': 'active',
            'expire': self._expire_iso(int(plan.duration_days or 0)),
            'data_limit': target_bytes,
            'group_ids': group_ids,
            'hwid_limit': max(int(getattr(plan, 'hwid_limit', 0) or 0), 0),
        }

        reset_denied = False
        try:
            await self._request(server, 'POST', f'/api/user/by-username/{username}/reset')
        except RuntimeError as exc:
            if '(403)' not in str(exc):
                raise
            reset_denied = True

        if reset_denied:
            # If reset_usage is intentionally denied but update is allowed, keep
            # the accumulated counter and extend the total quota by exactly one
            # fresh plan allowance. This gives the customer the expected remaining
            # volume without deleting the subscription or changing its token.
            current = await self.get_user(server, username)
            if current:
                payload['data_limit'] = int(current.get('used_bytes') or 0) + target_bytes

        try:
            data = await self._request(server, 'PUT', f'/api/user/by-username/{username}', json=payload)
            return {
                **(data if isinstance(data, dict) else {}),
                'sub_link': (data.get('subscription_url') if isinstance(data, dict) else '') or '',
                'uuid': str((data.get('id') if isinstance(data, dict) else '') or ''),
                'inbound_ids': group_ids,
                'renewal_mode': 'quota-extension' if reset_denied else 'reset-update',
            }
        except RuntimeError as exc:
            # Last resort for a custom reseller role that denies update/reset but
            # still allows create+delete. Scope=OWN in PasarGuard ensures D Bot can
            # only replace a user owned by this same restricted admin.
            if '(403)' not in str(exc):
                raise
            await self.delete_user(server, username)
            try:
                result = await self.create_user_on_plan(server, plan, username)
                result['renewal_mode'] = 'recreate'
                return result
            except Exception:
                raise RuntimeError(
                    'PasarGuard restricted-admin renewal fallback failed after delete/recreate. '
                    'Grant users.update or users.reset_usage, or verify users.create/delete and allowed groups.'
                ) from None

    async def update_user(
        self,
        server: Server,
        username: str,
        *,
        data_limit_bytes: int | None = None,
        expire_at: datetime | None = None,
        expire_days: int | None = None,
        group_ids: list[int] | None = None,
        hwid_limit: int | None = None,
        status: str | None = 'active',
    ) -> dict:
        payload: dict[str, Any] = {}
        if status is not None:
            payload['status'] = status
        if data_limit_bytes is not None:
            payload['data_limit'] = max(int(data_limit_bytes), 0)
        if expire_at is not None:
            if expire_at.tzinfo is None:
                expire_at = expire_at.replace(tzinfo=timezone.utc)
            payload['expire'] = expire_at.astimezone(timezone.utc).isoformat()
        elif expire_days is not None:
            payload['expire'] = self._expire_iso(int(expire_days))
        if group_ids is not None:
            payload['group_ids'] = [int(x) for x in group_ids if int(x) > 0]
        if hwid_limit is not None:
            payload['hwid_limit'] = max(int(hwid_limit), 0)
        data = await self._request(server, 'PUT', f'/api/user/by-username/{username}', json=payload)
        return data if isinstance(data, dict) else {}

    async def sync_plan_hwid_limit(self, plan_id: int) -> dict:
        """Apply a PasarGuard plan HWID cap to all active services on that plan."""
        from sqlalchemy import select
        from app.database.session import SessionLocal
        from app.database.models import ClientService

        try:
            pid = int(plan_id)
        except Exception as exc:
            raise RuntimeError('Invalid plan id') from exc

        async with SessionLocal() as session:
            plan = await session.get(Plan, pid)
            if not plan:
                raise RuntimeError('Plan not found')
            limit = max(int(getattr(plan, 'hwid_limit', 0) or 0), 0)
            services = (await session.execute(
                select(ClientService).where(
                    ClientService.plan_id == pid,
                    ClientService.is_active == True,
                )
            )).scalars().all()
            server_ids = {int(x.server_id) for x in services if getattr(x, 'server_id', None)}
            servers = {}
            if server_ids:
                rows = (await session.execute(select(Server).where(Server.id.in_(server_ids)))).scalars().all()
                servers = {int(row.id): row for row in rows}

        targets = []
        for service in services:
            server = servers.get(int(getattr(service, 'server_id', 0) or 0))
            if not server or str(getattr(server, 'server_type', '') or '').lower() != 'pasarguard':
                continue
            username = str(getattr(service, 'client_username', '') or getattr(service, 'xui_email', '') or '').strip()
            if username:
                targets.append((server, username))

        result = {'plan_id': pid, 'limit': limit, 'clients': 0, 'errors': []}
        semaphore = asyncio.Semaphore(4)

        async def sync_one(server: Server, username: str):
            async with semaphore:
                try:
                    await self.update_user(server, username, hwid_limit=limit)
                    return username, None
                except Exception as exc:
                    return username, f'{type(exc).__name__}: {exc}'

        if targets:
            rows = await asyncio.gather(*(sync_one(server, username) for server, username in targets))
            for username, error in rows:
                if error:
                    result['errors'].append({'username': username, 'error': error})
                else:
                    result['clients'] += 1
        return result

    async def add_volume(self, server: Server, username: str, add_bytes: int) -> dict:
        current = await self.get_user(server, username)
        if not current:
            raise RuntimeError('PasarGuard user not found')
        current_total = int(current.get('total_bytes') or current.get('data_limit') or 0)
        return await self.update_user(server, username, data_limit_bytes=current_total + max(int(add_bytes), 0))

    async def add_days(self, server: Server, username: str, days: int) -> dict:
        current = await self.get_user(server, username)
        if not current:
            raise RuntimeError('PasarGuard user not found')
        raw_expire = current.get('expire')
        now = datetime.now(timezone.utc)
        base = now
        if isinstance(raw_expire, str) and raw_expire:
            try:
                parsed = datetime.fromisoformat(raw_expire.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed > now:
                    base = parsed
            except Exception:
                pass
        elif isinstance(raw_expire, (int, float)) and raw_expire:
            try:
                parsed = datetime.fromtimestamp(float(raw_expire), tz=timezone.utc)
                if parsed > now:
                    base = parsed
            except Exception:
                pass
        return await self.update_user(server, username, expire_at=base + timedelta(days=max(int(days), 0)))

    async def set_enabled(self, server: Server, username: str, enabled: bool) -> dict:
        data = await self._request(
            server,
            'PUT',
            f'/api/user/by-username/{username}/disabled',
            json={'disabled': not bool(enabled)},
        )
        return data if isinstance(data, dict) else {}

    async def delete_user(self, server: Server, username: str) -> None:
        await self._request(server, 'DELETE', f'/api/user/by-username/{username}')

    async def revoke_subscription(self, server: Server, username: str) -> dict:
        data = await self._request(server, 'POST', f'/api/user/by-username/{username}/revoke_sub')
        if not isinstance(data, dict):
            return {}
        return {**data, 'sub_link': data.get('subscription_url') or ''}
