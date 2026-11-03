# PAYG update validation

- Frontend production build: passed (Next static export).
- 16 financial/owner-access tests: passed. SQLite transaction tests and mocked remote providers cover integer settlement, fractional carry, counter resets, rollback, repeated operations, separate wallets, 30-minute persistence, tariff changes, switching modes, pause/retry/recovery, receipt approval, owner authentication and admin form persistence.
- Existing suite plus new tests: 325 passed and five pre-existing failures. The five baseline failures are source-text assertions in dashboard layout (two), reseller duplicate-name sequence, revenue export and Sanaei performance feature checks. No new failure remains.
- Browser smoke: customer and reseller responsive widths, direct support, configured-only/empty catalog, action handoffs, financial-mode display, wallet balance, tariffs, admin edit fields, server financial options, owner-entry navigation, financial ledger and existing Mini App settings.
- No production database or live provider was modified. PostgreSQL migration and real provider/payment behavior require deployment verification with a test reseller.

Run from the project root with development test dependencies (pytest, pytest-asyncio, aiosqlite):

    PYTHONPATH=. pytest tests --asyncio-mode=auto -q

Set BOT_TOKEN and DATABASE_URL for the local test environment.

## Follow-up Mini App fixes

- Native Telegram menu text follows the current bot display name.
- Happ links use a same-origin HTTPS browser launch page instead of navigating the Mini App to a custom URL scheme. Plain subscription and crypt5 links are supported; invalid schemes are rejected. URL fragments are cleared after reading; hash changes reset the prior link. Manual copy remains available.
- Client username precedes the purchased plan title in service cards and details.
- Categories use a full-width row with a large left icon, readable wrapping and a separated footer; checked at 320, 390, 520 and 820 pixels.
- 31 focused Mini App and financial tests passed; frontend production build passed. Browser checks cover HTTPS handoff without leaving the Mini App, plain/encrypted/invalid launch links and responsive category layout. Native Happ launch on a physical phone has not been tested.

## Happ delivery follow-up

The retail plan setting no longer depends on finding a linked paid Order. Normalization handles legacy true/yes/1 values, and omitted fields in old edit forms preserve the saved option. Telegram delivery, Mini App copy/QR and My Configs use a shared resolver that requests a current native crypt5 URI from the Sanaei API. Failed generation never substitutes an ordinary URL. Plain Happ add links retain the embedded HTTP URL without percent-encoding the whole address.

46 focused tests passed, including an imported service with no linked order, exact matching of the caption/QR/copy payload, failed generation with an existing cache and legacy-form persistence. Three produced QR cards (121, 414 and 1348 characters) were independently decoded with ZXing and matched the input exactly. QR cells now use integer scaling, a four-cell quiet zone and no central logo obstruction; oversized payloads fall back to complete text delivery. Tests use mocked provider generation, not a live Sanaei server or physical Happ device.

## Native Mini App checkout

- 10 dedicated checkout tests passed: quote/currency/discount totals, repeated wallet submission and one debit/provision, insufficient funds and tampered totals, receipt ownership/validation/repeat upload, discount cancellation, card approval, provider failure, interrupted mutation review, cross-install password backup and paid delivery with a hidden service tab.
- Full suite: 338 passed, the same five baseline source-text failures remain.
- Frontend production export and TypeScript checks passed.
- Browser flow passed: card purchase, image upload, pending receipt, approval result, native service delivery/copy/Happ/QR, wallet purchase, reopening order history after reload, and responsive checkout widths 320/390/520/820. Existing customer/reseller/admin Mini App checks also passed without JavaScript errors.
- Receipt approval/provisioning tests use a local database and mocked Telegram/provider calls. No live bank payment or production provider was changed.

## Case-insensitive client names and long Telegram captions

24 new runtime regressions passed, including panel-only mixed-case names, local public/reseller lookups, pagination beyond 500 with clamped page sizes, legacy inbound names, failed enumeration, repeated pages, the production duplicate error, refusal to retry ambiguous/mixed errors, complete long Happ delivery, QR overflow, temporary-file cleanup and a single revoke operation. Full suite: 362 passed, the same five baseline source-text failures remain. Telegram and Sanaei calls were mocked; no live production service was changed. Frontend files and compiled export are unchanged in this update.
