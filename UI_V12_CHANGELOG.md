# UI v12 - 3x-ui Client Add API Fix

- Fixed service creation on modern 3x-ui panels where `/panel/inbound/addClient` returns `404 Not Found`.
- Primary client creation now uses the new 3x-ui Client API endpoint: `/panel/api/clients/add`.
- Payload is sent as `{ "client": ..., "inboundIds": [...] }`, matching the current 3x-ui v3 API shape.
- Legacy endpoints are now only fallback routes and their 404 errors no longer hide the real primary endpoint error.
- `tgId` is sent as numeric `0` instead of an empty string to avoid validation/binding issues on newer 3x-ui builds.
- CSRF/cookie login support from v11 is kept.
