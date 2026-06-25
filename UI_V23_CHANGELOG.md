# UI v23 - Safe Tombstone Lifecycle + Revoke Detail Fix

## Fixed

- Removed generic orphan-client cleanup from service creation. The bot no longer deletes unknown, manual, or offline 3x-ui panel users.
- Service creation now cleans only explicit tombstone identifiers stored in the bot database for deleted/inactive bot-created services.
- Deleted bot clients are purged through the current 3x-ui Client API and from `inbound.settings.clients[]` before and after new client creation, preventing deleted bot users from being resurrected on the next add.
- Public username allocation now reserves inactive/deleted local service names too, preventing username reuse against tombstone records.
- Deleting a client retries safe tombstone cleanup after canonical Client API deletion.
- After “revoke / regenerate link” in My Configs, the bot sends the new config card and then sends a second message opening that same service detail page.

## Safety

- No cleanup is based on online/offline status.
- No cleanup is based on missing users from a partial `/panel/api/clients/list` response.
- Manual panel users are never touched unless their exact identifiers are stored as deleted bot-service tombstones.
