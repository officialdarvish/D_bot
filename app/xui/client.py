from __future__ import annotations

import asyncio
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from app.core.config import settings

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
        return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp() * 1000)


class XUIClient:
    """Async client for Sanaei x-ui / 3x-ui panels.

    This wrapper centralizes all Sanaei / 3x-ui communication. Client create,
    update, delete, renew, revoke, traffic and IP actions use the current
    3x-ui Client API after a CSRF/cookie login. Removed inbound-client endpoints
    are never used for client mutations.
    """

    def __init__(self, base_url: str, username: str, password: str, *, timeout: float | httpx.Timeout | None = None) -> None:
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
        verify_tls: bool | str = bool(settings.XUI_VERIFY_TLS)
        if settings.XUI_CA_BUNDLE:
            verify_tls = settings.XUI_CA_BUNDLE
        request_timeout = timeout or httpx.Timeout(connect=5.0, read=12.0, write=12.0, pool=5.0)
        self.client = httpx.AsyncClient(
            base_url=self.base_url + "/",
            timeout=request_timeout,
            follow_redirects=True,
            verify=verify_tls,
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
        for entry in (".", "login"):
            try:
                response = await self.client.get(entry)
                token = self._extract_csrf_token(response.text or "")
                if token:
                    self.client.headers["X-CSRF-Token"] = token
                    return token
                if response.status_code < 400:
                    # Some panels render an empty/minimal shell but still set the cookie.
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
                data = await self._request("GET", "/panel/api/clients/list/paged?page=1&pageSize=1")
                return self._is_success(data)
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
                    data = await self._request("GET", "/panel/api/clients/list/paged?page=1&pageSize=1")
                    if self._is_success(data):
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

    async def add_client_to_inbounds(
        self,
        inbound_ids: list[int],
        payload: XuiClientPayload,
        *,
        keep_identifiers: Iterable[str | None] | None = None,
        strict_owned_cleanup: bool = False,
        deleted_identifiers: Iterable[str | None] | None = None,
    ) -> dict[str, Any]:
        """Create one client through the official 3x-ui Client API.

        No inbound JSON rewrite, legacy endpoint, tombstone sweep or global list
        scan is performed on the purchase path. 3x-ui itself validates the
        inbound IDs and fills protocol-specific credentials.
        """
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

        new_client = self._client_template(payload, None)
        data = await self.create_client(new_client, clean_ids)
        return {"results": [data], "_client": new_client}

    async def get_client_traffic(self, email: str) -> dict[str, Any] | None:
        if not email:
            return None
        encoded = quote(str(email), safe="")
        # Use the current 3x-ui Client API only. Older inbound getClientTraffics
        # endpoints are removed on many panels and create repeated 404 requests.
        try:
            data = await self._request("GET", f"/panel/api/clients/traffic/{encoded}")
            if self._is_success(data):
                obj = self._obj(data)
                if isinstance(obj, dict):
                    return obj
        except Exception:
            return None
        return None

    async def _client_api_request(self, method: str, path: str, **kwargs: Any) -> Any:
        data = await self._request(method, path, **kwargs)
        if not self._is_success(data):
            raise RuntimeError(self._error_message(data) or f"3x-ui Client API {method} {path} failed")
        return data

    async def list_clients(self, *, page: int | None = None, page_size: int = 100, search: str | None = None) -> Any:
        if page is None:
            data = await self._client_api_request("GET", "/panel/api/clients/list")
        else:
            query = f"page={max(int(page), 1)}&pageSize={max(int(page_size), 1)}"
            if search:
                query += "&search=" + quote(str(search), safe="")
            data = await self._client_api_request("GET", f"/panel/api/clients/list/paged?{query}")
        return self._obj(data)

    async def get_client(self, email: str) -> dict[str, Any] | None:
        return await self._get_client_api(email)

    async def get_subscription_links(self, sub_id: str) -> Any:
        data = await self._client_api_request("GET", f"/panel/api/clients/subLinks/{quote(str(sub_id), safe='')}")
        return self._obj(data)

    async def get_client_links(self, email: str) -> Any:
        data = await self._client_api_request("GET", f"/panel/api/clients/links/{quote(str(email), safe='')}")
        return self._obj(data)

    def _clean_int_ids(self, values: Iterable[Any] | None) -> list[int]:
        result: list[int] = []
        for value in values or []:
            try:
                number = int(value)
            except Exception:
                continue
            if number > 0 and number not in result:
                result.append(number)
        return result

    def _clean_emails(self, values: Iterable[Any] | None) -> list[str]:
        result: list[str] = []
        for value in values or []:
            text = str(value or '').strip()
            if text and text not in result:
                result.append(text)
        return result

    async def create_client(self, client: dict[str, Any], inbound_ids: Iterable[int]) -> Any:
        ids = self._clean_int_ids(inbound_ids)
        if not ids:
            raise RuntimeError("At least one valid 3x-ui inbound ID is required")
        return await self._client_api_request(
            "POST", "/panel/api/clients/add", json={"client": client, "inboundIds": ids}
        )

    async def update_client(self, email: str, client: dict[str, Any], inbound_ids: Iterable[int] | None = None) -> Any:
        query = ""
        if inbound_ids is not None:
            ids = self._clean_int_ids(inbound_ids)
            if ids:
                query = "?inboundIds=" + ",".join(str(x) for x in ids)
        return await self._client_api_request(
            "POST", f"/panel/api/clients/update/{quote(str(email), safe='')}{query}", json=client
        )

    async def delete_client_by_email(self, email: str, *, keep_traffic: bool = False) -> Any:
        query = "?keepTraffic=1" if keep_traffic else ""
        return await self._client_api_request(
            "POST", f"/panel/api/clients/del/{quote(str(email), safe='')}{query}"
        )

    async def attach_client(self, email: str, inbound_ids: Iterable[int]) -> Any:
        ids = self._clean_int_ids(inbound_ids)
        return await self._client_api_request(
            "POST", f"/panel/api/clients/{quote(str(email), safe='')}/attach", json={"inboundIds": ids}
        )

    async def detach_client(self, email: str, inbound_ids: Iterable[int]) -> Any:
        ids = self._clean_int_ids(inbound_ids)
        return await self._client_api_request(
            "POST", f"/panel/api/clients/{quote(str(email), safe='')}/detach", json={"inboundIds": ids}
        )

    async def set_client_external_links(self, email: str, external_links: list[dict[str, Any]]) -> Any:
        return await self._client_api_request(
            "POST", f"/panel/api/clients/{quote(str(email), safe='')}/externalLinks", json={"externalLinks": external_links}
        )

    async def export_clients(self) -> Any:
        data = await self._client_api_request("GET", "/panel/api/clients/export")
        return self._obj(data)

    async def import_clients(self, exported_json: str) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/import", json={"data": exported_json})

    async def delete_orphan_clients(self) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/delOrphans")

    async def reset_all_client_traffic(self) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/resetAllTraffics")

    async def delete_depleted_clients(self) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/delDepleted")

    async def bulk_adjust_clients(self, emails: Iterable[str], *, add_days: int = 0, add_bytes: int = 0, flow: str = "") -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkAdjust", json={
            "emails": self._clean_emails(emails),
            "addDays": int(add_days or 0), "addBytes": int(add_bytes or 0), "flow": str(flow or ""),
        })

    async def bulk_set_enabled(self, emails: Iterable[str], enabled: bool) -> Any:
        path = "/panel/api/clients/bulkEnable" if enabled else "/panel/api/clients/bulkDisable"
        return await self._client_api_request("POST", path, json={"emails": self._clean_emails(emails)})

    async def bulk_delete_clients(self, emails: Iterable[str], *, keep_traffic: bool = False) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkDel", json={
            "emails": self._clean_emails(emails), "keepTraffic": bool(keep_traffic),
        })

    async def bulk_create_clients(self, payloads: list[dict[str, Any]]) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkCreate", json=payloads)

    async def bulk_attach_clients(self, emails: Iterable[str], inbound_ids: Iterable[int]) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkAttach", json={
            "emails": self._clean_emails(emails),
            "inboundIds": self._clean_int_ids(inbound_ids),
        })

    async def bulk_detach_clients(self, emails: Iterable[str], inbound_ids: Iterable[int]) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkDetach", json={
            "emails": self._clean_emails(emails),
            "inboundIds": self._clean_int_ids(inbound_ids),
        })

    async def bulk_reset_client_traffic(self, emails: Iterable[str]) -> Any:
        return await self._client_api_request("POST", "/panel/api/clients/bulkResetTraffic", json={
            "emails": self._clean_emails(emails),
        })

    async def reset_client_traffic(self, email: str) -> Any:
        return await self._client_api_request("POST", f"/panel/api/clients/resetTraffic/{quote(str(email), safe='')}")

    async def update_client_traffic(self, email: str, *, upload: int = 0, download: int = 0) -> Any:
        return await self._client_api_request(
            "POST", f"/panel/api/clients/updateTraffic/{quote(str(email), safe='')}",
            json={"upload": int(upload or 0), "download": int(download or 0)},
        )

    async def get_client_ips(self, email: str) -> Any:
        data = await self._client_api_request("POST", f"/panel/api/clients/ips/{quote(str(email), safe='')}")
        return self._obj(data)

    async def clear_client_ips(self, email: str) -> Any:
        return await self._client_api_request("POST", f"/panel/api/clients/clearIps/{quote(str(email), safe='')}")

    async def get_online_clients_by_guid(self) -> Any:
        data = await self._client_api_request("POST", "/panel/api/clients/onlinesByGuid")
        return self._obj(data)

    async def get_client_ips_by_guid(self) -> Any:
        data = await self._client_api_request("POST", "/panel/api/clients/clientIpsByGuid")
        return self._obj(data)

    async def get_active_inbounds_by_guid(self) -> Any:
        data = await self._client_api_request("POST", "/panel/api/clients/activeInbounds")
        return self._obj(data)

    async def get_clients_last_online(self) -> Any:
        data = await self._client_api_request("POST", "/panel/api/clients/lastOnline")
        return self._obj(data)

    def _looks_like_client_credential(self, value: Any) -> bool:
        """Return True only for a real 3x-ui client credential/id string.

        Newer 3x-ui Client API responses can contain a numeric database row id
        or inbound id in the field named ``id``. That value must never be stored
        as client UUID and must never be sent back as the client credential. The
        actual connection credential is usually ``uuid`` or a string ``id`` from
        the inbound client settings.
        """
        if value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        if text.isdigit():
            return False
        # UUID, trojan/shadowsocks password/auth tokens, and mixed tokens are all
        # strings. Pure numbers are database ids and are rejected above.
        return True

    def _safe_client_credential(self, *values: Any) -> str | None:
        for value in values:
            if self._looks_like_client_credential(value):
                return str(value).strip()
        return None

    def _normalize_string_list(self, value: Any) -> list[str]:
        """Normalize 3x-ui list fields that older APIs may return as strings.

        3x-ui v3.4.x validates fields such as ``allowedIPs`` as ``[]string``.
        Some panel responses return the same field as ``""`` or a JSON string
        like ``"[]"``. Sending that raw value back to ``/clients/update`` makes
        Go fail with: ``cannot unmarshal string into Go struct field``.
        """
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
                if parsed is not value:
                    return self._normalize_string_list(parsed)
            except Exception:
                pass
            return [item.strip() for item in re.split(r"[,\n\r\t ]+", text) if item.strip()]
        if isinstance(value, (list, tuple, set)):
            result: list[str] = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, str):
                    text = item.strip()
                    if text:
                        result.append(text)
                elif isinstance(item, dict):
                    text = item.get("ip") or item.get("address") or item.get("value")
                    if text:
                        result.append(str(text).strip())
                else:
                    result.append(str(item).strip())
            return [item for item in result if item]
        if isinstance(value, dict):
            for key in ("ips", "items", "list", "data", "allowedIPs"):
                if key in value:
                    return self._normalize_string_list(value[key])
        return []

    def _normalize_client_record(self, client: dict[str, Any] | None) -> dict[str, Any]:
        """Convert 3x-ui ClientRecord/API shapes to the client update shape.

        /panel/api/clients/get may return record fields like id=407 plus
        uuid=<real client uuid>. /panel/api/clients/update expects the real
        client credential in ``id``. This normalizer prevents storing/sending the
        numeric DB/inbound id as ``xui_uuid`` and makes renew/revoke update the
        actual panel client. It also converts list fields returned as strings
        into the Go API shape expected by 3x-ui v3.4.x.
        """
        if not isinstance(client, dict):
            return {}
        out = dict(client)

        credential = self._safe_client_credential(
            out.get("uuid"),
            out.get("clientUuid"),
            out.get("client_uuid"),
            out.get("id"),
            out.get("password"),
            out.get("auth"),
        )
        if credential:
            out["id"] = credential
        else:
            # Keep numeric record ids out of the update payload and DB xui_uuid.
            out.pop("id", None)

        if not out.get("subId") and out.get("sub_id"):
            out["subId"] = out.get("sub_id")
        if not out.get("subId") and out.get("subscriptionId"):
            out["subId"] = out.get("subscriptionId")
        if not out.get("subId") and out.get("subscription_id"):
            out["subId"] = out.get("subscription_id")
        if out.get("subId") is not None:
            out["subId"] = str(out.get("subId"))

        if not out.get("created_at") and out.get("createdAt"):
            out["created_at"] = out.get("createdAt")
        if not out.get("updated_at") and out.get("updatedAt"):
            out["updated_at"] = out.get("updatedAt")

        # 3x-ui v3.4.x Client API expects these fields as JSON arrays. Older
        # responses can return allowedIPs as an empty string or JSON-encoded
        # string. Never send raw strings back to updateClient.
        if "allowed_ips" in out and "allowedIPs" not in out:
            out["allowedIPs"] = out.get("allowed_ips")
        if "allowedIPs" in out:
            out["allowedIPs"] = self._normalize_string_list(out.get("allowedIPs"))

        for int_key in ("limitIp", "totalGB", "expiryTime", "tgId", "reset"):
            if int_key in out and out.get(int_key) is not None:
                try:
                    out[int_key] = int(out.get(int_key) or 0)
                except Exception:
                    out[int_key] = 0

        out.pop("uuid", None)
        out.pop("clientUuid", None)
        out.pop("client_uuid", None)
        out.pop("sub_id", None)
        out.pop("subscriptionId", None)
        out.pop("subscription_id", None)
        out.pop("createdAt", None)
        out.pop("updatedAt", None)
        out.pop("allowed_ips", None)
        return out

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
        used_traffic = 0
        external_links: list[Any] = []
        if isinstance(obj, dict):
            try:
                used_traffic = int(obj.get("usedTraffic") or obj.get("used_traffic") or 0)
            except Exception:
                used_traffic = 0
            raw_links = obj.get("externalLinks") or obj.get("external_links") or []
            if isinstance(raw_links, list):
                external_links = raw_links
        normalized = self._normalize_client_record(client)
        traffic = {"up": 0, "down": used_traffic, "total": int(normalized.get("totalGB") or 0)}
        return {
            "client": normalized,
            "traffic": traffic,
            "used_traffic": used_traffic,
            "external_links": external_links,
            "inbound": None,
            "inbound_ids": inbound_ids,
        }

    async def _list_clients_api(self) -> list[dict[str, Any]]:
        """Return the official client list for legacy-record repair only.

        Normal create/renew/delete paths never call this method. The unpaged
        official endpoint is preferred; a bounded page is only a compatibility
        fallback for panel builds where /list is unavailable.
        """
        rows: list[dict[str, Any]] = []
        for path in (
            "/panel/api/clients/list",
            "/panel/api/clients/list/paged?page=1&pageSize=500",
        ):
            try:
                data = await self._request("GET", path)
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
                    if not isinstance(item, dict):
                        continue
                    record = item.get("client") if isinstance(item.get("client"), dict) else item
                    rows.append(self._normalize_client_record(record))
                if rows:
                    return rows
        return rows
    def _client_identifier_values(self, client: dict[str, Any] | None) -> set[str]:
        values: set[str] = set()
        if not isinstance(client, dict):
            return values
        for key in (
            "email",
            "id",
            "uuid",
            "clientUuid",
            "client_uuid",
            "password",
            "auth",
            "subId",
            "sub_id",
            "subscriptionId",
            "subscription_id",
        ):
            value = str(client.get(key) or "").strip()
            if value:
                values.add(value)
        return values

    def _identifier_tokens(self, identifiers: Iterable[str | None]) -> set[str]:
        values: set[str] = set()
        for item in identifiers:
            value = str(item or "").strip()
            if not value:
                continue
            values.add(value)
            if value.startswith("http://") or value.startswith("https://"):
                token = value.rstrip("/").split("/")[-1].strip()
                if token:
                    values.add(token)
        return values

    async def find_client(self, keyword: str, *, exhaustive: bool = False) -> dict[str, Any] | None:
        """Find a client through official Client API endpoints only.

        The normal path performs one direct GET by panel email. Expensive list
        lookup is opt-in for repairing older records that only have UUID/subId.
        """
        if not keyword:
            return None
        needle = str(keyword).strip()
        if not needle or needle.startswith('deleted_'):
            return None

        direct = await self._get_client_api(needle)
        if direct and direct.get("client"):
            return direct
        if not exhaustive:
            return None

        for client in await self._list_clients_api():
            if needle not in self._client_identifier_values(client):
                continue
            email = str(client.get("email") or "").strip()
            if email:
                canonical = await self._get_client_api(email)
                if canonical and canonical.get("client"):
                    return canonical
            return {"client": client, "traffic": {}, "inbound": None, "inbound_ids": []}
        return None

    async def find_client_by_identifiers(self, identifiers: Iterable[str | None]) -> dict[str, Any] | None:
        tokens = self._identifier_tokens(identifiers)
        if not tokens:
            return None
        for token in tokens:
            direct = await self.find_client(token)
            if direct and direct.get("client"):
                return direct
        rows = await self._list_clients_api()
        for client in rows:
            if not self._client_identifier_values(client).intersection(tokens):
                continue
            email = str(client.get("email") or "").strip()
            if email:
                canonical = await self._get_client_api(email)
                if canonical and canonical.get("client"):
                    return canonical
            return {"client": client, "traffic": {}, "inbound": None, "inbound_ids": []}
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
        try:
            data = await self._client_api_request("POST", "/panel/api/clients/onlines")
            return self._parse_online_obj(self._obj(data))
        except Exception:
            return []


    async def _update_client(self, client: dict[str, Any], inbound: dict[str, Any] | None = None, inbound_ids: list[int] | None = None) -> dict[str, Any]:
        client = self._normalize_client_record(client)
        email = str(client.get("email") or "").strip()
        if not email:
            raise RuntimeError("X-UI client email not found")
        return await self.update_client(email, client, inbound_ids)

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
        inbound_ids = found.get("inbound_ids") or None
        old_sub = str(client.get("subId") or "").strip()
        old_id = str(client.get("id") or client.get("password") or client.get("auth") or "").strip()

        # Revoke means the old subscription link must stop working. Therefore
        # rotate BOTH the connection credential and the Subscription ID.
        client["subId"] = self._new_sub_id()
        if client.get("id") or client.get("uuid") or not (client.get("password") or client.get("auth")):
            client["id"] = str(uuid.uuid4())
        if client.get("password"):
            client["password"] = secrets.token_hex(8)
        if client.get("auth"):
            client["auth"] = secrets.token_hex(8)
        data = await self._update_client(client, inbound_ids=inbound_ids)

        # Read back and verify. Some panel variants return success but ignore
        # subId/credential if inboundIds or payload shape is wrong. Never send the
        # old subscription link again as a successful revoke.
        after = await self.find_client(email)
        real = dict((after or {}).get("client") or {})
        new_sub = str(real.get("subId") or client.get("subId") or "").strip()
        new_id = str(real.get("id") or real.get("password") or real.get("auth") or client.get("id") or "").strip()
        if old_sub and new_sub == old_sub:
            raise RuntimeError("X-UI revoke failed: Subscription ID did not change")
        if old_id and new_id == old_id:
            raise RuntimeError("X-UI revoke failed: client credential did not change")
        return {"result": data, "client": real or client}

    async def add_client_volume(self, email: str, add_gb: int | float) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])
        inbound_ids = found.get("inbound_ids") or None
        traffic = found.get("traffic") or {}
        add_bytes = XuiClientPayload(email=email, total_gb=add_gb, expire_days=0).total_bytes
        if add_bytes <= 0:
            raise RuntimeError("Volume must be greater than zero")
        try:
            current_total = int(client.get("totalGB") or client.get("total") or traffic.get("total") or 0)
        except Exception:
            current_total = 0
        new_total = current_total + add_bytes
        client["totalGB"] = new_total
        client["enable"] = True
        data = await self._update_client(client, inbound_ids=inbound_ids)
        after = await self.find_client(email)
        real = (after or {}).get("client") or {}
        real_tr = (after or {}).get("traffic") or {}
        try:
            real_total = int(real.get("totalGB") or real.get("total") or real_tr.get("total") or 0)
        except Exception:
            real_total = 0
        if real_total and real_total < new_total:
            raise RuntimeError("X-UI add volume failed: totalGB did not increase on panel")
        return data

    async def add_client_days(self, email: str, add_days: int) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])
        inbound_ids = found.get("inbound_ids") or None
        try:
            days = int(add_days or 0)
        except Exception:
            days = 0
        if days <= 0:
            raise RuntimeError("Days must be greater than zero")
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        try:
            current_expiry = int(client.get("expiryTime") or 0)
        except Exception:
            current_expiry = 0
        base_ms = current_expiry if current_expiry > now_ms else now_ms
        new_expiry = base_ms + days * 24 * 60 * 60 * 1000
        client["expiryTime"] = new_expiry
        client["enable"] = True
        data = await self._update_client(client, inbound_ids=inbound_ids)
        after = await self.find_client(email)
        real = (after or {}).get("client") or {}
        try:
            real_expiry = int(real.get("expiryTime") or 0)
        except Exception:
            real_expiry = 0
        if real_expiry and real_expiry < new_expiry - 60000:
            raise RuntimeError("X-UI add days failed: expiryTime did not change on panel")
        return data

    async def reset_client_plan(self, email: str, total_gb: int | float, expire_days: int) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")

        client = dict(found["client"])
        try:
            before_total = int(client.get("totalGB") or 0)
        except Exception:
            before_total = 0
        try:
            before_expiry = int(client.get("expiryTime") or 0)
        except Exception:
            before_expiry = 0

        payload = XuiClientPayload(email=email, total_gb=total_gb, expire_days=expire_days)

        # 3x-ui's resetTraffic endpoint already enables a disabled client.
        # Renewal must therefore never force enable=true itself. Reset traffic
        # first, then read the canonical client record back from the panel and
        # change only the quota and expiry fields. Re-reading is important:
        # using the pre-reset record would contain enable=false and the full
        # Client update API would disable the client again.
        await self.reset_client_traffic(email)

        def panel_enabled(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}

        refreshed_client: dict[str, Any] = {}
        for delay in (0.0, 0.25, 0.6, 1.0):
            if delay:
                await asyncio.sleep(delay)
            refreshed = await self.find_client(email)
            refreshed_client = dict((refreshed or {}).get("client") or {})
            if refreshed_client and panel_enabled(refreshed_client.get("enable")):
                break

        if not refreshed_client:
            raise RuntimeError("X-UI renew failed: client disappeared after resetTraffic")
        if not panel_enabled(refreshed_client.get("enable")):
            raise RuntimeError("X-UI renew failed: resetTraffic did not enable client on panel")

        client = refreshed_client
        client["totalGB"] = payload.total_bytes
        client["expiryTime"] = payload.expiry_ms

        # Do not pass inboundIds as an update filter. The official Client API
        # already knows every inbound attached to the email. Omitting the filter
        # is safer for multi-location / node clients and updates all attachments.
        data = await self._update_client(client)

        # Multi-node updates can take a short moment to become visible through
        # GET /clients/get/:email. Poll briefly instead of reporting a false
        # failure after one immediate read.
        real: dict[str, Any] = {}
        real_total = 0
        real_expiry = 0
        verified = False
        for delay in (0.0, 0.35, 0.75, 1.25, 2.0):
            if delay:
                await asyncio.sleep(delay)
            after = await self.find_client(email)
            real = dict((after or {}).get("client") or {})
            try:
                real_total = int(real.get("totalGB") or 0)
            except Exception:
                real_total = 0
            try:
                real_expiry = int(real.get("expiryTime") or 0)
            except Exception:
                real_expiry = 0

            total_ok = (not payload.total_bytes) or real_total == payload.total_bytes
            # 3x-ui stores milliseconds but some builds round timestamps. A
            # two-minute tolerance covers rounding/clock drift without accepting
            # an actually unchanged old expiry date.
            expiry_ok = (not payload.expiry_ms) or abs(real_expiry - payload.expiry_ms) <= 120000
            if total_ok and expiry_ok:
                verified = True
                break

        # Last-resort verification through the official list endpoint. This is
        # only used after direct GET stayed stale and never runs on normal renewals.
        if not verified:
            try:
                for row in await self._list_clients_api():
                    if str(row.get("email") or "").strip() != str(email).strip():
                        continue
                    real = dict(row)
                    real_total = int(real.get("totalGB") or 0)
                    real_expiry = int(real.get("expiryTime") or 0)
                    total_ok = (not payload.total_bytes) or real_total == payload.total_bytes
                    expiry_ok = (not payload.expiry_ms) or abs(real_expiry - payload.expiry_ms) <= 120000
                    if total_ok and expiry_ok:
                        verified = True
                    break
            except Exception:
                pass

        if not verified:
            raise RuntimeError(
                "X-UI renew verification failed: "
                f"email={email}, before_total={before_total}, target_total={payload.total_bytes}, after_total={real_total}, "
                f"before_expiry={before_expiry}, target_expiry={payload.expiry_ms}, after_expiry={real_expiry}"
            )

        return {
            "result": data,
            "client": real or client,
            "traffic_reset_warning": None,
        }

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
        """Return True only if the canonical 3x-ui Client API still has it.

        The canonical 3x-ui Client API is the only source of truth here.
        No inbound.settings scan or legacy inbound mutation is performed.
        """
        try:
            found = await self._get_client_api(email)
            return bool(found and found.get("client"))
        except Exception:
            return False

    async def delete_client(self, *identifiers: str | None) -> dict[str, Any]:
        candidates = self._delete_candidates(identifiers)
        if not candidates:
            raise RuntimeError("No client identifier supplied")

        errors: list[str] = []
        for candidate in candidates:
            try:
                data = await self.delete_client_by_email(candidate)
                return {"result": data, "email": candidate}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                errors.append(f"{candidate}: HTTP {status}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")

        # Older local rows may only retain UUID/subId. Resolve all identifiers with
        # one official list request, then delete by the canonical panel email.
        found = await self.find_client_by_identifiers(candidates)
        client = (found or {}).get("client") or {}
        email = str(client.get("email") or "").strip()
        if email and email not in candidates:
            try:
                data = await self.delete_client_by_email(email)
                return {"result": data, "email": email}
            except Exception as exc:
                errors.append(f"{email}: {exc}")

        raise RuntimeError("X-UI delete client failed: " + " | ".join(errors or ["client not found"]))
