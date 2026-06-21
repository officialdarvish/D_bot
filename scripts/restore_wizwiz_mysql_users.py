#!/usr/bin/env python3
"""Convert a WizWiz MySQL users dump into PostgreSQL INSERT SQL for Darvish D Bot.

Input can be a .sql file exported by mysqldump/phpMyAdmin or a .zip that contains one .sql file.
Only the users table is imported. Orders/configs are untouched.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

TARGET_COLUMNS = {
    "userid": "telegram_id",
    "username": "username",
    "name": "full_name",
    "wallet": "wallet_balance",
    "date": "joined_at",
}


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def clean_username(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"ندارد", "ندارد ", " ندارد", " ندارد ", "NULL", "null"}:
        return None
    if text.startswith("@"):
        text = text[1:]
    return text[:128] or None


def clean_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:255] or None


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def read_input(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".sql") and not n.endswith("/")]
            if not names:
                raise SystemExit("ZIP file does not contain any .sql file")
            # Prefer a users dump if present.
            names.sort(key=lambda n: ("users" not in n.lower(), len(n)))
            with zf.open(names[0]) as f:
                return f.read().decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def parse_mysql_string(s: str, i: int) -> tuple[str, int]:
    # s[i] == "'"
    i += 1
    out: list[str] = []
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 1
            if i >= len(s):
                break
            esc = s[i]
            mapping = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "Z": "\x1a", "\\": "\\", "'": "'", '"': '"'}
            out.append(mapping.get(esc, esc))
            i += 1
            continue
        if ch == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ValueError("Unterminated SQL string")


def parse_value(s: str, i: int) -> tuple[Any, int]:
    while i < len(s) and s[i].isspace():
        i += 1
    if i < len(s) and s[i] == "'":
        return parse_mysql_string(s, i)
    start = i
    while i < len(s) and s[i] not in ",)":
        i += 1
    token = s[start:i].strip()
    if token.upper() == "NULL":
        return None, i
    return token, i


def parse_tuple(s: str, i: int) -> tuple[list[Any], int]:
    # s[i] == "("
    i += 1
    values: list[Any] = []
    while i < len(s):
        while i < len(s) and s[i].isspace():
            i += 1
        if i < len(s) and s[i] == ")":
            return values, i + 1
        value, i = parse_value(s, i)
        values.append(value)
        while i < len(s) and s[i].isspace():
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
            continue
        if i < len(s) and s[i] == ")":
            return values, i + 1
    raise ValueError("Unterminated tuple")


def table_columns_from_create(sql: str) -> list[str] | None:
    m = re.search(r"CREATE\s+TABLE\s+`?users`?\s*\((.*?)\)\s*ENGINE", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    cols: list[str] = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(',')
        cm = re.match(r"`([^`]+)`\s+", line)
        if cm:
            cols.append(cm.group(1))
    return cols or None


def extract_user_rows(sql: str) -> tuple[list[str], list[list[Any]]]:
    rows: list[list[Any]] = []
    columns: list[str] | None = None
    create_columns = table_columns_from_create(sql)

    pattern = re.compile(r"INSERT\s+INTO\s+`?users`?\s*(?:\((.*?)\))?\s*VALUES\s*", re.IGNORECASE | re.DOTALL)
    pos = 0
    while True:
        m = pattern.search(sql, pos)
        if not m:
            break
        raw_cols = m.group(1)
        if raw_cols:
            current_cols = [c.strip().strip("`").strip() for c in raw_cols.split(",")]
        else:
            if not create_columns:
                raise SystemExit("INSERT INTO users has no column list and CREATE TABLE users was not found.")
            current_cols = create_columns
        if columns is None:
            columns = current_cols
        elif columns != current_cols:
            raise SystemExit("Found INSERT blocks with different users column order; cannot safely import.")

        i = m.end()
        while i < len(sql):
            while i < len(sql) and sql[i].isspace():
                i += 1
            if i >= len(sql):
                break
            if sql[i] == "(":
                row, i = parse_tuple(sql, i)
                rows.append(row)
                while i < len(sql) and sql[i].isspace():
                    i += 1
                if i < len(sql) and sql[i] == ",":
                    i += 1
                    continue
                if i < len(sql) and sql[i] == ";":
                    i += 1
                    break
            elif sql[i] == ";":
                i += 1
                break
            else:
                break
        pos = i

    if columns is None:
        raise SystemExit("No INSERT INTO users VALUES block was found in input file.")
    return columns, rows


def build_postgres_sql(columns: list[str], rows: list[list[Any]]) -> str:
    idx = {name: n for n, name in enumerate(columns)}
    required = ["userid", "name", "username", "wallet", "date"]
    missing = [c for c in required if c not in idx]
    if missing:
        raise SystemExit(f"Required columns missing from users dump: {', '.join(missing)}")

    users: dict[int, dict[str, Any]] = {}
    for row in rows:
        if len(row) != len(columns):
            continue
        telegram_id = to_int(row[idx["userid"]], 0)
        if telegram_id <= 0:
            continue
        users[telegram_id] = {
            "telegram_id": telegram_id,
            "username": clean_username(row[idx["username"]]),
            "full_name": clean_name(row[idx["name"]]),
            "wallet": max(0, to_int(row[idx["wallet"]], 0)),
            "joined_ts": max(0, to_int(row[idx["date"]], 0)),
        }

    if not users:
        raise SystemExit("No valid Telegram users were found in the dump.")

    out = io.StringIO()
    out.write("BEGIN;\n")
    out.write("-- VPN Bot WizWiz users import. Generated by restore_wizwiz_mysql_users.py\n")
    out.write(f"-- Source rows: {len(rows)} | unique telegram_id: {len(users)}\n")
    out.write("INSERT INTO users (telegram_id, username, full_name, wallet_balance, wallet_v2ray_balance, wallet_openvpn_balance, accepted_rules, is_blocked, joined_at)\nVALUES\n")

    value_lines = []
    for u in sorted(users.values(), key=lambda x: x["telegram_id"]):
        joined = f"to_timestamp({u['joined_ts']})::timestamp" if u["joined_ts"] > 0 else "NOW()"
        wallet = int(u["wallet"])
        # Copy old WizWiz wallet into both main and V2Ray wallet so it is not lost.
        value_lines.append(
            f"({u['telegram_id']}, {sql_literal(u['username'])}, {sql_literal(u['full_name'])}, {wallet}, {wallet}, 0, TRUE, FALSE, {joined})"
        )
    out.write(",\n".join(value_lines))
    out.write("\nON CONFLICT (telegram_id) DO UPDATE SET\n")
    out.write("  username = COALESCE(EXCLUDED.username, users.username),\n")
    out.write("  full_name = COALESCE(EXCLUDED.full_name, users.full_name),\n")
    out.write("  wallet_balance = GREATEST(COALESCE(users.wallet_balance, 0), COALESCE(EXCLUDED.wallet_balance, 0)),\n")
    out.write("  wallet_v2ray_balance = GREATEST(COALESCE(users.wallet_v2ray_balance, 0), COALESCE(EXCLUDED.wallet_v2ray_balance, 0)),\n")
    out.write("  accepted_rules = TRUE,\n")
    out.write("  is_blocked = FALSE;\n")
    out.write("COMMIT;\n")
    out.write(f"SELECT COUNT(*) AS dbot_total_users_after_import FROM users;\n")
    return out.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert WizWiz MySQL users dump to VPN Bot PostgreSQL import SQL")
    ap.add_argument("input", help="WizWiz users .sql dump or .zip containing the dump")
    args = ap.parse_args()

    sql = read_input(Path(args.input))
    columns, rows = extract_user_rows(sql)
    sys.stderr.write(f"Found {len(rows)} WizWiz user rows in dump.\n")
    output = build_postgres_sql(columns, rows)
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
