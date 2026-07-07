# D Bot v1.1.4 - GitHub Ready Build

This package is cleaned and prepared for the GitHub `v1.1.4` tag.

## Included fixes and changes

- Removed the Pay As You Go runtime flow from the bot.
- Kept startup cleanup for old PayG database columns/tables so older installs can migrate safely.
- Added admin-only free service purchase and renewal for all service types.
- Added Wallet inside the user interaction/admin flow with increase/decrease actions by numeric Telegram ID.
- Changed user information lookup to numeric Telegram ID only.
- Improved admin error reports so they are short, structured and focused on the exact error.
- Added service creation/renewal progress messages for users, resellers and admins.
- Added success messages with a Home button after successful service creation or renewal.
- Added short owner/admin notification when a reseller creates a config, including custom name, volume, duration and expiry date.
- Updated README.md and README_FA.md to match the current project behavior.

## Upload safety

- `.env` and local secrets are excluded.
- `.env.example` is included with safe placeholders.
- `.git/`, cache files, logs, backups, database dumps and generated runtime files are excluded.

## Suggested GitHub tag

```bash
git tag -a v1.1.4 -m "Release v1.1.4"
git push origin v1.1.4
```

## Suggested commit message

```text
Release v1.1.4: update README and finalize bot workflow fixes
```
