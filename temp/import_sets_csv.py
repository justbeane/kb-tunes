# -*- coding: utf-8 -*-
"""Import sets from sets.csv into sets + set_tunes (tune names matched to tunes.db)."""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from difflib import get_close_matches
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_LEGACY_DB = ROOT / "songs.db"
DB_PATH = ROOT / "tunes.db"
if _LEGACY_DB.exists() and not DB_PATH.exists():
    _LEGACY_DB.rename(DB_PATH)

_URL_TAIL = re.compile(r"\s*\(https?://[^\)]*\)?", re.IGNORECASE)


def normalize_key(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "")
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return s


def variants_for_match(name: str) -> list[str]:
    n = normalize_key(name)
    if not n:
        return []
    out = [n]
    if n.startswith("the "):
        out.append(n[4:].strip())
    else:
        out.append("the " + n)
    stripped = re.sub(r"\s*\([^)]+\)\s*$", "", name)
    sn = normalize_key(stripped)
    if sn and sn not in out:
        out.append(sn)
        if sn.startswith("the "):
            out.append(sn[4:].strip())
        else:
            out.append("the " + sn)
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def split_tunes_cell(cell: str) -> list[str]:
    if not cell or not str(cell).strip():
        return []
    raw = str(cell).strip()
    chunks = re.split(r"\)\s*,\s*", raw)
    names: list[str] = []
    for ch in chunks:
        ch = ch.strip()
        if not ch:
            continue
        label = _URL_TAIL.sub("", ch).strip()
        label = re.sub(r"\s+", " ", label)
        if label:
            names.append(label)
    return names


def build_tune_index(conn: sqlite3.Connection) -> tuple[dict[str, list[int]], list[str]]:
    by_key: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, name FROM tunes"):
        tid = int(r["id"])
        nm = (r["name"] or "").strip()
        for v in variants_for_match(nm):
            by_key.setdefault(v, []).append(tid)
    return by_key, list(by_key.keys())


def resolve_tune_id(
    conn: sqlite3.Connection,
    by_key: dict[str, list[int]],
    all_keys: list[str],
    label: str,
) -> tuple[int | None, str]:
    for v in variants_for_match(label):
        ids = by_key.get(v)
        if ids:
            return ids[0], "exact_norm"
    row = conn.execute(
        "SELECT id FROM tunes WHERE name = ? COLLATE NOCASE LIMIT 1",
        (label.strip(),),
    ).fetchone()
    if row:
        return int(row["id"]), "sql_nocase"
    row = conn.execute(
        """
        SELECT id, name FROM tunes
        WHERE ? LIKE name || '%' COLLATE NOCASE
        ORDER BY LENGTH(name) DESC
        LIMIT 1
        """,
        (label.strip(),),
    ).fetchone()
    if row and len(str(row["name"])) >= 4:
        return int(row["id"]), "prefix_db"
    row = conn.execute(
        """
        SELECT id, name FROM tunes
        WHERE name LIKE ? COLLATE NOCASE
        ORDER BY LENGTH(name) DESC
        LIMIT 1
        """,
        (label.strip() + "%",),
    ).fetchone()
    if row and len(label.strip()) >= 4:
        return int(row["id"]), "prefix_csv"
    nk = normalize_key(label)
    if len(nk) >= 4:
        hits = get_close_matches(nk, all_keys, n=1, cutoff=0.82)
        if hits:
            ids = by_key[hits[0]]
            return ids[0], f"fuzzy({hits[0]})"
    return None, "unmatched"


def clear_sets(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        DELETE FROM set_tunes;
        DELETE FROM sets;
        PRAGMA foreign_keys = ON;
        """
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "sets.csv",
        help="Path to sets CSV (default: ./sets.csv)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; do not modify the database",
    )
    args = ap.parse_args()
    csv_path: Path = args.csv
    if not csv_path.is_file():
        raise SystemExit(f"Missing CSV: {csv_path}")

    sys.path.insert(0, str(ROOT))
    import app as _app  # noqa: F401, E402

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    by_key, all_keys = build_tune_index(conn)
    unmatched: list[tuple[str, str, str]] = []  # set_name, tune_label, set_type

    sets_inserted = 0
    links_inserted = 0

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not args.dry_run:
        clear_sets(conn)

    for row in rows:
        set_name = (row.get("Name") or "").strip()
        set_type = (row.get("Tune Type") or "").strip()
        tunes_cell = row.get("Tunes") or ""
        if not set_name:
            continue
        tune_labels = split_tunes_cell(tunes_cell)
        if not tune_labels:
            print(f"SKIP set (no tunes parsed): {set_name[:60]!r}", file=sys.stderr)
            continue

        matched_ids: list[int] = []
        for lab in tune_labels:
            tid, _ = resolve_tune_id(conn, by_key, all_keys, lab)
            if tid is None:
                unmatched.append((set_name, lab, set_type))
                matched_ids.append(-1)
            else:
                matched_ids.append(tid)

        ok_ids = [x for x in matched_ids if x != -1]
        if args.dry_run:
            print(
                f"Would insert set: {set_name!r} type={set_type!r} "
                f"tunes={len(ok_ids)}/{len(tune_labels)}"
            )
            sets_inserted += 1
            links_inserted += len(ok_ids)
            continue

        cur = conn.execute(
            "INSERT INTO sets (description, type) VALUES (?, ?)",
            (set_name, set_type),
        )
        set_id = int(cur.lastrowid)
        sets_inserted += 1
        seen_tid: set[int] = set()
        order = 0
        for tid in matched_ids:
            if tid == -1 or tid in seen_tid:
                continue
            seen_tid.add(tid)
            conn.execute(
                "INSERT INTO set_tunes (set_id, tune_id, sort_order) VALUES (?, ?, ?)",
                (set_id, tid, order),
            )
            order += 1
            links_inserted += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"Sets: {sets_inserted}, tune links: {links_inserted}")
    if unmatched:
        print(f"\nUnmatched tune labels ({len(unmatched)}):", file=sys.stderr)
        for set_name, lab, st in unmatched:
            print(f"  {lab!r} (set: {set_name[:50]!r}… type {st!r})", file=sys.stderr)


if __name__ == "__main__":
    main()
