# Native Mini App workflows — 2026-10-18

- Resellers can create configurations, increase volume/days, renew, delete, rotate credentials and clear HWIDs within the Mini App. Server allowlists, inbound policies, inventory settlement and PAYG accounting use the existing bot workflows.
- Volume packages and PAYG wallet recharge support personal-wallet payment and card receipts. Personal-wallet recharge also accepts receipts inside the Mini App. Administrators use the existing approval buttons.
- Home ends with order tracking, including open receipts submitted earlier in chat. Each eligible pending receipt has a real resend action, with a five-minute cooldown. Completed purchases do not appear below the shop catalogue; subscriptions remain in Configs.
- Public renewal lists active public categories/plans from the subscription's existing panel, charges the server-calculated price and renews the same subscription. It supports wallet and card receipts.
- Public link revocation and HWID clearing are native confirmed actions. Conversion explicitly opens the existing Telegram bot conversion flow.
- Mini App interactions do not send intermediate prompts, menus or funding approval messages to buyers. Completed subscription purchases/renewals deliver subscription details in Telegram. Administrator notices remain enabled.
- ERROR log records and tracebacks are forwarded as text documents to the configured backup destination, respecting its selected sender bot. Tokens, database credentials and URLs are redacted. Repeated identical records are coalesced for 30 seconds; report-delivery errors do not recursively report themselves.

## Persistence and recovery

Startup creates the `miniapp_operations` table using the existing schema initialization. Operation keys are unique, scoped to the authenticated purchaser and checked against request contents. Financial/remote actions are committed before final chat delivery. An interrupted remote mutation is marked for review after 15 minutes and is never blindly retried. Mini App operations are included in portable backup/restore.

Deployment requires rebuilding the full API and bot images. Real panel connectivity and Telegram delivery must be checked on the deployment; local integration tests use mocked provider/Telegram calls.

## Validation

The full local suite passed 388 tests. The same five pre-existing failures remain in dashboard/source-shape and legacy duplicate-name/performance assertions. Production frontend compilation and TypeScript checking succeeded. Mobile-browser checks cover native reseller creation, volume changes, card receipt upload, actual receipt resend, HWID reset, wallet renewal, conversion handoff, and the final Home/shop placement. Provider, Telegram and backup-channel delivery were mocked in local integration tests; no production credentials or live payment were used.
