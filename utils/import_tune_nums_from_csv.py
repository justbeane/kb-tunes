#!/usr/bin/env python3
"""
Set tunes.tune_num from temp/tunes.csv only (Name -> Tune No.).

Updates no other columns. Rows with a missing or invalid Tune No. are skipped.
Run from repo root:  python utils/import_tune_nums_from_csv.py
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = _ROOT / "temp" / "tunes.csv"
DEFAULT_DB = _ROOT / "tunes.db"
NAME_COL = "Name"
TUNE_NUM_COL = "Tune No."


def _parse_tune_num(value: object) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except (ValueError, TypeError, OverflowError):
            return None


def main() -> None:
    csv_path = DEFAULT_CSV
    db_path = DEFAULT_DB
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        db_path = Path(sys.argv[2])

    if not csv_path.is_file():
        sys.stderr.write(f"CSV not found: {csv_path}\n")
        sys.exit(1)
    if not db_path.is_file():
        sys.stderr.write(f"Database not found: {db_path}\n")
        sys.exit(1)

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("CSV has no data rows.")
        return

    if NAME_COL not in rows[0] or TUNE_NUM_COL not in rows[0]:
        sys.stderr.write(
            f"CSV must include {NAME_COL!r} and {TUNE_NUM_COL!r} columns.\n"
            f"Found: {list(rows[0].keys())}\n"
        )
        sys.exit(1)

    updates: list[tuple[int, str]] = []
    skipped_no_num = 0
    for r in rows:
        name = (r.get(NAME_COL) or "").strip()
        if not name:
            continue
        num = _parse_tune_num(r.get(TUNE_NUM_COL))
        if num is None:
            skipped_no_num += 1
            continue
        updates.append((num, name))

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        total_rowcount = 0
        not_found: list[str] = []
        for num, name in updates:
            cur = conn.execute(
                "UPDATE tunes SET tune_num = ? WHERE name = ?",
                (num, name),
            )
            n = cur.rowcount
            total_rowcount += n
            if n == 0:
                not_found.append(name)
        conn.commit()
    finally:
        conn.close()

    print(f"CSV rows read: {len(rows)}")
    print(f"Candidates with a Tune No.: {len(updates)}")
    print(f"Rows skipped (empty/invalid Tune No.): {skipped_no_num}")
    print(f"UPDATE statements applied (sum of rowcounts): {total_rowcount}")
    if not_found:
        uniq = sorted(set(not_found))
        print(f"Names in CSV with no matching tune row ({len(uniq)}):")
        for nm in uniq[:50]:
            print(f"  - {nm}")
        if len(uniq) > 50:
            print(f"  ... and {len(uniq) - 50} more")


if __name__ == "__main__":
    main()
