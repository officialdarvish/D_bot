# UI v17 — 3x-ui Client State Hard Fix

## Fixed

- Unified renew, revoke/regenerate link, delete and create around the current 3x-ui Client API.
- Removed stale legacy mutation usage for `panel/inbound/updateClient`, `panel/inbound/addClient`, and `panel/inbound/delClient` from runtime XUI flows.
- Revoke/regenerate now rotates both the connection credential and `subId`, so the new subscription link is really new.
- Renew now updates the canonical client record through `/panel/api/clients/update/:email` without limiting updates to only one inbound.
- Delete now tries direct `/panel/api/clients/del/:email`, verifies the client is gone, and only then allows local bot cleanup.
- Added canonical client lookup using `/panel/api/clients/get/:email` and `/panel/api/clients/list` before falling back to inbound settings.
- Prevents previously deleted panel clients from reappearing when a new client is created later.

## Notes

Correct 3x-ui path example:

```text
Panel URL / Origin: https://panel.mgiftshop.ir
Panel Web Path: /U76peSug8RbmlymBHQ/
```
