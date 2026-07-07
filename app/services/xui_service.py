from sqlalchemy import select
from app.core.security import decrypt_text
from app.database.session import SessionLocal
from app.database.models import Server, Plan, ClientService
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

    async def active_client_identifiers_for_server(self, server: Server) -> list[str]:
        """Return identifiers of services that should remain on owned sale inbounds.

        Deleted services are removed from client_services, so they are excluded
        here. Before creating a new client, the XUI client uses this list to
        prune stale clients from target inbound settings and prevent deleted
        users from being recreated by 3x-ui.
        """
        if not getattr(server, 'id', None):
            return []
        identifiers = []
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(ClientService).where(
                    ClientService.server_id == server.id,
                    ClientService.is_active.is_(True),
                )
            )).scalars().all()
            for svc in rows:
                identifiers.extend(self._identifier_tokens([
                    getattr(svc, 'xui_email', None),
                    getattr(svc, 'client_username', None),
                    getattr(svc, 'xui_uuid', None),
                    getattr(svc, 'sub_link', None),
                ]))
        return identifiers


    async def deleted_client_identifiers_for_server(self, server: Server) -> list[str]:
        """Return identifiers of locally deleted/inactive bot services.

        These are the only clients we are allowed to purge from 3x-ui
        inbound.settings before creating a new client. Never remove unknown
        or manual panel users just because they are offline or not in the bot DB.
        """
        if not getattr(server, 'id', None):
            return []
        identifiers = []
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(ClientService).where(
                    ClientService.server_id == server.id,
                    ClientService.is_active.is_(False),
                )
            )).scalars().all()
            for svc in rows:
                identifiers.extend(self._identifier_tokens([
                    getattr(svc, 'xui_email', None),
                    getattr(svc, 'client_username', None),
                    getattr(svc, 'xui_uuid', None),
                    getattr(svc, 'sub_link', None),
                ]))
        return identifiers

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

    async def create_client_on_plan(self, server: Server, plan: Plan, email: str):
        payload = XuiClientPayload(email=email, total_gb=plan.volume_gb, expire_days=plan.duration_days)
        raw_ids = list(plan.inbound_ids or [])
        if not raw_ids:
            meta = getattr(server, 'meta', None) or {}
            raw_ids = meta.get('inbound_ids') or []
        inbound_ids = []
        for item in raw_ids:
            try:
                iid = int(item.get('id') if isinstance(item, dict) else item)
            except Exception:
                continue
            if iid and iid not in inbound_ids:
                inbound_ids.append(iid)
        if server.server_type == 'xui':
            live_ids = await self.live_inbound_ids(server)
            if live_ids and (not inbound_ids or any(i not in live_ids for i in inbound_ids)):
                inbound_ids = live_ids
        try:
            return await self.create_client_on_inbounds(server, inbound_ids, payload)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if server.server_type == 'xui' and ('record not found' in msg or 'something went wrong' in msg):
                live_ids = await self.live_inbound_ids(server)
                if live_ids:
                    return await self.create_client_on_inbounds(server, live_ids, payload)
            raise

    async def create_client_on_inbounds(self, server: Server, inbound_ids: list[int], payload: XuiClientPayload):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        results=[]
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            clean_inbound_ids = []
            for inbound_id in inbound_ids:
                try:
                    iid = int(inbound_id)
                except Exception:
                    continue
                if iid not in clean_inbound_ids:
                    clean_inbound_ids.append(iid)

            # 3x-ui 3.3.x treats client email as globally unique. If a plan has
            # several inbound IDs, create the client in ONE /panel/api/clients/add
            # request with inboundIds=[...]. Creating it once per inbound causes
            # "email already in use" after the first successful inbound.
            # Only purge clients that the bot has explicitly marked inactive/deleted.
            # Never prune unknown/manual/offline panel users from an inbound.
            deleted_identifiers = await self.deleted_client_identifiers_for_server(server)
            created = await xui.add_client_to_inbounds(
                clean_inbound_ids,
                payload,
                deleted_identifiers=deleted_identifiers,
            )
            if isinstance(created, dict) and isinstance(created.get('results'), list):
                results.extend(created.get('results') or [])
            else:
                results.append(created)

            # Important: Sanai/3x-ui may overwrite or normalize subId after creating the client.
            # Always read the client back from the panel and store the real panel Subscription ID.
            # The add response can also include numeric record ids; never store those as xui_uuid.
            sub_id = None
            uuid_val = None
            for r in results:
                if isinstance(r, dict) and isinstance(r.get('_client'), dict):
                    sub_id = self._safe_text(r['_client'].get('subId')) or sub_id
                    uuid_val = self._safe_uuid(r['_client'].get('uuid'), r['_client'].get('id'), r['_client'].get('password'), r['_client'].get('auth')) or uuid_val
            found = None
            # Sanai/3x-ui sometimes needs a short moment to persist the new client.
            import asyncio
            for _ in range(5):
                found = await xui.find_client(payload.email)
                if found:
                    break
                await asyncio.sleep(0.4)

            if found:
                client = found.get('client') or {}
                traffic = found.get('traffic') or {}
                sub_id = (
                    client.get('subId') or client.get('sub_id')
                    or traffic.get('subId') or traffic.get('sub_id')
                    or traffic.get('subscriptionId') or traffic.get('subscription_id')
                    or sub_id
                )
                uuid_val = self._safe_uuid(client.get('uuid'), client.get('id'), client.get('password'), client.get('auth')) or uuid_val

            if not sub_id or not uuid_val:
                for r in results:
                    if isinstance(r, dict) and r.get('_client'):
                        sub_id = self._safe_text(r['_client'].get('subId')) or sub_id
                        uuid_val = self._safe_uuid(r['_client'].get('uuid'), r['_client'].get('id'), r['_client'].get('password'), r['_client'].get('auth')) or uuid_val

            return {'results': results, 'sub_id': self._safe_text(sub_id), 'uuid': self._safe_uuid(uuid_val), 'sub_link': self.build_subscription_link(server, sub_id, payload.email)}
        finally: await xui.close()

    async def query_client(self, server: Server, email: str):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.get_client_traffic(email)
        finally: await xui.close()

    async def find_client_any(self, server: Server, keyword: str):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.find_client(keyword)
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
            for token in tokens:
                found = await xui.find_client(token)
                if found and found.get('client'):
                    return found
            return None
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
            found = None
            matched_token = None
            for token in tokens:
                found = await xui.find_client(token)
                if found and found.get('client'):
                    matched_token = token
                    break
            if not found or not found.get('client'):
                raise RuntimeError('X-UI client not found on panel. Checked identifiers: ' + ', '.join(tokens[:6]))
            client = found.get('client') or {}
            panel_email = self._safe_text(client.get('email')) or matched_token or tokens[0]
            result = await xui.reset_client_plan(panel_email, total_gb, expire_days)
            after = await xui.find_client(panel_email) or found
            return {'result': result, 'found': after, 'panel_email': panel_email, 'matched_identifier': matched_token}
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
