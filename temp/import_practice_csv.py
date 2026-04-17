# -*- coding: utf-8 -*-
"""Import practice log CSV from temp_data into tunes + practice_history."""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_LEGACY_DB = ROOT / "songs.db"
DB_PATH = ROOT / "tunes.db"
if _LEGACY_DB.exists() and not DB_PATH.exists():
    _LEGACY_DB.rename(DB_PATH)


def find_csv() -> Path:
    td = ROOT / "temp_data"
    if not td.is_dir():
        raise SystemExit(f"Missing {td}")
    names = sorted(td.glob("*.csv"))
    if not names:
        raise SystemExit("No .csv files in temp_data")
    for p in names:
        if "Practice Database" in p.name:
            return p
    return names[0]


def extract_name(field: str) -> str:
    field = field.strip().replace("\n", " ")
    return re.sub(r"\s*\(https?://[^)]+\)\s*$", "", field).strip()


def parse_practiced_at(field: str) -> str | None:
    field = field.strip()
    if not field:
        return None
    field = re.sub(r"\s*\([A-Z]{2,4}\)\s*$", "", field).strip()
    for fmt in ("%B %d, %Y %I:%M %p", "%B %d, %Y"):
        try:
            dt = datetime.strptime(field, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def get_or_create_tune_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM tunes WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO tunes (name) VALUES (?)",
        (name,),
    )
    return int(cur.lastrowid)


def wipe(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        DELETE FROM practice_history;
        DELETE FROM set_practice;
        DELETE FROM set_tunes;
        DELETE FROM sets;
        DELETE FROM tunes;
        PRAGMA foreign_keys = ON;
        """
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--wipe",
        action="store_true",
        help="Remove all tunes, sets, and practice rows before import",
    )
    args = ap.parse_args()

    csv_path = find_csv()
    sys.path.insert(0, str(ROOT))
    import app as _app  # noqa: F401, E402  # triggers init_db

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if args.wipe:
        wipe(conn)
        conn.commit()

    inserted = 0
    skipped = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tunes_raw = (row.get("Tunes") or "").strip()
            name = extract_name(tunes_raw)
            if not name:
                name = extract_name((row.get("Name") or "").strip())
            dt_s = parse_practiced_at((row.get("Date Practiced") or "").strip())
            if not name or not dt_s:
                skipped += 1
                continue
            tid = get_or_create_tune_id(conn, name)
            conn.execute(
                "INSERT INTO practice_history (tune_id, date_played) VALUES (?, ?)",
                (tid, dt_s),
            )
            inserted += 1

    conn.commit()
    total_tunes = conn.execute("SELECT COUNT(*) AS c FROM tunes").fetchone()["c"]
    conn.close()

    print(f"CSV: {csv_path.name}")
    print(f"Practice rows inserted: {inserted}")
    print(f"Rows skipped: {skipped}")
    print(f"Tunes in database: {total_tunes}")


if __name__ == "__main__":
    main()
