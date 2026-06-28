# UI v24 - Security Hardening Fix

Security fixes applied:

- NOWPayments webhook now requires `NOWPAYMENTS_IPN_SECRET`, rejects missing signatures, and verifies payment details with NOWPayments before provisioning.
- Admin passwords are stored with bcrypt hashes; legacy plaintext passwords migrate after successful login.
- Removed old `FERNET_KEY[:24]` admin password fallback.
- Admin login has per-IP/per-username throttling.
- Admin session cookie is `SameSite=Strict` and all mutating AJAX calls use POST + CSRF token.
- Login `next_url` rejects protocol-relative and absolute redirects.
- Docker socket mount removed from Compose; in-panel Docker restart is disabled unless explicitly enabled.
- X-UI TLS verification is enabled by default; custom CA bundle support added.
- Backup files are signed; restore validates size, schema, trusted signature and runs in one transaction.
- Admin/browser-facing errors are generic; detailed errors are logged server-side.
- Legacy backend dependencies pinned; Dependabot and security audit workflow added.

New environment variables:

```env
ADMIN_MAX_LOGIN_ATTEMPTS=8
ADMIN_LOGIN_LOCK_SECONDS=900
XUI_VERIFY_TLS=true
XUI_CA_BUNDLE=
BACKUP_SIGNING_SECRET=
BACKUP_REQUIRE_SIGNATURE=true
BACKUP_MAX_UPLOAD_BYTES=5242880
DBOT_ALLOW_DOCKER_RESTART=false
```
