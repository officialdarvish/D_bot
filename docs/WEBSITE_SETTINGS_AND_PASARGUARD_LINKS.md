# Website access and PasarGuard subscriptions

The owner-only Telegram website settings menu reads the same active credential
snapshot and public login URL as the website Credentials Center. It displays the
configured web path, username, recoverable password, session timeout and SSL
status. Its login button includes the configured prefix and port. When only a
password hash remains, the menu asks the owner to set a new password instead of
showing the hash. An unconfigured SERVER_IP placeholder is never a clickable URL.
The /websetup completion message uses this same login URL.

PasarGuard subscription URLs are opaque values returned by the panel. Creation
(including template creation), renewal and purchased-panel Mini App creation read
the final user record and prefer its subscription_url. Partial update responses
cannot erase a previous panel-issued URL. If the final read fails, an existing
panel-issued response remains usable; no link is synthesized from the dashboard,
custom X-UI base, numeric ID or username. Existing service downloads refresh their
stored link through the same provider read. Telegram escapes HTML entities only
for presentation; the copied value and QR payload retain the original URL.

Validation: tests/test_website_settings_pasarguard_links.py checks owner access,
active credentials and prefixed login buttons, unavailable secrets, final panel
URLs with query strings, old service repair and partial-response/read-outage
handling. Provider and Telegram calls are simulated; production configuration
and real upstream panel availability require deployment verification.
