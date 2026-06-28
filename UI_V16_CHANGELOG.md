# UI v16 - Unified 3x-ui Client API Fix

## Fixed

- Unified all Sanaei / 3x-ui client mutation actions through `app/xui/client.py`.
- Removed all old client mutation endpoints from source usage:
  - service creation now uses the current Client API.
  - revoke / new link now uses the current Client API.
  - reseller renewal now uses the current Client API.
  - delete service now uses the current Client API.
- Reseller service delete no longer deletes the local bot record if deletion from the panel fails. It only continues local cleanup when the client was already missing from the panel.
- Added current-API delete fallback using bulk deletion.
- Kept safe error reporting: users see only the generic support message, while owners/admins receive the complete technical error.

## 3x-ui Panel Values

For a hidden-path panel such as:

```text
https://panel.mgiftshop.ir/U76peSug8RbmlymBHQ/
```

Use:

```text
Panel URL / Origin: https://panel.mgiftshop.ir
Panel Web Path: /U76peSug8RbmlymBHQ/
```
