# UI v11 - 3x-ui CSRF Login Fix

## Fixed

- Fixed 3x-ui hidden path connection when the panel URL includes a Web Base Path such as `/U76peSug8RbmlymBHQ/`.
- Fixed API requests losing the hidden panel path by switching XUI client requests to relative URL joining.
- Added CSRF + cookie login flow for newer 3x-ui versions:
  1. GET the panel base path to receive the `3x-ui` cookie and `csrf-token` meta value.
  2. POST `/login` with `X-CSRF-Token`, `X-Requested-With`, `Origin`, and `Referer` headers.
  3. Reuse the same cookie jar for `/panel/api/inbounds/list` and all later panel API calls.
- Kept compatibility with older Sanaei/x-ui routes and form-login fallback.

## Correct panel form values for the tested server

```text
Panel URL / Origin: https://panel.mgiftshop.ir
Panel Web Path: /U76peSug8RbmlymBHQ/
Username: your 3x-ui username
Password: your 3x-ui password
```

## Test

```bash
python -m compileall -q app
```
