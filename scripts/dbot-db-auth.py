#!/usr/bin/env python3
"""Synchronize the installed PostgreSQL role and the D BOT connection URL."""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

DB_ENV_KEYS = (
    "POSTGRES_USER", "POSTGRES_DB", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_PASSWORD",
    "DATABASE_URL",
)
PSQL = ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1"]
TCP_CHECK = """
IFS= read -r PGPASSWORD || exit 1
export PGPASSWORD PGCONNECT_TIMEOUT=5
export LC_ALL=C
exec "$@" -h 127.0.0.1 -c 'SELECT 1'
"""


def compose(args, *, secret=None, timeout=30):
    env = dict(os.environ)
    for key in DB_ENV_KEYS:
        env.pop(key, None)
    return subprocess.run(
        [*sys.argv[2:], *args], input=secret, stdin=None if secret is not None else subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, env=env,
    )


def sync_password(mode, env_file):
    config = compose(["config", "--format", "json"])
    if config.returncode:
        raise ValueError("Could not read the Compose configuration. Verify Docker Compose and the .env syntax.")
    services = json.loads(config.stdout)["services"]
    db = services["db"]["environment"]
    user, database, current = (db[key] for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"))
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", database):
        raise ValueError("The configured database name is outside the standard installer format.")
    if not current or any(ch in current for ch in "\r\n\x00"):
        raise ValueError("The configured PostgreSQL password must be nonempty and on one line.")
    for service in ("api", "bot"):
        raw_url = services[service]["environment"]["DATABASE_URL"]
        scheme, sep, body = raw_url.partition("://")
        credentials, at, target = body.rpartition("@")
        parsed = urlsplit(f"{scheme}://{target}")
        if (
            not sep or not at or scheme != "postgresql+asyncpg"
            or parsed.hostname != "db" or parsed.port not in (None, 5432)
            or unquote(credentials.partition(":")[0]) != user
            or parsed.path != f"/{database}" or parsed.query or parsed.fragment
        ):
            raise ValueError("This command requires the standard bundled PostgreSQL connection for API and bot.")

    password = current
    if mode == "change":
        password = sys.stdin.readline().removesuffix("\n")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{12,128}", password):
            raise ValueError("Use 12–128 English letters, digits, _ or -.")
    url = f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}@db:5432/{database}"
    values = {"DATABASE_URL": url}
    if mode == "change":
        values["POSTGRES_PASSWORD"] = password

    original = env_file.read_text(encoding="utf-8")
    lines = [line for line in original.splitlines() if line.split("=", 1)[0].strip() not in values]
    lines.extend(f"{key}={value}" for key, value in values.items())
    exec_db = ["exec", "-T", "db"]
    connection = [*PSQL, "-U", user, "-d", database]

    def check(value):
        return compose([*exec_db, "sh", "-c", TCP_CHECK, "sh", *connection], secret=value + "\n")

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=env_file.parent, delete=False) as staged:
        staged_path = Path(staged.name)
        staged.write("\n".join(lines) + "\n")
    try:
        auth = check(current)
        if auth.returncode and "password authentication failed" not in auth.stderr:
            raise ValueError("PostgreSQL is unavailable or the configured database is invalid. Check the db service and retry.")
        if env_file.read_text(encoding="utf-8") != original:
            raise ValueError("The .env file changed during the operation. Retry.")
        if auth.returncode or password != current:
            # The bundled image permits local socket administration. psql hashes
            # the new password before issuing ALTER ROLE and reads it from stdin.
            changed = compose([*exec_db, *connection, "-c", r"\password"], secret=f"{password}\n{password}\n")
            if changed.returncode:
                raise ValueError("Could not set the role password through the local PostgreSQL socket. Check the db service's local authentication policy.")
        # Keep configuration recoverable on retries even if the post-change check fails.
        staged_path.replace(env_file)
        if check(password).returncode:
            raise ValueError("PostgreSQL rejected the configured password after synchronization. Check the db service and retry.")
    finally:
        staged_path.unlink(missing_ok=True)

    if compose(["up", "-d", "--no-deps", "--force-recreate", "api", "bot"], timeout=120).returncode:
        raise ValueError("PostgreSQL authentication was verified. API or bot could not be recreated; check Docker Compose and run this command again.")


def main():
    mode = sys.argv[1]
    try:
        with open(".dbot-db-auth.lock", "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            sync_password(mode, Path(".env"))
    except BlockingIOError:
        sys.exit("A PostgreSQL credential operation is already running.")
    except (OSError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        if type(error) is ValueError:
            sys.exit(str(error))
        sys.exit("Could not complete PostgreSQL authentication recovery. Check Docker Compose and .env.")
    print("PostgreSQL authentication verified. API and bot containers recreated.")


if __name__ == "__main__":
    main()
