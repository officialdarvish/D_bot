#!/usr/bin/env python3
"""Read-only source completeness check, usable before Docker starts or without .env."""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
import sys

REQUIRED = {
    'app/services/conversion_recovery.py': {'release_failed', 'ensure_available', 'destination_absent'},
    'app/bot/handlers/admin/conversion_requests.py': {'conversion_requests', 'show_list', 'show_detail', 'panel_state'},
    'app/api/miniapp_ownership.py': {'preview','transfer'},
    'app/services/reseller_onboarding.py': {'catalog','checkout','submit','approve','finalize_panel'},
    'app/api/miniapp_reseller_join.py': {'catalog','purchase','receipt'},
    'app/bot/handlers/public/reseller_join.py': {'shop','approve','receipt'},
    'app/api/miniapp_actions.py': {'conversion_catalog', 'conversion_preview', 'conversion_confirm'},
    'app/services/error_backup.py': {'send_error_log', 'redact'},
    'app/services/service_ownership.py': {'OwnershipTransferError', 'eligible_service', 'recipient_telegram_id', 'transfer_service_ownership'},
    'app/services/receipt_status.py': {'receipt_failure_reason', 'receipt_status_label'},
    'app/services/disk_cleanup.py': {'cleanup_artifacts', 'temporary_artifact'},
    'app/bot/states/public_states.py': {'ServiceOwnershipTransfer','ResellerJoin'},
    'app/bot/handlers/public/my_services.py': {'begin_ownership_transfer', 'receive_ownership_recipient'},
    'app/bot/handlers/admin/pending_receipts.py': {'pending_receipts_keyboard', 'pending_receipts_detail'},
}


def check_runtime_files(root: Path) -> list[str]:
    errors = []
    for name, required_exports in REQUIRED.items():
        path = root / name
        if not path.is_file():
            errors.append(f'Missing required file: {name}')
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=name)
        except (OSError, UnicodeError, SyntaxError):
            errors.append(f'Unreadable or invalid Python file: {name}')
            continue
        exports = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        missing = required_exports - exports
        if missing:
            errors.append(f'Incomplete or outdated file: {name}; missing: {", ".join(sorted(missing))}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = check_runtime_files(args.root)
    if errors:
        for error in errors:
            print(f'[dbot-runtime] ERROR: {error}', file=sys.stderr)
        print('[dbot-runtime] Extract the FULL release into the Docker build directory, then rebuild api and bot. No database changes are required.', file=sys.stderr)
        return 1
    print('[dbot-runtime] Required source files are present and valid. Ownership transfer and receipt inbox modules are included.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
