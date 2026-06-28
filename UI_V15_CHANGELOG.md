# UI v15 - Safe Bot Error Reporting

## Changes

- Added centralized bot error reporting.
- Full technical errors and tracebacks are sent only to configured owner/admin Telegram IDs.
- End users no longer see raw exceptions, HTTP errors, panel errors, stack traces, or client errors.
- User-facing error message is now always:

```text
❌ خطایی رخ داده
هرچه زودتر با پشتیبانی در ارتباط باشید.
```

- Added global safe error middleware for unhandled bot message/callback exceptions.
- Updated public purchase, wallet purchase, crypto payment, service renewal, service deletion, link revoke/regenerate, and reseller flows to hide technical errors from users.
- Updated admin-side bot actions that previously displayed raw panel errors to use safe messaging while sending details to owners.

## Admin Error Report Includes

- UTC time
- Context/action name
- Telegram user ID, username, full name
- Chat ID/type
- Callback data or message text
- Full traceback
