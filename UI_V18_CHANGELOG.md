# UI v18 - DB UUID + stale plan callback fix

## Fixed

- Fixed PostgreSQL/asyncpg error when `client_services.xui_uuid` received a numeric 3x-ui record id such as `407` instead of a string proxy UUID.
- Normalized 3x-ui Client API records so `uuid` is used as the wire-client `id` and numeric database row ids are preserved separately as `db_id`.
- Converted all stored `xui_uuid` values to string-safe values across public buy, webhook creation, reseller service creation, test accounts, referrals and revoke/regenerate flows.
- Fixed stale buy buttons (`buy:plan:<id>`) that could crash when a plan was deleted, disabled, or lost its server.
- Added user-facing guard for removed/inactive plans so users are sent back to the buy menu instead of triggering `NoneType.server_id`.

## Notes

These fixes are related to admin error reports:

- `invalid input for query argument $1: 407 (expected str, got int)`
- `AttributeError: 'NoneType' object has no attribute 'server_id'`
