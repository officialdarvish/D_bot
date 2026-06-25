# UI v20 - Owned Inbound Clean Create Fix

Fixes the issue where deleted bot-created users reappeared after creating a new user.

## Changes
- Before creating a new 3x-ui client, the bot now treats sale inbounds as bot-owned inbounds.
- The target inbound `settings.clients[]` list is rewritten to keep only currently active local `client_services` records.
- Deleted local services are excluded, so old deleted clients cannot be written back by `/panel/api/clients/add`.
- The previous orphan cleanup based only on `/panel/api/clients/list` is no longer trusted for bot-owned sale inbounds, because some 3x-ui builds keep deleted clients in the Client API list until the inbound is rewritten.
- Existing active bot services remain untouched.
