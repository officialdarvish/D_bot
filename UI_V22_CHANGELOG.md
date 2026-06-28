# UI v22 - Safe XUI Lifecycle Fix

This version fixes the remaining 3x-ui lifecycle issues without deleting manual/offline panel users.

## Fixed

- Public/reseller client creation no longer resurrects previously deleted bot clients.
- Before `POST /panel/api/clients/add`, the bot now performs a conservative stale cleanup on only the target inbound IDs.
- The stale cleanup removes only clients that exist in `inbound.settings.clients[]` but do not exist in the canonical 3x-ui Client API (`/panel/api/clients/list` and `/panel/api/clients/get/<email>`).
- Manual/offline panel users are not removed because they still exist in the canonical Client API.
- Delete verification now checks only the canonical Client API after delete; stale `settings.clients[]` copies are cleaned separately and are not treated as live clients.
- Revoke link now verifies that both `subId` and credential actually changed on the panel before returning a new link.
- Renew now sends `inboundIds` when available and verifies that `totalGB` and `expiryTime` changed on the panel.

## 3x-ui endpoints used

- Login: `GET /` + `POST /login` with cookie/CSRF
- Inbounds list: `GET /panel/api/inbounds/list`
- Client create: `POST /panel/api/clients/add`
- Client update/revoke/renew: `POST /panel/api/clients/update/<email>?inboundIds=...`
- Client delete: `POST /panel/api/clients/del/<email>`
- Safe settings cleanup: `POST /panel/api/inbounds/update/<inbound_id>` only for exact deleted/stale non-canonical clients
