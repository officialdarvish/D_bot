from __future__ import annotations

import asyncio
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
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
        verify_tls: bool | str = bool(settings.XUI_VERIFY_TLS)
        if settings.XUI_CA_BUNDLE:
            verify_tls = settings.XUI_CA_BUNDLE
        self.client = httpx.AsyncClient(
            base_url=self.base_url + "/",
            timeout=timeout,
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

    async def add_client_to_inbounds(
        self,
        inbound_ids: list[int],
        payload: XuiClientPayload,
        *,
        keep_identifiers: Iterable[str | None] | None = None,
        strict_owned_cleanup: bool = False,
        deleted_identifiers: Iterable[str | None] | None = None,
    ) -> dict[str, Any]:
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

        # Safe cleanup before create:
        # Only clients that the bot explicitly marked as deleted/inactive are
        # cleaned. Never prune unknown/manual/offline panel users. The cleanup is
        # performed against both the current Client API and inbound.settings[],
        # because 3x-ui can keep a stale settings copy that gets resurrected on
        # the next /panel/api/clients/add call.
        deleted_targets = self._identifier_tokens(deleted_identifiers or [])
        if deleted_targets:
            await self.purge_deleted_clients_everywhere(deleted_targets, inbound_ids=clean_ids, attempts=2)

        # Do not run generic orphan cleanup here. A panel variant can return a
        # partial/empty canonical client list for offline/manual users; removing
        # every "orphan" would be dangerous. Tombstones from the bot DB are the
        # only source of truth for safe cleanup.

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
                # A successful add can re-save an old inbound.settings[] snapshot
                # in some 3x-ui builds. Run one more explicit tombstone cleanup
                # after the add, but never include identifiers of the newly
                # created client.
                if deleted_targets:
                    protected = self._identifier_tokens([
                        payload.email,
                        new_client.get("email"),
                        new_client.get("id"),
                        new_client.get("password"),
                        new_client.get("auth"),
                        new_client.get("subId"),
                    ])
                    post_targets = [x for x in deleted_targets if x not in protected]
                    if post_targets:
                        await self.purge_deleted_clients_everywhere(post_targets, inbound_ids=clean_ids, attempts=2)
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

    def _normalize_client_record(self, client: dict[str, Any] | None) -> dict[str, Any]:
        """Convert 3x-ui ClientRecord/API shapes to the client update shape.

        /panel/api/clients/get may return record fields like id=407 plus
        uuid=<real client uuid>. /panel/api/clients/update expects the real
        client credential in ``id``. This normalizer prevents storing/sending the
        numeric DB/inbound id as ``xui_uuid`` and makes renew/revoke update the
        actual panel client.
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
    async def _list_client_emails_api(self) -> set[str]:
        emails: set[str] = set()
        for row in await self._list_clients_api():
            email = str(row.get("email") or "").strip()
            if email:
                emails.add(email)
        return emails

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

    def _prepare_inbound_update_payload(self, inbound: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(inbound or {})
        payload["settings"] = json.dumps(settings, ensure_ascii=False)

        # These fields are display/derived values from list/detail APIs and are
        # not part of the inbound edit form. Sending them can break validation on
        # some 3x-ui versions.
        for key in (
            "clientStats",
            "client_stats",
            "clients",
            "traffic",
            "tags",
            "obj",
            "data",
            "result",
            "results",
        ):
            payload.pop(key, None)

        # 3x-ui model fields for these values are JSON strings. The list API may
        # return them as decoded objects, so encode them before /inbounds/update.
        for key in ("streamSettings", "sniffing", "allocate"):
            if isinstance(payload.get(key), (dict, list)):
                payload[key] = json.dumps(payload.get(key), ensure_ascii=False)
        return payload

    async def _update_inbound_settings(self, inbound: dict[str, Any], settings: dict[str, Any]) -> Any:
        try:
            inbound_id = int(inbound.get("id"))
        except Exception as exc:
            raise RuntimeError("X-UI inbound id not found for settings cleanup") from exc
        payload = self._prepare_inbound_update_payload(inbound, settings)
        data = await self._request("POST", f"/panel/api/inbounds/update/{inbound_id}", json=payload)
        if not self._is_success(data):
            raise RuntimeError(self._error_message(data) or f"X-UI inbound {inbound_id} cleanup failed")
        return data

    async def purge_client_from_inbounds(self, *identifiers: str | None, inbound_ids: list[int] | None = None) -> int:
        """Remove one deleted client from inbound.settings JSON.

        Some 3x-ui builds delete the canonical client row but can leave the
        client object inside inbound.settings. The next add operation appends to
        that old settings array and the deleted user appears again. This cleanup
        removes the stale object by email/UUID/password/auth/subId/token.
        """
        targets = self._identifier_tokens(identifiers)
        if not targets:
            return 0

        allowed_ids: set[int] | None = None
        if inbound_ids is not None:
            allowed_ids = set()
            for item in inbound_ids:
                try:
                    allowed_ids.add(int(item))
                except Exception:
                    continue

        changed = 0
        for inbound in await self.get_inbounds():
            try:
                inbound_id = int(inbound.get("id"))
            except Exception:
                continue
            if allowed_ids is not None and inbound_id not in allowed_ids:
                continue
            settings = self._load_settings(inbound)
            clients = settings.get("clients")
            if not isinstance(clients, list) or not clients:
                continue
            kept: list[Any] = []
            removed = False
            for client in clients:
                if isinstance(client, dict) and self._client_identifier_values(client).intersection(targets):
                    removed = True
                    continue
                kept.append(client)
            if removed:
                settings["clients"] = kept
                await self._update_inbound_settings(inbound, settings)
                changed += 1
        return changed

    async def purge_deleted_clients_everywhere(
        self,
        identifiers: Iterable[str | None],
        *,
        inbound_ids: list[int] | None = None,
        attempts: int = 2,
    ) -> dict[str, int]:
        """Remove explicitly deleted bot clients without touching manual users.

        This method is intentionally driven only by tombstone identifiers stored
        in the bot database. It never scans for offline/unknown users. It tries
        the current 3x-ui Client API and then removes matching objects from
        inbound.settings[] so a later create cannot resurrect them.
        """
        candidates = self._delete_candidates(tuple(identifiers))
        if not candidates:
            return {"deleted": 0, "purged": 0}

        deleted_count = 0
        purged_count = 0
        attempts = max(1, int(attempts or 1))

        for attempt in range(attempts):
            expanded = list(candidates)

            # Resolve UUID/subId/token tombstones to real panel emails when the
            # panel can still find them. If it only exists as a stale settings
            # object, find_client() still gives us its email for targeted purge.
            for candidate in list(candidates):
                try:
                    found = await self.find_client(candidate)
                except Exception:
                    found = None
                client = (found or {}).get("client") or {}
                email = str(client.get("email") or "").strip()
                if email and email not in expanded:
                    expanded.append(email)

            # Delete canonical Client API rows for the explicit tombstones. 404s
            # are fine here: the stale settings copy will be removed below.
            for item in expanded:
                encoded = quote(str(item), safe="")
                try:
                    data = await self._request("POST", f"/panel/api/clients/del/{encoded}")
                    if self._is_success(data):
                        deleted_count += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response is not None and exc.response.status_code in {400, 404} :
                        pass
                    else:
                        pass
                except Exception:
                    pass

            if expanded:
                try:
                    data = await self._request("POST", "/panel/api/clients/bulkDel", json={"emails": expanded, "keepTraffic": False})
                    if self._is_success(data):
                        deleted_count += 1
                except Exception:
                    pass

            purged_count += await self.purge_client_from_inbounds(*expanded, inbound_ids=inbound_ids)
            if attempt < attempts - 1:
                await asyncio.sleep(0.35)

        return {"deleted": deleted_count, "purged": purged_count}

    async def prune_inbounds_to_identifiers(self, inbound_ids: list[int] | None, keep_identifiers: Iterable[str | None]) -> int:
        """Deprecated safety guard.

        This method used to remove every inbound client not present in the bot
        active-service list. That can delete valid manual/offline panel users.
        It is intentionally disabled; use purge_client_from_inbounds() with
        explicit deleted identifiers instead.
        """
        return 0

    async def purge_orphan_clients_from_inbounds(
        self,
        inbound_ids: list[int] | None = None,
        protected_identifiers: Iterable[str | None] | None = None,
    ) -> int:
        """Purge stale settings-only clients without touching valid panel users.

        A client is removed only when all of these are true:
        1) it exists in inbound.settings.clients[];
        2) it has an email;
        3) it is not in the canonical /panel/api/clients/list result;
        4) /panel/api/clients/get/<email> also says it does not exist;
        5) it is not one of the protected identifiers, such as the new user that
           is about to be created.

        This is safe for manual/offline users because offline users still exist
        in the canonical Client API. If the canonical list is unavailable/empty,
        the method does nothing.
        """
        canonical_emails = await self._list_client_emails_api()
        if not canonical_emails:
            return 0
        protected = self._identifier_tokens(protected_identifiers or [])

        allowed_ids: set[int] | None = None
        if inbound_ids is not None:
            allowed_ids = set()
            for item in inbound_ids:
                try:
                    allowed_ids.add(int(item))
                except Exception:
                    continue

        changed = 0
        for inbound in await self.get_inbounds():
            try:
                inbound_id = int(inbound.get("id"))
            except Exception:
                continue
            if allowed_ids is not None and inbound_id not in allowed_ids:
                continue
            settings = self._load_settings(inbound)
            clients = settings.get("clients")
            if not isinstance(clients, list) or not clients:
                continue

            kept: list[Any] = []
            removed = False
            for client in clients:
                if not isinstance(client, dict):
                    kept.append(client)
                    continue
                email = str(client.get("email") or "").strip()
                if not email or email in canonical_emails:
                    kept.append(client)
                    continue
                if self._client_identifier_values(client).intersection(protected):
                    kept.append(client)
                    continue
                # Verify the client is really absent; this protects valid users
                # if list pagination or a panel variant returns a partial list.
                exists = await self._get_client_api(email)
                if exists and exists.get("client"):
                    kept.append(client)
                    continue
                removed = True

            if removed:
                settings["clients"] = kept
                await self._update_inbound_settings(inbound, settings)
                changed += 1
        return changed


    async def find_client(self, keyword: str) -> dict[str, Any] | None:
        if not keyword:
            return None
        needle = str(keyword).strip()
        if needle.startswith('deleted_'):
            return None

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

    async def reset_client_plan(self, email: str, total_gb: int | float, expire_days: int) -> dict[str, Any]:
        found = await self.find_client(email)
        if not found or not found.get("client"):
            raise RuntimeError("X-UI client not found")
        client = dict(found["client"])
        inbound_ids = found.get("inbound_ids") or None
        payload = XuiClientPayload(email=email, total_gb=total_gb, expire_days=expire_days)
        client["totalGB"] = payload.total_bytes
        client["expiryTime"] = payload.expiry_ms
        client["enable"] = True
        data = await self._update_client(client, inbound_ids=inbound_ids)

        # Reset current traffic after a renewal/plan reset. This route is part
        # of the current 3x-ui Client API.
        encoded_email = quote(str(email), safe="")
        try:
            await self._request("POST", f"/panel/api/clients/resetTraffic/{encoded_email}")
        except Exception:
            pass

        # Verify that the panel actually accepted the renewal.
        after = await self.find_client(email)
        real = (after or {}).get("client") or {}
        try:
            real_total = int(real.get("totalGB") or 0)
        except Exception:
            real_total = 0
        try:
            real_expiry = int(real.get("expiryTime") or 0)
        except Exception:
            real_expiry = 0
        if payload.total_bytes and real_total != payload.total_bytes:
            raise RuntimeError("X-UI renew failed: totalGB did not change on panel")
        if payload.expiry_ms and real_expiry < payload.expiry_ms - 60000:
            raise RuntimeError("X-UI renew failed: expiryTime did not change on panel")
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
        """Return True only if the canonical 3x-ui Client API still has it.

        Do not scan inbound.settings here. Stale copies inside settings.clients[]
        are exactly what purge_client_from_inbounds() removes after a delete.
        Treating those stale copies as a live client makes delete look failed and
        can leave local/panel state inconsistent.
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
                    # Also remove any stale copy from inbound.settings so a later
                    # /panel/api/clients/add cannot resurrect this deleted client.
                    await self.purge_deleted_clients_everywhere(candidates, attempts=2)
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
                if self._is_success(data):
                    await self.purge_deleted_clients_everywhere([email, *candidates], attempts=2)
                    if not await self._client_exists_after_delete(email):
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
                    await self.purge_deleted_clients_everywhere([*email_like, *candidates], attempts=2)
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
