# UI v28 — MikroTik / OpenVPN Profile Integration

- Added `MikroTik` as a server panel type alongside 3x-ui/Sanaei.
- Added MikroTik REST adapter for the documented PPP Secret Panel API only.
- Server add/edit form now changes fields for 3x-ui vs MikroTik and keeps Test Connection.
- Public and reseller service creation now supports MikroTik user creation with customer-selected username.
- MikroTik create/update/delete/revoke/sync lifecycle is wired to the documented REST API.
- Added OpenVPN Profile admin section for add, edit, delete, upload and full text editing of `.ovpn` profile content.
- Added bot button `📥 دریافت پروفایل سرور` to send the matching `.ovpn` file to the customer.
- Added OpenVPN and iPhone L2TP guidance in MikroTik service messages.
- Plan forms now show MikroTik protocol/profile/L2TP fields when a MikroTik server is selected.
- No uploaded sample credentials, API keys, router passwords, login URLs, or OVPN private content are hard-coded into the project.
