# Nginx activation on Ubuntu 22 and other supported releases

Reported symptom: the SSL installer says Nginx does not load sites-enabled or
conf.d even though nginx.conf includes both. The prior activation code piped
`nginx -T 2>&1` into `grep -Fq` under `set -Eeuo pipefail`. On an early match,
grep closes the pipe before a sufficiently large dump finishes. Nginx can then
exit on SIGPIPE (141), so the successful match is interpreted as failure.
The outcome depends on output size and process scheduling, not solely the
Ubuntu version. Upgrading the OS is not required to fix this script bug.

The script now captures the complete dump and its exit status before checking
exact configuration-file banner lines. It supports sites-enabled, conf.d and
Nginx versions that report the canonical sites-available path. A genuine Nginx
configuration error is shown as such and does not trigger a misleading fallback.
Quiet grep was also removed from the UFW and listener producer pipelines;
those checks now consume their full input. Nginx syntax checks remain required
before reload. Existing certificate/webroot and proxy behavior is unchanged.

Validation: test_nginx_activation_pipefail.py runs real Bash with pipefail and
an isolated fake Nginx producer. An 8 MiB dump reproduces exit 141 in the old
pipeline, then succeeds through the corrected activation. Other cases cover
both include layouts, canonical paths, real errors (even with a matching banner)
and genuinely absent includes. Shell syntax and existing setup tests pass.
No services, certificates or host configuration are modified by these tests.
The test environment is Ubuntu 24; real Ubuntu 22/26 deployment was not performed.

References:
- https://www.gnu.org/software/grep/manual/html_node/Usage.html
- https://nginx.org/en/docs/switches.html
