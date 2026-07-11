import asyncio

from app.core.security import decrypt_text
from app.database.models import Server, Plan
from app.xui.client import XUIClient, XuiClientPayload

class XuiService:
    def _safe_text(self, value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _safe_uuid(self, *values):
        for value in values:
            text = self._safe_text(value)
            if text and not text.isdigit():
                return text
        return None

    async def test_server(self, server: Server) -> tuple[bool, list[dict]]:
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            ok = await xui.login()
            if not ok: return False, []
            return True, await xui.get_inbounds()
        finally: await xui.close()


    def _identifier_tokens(self, values):
        result = []
        for value in values or []:
            text = self._safe_text(value)
            if not text:
                continue
            if text not in result:
                result.append(text)
            if text.startswith('http://') or text.startswith('https://'):
                token = text.rstrip('/').split('/')[-1].strip()
                if token and token not in result:
                    result.append(token)
        return result

    def build_subscription_link(self, server: Server, sub_id: str | None, fallback_email: str | None = None) -> str | None:
        if not sub_id and not fallback_email:
            return None
        base = (getattr(server, 'subscription_url', None) or '').strip() or server.panel_url.rstrip('/') + '/sub/'
        base = base.strip()
        token = sub_id or fallback_email
        if '{sub_id}' in base:
            return base.replace('{sub_id}', token)
        if '{token}' in base:
            return base.replace('{token}', token)
        if base.endswith('/'):
            return base + token
        return base + '/' + token

    async def live_inbound_ids(self, server: Server) -> list[int]:
        if server.server_type != 'xui':
            return []
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                raise RuntimeError('X-UI login failed')
            rows = await xui.get_inbounds()
            ids: list[int] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                try:
                    iid = int(row.get('id'))
                except Exception:
                    continue
                if iid > 0 and iid not in ids:
                    ids.append(iid)
            return ids
        finally:
            await xui.close()

    def _configured_inbound_ids(self, server: Server, plan: Plan) -> list[int]:
        raw_ids = list(plan.inbound_ids or [])
        if not raw_ids:
            meta = getattr(server, 'meta', None) or {}
            raw_ids = meta.get('inbound_ids') or []
        result: list[int] = []
        for item in raw_ids:
            try:
                iid = int(item.get('id') if isinstance(item, dict) else item)
            except Exception:
                continue
            if iid > 0 and iid not in result:
                result.append(iid)
        return result

    def _extract_live_inbound_ids(self, rows) -> list[int]:
        result: list[int] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                iid = int(row.get('id'))
            except Exception:
                continue
            if iid > 0 and iid not in result:
                result.append(iid)
        return result

    async def create_client_on_plan(self, server: Server, plan: Plan, email: str):
        payload = XuiClientPayload(
            email=email,
            total_gb=plan.volume_gb,
            expire_days=plan.duration_days,
        )
        return await self.create_client_on_inbounds(
            server,
            self._configured_inbound_ids(server, plan),
            payload,
        )

    async def create_client_on_inbounds(self, server: Server, inbound_ids: list[int], payload: XuiClientPayload):
        """Create a client with one authenticated 3x-ui session.

        The normal purchase path uses only the official Client API:
        login -> clients/add -> clients/get. Inbounds are listed only when no
        IDs are configured or the panel rejects stale IDs, and the same HTTP
        session is reused for the retry.
        """
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                raise RuntimeError('X-UI login failed: ' + (xui.last_error or 'authentication failed'))

            clean_ids: list[int] = []
            for item in inbound_ids or []:
                try:
                    iid = int(item)
                except Exception:
                    continue
                if iid > 0 and iid not in clean_ids:
                    clean_ids.append(iid)

            # Only query inbounds when the plan/server has no configured IDs.
            if not clean_ids:
                clean_ids = self._extract_live_inbound_ids(await xui.get_inbounds())
            if not clean_ids:
                raise RuntimeError('No active 3x-ui inbound is configured for this plan')

            try:
                created = await xui.add_client_to_inbounds(clean_ids, payload)
            except Exception as exc:
                # A panel may have had inbounds deleted/recreated manually. Refresh
                # once with the same session, then retry only for an ID-related error.
                message = str(exc).lower()
                inbound_error = any(token in message for token in (
                    'inbound', 'record not found', 'not found', 'something went wrong',
                ))
                if not inbound_error:
                    raise
                live_ids = self._extract_live_inbound_ids(await xui.get_inbounds())
                if not live_ids or live_ids == clean_ids:
                    raise
                clean_ids = live_ids
                created = await xui.add_client_to_inbounds(clean_ids, payload)

            results = []
            if isinstance(created, dict) and isinstance(created.get('results'), list):
                results.extend(created.get('results') or [])
            else:
                results.append(created)

            # The create payload already contains usable UUID/subId. Read back at
            # most twice to store any normalization performed by the panel.
            create_client = {}
            if isinstance(created, dict) and isinstance(created.get('_client'), dict):
                create_client = created['_client']
            sub_id = self._safe_text(create_client.get('subId'))
            uuid_val = self._safe_uuid(
                create_client.get('uuid'), create_client.get('id'),
                create_client.get('password'), create_client.get('auth'),
            )

            found = await xui.find_client(payload.email)
            if not found:
                await asyncio.sleep(0.25)
                found = await xui.find_client(payload.email)
            if found:
                client = found.get('client') or {}
                sub_id = self._safe_text(client.get('subId') or client.get('sub_id')) or sub_id
                uuid_val = self._safe_uuid(
                    client.get('uuid'), client.get('id'), client.get('password'), client.get('auth'),
                ) or uuid_val

            return {
                'results': results,
                'sub_id': self._safe_text(sub_id),
                'uuid': self._safe_uuid(uuid_val),
                'sub_link': self.build_subscription_link(server, sub_id, payload.email),
                'inbound_ids': clean_ids,
            }
        finally:
            await xui.close()

    async def query_client(self, server: Server, email: str):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.get_client_traffic(email)
        finally: await xui.close()

    async def find_client_any(self, server: Server, keyword: str, *, exhaustive: bool = False):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.find_client(keyword, exhaustive=exhaustive)
        finally: await xui.close()

    async def find_client_by_identifiers(self, server: Server, *identifiers: str | None):
        """Find a client using every stable identifier we may have stored locally.

        Older reseller services can have a stale xui_email while the real panel
        client is still discoverable by client_username, UUID, Subscription ID or
        subscription link token.  This resolver keeps renew/revoke/delete flows
        from failing just because one local identifier is stale.
        """
        tokens = self._identifier_tokens(identifiers)
        if not tokens:
            return None
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                raise RuntimeError('X-UI login failed')
            return await xui.find_client_by_identifiers(tokens)
        finally:
            await xui.close()

    async def reset_client_plan_any(self, server: Server, identifiers: list[str | None] | tuple[str | None, ...], total_gb: float, expire_days: int):
        """Reset/renew a client after resolving its real panel email.

        3x-ui updates are safest when addressed by the real panel email.  The
        bot database may contain username/subId/UUID/link values from older
        versions, so we resolve first and then call reset_client_plan with the
        panel email.
        """
        tokens = self._identifier_tokens(identifiers)
        if not tokens:
            raise RuntimeError('X-UI client identifier is empty')
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                raise RuntimeError('X-UI login failed')
            found = await xui.find_client_by_identifiers(tokens)
            if not found or not found.get('client'):
                raise RuntimeError('X-UI client not found on panel. Checked identifiers: ' + ', '.join(tokens[:6]))
            client = found.get('client') or {}
            panel_email = self._safe_text(client.get('email')) or tokens[0]
            result = await xui.reset_client_plan(panel_email, total_gb, expire_days)
            after = await xui.find_client(panel_email) or found
            return {
                'result': result,
                'found': after,
                'panel_email': panel_email,
                'matched_identifier': panel_email,
            }
        finally:
            await xui.close()

    async def revoke_and_new_link(self, server: Server, email: str):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            updated = await xui.rotate_client_uuid(email)
            client = updated.get('client') or {}
            sub_id = client.get('subId') or client.get('sub_id')
            uuid_val = self._safe_uuid(client.get('uuid'), client.get('id'), client.get('password'), client.get('auth'))
            # Read once more from panel to ensure the stored Subscription ID is the real one.
            found = await xui.find_client(email)
            if found:
                real = found.get('client') or {}
                traffic = found.get('traffic') or {}
                sub_id = (
                    real.get('subId') or real.get('sub_id')
                    or traffic.get('subId') or traffic.get('sub_id')
                    or traffic.get('subscriptionId') or traffic.get('subscription_id')
                    or sub_id
                )
                uuid_val = self._safe_uuid(real.get('uuid'), real.get('id'), real.get('password'), real.get('auth')) or uuid_val
            return {'uuid': self._safe_uuid(uuid_val), 'sub_id': self._safe_text(sub_id), 'sub_link': self.build_subscription_link(server, sub_id, email)}
        finally: await xui.close()


    async def get_online_clients(self, server: Server) -> list[str]:
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.get_online_clients()
        finally: await xui.close()


    async def set_client_enabled(self, server: Server, email: str, enabled: bool):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.set_client_enabled(email, enabled)
        finally: await xui.close()

    async def delete_client(self, server: Server, *identifiers: str | None):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.delete_client(*identifiers)
        finally: await xui.close()

    async def reset_client_plan(self, server: Server, email: str, total_gb: float, expire_days: int):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.reset_client_plan(email, total_gb, expire_days)
        finally: await xui.close()

    async def add_client_volume(self, server: Server, email: str, add_gb: float):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.add_client_volume(email, add_gb)
        finally: await xui.close()

    async def add_client_days(self, server: Server, email: str, add_days: int):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.add_client_days(email, add_days)
        finally: await xui.close()
