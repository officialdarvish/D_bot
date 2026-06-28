# D BOT Cyber Admin UI v2

Applied changes:
- Modern dark login page for owner access.
- Header cleaned: only the Admin/Owner profile button remains in top actions.
- Profile image upload/removal through the Admin button using browser local storage.
- Dashboard date filter with dark themed date inputs.
- Removed dashboard page badge and all dollar signs from dashboard money values.
- Removed Top Plans from dashboard.
- System Status no longer has the View all button.
- Recent Activities now displays the buyer username/name.
- Recent Orders shows Wallet when the order is a wallet recharge or has no plan but wallet-like payment method.
- Revenue Export downloads a complete sales PDF from bot start, sorted oldest to newest.
- Revenue View Report opens the orders report with the selected date range.
- Dark dropdown/select backgrounds for all modal forms.
- Dark themed scrollbars for tables, modals, and page scroll.
- Discount form supports Percent and fixed Toman discount types.
- Users table includes a reseller status column with green/red icons.
- Add Reseller modal includes database user search by full name, username, or numeric Telegram ID and auto-fills user fields.
- Server Refresh updates only the selected server card visually.
- Settings includes bot start text, rules text, bot status, and database info card that writes to the settings table.
- Buttons/cards now brighten on hover/focus/active states so selected/clicked elements are visible.

Build notes:
- frontend_out is rebuilt and included.
- Dockerfile uses frontend_out directly, so Docker build does not need npm install or next build.
