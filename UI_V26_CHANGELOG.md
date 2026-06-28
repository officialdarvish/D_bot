# UI v26 - Admin CSRF Frontend Fix

## Fixed
- Fixed `403 Forbidden` on admin POST actions after v24 security hardening.
- Next.js admin API helper now reads `dbot_csrf_token` from cookies and sends it as `X-CSRF-Token` for all admin fetch helpers.
- Backup restore custom upload request now also sends the CSRF token.
- Prebuilt `frontend_out` bundle was patched so Docker runtime immediately serves the fixed dashboard without requiring a local Next.js rebuild.

## Affected endpoints
- `POST /admin/servers/test`
- `POST /admin/servers/add`
- `POST /admin/servers/:id/edit`
- Other form-based admin POST actions using the shared frontend helper.
