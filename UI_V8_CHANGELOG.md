# UI v8 Changelog

## Plan Sorting
- Added drag-and-drop plan ordering in Admin Web > Plans.
- Saved public plan order in `settings.plan_order_public`.
- Saved reseller package order in `settings.plan_order_reseller`.
- Telegram public sales plan list now follows the saved public plan order.
- Telegram reseller top-up package list now follows the saved reseller package order.

## Reseller Server Bot Fixes
- Fixed reseller server deletion from the Telegram admin bot.
- Deleting a reseller server now detaches related reseller packages/accounts/build configs/payment cards safely.
- If the server has active services, it is archived and removed from the reseller server list instead of breaking existing services.
- Added manual Inbound ID fallback when adding a reseller server from the Telegram bot if auto-detection fails.

## Build
- Frontend static output regenerated and copied to `frontend_out`.
- Python source compile check passed.
