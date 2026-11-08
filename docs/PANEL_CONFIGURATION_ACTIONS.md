# Purchased-panel configuration controls

The My Configs detail page now offers delete, HWID reset, subscription rotation,
quota extension, day extension and renewal for users created through a purchased
PasarGuard panel. These controls stay inside the Mini App and authenticate using
the purchased sub-admin; they do not use the ordinary retail or config-reseller
write paths. The completed creation operation, panel owner, remote numeric ID
and upstream admin ownership are verified before every mutation.

Quota extension and renewal add the requested GiB to the existing finite quota;
usage counters and unused quota are preserved. Renewal sets a new expiry from
now and activates the service. Day extension adds days to the later of the
current expiry or now, preserving the existing status. Volume-mode growth is
reserved once before the remote write. PAYG growth requires a funded,
unsuspended wallet. Admin manual-tariff pauses cannot be bypassed by growth or
renewal. PAYG deletion checkpoints last observed traffic for the normal meter;
volume-mode deletion refunds only unused, reserved quota after deletion is
confirmed. These controls do not send extra customer Telegram messages.

Each operation has a durable request key and absolute remote targets. Repeated
requests reuse the result and cannot charge or extend again. Unknown outcomes
retain the reservation and offer an explicit same-key continuation. Rotation
retries adopt an already changed panel URL; deletion retries reconcile confirmed
absence. Deleted configs are persistently hidden even during a panel outage.
The UI restores incomplete operations after leaving/reopening a control. A
short processing lease prevents parallel writes; pending operations also block
new native panel creation and financial mode changes/manual admin renewal.

Validation: test_miniapp_panel_actions.py exercises all six controls, scoped
access, remote identity, confirmation, volume debit/refund idempotency,
insufficient volume, manual pauses, usage preservation, uncertain update/delete/
rotation recovery and operation restoration. Browser checks exercise all six
controls and same-key recovery without Telegram handoff at 320–520px widths.
Tests simulate remote panel and Telegram APIs; live deployment was not performed.
