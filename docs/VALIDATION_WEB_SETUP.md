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
