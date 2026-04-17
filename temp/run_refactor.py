# -*- coding: utf-8 -*-
"""Refactor katie/app.py: tunes DB, no instrument, song→tune naming. Run: python run_refactor.py"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
p = ROOT / "app.py"
t = p.read_text(encoding="utf-8")

# --- DB ---
t = t.replace(
    '_APP_ROOT = Path(__file__).resolve().parent\nDB_PATH = str(_APP_ROOT / "songs.db")',
    """_APP_ROOT = Path(__file__).resolve().parent
_LEGACY_DB = _APP_ROOT / "songs.db"
DB_PATH = str(_APP_ROOT / "tunes.db")
if _LEGACY_DB.exists() and not Path(DB_PATH).exists():
    _LEGACY_DB.rename(Path(DB_PATH))""",
)

# --- Remove INSTRUMENTS + _instrument_from_request ---
t = t.replace('\nINSTRUMENTS = ["", "Banjo", "Guitar"]\n', "\n")
t = re.sub(
    r"\ndef _instrument_from_request\(\):.*?\n    return \(v or \"\"\)\.strip\(\)\n",
    "\n",
    t,
    count=1,
    flags=re.DOTALL,
)

# --- _ensure_set_* ---
old_ensure = re.search(
    r"def _ensure_set_songs_sort_order\(conn\):.*?^(?=def distinct_tune_types)",
    t,
    flags=re.MULTILINE | re.DOTALL,
)
if not old_ensure:
    raise SystemExit("_ensure_set_songs_sort_order not found")
new_ensure = '''def _ensure_set_tunes_sort_order(conn):
    """Add sort_order to set_tunes if missing; normalize 0..n-1 per set."""
    try:
        info = conn.execute("PRAGMA table_info(set_tunes)").fetchall()
    except sqlite3.OperationalError:
        return
    if not info:
        return
    cols = {r["name"] for r in info}
    if "sort_order" not in cols:
        try:
            conn.execute(
                "ALTER TABLE set_tunes ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
    for r in conn.execute("SELECT DISTINCT set_id FROM set_tunes"):
        set_id = r["set_id"]
        tune_rows = conn.execute(
            """
            SELECT tune_id FROM set_tunes
            WHERE set_id = ?
            ORDER BY sort_order ASC, tune_id ASC
            """,
            (set_id,),
        ).fetchall()
        for i, sr in enumerate(tune_rows):
            conn.execute(
                """
                UPDATE set_tunes SET sort_order = ?
                WHERE set_id = ? AND tune_id = ?
                """,
                (i, set_id, sr["tune_id"]),
            )


'''
t = t[: old_ensure.start()] + new_ensure + t[old_ensure.end() :]

# --- init_db ---
m = re.search(r"^def init_db\(\):.*?^        conn\.commit\(\)\n", t, flags=re.MULTILINE | re.DOTALL)
if not m:
    raise SystemExit("init_db not found")
new_init = r'''def _migrate_legacy_katie_schema(conn: sqlite3.Connection) -> None:
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "songs" in tabs and "tunes" not in tabs:
        conn.execute("ALTER TABLE songs RENAME TO tunes")
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "tunes" in tabs:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tunes)")]
        if "group_name" in cols:
            try:
                conn.execute("ALTER TABLE tunes DROP COLUMN group_name")
            except sqlite3.OperationalError:
                pass
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "practice_history" in tabs:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(practice_history)")]
        if "song_id" in cols and "tune_id" not in cols:
            try:
                conn.execute("ALTER TABLE practice_history RENAME COLUMN song_id TO tune_id")
            except sqlite3.OperationalError:
                pass
        conn.execute("DROP INDEX IF EXISTS idx_practice_history_song_id")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_practice_history_tune_id ON practice_history(tune_id)"
        )
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "set_songs" in tabs and "set_tunes" not in tabs:
        conn.execute("ALTER TABLE set_songs RENAME TO set_tunes")
    tabs = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "set_tunes" in tabs:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(set_tunes)")]
        if "song_id" in cols and "tune_id" not in cols:
            try:
                conn.execute("ALTER TABLE set_tunes RENAME COLUMN song_id TO tune_id")
            except sqlite3.OperationalError:
                pass


def init_db():
    with get_db() as conn:
        _migrate_legacy_katie_schema(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tunes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                tune_type TEXT,
                key TEXT,
                strumming TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS practice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tune_id INTEGER NOT NULL,
                date_played TEXT NOT NULL,
                FOREIGN KEY (tune_id) REFERENCES tunes(id) ON DELETE CASCADE
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_practice_history_tune_id "
            "ON practice_history(tune_id)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS set_tunes (
                set_id INTEGER NOT NULL,
                tune_id INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (set_id, tune_id),
                FOREIGN KEY (set_id) REFERENCES sets(id) ON DELETE CASCADE,
                FOREIGN KEY (tune_id) REFERENCES tunes(id) ON DELETE CASCADE
            )
        """)
        _ensure_set_tunes_sort_order(conn)
        for col in ("first_played", "last_played"):
            try:
                conn.execute(f"ALTER TABLE tunes DROP COLUMN {col}")
            except Exception:
                pass
        conn.execute("UPDATE tunes SET strumming = '' WHERE strumming IN ('None', 'none', 'NULL')")
        conn.execute("UPDATE tunes SET key = '' WHERE key IN ('None', 'none', 'NULL')")
        for col, defn in [
            ("capo", "INTEGER"),
            ("priority",    "TEXT"),
            ("learn_start", "TEXT"),
            ("learn_end",   "TEXT"),
            ("progress",    "INTEGER"),
            ("link_1",      "TEXT"),
            ("link_2",      "TEXT"),
            ("link_3",      "TEXT"),
            ("notes",       "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tunes ADD COLUMN {col} {defn}")
            except Exception:
                pass
        conn.execute(
            "UPDATE tunes SET tune_type = 'Barndance' WHERE tune_type = 'Barn Dance'"
        )
        conn.execute(
            "UPDATE tunes SET name = REPLACE(name, 'Barn Dance', 'Barndance') "
            "WHERE name LIKE '%Barn Dance%'"
        )
        try:
            conn.execute(
                "UPDATE sets SET type = 'Barndance' WHERE type = 'Barn Dance'"
            )
        except sqlite3.OperationalError:
            pass
        conn.commit()
'''
t = t[: m.start()] + new_init + t[m.end() :]

# --- HTTP routes: /song/ -> /tune/, /api/song -> /api/tune, set .../songs/ -> /tunes/ ---
t = t.replace('@app.route("/song/<int:song_id>/panel")', '@app.route("/tune/<int:tune_id>/panel")')
t = t.replace('@app.route("/practiced/<int:song_id>",', '@app.route("/practiced/<int:tune_id>",')
t = t.replace('@app.route("/api/song/<int:song_id>",', '@app.route("/api/tune/<int:tune_id>",')
t = t.replace('@app.route("/edit/<int:song_id>",', '@app.route("/edit/<int:tune_id>",')
t = t.replace('@app.route("/delete/<int:song_id>",', '@app.route("/delete/<int:tune_id>",')
t = t.replace("/set/<int:set_id>/songs/add", "/set/<int:set_id>/tunes/add")
t = t.replace("/set/<int:set_id>/songs/<int:song_id>/replace", "/set/<int:set_id>/tunes/<int:tune_id>/replace")
t = t.replace("/set/<int:set_id>/songs/<int:song_id>/remove", "/set/<int:set_id>/tunes/<int:tune_id>/remove")
t = t.replace("/set/<int:set_id>/songs/reorder", "/set/<int:set_id>/tunes/reorder")

# --- Function signatures ---
t = t.replace("def song_panel(song_id):", "def tune_panel(tune_id):")
t = t.replace("def edit_song(song_id):", "def edit_tune(tune_id):")
t = t.replace("def practiced_song(song_id):", "def practiced_tune(tune_id):")
t = t.replace("def update_song_field(song_id):", "def update_tune_field(tune_id):")
t = t.replace("def add_song_to_set(set_id):", "def add_tune_to_set(set_id):")
t = t.replace("def replace_song_in_set(set_id, song_id):", "def replace_tune_in_set(set_id, tune_id):")
t = t.replace("def remove_song_from_set(set_id, song_id):", "def remove_tune_from_set(set_id, tune_id):")
t = t.replace("def delete_song(song_id):", "def delete_tune(tune_id):")
t = t.replace("def reorder_set_songs(set_id):", "def reorder_set_tunes(set_id):")

t = t.replace("def add_song():", "def add_tune():")

# --- Templates ---
t = t.replace("song_form.html", "tune_form.html")
t = t.replace("song_panel.html", "tune_panel.html")

# --- url_for endpoints ---
for a, b in [
    ("add_song", "add_tune"),
    ("song_panel", "tune_panel"),
    ("edit_song", "edit_tune"),
    ("practiced_song", "practiced_tune"),
    ("delete_song", "delete_tune"),
]:
    t = re.sub(rf"url_for\(\s*['\"]{a}['\"]", f'url_for("{b}"', t)

# --- SQL tokens ---
for pat, repl in [
    (r"\bFROM songs\b", "FROM tunes"),
    (r"\bJOIN songs\b", "JOIN tunes"),
    (r"\bINTO songs\b", "INTO tunes"),
    (r"\bUPDATE songs\b", "UPDATE tunes"),
    (r"\bTABLE songs\b", "TABLE tunes"),
    (r"REFERENCES songs\(", "REFERENCES tunes("),
    (r"\bDELETE FROM songs\b", "DELETE FROM tunes"),
    (r"\bset_songs\b", "set_tunes"),
    (r"\bsong_id\b", "tune_id"),
]:
    t = re.sub(pat, repl, t)

t = t.replace("SONGS_WITH_STATS", "TUNES_WITH_STATS")
t = t.replace("idx_practice_history_song_id", "idx_practice_history_tune_id")

# --- Remove group_name from SQL DML (simple patterns) ---
t = t.replace(
    """INSERT INTO tunes
                   (name, group_name, tune_type, key, strumming,
                    capo, priority, learn_start, learn_end, progress, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    """INSERT INTO tunes
                   (name, tune_type, key, strumming,
                    capo, priority, learn_start, learn_end, progress, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
)
t = t.replace(
    """                (
                    name,
                    request.form.get("group_name", ""),
                    request.form.get("tune_type", ""),""",
    """                (
                    name,
                    request.form.get("tune_type", ""),""",
)

t = t.replace(
    """UPDATE tunes SET name=?, group_name=?, tune_type=?, key=?, strumming=?,
                          capo=?, priority=?, learn_start=?, learn_end=?, progress=?,
                          link_1=?, link_2=?, link_3=?, notes=?
                   WHERE id=?""",
    """UPDATE tunes SET name=?, tune_type=?, key=?, strumming=?,
                          capo=?, priority=?, learn_start=?, learn_end=?, progress=?,
                          link_1=?, link_2=?, link_3=?, notes=?
                   WHERE id=?""",
)
t = t.replace(
    """                (
                    name,
                    request.form.get("group_name", ""),
                    request.form.get("tune_type", ""),
                    request.form.get("key", ""),
                    request.form.get("strumming", "").strip(),
                    request.form.get("capo", "").strip() or None,
                    request.form.get("priority", ""),
                    request.form.get("learn_start", "") or None,
                    request.form.get("learn_end", "") or None,
                    request.form.get("progress", "").strip() or None,
                    _link_from_form("link_1"),
                    _link_from_form("link_2"),
                    _link_from_form("link_3"),
                    _notes_from_form(),
                    tune_id,
                )""",
    """                (
                    name,
                    request.form.get("tune_type", ""),
                    request.form.get("key", ""),
                    request.form.get("strumming", "").strip(),
                    request.form.get("capo", "").strip() or None,
                    request.form.get("priority", ""),
                    request.form.get("learn_start", "") or None,
                    request.form.get("learn_end", "") or None,
                    request.form.get("progress", "").strip() or None,
                    _link_from_form("link_1"),
                    _link_from_form("link_2"),
                    _link_from_form("link_3"),
                    _notes_from_form(),
                    tune_id,
                )""",
)

t = t.replace(
    'allowed = {"name", "group_name", "tune_type",',
    'allowed = {"name", "tune_type",',
)

# --- _soundslice ---
t = t.replace("def _soundslice_slice_ids_from_song(song_row):", "def _soundslice_slice_ids_from_tune(tune_row):")
t = t.replace("song_row[", "tune_row[")
t = t.replace("_soundslice_slice_ids_from_song(song)", "_soundslice_slice_ids_from_tune(tune)")

# --- User-visible strings ---
for a, b in [
    ("Song not found.", "Tune not found."),
    ("Song name is required.", "Tune name is required."),
    ("Invalid song.", "Invalid tune."),
    ("Invalid song ids.", "Invalid tune ids."),
    ("Duplicate song in order.", "Duplicate tune in order."),
]:
    t = t.replace(a, b)

# --- Remove instrument filtering & render kwargs ---
t = re.sub(r"\n    instrument = _instrument_from_request\(\)\n", "\n", t)
t = re.sub(r"\n    if instrument:\n        type_cond_parts\.insert\(0, \"s\.group_name = \?\"\)\n        type_params\.append\(instrument\)\n", "\n", t)
t = re.sub(r"\n        if instrument:\n            conditions\.append\(\"s\.group_name = \?\"\)\n            params\.append\(instrument\)\n", "\n", t)
t = re.sub(r",\s*instrument=instrument", "", t)
t = re.sub(r",\s*instruments=INSTRUMENTS", "", t)
t = re.sub(r"instruments=INSTRUMENTS,\s*", "", t)

# --- Statistics: replace _statistics_payload function ---
stats_m = re.search(
    r"^def _statistics_payload\(conn\):.*?^(?=@app\.route\(\"/statistics\"\))",
    t,
    flags=re.MULTILINE | re.DOTALL,
)
if not stats_m:
    raise SystemExit("_statistics_payload not found")
new_stats = '''def _statistics_payload(conn):
    """Build chart-ready series from practice_history (month buckets + tune type)."""
    from datetime import date

    bounds = conn.execute(
        "SELECT MIN(date_played) AS lo, MAX(date_played) AS hi FROM practice_history"
    ).fetchone()
    lo, hi = bounds["lo"], bounds["hi"]
    empty_series = {"labels": [], "values": []}
    if not lo or not hi:
        return {
            "has_data": False,
            "plays_by_month": empty_series,
            "unique_tunes_by_month": empty_series,
            "cumulative_completed": empty_series,
            "plays_by_month_by_type": {"labels": [], "datasets": []},
        }

    def _parse_iso(d):
        return date.fromisoformat(str(d)[:10])

    d0, d1 = _parse_iso(lo), _parse_iso(hi)
    start_m = date(d0.year, d0.month, 1)
    end_m = date(d1.year, d1.month, 1)

    ym_keys = []
    cy, cm = start_m.year, start_m.month
    ey, em = end_m.year, end_m.month
    while (cy, cm) <= (ey, em):
        ym_keys.append(f"{cy:04d}-{cm:02d}")
        cm += 1
        if cm > 12:
            cm, cy = 1, cy + 1

    plays_rows = conn.execute(
        """
        SELECT strftime('%Y-%m', date_played) AS ym, COUNT(*) AS c
        FROM practice_history
        GROUP BY ym
        """
    ).fetchall()
    uniq_rows = conn.execute(
        """
        SELECT strftime('%Y-%m', date_played) AS ym, COUNT(DISTINCT tune_id) AS c
        FROM practice_history
        GROUP BY ym
        """
    ).fetchall()
    plays_map = {r["ym"]: r["c"] for r in plays_rows}
    uniq_map = {r["ym"]: r["c"] for r in uniq_rows}

    month_labels = []
    for key in ym_keys:
        y, m = int(key[:4]), int(key[5:7])
        month_labels.append(date(y, m, 1).strftime("%b %Y"))

    type_rows = conn.execute(
        """
        SELECT strftime('%Y-%m', p.date_played) AS ym,
               COALESCE(NULLIF(TRIM(s.tune_type), ''), 'Other') AS tt,
               COUNT(*) AS c
        FROM practice_history p
        JOIN tunes s ON s.id = p.tune_id
        GROUP BY ym, tt
        ORDER BY ym, tt
        """
    ).fetchall()

    def _type_datasets(rows, ym_keys_local):
        totals: dict = {}
        tmap: dict = {}
        for r in rows:
            totals[r["tt"]] = totals.get(r["tt"], 0) + r["c"]
            tmap.setdefault(r["ym"], {})[r["tt"]] = r["c"]
        types_sorted = sorted(totals, key=lambda x: -totals[x])
        return [
            {"label": tt, "values": [tmap.get(k, {}).get(tt, 0) for k in ym_keys_local]}
            for tt in types_sorted
        ]

    datasets = _type_datasets(type_rows, ym_keys)

    completed_rows = conn.execute(
        """
        SELECT strftime('%Y-%m', learn_end) AS ym, COUNT(*) AS c
        FROM tunes
        WHERE TRIM(COALESCE(learn_end, '')) != ''
        GROUP BY ym
        ORDER BY ym
        """
    ).fetchall()

    cumulative_completed = empty_series
    if completed_rows:
        comp_map = {r["ym"]: r["c"] for r in completed_rows}
        cy2, cm2 = int(completed_rows[0]["ym"][:4]), int(completed_rows[0]["ym"][5:7])
        today2 = date.today()
        ey2, em2 = today2.year, today2.month
        comp_keys = []
        while (cy2, cm2) <= (ey2, em2):
            comp_keys.append(f"{cy2:04d}-{cm2:02d}")
            cm2 += 1
            if cm2 > 12:
                cm2, cy2 = 1, cy2 + 1
        comp_labels, comp_values, running = [], [], 0
        for key in comp_keys:
            y, m = int(key[:4]), int(key[5:7])
            comp_labels.append(date(y, m, 1).strftime("%b %Y"))
            running += comp_map.get(key, 0)
            comp_values.append(running)
        cumulative_completed = {"labels": comp_labels, "values": comp_values}

    return {
        "has_data": True,
        "plays_by_month": {
            "labels": month_labels,
            "values": [plays_map.get(k, 0) for k in ym_keys],
        },
        "unique_tunes_by_month": {
            "labels": month_labels,
            "values": [uniq_map.get(k, 0) for k in ym_keys],
        },
        "cumulative_completed": cumulative_completed,
        "plays_by_month_by_type": {
            "labels": month_labels,
            "datasets": datasets,
        },
    }

'''
t = t[: stats_m.start()] + new_stats + t[stats_m.end() :]

# --- set_panel: remove Banjo filter; rename vars for template ---
t = re.sub(
    r"banjo_songs_available = conn\.execute\(\n f\"\"\"\n            SELECT s\.id, s\.name\n            FROM tunes s\n            WHERE s\.group_name = 'Banjo'\n              AND s\.id NOT IN \(SELECT tune_id FROM set_tunes WHERE set_id = \?\)\n            ORDER BY \{SORT_NAME\} ASC\n            \"\"\",\n            \(set_id,\),\n        \)\.fetchall\(\)\n        banjo_all_rows = conn\.execute\(\n            f\"\"\"\n            SELECT s\.id, s\.name\n            FROM tunes s\n            WHERE s\.group_name = 'Banjo'\n            ORDER BY \{SORT_NAME\} ASC\n            \"\"\"\n        \)\.fetchall\(\)",
    '''tunes_available_for_set = conn.execute(
            f"""
            SELECT s.id, s.name
            FROM tunes s
            WHERE s.id NOT IN (SELECT tune_id FROM set_tunes WHERE set_id = ?)
            ORDER BY {SORT_NAME} ASC
            """,
            (set_id,),
        ).fetchall()
        all_tune_rows = conn.execute(
            f"""
            SELECT s.id, s.name
            FROM tunes s
            ORDER BY {SORT_NAME} ASC
            """
        ).fetchall()''',
    t,
    count=1,
    flags=re.DOTALL,
)
t = t.replace(
    "banjo_tune_picker_options = [\n        {\"id\": int(r[\"id\"]), \"name\": r[\"name\"]} for r in banjo_songs_available\n ]\n    banjo_all_for_picker = [\n        {\"id\": int(r[\"id\"]), \"name\": r[\"name\"]} for r in banjo_all_rows\n    ]",
    "tune_picker_add_options = [\n        {\"id\": int(r[\"id\"]), \"name\": r[\"name\"]} for r in tunes_available_for_set\n    ]\n    tune_picker_all = [\n        {\"id\": int(r[\"id\"]), \"name\": r[\"name\"]} for r in all_tune_rows\n    ]",
)
t = t.replace(
    '''banjo_picker_bundle = {
        "add": banjo_tune_picker_options,
        "allBanjo": banjo_all_for_picker,
        "setSongIds": set_tune_ids_json,
    }''',
    '''tune_picker_bundle = {
        "add": tune_picker_add_options,
        "allTunes": tune_picker_all,
        "setTuneIds": set_tune_ids_json,
    }''',
)
t = t.replace(
    """ banjo_songs_available=banjo_songs_available,
        banjo_tune_picker_options=banjo_tune_picker_options,
        banjo_picker_bundle=banjo_picker_bundle,""",
    """        tunes_available_for_set=tunes_available_for_set,
        tune_picker_add_options=tune_picker_add_options,
        tune_picker_bundle=tune_picker_bundle,""",
)

# add_tune_to_set / replace: remove Banjo checks
t = re.sub(
    r"        tune_row = conn\.execute\(\n            \"SELECT id, group_name FROM tunes WHERE id = \?\", \(tune_id,\)\n        \)\.fetchone\(\)\n        if not tune_row or \(tune_row\[\"group_name\"\] or \"\"\) != \"Banjo\":\n            if is_modal:\n                return jsonify\(\{\"ok\": False, \"error\": \"Invalid tune\.\"\}\), 400\n            flash\(\"Invalid tune\.\", \"error\"\)\n            return redirect\(url_for\(\"sets_view\"\)\)\n",
    "",
    t,
    count=1,
)
t = re.sub(
    r"        song = conn\.execute\(\n            \"SELECT id, group_name FROM tunes WHERE id = \?\", \(new_tune_id,\)\n        \)\.fetchone\(\)\n        if not song or \(song\[\"group_name\"\] or \"\"\) != \"Banjo\":\n            if is_modal:\n                return jsonify\(\{\"ok\": False, \"error\": \"Invalid tune\.\"\}\), 400\n            flash\(\"Invalid tune\.\", \"error\"\)\n            return redirect\(url_for\(\"sets_view\"\)\)\n",
    "",
    t,
    count=1,
)

# tune_panel / edit: song variable -> tune
t = t.replace("def tune_panel(tune_id):\n    with get_db() as conn:\n        song = conn.execute", "def tune_panel(tune_id):\n    with get_db() as conn:\n        tune = conn.execute")
t = t.replace("        if not song:\n            return \"Not found\", 404\n        stats = _practice_stats(conn, tune_id)\n    return render_template(\n        \"tune_panel.html\",\n        song=song,", "        if not tune:\n            return \"Not found\", 404\n        stats = _practice_stats(conn, tune_id)\n    return render_template(\n        \"tune_panel.html\",\n        tune=tune,")
t = t.replace("        soundslice_embeds=_soundslice_slice_ids_from_tune(tune),", "        soundslice_embeds=_soundslice_slice_ids_from_tune(tune),")

t = re.sub(
    r"def edit_tune\(tune_id\):.*?song = conn\.execute\(\"SELECT \* FROM tunes",
    "def edit_tune(tune_id):\n    is_modal = request.form.get(\"modal\") == \"1\"\n\n    with get_db() as conn:\n        tune = conn.execute(\"SELECT * FROM tunes",
    t,
    count=1,
    flags=re.DOTALL,
)
t = t.replace("        if not song:\n            flash(\"Tune not found.", "        if not tune:\n            flash(\"Tune not found.")
t = t.replace("                return render_template(\n                    \"tune_form.html\",\n                    song=song,", "                return render_template(\n                    \"tune_form.html\",\n                    tune=tune,")
t = t.replace("                    song[\"tune_type\"]", "                    tune[\"tune_type\"]")
t = t.replace("                    v = song[\"notes\"]", "                    v = tune[\"notes\"]")
t = t.replace("                    v = song[key]", "                    v = tune[key]")
t = t.replace("                    song_id,", "                    tune_id,")
t = t.replace(" stats = _practice_stats(conn, tune_id)\n\n    return render_template(\n        \"tune_form.html\",\n        song=song,", "        stats = _practice_stats(conn, tune_id)\n\n    return render_template(\n        \"tune_form.html\",\n        tune=tune,")
t = t.replace("        tune_type_suggestions=suggestions_merge(distinct_tune_types(), song[\"tune_type\"]),\n        key_suggestions=suggestions_merge(distinct_keys(), song[\"key\"]),", "        tune_type_suggestions=suggestions_merge(distinct_tune_types(), tune[\"tune_type\"]),\n        key_suggestions=suggestions_merge(distinct_keys(), tune[\"key\"]),")

# practiced_tune / delete_tune: use `row` for existence check
t = t.replace(
    "def practiced_tune(tune_id):\n    ts = practice_timestamp_now()\n    with get_db() as conn:\n        song = conn.execute(\"SELECT name FROM tunes WHERE id = ?\", (tune_id,)).fetchone()\n        if song:",
    "def practiced_tune(tune_id):\n    ts = practice_timestamp_now()\n    with get_db() as conn:\n        row = conn.execute(\"SELECT name FROM tunes WHERE id = ?\", (tune_id,)).fetchone()\n        if row:",
)
t = t.replace(
    "def delete_tune(tune_id):\n    is_modal = request.form.get(\"modal\") == \"1\"\n    if request.form.get(\"confirm_delete\") != \"1\":\n        if is_modal:\n            return jsonify({\"ok\": False, \"error\": \"Confirmation required.\"}), 400\n        flash(\"Action was not confirmed.\", \"error\")\n        return redirect(url_for(\"index\"))\n    with get_db() as conn:\n        tune = conn.execute(\"SELECT name FROM tunes WHERE id = ?\", (tune_id,)).fetchone()\n        if tune:\n            conn.execute(\"DELETE FROM tunes WHERE id = ?\", (tune_id,))",
    "def delete_tune(tune_id):\n    is_modal = request.form.get(\"modal\") == \"1\"\n    if request.form.get(\"confirm_delete\") != \"1\":\n        if is_modal:\n            return jsonify({\"ok\": False, \"error\": \"Confirmation required.\"}), 400\n        flash(\"Action was not confirmed.\", \"error\")\n        return redirect(url_for(\"index\"))\n    with get_db() as conn:\n        row = conn.execute(\"SELECT name FROM tunes WHERE id = ?\", (tune_id,)).fetchone()\n        if row:\n            conn.execute(\"DELETE FROM tunes WHERE id = ?\", (tune_id,))",
)

# history SELECT s.group_name - remove from query
t = t.replace(
    "SELECT p.id, p.date_played, s.id AS tune_id, s.name, s.group_name,\n                       s.tune_type, s.key,",
    "SELECT p.id, p.date_played, s.id AS tune_id, s.name,\n                       s.tune_type, s.key,",
)

# table_tune_key_suggestions parameter
t = t.replace("def table_tune_key_suggestions(songs_rows):", "def table_tune_key_suggestions(tunes_rows):")
t = t.replace("    for song in songs_rows:", "    for tune in tunes_rows:")
t = t.replace("        tt = (song[\"tune_type\"]", "        tt = (tune[\"tune_type\"]")
t = t.replace("        k = (song[\"key\"]", "        k = (tune[\"key\"]")

p.write_text(t, encoding="utf-8")
ast.parse(t)
print("OK:", p)
