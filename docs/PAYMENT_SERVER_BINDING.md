# Payment server binding update

- Removed the separate post-purchase success/home message. Subscription details and their controls still deliver normally; owner payment notifications remain enabled.
- Add/Edit Server offers Public sales and Reseller sales only. Newly submitted server data cannot create the former combined scope. Existing legacy records remain readable.
- Add/Edit Payment now filters server choices by public/reseller usage and includes PasarGuard. A reseller payment can bind to a specific reseller server, or remain a global fallback when no server is selected.
- Panel sales, quota purchases and native Mini App funding prefer that server's own active card, followed by the global reseller fallback. A card assigned only to another server is never used as a fallback.
- PasarGuard panel-sales enablement validates payment availability through the same resolver.

Validation: 392 tests passed; the same five pre-existing failures remain. Production frontend and TypeScript checks passed. Provider and Telegram calls were mocked; no live payment or production deployment was performed.
