# Debug Report - UI v5

## Fixed Requests

1. VPS installation now prints the generated website username and password clearly.
2. Added `dbot credentials` command for showing the generated website login details from `.env`.
3. Website credential changes from the admin panel now force logout and require login with the new credentials.
4. Added a login-page notice after credential update.
5. Rebuilt README.md and README_FA.md with clean, separated, full documentation.
6. Added official Telegram/GitHub links and NOWPayments donation block.
7. Added project permission/copying notice to README files.
8. Updated LICENSE to custom permission-required source license.

## Checks

- `npm run build` completed successfully inside `frontend/`.
- `python -m compileall -q app` completed successfully.

## Notes

- The `dbot credentials` command reads initial credentials from `.env`. If the owner later changes website credentials from the website, the new credentials are stored in the database and the website logs out automatically.
- Owners should save the new website credentials immediately after changing them.

## UI v14 validation

- Python compile passed with `python -m compileall -q app`.
- Frontend static export passed with `npm --prefix frontend run build`.
- `frontend_out` was regenerated from `frontend/out`.

## UI v15 Safe Error Reporting
- Added `app/bot/error_reporting.py`.
- Added global `UserSafeErrorMiddleware` in `app/main.py`.
- Replaced user-visible technical exception output in public bot flows with a generic support message.
- Full error reports are sent to owner/admin IDs only.
