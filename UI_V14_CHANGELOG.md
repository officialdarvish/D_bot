# UI v14 - Test Account Single Reset + 3x-ui Client Update/Delete Fix

## Fixed

- Fixed 3x-ui revoke/new-link flow by replacing legacy `/panel/inbound/updateClient/:uuid` calls with the current 3x-ui client route:
  - `POST /panel/api/clients/update/:email?inboundIds=...`
- Fixed service deletion from the Telegram bot by deleting clients through the current 3x-ui client route:
  - `POST /panel/api/clients/del/:email`
- Removed legacy inbound update/delete fallbacks that caused user-facing 404 errors on modern 3x-ui panels.

## Added

- Added a Test Account usage removal tool in the website panel.
- Admins can search by `User Telegram ID`, select a row, and remove that single user from the test-account usage history.
- The full reset-all button remains available.

## Notes

- The panel path for hidden 3x-ui deployments remains supported, for example `/U76peSug8RbmlymBHQ/`.
- Build output in `frontend_out` was regenerated.
