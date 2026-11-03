# PasarGuard connection timeouts during PAYG polling

`ConnectTimeout` means the connection could not be established within the
configured timeout; it does not establish that an API path, password, token or
user ownership filter is wrong. Common areas to inspect are container DNS,
the configured panel host/port, routing, firewall, proxy environment and TLS.
The log alone, especially with the URL redacted, cannot identify which applies.

The provider now distinguishes transport failures from route discovery errors.
ConnectTimeout/ConnectError get one bounded connection retry. Once an origin
cannot be reached, alternate paths on that origin are skipped in that discovery
pass. Real 404/405 responses still trigger path discovery. Authentication denials
are not retried. Read/write timeouts are not automatically replayed, protecting
ambiguous config creation, rotation, renewal and deletion requests. TLS
verification remains enabled; proxy behavior and the configured host are not
silently changed.

PAYG polling already fetches the complete, ownership-verified snapshot before
updating billing. On failure, wallet, usage, time checkpoint, debt and suspension
state remain unchanged. The next successful poll resumes from that checkpoint.
The detailed transport category is now saved to last_error, and an error report
is sent through the existing backup error-report path when it changes. Repeated
identical failures do not repeatedly notify until the meter recovers.

After replacing the project files and rebuilding the bot image, run from the
installation directory:

```bash
docker compose exec -T bot python scripts/diagnose_pasarguard_connection.py --order-id 1
```

The diagnostic reads the saved server for that order, resolves DNS in the bot
container and performs unauthenticated GET probes. It prints safe origins,
resolved IPs, response statuses or transport error types, and the names of proxy
environment variables that are present (never their values). It does not decrypt
or send panel passwords/API keys, embedded URL credentials or query tokens, and
does not modify panel users, wallet or configuration. A 401/403 response proves
an HTTP response was received, but may still originate from a proxy/WAF.

Tests simulate connection outages, transient recovery, route fallback,
authentication rejection, ambiguous mutations, billing preservation/recovery,
report deduplication and diagnostic credential stripping. No live VPS or panel
was contacted during implementation; a persistent network outage requires
correcting reachability on the deployment.

References:
- https://www.python-httpx.org/advanced/timeouts/
- https://www.python-httpx.org/advanced/transports/
