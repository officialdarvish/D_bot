from app.core.security import decrypt_text
from app.database.models import Server, Plan
from app.xui.client import XUIClient, XuiClientPayload

class XuiService:
    async def test_server(self, server: Server) -> tuple[bool, list[dict]]:
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            ok = await xui.login()
            if not ok: return False, []
            return True, await xui.get_inbounds()
        finally: await xui.close()

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

    async def create_client_on_plan(self, server: Server, plan: Plan, email: str):
        payload = XuiClientPayload(email=email, total_gb=plan.volume_gb, expire_days=plan.duration_days)
        return await self.create_client_on_inbounds(server, [int(x) for x in plan.inbound_ids], payload)

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
            created = await xui.add_client_to_inbounds(clean_inbound_ids, payload)
            if isinstance(created, dict) and isinstance(created.get('results'), list):
                results.extend(created.get('results') or [])
            else:
                results.append(created)

            # Important: Sanai/3x-ui may overwrite or normalize subId after creating the client.
            # Always read the client back from the panel and store the real panel Subscription ID.
            sub_id = None
            uuid_val = None
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
                uuid_val = client.get('id') or client.get('uuid') or uuid_val

            if not sub_id or not uuid_val:
                for r in results:
                    if isinstance(r, dict) and r.get('_client'):
                        sub_id = r['_client'].get('subId') or sub_id
                        uuid_val = r['_client'].get('id') or uuid_val

            return {'results': results, 'sub_id': sub_id, 'uuid': uuid_val, 'sub_link': self.build_subscription_link(server, sub_id, payload.email)}
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

    async def revoke_and_new_link(self, server: Server, email: str):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            updated = await xui.rotate_client_uuid(email)
            client = updated.get('client') or {}
            sub_id = client.get('subId') or client.get('sub_id')
            uuid_val = client.get('id') or client.get('uuid')
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
                uuid_val = real.get('id') or real.get('uuid') or uuid_val
            return {'uuid': uuid_val, 'sub_id': sub_id, 'sub_link': self.build_subscription_link(server, sub_id, email)}
        finally: await xui.close()


    async def get_online_clients(self, server: Server) -> list[str]:
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.get_online_clients()
        finally: await xui.close()

    async def get_client_ips(self, server: Server, email: str) -> list[str]:
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.get_client_ips(email)
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
