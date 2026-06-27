# D BOT Cyber Admin UI v5 Changelog

## VPS Installer

- The installer now prints the web admin login URL, username, password, and role after the containers are built and HTTPS setup finishes.
- Added `dbot credentials` / `dbot info` command to show the initial web admin credentials from `.env`.
- Installer output now clearly tells the owner to save the generated web admin credentials.

## Website Login Security

- When the website username or password is changed from `Settings > Website & SSL`, all active admin sessions are invalidated.
- The current browser is logged out automatically and redirected to `/login?updated=1`.
- Login page now shows a message telling the owner to sign in again with the new credentials.

## Documentation

- Rebuilt `README.md` in English with full install, command, admin panel, backup, SSL, Docker, troubleshooting, donation, and permission sections.
- Rebuilt `README_FA.md` in Persian with the same structure and details.
- Added NOWPayments donation block and official links.
- Updated license text to require explicit permission before copying, redistributing, reselling, or using the source in another project.

## Validation

- Frontend production build completed successfully.
- Python app compile check completed successfully.
