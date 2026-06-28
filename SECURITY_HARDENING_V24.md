# D BOT Security Hardening v24

This release addresses the audit findings reported for payment webhooks, admin authentication, CSRF, Docker socket exposure, TLS verification, backup/restore integrity, login throttling, open redirects, raw error leakage, and supply-chain checks.

## Fixed items

1. **NOWPayments IPN security**
   - IPN secret is now mandatory when the webhook is used.
   - Missing/invalid signatures are rejected.
   - Webhook provisioning verifies `payment_id`, `order_id`, status, amount, and currency by querying NOWPayments before marking an order paid.

2. **Admin password storage**
   - New admin passwords are stored as bcrypt hashes.
   - Existing plaintext DB passwords are migrated to bcrypt after a successful login.
   - The old `FERNET_KEY[:24]` password fallback was removed.

3. **Admin CSRF protection**
   - Admin session cookie is now `SameSite=Strict`.
   - Mutating AJAX actions use POST plus `X-CSRF-Token`.
   - Same-origin checks block cross-site admin requests.
   - Destructive routes also accept POST so the UI no longer needs state-changing GET requests.

4. **Docker socket risk reduced**
   - `/var/run/docker.sock` is no longer mounted in compose by default.
   - In-panel Docker restart is disabled unless `DBOT_ALLOW_DOCKER_RESTART=true` is explicitly set.

5. **X-UI TLS verification**
   - X-UI HTTP client verifies TLS by default.
   - Self-signed panels can use `XUI_CA_BUNDLE=/path/to/ca.pem` instead of disabling verification globally.

6. **Backup/restore integrity**
   - Backups are signed with HMAC using `BACKUP_SIGNING_SECRET` or the existing application secret.
   - Restore validates structure, size, known sections, and signature.
   - Restore runs in a single transaction; failed restores do not leave a half-deleted database.

7. **Login brute-force protection**
   - Admin login now has in-memory per-IP/per-user throttling.
   - Failed login attempts are logged.

8. **Open redirect protection**
   - Login `next_url` now rejects `//external.example`, absolute URLs, and unsafe login loops.

9. **Safer error messages**
   - Admin JSON errors return a generic message with a request ID.
   - Detailed exceptions are logged server-side only.
   - SSL/restore command output is no longer returned to browser clients.

10. **Supply-chain hardening**
   - Legacy backend requirements are pinned.
   - Dependabot and CI audit workflow were added for pip, npm, and Docker updates.

## New environment variables

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

## Important deployment note

If your 3x-ui panel uses a self-signed certificate, do **not** set `verify=False` in code. Export the panel CA certificate and set:

```env
XUI_CA_BUNDLE=/path/to/your/ca.pem
```

If the panel uses a public valid certificate, no change is required.
