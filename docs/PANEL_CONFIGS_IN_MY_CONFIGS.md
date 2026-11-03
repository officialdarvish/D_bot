# Panel configs in My Configs

PasarGuard server creation in Telegram now requires a public subscription base
before requesting admin credentials. The website server form also exposes and
saves this field for PasarGuard, including edits. Absolute panel-generated user
URLs remain unchanged. Relative URLs are resolved using the configured public
subscription base according to standard URL resolution (a leading slash uses
the configured origin). Credentials, queries and fragments are rejected in a
base URL. Existing servers can be edited to populate the new field.

The Mini App My Configs list combines ordinary purchases, config-reseller
accounts and completed native purchased-panel configurations. Each card and
detail page shows its source: public purchase or reseller. Panel-created entries
use their existing durable operation records and a separate ID namespace; they
are not copied into ClientService or enrolled again in retail sync/accounting.
This also makes successful operations from previous releases visible without a
schema migration. Failed/pending operations are excluded.

Purchased-panel usage/status is read from the established strict admin-owned
remote listing, bounded by a read timeout. Deleted/transferred users are omitted
when the listing succeeds; on an outage the saved creation snapshot is marked
stale. The normal refresh reloads this list. Copy, Happ and QR use authenticated
panel-specific endpoints which verify the operation owner, purchased panel,
remote ID and remote admin. Panel-specific controls now provide native deletion, HWID reset, link rotation,
quota/day extension and renewal for these independently billed users; retail
renewal/conversion endpoints are not used. See PANEL_CONFIGURATION_ACTIONS.md.

Validation: test_pasarguard_subscription_form.py and the purchased-panel tests
exercise the required bot step, URL validation, relative URLs, exact absolute
URLs, config listing, source labels, duplicate prevention, cross-user denial,
remote ownership and QR delivery. Browser checks cover three configuration
sources and mobile widths 320–520 px. All provider calls in tests are simulated.
