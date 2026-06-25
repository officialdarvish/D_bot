# D BOT Cyber Admin UI v3

## Dashboard
- Revenue Overview chart Y-axis now displays Toman values divided by 1,000 without the `K` suffix.
- Recent Orders shows the payment source: Wallet, Card to Card, Crypto, or Reseller Payment.
- PDF export now uses Unicode/Persian-safe rendering when ReportLab and DejaVu fonts are available.
- PDF export includes payment source per order and keeps orders sorted from oldest to newest.

## Header / Mobile
- Desktop hamburger button is hidden.
- Mobile keeps the hamburger button for opening/closing the sidebar.

## Website / SSL
- Website settings apply SSL automatically after domain changes.
- Added an Apply SSL action and visible SSL status/message in Settings.

## Backup & Restore
- Sidebar item renamed to Backup & Restore.
- Backup setup moved to website-only management.
- Backup destination can be Channel, Group, or Bot/private chat.
- Backup destination has a Test button.
- Channel/group tests verify bot admin access and show success/failure status.
- Manual backup creates a JSON backup and sends it to the configured Telegram destination.
- Added local JSON restore card that synchronizes database tables and resets sequences.
- Backup and restore buttons were removed from the Telegram bot settings menu.

## Build
- Runtime Docker image uses prepared `frontend_out` and includes fonts required for Persian PDF output.
- Added ReportLab, arabic-reshaper, and python-bidi dependencies for clean Persian PDF export.
