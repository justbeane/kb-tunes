#!/usr/bin/env python3
"""
Summarize SQLite tables or print a sample of rows for one table.

  python table_summary.py                       # overview of all tables
  python table_summary.py tunes                 # sample rows from tunes
  python table_summary.py --table sets -n 5     # or use --table + row limit
  python table_summary.py tunes --search foo    # rows where any field contains 'foo'
  python table_summary.py tunes --id 42         # row with id=42

Use --db to point at another database file (default: songs.db next to the script root).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd


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


def _validate_table(conn: sqlite3.Connection, table: str) -> None:
    tables = set(list_user_tables(conn))
    if table not in tables:
        sys.stderr.write(
            f"Unknown table {table!r}. Tables: {', '.join(sorted(tables))}\n"
        )
        sys.exit(1)


def _print_df(df: pd.DataFrame, max_cell_len: int) -> None:
    def shorten(v: object) -> str:
        if v is None:
            return ""
        s = str(v)
        return s[: max_cell_len - 1] + "…" if len(s) > max_cell_len else s

    display_df = df.map(shorten)
    with pd.option_context(
        "display.max_rows", None,
        "display.max_columns", None,
        "display.width", None,
        "display.max_colwidth", max_cell_len,
    ):
        print(display_df.to_string(index=False))


def preview_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    limit: int,
    max_cell_len: int,
) -> None:
    _validate_table(conn, table)

    df = pd.read_sql_query(f'SELECT * FROM "{table}" LIMIT ?', conn, params=(limit,))
    if df.empty:
        print(f"(no rows in {table})")
        return

    print(f"{table}  ({len(df)} row{'s' if len(df) != 1 else ''} shown)")
    _print_df(df, max_cell_len)


def search_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    substring: str | None = None,
    row_id: int | None = None,
    limit: int,
    max_cell_len: int,
) -> None:
    _validate_table(conn, table)

    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    col_names = [c["name"] if isinstance(c, sqlite3.Row) else c[1] for c in cols]

    if row_id is not None:
        id_col = col_names[0]
        df = pd.read_sql_query(
            f'SELECT * FROM "{table}" WHERE "{id_col}" = ?',
            conn,
            params=(row_id,),
        )
    elif substring is not None:
        like_clauses = " OR ".join(
            f'CAST("{c}" AS TEXT) LIKE ?' for c in col_names
        )
        params = [f"%{substring}%"] * len(col_names) + [limit]
        df = pd.read_sql_query(
            f'SELECT * FROM "{table}" WHERE {like_clauses} LIMIT ?',
            conn,
            params=params,
        )
    else:
        sys.stderr.write("search_table: provide substring or row_id.\n")
        sys.exit(2)

    if df.empty:
        print("(no matching rows)")
        return

    print(f"{len(df)} matching row{'s' if len(df) != 1 else ''}:")
    _print_df(df, max_cell_len)


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
    p.add_argument(
        "--search",
        metavar="TEXT",
        default=None,
        help="Return rows where any field contains TEXT as a substring.",
    )
    p.add_argument(
        "--id",
        type=int,
        default=None,
        metavar="ID",
        help="Return the row whose first column equals ID.",
    )
    args = p.parse_args()

    table_name = args.table_opt or args.table
    if args.table_opt and args.table and args.table_opt.strip() != args.table.strip():
        sys.stderr.write(
            "Conflicting table names: positional and --table must match.\n"
        )
        sys.exit(2)

    if (args.search is not None or args.id is not None) and not table_name:
        sys.stderr.write("--search and --id require a table name.\n")
        sys.exit(2)

    db_path = args.db if args.db is not None else default_db_path()

    with _connect(db_path) as conn:
        if table_name and (args.search is not None or args.id is not None):
            search_table(
                conn,
                table_name.strip(),
                substring=args.search,
                row_id=args.id,
                limit=max(1, args.limit),
                max_cell_len=max(8, args.max_cell),
            )
        elif table_name:
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
