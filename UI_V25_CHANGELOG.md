# UI v25 - API Syntax Hotfix

## Fixed
- Fixed API startup failure caused by a Python f-string quoting bug in `app/api/admin_web.py`.
- The API no longer crashes with: `SyntaxError: f-string: unmatched '('`.
- Re-ran Python syntax compile check across the full `app` package.

## Verification
```bash
python -m compileall -q app
```
