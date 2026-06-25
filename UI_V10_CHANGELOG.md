# D BOT UI v10 - 3x-ui Connection Compatibility Fix

## Fixed

- Updated XUI client compatibility with current MHSanaei 3x-ui API routes.
- Added support for official 3x-ui session-cookie authentication through `/login`.
- Added optional Bearer/API token support by entering `token:<API_TOKEN>` or `bearer:<API_TOKEN>` in the password/token field.
- Added endpoint fallbacks for older X-UI / early 3x-ui panels:
  - `/panel/api/inbounds/list`
  - `/panel/inbound/list`
  - `/xui/API/inbounds`
  - `/panel/api/inbounds/addClient`
  - `/panel/inbound/addClient`
- Normalized pasted panel URLs so admins can paste:
  - `https://domain.com/path`
  - `https://domain.com/path/login`
  - `https://domain.com/path/panel/api/openapi.json`
- Added Panel Web Path field to the Servers modal.
- Server test/add/edit now stores both the clean panel origin and the panel web path.
- Rebuilt `frontend_out` for Docker/static serving.

## Notes

For MHSanaei 3x-ui, use either:

- Panel URL / Origin: `https://domain.com:PORT`
- Panel Web Path: `/your-secret-path/`

or paste the full panel URL in the Panel URL field and leave the path as `/`.
