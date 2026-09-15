import asyncio
from datetime import datetime, timezone

import httpx

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

    def _plan_inbound_mode(self, plan: Plan) -> str:
        return 'manual' if str((getattr(plan, 'meta', None) or {}).get('inbound_mode') or '').strip().lower() == 'manual' else 'automatic'

    def _configured_inbound_ids(self, server: Server, plan: Plan) -> list[int]:
        mode = self._plan_inbound_mode(plan)
        if mode == 'manual':
            raw_ids = list(plan.inbound_ids or [])
        else:
            meta = getattr(server, 'meta', None) or {}
            inbound_rows = meta.get('inbounds') or []
            # Automatic plans follow every currently enabled inbound. Keep the
            # legacy inbound_ids fallback for servers synced by older versions.
            raw_ids = [
                row.get('id')
                for row in inbound_rows
                if isinstance(row, dict) and row.get('enable') is not False
            ] or meta.get('inbound_ids') or plan.inbound_ids or []
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
            if not isinstance(row, dict) or row.get('enable', row.get('enabled', True)) is False:
                continue
            try:
                iid = int(row.get('id'))
            except Exception:
                continue
            if iid > 0 and iid not in result:
                result.append(iid)
        return result

    def server_inbound_mode(self, server: Server) -> str:
        """Return the server-level inbound scope used by reseller services.

        Reseller servers historically meant "all panel inbounds", so missing
        metadata remains automatic for backward compatibility. A future/manual
        reseller configuration can opt into a fixed selected list by storing
        ``meta['inbound_mode'] = 'manual'``.
        """
        meta = getattr(server, 'meta', None) or {}
        return 'manual' if str(meta.get('inbound_mode') or '').strip().lower() == 'manual' else 'automatic'

    async def _renewal_inbound_ids(
        self,
        xui: XUIClient,
        server: Server,
        *,
        mode: str,
        configured_ids: list[int] | None = None,
    ) -> list[int]:
        """Resolve the memberships that must be reasserted after renewal."""
        if mode == 'manual':
            ids: list[int] = []
            for item in configured_ids or []:
                try:
                    iid = int(item)
                except Exception:
                    continue
                if iid > 0 and iid not in ids:
                    ids.append(iid)
        else:
            # Read the panel at renewal time. Cached server metadata can be stale
            # after an inbound was added, and automatic scope means every active
            # inbound must be attached again after Sanaei re-enables the client.
            ids = self._extract_live_inbound_ids(await xui.get_inbounds())
        if not ids:
            scope = 'manual selection' if mode == 'manual' else 'automatic live list'
            raise RuntimeError(f'No active X-UI inbound is available for renewal ({scope})')
        return ids

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
            automatic=(self._plan_inbound_mode(plan) == 'automatic'),
        )

    async def create_client_on_inbounds(self, server: Server, inbound_ids: list[int], payload: XuiClientPayload, *, automatic: bool = True):
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

            # Automatic plans may recover their live inbound list when no
            # cached IDs exist. Manual plans must never silently fall back to
            # every server inbound because that would violate the saved scope.
            if not clean_ids and automatic:
                clean_ids = self._extract_live_inbound_ids(await xui.get_inbounds())
            if not clean_ids:
                raise RuntimeError('No active 3x-ui inbound is configured for this plan')

            try:
                created = await xui.add_client_to_inbounds(clean_ids, payload)
            except Exception as exc:
                # A panel may have had inbounds deleted/recreated manually. Refresh
                # once with the same session, then retry only for an ID-related error.
                message = str(exc).lower()
                duplicate_client_error = any(token in message for token in (
                    'email already in use', 'email is already in use',
                    'email already exists', 'duplicate email',
                    'username already in use', 'username already exists',
                ))
                inbound_error = (
                    not duplicate_client_error
                    and any(token in message for token in (
                        'inbound', 'record not found', 'not found', 'something went wrong',
                    ))
                )
                if not inbound_error or not automatic:
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

    def _is_transient_panel_error(self, exc: BaseException | None) -> bool:
        """Return True for a transport failure that is safe to reconcile.

        Renewal code may wrap the original httpx exception in RuntimeError after
        checking reset/update/attach state. Walk the exception chain as well as
        the message so reseller renewal never leaks a raw ReadTimeout to users.
        """
        current = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, httpx.TransportError):
                return True
            message = f'{type(current).__name__}: {current}'.lower()
            if any(token in message for token in (
                'readtimeout', 'connecttimeout', 'writetimeout', 'pooltimeout',
                'remoteprotocolerror', 'connection reset', 'connection aborted',
            )):
                return True
            current = current.__cause__ or current.__context__
        return False

    async def _reconcile_reseller_renew_after_timeout(
        self,
        server: Server,
        identifiers: list[str | None] | tuple[str | None, ...],
        total_gb: float,
        expire_days: int,
        *,
        inbound_mode: str = 'automatic',
        inbound_ids: list[int] | None = None,
    ):
        """Confirm a reseller renewal after an ambiguous panel timeout.

        Sanaei can commit a POST and then fail to return its response. A blind
        retry would reset traffic a second time. Instead open a fresh session,
        verify absolute quota/expiry/enable state, reassert every active inbound,
        and only report success when the desired state is visible on the panel.
        """
        tokens = self._identifier_tokens(identifiers)
        if not tokens:
            return None
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                return None
            found = await xui.find_client_by_identifiers(tokens)
            if not found or not found.get('client'):
                return None
            client = found.get('client') or {}
            panel_email = self._safe_text(client.get('email')) or tokens[0]

            try:
                target_total = int(float(total_gb or 0) * (1024 ** 3))
            except Exception:
                target_total = 0
            try:
                real_total = int(client.get('totalGB') or 0)
            except Exception:
                real_total = 0
            try:
                real_expiry = int(client.get('expiryTime') or 0)
            except Exception:
                real_expiry = 0

            enabled_raw = client.get('enable')
            enabled = enabled_raw is True or str(enabled_raw or '').strip().lower() in {
                '1', 'true', 'yes', 'on', 'enabled'
            }
            days = max(int(expire_days or 0), 0)
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            expected_expiry = now_ms + days * 24 * 60 * 60 * 1000 if days > 0 else 0
            # The first request may have spent time waiting for Sanaei before the
            # timeout was raised. Fifteen minutes is intentionally generous while
            # still preventing an old expiry date from being mistaken as renewed.
            expiry_ok = (
                expected_expiry == 0
                or abs(real_expiry - expected_expiry) <= 15 * 60 * 1000
            )
            total_ok = (target_total == 0 and real_total == 0) or real_total == target_total
            if not (enabled and total_ok and expiry_ok):
                return None

            mode = 'manual' if str(inbound_mode or '').strip().lower() == 'manual' else 'automatic'
            try:
                required_ids = await self._renewal_inbound_ids(
                    xui, server, mode=mode, configured_ids=inbound_ids or []
                )
            except Exception:
                return None
            if not required_ids:
                return None

            panel_ids = []
            for item in found.get('inbound_ids') or []:
                try:
                    iid = int(item)
                except Exception:
                    continue
                if iid > 0 and iid not in panel_ids:
                    panel_ids.append(iid)

            # Reassert the reseller-required inbound scope even when the read looks
            # correct. This repairs Sanaei auto-detach races for both modes.
            # Do not blindly repeat this POST on timeout: Sanaei may have committed
            # it already. Verification below decides whether another write is needed.
            attach_returned = True
            try:
                await xui.attach_client(panel_email, required_ids)
            except Exception as attach_exc:
                attach_returned = False
                if not self._is_transient_panel_error(attach_exc):
                    return None

            # A timed-out attach may still be committed, so verify with fresh
            # reads. Panels that omit inboundIds after a successful attach are
            # accepted only when the attach call itself returned successfully.
            latest = None
            membership_verified = False
            latest_ids: list[int] = []
            for delay in (0.0, 0.35, 0.8):
                if delay:
                    await asyncio.sleep(delay)
                latest = await xui.find_client(panel_email)
                latest_ids = []
                for item in (latest or {}).get('inbound_ids') or []:
                    try:
                        iid = int(item)
                    except Exception:
                        continue
                    if iid > 0 and iid not in latest_ids:
                        latest_ids.append(iid)
                if latest_ids and set(required_ids).issubset(set(latest_ids)):
                    panel_ids = latest_ids
                    membership_verified = True
                    break
                if not latest_ids and attach_returned:
                    # Some older panel builds omit inboundIds from client/get. A
                    # successful attach response is the best available proof.
                    panel_ids = required_ids
                    membership_verified = True
                    break

            if not membership_verified:
                missing_ids = [iid for iid in required_ids if iid not in latest_ids]
                try:
                    await xui.bulk_attach_clients([panel_email], missing_ids or required_ids)
                    panel_ids = required_ids
                    membership_verified = True
                except Exception as bulk_exc:
                    if not self._is_transient_panel_error(bulk_exc):
                        return None
                    # bulkAttach can time out after commit as well. One final read
                    # is enough; never loop mutating calls indefinitely.
                    await asyncio.sleep(0.4)
                    latest = await xui.find_client(panel_email)
                    verified_ids = []
                    for item in (latest or {}).get('inbound_ids') or []:
                        try:
                            iid = int(item)
                        except Exception:
                            continue
                        if iid > 0 and iid not in verified_ids:
                            verified_ids.append(iid)
                    if verified_ids and set(required_ids).issubset(set(verified_ids)):
                        panel_ids = verified_ids
                        membership_verified = True

            if not membership_verified:
                return None
            if panel_ids and not set(required_ids).issubset(set(panel_ids)):
                return None

            if mode == 'manual' and panel_ids:
                extra_ids = [iid for iid in panel_ids if iid not in required_ids]
                if extra_ids:
                    detach_returned = False
                    try:
                        await xui.detach_client(panel_email, extra_ids)
                        detach_returned = True
                    except Exception as detach_exc:
                        if not self._is_transient_panel_error(detach_exc):
                            return None
                    latest_scope = None
                    for delay in (0.0, 0.35, 0.8):
                        if delay:
                            await asyncio.sleep(delay)
                        latest_scope = await xui.find_client(panel_email)
                        ids_now = []
                        for item in (latest_scope or {}).get('inbound_ids') or []:
                            try:
                                iid = int(item)
                            except Exception:
                                continue
                            if iid > 0 and iid not in ids_now:
                                ids_now.append(iid)
                        if ids_now:
                            if set(ids_now) == set(required_ids):
                                panel_ids = ids_now
                                latest = latest_scope or latest
                                break
                        elif detach_returned:
                            panel_ids = list(required_ids)
                            latest = latest_scope or latest
                            break
                    if set(panel_ids) != set(required_ids):
                        return None

            final_found = latest or found
            return {
                'result': {
                    'success': True,
                    'transport_timeout_reconciled': True,
                    'inbound_ids': (required_ids if mode == 'manual' else (panel_ids or required_ids)),
                },
                'found': final_found,
                'panel_email': panel_email,
                'matched_identifier': panel_email,
                'transport_timeout_reconciled': True,
            }
        finally:
            await xui.close()

    async def renew_reseller_client_any(
        self,
        server: Server,
        identifiers: list[str | None] | tuple[str | None, ...],
        total_gb: float,
        expire_days: int,
        *,
        inbound_mode: str = 'automatic',
        inbound_ids: list[int] | None = None,
    ):
        """Renew a reseller client using that reseller's inbound policy.

        Automatic mode resolves every currently active panel inbound at renewal
        time. Manual mode reasserts only the administrator-selected IDs and
        removes extra memberships so the reseller remains restricted. Sanaei may
        detach memberships when an expired client is disabled, therefore the
        selected scope is always re-applied after enable.

        A Sanaei ReadTimeout is ambiguous: the panel can commit the renewal and
        close the HTTP response late. We therefore reconcile the live state before
        retrying. At most one complete retry is attempted, and a raw httpx timeout
        is never exposed to the reseller flow.
        """
        last_error: BaseException | None = None
        for attempt in range(2):
            try:
                return await self.reset_client_plan_any(
                    server,
                    identifiers,
                    total_gb,
                    expire_days,
                    inbound_ids=list(inbound_ids or []),
                    inbound_mode=inbound_mode,
                    current_inbound_ids=[],
                )
            except Exception as exc:
                if not self._is_transient_panel_error(exc):
                    raise
                last_error = exc
                try:
                    reconciled = await self._reconcile_reseller_renew_after_timeout(
                        server, identifiers, total_gb, expire_days, inbound_mode=inbound_mode, inbound_ids=list(inbound_ids or [])
                    )
                except Exception as reconcile_exc:
                    if not self._is_transient_panel_error(reconcile_exc):
                        raise
                    reconciled = None
                    last_error = reconcile_exc
                if reconciled:
                    return reconciled
                if attempt == 0:
                    await asyncio.sleep(0.8)
                    continue

        # One last read is safer than reporting failure immediately after the
        # retry timeout because the second POST may also have committed remotely.
        try:
            reconciled = await self._reconcile_reseller_renew_after_timeout(
                server, identifiers, total_gb, expire_days, inbound_mode=inbound_mode, inbound_ids=list(inbound_ids or [])
            )
        except Exception:
            reconciled = None
        if reconciled:
            return reconciled
        detail = f'{type(last_error).__name__}: {last_error}' if last_error else 'unknown transport timeout'
        raise RuntimeError(
            'X-UI reseller renewal could not be confirmed after a temporary panel timeout. '
            'No reseller quota is committed on this failure; retry the renewal after checking panel connectivity. '
            f'Last transport error: {detail}'
        ) from last_error

    async def reset_client_plan_any(
        self,
        server: Server,
        identifiers: list[str | None] | tuple[str | None, ...],
        total_gb: float,
        expire_days: int,
        *,
        inbound_ids: list[int] | None = None,
        inbound_mode: str = 'manual',
        current_inbound_ids: list[int] | None = None,
    ):
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
            panel_inbound_ids = found.get('inbound_ids') or []
            preserve_hint = []
            for item in [*panel_inbound_ids, *(current_inbound_ids or [])]:
                try:
                    iid = int(item)
                except Exception:
                    continue
                if iid > 0 and iid not in preserve_hint:
                    preserve_hint.append(iid)
            mode = 'manual' if str(inbound_mode or '').strip().lower() == 'manual' else 'automatic'
            renewal_inbound_ids = await self._renewal_inbound_ids(
                xui,
                server,
                mode=mode,
                configured_ids=inbound_ids,
            )
            result = await xui.reset_client_plan(
                panel_email,
                total_gb,
                expire_days,
                inbound_ids=renewal_inbound_ids,
                current_inbound_ids_hint=preserve_hint,
                exact_inbound_scope=(mode == 'manual'),
            )
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

    async def renew_client_on_plan(self, server: Server, plan: Plan, email: str, current_inbound_ids: list[int] | None = None):
        """Renew a public service and rebuild its plan inbound scope.

        Sanaei/3x-ui may remove every membership when an expired client becomes
        disabled. Renewal therefore reasserts the plan scope after enabling:
        manual plans use exactly the administrator-selected IDs, while automatic
        plans fetch every currently active inbound directly from the panel.
        Existing extra memberships are never detached.
        """
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login():
                raise RuntimeError('X-UI login failed')
            mode = self._plan_inbound_mode(plan)
            renewal_inbound_ids = await self._renewal_inbound_ids(
                xui,
                server,
                mode=mode,
                configured_ids=self._configured_inbound_ids(server, plan),
            )
            return await xui.reset_client_plan(
                email,
                plan.volume_gb,
                plan.duration_days,
                inbound_ids=renewal_inbound_ids,
                current_inbound_ids_hint=current_inbound_ids,
            )
        finally:
            await xui.close()

    async def reset_client_plan(self, server: Server, email: str, total_gb: float, expire_days: int, inbound_ids: list[int] | None = None, current_inbound_ids: list[int] | None = None):
        xui = XUIClient(server.panel_url, server.username, decrypt_text(server.password_encrypted))
        try:
            if not await xui.login(): raise RuntimeError('X-UI login failed')
            return await xui.reset_client_plan(
                email,
                total_gb,
                expire_days,
                inbound_ids=inbound_ids,
                current_inbound_ids_hint=current_inbound_ids,
            )
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
