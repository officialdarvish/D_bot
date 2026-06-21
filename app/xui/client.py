from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx


@dataclass
class XuiClientPayload:
    email: str
    total_gb: float
    expire_days: int
    enable: bool = True


class XUIClient:
    def __init__(self, panel_url: str, username: str, password: str, timeout: int = 20):
        # X-UI panels are often published under a secret web base path, for example:
        # https://domain.com/U76peSug8RbmlymBHQ/ .
        # httpx would drop that path when we call an absolute URL like /panel/api/... .
        # Keep the origin as base_url and prepend the secret path ourselves.
        raw_url = panel_url.rstrip("/")
        parsed = urlsplit(raw_url)
        self.panel_url = raw_url
        self._path_prefix = parsed.path.rstrip("/") if parsed.path and parsed.path != "/" else ""
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else raw_url
        self.username = username
        self.password = password
        self.timeout = timeout
        self.csrf_token: str | None = None
        self.client = httpx.AsyncClient(
            base_url=origin,
            timeout=timeout,
            follow_redirects=True,
        )

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        if self._path_prefix and not path.startswith(self._path_prefix + "/") and path != self._path_prefix:
            return self._path_prefix + path
        return path

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        return await self.client.get(self._url(path), **kwargs)

    async def _post(self, path: str, **kwargs) -> httpx.Response:
        return await self.client.post(self._url(path), **kwargs)

    async def _delete(self, path: str, **kwargs) -> httpx.Response:
        return await self.client.delete(self._url(path), **kwargs)

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, *, form: bool = False, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }
        if form:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token
        return headers

    async def _load_login_page(self) -> None:
        response = await self._get("/")
        response.raise_for_status()
        match = re.search(r'name="csrf-token"\s+content="([^"]+)"', response.text)
        if match:
            self.csrf_token = match.group(1)

    async def login(self) -> bool:
        # 3x-ui newer builds require a cookie + CSRF token before POST /login.
        await self._load_login_page()
        response = await self._post(
            "/login",
            data={"username": self.username, "password": self.password},
            headers=self._headers(form=True),
        )

        if response.status_code not in (200, 204):
            return False

        try:
            data = response.json()
            return bool(data.get("success", True))
        except Exception:
            return True

    async def get_inbounds(self) -> list[dict[str, Any]]:
        last_response: httpx.Response | None = None
        for path in (
            "/panel/api/inbounds/list",
            "/panel/inbound/list",
            "/xui/API/inbounds/list",
            "/xui/API/inbounds/",
        ):
            response = await self._get(path, headers=self._headers())
            last_response = response
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                obj = data.get("obj", [])
                return obj if isinstance(obj, list) else []
            return data if isinstance(data, list) else []

        if last_response:
            last_response.raise_for_status()
        return []

    @staticmethod
    def _build_client(payload: XuiClientPayload) -> dict[str, Any]:
        total_bytes = int(payload.total_gb * 1024**3) if payload.total_gb else 0
        expiry = int((time.time() + payload.expire_days * 86400) * 1000) if payload.expire_days else 0

        client_id = str(uuid.uuid4())
        # Match 3x-ui's own ClientFormModal create payload.  The panel sends a
        # UUID plus protocol-specific shared secrets; when a user is attached to
        # mixed inbounds (VLESS/VMess/Trojan/SS/Hysteria), missing password/auth
        # fields can make some attached inbounds unusable or invisible.
        secret = uuid.uuid4().hex[:16]
        return {
            "id": client_id,
            "email": payload.email,
            "enable": payload.enable,
            "totalGB": total_bytes,
            "expiryTime": expiry,
            "limitIp": 0,
            "tgId": 0,
            "subId": uuid.uuid4().hex[:16],
            "reset": 0,
            "flow": "",
            "security": "auto",
            "password": secret,
            "auth": secret,
        }

    @staticmethod
    def _parse_json_field(value: Any, default: Any = None) -> Any:
        if default is None:
            default = {}
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return default
        return value if value is not None else default

    @staticmethod
    def _inbound_needs_vision(inbound: dict[str, Any]) -> bool:
        protocol = str(inbound.get("protocol") or "").lower()
        stream = XUIClient._parse_json_field(inbound.get("streamSettings"), {})
        security = str((stream or {}).get("security") or "").lower()
        return protocol == "vless" and security == "reality"

    async def _prepare_client_for_inbounds(self, inbound_ids: list[int], client: dict[str, Any]) -> dict[str, Any]:
        """Do not modify protocol/stream settings for reseller-created configs.

        The source of truth is the inbound IDs configured on the reseller server.
        We only send the client to those inbound IDs; we do not force flow,
        transport, TLS, Reality, or any per-inbound config value here.
        """
        return client

    async def _post_json_ok(self, paths: tuple[str, ...], body: dict[str, Any]) -> dict[str, Any] | None:
        last_error = None
        for path in paths:
            try:
                response = await self._post(path, json=body, headers=self._headers(json_body=True))
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception:
                    data = {"success": response.status_code in (200, 204), "raw": response.text}
                if isinstance(data, dict) and data.get("success") is False:
                    last_error = str(data.get("msg") or data)
                    continue
                return data if isinstance(data, dict) else {"success": True, "obj": data}
            except Exception as exc:
                last_error = str(exc)
                continue
        if last_error:
            return {"success": False, "msg": last_error}
        return None

    @staticmethod
    def _required_client_identifier_for_inbound(inbound: dict[str, Any], client: dict[str, Any]) -> str:
        """Return the field 3x-ui validates as the client ID for this protocol."""
        protocol = str(inbound.get("protocol") or "").lower()
        if protocol == "trojan":
            return str(client.get("password") or "").strip()
        if protocol == "shadowsocks":
            return str(client.get("email") or "").strip()
        if protocol == "hysteria":
            return str(client.get("auth") or "").strip()
        return str(client.get("id") or client.get("uuid") or "").strip()

    async def _remove_empty_clients_from_inbounds(self, inbound_ids: list[int]) -> int:
        """Clean corrupted empty clients that make 3x-ui return `empty client ID`.

        3x-ui 3.3.x validates every client in an inbound when the UI/API saves
        attached inbounds. A single old empty client inside settings.clients can
        make a valid new client fail with `empty client ID`. This removes only
        records that have no required identifier for that inbound protocol.
        """
        wanted = {int(x) for x in inbound_ids if str(x).isdigit() or isinstance(x, int)}
        removed = 0
        try:
            inbounds = await self.get_inbounds()
        except Exception:
            return 0
        for inbound in inbounds:
            try:
                iid = int(inbound.get("id"))
            except Exception:
                continue
            if iid not in wanted:
                continue
            settings = inbound.get("settings") or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            if not isinstance(settings, dict):
                continue
            clients = settings.get("clients") or []
            if not isinstance(clients, list):
                continue
            kept = []
            changed = False
            for c in clients:
                if not isinstance(c, dict):
                    changed = True
                    removed += 1
                    continue
                if not self._required_client_identifier_for_inbound(inbound, c):
                    changed = True
                    removed += 1
                    continue
                kept.append(c)
            if changed:
                await self._update_inbound_clients(inbound, kept)
        return removed

    async def _rewrite_attached_inbounds_legacy(self, email: str, inbound_ids: list[int], client: dict[str, Any]) -> dict[str, Any]:
        """Legacy clear-all/select-all fallback by rewriting settings.clients.

        This is used only when the new 3x-ui client attachment API refuses the
        request. It removes the client from every inbound and writes it back to
        the selected inbounds, which is the closest safe API equivalent of Clear
        All + Select All.
        """
        clean_ids = []
        for item in inbound_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid > 0 and iid not in clean_ids:
                clean_ids.append(iid)
        wanted = set(clean_ids)
        real_email = str(email or client.get("email") or "").strip()
        if not real_email:
            raise RuntimeError("Cannot attach client without email")
        base_client = dict(client)
        base_client["email"] = real_email
        base_client.setdefault("enable", True)
        if not base_client.get("id") and not base_client.get("uuid"):
            base_client["id"] = str(uuid.uuid4())
        inbounds = await self.get_inbounds()
        touched = 0
        for inbound in inbounds:
            try:
                iid = int(inbound.get("id"))
            except Exception:
                continue
            settings = inbound.get("settings") or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            if not isinstance(settings, dict):
                settings = {}
            clients = settings.get("clients") or []
            if not isinstance(clients, list):
                clients = []
            new_clients = []
            for c in clients:
                if isinstance(c, dict) and str(c.get("email") or "") == real_email:
                    continue
                if isinstance(c, dict) and self._required_client_identifier_for_inbound(inbound, c):
                    new_clients.append(c)
            if iid in wanted:
                attach_client = await self._prepare_client_for_inbounds([iid], dict(base_client))
                new_clients.append(attach_client)
            await self._update_inbound_clients(inbound, new_clients)
            touched += 1
        return {"success": True, "method": "legacy-clear-select", "inboundIds": clean_ids, "touched": touched, "client": base_client}

    async def sync_client_attached_inbounds(self, email: str, inbound_ids: list[int], client: dict[str, Any] | None = None) -> dict[str, Any]:
        """Force 3x-ui's Attached inbounds to match the selected list.

        This mirrors the panel behavior: Clear All, then Select All, then Save.
        3x-ui 3.x stores attachment in client/inbound relation tables, so only
        appending the client to old inbound settings is not enough.
        """
        clean_ids: list[int] = []
        for item in inbound_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid > 0 and iid not in clean_ids:
                clean_ids.append(iid)
        if not clean_ids:
            raise RuntimeError("No inbound id was provided for attach sync")

        found = await self.find_client(email)
        real_client = dict(client or (found or {}).get("client") or {})
        real_email = str(real_client.get("email") or email)
        if real_client:
            real_client = await self._prepare_client_for_inbounds(clean_ids, real_client)
            # Most 3x-ui 3.3.x builds save Attached inbounds on client update when
            # inboundIds is present. Try this first because it is exactly like saving
            # the client edit modal after Clear All + Select All.
            update_body = dict(real_client)
            update_body["inboundIds"] = clean_ids
            update_error = None
            try:
                updated = await self._client_api_update_by_email(real_email, update_body)
            except Exception as exc:
                update_error = str(exc)
                updated = False
                # 3x-ui may reject saving if an old empty client exists in one of
                # the selected inbounds. Clean only those broken rows and retry.
                if "empty client id" in update_error.lower():
                    try:
                        await self._remove_empty_clients_from_inbounds(clean_ids)
                        updated = await self._client_api_update_by_email(real_email, update_body)
                    except Exception as exc2:
                        update_error = str(exc2)
                        updated = False
            if updated:
                return {"success": True, "method": "clients/update", "inboundIds": clean_ids, "client": real_client}

        # Safe append-only attach. The previous implementation detached the user
        # from all inbounds before attaching again. On reseller creation/update,
        # if the second attach request is rejected by 3x-ui, the panel ends up
        # showing Attached inbounds as cleared. Never Clear All here.
        try:
            attach = await self._official_bulk_attach(real_email, clean_ids)
            ok, got_ids = await self._verify_client_inbounds(real_email, clean_ids)
            if ok:
                return {"success": True, "method": attach.get("method", "safe-attach"), "inboundIds": clean_ids, "got": got_ids, "client": real_client}
            raise RuntimeError(f"verification failed after safe attach; expected={clean_ids}, got={got_ids}")
        except Exception as exc:
            raise RuntimeError(f"Attached inbounds sync failed without clearing existing attachments: {exc}")

    async def _post_variants(self, path: str, body: dict[str, Any]) -> httpx.Response:
        """Try JSON first, then form, because 3x-ui builds differ."""
        # JSON body
        response = await self._post(path, json=body, headers=self._headers(json_body=True))
        if response.status_code not in (400, 404, 405, 415):
            return response

        # Raw JSON body with explicit content-type
        response2 = await self._post(
            path,
            content=json.dumps(body, ensure_ascii=False),
            headers=self._headers(json_body=True),
        )
        if response2.status_code not in (400, 404, 405, 415):
            return response2

        # Form body. Some old x-ui APIs expect form fields.
        response3 = await self._post(path, data=body, headers=self._headers(form=True))
        return response3

    async def _update_inbound_append_client(self, inbound_id: int, client: dict[str, Any]) -> dict[str, Any]:
        """Fallback for 3x-ui builds where addClient endpoint is unavailable.

        It reads the inbound, appends the client into settings.clients, and sends
        the full inbound back to /panel/api/inbounds/update/{id}.
        """
        inbounds = await self.get_inbounds()
        inbound = next((item for item in inbounds if int(item.get("id", 0)) == int(inbound_id)), None)
        if not inbound:
            raise RuntimeError(f"Inbound id {inbound_id} was not found in X-UI inbounds/list")

        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        if not isinstance(settings, dict):
            settings = {}

        clients = settings.get("clients")
        if not isinstance(clients, list):
            clients = []
        clients.append(client)
        settings["clients"] = clients

        def dump(value: Any) -> str:
            if isinstance(value, str):
                return value
            return json.dumps(value or {}, ensure_ascii=False)

        body: dict[str, Any] = {
            "up": inbound.get("up", 0),
            "down": inbound.get("down", 0),
            "total": inbound.get("total", 0),
            "remark": inbound.get("remark", ""),
            "enable": inbound.get("enable", True),
            "expiryTime": inbound.get("expiryTime", 0),
            "listen": inbound.get("listen", ""),
            "port": inbound.get("port"),
            "protocol": inbound.get("protocol"),
            "settings": json.dumps(settings, ensure_ascii=False),
            "streamSettings": dump(inbound.get("streamSettings")),
            "sniffing": dump(inbound.get("sniffing")),
        }

        # Keep optional fields when present in newer 3x-ui builds.
        for key in ("tag", "allocate", "nodeId", "originNodeGuid"):
            if key in inbound and inbound.get(key) is not None:
                body[key] = inbound.get(key)

        attempts = [
            f"/panel/api/inbounds/update/{inbound_id}",
            f"/panel/api/inbounds/update/{inbound_id}/",
            f"/panel/inbound/update/{inbound_id}",
            f"/xui/API/inbounds/update/{inbound_id}",
        ]

        last_response: httpx.Response | None = None
        for path in attempts:
            response = await self._post_variants(path, body)
            last_response = response
            if response.status_code == 404:
                continue
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"success": response.status_code in (200, 204), "raw": response.text}
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"X-UI update inbound failed: {data.get('msg') or data}")
            if isinstance(data, dict):
                data["_client"] = client
                data["_endpoint"] = path
                data["_fallback"] = "update_inbound"
                return data
            return {"success": True, "obj": data, "_client": client, "_endpoint": path, "_fallback": "update_inbound"}

        if last_response is not None:
            raise RuntimeError(f"X-UI update inbound fallback failed. Last endpoint returned {last_response.status_code}: {last_response.text[:500]}")
        raise RuntimeError("X-UI update inbound fallback failed before any HTTP response was received")

    async def _client_api_create(self, inbound_id: int, client: dict[str, Any]) -> dict[str, Any] | None:
        """3x-ui v3.x official client API: POST /panel/api/clients/add."""
        return await self._client_api_create_many([int(inbound_id)], client)

    async def _client_api_create_many(self, inbound_ids: list[int], client: dict[str, Any]) -> dict[str, Any] | None:
        """3x-ui v3.x official client API: POST /panel/api/clients/add.

        IMPORTANT: In 3x-ui 3.x the email is global. When a plan uses multiple
        inbound IDs, the same client must be created in ONE request with
        inboundIds=[...]. Calling /clients/add once per inbound creates the first
        client and then fails with "email already in use" on the second inbound.
        """
        clean_ids = []
        for item in inbound_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid not in clean_ids:
                clean_ids.append(iid)
        if not clean_ids:
            raise RuntimeError("No inbound id was provided for client creation")

        body = {"client": client, "inboundIds": clean_ids}
        attempts = (
            "/panel/api/clients/add",
            "/panel/api/clients/add/",
        )
        last_response: httpx.Response | None = None
        for path in attempts:
            response = await self._post(path, json=body, headers=self._headers(json_body=True))
            last_response = response
            if response.status_code == 404:
                continue
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"success": response.status_code in (200, 204), "raw": response.text}
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"3x-ui clients/add failed: {data.get('msg') or data}")
            if isinstance(data, dict):
                data["_client"] = client
                data["_endpoint"] = path
                data["_api"] = "clients/add"
                return data
            return {"success": True, "obj": data, "_client": client, "_endpoint": path, "_api": "clients/add"}
        return None

    async def _client_api_delete_by_email(self, email: str, *, keep_traffic: bool = False) -> bool:
        """3x-ui v3.x official delete API: POST /panel/api/clients/del/{email}."""
        safe_email = quote(str(email), safe="")
        suffix = "?keepTraffic=1" if keep_traffic else ""
        attempts = (
            f"/panel/api/clients/del/{safe_email}{suffix}",
            f"/panel/api/clients/del/{safe_email}/{suffix}",
        )
        for path in attempts:
            response = await self._post(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                return response.status_code in (200, 204)
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"3x-ui clients/del failed: {data.get('msg') or data}")
            return True
        return False

    async def _client_api_get_by_email(self, email: str) -> dict[str, Any] | None:
        """3x-ui v3.x official get API: returns client + attached inboundIds."""
        safe_email = quote(str(email), safe="")
        for path in (
            f"/panel/api/clients/get/{safe_email}",
            f"/panel/api/clients/get/{safe_email}/",
        ):
            response = await self._get(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                return None
            if isinstance(data, dict) and data.get("success") is False:
                raise RuntimeError(f"3x-ui clients/get failed: {data.get('msg') or data}")
            obj = data.get("obj") if isinstance(data, dict) else data
            return obj if isinstance(obj, dict) else None
        return None

    @staticmethod
    def _extract_inbound_ids_from_client_obj(obj: Any) -> list[int]:
        ids: list[int] = []
        if not isinstance(obj, dict):
            return ids
        candidates = []
        for key in (
            "inboundIds", "inbound_ids", "attachedInboundIds", "attached_inbound_ids",
            "inbounds", "attachedInbounds", "attached_inbounds",
        ):
            value = obj.get(key)
            if value is not None:
                candidates.append(value)
        client = obj.get("client") if isinstance(obj.get("client"), dict) else None
        if client:
            for key in ("inboundIds", "inbound_ids", "attachedInboundIds", "inbounds"):
                value = client.get(key)
                if value is not None:
                    candidates.append(value)
        for value in candidates:
            if isinstance(value, str):
                parts = re.split(r"[,\s]+", value.strip())
            elif isinstance(value, (list, tuple, set)):
                parts = list(value)
            else:
                parts = [value]
            for item in parts:
                if isinstance(item, dict):
                    item = item.get("id") or item.get("inbound_id") or item.get("inboundId")
                try:
                    iid = int(item)
                except Exception:
                    continue
                if iid > 0 and iid not in ids:
                    ids.append(iid)
        return ids

    async def _verify_client_inbounds(self, email: str, expected_ids: list[int]) -> tuple[bool, list[int]]:
        """Verify Attached inbounds using the official client API, then fallback to scanning inbounds."""
        expected: list[int] = []
        for item in expected_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid > 0 and iid not in expected:
                expected.append(iid)
        if not expected:
            return False, []

        got: list[int] = []
        try:
            obj = await self._client_api_get_by_email(email)
            got = self._extract_inbound_ids_from_client_obj(obj)
        except Exception:
            got = []

        if not got:
            try:
                inbounds = await self.get_inbounds()
            except Exception:
                inbounds = []
            for inbound in inbounds:
                try:
                    iid = int(inbound.get("id"))
                except Exception:
                    continue
                settings = inbound.get("settings") or {}
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except Exception:
                        settings = {}
                clients = (settings or {}).get("clients") or []
                if not isinstance(clients, list):
                    continue
                for c in clients:
                    if isinstance(c, dict) and str(c.get("email") or "") == str(email):
                        if iid not in got:
                            got.append(iid)
                        break

        return set(expected).issubset(set(got)), got

    async def _official_bulk_attach(self, email: str, inbound_ids: list[int]) -> dict[str, Any]:
        """Press the same action as Attached inbounds Select All, without detaching anything."""
        clean_ids: list[int] = []
        for item in inbound_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid > 0 and iid not in clean_ids:
                clean_ids.append(iid)
        if not clean_ids:
            raise RuntimeError("No inbound id was provided for attach")
        safe_email = quote(str(email), safe="")
        body = {"inboundIds": clean_ids}
        attempts = (
            f"/panel/api/clients/{safe_email}/attach",
            f"/panel/api/clients/{safe_email}/attach/",
            "/panel/api/clients/bulkAttach",
            "/panel/api/clients/bulkAttach/",
        )
        last_error: str | None = None
        for path in attempts:
            payload = body if "bulkAttach" not in path else {"emails": [str(email)], "inboundIds": clean_ids}
            try:
                response = await self._post(path, json=payload, headers=self._headers(json_body=True))
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception:
                    data = {"success": response.status_code in (200, 204), "raw": response.text}
                if isinstance(data, dict) and data.get("success") is False:
                    last_error = str(data.get("msg") or data)
                    continue
                if isinstance(data, dict):
                    data["method"] = "clients/attach" if "bulkAttach" not in path else "clients/bulkAttach"
                    data["inboundIds"] = clean_ids
                    return data
                return {"success": True, "obj": data, "method": "clients/attach", "inboundIds": clean_ids}
            except Exception as exc:
                last_error = str(exc)
                continue
        raise RuntimeError(last_error or "3x-ui attach endpoint was not available")

    async def _client_api_update_by_email(self, email: str, client: dict[str, Any]) -> bool:
        """3x-ui v3.x official update API: POST /panel/api/clients/update/{email}.

        3x-ui can occasionally return PostgreSQL deadlock errors when traffic
        counters are being written at the same time. Retry the exact same update
        a few times before failing.
        """
        safe_email = quote(str(email), safe="")
        attempts = (
            f"/panel/api/clients/update/{safe_email}",
            f"/panel/api/clients/update/{safe_email}/",
        )
        last_error: str | None = None
        for retry in range(5):
            for path in attempts:
                response = await self._post(path, json=client, headers=self._headers(json_body=True))
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception:
                    return response.status_code in (200, 204)
                if isinstance(data, dict) and data.get("success") is False:
                    msg = str(data.get('msg') or data)
                    last_error = msg
                    if 'deadlock' in msg.lower() and retry < 4:
                        await asyncio.sleep(0.5 + retry * 0.5)
                        continue
                    raise RuntimeError(f"3x-ui clients/update failed: {msg}")
                return True
        if last_error:
            raise RuntimeError(f"3x-ui clients/update failed: {last_error}")
        return False

    async def _client_api_reset_traffic_by_email(self, email: str) -> bool:
        """Press the same action as the red Reset Traffic button in 3x-ui UI."""
        safe_email = quote(str(email), safe="")
        attempts = (
            f"/panel/api/clients/resetTraffic/{safe_email}",
            f"/panel/api/clients/resetTraffic/{safe_email}/",
        )
        last_error: str | None = None
        for retry in range(5):
            for path in attempts:
                response = await self._post(path, headers=self._headers())
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception:
                    return response.status_code in (200, 204)
                if isinstance(data, dict) and data.get("success") is False:
                    msg = str(data.get('msg') or data)
                    last_error = msg
                    if 'deadlock' in msg.lower() and retry < 4:
                        await asyncio.sleep(0.5 + retry * 0.5)
                        continue
                    raise RuntimeError(f"3x-ui clients/resetTraffic failed: {msg}")
                return True
        if last_error:
            raise RuntimeError(f"3x-ui clients/resetTraffic failed: {last_error}")
        return False

    async def add_client_to_inbounds(self, inbound_ids: list[int], payload: XuiClientPayload) -> dict[str, Any]:
        """Add one client to one or more inbounds.

        This is the correct path for 3x-ui 3.3.x plans that contain multiple
        inbound IDs: one email, one UUID/subId, one /clients/add request with
        all inbound IDs.
        """
        ids = []
        for item in inbound_ids:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid not in ids:
                ids.append(iid)
        if not ids:
            raise RuntimeError("No inbound id was provided for client creation")

        client = await self._prepare_client_for_inbounds(ids, self._build_client(payload))
        created = await self._client_api_create_many(ids, client)
        if created is not None:
            # 3x-ui 3.3.1 already applies per-inbound protocol defaults inside
            # /panel/api/clients/add. Calling Clear All + Select All immediately
            # after creation can rebuild non-Reality inbounds from an incomplete
            # client record and make only Reality ping. So we verify first and only
            # attach missing IDs without detaching existing working ones.
            try:
                ok = False
                got_ids: list[int] = []
                # Give 3x-ui a short moment to persist the relation rows before
                # deciding that an inbound is missing.
                for _ in range(5):
                    ok, got_ids = await self._verify_client_inbounds(payload.email, ids)
                    if ok:
                        break
                    await asyncio.sleep(0.35)
                created["_attached_verify"] = {"ok": ok, "expected": ids, "got": got_ids}
                if not ok:
                    # Use the same action as Select All in the 3x-ui client UI.
                    # Send the FULL configured list, not only the currently missing
                    # ids, because the panel attach endpoint is idempotent and this
                    # avoids stale/partial relation rows.
                    attach = await self._official_bulk_attach(payload.email, ids)
                    created["_attached_select_all"] = attach
                    ok2, got2 = await self._verify_client_inbounds(payload.email, ids)
                    created["_attached_verify_after_attach"] = {"ok": ok2, "expected": ids, "got": got2}
                    if not ok2:
                        raise RuntimeError(
                            f"Attached inbounds verify failed for {payload.email}: "
                            f"expected={ids}, got={got2}. Check reseller build inbound IDs."
                        )
            except Exception as exc:
                created["_attached_verify_error"] = str(exc)
            return created

        # Legacy fallback: older x-ui versions do not have /panel/api/clients/add.
        results = []
        for inbound_id in ids:
            results.append(await self._update_inbound_append_client(inbound_id, dict(client)))
        return {"success": True, "results": results, "_client": client, "_fallback": "update_inbound_many"}

    async def add_client(self, inbound_id: int, payload: XuiClientPayload) -> dict[str, Any]:
        """Add a client to 3x-ui.

        Version 3.3.1 no longer uses /panel/api/inbounds/addClient.
        The correct API is /panel/api/clients/add with {client, inboundIds}.
        Older forks are still supported with update-inbound fallback.
        """
        client = self._build_client(payload)

        # 3x-ui 3.x official API. This is the endpoint used by the current UI.
        created = await self._client_api_create(inbound_id, client)
        if created is not None:
            return created

        # Legacy Sanai/x-ui endpoints. Kept only as fallback for older panels.
        settings = json.dumps({"clients": [client]}, ensure_ascii=False)
        attempts: list[tuple[str, dict[str, Any]]] = [
            ("/panel/api/inbounds/addClient", {"id": inbound_id, "settings": settings}),
            (f"/panel/api/inbounds/addClient/{inbound_id}", {"settings": settings}),
        ]

        last_response: httpx.Response | None = None
        errors: list[str] = []
        for path, body in attempts:
            try:
                response = await self._post_variants(path, body)
                last_response = response
                if response.status_code == 404:
                    errors.append(f"{path}=404")
                    continue
                response.raise_for_status()
                try:
                    data = response.json()
                except Exception:
                    data = {"success": response.status_code in (200, 204), "raw": response.text}
                if isinstance(data, dict) and data.get("success") is False:
                    errors.append(f"{path}={data.get('msg') or data}")
                    continue
                if isinstance(data, dict):
                    data["_client"] = client
                    data["_endpoint"] = path
                    return data
                return {"success": True, "obj": data, "_client": client, "_endpoint": path}
            except Exception as exc:
                errors.append(f"{path}={exc}")
                continue

        try:
            return await self._update_inbound_append_client(inbound_id, client)
        except Exception as exc:
            details = "; ".join(errors[-8:])
            if last_response is not None:
                raise RuntimeError(
                    f"X-UI add client failed. 3x-ui clients/add was unavailable and legacy fallback failed. "
                    f"Last legacy status={last_response.status_code}, body={last_response.text[:300]}, "
                    f"fallback_error={exc}, tried={details}"
                ) from exc
            raise RuntimeError(f"X-UI add client failed: {exc}; tried={details}") from exc

    @staticmethod
    def _unwrap_obj(data: Any) -> Any:
        if isinstance(data, dict) and "obj" in data:
            return data.get("obj")
        return data

    @staticmethod
    def _normalize_ip_item(item: Any) -> str | None:
        if isinstance(item, dict):
            ip = str(item.get("ip") or item.get("IP") or "").strip()
        else:
            ip = str(item or "").strip()
            if " (" in ip:
                ip = ip.split(" (", 1)[0].strip()
        if not ip or ip.lower() in {"no ip record", "null", "none"}:
            return None
        return ip

    async def get_online_clients(self) -> list[str]:
        """Return online client emails from 3x-ui 3.3.x official API."""
        for path in (
            "/panel/api/clients/onlines",
            "/panel/api/inbounds/onlines",
        ):
            response = await self._post(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = self._unwrap_obj(response.json())
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
            return []
        return []

    async def get_client_ips(self, email: str) -> list[str]:
        """Return unique IPs recorded by 3x-ui for one client email.

        3x-ui 3.3.x fills this from Xray online-stats API first and only falls
        back to access.log internally. The bot should call this API instead of
        parsing access.log itself.
        """
        safe_email = quote(str(email), safe="")
        for path in (
            f"/panel/api/clients/ips/{safe_email}",
            f"/panel/api/inbounds/client/ips/{safe_email}",
        ):
            response = await self._post(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = self._unwrap_obj(response.json())
            if isinstance(data, list):
                ips=[]
                for item in data:
                    ip = self._normalize_ip_item(item)
                    if ip and ip not in ips:
                        ips.append(ip)
                return ips
            ip = self._normalize_ip_item(data)
            return [ip] if ip else []
        return []

    async def clear_client_ips(self, email: str) -> bool:
        safe_email = quote(str(email), safe="")
        for path in (f"/panel/api/clients/clearIps/{safe_email}",):
            response = await self._post(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            return True
        return False

    async def set_client_enabled(self, email: str, enabled: bool) -> bool:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("Client was not found on 3x-ui panel")
        client = dict(found["client"] or {})
        real_email = str(client.get("email") or email)
        client["enable"] = bool(enabled)
        updated = await self._client_api_update_by_email(real_email, client)
        if updated:
            return True

        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            settings = inbound.get("settings")
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            clients = (settings or {}).get("clients") or []
            changed = False
            for c in clients:
                if str(c.get("email", "")) == real_email:
                    c["enable"] = bool(enabled)
                    changed = True
            if changed:
                await self._update_inbound_clients(inbound, clients)
                return True
        return False

    async def get_client_traffic(self, email: str) -> dict[str, Any] | None:
        safe_email = quote(str(email), safe="")
        for path in (
            f"/panel/api/clients/traffic/{safe_email}",
            f"/panel/api/inbounds/getClientTraffics/{safe_email}",
            f"/panel/inbound/getClientTraffics/{safe_email}",
            f"/xui/API/inbounds/getClientTraffics/{safe_email}",
        ):
            response = await self._get(path, headers=self._headers())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            return data.get("obj") if isinstance(data, dict) else data
        return None


    async def find_client(self, keyword: str) -> dict[str, Any] | None:
        """Find a client by username/email, uuid, subId, subscription link token.

        Important: for Sanai/3x-ui the real Subscription ID can be stored in
        settings.clients[*].subId OR in getClientTraffics response depending on
        version. This method always tries both and returns the real panel value.
        """
        key = (keyword or "").strip()
        key = key.rstrip("/").split("/")[-1].split("?")[0].split("#")[0]
        inbounds = await self.get_inbounds()

        for inbound in inbounds:
            settings = inbound.get("settings")
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}

            clients = (settings or {}).get("clients", [])
            if not isinstance(clients, list):
                continue

            for client in clients:
                email = str(client.get("email", "") or "")
                uuid_value = str(client.get("id", "") or client.get("uuid", "") or "")
                sub_id = str(client.get("subId", "") or client.get("sub_id", "") or "")

                fields = [email, uuid_value, sub_id]
                matched = any(key == f or (key and key in f) for f in fields if f)
                if not matched:
                    continue

                traffic = None
                if email:
                    try:
                        traffic = await self.get_client_traffic(email)
                    except Exception:
                        traffic = None

                # Prefer the Subscription ID that the panel reports.
                if isinstance(traffic, dict):
                    traffic_sub = (
                        traffic.get("subId")
                        or traffic.get("sub_id")
                        or traffic.get("subscriptionId")
                        or traffic.get("subscription_id")
                    )
                    if traffic_sub:
                        client["subId"] = str(traffic_sub)

                    traffic_uuid = traffic.get("id") or traffic.get("uuid")
                    if traffic_uuid and not (client.get("id") or client.get("uuid")):
                        client["id"] = str(traffic_uuid)

                return {
                    "inbound_id": inbound.get("id"),
                    "remark": inbound.get("remark"),
                    "client": client,
                    "traffic": traffic,
                }

        return None


    async def _update_inbound_clients(self, inbound: dict[str, Any], clients: list[dict[str, Any]]) -> dict[str, Any]:
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        if not isinstance(settings, dict):
            settings = {}
        settings["clients"] = clients
        def dump(value: Any) -> str:
            if isinstance(value, str):
                return value
            return json.dumps(value or {}, ensure_ascii=False)
        inbound_id = int(inbound.get("id"))
        body = {"up": inbound.get("up", 0), "down": inbound.get("down", 0), "total": inbound.get("total", 0), "remark": inbound.get("remark", ""), "enable": inbound.get("enable", True), "expiryTime": inbound.get("expiryTime", 0), "listen": inbound.get("listen", ""), "port": inbound.get("port"), "protocol": inbound.get("protocol"), "settings": json.dumps(settings, ensure_ascii=False), "streamSettings": dump(inbound.get("streamSettings")), "sniffing": dump(inbound.get("sniffing"))}
        for key in ("tag", "allocate", "nodeId", "originNodeGuid"):
            if key in inbound and inbound.get(key) is not None:
                body[key] = inbound.get(key)
        for path in (f"/panel/api/inbounds/update/{inbound_id}", f"/panel/api/inbounds/update/{inbound_id}/", f"/panel/inbound/update/{inbound_id}", f"/xui/API/inbounds/update/{inbound_id}"):
            response = await self._post_variants(path, body)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            return {"success": True, "inbound_id": inbound_id, "endpoint": path}
        raise RuntimeError("Could not update inbound clients on X-UI panel")


    @staticmethod
    def _client_matches(client: dict[str, Any], identifiers: set[str]) -> bool:
        values = {
            str(client.get("email", "") or "").strip(),
            str(client.get("id", "") or "").strip(),
            str(client.get("uuid", "") or "").strip(),
            str(client.get("subId", "") or "").strip(),
            str(client.get("sub_id", "") or "").strip(),
        }
        values.discard("")
        return bool(values & identifiers)

    @staticmethod
    def _extract_identifier(value: str | None) -> str | None:
        if not value:
            return None
        value = str(value).strip()
        if not value:
            return None
        # Accept raw email/username/uuid/subId, or a subscription link.
        return value.rstrip("/").split("/")[-1].split("?")[0].split("#")[0]

    async def delete_client(self, *identifiers: str | None) -> dict[str, Any]:
        """Fully delete a client from 3x-ui/Sanai panel.

        Test accounts can be created on multiple inbound IDs. Some 3x-ui/Sanai
        builds return success for /panel/api/clients/del/{email}, but the client
        row may still remain inside one or more inbound settings.clients lists.
        To make deletion identical to pressing the red Delete button in the UI,
        this method:
          1) resolves every given identifier to real panel emails/UUID/subId,
          2) calls the official clients/del API when available,
          3) rewrites every affected inbound and removes matching clients from
             settings.clients,
          4) verifies that no matching client is left in the inbound list.
        """
        normalized = {self._extract_identifier(v) for v in identifiers if v}
        normalized = {v for v in normalized if v}
        if not normalized:
            raise RuntimeError("No client identifier was provided for deletion")

        # Resolve to the real email stored on the panel when possible.
        targets: set[str] = set(normalized)
        for ident in list(normalized):
            found = await self.find_client(ident)
            if found and found.get("client"):
                client = found["client"] or {}
                for key in ("email", "id", "uuid", "subId", "sub_id"):
                    value = str(client.get(key) or "").strip()
                    if value:
                        targets.add(value)

        def parse_settings(inbound: dict[str, Any]) -> dict[str, Any]:
            settings = inbound.get("settings") or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            return settings if isinstance(settings, dict) else {}

        def client_values(client: dict[str, Any]) -> set[str]:
            vals = {
                str(client.get("email") or "").strip(),
                str(client.get("id") or "").strip(),
                str(client.get("uuid") or "").strip(),
                str(client.get("subId") or "").strip(),
                str(client.get("sub_id") or "").strip(),
            }
            vals.discard("")
            return vals

        # Find every matching client in every inbound, not just the first match.
        inbounds = await self.get_inbounds()
        matched_emails: set[str] = set()
        affected: list[tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]] = []
        for inbound in inbounds:
            settings = parse_settings(inbound)
            clients = settings.get("clients") if isinstance(settings, dict) else []
            if not isinstance(clients, list):
                continue
            remaining: list[dict[str, Any]] = []
            removed_here: list[dict[str, Any]] = []
            for client in clients:
                vals = client_values(client)
                if vals & targets:
                    removed_here.append(client)
                    email = str(client.get("email") or "").strip()
                    if email:
                        matched_emails.add(email)
                        targets.add(email)
                    for key in ("id", "uuid", "subId", "sub_id"):
                        value = str(client.get(key) or "").strip()
                        if value:
                            targets.add(value)
                else:
                    remaining.append(client)
            if removed_here:
                affected.append((inbound, clients, remaining))

        if not affected and not matched_emails:
            # One last try through find_client for panels where list parsing differs.
            for ident in normalized:
                found = await self.find_client(ident)
                if found and found.get("client"):
                    email = str((found.get("client") or {}).get("email") or "").strip()
                    if email:
                        matched_emails.add(email)
            if not matched_emails:
                raise RuntimeError("Client was not found on 3x-ui panel")

        api_removed = 0
        # Call official delete API for all resolved emails. Ignore 404/unavailable
        # because the update-inbound removal below is the source of truth.
        for email in sorted(matched_emails):
            try:
                if await self._client_api_delete_by_email(email, keep_traffic=False):
                    api_removed += 1
            except Exception:
                # Continue to the hard delete fallback below.
                pass

        fallback_removed = 0

        # Hard-delete source of truth: we already computed the affected inbounds
        # BEFORE calling /clients/del. Some Sanai/3x-ui builds return 200 from
        # /panel/api/clients/del/{email} and briefly hide the client from list,
        # but later restore it from the inbound settings. Therefore always write
        # the precomputed remaining clients back to every affected inbound.
        for inbound, old_clients, remaining_clients in affected:
            try:
                await self._update_inbound_clients(inbound, remaining_clients)
                fallback_removed += len(old_clients) - len(remaining_clients)
            except Exception:
                # Continue with the second pass below; if the client still exists,
                # final verification will raise a clear error.
                pass

        # Second pass after official API + hard update: remove any leftovers that
        # may still be visible in fresh inbound data.
        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            settings = parse_settings(inbound)
            clients = settings.get("clients") if isinstance(settings, dict) else []
            if not isinstance(clients, list):
                continue
            new_clients = [c for c in clients if not (client_values(c) & targets)]
            if len(new_clients) != len(clients):
                await self._update_inbound_clients(inbound, new_clients)
                fallback_removed += len(clients) - len(new_clients)

        # Verify by reading the inbound list, not only the traffic API. Traffic
        # rows may remain for history, but the client must not remain in clients.
        leftovers: list[str] = []
        for inbound in await self.get_inbounds():
            settings = parse_settings(inbound)
            clients = settings.get("clients") if isinstance(settings, dict) else []
            if not isinstance(clients, list):
                continue
            for client in clients:
                if client_values(client) & targets:
                    leftovers.append(str(client.get("email") or client.get("id") or "unknown"))
        if leftovers:
            raise RuntimeError("Client deletion was sent, but the client still exists on 3x-ui panel: " + ", ".join(leftovers[:5]))

        total_removed = api_removed + fallback_removed
        if total_removed == 0:
            # If no row remained after refresh, treat as success because the goal
            # is that the client is gone from the panel.
            return {"success": True, "removed": 0, "api_removed": api_removed, "fallback_removed": fallback_removed, "already_absent": True}
        return {"success": True, "removed": total_removed, "api_removed": api_removed, "fallback_removed": fallback_removed}


    async def reset_client_plan(self, email: str, total_gb: float, expire_days: int) -> dict[str, Any]:
        """Renew a 3x-ui client exactly like the UI workflow.

        Required order for the user's 3x-ui 3.3.x panel:
        1) press Reset Traffic,
        2) save the new expiry and traffic limit,
        3) force Enabled=true,
        4) read back and verify the panel really changed.
        """
        total_bytes = int(total_gb * 1024**3) if total_gb else 0
        expiry = int((time.time() + expire_days * 86400) * 1000) if expire_days else 0
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("Client was not found on 3x-ui panel")

        client = dict(found["client"])
        real_email = str(client.get("email") or email)

        # Step 1: this is the same endpoint used by the 3x-ui Reset Traffic button.
        reset_ok = await self._client_api_reset_traffic_by_email(real_email)
        await asyncio.sleep(0.4)

        # Step 2/3: update expiry, volume and enabled state. Do not use reset=1
        # here; resetTraffic already did that and combining both can deadlock.
        client["totalGB"] = total_bytes
        client["expiryTime"] = expiry
        client["enable"] = True
        client["reset"] = int(client.get("reset") or 0)
        updated = await self._client_api_update_by_email(real_email, client)
        if not updated:
            # Legacy fallback: rewrite inbound settings.clients.
            inbounds = await self.get_inbounds()
            for inbound in inbounds:
                settings = inbound.get("settings")
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except Exception:
                        settings = {}
                clients = (settings or {}).get("clients") or []
                changed = False
                for c in clients:
                    if str(c.get("email", "")) == real_email:
                        c["totalGB"] = total_bytes
                        c["expiryTime"] = expiry
                        c["enable"] = True
                        c["reset"] = int(c.get("reset") or 0)
                        changed = True
                if changed:
                    await self._update_inbound_clients(inbound, clients)
                    updated = True
                    break
        if not updated:
            raise RuntimeError("3x-ui panel refused client renewal update")

        await asyncio.sleep(0.5)
        verified = await self.find_client(real_email)
        vclient = (verified or {}).get("client") or {}
        vtraffic = (verified or {}).get("traffic") or {}
        panel_total = int(vclient.get("totalGB") or vtraffic.get("total") or 0)
        panel_expiry = int(vclient.get("expiryTime") or vtraffic.get("expiryTime") or 0)
        panel_enabled = bool(vclient.get("enable", True))
        if total_bytes and panel_total and panel_total != total_bytes:
            raise RuntimeError("3x-ui renewal verification failed: traffic limit was not updated")
        if expiry and panel_expiry and abs(panel_expiry - expiry) > 120000:
            raise RuntimeError("3x-ui renewal verification failed: expiry was not updated")
        if not panel_enabled:
            raise RuntimeError("3x-ui renewal verification failed: client is still disabled")
        return {"success": True, "totalGB": total_bytes, "expiryTime": expiry, "resetTraffic": reset_ok, "api": "clients/resetTraffic+clients/update"}


    async def rotate_client_uuid(self, email: str) -> dict[str, Any]:
        """Rotate UUID/subId using the 3x-ui client API, preserving attached inbounds.

        The previous fallback rewrote only the first inbound that contained the
        client. On 3x-ui 3.3.x, clients can be attached to many inbounds, so the
        correct behavior is to update the global client by email and keep the
        inbound relation table untouched.
        """
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("Client was not found on X-UI panel")

        client = dict(found["client"] or {})
        real_email = str(client.get("email") or email)
        client["id"] = str(uuid.uuid4())
        client["subId"] = uuid.uuid4().hex[:16]

        updated = await self._client_api_update_by_email(real_email, client)
        if updated:
            reread = await self.find_client(real_email)
            if reread and reread.get("client"):
                return {"success": True, "client": reread["client"], "inbound_id": reread.get("inbound_id"), "method": "clients/update"}
            return {"success": True, "client": client, "inbound_id": found.get("inbound_id"), "method": "clients/update"}

        # Legacy fallback: rewrite every inbound containing the client, not just
        # the first one. This keeps old panels working and fixes reseller revoke.
        changed = False
        for inbound in await self.get_inbounds():
            settings = inbound.get("settings")
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            if not isinstance(settings, dict):
                settings = {}
            clients = settings.get("clients") or []
            if not isinstance(clients, list):
                continue
            inbound_changed = False
            for c in clients:
                if str(c.get("email", "")) == real_email:
                    c["id"] = client["id"]
                    c["subId"] = client["subId"]
                    inbound_changed = True
                    changed = True
            if inbound_changed:
                await self._update_inbound_clients(inbound, clients)

        if not changed:
            raise RuntimeError("Client was not found on X-UI panel")

        reread = await self.find_client(real_email)
        return {"success": True, "client": (reread or {}).get("client") or client, "inbound_id": (reread or {}).get("inbound_id"), "method": "update_inbounds"}

