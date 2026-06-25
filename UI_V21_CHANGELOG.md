# UI v21 - Safe Client Delete Fix

- Reverted dangerous v20 owned-inbound pruning behavior.
- Bot no longer deletes unknown/manual/offline panel users during create.
- Deleted bot services are kept as inactive tombstones so only their exact identifiers can be purged safely from 3x-ui inbound settings.
- Public and reseller service lists now hide inactive/tombstone services.
- Username availability ignores inactive tombstones.
