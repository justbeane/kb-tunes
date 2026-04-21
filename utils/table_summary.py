#!/usr/bin/env python3
"""
Summarize SQLite tables or print a sample of rows for one table.

  python table_summary.py                       # overview of all tables
  python table_summary.py tunes                 # sample rows from tunes
  python table_summary.py --table sets -n 5     # or use --table + row limit

Use --db to point at another database file (default: tunes.db next to the katie app).
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
    return _repo_root() / "tunes.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        sys.stderr.write(f"Database not found: {db_path}\n")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    return [str(r["name"]) if isinstance(r, sqlite3.Row) else r[0] for r in rows]


def summarize(conn: sqlite3.Connection) -> None:
    tables = list_user_tables(conn)
    if not tables:
        print("(no user tables)")
        return

    for name in tables:
        n = conn.execute(
            f'SELECT COUNT(*) AS c FROM "{name}"'
        ).fetchone()
        count = n["c"] if isinstance(n, sqlite3.Row) else n[0]
        cols = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        col_names = [
            c["name"] if isinstance(c, sqlite3.Row) else c[1] for c in cols
        ]
        types = [
            (c["type"] if isinstance(c, sqlite3.Row) else c[2]) or "" for c in cols
        ]
        print(f"\n{name}  ({count} row{'s' if count != 1 else ''})")
        print("  columns:")
        for cn, ct in zip(col_names, types):
            t = f" {ct}" if ct else ""
            print(f"    - {cn}{t}")


def preview_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    limit: int,
    max_cell_len: int,
) -> None:
    tables = set(list_user_tables(conn))
    if table not in tables:
        sys.stderr.write(
            f"Unknown table {table!r}. Tables: {', '.join(sorted(tables))}\n"
        )
        sys.exit(1)

    rows = conn.execute(
        f'SELECT * FROM "{table}" LIMIT ?',
        (limit,),
    ).fetchall()
    if not rows:
        print(f"(no rows in {table})")
        return

    keys = list(rows[0].keys())

    def shorten(v: object) -> str:
        if v is None:
            return ""
        s = str(v)
        if len(s) > max_cell_len:
            return s[: max_cell_len - 1] + "…"
        return s

    out = sys.stdout
    w = csv.writer(out, lineterminator="\n")
    w.writerow(keys)
    for r in rows:
        w.writerow([shorten(r[k]) for k in keys])


def main() -> None:
    p = argparse.ArgumentParser(
        description="Summarize tunes.db tables or print sample rows."
    )
    p.add_argument(
        "table",
        nargs="?",
        help="Table name: print up to LIMIT rows as CSV (omit for summary).",
    )
    p.add_argument(
        "--table",
        dest="table_opt",
        metavar="NAME",
        default=None,
        help="Same as positional table name (if both given, must match).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"SQLite file (default: {default_db_path()})",
    )
    p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Max rows when showing a table (default: 50).",
    )
    p.add_argument(
        "--max-cell",
        type=int,
        default=120,
        metavar="LEN",
        help="Truncate cell text longer than this (default: 120).",
    )
    args = p.parse_args()

    table_name = args.table_opt or args.table
    if args.table_opt and args.table and args.table_opt.strip() != args.table.strip():
        sys.stderr.write(
            "Conflicting table names: positional and --table must match.\n"
        )
        sys.exit(2)

    db_path = args.db if args.db is not None else default_db_path()

    with _connect(db_path) as conn:
        if table_name:
            preview_table(
                conn,
                table_name.strip(),
                limit=max(1, args.limit),
                max_cell_len=max(8, args.max_cell),
            )
        else:
            print(f"Database: {db_path.resolve()}")
            summarize(conn)


if __name__ == "__main__":
    main()
