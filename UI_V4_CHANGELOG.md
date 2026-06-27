# D BOT Cyber Admin UI v4

## Fixes
- Fixed dashboard crash: `name 'percent_change' is not defined`.
- Removed the dashboard welcome subtitle text.
- Kept desktop hamburger hidden; mobile hamburger remains available for opening/closing the sidebar.
- Updated Backup Destination dynamic fields:
  - Channel shows only Channel link.
  - Group shows only Group Link.
  - Bot shows only Bot token for sending backup.
  - Target chat ID and Backup bot username are no longer shown in the UI.
- Changed restore badge text from Website only to Website and Bot.
- Service Types cards no longer show the internal database key; only the service value/name is displayed.
- Improved sales PDF layout with landscape table, header cards, alternating rows, and clearer columns.
- Preserved Persian/Unicode text support inside the PDF report.

## Backend
- Added safe `percent_change()` helper used by both legacy and v2 dashboard APIs.
- Backup channel/group links are normalized from `https://t.me/...` to Telegram username format where possible.
- Bot backup destination can use the configured owner/admin ID as the default send target.
