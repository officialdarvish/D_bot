from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

GB = 1024 ** 3


@dataclass(slots=True)
class XuiClientPayload:
    """Minimal client creation payload used by the bot/service layer."""

    email: str
    total_gb: int | float = 0
    expire_days: int = 0
    limit_ip: int = 0
    enable: bool = True

    @property
    def total_bytes(self) -> int:
        try:
            total = float(self.total_gb or 0)
        except Exception:
            total = 0
        return int(total * GB) if total > 0 else 0

    @property
    def expiry_ms(self) -> int:
        try:
            days = int(self.expire_days or 0)
        except Exception:
            days = 0
        if days <= 0:
            return 0
        return int((datetime.utcnow() + timedelta(days=days)).timestamp() * 1000)


class XUIClient:
    """Async client for Sanaei x-ui / 3x-ui panels.

    This wrapper centralizes all Sanaei / 3x-ui communication. Client create,
    update, delete, renew, revoke, traffic and IP actions use the current
    3x-ui Client API after a CSRF/cookie login. Removed inbound-client endpoints
    are never used for client mutations.
    """

    def __init__(self, base_url: str, username: str, password: str, *, timeout: float = 25.0) -> None:
        self.base_url = self._normalize_base_url(base_url)
        if not self.base_url:
            raise ValueError("X-UI base URL is empty")
        self.username = username
        self.password = password
        self.last_error: str = ""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "D-Bot/3x-ui-client",
        }
        # Optional 3x-ui API token support. In the server password/token field,
        # admins may enter: token:<API_TOKEN> or bearer:<API_TOKEN>.
        lowered = (password or "").strip().lower()
        if lowered.startswith("token:") or lowered.startswith("bearer:"):
            token = (password or "").split(":", 1)[1].strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(
            base_url=self.base_url + "/",
            timeout=timeout,
            follow_redirects=True,
            verify=False,
            headers=headers,
        )

    def _normalize_base_url(self, value: str) -> str:
        raw = (value or "").strip().rstrip("/")
        if not raw:
            return ""
        # Admins sometimes paste the full login/API URL. Keep the 3x-ui web
        # base path but strip endpoint tails so requests become:
        #   <origin>/<web-base-path>/login
        #   <origin>/<web-base-path>/panel/api/inbounds/list
        try:
            parsed = urlsplit(raw)
            path = parsed.path or ""
            strip_markers = (
                "/panel/api/openapi.json",
                "/panel/api/inbounds/list",
                "/panel/api/inbounds",
                "/panel/api/clients",
                "/panel/api/server",
                "/panel/api",
                "/panel/inbound",
                "/panel",
                "/login",
            )
            changed = True
            while changed:
                changed = False
                for marker in strip_markers:
                    idx = path.find(marker)
                    if idx >= 0:
                        path = path[:idx]
                        changed = True
                        break
            path = path.rstrip("/")
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")
        except Exception:
            return raw

    async def close(self) -> None:
        await self.client.aclose()

    def _path(self, path: str) -> str:
        """Return a relative URL so httpx keeps hidden 3x-ui base paths.

        With a base URL like https://host/secret/, requesting "/login" would
        jump to https://host/login and lose the secret path. 3x-ui commonly
        uses hidden web base paths, so every API path must be joined relative
        to self.client.base_url.
        """
        clean = (path or "").strip()
        if clean in {"", "/"}:
            return "."
        return clean.lstrip("/")

    def _extract_csrf_token(self, html: str) -> str:
        if not html:
            return ""
        for tag in re.findall(r"<meta[^>]+>", html, flags=re.IGNORECASE):
            if "csrf-token" not in tag.lower():
                continue
            match = re.search(r"content=[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        match = re.search(r"csrf[-_]token[\"']?\s*[:=]\s*[\"']([^\"']+)", html, flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")

    async def _prepare_3xui_session(self) -> str:
        """Load the login shell to receive session cookie + CSRF token.

        Newer 3x-ui builds protect /login and API routes with CSRF. The login
        page at the hidden base path contains <meta name="csrf-token" ...> and
        sets the 3x-ui cookie. We must preserve both for the following login/API
        requests.
        """
        last_error = ""
        for entry in (".", "login", "panel/"):
            try:
                response = await self.client.get(entry)
                token = self._extract_csrf_token(response.text or "")
                if token:
                    self.client.headers["X-CSRF-Token"] = token
                    return token
                if response.status_code < 400 and response.text:
                    # Some older panels do not use CSRF; the cookie is still useful.
                    return ""
                last_error = f"GET {response.url} -> HTTP {response.status_code}"
            except Exception as exc:
                last_error = str(exc)
        self.last_error = last_error or "Could not load 3x-ui login page"
        return ""

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(method, self._path(path), **kwargs)
        if response.status_code >= 400:
            body = (response.text or "").strip().replace("\n", " ")[:300]
            self.last_error = f"{method} {response.url} -> HTTP {response.status_code}: {body}"
            response.raise_for_status()
        ctype = response.headers.get("content-type", "")
        if "application/json" in ctype:
            data = response.json()
            if isinstance(data, dict) and not self._is_success(data):
                self.last_error = self._error_message(data)
            return data
        text = response.text.strip()
        if not text:
            return {"success": response.is_success}
        try:
            data = json.loads(text)
            if isinstance(data, dict) and not self._is_success(data):
                self.last_error = self._error_message(data)
            return data
        except Exception:
            return {"success": response.is_success, "raw": text}

    def _is_success(self, data: Any) -> bool:
        if isinstance(data, dict):
            if "success" in data:
                return bool(data.get("success"))
            if "status" in data and str(data.get("status")).lower() in {"ok", "success", "true"}:
                return True
        return True

    def _obj(self, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("obj", "data", "result", "results"):
                if key in data:
                    return data[key]
        return data

    def _error_message(self, data: Any) -> str:
        if isinstance(data, dict):
            return str(data.get("msg") or data.get("message") or data.get("error") or data)
        return str(data)

    async def login(self) -> bool:
        # If an API token is configured, no form login is needed. Verify it with
        # a lightweight API call so wrong tokens are caught early. 3x-ui also
        # supports panel session-cookie auth from /login.
        if self.client.headers.get("Authorization"):
            try:
                await self._request("GET", "/panel/api/inbounds/list")
                return True
            except Exception as exc:
                self.last_error = str(exc)
                return False

        csrf_token = await self._prepare_3xui_session()
        payload = {"username": self.username, "password": self.password}
        common_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self._origin(),
            "Referer": self.base_url + "/",
        }
        if csrf_token:
            common_headers["X-CSRF-Token"] = csrf_token

        last_error: Exception | None = None
        # New 3x-ui versions accept JSON + CSRF. Older x-ui variants may accept
        # form data. Try both, then verify by calling the inbounds API with the
        # same cookie jar.
        for kwargs in (
            {"json": payload, "headers": common_headers},
            {"data": payload, "headers": common_headers},
        ):
            try:
                response = await self.client.post(self._path("/login"), **kwargs)
                if response.status_code >= 400:
                    body = (response.text or "").strip().replace("\n", " ")[:300]
                    self.last_error = f"POST {response.url} -> HTTP {response.status_code}: {body}"
                    response.raise_for_status()

                # If the server returns a fresh CSRF token after login, keep it.
                new_token = self._extract_csrf_token(response.text or "")
                if new_token:
                    self.client.headers["X-CSRF-Token"] = new_token
                    common_headers["X-CSRF-Token"] = new_token

                try:
                    await self._request("GET", "/panel/api/inbounds/list")
                    return True
                except Exception as exc:
                    last_error = exc
                    continue
            except Exception as exc:
                last_error = exc

        if last_error:
            self.last_error = str(last_error)
        return False

    async def get_inbounds(self) -> list[dict[str, Any]]:
        for method, path in (
            ("GET", "/panel/api/inbounds/list"),
            ("POST", "/panel/api/inbounds/list"),
        ):
            try:
                data = await self._request(method, path)
                if not self._is_success(data):
                    continue
                obj = self._obj(data)
                if isinstance(obj, list):
                    return [x for x in obj if isinstance(x, dict)]
                if isinstance(obj, dict) and isinstance(obj.get("inbounds"), list):
                    return [x for x in obj["inbounds"] if isinstance(x, dict)]
            except Exception:
                continue
        return []

    def _load_settings(self, inbound: dict[str, Any] | None) -> dict[str, Any]:
        if not inbound:
            return {}
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings or "{}")
            except Exception:
                settings = {}
        return settings if isinstance(settings, dict) else {}

    def _client_template(self, payload: XuiClientPayload, inbound: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = self._load_settings(inbound)
        existing_clients = settings.get("clients") if isinstance(settings, dict) else []
        sample = existing_clients[0] if isinstance(existing_clients, list) and existing_clients and isinstance(existing_clients[0], dict) else {}
        client_id = str(uuid.uuid4())
        sub_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
        client = {
            "id": client_id,
            "flow": sample.get("flow", ""),
            "email": payload.email,
            "limitIp": int(payload.limit_ip or 0),
            "totalGB": payload.total_bytes,
            "expiryTime": payload.expiry_ms,
            "enable": bool(payload.enable),
            "tgId": 0,
            "subId": sub_id,
            "reset": 0,
        }
        # Some older panels expect slightly different keys to already exist.
        for key in ("alterId", "security", "method", "password"):
            if key in sample and key not in client:
                client[key] = sample.get(key)
        return client

    def _inbound_map(self, inbounds: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for inbound in inbounds:
            try:
                iid = int(inbound.get("id"))
            except Exception:
                continue
            result[iid] = inbound
        return result

    async def add_client_to_inbounds(self, inbound_ids: list[int], payload: XuiClientPayload) -> dict[str, Any]:
        clean_ids: list[int] = []
        for inbound_id in inbound_ids or []:
            try:
                iid = int(inbound_id)
            except Exception:
                continue
            if iid > 0 and iid not in clean_ids:
                clean_ids.append(iid)
        if not clean_ids:
            raise RuntimeError("No valid inbound IDs supplied")

        inbounds = await self.get_inbounds()
        inbound_by_id = self._inbound_map(inbounds)
        first_inbound = inbound_by_id.get(clean_ids[0])
        new_client = self._client_template(payload, first_inbound)

        # 3x-ui v3.3+ uses the Client API:
        #   POST /panel/api/clients/add
        # with body: {"client": {...}, "inboundIds": [...]}
        # Only the current 3x-ui Client API is used here.
        primary_error: str | None = None
        try:
            data = await self._request(
                "POST",
                "/panel/api/clients/add",
                json={"client": new_client, "inboundIds": clean_ids},
            )
            if self._is_success(data):
                return {"results": [data], "_client": new_client}
            primary_error = self._error_message(data)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = (exc.response.text or "").strip().replace("\n", " ")[:300] if exc.response is not None else ""
            primary_error = f"POST {exc.request.url} -> HTTP {status}: {body}"
            # Only fall back when the endpoint itself is not available.
            if status not in {404, 405}:
                raise RuntimeError(primary_error)
        except Exception as exc:
            primary_error = str(exc)

        # Do not fall back to removed inbound-client endpoints. Return the real
        # Client API error so admins can diagnose CSRF/login/body validation or
        # duplicate-email issues.
        details = primary_error or "X-UI add client failed"
        raise RuntimeError(details)

    async def get_client_traffic(self, email: str) -> dict[str, Any] | None:
        if not email:
            return None
        encoded = quote(str(email), safe="")
        for method, path in (
            ("GET", f"/panel/api/clients/traffic/{encoded}"),
            ("GET", f"/panel/api/inbounds/getClientTraffics/{encoded}"),
            ("POST", f"/panel/api/inbounds/getClientTraffics/{encoded}"),
        ):
            try:
                data = await self._request(method, path)
                if self._is_success(data):
                    obj = self._obj(data)
                    if isinstance(obj, dict):
                        return obj
            except Exception:
                continue
        return None

    def _normalize_client_record(self, client: dict[str, Any] | None) -> dict[str, Any]:
        """Convert 3x-ui ClientRecord/API shapes to the Client update shape.

        New 3x-ui Client API records can contain both:
          - id: numeric database row id, e.g. 407
          - uuid: real proxy credential UUID

        The update endpoint expects the wire-client field `id` to be the real
        proxy UUID, not the numeric database row id. Storing/sending the numeric
        row id caused PostgreSQL errors in D BOT (`expected str, got int`) and
        also made renew/revoke appear successful without changing the real
        client credential.
        """
        if not isinstance(client, dict):
            return {}
        out = dict(client)

        record_id = out.get("id")
        real_uuid = out.get("uuid") or out.get("clientId") or out.get("client_id")
        if real_uuid:
            out["db_id"] = record_id
            out["id"] = str(real_uuid)
        elif record_id is not None:
            # Keep the value string-typed for DB/model safety. If the panel only
            # returned a DB id, update methods will still try to resolve the
            # full client via find_client()/inbounds before mutating.
            out["id"] = str(record_id)

        if out.get("subId") is not None:
            out["subId"] = str(out.get("subId"))
        elif out.get("sub_id") is not None:
            out["subId"] = str(out.get("sub_id"))
        if not out.get("created_at") and out.get("createdAt"):
            out["created_at"] = out.get("createdAt")
        if not out.get("updated_at") and out.get("updatedAt"):
            out["updated_at"] = out.get("updatedAt")
        out.pop("uuid", None)
        out.pop("clientId", None)
        out.pop("client_id", None)
        out.pop("sub_id", None)
        out.pop("createdAt", None)
        out.pop("updatedAt", None)
        return out

    def _safe_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _credential_from_client(self, client: dict[str, Any] | None) -> str | None:
        if not isinstance(client, dict):
            return None
        for key in ("id", "uuid", "clientId", "client_id", "password", "auth"):
            value = self._safe_text(client.get(key))
            if value:
                return value
        return None

    async def _get_client_api(self, email: str) -> dict[str, Any] | None:
        if not email:
            return None
        encoded = quote(str(email), safe="")
        try:
            data = await self._request("GET", f"/panel/api/clients/get/{encoded}")
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in {404, 400}:
                return None
            raise
        except Exception:
            return None
        if not self._is_success(data):
            return None
        obj = self._obj(data)
        client: dict[str, Any] | None = None
        inbound_ids: list[int] = []
        if isinstance(obj, dict):
            if isinstance(obj.get("client"), dict):
                client = obj.get("client")
            elif obj.get("email"):
                client = obj
            raw_ids = obj.get("inboundIds") or obj.get("inbound_ids") or []
            if isinstance(raw_ids, list):
                for item in raw_ids:
                    try:
                        iid = int(item)
                    except Exception:
                        continue
                    if iid > 0 and iid not in inbound_ids:
                        inbound_ids.append(iid)
        if not client:
            return None
        return {"client": self._normalize_client_record(client), "traffic": {}, "inbound": None, "inbound_ids": inbound_ids}

    async def _list_clients_api(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for method, path in (("GET", "/panel/api/clients/list"), ("GET", "/panel/api/clients/list/paged?page=1&pageSize=10000")):
            try:
                data = await self._request(method, path)
            except Exception:
                continue
            if not self._is_success(data):
                continue
            obj = self._obj(data)
            candidates: Any = obj
            if isinstance(obj, dict):
                for key in ("items", "list", "rows", "clients", "data"):
                    if isinstance(obj.get(key), list):
                        candidates = obj.get(key)
                        break
            if isinstance(candidates, list):
                for item in candidates:
                    if isinstance(item, dict):
                        if isinstance(item.get("client"), dict):
                            rows.append(self._normalize_client_record(item["client"]))
                        else:
                            rows.append(self._normalize_client_record(item))
                if rows:
                    return rows
        return rows

    async def find_client(self, keyword: str) -> dict[str, Any] | None:
        if not keyword:
            return None
        needle = str(keyword).strip()

        # Prefer the current 3x-ui Client API, because it reads the canonical
        # clients table and avoids stale inbound JSON that can resurrect deleted
        # clients on the next create/update operation.
        direct = await self._get_client_api(needle)
        if direct and direct.get("client"):
            direct["traffic"] = await self.get_client_traffic(direct["client"].get("email") or needle) or {}
            return direct

        for client in await self._list_clients_api():
            values = {
                str(client.get("email") or ""),
                str(client.get("id") or ""),
                str(client.get("uuid") or ""),
                str(client.get("subId") or ""),
                str(client.get("sub_id") or ""),
            }
            if needle in values:
                email = str(client.get("email") or needle)
                return {"client": client, "traffic": await self.get_client_traffic(email) or {}, "inbound": None, "inbound_ids": []}

        traffic = await self.get_client_traffic(needle)
        inbounds = await self.get_inbounds()
        for inbound in inbounds:
            settings = self._load_settings(inbound)
            clients = settings.get("clients") or []
            if not isinstance(clients, list):
                continue
            for client in clients:
                if not isinstance(client, dict):
                    continue
                normalized = self._normalize_client_record(client)
                values = {
                    str(normalized.get("email") or ""),
                    str(normalized.get("id") or ""),
                    str(normalized.get("uuid") or ""),
                    str(normalized.get("subId") or ""),
                    str(normalized.get("sub_id") or ""),
                }
                if needle in values:
                    return {"client": normalized, "traffic": traffic or {}, "inbound": inbound, "inbound_ids": [int(inbound.get("id"))] if str(inbound.get("id") or "").isdigit() else []}
        if traffic:
            return {"client": {}, "traffic": traffic, "inbound": None, "inbound_ids": []}
        return None

    def _parse_online_obj(self, obj: Any) -> list[str]:
        if obj is None:
            return []
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except Exception:
                return [obj] if obj else []
        if isinstance(obj, list):
            result: list[str] = []
            for item in obj:
                if isinstance(item, str) and item:
                    result.append(item)
                elif isinstance(item, dict):
                    val = item.get("email") or item.get("client") or item.get("name")
                    if val:
                        result.append(str(val))
            return sorted(set(result))
        if isinstance(obj, dict):
            for key in ("emails", "clients", "onlines", "list"):
                if key in obj:
                    return self._parse_online_obj(obj[key])
        return []

    async def get_online_clients(self) -> list[str]:
        for method, path in (
            ("POST", "/panel/api/clients/onlines"),
            ("POST", "/panel/api/inbounds/onlines"),
            ("GET", "/panel/api/clients/onlines"),
        ):
            try:
                data = await self._request(method, path)
                if self._is_success(data):
                    return self._parse_online_obj(self._obj(data))
            except Exception:
                continue
        return []

    def _parse_ips_obj(self, obj: Any) -> list[str]:
        if obj is None:
            return []
        if isinstance(obj, str):
            text = obj.strip()
            if not text:
                return []
            try:
                return self._parse_ips_obj(json.loads(text))
            except Exception:
                return [x.strip() for x in text.replace(",", "\n").splitlines() if x.strip()]
        if isinstance(obj, list):
            result: list[str] = []
            for item in obj:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    val = item.get("ip") or item.get("address") or item.get("clientIp")
                    if val:
                        result.append(str(val))
            return sorted(set(result))
        if isinstance(obj, dict):
            for key in ("ips", "clientIps", "list", "data"):
                if key in obj:
                    return self._parse_ips_obj(obj[key])
        return []

    async def get_client_ips(self, email: str) -> list[str]:
        encoded = quote(str(email), safe="")
        for method, path in (
            ("POST", f"/panel/api/clients/ips/{encoded}"),
            ("GET", f"/panel/api/clients/ips/{encoded}"),
            ("POST", f"/panel/api/inbounds/clientIps/{encoded}"),
            ("GET", f"/panel/api/inbounds/clientIps/{encoded}"),
        ):
            try:
                data = await self._request(method, path)
                if self._is_success(data):
                    return self._parse_ips_obj(self._obj(data))
            except Exception:
                continue
        return []

    async def _update_client(self, client: dict[str, Any], inbound: dict[str, Any] | None = None, inbound_ids: list[int] | None = None) -> dict[str, Any]:
        """Update one client using only the current 3x-ui Client API.

        When inboundIds is omitted, 3x-ui updates every inbound currently
        attached to the client. That is the safest behaviour for renew/revoke,
        because reseller/public services can be attached to several inbounds.
        """
        client = self._normalize_client_record(client)
        email = str(client.get("email") or "").strip()
        if not email:
            raise RuntimeError("X-UI client email not found")

        query = ""
        clean_ids: list[int] = []
        for item in inbound_ids or []:
            try:
                iid = int(item)
            except Exception:
                continue
            if iid > 0 and iid not in clean_ids:
                clean_ids.append(iid)
        if clean_ids:
            query = "?inboundIds=" + ",".join(str(x) for x in clean_ids)

        encoded_email = quote(email, safe="")
        try:
            data = await self._request("POST", f"/panel/api/clients/update/{encoded_email}{query}", json=client)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = (exc.response.text or "").strip().replace("\n", " ")[:300] if exc.response is not None else ""
            raise RuntimeError(f"POST {exc.request.url} -> HTTP {status}: {body}") from exc
        if self._is_success(data):
            return data
        raise RuntimeError(self._error_message(data) or "X-UI update client failed")

    async def set_client_enabled(self, email: str, enabled: bool) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])
        client["enable"] = bool(enabled)
        return await self._update_client(client)

    def _new_sub_id(self) -> str:
        return secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]

    async def rotate_client_uuid(self, email: str) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])

        # Revoke means the old subscription link must stop working. Therefore
        # rotate BOTH the connection credential and the Subscription ID.
        client["subId"] = self._new_sub_id()
        if client.get("id") or client.get("uuid") or not (client.get("password") or client.get("auth")):
            client["id"] = str(uuid.uuid4())
        if client.get("password"):
            client["password"] = secrets.token_hex(8)
        if client.get("auth"):
            client["auth"] = secrets.token_hex(8)
        data = await self._update_client(client)
        return {"result": data, "client": client}

    async def reset_client_plan(self, email: str, total_gb: int | float, expire_days: int) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])
        payload = XuiClientPayload(email=email, total_gb=total_gb, expire_days=expire_days)
        client["totalGB"] = payload.total_bytes
        client["expiryTime"] = payload.expiry_ms
        client["enable"] = True
        data = await self._update_client(client)

        # Reset current traffic after a renewal/plan reset. This route is part
        # of the current 3x-ui Client API.
        encoded_email = quote(str(email), safe="")
        try:
            await self._request("POST", f"/panel/api/clients/resetTraffic/{encoded_email}")
        except Exception:
            pass
        return data

    def _delete_candidates(self, identifiers: tuple[str | None, ...]) -> list[str]:
        candidates: list[str] = []
        for item in identifiers:
            value = str(item or "").strip()
            if not value or value in candidates:
                continue
            # A full subscription URL is not an email; extract the last token as
            # a weak lookup candidate but keep real emails/usernames first.
            if value.startswith("http://") or value.startswith("https://"):
                token = value.rstrip("/").split("/")[-1]
                if token and token not in candidates:
                    candidates.append(token)
                continue
            candidates.append(value)
        return candidates

    async def _client_exists_after_delete(self, email: str) -> bool:
        try:
            found = await self._get_client_api(email)
            if found and found.get("client"):
                return True
        except Exception:
            pass
        try:
            found = await self.find_client(email)
            return bool(found and found.get("client"))
        except Exception:
            return False

    async def delete_client(self, *identifiers: str | None) -> dict[str, Any]:
        candidates = self._delete_candidates(identifiers)
        if not candidates:
            raise RuntimeError("No client identifier supplied")

        errors: list[str] = []
        attempted: list[str] = []

        # First try direct delete by the identifiers that are usually the panel
        # email. This prevents a failed/stale find_client() from causing local
        # deletion while the real panel client remains and later resurrects.
        for candidate in candidates:
            if candidate in attempted:
                continue
            attempted.append(candidate)
            encoded = quote(candidate, safe="")
            try:
                data = await self._request("POST", f"/panel/api/clients/del/{encoded}")
                if self._is_success(data):
                    if not await self._client_exists_after_delete(candidate):
                        return data
                    errors.append(f"{candidate}: delete returned success but client still exists")
                    continue
                errors.append(f"{candidate}: {self._error_message(data)}")
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                body_text = (exc.response.text or "").strip().replace("\n", " ")[:300] if exc.response is not None else ""
                errors.append(f"POST {exc.request.url} -> HTTP {status}: {body_text}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        # If direct identifiers were UUID/subId, resolve the real email through
        # the Client API/list/inbounds and delete that email.
        for candidate in candidates:
            try:
                found = await self.find_client(candidate)
            except Exception as exc:
                errors.append(f"find {candidate}: {exc}")
                continue
            client = (found or {}).get("client") or {}
            email = str(client.get("email") or "").strip()
            if not email or email in attempted:
                continue
            attempted.append(email)
            encoded = quote(email, safe="")
            try:
                data = await self._request("POST", f"/panel/api/clients/del/{encoded}")
                if self._is_success(data) and not await self._client_exists_after_delete(email):
                    return data
                errors.append(f"{email}: delete did not remove client")
            except Exception as exc:
                errors.append(f"{email}: {exc}")

        # As a last current-API fallback, call bulkDel with all plausible emails.
        email_like = [x for x in attempted if not x.startswith("http")]
        if email_like:
            try:
                data = await self._request("POST", "/panel/api/clients/bulkDel", json={"emails": email_like, "keepTraffic": False})
                if self._is_success(data):
                    still_existing = []
                    for email in email_like:
                        if await self._client_exists_after_delete(email):
                            still_existing.append(email)
                    if not still_existing:
                        return data
                    errors.append("bulkDel left clients: " + ", ".join(still_existing))
            except Exception as exc:
                errors.append(f"bulkDel: {exc}")

        raise RuntimeError("X-UI delete client failed: " + " | ".join(x for x in errors if x))
