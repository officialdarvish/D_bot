# Validation of the 1.4.0 web setup and integrations update

Date: 2026-11-12. The maintainer requested publication as version 1.4.0 after receiving this validation status. Publication does not imply additional operational validation.

## Results

| Check | Result | Scope |
| --- | --- | --- |
| Full D BOT test suite | 1211 passed, 12 failed, 3 subtests passed | Run before the final Telegram NX registration/profile and connection-removal adjustments |
| Latest focused regression run | 64 passed | NX lifecycle/registration/reseller profile ownership, Bridge checkout/signature/delivery/auth, shared connections/migration, secure host queue/runtime selection, service deletion/list removal, reseller scope |
| Bridge companion suite | 11 passed | Original MVP tests plus explicit digital capability test |
| Next.js production build | Passed | React export and TypeScript checking |
| Generated wizard JavaScript | 3 script blocks parsed successfully | Includes conditional stages, progress persistence and same-origin frame messages |
| Python syntax | Passed | Application and worker sources; Python 3.11 syntax parsing also checked |
| Shell syntax and whitespace | Passed | Installer, host updater installer, CLI; git diff --check |

Run the Python suite with the project virtual environment on PATH so the backup CLI subprocess uses the same dependencies. `pytest.ini` confines discovery to tests rather than Telegram handlers whose production names start with test_. Companion tests run separately from integrations/darvish_bridge with PYTHONPATH=.; the two projects intentionally have separate app packages.

The AES backup test now supplies a deterministic matching Fernet context to its subprocess. It does not weaken decryption or accept an incorrect key. Provider admission and shared-scope assertions were updated for NX and scope=all. Unrelated failing assertions were not removed or marked xfail.

## Remaining full-suite failures

The following failures were also observed against original main commit `24b671fda1772d0bb3bc84663ebf3dbd3d984a52` in the baseline comparison. Several inspect historical literal source/UI text; the two HWID tests mock the verified revoke method with an unverified response. They remain unresolved and are not counted as passing:

- tests/test_dashboard_sales_report_factory_reset.py::DashboardSalesReportFactoryResetTests::test_dashboard_ui_requested_changes_present
- tests/test_dashboard_sales_report_factory_reset.py::DashboardSalesReportFactoryResetTests::test_scroll_fixes_and_plans_sidebar_behavior_present
- tests/test_hwid_rotation_content.py::test_pasarguard_native_reset_preserves_remote_account_and_quota[False]
- tests/test_hwid_rotation_content.py::test_pasarguard_native_reset_preserves_remote_account_and_quota[True]
- tests/test_hwid_rotation_content.py::test_telegram_tutorial_sends_manual_text_and_download
- tests/test_legacy_restore_secret.py::LegacyRestoreSecretTests::test_web_and_telegram_restore_paths_pass_legacy_secret
- tests/test_pasarguard_payg_panel.py::test_web_pricing_and_scrollbar_and_scheduler_wired
- tests/test_persian_admin_errors_and_reseller_duplicate_names.py::test_reseller_duplicate_names_use_independent_four_digit_sequence
- tests/test_persistent_report_home_and_test_account.py::test_persistent_reports_have_home_button_and_stale_guard_exception
- tests/test_reseller_created_admin_report_home.py::test_reseller_created_admin_notice_has_persistent_home_button
- tests/test_revenue_cycle_export.py::test_reset_and_export_wired_to_persistent_backend
- tests/test_sanaei_380_sync.py::Sanaei380CompatibilityTests::test_runtime_performance_features_are_enabled

## Operational limits

No real VPS, Docker daemon/systemd update/recovery, live PostgreSQL migration, NX panel, Bridge bank transfer/webhook delivery or interactive browser session was verified. API/provider tests use SQLite and mocked HTTP/Telegram boundaries. Successful builds and unit tests do not replace these checks.

Compatible duplicate connections are consolidated transactionally. Conflicting tariffs, receipt recipients, inbound policies or usernames are retained and reported rather than guessed. Legacy financial rows and server aliases are preserved. See SERVER_CONNECTION_MIGRATION_FA.md.

Public-source detection finds GitHub forks and indexed copies retaining the marker. It cannot guarantee detection of private, unindexed or marker-removed copies. The workflow becomes active only after publication on the repository's default branch.

The release notes retain these test discrepancies and operational limits. The maintainer explicitly requested publishing PR #33 as version 1.4.0.


