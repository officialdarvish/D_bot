# Purchased PasarGuard PAYG panels

Approved purchased dashboard panels now appear in the Mini App independently of configuration-reseller accounts. The panel view reads the existing User wallet used by the panel meter; balances are shared across purchased panels belonging to that user. It never substitutes the separate configuration-reseller wallet.

Panel wallet recharge supports the Mini App receipt workflow and the bot's dedicated panel recharge button. Ownership and approved provisioning status are required. Payment cards use the panel server's reseller card, with the existing global reseller fallback. Receipt approval credits the existing wallet once.

The meter checks low-credit levels at 200,000 / 150,000 / 100,000 / 50,000 toman. Persistent per-user state suppresses repeats across polls and panels. If several levels are crossed between checks, one notification reports the lowest crossed level. Failed delivery is retried; successful recharge re-arms replenished levels. Exhausted-wallet notices also include the recharge button.

Proactive `pgsale:shop` approval buttons and `pgsale:topup:` buttons bypass the menu's stale-message guard. Their handlers retain approval and ownership checks.

Validation: six focused integration tests cover panel visibility without a configuration-reseller account, ownership, card receipts and idempotent approval, persistent thresholds and re-arming, failed-send retries, callback freshness, and meter integration. Browser checks cover newly approved panels appearing without reopening the Mini App, actual balance display, responsive panel details, and native receipt submission.

## Recharge confirmation and recovery

A dedicated panel recharge now creates a durable post-credit operation in the same transaction as receipt approval. After commit, the purchaser receives a Telegram confirmation even when the receipt came from the Mini App. A failed Telegram send stays queued for the next panel synchronization; retries never credit the wallet again.

For PAYG panels, recovery settles current usage and restores only the remote user IDs recorded by the credit cutoff. Manually disabled users and tariff-conversion pauses remain disabled. If provider recovery fails or credit cannot cover outstanding usage, the charge notification reports pending activation, and the synchronization worker retries. In volume mode, recovery refreshes prepaid capacity and panel-admin account limits without lifting manual configuration pauses.

The Mini App panel wallet uses a dedicated graphical card with an accessible recharge button. The amount page offers 100,000 / 200,000 / 500,000 / 1,000,000 Toman shortcuts plus custom entry. Refresh applies a fresh account snapshot, permissions, panel access and reseller menu before fetching the catalog. Catalog failures therefore cannot hide newly approved reseller access; superseded refresh responses cannot overwrite newer state.
