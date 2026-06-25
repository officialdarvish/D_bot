# UI v19 - 3x-ui Stale Client Purge Fix

## Fixed

- Fixed a 3x-ui state bug where a client deleted from the bot could reappear when creating the next client.
- Added pre-create cleanup: before `/panel/api/clients/add`, the bot now purges orphan clients from target `inbound.settings.clients[]` if those clients no longer exist in `/panel/api/clients/list` or `/panel/api/clients/get/<email>`.
- Added post-delete cleanup: after `/panel/api/clients/del/<email>` or `bulkDel`, the bot removes any stale copy of the deleted client from inbound settings by email, UUID/password/auth, `subId`, or subscription token.
- The bot continues to use the unified current 3x-ui API for client mutations and does not call removed `panel/inbound/addClient` or `panel/inbound/updateClient` endpoints.

## Why

Some 3x-ui builds can leave a deleted client inside the inbound JSON settings. When a new client is added later, 3x-ui appends the new client to that stale JSON and the deleted user appears again. v19 cleans that stale JSON before adding new users and immediately after deleting users.
