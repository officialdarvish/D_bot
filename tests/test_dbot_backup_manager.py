import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dbot-control.sh"


def _env(app: Path, keep: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "TERM": "xterm",
            "DBOT_APP_DIR": str(app),
            "DBOT_BACKUP_KEEP_DIR": str(keep),
        }
    )
    return env


def _run(args: list[str], *, app: Path, keep: Path, input_text: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=_env(app, keep),
        check=True,
    )


def test_backup_list_is_oldest_first_and_skips_symlink(tmp_path: Path) -> None:
    app = tmp_path / "app"
    keep = tmp_path / "keep"
    (app / "backups").mkdir(parents=True)
    archived = keep / "backups-20260401_120000"
    archived.mkdir(parents=True)

    old = app / "backups" / "dbot-backup-20260101_010101.tar.gz"
    middle = app / "backups" / "dbot-backup-20260202_020202.tar.gz"
    new = archived / "dbot-backup-20260303_030303.tar.gz"
    for path, payload in [(old, b"old"), (middle, b"middle"), (new, b"new")]:
        path.write_bytes(payload)

    (app / "backups" / "not-a-backup-link").symlink_to("/etc/passwd")

    result = _run(["backup-list"], app=app, keep=keep)
    output = result.stdout

    assert output.index(old.name) < output.index(middle.name) < output.index(new.name)
    assert "2026-01-01 01:01:01" in output
    assert "2026-03-03 03:03:03" in output
    assert "not-a-backup-link" not in output


def test_backup_manager_deletes_single_item_then_all(tmp_path: Path) -> None:
    app = tmp_path / "app"
    keep = tmp_path / "keep"
    (app / "backups").mkdir(parents=True)
    keep.mkdir(parents=True)

    first = app / "backups" / "dbot-backup-20260101_010101.tar.gz"
    second = app / "backups" / "dbot-backup-20260202_020202.tar.gz"
    third = keep / "dbot-backup-20260303_030303.tar.gz"
    for path in (first, second, third):
        path.write_bytes(b"backup")

    one = _run(["backups"], app=app, keep=keep, input_text="2\ny\n\n0\n")
    assert "Backup deleted." in one.stdout
    assert first.exists()
    assert not second.exists()
    assert third.exists()

    all_result = _run(["backups"], app=app, keep=keep, input_text="A\nDELETE ALL\n\n0\n")
    assert "Deleted 2 backup item(s)." in all_result.stdout
    assert not first.exists()
    assert not third.exists()
