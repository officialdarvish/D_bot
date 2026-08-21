from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "dbot-launcher.sh"
CONTROL = ROOT / "scripts" / "dbot-control.sh"
INSTALL = ROOT / "install.sh"
REPAIR = ROOT / "scripts" / "repair-dbot-cli.sh"


def test_launcher_executes_live_project_control_script(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True)
    control = scripts / "dbot-control.sh"
    control.write_text(
        '#!/usr/bin/env bash\nprintf "LIVE:%s\\n" "${1:-NOARGS}"\n',
        encoding="utf-8",
    )
    control.chmod(0o755)

    env = os.environ.copy()
    env["DBOT_APP_DIR"] = str(tmp_path)

    no_args = subprocess.run(
        ["bash", str(LAUNCHER)],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    menu = subprocess.run(
        ["bash", str(LAUNCHER), "menu"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert no_args.stdout.strip() == "LIVE:NOARGS"
    assert menu.stdout.strip() == "LIVE:menu"


def test_control_dispatch_opens_menu_for_dbot_and_dbot_menu() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    assert 'if [ "$#" -eq 0 ]; then\n  control_menu' in source
    assert 'menu|m|control|center|--menu) control_menu ;;' in source


def test_installer_uses_live_symlink_instead_of_stale_copy() -> None:
    source = INSTALL.read_text(encoding="utf-8")
    assert '$APP_DIR/scripts/repair-dbot-cli.sh' in source
    assert 'bash "$repair"' in source
    assert 'ln -s "$target" /usr/local/bin/dbot' in source


def test_update_refreshes_cli_from_fresh_checkout() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    assert 'bash "$APP_DIR/scripts/repair-dbot-cli.sh"' in source
    assert 'This is intentionally done before Docker rebuilds' in source


def test_repair_script_installs_live_symlinks(tmp_path: Path) -> None:
    app = tmp_path / "app"
    scripts = app / "scripts"
    bindir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    launcher = scripts / "dbot-launcher.sh"
    control = scripts / "dbot-control.sh"
    launcher.write_text('#!/usr/bin/env bash\nexec bash "$(dirname "$0")/dbot-control.sh" "$@"\n', encoding="utf-8")
    control.write_text('#!/usr/bin/env bash\necho live-menu\n', encoding="utf-8")

    env = os.environ.copy()
    env["DBOT_APP_DIR"] = str(app)
    env["DBOT_BIN_DIR"] = str(bindir)
    subprocess.run(["bash", str(REPAIR)], env=env, check=True, text=True, capture_output=True)

    dbot = bindir / "dbot"
    dbot_alias = bindir / "d-bot"
    assert dbot.is_symlink()
    assert dbot.resolve() == launcher.resolve()
    assert dbot_alias.is_symlink()
    assert dbot_alias.resolve() == launcher.resolve()
