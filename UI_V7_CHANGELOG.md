# D BOT Cyber Admin UI v7

## Added

- Telegram owner command `/websetup` for domain + SSL + web panel credentials setup.
- Alias commands: `/site_setup` and `/sslsetup`.
- Step-by-step bot flow:
  1. Receive domain.
  2. Save website domain.
  3. Run VPS SSL script.
  4. Ask for web admin username.
  5. Ask for web admin password.
  6. Save credentials in the shared settings table.
- New sidebar page: **Test Account**.
- New **Test Account** web card for:
  - Enabling/disabling test accounts.
  - Showing/hiding the Telegram test account button.
  - Selecting server.
  - Setting inbound IDs.
  - Setting volume and duration.
  - Resetting test account usage history.
- New admin APIs:
  - `GET /admin/api/v2/test-account`
  - `POST /admin/test-account/save`
  - `GET /admin/test-account/reset-usages`

## Updated

- README.md and README_FA.md now document the Telegram owner commands and the Test Account web page.
- `frontend_out` has been regenerated from the updated Next.js build artifacts.
