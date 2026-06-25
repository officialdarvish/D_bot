# UI v18 - 3x-ui UUID Type Fix

## Fixed

- Fixed `asyncpg.exceptions.DataError: expected str, got int` when saving `client_services.xui_uuid` after public/admin-free service creation.
- 3x-ui Client API may return a numeric database row/inbound id like `407` in the `id` field. The bot now rejects numeric IDs as client UUID values.
- Client UUID extraction now prefers the real connection credential fields: `uuid`, `clientUuid`, `client_uuid`, string `id`, `password`, or `auth`.
- Add/renew/revoke now keep `xui_uuid` as string-or-null only.
- Subscription links still use the real `subId` from the panel.

## Why this matters

The previous version could create the client successfully on 3x-ui, then fail during PostgreSQL commit because `xui_uuid` is a VARCHAR column but received an integer panel record id.
