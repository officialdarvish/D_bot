# UI v13 - 3x-ui addClient hard fix + Resellers cleanup

- Removed legacy `/panel/inbound/addClient` calls from service creation completely.
- Service creation now only uses the modern 3x-ui endpoint: `/panel/api/clients/add`.
- Kept hidden-path + CSRF/cookie login support for panels like `/U76peSug8RbmlymBHQ/`.
- Cleaned the Resellers page: reseller package/plan preview is no longer shown there; only reseller users are displayed.
- Rebuilt `frontend_out` after the Resellers UI cleanup.