## 1.4.0 build 2 — settings, trial customization and dashboard version

Date: 2026-11-12.

- Full D BOT suite: **1223 passed, 12 failed, 3 subtests passed** (119.72 seconds). The failed test names are exactly the twelve previously documented above; no new full-suite failure was observed.
- Related regression suite: **108 passed** across Custom/delivery templates, shared-server migration and payment binding, module/update controls, fractional/multi-server trials, Mini App trials and reseller onboarding.
- Final delivery/migration checks: **31 passed**, including saving and reading trial overrides through the API, actual service delivery through a plain mock bot, long captions, all supported trial provider layouts, reset, media edits/albums/buttons, role-specific recipient preservation, old v1 conflict retry and alias payment routing.
- Frontend TypeScript check and production static build: **passed**. Generated frontend/out files were restored; Docker builds the source export.
- The historical trial-input test now accepts subsequent semantic versions instead of requiring the obsolete literal 1.3.0.

Bot modules now use shared settings styles and bilingual switch cards. The Version card sits below System Status and retains the host update confirmation flow; manual recheck bypasses the five-minute update metadata cache. The legacy migration banner and Servers subtitle were removed. Build 2 changes only update.json metadata, so it does not overwrite the v1.4.0 release tag or assets.

Operational limits above still apply. Chromium could not launch in this environment, so no interactive visual/browser check was completed. The role-aware v2 consolidation runs on application startup after installation; the user's live server IDs #5/#8 were not directly inspected or modified. Genuine changes to a role's payment recipient still prevent automatic consolidation.


## 1.4.0 build 3 — Bridge in Payments and VPS update confirmation

Date: 2026-11-12.

- Backend integration/regression checks: **25 passed**. Panel confirmation writes an exclusive complete request to the shared directory, the host runner consumes it, backs up, checks out the official commit, builds/restarts, and reports completion. Failure tests cover manifest rejection, build/health recovery and preserved backups. Docker/systemd command execution is mocked; this is not a live VPS deployment test.
- React DOM interaction checks: **6 passed** using JSDOM and the real language provider. Both English and Persian exercise Payments + → Bridge configuration/save, retained blank credentials and the bank-card alternative; update confirmation sends the expected commit/CSRF token, immediately displays queued status and blocks duplicates. Offline-worker feedback and refreshing a changed commit before retry are covered. A private web path is checked too. Run `npm --prefix frontend run test:payments-updater`.
- Full D BOT suite: **1232 passed, 12 previously documented failures, 3 subtests passed** (122.92 seconds). Failed test names are unchanged from build 2.
- Next.js production export with TypeScript checking: **passed**. Generated frontend/out is not committed.
- Python syntax, installer shell syntax and whitespace checks: **passed**.

Bridge settings now live under Payments, including a payment-method chooser and a configurable saved connection card. The backend encryption, capability verification and bot/Mini App configuration remain shared; API save/disable/error checks prove they stay synchronized.

The update confirmation now uses the existing admin dialog system, acknowledges queued jobs immediately and shows host connection diagnostics. Publishing a request uses a temporary file plus an exclusive atomic link, so the worker cannot read partial JSON or accept duplicate jobs. The systemd installer checks actual readiness. After a healthy web update, the host worker is replaced from the new source before a deferred restart, after request cleanup. The queue is excluded from Docker build context.

An old installation with no host agent still requires `sudo dbot update` once on that same VPS; a web container cannot install a privileged service on an inaccessible host. No user VPS connection, SSH/Docker/systemd deployment, live Bridge payment or graphical Chromium check was performed. Existing v1.4.0 release assets/tag are preserved; update.json advances to build 3.


## 1.4.0 build 4 — horizontal dashboard statistics

The four dashboard statistic cards now form a single horizontal row with line icons next to their labels/values, distinct accent colors and correct negative trend coloring. Narrow screens retain the row with horizontal scroll/snap and a visible next-card edge; logical CSS supports Persian RTL. The scrollable list can receive keyboard focus. Other dashboard sections and data sources are unchanged.

Next.js production build, final TypeScript check and git diff whitespace validation passed. This is a reversible presentation change; backend tests were not rerun, and no interactive graphical browser/VPS validation was performed. Build metadata advances to 4; the v1.4.0 release assets/tag remain unchanged.
