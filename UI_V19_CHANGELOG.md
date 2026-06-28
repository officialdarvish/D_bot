# D BOT UI v19 - 3x-ui Auto Login / Add Server Form Split

## Changes

- Add Server form is now profile-aware:
  - Selecting **3x-ui Sanaei** only shows 3x-ui fields.
  - Selecting **MikroTik** only shows MikroTik fields.
  - Combined labels such as `3x-ui URL / MikroTik API Base` were removed.
- 3x-ui Add Server can now work with only panel login information:
  - Panel URL
  - Username
  - Password/API token
- `Test & Auto Fill` logs in to the 3x-ui panel, lists inbounds, and auto-fills:
  - Server key/name
  - Display name
  - Normalized panel origin
  - Normalized panel web path
  - Subscription URL base fallback
- Backend Add Server no longer requires manually entering `Server name` for 3x-ui. If empty, it derives the name from inbound remark or panel host/IP.
- When adding 3x-ui, inbound IDs are synchronized immediately and saved into server metadata/plans as before.
- Legacy server add fallback was made safer for blank names.

## Validation

- `python -m compileall -q app`
- `npm run build`
