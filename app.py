import calendar
import hashlib
import json
import math
import sys
import mimetypes
import random
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

app = Flask(__name__)
app.secret_key = "katie-music-practice-key"
mimetypes.add_type("application/manifest+json", ".webmanifest")


@app.after_request
def _no_cache_html_responses(response):
    """Avoid stale main views after form redirects (POST/PRG) or back/forward navigation."""
    ct = response.headers.get("Content-Type", "")
    if ct.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

_APP_ROOT = Path(__file__).resolve().parent
# WSGI often loads this module as e.g. kb_tunes.app; ensure sibling modules resolve.
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
LESSON_TUNES_DIR = _APP_ROOT / "lesson_tunes"
_LEGACY_DB = _APP_ROOT / "songs.db"
DB_PATH = str(_APP_ROOT / "tunes.db")
if _LEGACY_DB.exists() and not Path(DB_PATH).exists():
    _LEGACY_DB.rename(Path(DB_PATH))
SETTINGS_PATH = str(_APP_ROOT / "settings.json")
BACKUPS_DIR = _APP_ROOT / "__local__" / "backups"

_MP_STATIC_CACHE_NAMES = (
    "style.css",
    "mp_suggest.js",
    "mp_practice_groups.js",
    "mp_key_multiselect.js",
    "mp_custom_select.js",
    "mp_refresh_page.js",
    "mp_lesson_tunes_table.js",
)


def _mp_static_asset_version() -> str:
    m = 0
    for n in _MP_STATIC_CACHE_NAMES:
        try:
            p = _APP_ROOT / "static" / n
            m = max(m, int(p.stat().st_mtime))
        except OSError:
            pass
    return str(m) if m else "0"

# IANA zone for all timestamps persisted in SQLite (wall time, DST-aware).
DB_TIMEZONE = ZoneInfo("America/Chicago")

# Days since this date (calendar date in US Central) seed the daily header phrase selection.
HEADER_PHRASE_EPOCH = date(2020, 1, 1)

# Fixed pool when settings["phrase_subset_override_enabled"] is true (header90% branch).
HEADER_PHRASE_OVERRIDE_POOL = (
    "Fiddle me this...",
    "The jig is up.",
    "You'll polka your eye out.",
    "Keeping it reel.",
    "Britches get stiches.",
)

VALID_PHRASE_VARIETIES = frozenset({"low", "medium", "high", "all"})
PHRASE_VARIETY_POOL_CAP = {"low": 5, "medium": 10, "high": 20}
VALID_PHRASE_FREQUENCY_SEC = frozenset({1, 30, 60})


def practice_timestamp_now() -> str:
    """US Central wall time for new practice rows (date + time, SQLite-friendly)."""
    return datetime.now(DB_TIMEZONE).replace(microsecond=0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def central_date_today() -> date:
    """Current calendar date in US Central."""
    return datetime.now(DB_TIMEZONE).date()


def _central_now_minute() -> datetime:
    """Naive Central wall clock truncated to the minute (refresh windows, stats)."""
    return datetime.now(DB_TIMEZONE).replace(
        second=0, microsecond=0, tzinfo=None
    )


def _julianday_anchor_sql() -> str:
    """Central 'now' as YYYY-MM-DD HH:MM:SS for SQLite julianday(?)."""
    return datetime.now(DB_TIMEZONE).replace(microsecond=0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def normalize_practice_datetime(value: str) -> str | None:
    """Normalize date / datetime-local / 'YYYY-MM-DD HH:MM:SS' for storage (Central)."""
    if not value or not str(value).strip():
        return None
    v = str(value).strip()
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return f"{v} 00:00:00"
    if "T" in v:
        v = v.replace("T", " ", 1)
    if "." in v:
        v = v.split(".")[0]
    parts = v.split()
    if len(parts) != 2:
        return None
    d, t = parts[0], parts[1]
    seg = t.split(":")
    if len(seg) == 2:
        t = f"{int(seg[0]):02d}:{int(seg[1]):02d}:00"
    elif len(seg) == 3:
        t = f"{int(seg[0]):02d}:{int(seg[1]):02d}:{int(seg[2]):02d}"
    else:
        return None
    return f"{d} {t}"


SETTINGS_DEFAULTS: dict = {
    "card_dividers": True,
    "mark_played_today": False,
    "bold_card_titles": False,
    "type_bubbles": True,
    "stats_layout": [],
    "phrase_subset_override_enabled": False,
    "phrase_variety": "medium",
    "phrase_frequency_sec": 1,
}


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    settings = dict(SETTINGS_DEFAULTS)
    for key, default in SETTINGS_DEFAULTS.items():
        v = data.get(key)
        if isinstance(v, type(default)):
            settings[key] = v
    if settings.get("phrase_variety") not in VALID_PHRASE_VARIETIES:
        settings["phrase_variety"] = SETTINGS_DEFAULTS["phrase_variety"]
    if settings.get("phrase_frequency_sec") not in VALID_PHRASE_FREQUENCY_SEC:
        settings["phrase_frequency_sec"] = SETTINGS_DEFAULTS["phrase_frequency_sec"]
    return settings


def save_settings(settings: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


from theming import (  # noqa: E402
    THEME_EDITOR_GROUPS,
    THEME_EDITOR_KEYS,
    THEME_EDITOR_ROWS,
    THEME_FALLBACK_ID,
    THEME_PRESETS,
    _normalize_theme_variables_dict,
    _variables_from_post_form,
    complete_theme_variables,
    delete_theme_in_file,
    load_themes_data,
    save_themes_data,
    theme_editor_page_state,
    theme_runtime_for_client,
    themes_list_for_client,
    upsert_theme_in_file,
)


def _mp_manifest_bust() -> str:
    s = load_settings()
    tr = theme_runtime_for_client()
    raw = f"{s.get('phrase_variety', '')!s}\0{tr.get('active_id', '')!s}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# Default / suggested labels (combobox + sort order). Custom labels are also allowed.
MAX_PRACTICE_GROUP_LABEL_LEN = 120
PRACTICE_GROUPS = (
    "Favorites",
    "Top 50",
    "Next 50",
    "Needs Practice",
    "New",
    "Stretch Tune",
    "Easy/Popular",
    "Slow Tunes",
)
PRACTICE_GROUP_SET = frozenset(PRACTICE_GROUPS)
_PRACTICE_GROUP_ALIASES = {
    "stretch tunes": "Stretch Tune",
}


def map_practice_group_token(token: str) -> str | None:
    """Map one CSV/UI token to a stored label (preset canonical name or custom text)."""
    t = (token or "").strip()
    if not t:
        return None
    if len(t) > MAX_PRACTICE_GROUP_LABEL_LEN:
        t = t[:MAX_PRACTICE_GROUP_LABEL_LEN].rstrip()
        if not t:
            return None
    if t in PRACTICE_GROUP_SET:
        return t
    low = t.lower()
    if low in _PRACTICE_GROUP_ALIASES:
        return _PRACTICE_GROUP_ALIASES[low]
    for g in PRACTICE_GROUPS:
        if g.lower() == low:
            return g
    return t


def normalize_practice_groups_stored(raw: str | None) -> str:
    """Normalize: unique labels (case-insensitive), presets first in fixed order, then custom A–Z."""
    if not raw or not str(raw).strip():
        return ""
    parts = re.split(r"\s*,\s*", str(raw).strip())
    preset_order = {g: i for i, g in enumerate(PRACTICE_GROUPS)}
    labels: list[str] = []
    seen_lower: set[str] = set()
    for p in parts:
        m = map_practice_group_token(p)
        if not m:
            continue
        low = m.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        labels.append(m)

    def sort_key(g: str) -> tuple:
        if g in preset_order:
            return (0, preset_order[g])
        return (1, g.lower())

    labels.sort(key=sort_key)
    return ", ".join(labels)


def format_practice_groups_from_list(labels: list[str]) -> str:
    """Normalize selected labels from forms or API (list of strings)."""
    parts = [p for p in (str(x).strip() for x in labels) if p]
    if not parts:
        return ""
    return normalize_practice_groups_stored(", ".join(parts))


def _practice_groups_from_request_form() -> str:
    return format_practice_groups_from_list(request.form.getlist("practice_group"))


# Keys: comma-separated in DB (like practice_group), multiple picks in the tune/set forms.
MAX_KEY_TOKEN_LEN = 40


def normalize_keys_stored(raw: str | None) -> str:
    """Unique keys (case-insensitive), sorted A–Z, stored as comma-separated."""
    if not raw or not str(raw).strip():
        return ""
    parts = re.split(r"\s*,\s*", str(raw).strip())
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        t = p.strip()
        if len(t) > MAX_KEY_TOKEN_LEN:
            t = t[:MAX_KEY_TOKEN_LEN].rstrip()
        if not t:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
    out.sort(key=str.lower)
    return ", ".join(out)


def format_keys_from_list(labels: list[str]) -> str:
    parts = [p for p in (str(x).strip() for x in labels) if p]
    if not parts:
        return ""
    return normalize_keys_stored(", ".join(parts))


def _keys_from_request_form() -> str:
    return format_keys_from_list([str(x).strip() for x in request.form.getlist("key")])


def _set_types_from_request_form() -> str:
    """Set type tokens; stored like keys (comma-separated, normalized)."""
    return format_keys_from_list([str(x).strip() for x in request.form.getlist("type")])


def suggestions_merge_keys(base: list, *raw_key_fields: str | None) -> list[str]:
    seen = {str(x).strip() for x in base if x and str(x).strip()}
    for ev in raw_key_fields:
        if ev is None:
            continue
        s = str(ev).strip()
        if not s:
            continue
        for part in re.split(r"\s*,\s*", s):
            p = part.strip()
            if p:
                seen.add(p)
    return sorted(seen, key=str.lower)


@app.template_filter("keys_selected")
def keys_selected_filter(stored):
    s = normalize_keys_stored(stored or "")
    if not s:
        return []
    return [p.strip() for p in re.split(r"\s*,\s*", s) if p.strip()]


@app.template_filter("practice_groups_selected")
def practice_groups_selected_filter(stored):
    s = normalize_practice_groups_stored(stored or "")
    return s.split(", ") if s else []


# Lesson file names: one per line in storage (TEXT).
MAX_LESSON_ENTRY_LEN = 260


def normalize_lessons_stored(raw: str | None) -> str:
    """Trim, one entry per line, dedupe case-insensitively, preserve first-seen casing."""
    if raw is None:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for line in str(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s:
            continue
        if len(s) > MAX_LESSON_ENTRY_LEN:
            s = s[:MAX_LESSON_ENTRY_LEN].rstrip()
            if not s:
                continue
        low = s.lower()
        if low in seen:
            continue
        seen.add(low)
        lines.append(s)
    return "\n".join(lines)


@app.template_filter("lessons_list")
def lessons_list_filter(stored):
    if not stored:
        return []
    return [ln.strip() for ln in str(stored).split("\n") if ln.strip()]


def _lessons_from_request_form() -> str:
    return normalize_lessons_stored(request.form.get("lessons", ""))


def _next_tune_num(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(tune_num) AS m FROM tunes").fetchone()
    if not row or row["m"] is None:
        return 1
    return int(row["m"]) + 1


def _tune_num_from_add_form(conn: sqlite3.Connection) -> int | None:
    raw = (request.form.get("tune_num") or "").strip()
    if not raw:
        return _next_tune_num(conn)
    try:
        n = int(raw, 10)
        if n < 1:
            return _next_tune_num(conn)
        return n
    except ValueError:
        return _next_tune_num(conn)


def _parse_tune_num_update(raw: object) -> tuple[int | None, str | None]:
    """Parse tune_num when editing. Returns (value, error_message). None = clear in DB."""
    s = raw.strip() if isinstance(raw, str) else str(raw).strip()
    if not s:
        return None, None
    try:
        n = int(s, 10)
    except ValueError:
        return None, "Tune No. must be a whole number."
    if n < 1:
        return None, "Tune No. must be at least 1."
    return n, None


def _add_tune_form_repopulate() -> dict:
    return {
        "name": request.form.get("name", "") or "",
        "tune_num": (request.form.get("tune_num") or "").strip(),
        "tune_type": request.form.get("tune_type", "") or "",
        "key_list": request.form.getlist("key"),
        "composer": request.form.get("composer", "") or "",
        "notes": request.form.get("notes", "") or "",
        "link_1": (request.form.get("link_1", "") or "").strip(),
        "link_2": (request.form.get("link_2", "") or "").strip(),
        "link_3": (request.form.get("link_3", "") or "").strip(),
        "practice_groups": request.form.getlist("practice_group"),
    }


def distinct_practice_groups_from_db(conn: sqlite3.Connection) -> list[str]:
    """Sorted unique labels that appear on at least one tune (presets first, then custom A–Z)."""
    rows = conn.execute(
        "SELECT practice_group FROM tunes "
        "WHERE practice_group IS NOT NULL AND TRIM(COALESCE(practice_group, '')) != ''"
    ).fetchall()
    seen: set[str] = set()
    labels: list[str] = []
    for r in rows:
        for g in practice_groups_selected_filter(r["practice_group"]):
            low = g.lower()
            if low in seen:
                continue
            seen.add(low)
            labels.append(g)
    preset_order = {g: i for i, g in enumerate(PRACTICE_GROUPS)}

    def sort_key(g: str) -> tuple:
        if g in preset_order:
            return (0, preset_order[g])
        return (1, g.lower())

    labels.sort(key=sort_key)
    return labels


@app.template_filter("practice_date_display")
def practice_date_display_filter(value):
    """Date-only label for practice timestamps (YYYY-MM-DD)."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if "T" in s:
        return s.split("T", 1)[0].strip()[:10]
    if " " in s:
        return s.split(" ", 1)[0].strip()[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


@app.template_filter("practice_datetime_no_seconds")
def practice_datetime_no_seconds_filter(value):
    """Practice timestamp for display: YYYY-MM-DD HH:MM (drop seconds if present)."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if "T" in s:
        s = s.replace("T", " ", 1)
    if len(s) >= 16 and s[10] == " ":
        return s[:16]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


# Strips leading "The " / "A " for natural title sorting.
# Tuple: (label, months back from Central "today", or None = all time).
PERIOD_OPTIONS = {
    "1m":  ("1 Month",  1),
    "2m":  ("2 Months", 2),
    "3m":  ("3 Months", 3),
    "6m":  ("6 Months", 6),
    "1y":  ("1 Year",   12),
    "all": ("All Time", None),
}


def _add_calendar_months(d: date, delta_months: int) -> date:
    total = d.year * 12 + (d.month - 1) + delta_months
    y, m0 = divmod(total, 12)
    month = m0 + 1
    last = calendar.monthrange(y, month)[1]
    return date(y, month, min(d.day, last))


def central_period_start_date(period_key: str) -> date | None:
    """First calendar day to include for /times-played period filters (US Central)."""
    months_back = PERIOD_OPTIONS.get(period_key, PERIOD_OPTIONS["1m"])[1]
    if months_back is None:
        return None
    return _add_calendar_months(central_date_today(), -int(months_back))

SORT_NAME = """
    CASE
        WHEN LOWER(s.name) LIKE 'the %' THEN LOWER(SUBSTR(s.name, 5))
        WHEN LOWER(s.name) LIKE 'a %'   THEN LOWER(SUBSTR(s.name, 3))
        ELSE LOWER(s.name)
    END
"""



SORT_OPTIONS = {
    "name": ("Name \u2191", f"{SORT_NAME} ASC"),
    "name_d": ("Name \u2193", f"{SORT_NAME} DESC"),
    "tune_num": (
        "No. \u2191",
        "CASE WHEN s.tune_num IS NULL THEN 1 ELSE 0 END, s.tune_num ASC, "
        + SORT_NAME
        + " ASC",
    ),
    "tune_num_d": (
        "No. \u2193",
        "CASE WHEN s.tune_num IS NULL THEN 1 ELSE 0 END, s.tune_num DESC, "
        + SORT_NAME
        + " ASC",
    ),
    "least": ("Count \u2191", f"practice_count ASC, {SORT_NAME} ASC"),
    "most": ("Count \u2193", f"practice_count DESC, {SORT_NAME} ASC"),
    "last_asc": (
        "Last Practiced \u2191",
        "CASE WHEN last_practiced IS NULL THEN 1 ELSE 0 END, last_practiced ASC",
    ),
    "recent": (
        "Last Practiced \u2193",
        "CASE WHEN last_practiced IS NULL THEN 1 ELSE 0 END, last_practiced DESC",
    ),
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _backup_tunes_db_filename() -> str:
    """tunes_bu_YYYYMMDD_#####.db; ##### = seconds since start of day (US Central)."""
    now = datetime.now(DB_TIMEZONE)
    ymd = now.strftime("%Y%m%d")
    sec = now.hour * 3600 + now.minute * 60 + now.second
    return f"tunes_bu_{ymd}_{sec:05d}.db"


def _backup_tunes_db(conn: sqlite3.Connection) -> None:
    """Write a consistent snapshot to __local__/backups (used before destructive or risky writes)."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS_DIR / _backup_tunes_db_filename()
    bck = sqlite3.connect(str(dest))
    try:
        conn.backup(bck)
    finally:
        bck.close()


def _no_practice_rows_on_central_day(conn: sqlite3.Connection, ymd: str) -> bool:
    """ymd is YYYY-MM-DD. True if there are no practice rows for that calendar date."""
    row = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM practice_history WHERE substr(date_played, 1, 10) = ?)
        + (SELECT COUNT(*) FROM set_practice WHERE substr(date_practiced, 1, 10) = ?)
        AS n
        """,
        (ymd, ymd),
    ).fetchone()
    n = int(row["n"] if row else 0)
    return n == 0


def _tune_practiced_on_central_day(
    conn: sqlite3.Connection, tune_id: int, ymd: str
) -> bool:
    """ymd is YYYY-MM-DD (Central). True if this tune has a practice row on that date."""
    row = conn.execute(
        """
        SELECT 1 FROM practice_history
        WHERE tune_id = ? AND substr(date_played, 1, 10) = ?
        LIMIT 1
        """,
        (tune_id, ymd),
    ).fetchone()
    return row is not None


def _set_practiced_on_central_day(
    conn: sqlite3.Connection, set_id: int, ymd: str
) -> bool:
    """ymd is YYYY-MM-DD (Central). True if this set has a set_practice row on that date."""
    row = conn.execute(
        """
        SELECT 1 FROM set_practice
        WHERE set_id = ? AND substr(date_practiced, 1, 10) = ?
        LIMIT 1
        """,
        (set_id, ymd),
    ).fetchone()
    return row is not None


def _refresh_log_drop_legacy_columns(conn) -> None:
    """Remove pre–start_at/end_at columns if present."""
    legacy = (
        "start_date",
        "end_date",
        "start_time_minutes",
        "end_time_minutes",
        "refreshed_at",
    )
    for _ in range(len(legacy) + 2):
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
        }
        hit = next((c for c in legacy if c in cols), None)
        if not hit:
            break
        try:
            conn.execute(f"ALTER TABLE refresh_log DROP COLUMN {hit}")
        except sqlite3.OperationalError:
            break


def _ensure_refresh_log_schema(conn):
    """Migrate refresh_log to start_at / end_at (local YYYY-MM-DDTHH:MM)."""
    try:
        info = conn.execute("PRAGMA table_info(refresh_log)").fetchall()
    except sqlite3.OperationalError:
        return
    if not info:
        return
    cols = {r["name"] for r in info}
    if "start_at" in cols:
        _refresh_log_drop_legacy_columns(conn)
        return

    if "start_date" not in cols and "refreshed_at" in cols:
        try:
            conn.execute(
                "ALTER TABLE refresh_log RENAME COLUMN refreshed_at TO start_date"
            )
        except sqlite3.OperationalError:
            pass
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
        }
    added_end = False
    if "end_date" not in cols:
        try:
            conn.execute("ALTER TABLE refresh_log ADD COLUMN end_date TEXT")
            added_end = True
        except sqlite3.OperationalError:
            pass
    if added_end:
        conn.execute(
            "UPDATE refresh_log SET end_date = start_date WHERE end_date IS NULL"
        )
    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
    }
    if "start_time_minutes" not in cols:
        try:
            conn.execute(
                "ALTER TABLE refresh_log ADD COLUMN start_time_minutes "
                "INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
    if "end_time_minutes" not in cols:
        try:
            conn.execute(
                "ALTER TABLE refresh_log ADD COLUMN end_time_minutes INTEGER"
            )
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "UPDATE refresh_log SET end_time_minutes = 0 "
            "WHERE end_date IS NOT NULL AND end_time_minutes IS NULL"
        )

    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
    }
    if "start_at" not in cols:
        try:
            conn.execute("ALTER TABLE refresh_log ADD COLUMN start_at TEXT")
            conn.execute("ALTER TABLE refresh_log ADD COLUMN end_at TEXT")
        except sqlite3.OperationalError:
            pass
    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
    }
    if "start_at" in cols and "start_date" in cols:
        conn.execute(
            """
            UPDATE refresh_log SET start_at =
                start_date || 'T' || printf('%02d:%02d',
                    COALESCE(start_time_minutes, 0) / 60,
                    COALESCE(start_time_minutes, 0) % 60)
            WHERE start_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE refresh_log SET end_at =
              end_date || 'T' || printf('%02d:%02d',
                COALESCE(end_time_minutes, 0) / 60,
                COALESCE(end_time_minutes, 0) % 60)
            WHERE end_date IS NOT NULL AND end_at IS NULL
            """
        )
        conn.execute(
            "UPDATE refresh_log SET end_at = NULL WHERE end_date IS NULL"
        )
    _refresh_log_drop_legacy_columns(conn)


def _ensure_refresh_log_numbers(conn) -> None:
    """Ensure refresh_number exists; fill NULLs in chronological order after MAX."""
    try:
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(refresh_log)").fetchall()
        }
    except sqlite3.OperationalError:
        return
    if not cols or "start_at" not in cols:
        return
    if "refresh_number" not in cols:
        try:
            conn.execute(
                "ALTER TABLE refresh_log ADD COLUMN refresh_number INTEGER"
            )
        except sqlite3.OperationalError:
            return
    has_null = conn.execute(
        "SELECT 1 FROM refresh_log WHERE refresh_number IS NULL LIMIT 1"
    ).fetchone()
    if not has_null:
        return
    mx_row = conn.execute("SELECT MAX(refresh_number) FROM refresh_log").fetchone()
    mx = int(mx_row[0]) if mx_row[0] is not None else 0
    rows = conn.execute(
        """
        SELECT id FROM refresh_log
        WHERE refresh_number IS NULL
        ORDER BY start_at ASC, id ASC
        """
    ).fetchall()
    for j, r in enumerate(rows, start=1):
        conn.execute(
            "UPDATE refresh_log SET refresh_number = ? WHERE id = ?",
            (mx + j, r["id"]),
        )


def _ensure_set_tunes_sort_order(conn):
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


def distinct_tune_types():
    """Distinct non-empty tune_type values from tunes (for set type dropdown)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(s.tune_type) AS t
            FROM tunes s
            WHERE TRIM(COALESCE(s.tune_type, '')) != ''
            ORDER BY t COLLATE NOCASE
            """
        ).fetchall()
    return [r["t"] for r in rows]


def distinct_keys():
    """Distinct key tokens from tunes and sets (comma-separated in each cell)."""
    with get_db() as conn:
        trows = conn.execute(
            "SELECT key FROM tunes WHERE TRIM(COALESCE(key, '')) != ''"
        ).fetchall()
        try:
            srows = conn.execute(
                "SELECT key FROM sets WHERE TRIM(COALESCE(key, '')) != ''"
            ).fetchall()
        except sqlite3.OperationalError:
            srows = []
    seen: set[str] = set()
    for r in trows:
        for part in re.split(r"\s*,\s*", (r["key"] or "")):
            p = part.strip()
            if p:
                seen.add(p)
    for r in srows:
        for part in re.split(r"\s*,\s*", (r["key"] or "")):
            p = part.strip()
            if p:
                seen.add(p)
    return sorted(seen, key=str.lower)


def distinct_set_types_union():
    """Tune types from tunes plus type tokens from sets (comma-separated like keys)."""
    with get_db() as conn:
        from_tunes = {
            r["t"]
            for r in conn.execute(
                """
                SELECT DISTINCT TRIM(tune_type) AS t
                FROM tunes
                WHERE TRIM(COALESCE(tune_type, '')) != ''
                """
            )
        }
        from_sets: set[str] = set()
        for r in conn.execute(
            "SELECT type FROM sets WHERE TRIM(COALESCE(type, '')) != ''"
        ):
            for part in re.split(r"\s*,\s*", (r["type"] or "")):
                t = part.strip()
                if t:
                    from_sets.add(t)
    return sorted(from_tunes | from_sets, key=str.lower)


def suggestions_merge(base_list, *extra_values):
    """Sorted unique strings from DB list plus current value(s) if any."""
    seen = {str(x).strip() for x in base_list if x and str(x).strip()}
    for ev in extra_values:
        if ev is not None and str(ev).strip():
            seen.add(str(ev).strip())
    return sorted(seen, key=str.lower)


def table_tune_key_suggestions(tunes_rows):
    """Suggestions for table inline edit: DB + values on visible rows."""
    types = set(distinct_tune_types())
    keys = set(distinct_keys())
    for tune in tunes_rows:
        tt = (tune["tune_type"] or "").strip()
        if tt:
            types.add(tt)
        raw_k = (tune["key"] or "").strip()
        if raw_k:
            for part in re.split(r"\s*,\s*", raw_k):
                p = part.strip()
                if p:
                    keys.add(p)
    return sorted(types, key=str.lower), sorted(keys, key=str.lower)


def pick_header_phrase_daily(
    phrases: list[str],
    *,
    use_override_pool: bool = False,
    variety: str = "medium",
    frequency_sec: int = 1,
) -> str | None:
    """
    Daily-seeded initial pool size from variety (5/10/20/all); time bucket from
    frequency_sec seeds the final draw. Then 90% from that pool, 10% from outside.
    Override pool ignores variety (fixed five strings).
    """
    v = variety if variety in VALID_PHRASE_VARIETIES else "medium"
    freq = int(frequency_sec)
    if freq not in VALID_PHRASE_FREQUENCY_SEC:
        freq = 1
    time_bucket = int(time.time() // max(1, freq))
    rng_sec = random.Random(time_bucket)

    if use_override_pool:
        pool_main = list(HEADER_PHRASE_OVERRIDE_POOL)
        pool_set = set(pool_main)
        outside = [p for p in phrases if p not in pool_set]
        if rng_sec.random() < 0.9 or not outside:
            return rng_sec.choice(pool_main)
        return rng_sec.choice(outside)

    if not phrases:
        return None
    n = len(phrases)
    if v == "all":
        k = n
    else:
        k = min(PHRASE_VARIETY_POOL_CAP.get(v, 10), n)
    if k < 1:
        return None
    days = (central_date_today() - HEADER_PHRASE_EPOCH).days
    rng_day = random.Random(days)
    pool_main = rng_day.sample(phrases, k=k)
    outside = [p for p in phrases if p not in set(pool_main)]
    if rng_sec.random() < 0.9 or not outside:
        return rng_sec.choice(pool_main)
    return rng_sec.choice(outside)


@app.context_processor
def inject_tune_types():
    sidebar_pg: list[str] = []
    header_random_phrase: str | None = None
    settings = load_settings()
    try:
        with get_db() as conn:
            sidebar_pg = distinct_practice_groups_from_db(conn)
            rows = conn.execute(
                """
                SELECT body FROM phrases
                WHERE TRIM(COALESCE(body, '')) != ''
                """
            ).fetchall()
        bodies = [str(r["body"]).strip() for r in rows if r["body"] and str(r["body"]).strip()]
        header_random_phrase = pick_header_phrase_daily(
            bodies,
            use_override_pool=bool(settings.get("phrase_subset_override_enabled")),
            variety=str(settings.get("phrase_variety") or "medium"),
            frequency_sec=int(settings.get("phrase_frequency_sec") or 1),
        )
    except Exception:
        pass

    return {
        "distinct_tune_types": distinct_tune_types(),
        "mp_server_today": central_date_today().isoformat(),
        "mp_settings": settings,
        "practice_groups": PRACTICE_GROUPS,
        "mp_sidebar_practice_groups": sidebar_pg,
        "header_random_phrase": header_random_phrase,
        "mp_static_assets_v": _mp_static_asset_version(),
        "mp_manifest_bust": _mp_manifest_bust(),
        "theme_css_var_keys": sorted(THEME_EDITOR_KEYS),
        "theme_runtime": theme_runtime_for_client(),
        "themes_list_client": themes_list_for_client(),
        "theme_fallback_id": THEME_FALLBACK_ID,
    }


@app.route("/site.webmanifest")
def web_manifest():
    tr = theme_runtime_for_client()
    tv = tr.get("theme_variables") or {}
    bg = str(tv.get("bg") or "#f6f7f9").strip() or "#f6f7f9"
    root = (request.script_root or "").rstrip("/")
    base = f"{root}/" if root else "/"
    manifest = {
        "name": "Fiddle Practice",
        "short_name": "Fiddle",
        "description": "Tune and practice tracking for fiddle players.",
        "id": base,
        "start_url": base,
        "scope": base,
        "display": "standalone",
        "orientation": "any",
        "background_color": bg,
        "theme_color": bg,
        "icons": [
            {
                "src": url_for("static", filename="pwa-icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="pwa-icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("static", filename="pwa-icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return Response(
        json.dumps(manifest, separators=(",", ":")),
        mimetype="application/manifest+json",
    )


@app.route("/api/theme/activate", methods=["POST"])
def api_theme_activate():
    data = request.get_json(silent=True) or {}
    tid = str(data.get("id") or "").strip()
    if not tid:
        return jsonify({"ok": False, "error": "Missing id"}), 400
    tdata = load_themes_data()
    if not any(t.get("id") == tid for t in tdata.get("themes", [])):
        return jsonify({"ok": False, "error": "Unknown theme id"}), 400
    tdata["active_id"] = tid
    save_themes_data(tdata)
    return jsonify({"ok": True, "id": tid})


@app.route("/api/theme/save", methods=["POST"])
def api_theme_save():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Invalid body"}), 400
    tid_in = str(data.get("id") or "").strip() or None
    name = str(data.get("name") or "Untitled").strip()[:120] or "Untitled"
    variables_in = data.get("variables")
    if not isinstance(variables_in, dict):
        return jsonify({"ok": False, "error": "Invalid variables"}), 400
    norm = _normalize_theme_variables_dict(variables_in)
    full = complete_theme_variables(norm)
    tid = upsert_theme_in_file(tid_in, name, full, activate=True)
    return jsonify({"ok": True, "id": tid})


@app.route("/theme-editor", methods=["GET", "POST"])
def theme_editor():
    if request.method == "POST":
        merged = _variables_from_post_form(request)
        full = complete_theme_variables(merged)
        library_id = request.form.get("library_id", "").strip()
        theme_name = request.form.get("theme_name", "").strip()[:120] or "Untitled"
        upsert_theme_in_file(library_id or None, theme_name, full, activate=True)
        return redirect(url_for("index"))
    requested_library = request.args.get("library_id", "").strip()
    base_q = request.args.get("base", "").strip()
    prefer_new = request.args.get("new", "").strip().lower() in ("1", "true", "yes")
    if not requested_library and not base_q:
        base_q = THEME_FALLBACK_ID
        prefer_new = True
    values, lib_from_state, theme_display_name = theme_editor_page_state(
        requested_library or None,
        prefer_new,
        base_q or None,
    )
    editing_is_new_theme = not (
        requested_library and lib_from_state and lib_from_state == requested_library
    )
    editing_library_id = lib_from_state or secrets.token_hex(6)
    built_in = set(THEME_PRESETS.keys())
    preset_labels: list[tuple[str, str]] = [
        (pid, pid.replace("-", " ").title()) for pid in THEME_PRESETS
    ]
    for t in load_themes_data().get("themes", []):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid or tid in built_in:
            continue
        n = str(t.get("name") or tid).strip()[:80] or tid
        preset_labels.append((tid, n))
    rows_by_group: dict[str, list[tuple[str, str]]] = {gid: [] for gid, _ in THEME_EDITOR_GROUPS}
    for key, label, gid in THEME_EDITOR_ROWS:
        rows_by_group[gid].append((key, label))
    base_preset_for_js: dict[str, str] = {k: values.get(k, "") for k in THEME_EDITOR_KEYS}
    fill_for_js: dict[str, dict] = {k: complete_theme_variables(dict(v)) for k, v in THEME_PRESETS.items()}
    for t in load_themes_data().get("themes", []):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        v0 = t.get("variables")
        fill_for_js[tid] = complete_theme_variables(v0 if isinstance(v0, dict) else {})
    editing_can_delete = (
        not editing_is_new_theme
        and bool(editing_library_id)
        and str(editing_library_id) not in THEME_PRESETS
    )
    return render_template(
        "theme_editor.html",
        theme_groups=THEME_EDITOR_GROUPS,
        theme_rows_by_group=rows_by_group,
        theme_values=values,
        theme_fill_for_js=fill_for_js,
        theme_preset_list=preset_labels,
        editing_base_preset_json=base_preset_for_js,
        editing_data_theme=editing_library_id,
        editing_library_id=editing_library_id,
        theme_display_name=theme_display_name,
        editing_is_new_theme=editing_is_new_theme,
        editing_can_delete=editing_can_delete,
    )


@app.route("/theme-editor/delete", methods=["POST"])
def theme_editor_delete():
    tid = (request.form.get("library_id") or "").strip()
    err = delete_theme_in_file(tid)
    if err is not None:
        if err == "builtin":
            flash("Built-in themes cannot be deleted.", "error")
        elif err in ("last_theme",):
            flash("Cannot delete the only remaining theme.", "error")
        elif err == "not_found":
            flash("Theme not found.", "error")
        else:
            flash("Could not delete theme.", "error")
    return redirect(url_for("index"))


def _migrate_legacy_katie_schema(conn: sqlite3.Connection) -> None:
    def _tables() -> set[str]:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    tabs = _tables()
    if "songs" in tabs and "tunes" not in tabs:
        conn.execute("ALTER TABLE songs RENAME TO tunes")

    tabs = _tables()
    if "tunes" in tabs:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(tunes)")]
        if "group_name" in cols:
            try:
                conn.execute("ALTER TABLE tunes DROP COLUMN group_name")
            except sqlite3.OperationalError:
                pass

    if "practice_history" in _tables():
        cols = [r[1] for r in conn.execute("PRAGMA table_info(practice_history)")]
        conn.execute("DROP INDEX IF EXISTS idx_practice_history_song_id")
        if "song_id" in cols and "tune_id" not in cols:
            try:
                conn.execute(
                    "ALTER TABLE practice_history RENAME COLUMN song_id TO tune_id"
                )
            except sqlite3.OperationalError:
                pass
        conn.execute("DROP INDEX IF EXISTS idx_practice_history_tune_id")

    tabs = _tables()
    if "set_songs" in tabs and "set_tunes" not in tabs:
        conn.execute("ALTER TABLE set_songs RENAME TO set_tunes")

    if "set_tunes" in _tables():
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
                composer TEXT
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refresh_number INTEGER NOT NULL,
                start_at TEXT NOT NULL,
                end_at TEXT
            )
        """)
        _ensure_refresh_log_schema(conn)
        _ensure_refresh_log_numbers(conn)
        _ensure_set_tunes_sort_order(conn)
        for col in (
            "first_played",
            "last_played",
            "learn_start",
            "learn_end",
            "capo",
            "strumming",
            "priority",
            "progress",
        ):
            try:
                conn.execute(f"ALTER TABLE tunes DROP COLUMN {col}")
            except Exception:
                pass
        conn.execute("UPDATE tunes SET key = '' WHERE key IN ('None', 'none', 'NULL')")
        for col, defn in [
            ("link_1",      "TEXT"),
            ("link_2",      "TEXT"),
            ("link_3",      "TEXT"),
            ("notes",       "TEXT"),
            ("practice_group", "TEXT"),
            ("composer",    "TEXT"),
            ("lessons",     "TEXT"),
            ("tune_num",    "INTEGER"),
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
        try:
            conn.execute("ALTER TABLE sets ADD COLUMN key TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.commit()


# Scalar subqueries avoid JOIN + GROUP BY over the full practice_history table (very slow
# when there are many log rows). idx_practice_history_tune_id keeps these fast.
TUNES_WITH_STATS = """
    SELECT s.*,
           (SELECT COUNT(*) FROM practice_history p WHERE p.tune_id = s.id) AS practice_count,
           (SELECT MIN(p.date_played) FROM practice_history p WHERE p.tune_id = s.id) AS first_practiced,
           (SELECT MAX(p.date_played) FROM practice_history p WHERE p.tune_id = s.id) AS last_practiced,
           (SELECT CASE WHEN MAX(p.date_played) IS NULL THEN NULL
                        ELSE CAST(ROUND(julianday(?) - julianday(MAX(p.date_played))) AS INTEGER)
                   END
              FROM practice_history p WHERE p.tune_id = s.id) AS days_since_last
    FROM tunes s
"""

PSR_FILTER_ALL = "all"
PSR_FILTER_PSR = "psr"
PSR_FILTER_NOT_PSR = "not_psr"
VALID_PSR_FILTERS = frozenset({PSR_FILTER_ALL, PSR_FILTER_PSR, PSR_FILTER_NOT_PSR})


def _psr_filter_from_request() -> str:
    raw = (request.args.get("psr") or "").strip().lower().replace("-", "_")
    if raw == "not_psr":
        return PSR_FILTER_NOT_PSR
    if raw == PSR_FILTER_PSR:
        return PSR_FILTER_PSR
    return PSR_FILTER_ALL


def _last_reset_start_sqlite(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT start_at FROM refresh_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row or not row["start_at"]:
        return None
    return _refresh_at_to_sqlite_datetime(str(row["start_at"]))


def _psr_sql_fragments(
    psr_mode: str, reset_bound: str | None
) -> tuple[list[str], list]:
    """WHERE fragments (no leading AND) for practice-since-reset filtering on alias s."""
    if psr_mode not in VALID_PSR_FILTERS or psr_mode == PSR_FILTER_ALL:
        return [], []
    if reset_bound is None:
        if psr_mode == PSR_FILTER_PSR:
            return (
                ["EXISTS (SELECT 1 FROM practice_history p WHERE p.tune_id = s.id)"],
                [],
            )
        return (
            [
                "NOT EXISTS (SELECT 1 FROM practice_history p WHERE p.tune_id = s.id)"
            ],
            [],
        )
    if psr_mode == PSR_FILTER_PSR:
        return (
            [
                "EXISTS (SELECT 1 FROM practice_history p WHERE p.tune_id = s.id "
                "AND datetime(p.date_played) > datetime(?))"
            ],
            [reset_bound],
        )
    return (
        [
            "NOT EXISTS (SELECT 1 FROM practice_history p WHERE p.tune_id = s.id "
            "AND datetime(p.date_played) > datetime(?))"
        ],
        [reset_bound],
    )


def _tune_ids_with_practice_since(
    conn: sqlite3.Connection, reset_bound: str | None
) -> set[int]:
    if reset_bound is None:
        rows = conn.execute(
            "SELECT DISTINCT tune_id FROM practice_history"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT tune_id FROM practice_history "
            "WHERE datetime(date_played) > datetime(?)",
            (reset_bound,),
        ).fetchall()
    return {int(r["tune_id"]) for r in rows}


@app.route("/")
def index():
    search = request.args.get("search", "").strip()
    req_tune_type = request.args.get("tune_type", "").strip()
    psr_filter = _psr_filter_from_request()
    sort_key = request.args.get("sort", "name")
    if sort_key == "oldest":
        sort_key = "last_asc"
    _, order_sql = SORT_OPTIONS.get(sort_key, SORT_OPTIONS["name"])

    type_cond_parts = ["TRIM(COALESCE(s.tune_type, '')) != ''"]
    type_params: list = []
    type_where_sql = "WHERE " + " AND ".join(type_cond_parts)

    with get_db() as conn:
        type_rows = conn.execute(
            "SELECT DISTINCT TRIM(s.tune_type) AS t FROM tunes s "
            + type_where_sql
            + " ORDER BY t COLLATE NOCASE",
            type_params,
        ).fetchall()
        types_for_filter = [str(r["t"]) for r in type_rows if r["t"] is not None]

        tune_type = req_tune_type if req_tune_type in types_for_filter else ""

        reset_bound = _last_reset_start_sqlite(conn)
        psr_frags, psr_params = _psr_sql_fragments(psr_filter, reset_bound)

        conditions, params = [], []
        if search:
            conditions.append("(s.name LIKE ? OR s.tune_type LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        if tune_type:
            conditions.append("TRIM(COALESCE(s.tune_type, '')) = ?")
            params.append(tune_type)
        conditions.extend(psr_frags)
        params.extend(psr_params)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = TUNES_WITH_STATS + where + f" ORDER BY {order_sql}"

        tunes = conn.execute(sql, [_julianday_anchor_sql()] + params).fetchall()

    return render_template(
        "index.html",
        tunes=tunes,
        search=search,
        tune_type=tune_type,
        psr_filter=psr_filter,
        types_for_filter=types_for_filter,
        sort_key=sort_key,
        sort_options=SORT_OPTIONS,
    )


@app.route("/add", methods=["GET", "POST"])
def add_tune():
    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            flash("Tune name is required.", "error")
            with get_db() as conn:
                next_num = _next_tune_num(conn)
            return render_template(
                "tune_form.html",
                tune=None,
                tune_type_suggestions=suggestions_merge(distinct_tune_types()),
                key_suggestions=suggestions_merge_keys(distinct_keys()),
                action="Add",
                default_tune_num=next_num,
                add_form=_add_tune_form_repopulate(),
            )

        with get_db() as conn:
            tune_num = _tune_num_from_add_form(conn)
            conn.execute(
                """INSERT INTO tunes
                   (name, tune_type, key, composer, tune_num,
                    link_1, link_2, link_3,
                    notes, practice_group, lessons)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    request.form.get("tune_type", ""),
                    _keys_from_request_form(),
                    request.form.get("composer", "").strip(),
                    tune_num,
                    (request.form.get("link_1", "") or "").strip(),
                    (request.form.get("link_2", "") or "").strip(),
                    (request.form.get("link_3", "") or "").strip(),
                    request.form.get("notes", "") or "",
                    _practice_groups_from_request_form(),
                    "",
                )
            )
            conn.commit()
        return redirect(url_for("index"))

    with get_db() as conn:
        next_num = _next_tune_num(conn)
    return render_template(
        "tune_form.html",
        tune=None,
        tune_type_suggestions=suggestions_merge(distinct_tune_types()),
        key_suggestions=suggestions_merge_keys(distinct_keys()),
        action="Add",
        default_tune_num=next_num,
    )


def _soundslice_slice_ids_from_tune(tune_row):
    """Slice IDs from link_1..link_3 where the URL contains 'soundslice', in field order."""
    ids = []
    for key in ("link_1", "link_2", "link_3"):
        url = (tune_row[key] or "").strip()
        if not url or "soundslice" not in url.lower():
            continue
        m = re.search(r"/slices/([^/?#]+)", url, re.I)
        if not m:
            continue
        sid = (m.group(1) or "").strip()
        if not sid or sid.lower() == "embed":
            continue
        ids.append(sid)
    return ids


def _tune_sets_for_panel(conn, tune_id: int) -> list[dict]:
    """Sets that include this tune: tune list, last set practice, days since."""
    rows = conn.execute(
        """
        SELECT se.id AS set_id, se.description
        FROM set_tunes st
        JOIN sets se ON se.id = st.set_id
        WHERE st.tune_id = ?
        ORDER BY (TRIM(COALESCE(se.description, '')) = ''),
                 LOWER(TRIM(COALESCE(se.description, ''))),
                 se.id
        """,
        (tune_id,),
    ).fetchall()
    if not rows:
        return []
    set_ids = [int(r["set_id"]) for r in rows]
    ph = ",".join("?" * len(set_ids))
    last_by_set: dict[int, str | None] = {}
    for r in conn.execute(
        f"""
        SELECT set_id, MAX(date_practiced) AS last_practiced
        FROM set_practice
        WHERE set_id IN ({ph})
        GROUP BY set_id
        """,
        set_ids,
    ):
        last_by_set[int(r["set_id"])] = r["last_practiced"]
    tunes_by_set: dict[int, list[dict]] = {sid: [] for sid in set_ids}
    for r in conn.execute(
        f"""
        SELECT ss.set_id, s.id AS tune_id, s.name
        FROM set_tunes ss
        JOIN tunes s ON s.id = ss.tune_id
        WHERE ss.set_id IN ({ph})
        ORDER BY ss.set_id, ss.sort_order ASC, ss.tune_id ASC
        """,
        set_ids,
    ):
        tunes_by_set[int(r["set_id"])].append(
            {"id": int(r["tune_id"]), "name": r["name"]}
        )
    out: list[dict] = []
    for r in rows:
        sid = int(r["set_id"])
        lp = last_by_set.get(sid)
        days_since_last = None
        if lp:
            try:
                days_since_last = (
                    central_date_today() - date.fromisoformat(str(lp)[:10])
                ).days
            except ValueError:
                pass
        desc = (r["description"] or "").strip()
        out.append(
            {
                "id": sid,
                "description": desc,
                "last_practiced": lp,
                "days_since_last": days_since_last,
                "tunes": tunes_by_set[sid],
            }
        )
    return out


@app.route("/tune/<int:tune_id>/panel")
def tune_panel(tune_id):
    with get_db() as conn:
        tune = conn.execute("SELECT * FROM tunes WHERE id = ?", (tune_id,)).fetchone()
        if not tune:
            return "Not found", 404
        stats = _practice_stats(conn, tune_id)
        tune_sets = _tune_sets_for_panel(conn, tune_id)
    lesson_audio_files = [
        {
            "name": r["name"],
            "url": url_for("lesson_tunes_download", filename=r["name"]),
        }
        for r in tune_lesson_files_rows(tune)
        if not r["missing"] and r.get("embed_kind") == "audio"
    ]
    return render_template(
        "tune_panel.html",
        tune=tune,
        soundslice_embeds=_soundslice_slice_ids_from_tune(tune),
        tune_type_suggestions=suggestions_merge(distinct_tune_types(), tune["tune_type"]),
        key_suggestions=suggestions_merge_keys(distinct_keys(), tune["key"]),
        tune_sets=tune_sets,
        lesson_audio_files=lesson_audio_files,
        **stats,
    )


@app.route("/edit/<int:tune_id>", methods=["GET", "POST"])
def edit_tune(tune_id):
    is_modal = request.form.get("modal") == "1"

    with get_db() as conn:
        tune = conn.execute("SELECT * FROM tunes WHERE id = ?", (tune_id,)).fetchone()
        if not tune:
            flash("Tune not found.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":
            name = request.form["name"].strip()
            if not name:
                if is_modal:
                    return jsonify({"ok": False, "error": "Tune name is required."}), 400
                flash("Tune name is required.", "error")
                stats = _practice_stats(conn, tune_id)
                return render_template(
                    "tune_form.html",
                    tune=tune,
                    tune_type_suggestions=suggestions_merge(distinct_tune_types(), tune["tune_type"]),
                    key_suggestions=suggestions_merge_keys(distinct_keys(), tune["key"]),
                    action="Save",
                    **stats,
                )

            def _link_from_form(key):
                if key in request.form:
                    return (request.form.get(key) or "").strip()
                try:
                    v = tune[key]
                    return (v or "").strip() if v is not None else ""
                except (KeyError, IndexError):
                    return ""

            def _notes_from_form():
                if "notes" in request.form:
                    return request.form.get("notes") or ""
                try:
                    v = tune["notes"]
                    return v if v is not None else ""
                except (KeyError, IndexError):
                    return ""

            tune_num_val, tune_num_err = _parse_tune_num_update(
                request.form.get("tune_num", "")
            )
            if tune_num_err:
                if is_modal:
                    return jsonify({"ok": False, "error": tune_num_err}), 400
                flash(tune_num_err, "error")
                stats = _practice_stats(conn, tune_id)
                return render_template(
                    "tune_form.html",
                    tune=tune,
                    tune_type_suggestions=suggestions_merge(distinct_tune_types(), tune["tune_type"]),
                    key_suggestions=suggestions_merge_keys(distinct_keys(), tune["key"]),
                    action="Save",
                    **stats,
                )

            conn.execute(
                """UPDATE tunes SET name=?, tune_type=?, key=?, composer=?,
                          tune_num=?, link_1=?, link_2=?, link_3=?, notes=?,
                          practice_group=?, lessons=?
                   WHERE id=?""",
                (
                    name,
                    request.form.get("tune_type", ""),
                    _keys_from_request_form(),
                    request.form.get("composer", "").strip(),
                    tune_num_val,
                    _link_from_form("link_1"),
                    _link_from_form("link_2"),
                    _link_from_form("link_3"),
                    _notes_from_form(),
                    _practice_groups_from_request_form(),
                    _lessons_from_request_form(),
                    tune_id,
                )
            )
            conn.commit()
            if is_modal:
                return jsonify({"ok": True})
            return redirect(url_for("index"))

        stats = _practice_stats(conn, tune_id)

    return render_template(
        "tune_form.html",
        tune=tune,
        tune_type_suggestions=suggestions_merge(distinct_tune_types(), tune["tune_type"]),
        key_suggestions=suggestions_merge_keys(distinct_keys(), tune["key"]),
        action="Save",
        **stats,
    )


def _practice_stats(conn, tune_id):
    from datetime import date

    row = conn.execute(
        """SELECT COUNT(*) AS practice_count,
                  MIN(date_played) AS first_practiced,
                  MAX(date_played) AS last_practiced
           FROM practice_history WHERE tune_id = ?""",
        (tune_id,)
    ).fetchone()
    days_since_last = None
    lp = row["last_practiced"]
    if lp:
        try:
            last = date.fromisoformat(lp[:10])
            days_since_last = (central_date_today() - last).days
        except ValueError:
            pass
    return {
        "practice_count":  row["practice_count"],
        "first_practiced": row["first_practiced"],
        "last_practiced":  row["last_practiced"],
        "days_since_last": days_since_last,
    }


@app.route("/practiced/<int:tune_id>", methods=["POST"])
def practiced_tune(tune_id):
    with get_db() as conn:
        ts = _adjust_practice_timestamp_avoid_refresh_starts(
            conn, practice_timestamp_now()
        )
        row = conn.execute("SELECT name FROM tunes WHERE id = ?", (tune_id,)).fetchone()
        if row:
            if _tune_practiced_on_central_day(conn, tune_id, ts[:10]):
                return jsonify({"ok": False, "error": "Already practiced today"}), 200
            if _no_practice_rows_on_central_day(conn, ts[:10]):
                _backup_tunes_db(conn)
            conn.execute(
                "INSERT INTO practice_history (tune_id, date_played) VALUES (?, ?)",
                (tune_id, ts)
            )
            conn.commit()
            return jsonify({"ok": True, "date": ts})
        return jsonify({"error": "Tune not found"}), 404


@app.route("/set/<int:set_id>/practice", methods=["POST"])
def record_set_practice(set_id):
    data = request.get_json(silent=True) or {}
    log_tunes = bool(data.get("log_tunes"))
    with get_db() as conn:
        ts = _adjust_practice_timestamp_avoid_refresh_starts(
            conn, practice_timestamp_now()
        )
        set_row = conn.execute("SELECT id FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not set_row:
            return jsonify({"ok": False, "error": "Set not found"}), 404
        if _set_practiced_on_central_day(conn, set_id, ts[:10]):
            return jsonify({"ok": False, "error": "Already recorded for today"}), 200
        if _no_practice_rows_on_central_day(conn, ts[:10]):
            _backup_tunes_db(conn)
        conn.execute(
            "INSERT INTO set_practice (set_id, date_practiced) VALUES (?, ?)",
            (set_id, ts),
        )
        if log_tunes:
            for r in conn.execute(
                "SELECT tune_id FROM set_tunes WHERE set_id = ?",
                (set_id,),
            ):
                tid = int(r["tune_id"])
                if not _tune_practiced_on_central_day(conn, tid, ts[:10]):
                    conn.execute(
                        "INSERT INTO practice_history (tune_id, date_played) VALUES (?, ?)",
                        (tid, ts),
                    )
        conn.commit()
    days_since = (central_date_today() - date.fromisoformat(ts[:10])).days
    return jsonify({"ok": True, "date": ts, "days_since_last": days_since})


def _statistics_payload(conn):
    """Build chart-ready series from practice_history (month buckets + tune type)."""
    from datetime import date

    bounds = conn.execute(
        "SELECT MIN(date_played) AS lo, MAX(date_played) AS hi FROM practice_history"
    ).fetchone()
    lo, hi = bounds["lo"], bounds["hi"]
    empty_series = {"labels": [], "values": [], "day_divisors": []}
    refresh_by_period = _statistics_refresh_series(conn)
    if not lo or not hi:
        return {
            "has_data": False,
            "plays_by_month": empty_series,
            "unique_tunes_by_month": empty_series,
            "plays_by_month_by_type": {"labels": [], "datasets": []},
            "plays_by_tune_type": {"labels": [], "values": []},
            "refresh_by_period": refresh_by_period,
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
    today_c = central_date_today()
    day_divisors: list[int] = []
    for key in ym_keys:
        y, m = int(key[:4]), int(key[5:7])
        month_labels.append(date(y, m, 1).strftime("%b %Y"))
        if (y, m) == (today_c.year, today_c.month):
            day_divisors.append(max(1, today_c.day))
        else:
            day_divisors.append(calendar.monthrange(y, m)[1])

    type_rows = conn.execute(
        """
        SELECT strftime('%Y-%m', p.date_played) AS ym,
               COALESCE(NULLIF(TRIM(COALESCE(s.tune_type, '')), ''), 'Other') AS tt,
               COUNT(*) AS c
        FROM practice_history p
        LEFT JOIN tunes s ON s.id = p.tune_id
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

    pie_totals: dict = {}
    for r in type_rows:
        pie_totals[r["tt"]] = pie_totals.get(r["tt"], 0) + int(r["c"])
    pie_sorted = sorted(pie_totals.items(), key=lambda x: -x[1])

    return {
        "has_data": True,
        "plays_by_month": {
            "labels": month_labels,
            "values": [plays_map.get(k, 0) for k in ym_keys],
            "day_divisors": day_divisors,
        },
        "unique_tunes_by_month": {
            "labels": month_labels,
            "values": [uniq_map.get(k, 0) for k in ym_keys],
        },
        "plays_by_month_by_type": {
            "labels": month_labels,
            "datasets": datasets,
        },
        "plays_by_tune_type": {
            "labels": [a[0] for a in pie_sorted],
            "values": [a[1] for a in pie_sorted],
        },
        "refresh_by_period": refresh_by_period,
    }

@app.route("/phrases", methods=["GET"])
def phrases_view():
    with get_db() as conn:
        phrases = conn.execute(
            """
            SELECT id, body, created_at
            FROM phrases
            ORDER BY id ASC
            """
        ).fetchall()
    return render_template("phrases.html", phrases=phrases)


@app.route("/phrases/subset-override", methods=["POST"])
def phrase_subset_override():
    settings = load_settings()
    settings["phrase_subset_override_enabled"] = request.form.get("enabled") == "1"
    save_settings(settings)
    return redirect(url_for("phrases_view"))


@app.route("/phrases/add", methods=["POST"])
def phrase_add():
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Phrase cannot be empty.", "error")
        return redirect(url_for("phrases_view"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO phrases (body, created_at) VALUES (?, ?)",
            (body, practice_timestamp_now()),
        )
        conn.commit()
    flash("Phrase added.", "success")
    return redirect(url_for("phrases_view"))


@app.route("/phrases/<int:phrase_id>/edit", methods=["POST"])
def phrase_edit(phrase_id):
    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Phrase cannot be empty.", "error")
        return redirect(url_for("phrases_view"))
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM phrases WHERE id = ?", (phrase_id,)).fetchone()
        if not row:
            flash("Phrase not found.", "error")
            return redirect(url_for("phrases_view"))
        conn.execute("UPDATE phrases SET body = ? WHERE id = ?", (body, phrase_id))
        conn.commit()
    flash("Phrase updated.", "success")
    return redirect(url_for("phrases_view"))


@app.route("/phrases/<int:phrase_id>/delete", methods=["POST"])
def phrase_delete(phrase_id):
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM phrases WHERE id = ?", (phrase_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
            conn.commit()
            flash("Phrase deleted.", "success")
        else:
            flash("Phrase not found.", "error")
    return redirect(url_for("phrases_view"))


@app.route("/charts")
@app.route("/statistics")
def charts_view():
    with get_db() as conn:
        stats_payload = _statistics_payload(conn)
    return render_template("statistics.html", stats_payload=stats_payload)


def _normalize_refresh_local_datetime(value: str) -> str | None:
    """US Central wall time as YYYY-MM-DDTHH:MM (datetime-local). Date-only → T00:00."""
    s = (value or "").strip().replace(" ", "T", 1)
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            date.fromisoformat(s)
            return f"{s}T00:00"
        except ValueError:
            return None
    if len(s) == 16 and s[10] == "T":
        try:
            datetime.fromisoformat(s)
            return s
        except ValueError:
            return None
    if len(s) >= 19 and s[10] == "T":
        try:
            dt = datetime.fromisoformat(s[:19])
            return dt.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            return None
    return None


def _refresh_range_valid_at(start_at: str, end_at: str | None) -> bool:
    if not end_at:
        return True
    return end_at >= start_at


def _refresh_at_to_sqlite_datetime(s: str) -> str | None:
    """YYYY-MM-DDTHH:MM → YYYY-MM-DD HH:MM:00 for practice_history comparison."""
    n = _normalize_refresh_local_datetime(s)
    if not n:
        return None
    return n.replace("T", " ") + ":00"


def _refresh_start_minute_keys(conn: sqlite3.Connection) -> set[str]:
    """YYYY-MM-DD HH:MM for each refresh_log.start_at (for collision checks)."""
    keys: set[str] = set()
    for r in conn.execute("SELECT start_at FROM refresh_log"):
        ssql = _refresh_at_to_sqlite_datetime(r["start_at"])
        if ssql:
            keys.add(ssql[:16])
    return keys


def _adjust_practice_timestamp_avoid_refresh_starts(
    conn: sqlite3.Connection, ts: str
) -> str:
    """If ts matches any refresh start (minute resolution), advance by 1 min until clear."""
    norm = normalize_practice_datetime(ts) or (ts or "").strip()
    if not norm:
        return ts
    try:
        dt = datetime.strptime(norm, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts
    start_keys = _refresh_start_minute_keys(conn)
    while dt.strftime("%Y-%m-%d %H:%M") in start_keys:
        dt += timedelta(minutes=1)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _refresh_days_round_up(
    start_at: str, end_at: str | None, now: datetime
) -> int:
    sn = _normalize_refresh_local_datetime(start_at)
    if not sn:
        return 0
    t0 = datetime.fromisoformat(sn)
    if end_at:
        en = _normalize_refresh_local_datetime(end_at)
        if not en:
            return 0
        t1 = datetime.fromisoformat(en)
    else:
        t1 = now
    delta = (t1 - t0).total_seconds()
    if delta < 0:
        return 0
    return max(1, math.ceil(delta / 86400.0))


def _refresh_practice_metrics(
    conn: sqlite3.Connection, start_sql: str, end_sql: str
) -> tuple[int, int]:
    n = conn.execute(
        """
        SELECT COUNT(*) AS n,
               COUNT(DISTINCT tune_id) AS tunes
        FROM practice_history
        WHERE datetime(date_played) > datetime(?)
          AND datetime(date_played) <= datetime(?)
        """,
        (start_sql, end_sql),
    ).fetchone()
    return int(n["n"]), int(n["tunes"])


def _refresh_unique_tunes_alphabetical(
    conn: sqlite3.Connection, start_sql: str, end_sql: str
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT DISTINCT t.id AS id, t.name AS name
        FROM practice_history p
        JOIN tunes t ON t.id = p.tune_id
        WHERE datetime(p.date_played) > datetime(?)
          AND datetime(p.date_played) <= datetime(?)
        ORDER BY t.name COLLATE NOCASE
        """,
        (start_sql, end_sql),
    ).fetchall()
    return [{"id": int(r["id"]), "name": r["name"]} for r in rows]


def _statistics_refresh_series(conn: sqlite3.Connection) -> dict:
    """Per refresh_log row: labels, day span, distinct tunes, tunes/day (charts)."""
    now = _central_now_minute()
    now_sql = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT id, refresh_number, start_at, end_at FROM refresh_log "
        "ORDER BY start_at ASC, id ASC"
    ).fetchall()
    labels: list[str] = []
    days: list[int] = []
    unique_tunes: list[int] = []
    tunes_per_day: list[float] = []
    for r in rows:
        num = int(r["refresh_number"])
        st = r["start_at"]
        sn = _normalize_refresh_local_datetime(st)
        start_date_only = sn[:10] if sn and len(sn) >= 10 else "?"
        labels.append(f"#{num}\n{start_date_only}")
        start_sql = _refresh_at_to_sqlite_datetime(st)
        if not start_sql:
            days.append(0)
            unique_tunes.append(0)
            tunes_per_day.append(0.0)
            continue
        if r["end_at"]:
            end_sql = _refresh_at_to_sqlite_datetime(r["end_at"])
            if not end_sql:
                end_sql = now_sql
        else:
            end_sql = now_sql
        d_sp = _refresh_days_round_up(r["start_at"], r["end_at"], now)
        _, ut = _refresh_practice_metrics(conn, start_sql, end_sql)
        days.append(int(d_sp))
        unique_tunes.append(int(ut))
        tunes_per_day.append(round(float(ut) / float(d_sp), 4) if d_sp > 0 else 0.0)
    return {
        "labels": labels,
        "days": days,
        "unique_tunes": unique_tunes,
        "tunes_per_day": tunes_per_day,
    }


@app.route("/refresh")
def refresh_view():
    now = _central_now_minute()
    now_sql = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, refresh_number, start_at, end_at FROM refresh_log "
            "ORDER BY id DESC"
        ).fetchall()
        refreshes = []
        for r in rows:
            start_sql = _refresh_at_to_sqlite_datetime(r["start_at"])
            if not start_sql:
                days = 0
                prac = 0
                utunes = 0
            else:
                if r["end_at"]:
                    end_sql = _refresh_at_to_sqlite_datetime(r["end_at"])
                    if not end_sql:
                        end_sql = now_sql
                else:
                    end_sql = now_sql
                days = _refresh_days_round_up(r["start_at"], r["end_at"], now)
                prac, utunes = _refresh_practice_metrics(conn, start_sql, end_sql)
            rd = dict(r)
            rd["days_span"] = days
            rd["practice_records"] = prac
            rd["unique_tune_count"] = utunes
            refreshes.append(rd)
    return render_template("refresh.html", refreshes=refreshes)


@app.route("/api/refresh/<int:refresh_id>/detail", methods=["GET"])
def api_refresh_detail(refresh_id: int):
    """JSON summary for a refresh period + unique tune names (A–Z)."""
    now = _central_now_minute()
    now_sql = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, refresh_number, start_at, end_at FROM refresh_log WHERE id = ?",
            (refresh_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Not found"}), 404
        start_sql = _refresh_at_to_sqlite_datetime(row["start_at"])
        if not start_sql:
            tunes: list[dict] = []
            days = 0
            prac = 0
            utunes = 0
        else:
            if row["end_at"]:
                end_sql = _refresh_at_to_sqlite_datetime(row["end_at"])
                if not end_sql:
                    end_sql = now_sql
            else:
                end_sql = now_sql
            days = _refresh_days_round_up(row["start_at"], row["end_at"], now)
            prac, utunes = _refresh_practice_metrics(conn, start_sql, end_sql)
            tunes = _refresh_unique_tunes_alphabetical(conn, start_sql, end_sql)
    return jsonify(
        {
            "ok": True,
            "id": row["id"],
            "refresh_number": row["refresh_number"],
            "start_at": row["start_at"],
            "end_at": row["end_at"],
            "days_span": days,
            "practice_records": prac,
            "unique_tune_count": utunes,
            "tunes": tunes,
        }
    )


@app.route("/api/refresh", methods=["POST"])
def api_refresh_create():
    now = _central_now_minute()
    at = now.strftime("%Y-%m-%dT%H:%M")
    with get_db() as conn:
        last = conn.execute(
            "SELECT id, start_at FROM refresh_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last:
            if at < last["start_at"]:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Current time is before the latest period start",
                        }
                    ),
                    400,
                )
            conn.execute(
                "UPDATE refresh_log SET end_at = ? WHERE id = ?",
                (at, last["id"]),
            )
        mx_row = conn.execute(
            "SELECT COALESCE(MAX(refresh_number), 0) FROM refresh_log"
        ).fetchone()
        next_n = int(mx_row[0]) + 1
        cur = conn.execute(
            "INSERT INTO refresh_log (refresh_number, start_at, end_at) "
            "VALUES (?, ?, ?)",
            (next_n, at, None),
        )
        new_id = int(cur.lastrowid)
        conn.commit()
    return jsonify(
        {
            "ok": True,
            "id": new_id,
            "refresh_number": next_n,
            "start_at": at,
            "end_at": None,
        }
    )


@app.route("/api/refresh/<int:refresh_id>", methods=["PATCH"])
def api_refresh_update(refresh_id):
    data = request.get_json(silent=True) or {}
    with get_db() as conn:
        row = conn.execute(
            "SELECT start_at, end_at, refresh_number FROM refresh_log WHERE id = ?",
            (refresh_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Not found"}), 404
        start_a = row["start_at"]
        end_a = row["end_at"]
        refresh_num = row["refresh_number"]

        if "start_at" in data:
            p = _normalize_refresh_local_datetime(str(data.get("start_at") or ""))
            if not p:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Invalid start_at; use YYYY-MM-DDTHH:MM",
                        }
                    ),
                    400,
                )
            start_a = p
        elif "refreshed_at" in data or "date" in data:
            raw = data.get("refreshed_at") or data.get("date") or ""
            donly = (raw or "").strip()[:10]
            try:
                date.fromisoformat(donly)
                tpart = "00:00"
                if start_a and "T" in str(start_a):
                    tpart = str(start_a).split("T", 1)[1][:5]
                start_a = f"{donly}T{tpart}"
            except ValueError:
                return (
                    jsonify({"ok": False, "error": "Invalid date; use YYYY-MM-DD"}),
                    400,
                )

        if "end_at" in data:
            er = data["end_at"]
            if er is None or str(er).strip() == "":
                end_a = None
            else:
                p_e = _normalize_refresh_local_datetime(str(er).strip())
                if not p_e:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "Invalid end_at; use YYYY-MM-DDTHH:MM",
                            }
                        ),
                        400,
                    )
                end_a = p_e

        if not _refresh_range_valid_at(start_a, end_a):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "End must be on or after start",
                    }
                ),
                400,
            )

        conn.execute(
            "UPDATE refresh_log SET start_at = ?, end_at = ? WHERE id = ?",
            (start_a, end_a, refresh_id),
        )
        conn.commit()
    return jsonify(
        {
            "ok": True,
            "start_at": start_a,
            "end_at": end_a,
            "refresh_number": refresh_num,
        }
    )


@app.route("/api/refresh/<int:refresh_id>", methods=["DELETE"])
def api_refresh_delete(refresh_id):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM refresh_log WHERE id = ?", (refresh_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True})


def _lesson_tunes_dir() -> Path:
    d = LESSON_TUNES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lesson_tune_resolved_file(filename: str) -> Path | None:
    """If filename is a single path segment and exists under lesson_tunes, return its path; else None."""
    if not filename or "\\" in filename or "/" in filename or filename in (".", ".."):
        return None
    d = _lesson_tunes_dir().resolve()
    target = (d / filename).resolve()
    try:
        target.relative_to(d)
    except ValueError:
        return None
    return target if target.is_file() else None


_LESSON_AUDIO_EXT = frozenset(
    {"mp3", "m4a", "wav", "ogg", "oga", "flac", "aac", "opus"}
)
_LESSON_VIDEO_EXT = frozenset({"mp4", "webm", "mov", "ogv", "m4v"})
_LESSON_IMAGE_EXT = frozenset(
    {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"}
)

# Explicit MIME for lesson files (Windows/registry guesses can be wrong for media).
_LESSON_EXT_TO_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "opus": "audio/opus",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "ogv": "video/ogg",
    "m4v": "video/x-m4v",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "bmp": "image/bmp",
    "avif": "image/avif",
}


def _lesson_serve_mimetype(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in _LESSON_EXT_TO_MIME:
        return _LESSON_EXT_TO_MIME[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _lesson_embed_media_type(filename: str, embed_kind: str | None) -> str | None:
    """MIME for <source type=\"…\"> on audio/video elements."""
    if embed_kind not in ("audio", "video"):
        return None
    ext = Path(filename).suffix.lower().lstrip(".")
    return _LESSON_EXT_TO_MIME.get(ext)


def _lesson_file_embed_kind(filename: str) -> str | None:
    """Return embed type for in-modal preview, or None for download-only."""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in _LESSON_AUDIO_EXT:
        return "audio"
    if ext in _LESSON_VIDEO_EXT:
        return "video"
    if ext == "pdf":
        return "pdf"
    if ext in _LESSON_IMAGE_EXT:
        return "image"
    return None


def _human_file_size(num: int) -> str:
    n = float(max(0, num))
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024.0 or unit == "GB":
            s = f"{n:.1f}".rstrip("0").rstrip(".")
            return f"{s} {unit}"
    return "0 B"


def tune_lesson_files_rows(tune_row) -> list[dict]:
    """Ordered unique file names from tune.lessons with size/mtime when present on disk."""
    raw = (tune_row["lessons"] or "") if tune_row else ""
    names: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        name = (line or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    rows: list[dict] = []
    for name in names:
        target = _lesson_tune_resolved_file(name)
        if target:
            st = target.stat()
            ek = _lesson_file_embed_kind(name)
            rows.append(
                {
                    "name": name,
                    "size_label": _human_file_size(st.st_size),
                    "modified_label": datetime.fromtimestamp(st.st_mtime).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "missing": False,
                    "embed_kind": ek,
                    "media_type": _lesson_embed_media_type(name, ek),
                }
            )
        else:
            rows.append(
                {
                    "name": name,
                    "size_label": "—",
                    "modified_label": "—",
                    "missing": True,
                    "embed_kind": None,
                    "media_type": None,
                }
            )
    return rows


def list_lesson_tune_files() -> list[dict]:
    d = _lesson_tunes_dir()
    base = d.resolve()
    rows: list[dict] = []
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        try:
            p.resolve().relative_to(base)
        except ValueError:
            continue
        st = p.stat()
        rows.append(
            {
                "name": p.name,
                "size": st.st_size,
                "size_label": _human_file_size(st.st_size),
            }
        )
    return rows


def linked_tunes_for_lesson_filename(conn: sqlite3.Connection, filename: str) -> list[dict]:
    """Tunes whose stored `lessons` text includes this file name (line match, case-insensitive)."""
    low = filename.lower()
    out: list[dict] = []
    for r in conn.execute(
        "SELECT id, name, lessons FROM tunes "
        "WHERE lessons IS NOT NULL AND TRIM(COALESCE(lessons, '')) != ''"
    ):
        for line in lessons_list_filter(r["lessons"]):
            if line.lower() == low:
                out.append({"id": int(r["id"]), "name": (r["name"] or "").strip()})
                break
    out.sort(key=lambda x: (x["name"] or "").lower())
    return out


@app.route("/lesson-tunes")
def lesson_tunes_view():
    files = list_lesson_tune_files()
    with get_db() as conn:
        for f in files:
            f["linked_tunes"] = linked_tunes_for_lesson_filename(conn, f["name"])
        picker_tunes = [
            {"id": int(r["id"]), "name": (r["name"] or "").strip()}
            for r in conn.execute("SELECT id, name FROM tunes ORDER BY name COLLATE NOCASE")
        ]
    return render_template(
        "lesson_tunes.html", files=files, picker_tunes=picker_tunes
    )


@app.route("/lesson-tunes/download/<filename>")
def lesson_tunes_download(filename: str):
    target = _lesson_tune_resolved_file(filename)
    if not target:
        abort(404)
    d = _lesson_tunes_dir().resolve()
    return send_from_directory(
        d,
        target.name,
        as_attachment=False,
        mimetype=_lesson_serve_mimetype(target.name),
    )


def list_lesson_tune_audio_filenames() -> list[str]:
    """File names in lesson_tunes that use a known audio extension (same listing rules as lesson page)."""
    return [
        row["name"]
        for row in list_lesson_tune_files()
        if Path(row["name"]).suffix.lower().lstrip(".") in _LESSON_AUDIO_EXT
    ]


@app.route("/test")
def test_view():
    files = list_lesson_tune_audio_filenames()
    audio_entries = [
        {"name": name, "url": url_for("lesson_tunes_download", filename=name)}
        for name in files
    ]
    return render_template("test.html", audio_entries=audio_entries)


@app.route("/times-played")
def times_played():
    req_tune_type = request.args.get("tune_type", "").strip()
    psr_filter = _psr_filter_from_request()
    period = request.args.get("period", "1m")
    sort = request.args.get("sort", "most")
    _tp_sort = frozenset({"most", "least", "tune_num", "tune_num_d"})
    if sort not in _tp_sort:
        sort = "most"
    search = request.args.get("search", "").strip()

    type_cond_parts = ["TRIM(COALESCE(s.tune_type, '')) != ''"]
    type_params: list = []
    type_where_sql = "WHERE " + " AND ".join(type_cond_parts)

    with get_db() as conn:
        type_rows = conn.execute(
            "SELECT DISTINCT TRIM(s.tune_type) AS t FROM tunes s "
            + type_where_sql
            + " ORDER BY t COLLATE NOCASE",
            type_params,
        ).fetchall()
        types_for_filter = [str(r["t"]) for r in type_rows if r["t"] is not None]

        tune_type = req_tune_type if req_tune_type in types_for_filter else ""

        reset_bound = _last_reset_start_sqlite(conn)
        psr_frags, psr_params = _psr_sql_fragments(psr_filter, reset_bound)

        if sort == "most":
            order = f"period_count DESC, {SORT_NAME} ASC"
        elif sort == "least":
            order = f"period_count ASC, {SORT_NAME} ASC"
        elif sort == "tune_num":
            order = (
                "CASE WHEN s.tune_num IS NULL THEN 1 ELSE 0 END, s.tune_num ASC, "
                + SORT_NAME
                + " ASC"
            )
        else:
            order = (
                "CASE WHEN s.tune_num IS NULL THEN 1 ELSE 0 END, s.tune_num DESC, "
                + SORT_NAME
                + " ASC"
            )

        conditions, params = [], []
        if tune_type:
            conditions.append("TRIM(COALESCE(s.tune_type, '')) = ?")
            params.append(tune_type)
        conditions.extend(psr_frags)
        params.extend(psr_params)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        period_start = central_period_start_date(period)
        date_filter_sql = ""
        period_params: list = []
        if period_start is not None:
            date_filter_sql = "AND date(p.date_played) >= ?"
            period_params = [period_start.isoformat()]

        sql = f"""
            SELECT s.*,
                   COUNT(p.id) AS period_count,
                   (SELECT MAX(ph.date_played) FROM practice_history ph
                    WHERE ph.tune_id = s.id) AS last_practiced,
                   (SELECT CASE WHEN MAX(ph.date_played) IS NULL THEN NULL
                                ELSE CAST(ROUND(julianday('{_julianday_anchor_sql()}') - julianday(MAX(ph.date_played))) AS INTEGER)
                           END
                      FROM practice_history ph WHERE ph.tune_id = s.id) AS days_since_last
            FROM tunes s
            LEFT JOIN practice_history p
                ON p.tune_id = s.id
               {date_filter_sql}
            {where}
            GROUP BY s.id
            ORDER BY {order}
        """
        tunes = conn.execute(sql, period_params + params).fetchall()

    return render_template(
        "times_played.html",
        tunes=tunes,
        tune_type=tune_type,
        psr_filter=psr_filter,
        types_for_filter=types_for_filter,
        period=period,
        sort=sort,
        search=search,
        period_options=PERIOD_OPTIONS,
    )


@app.route("/table")
def table_view():
    req_tune_type = request.args.get("tune_type", "").strip()
    psr_filter = _psr_filter_from_request()
    req_pg = request.args.get("practice_group", "").strip()
    filter_pg = map_practice_group_token(req_pg) if req_pg else None
    # Same semantics as /sets: played=asc → newest last_practiced first; played=desc → oldest first.
    practice_group_played_order = "asc"
    if filter_pg:
        req_played = (request.args.get("played") or "asc").strip().lower()
        practice_group_played_order = (
            req_played if req_played in ("asc", "desc") else "asc"
        )

    type_cond_parts = ["TRIM(COALESCE(s.tune_type, '')) != ''"]
    type_params: list = []
    type_where_sql = "WHERE " + " AND ".join(type_cond_parts)

    order = """
        ORDER BY
            CASE
                WHEN LOWER(s.name) LIKE 'the %' THEN LOWER(SUBSTR(s.name, 5))
                WHEN LOWER(s.name) LIKE 'a %'   THEN LOWER(SUBSTR(s.name, 3))
                ELSE LOWER(s.name)
            END
    """
    with get_db() as conn:
        reset_bound = _last_reset_start_sqlite(conn)
        practiced_since = _tune_ids_with_practice_since(conn, reset_bound)

        type_rows = conn.execute(
            "SELECT DISTINCT TRIM(s.tune_type) AS t FROM tunes s "
            + type_where_sql
            + " ORDER BY t COLLATE NOCASE",
            type_params,
        ).fetchall()
        types_for_filter_all = [str(r["t"]) for r in type_rows if r["t"] is not None]

        practice_group_label = None
        if filter_pg:
            all_tunes = conn.execute(
                TUNES_WITH_STATS + order, (_julianday_anchor_sql(),)
            ).fetchall()
            in_group = [
                t
                for t in all_tunes
                if filter_pg in practice_groups_selected_filter(t["practice_group"])
            ]
            types_for_filter = sorted(
                {str(t["tune_type"]).strip() for t in in_group if (t["tune_type"] or "").strip()},
                key=str.lower,
            )
            tune_type = req_tune_type if req_tune_type in types_for_filter else ""
            tunes = [
                t for t in in_group if not tune_type or str(t["tune_type"] or "").strip() == tune_type
            ]
            if psr_filter == PSR_FILTER_PSR:
                tunes = [t for t in tunes if int(t["id"]) in practiced_since]
            elif psr_filter == PSR_FILTER_NOT_PSR:
                tunes = [t for t in tunes if int(t["id"]) not in practiced_since]
            practice_group_label = filter_pg

            def _pg_last_played_sort_key(row: sqlite3.Row) -> tuple:
                lp = row["last_practiced"]
                if not lp:
                    return (0, "")
                return (1, str(lp))

            if practice_group_played_order == "asc":
                tunes.sort(key=_pg_last_played_sort_key, reverse=True)
            else:
                tunes.sort(
                    key=lambda r: (
                        0 if r["last_practiced"] else 1,
                        r["last_practiced"] or "",
                    )
                )
        else:
            tune_type = req_tune_type if req_tune_type in types_for_filter_all else ""
            conditions, params = [], []
            if tune_type:
                conditions.append("TRIM(COALESCE(s.tune_type, '')) = ?")
                params.append(tune_type)
            psr_frags, psr_params = _psr_sql_fragments(psr_filter, reset_bound)
            conditions.extend(psr_frags)
            params.extend(psr_params)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            tunes = conn.execute(
                TUNES_WITH_STATS + where + order,
                [_julianday_anchor_sql()] + params,
            ).fetchall()
            types_for_filter = types_for_filter_all

    tune_type_suggestions, key_suggestions = table_tune_key_suggestions(tunes)
    return render_template(
        "table.html",
        tunes=tunes,
        tune_type=tune_type,
        psr_filter=psr_filter,
        types_for_filter=types_for_filter,
        tune_type_suggestions=tune_type_suggestions,
        key_suggestions=key_suggestions,
        practice_group_label=practice_group_label,
        practice_group_played_order=practice_group_played_order,
    )


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(silent=True) or {}
    settings = load_settings()
    for key, default in SETTINGS_DEFAULTS.items():
        if key not in data:
            continue
        v = data[key]
        if not isinstance(v, type(default)):
            return jsonify({"ok": False, "error": f"Invalid type for '{key}'"}), 400
        settings[key] = v
    save_settings(settings)
    return jsonify({"ok": True})


@app.route("/api/tune/<int:tune_id>", methods=["POST"])
def update_tune_field(tune_id):
    data  = request.get_json()
    field = data.get("field", "")
    raw = data.get("value", "")

    allowed = {
        "name",
        "tune_type",
        "key",
        "composer",
        "tune_num",
        "link_1",
        "link_2",
        "link_3",
        "notes",
        "practice_group",
        "lessons",
    }
    if field not in allowed:
        return {"error": "Invalid field"}, 400

    if field == "notes":
        value = raw if isinstance(raw, str) else str(raw)
    elif field == "lessons":
        value = normalize_lessons_stored(raw if isinstance(raw, str) else str(raw))
    elif field == "composer":
        value = raw.strip() if isinstance(raw, str) else str(raw).strip()
    elif field == "practice_group":
        if isinstance(raw, list):
            value = format_practice_groups_from_list([str(x).strip() for x in raw])
        else:
            value = normalize_practice_groups_stored(
                raw.strip() if isinstance(raw, str) else str(raw).strip()
            )
    elif field == "key":
        if isinstance(raw, list):
            value = format_keys_from_list([str(x).strip() for x in raw])
        else:
            value = normalize_keys_stored(
                raw.strip() if isinstance(raw, str) else str(raw).strip()
            )
    elif field == "tune_num":
        value, err = _parse_tune_num_update(raw)
        if err:
            return {"ok": False, "error": err}, 400
    else:
        value = raw.strip() if isinstance(raw, str) else str(raw).strip()

    if field == "name" and not value:
        return {"error": "Name cannot be empty"}, 400

    with get_db() as conn:
        conn.execute(f"UPDATE tunes SET {field} = ? WHERE id = ?", (value, tune_id))
        conn.commit()
    return {"ok": True}


@app.route("/api/lesson-file-tune", methods=["POST"])
def lesson_file_tune_link():
    """Add or remove one lesson file name on a tune's `lessons` field (newline-separated)."""
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    remove = bool(data.get("remove"))
    try:
        tune_id = int(data.get("tune_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid tune"}), 400
    if not filename:
        return jsonify({"ok": False, "error": "Missing filename"}), 400
    # Path segments only (same rule as _lesson_tune_resolved_file).
    if "\\" in filename or "/" in filename or filename in (".", ".."):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400
    # Adding a link requires the file on disk. Removing must work even when the
    # file is missing (stale DB rows, moved lesson_tunes dir, prod vs dev paths).
    if not remove and _lesson_tune_resolved_file(filename) is None:
        return jsonify({"ok": False, "error": "File not found"}), 400
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, lessons FROM tunes WHERE id = ?",
            (tune_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Tune not found"}), 404
        lines = list(lessons_list_filter(row["lessons"]))
        low = filename.lower()
        if remove:
            lines = [ln for ln in lines if ln.lower() != low]
        else:
            if any(ln.lower() == low for ln in lines):
                return jsonify({"ok": True, "duplicate": True})
            lines.append(filename)
        new_val = normalize_lessons_stored("\n".join(lines))
        conn.execute("UPDATE tunes SET lessons = ? WHERE id = ?", (new_val, tune_id))
        conn.commit()
    return jsonify({"ok": True, "duplicate": False})


@app.route("/sets/create-draft", methods=["POST"])
def create_set_draft():
    """Create an empty set and return its panel URL (for Add New Set → same UI as View Set)."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO sets (description, type, key) VALUES (?, ?, ?)",
            ("", "", ""),
        )
        set_id = cur.lastrowid
        conn.commit()
    return jsonify(
        {
            "ok": True,
            "set_id": set_id,
            "panel_url": url_for("set_panel", set_id=set_id, new=1),
        }
    )


@app.route("/set/<int:set_id>/panel")
def set_panel(set_id):
    is_new = request.args.get("new") == "1"
    panel_title = "Add New Set" if is_new else "View Set"
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            return "Not found", 404
        set_tunes = conn.execute(
            """
            SELECT s.id, s.name, s.tune_type, s.key
            FROM tunes s
            JOIN set_tunes ss ON ss.tune_id = s.id
            WHERE ss.set_id = ?
            ORDER BY ss.sort_order ASC, ss.tune_id ASC
            """,
            (set_id,),
        ).fetchall()
        tunes_available_for_set = conn.execute(
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
        ).fetchall()
    set_type_suggestions = suggestions_merge_keys(
        distinct_set_types_union(), row["type"] if row["type"] is not None else ""
    )
    set_key_suggestions = suggestions_merge_keys(
        distinct_keys(), row["key"] if row["key"] is not None else ""
    )
    tune_picker_add_options = [
        {"id": int(r["id"]), "name": r["name"]} for r in tunes_available_for_set
    ]
    tune_picker_all = [
        {"id": int(r["id"]), "name": r["name"]} for r in all_tune_rows
    ]
    set_tune_ids_json = [int(r["id"]) for r in set_tunes]
    tune_picker_bundle = {
        "add": tune_picker_add_options,
        "allTunes": tune_picker_all,
        "setTuneIds": set_tune_ids_json,
    }
    panel_url = url_for("set_panel", set_id=set_id, new=1) if is_new else url_for("set_panel", set_id=set_id)
    return render_template(
        "set_panel.html",
        set_record=row,
        set_type_suggestions=set_type_suggestions,
        set_key_suggestions=set_key_suggestions,
        set_tunes=set_tunes,
        tunes_available_for_set=tunes_available_for_set,
        tune_picker_add_options=tune_picker_add_options,
        tune_picker_bundle=tune_picker_bundle,
        panel_title=panel_title,
        is_new=is_new,
        panel_url=panel_url,
    )


@app.route("/set/<int:set_id>/tunes/add", methods=["POST"])
def add_tune_to_set(set_id):
    is_modal = request.form.get("modal") == "1"
    raw = request.form.get("tune_id", "").strip()
    try:
        tune_id = int(raw)
    except ValueError:
        if is_modal:
            return jsonify({"ok": False, "error": "Invalid tune."}), 400
        flash("Invalid tune.", "error")
        return redirect(url_for("sets_view"))
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM sets WHERE id = ?", (set_id,)).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Set not found."}), 404
            flash("Set not found.", "error")
            return redirect(url_for("sets_view"))
        if not conn.execute("SELECT 1 FROM tunes WHERE id = ?", (tune_id,)).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Tune not found."}), 400
            flash("Tune not found.", "error")
            return redirect(url_for("sets_view"))
        if conn.execute(
            "SELECT 1 FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, tune_id),
        ).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "That tune is already in the set."}), 400
            flash("That tune is already in the set.", "error")
            return redirect(url_for("sets_view"))
        max_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM set_tunes WHERE set_id = ?",
            (set_id,),
        ).fetchone()
        next_order = (max_row["m"] if max_row else -1) + 1
        conn.execute(
            "INSERT INTO set_tunes (set_id, tune_id, sort_order) VALUES (?, ?, ?)",
            (set_id, tune_id, next_order),
        )
        conn.commit()
    if is_modal:
        return jsonify({"ok": True})
    return redirect(url_for("sets_view"))


@app.route("/set/<int:set_id>/tunes/<int:tune_id>/replace", methods=["POST"])
def replace_tune_in_set(set_id, tune_id):
    """Swap one set slot to a different tune (same sort_order)."""
    is_modal = request.form.get("modal") == "1"
    raw = request.form.get("new_tune_id", "").strip()
    try:
        new_tune_id = int(raw)
    except ValueError:
        if is_modal:
            return jsonify({"ok": False, "error": "Invalid tune."}), 400
        flash("Invalid tune.", "error")
        return redirect(url_for("sets_view"))
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM sets WHERE id = ?", (set_id,)).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Set not found."}), 404
            flash("Set not found.", "error")
            return redirect(url_for("sets_view"))
        slot = conn.execute(
            "SELECT sort_order FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, tune_id),
        ).fetchone()
        if not slot:
            if is_modal:
                return jsonify({"ok": False, "error": "Tune is not in this set."}), 404
            flash("Tune is not in this set.", "error")
            return redirect(url_for("sets_view"))
        sort_order = slot["sort_order"]
        if new_tune_id == tune_id:
            if is_modal:
                return jsonify({"ok": True})
            return redirect(url_for("sets_view"))
        if not conn.execute("SELECT 1 FROM tunes WHERE id = ?", (new_tune_id,)).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Tune not found."}), 400
            flash("Tune not found.", "error")
            return redirect(url_for("sets_view"))
        if conn.execute(
            "SELECT 1 FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, new_tune_id),
        ).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "That tune is already in the set."}), 400
            flash("That tune is already in the set.", "error")
            return redirect(url_for("sets_view"))
        conn.execute(
            "DELETE FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, tune_id),
        )
        conn.execute(
            "INSERT INTO set_tunes (set_id, tune_id, sort_order) VALUES (?, ?, ?)",
            (set_id, new_tune_id, sort_order),
        )
        conn.commit()
    if is_modal:
        return jsonify({"ok": True})
    return redirect(url_for("sets_view"))


@app.route("/set/<int:set_id>/tunes/<int:tune_id>/remove", methods=["POST"])
def remove_tune_from_set(set_id, tune_id):
    """Remove a tune from the set only (junction row); does not delete the tune."""
    is_modal = request.form.get("modal") == "1"
    if request.form.get("confirm_delete") != "1":
        if is_modal:
            return jsonify({"ok": False, "error": "Confirmation required."}), 400
        flash("Action was not confirmed.", "error")
        return redirect(url_for("sets_view"))
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM sets WHERE id = ?", (set_id,)).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Set not found."}), 404
            flash("Set not found.", "error")
            return redirect(url_for("sets_view"))
        if not conn.execute(
            "SELECT 1 FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, tune_id),
        ).fetchone():
            if is_modal:
                return jsonify({"ok": False, "error": "Tune is not in this set."}), 404
            flash("Tune is not in this set.", "error")
            return redirect(url_for("sets_view"))
        conn.execute(
            "DELETE FROM set_tunes WHERE set_id = ? AND tune_id = ?",
            (set_id, tune_id),
        )
        remaining = conn.execute(
            """
            SELECT tune_id FROM set_tunes
            WHERE set_id = ?
            ORDER BY sort_order ASC, tune_id ASC
            """,
            (set_id,),
        ).fetchall()
        for i, r in enumerate(remaining):
            conn.execute(
                """
                UPDATE set_tunes SET sort_order = ?
                WHERE set_id = ? AND tune_id = ?
                """,
                (i, set_id, r["tune_id"]),
            )
        conn.commit()
    if is_modal:
        return jsonify({"ok": True})
    return redirect(url_for("sets_view"))


@app.route("/set/<int:set_id>/tunes/reorder", methods=["POST"])
def reorder_set_tunes(set_id):
    data = request.get_json(silent=True) or {}
    ids = data.get("tune_ids")
    if not isinstance(ids, list) or not all(
        isinstance(x, int) or (isinstance(x, str) and str(x).isdigit()) for x in ids
    ):
        return jsonify({"ok": False, "error": "Invalid payload."}), 400
    try:
        tune_ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid tune ids."}), 400
    if len(tune_ids) != len(set(tune_ids)):
        return jsonify({"ok": False, "error": "Duplicate tune in order."}), 400
    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM sets WHERE id = ?", (set_id,)).fetchone():
            return jsonify({"ok": False, "error": "Set not found."}), 404
        cur = conn.execute(
            """
            SELECT tune_id FROM set_tunes
            WHERE set_id = ?
            ORDER BY sort_order ASC, tune_id ASC
            """,
            (set_id,),
        )
        existing = [r["tune_id"] for r in cur.fetchall()]
        if len(tune_ids) != len(existing) or sorted(tune_ids) != sorted(existing):
            return jsonify(
                {"ok": False, "error": "Order must include each tune exactly once."}
            ), 400
        for i, sid in enumerate(tune_ids):
            conn.execute(
                """
                UPDATE set_tunes SET sort_order = ?
                WHERE set_id = ? AND tune_id = ?
                """,
                (i, set_id, sid),
            )
        conn.commit()
    return jsonify({"ok": True})


@app.route("/set/<int:set_id>/edit", methods=["POST"])
def edit_set(set_id):
    is_modal = request.form.get("modal") == "1"
    description = request.form.get("description", "").strip()
    type_stored = _set_types_from_request_form()
    key_stored = _keys_from_request_form()
    with get_db() as conn:
        row = conn.execute("SELECT type FROM sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            if is_modal:
                return jsonify({"ok": False, "error": "Set not found."}), 404
            flash("Set not found.", "error")
            return redirect(url_for("sets_view"))
    with get_db() as conn:
        conn.execute(
            "UPDATE sets SET description = ?, type = ?, key = ? WHERE id = ?",
            (description, type_stored, key_stored, set_id),
        )
        conn.commit()
    if is_modal:
        return jsonify({"ok": True})
    return redirect(url_for("sets_view"))


@app.route("/set/<int:set_id>/delete", methods=["POST"])
def delete_set(set_id):
    is_modal = request.form.get("modal") == "1"
    if request.form.get("confirm_delete") != "1":
        if is_modal:
            return jsonify({"ok": False, "error": "Confirmation required."}), 400
        flash("Action was not confirmed.", "error")
        return redirect(url_for("sets_view"))
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM sets WHERE id = ?", (set_id,)).fetchone()
        if exists:
            _backup_tunes_db(conn)
            conn.execute("DELETE FROM sets WHERE id = ?", (set_id,))
            conn.commit()
            if is_modal:
                return jsonify({"ok": True})
        else:
            if is_modal:
                return jsonify({"ok": False, "error": "Set not found."}), 404
            flash("Set not found.", "error")
    return redirect(url_for("sets_view"))


@app.route("/sets", methods=["GET"])
def sets_view():
    # Mobile "Asc" / "Desc" toggle: UI label is intentionally inverted vs sort direction.
    # played=asc → newest last_played first (DESC). played=desc → oldest first (ASC).
    req_played = (request.args.get("played") or "asc").strip().lower()
    if req_played not in ("asc", "desc"):
        req_played = "asc"
    with get_db() as conn:
        has_sets_in_db = (
            conn.execute("SELECT 1 FROM sets LIMIT 1").fetchone() is not None
        )
        sets = conn.execute(
            "SELECT id, description, type FROM sets ORDER BY id DESC",
        ).fetchall()
        set_ids = [r["id"] for r in sets]
        last_by_set = {}
        tunes_by_set = {sid: [] for sid in set_ids}
        if set_ids:
            ph = ",".join("?" * len(set_ids))
            for r in conn.execute(
                f"""
                SELECT set_id, MAX(date_practiced) AS last_practiced
                FROM set_practice
                WHERE set_id IN ({ph})
                GROUP BY set_id
                """,
                set_ids,
            ):
                last_by_set[r["set_id"]] = r["last_practiced"]
            for r in conn.execute(
                f"""
                SELECT ss.set_id, s.name
                FROM set_tunes ss
                JOIN tunes s ON s.id = ss.tune_id
                WHERE ss.set_id IN ({ph})
                ORDER BY ss.set_id, ss.sort_order ASC, ss.tune_id ASC
                """,
                set_ids,
            ):
                tunes_by_set[r["set_id"]].append(r["name"])
        sets_display = []
        for r in sets:
            lp = last_by_set.get(r["id"])
            days_since_last = None
            if lp:
                try:
                    days_since_last = (
                        central_date_today() - date.fromisoformat(str(lp)[:10])
                    ).days
                except ValueError:
                    pass
            sets_display.append(
                {
                    "id": r["id"],
                    "description": r["description"],
                    "type": r["type"],
                    "last_practiced": lp,
                    "days_since_last": days_since_last,
                    "tunes_names": ", ".join(tunes_by_set[r["id"]]),
                }
            )

        def _last_played_sort_key(row: dict) -> tuple:
            lp = row["last_practiced"]
            if not lp:
                return (0, "")
            return (1, str(lp))

        if req_played == "asc":
            sets_display.sort(key=_last_played_sort_key, reverse=True)
        else:
            sets_display.sort(
                key=lambda x: (0 if x["last_practiced"] else 1, x["last_practiced"] or "")
            )
    return render_template(
        "sets.html",
        sets=sets_display,
        has_sets_in_db=has_sets_in_db,
        sets_played_order=req_played,
    )


HISTORY_PAGE_SIZE = 100
HISTORY_PAGE_WINDOW = 5


def _history_pagination_page_numbers(current: int, total_pages: int, window: int = HISTORY_PAGE_WINDOW) -> list[int]:
    """Sliding window of page indices (1-based) around `current`."""
    if total_pages <= 0:
        return []
    if total_pages <= window:
        return list(range(1, total_pages + 1))
    half = window // 2
    start = current - half
    if start < 1:
        start = 1
    if start + window - 1 > total_pages:
        start = total_pages - window + 1
    return list(range(start, start + window))


@app.route("/history")
def history_view():
    kind = request.args.get("view", "tunes")
    if kind not in ("tunes", "sets"):
        kind = "tunes"
    try:
        page = int(request.args.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(1, page)

    with get_db() as conn:
        type_arg = request.args.get("type", "").strip()
        if kind == "sets":
            type_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(s.type) AS t
                FROM sets s
                JOIN set_practice sp ON sp.set_id = s.id
                WHERE TRIM(COALESCE(s.type, '')) != ''
                ORDER BY t COLLATE NOCASE
                """
            ).fetchall()
            history_types_for_filter = [str(r["t"]) for r in type_rows if r["t"] is not None]
            type_filter = type_arg if type_arg in history_types_for_filter else ""
            type_sql = ""
            type_params: list = []
            if type_filter:
                type_sql = " AND TRIM(COALESCE(s.type, '')) = ?"
                type_params.append(type_filter)
            total = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM set_practice sp
                JOIN sets s ON s.id = sp.set_id
                WHERE 1=1{type_sql}
                """,
                type_params,
            ).fetchone()[0]
            total_pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
            page = min(page, total_pages)
            offset = (page - 1) * HISTORY_PAGE_SIZE
            records_raw = conn.execute(
                f"""
                SELECT sp.id, sp.date_practiced, sp.set_id,
                       s.description, s.type
                FROM set_practice sp
                JOIN sets s ON s.id = sp.set_id
                WHERE 1=1{type_sql}
                ORDER BY sp.date_practiced DESC,
                CASE
                    WHEN LOWER(COALESCE(NULLIF(TRIM(s.description), ''), s.type)) LIKE 'the %'
                        THEN LOWER(SUBSTR(COALESCE(NULLIF(TRIM(s.description), ''), s.type), 5))
                    WHEN LOWER(COALESCE(NULLIF(TRIM(s.description), ''), s.type)) LIKE 'a %'
                        THEN LOWER(SUBSTR(COALESCE(NULLIF(TRIM(s.description), ''), s.type), 3))
                    ELSE LOWER(COALESCE(NULLIF(TRIM(s.description), ''), s.type))
                END ASC
                LIMIT ? OFFSET ?
                """,
                (*type_params, HISTORY_PAGE_SIZE, offset),
            ).fetchall()
            unique_set_ids = list(dict.fromkeys(r["set_id"] for r in records_raw))
            tunes_by_set = {sid: [] for sid in unique_set_ids}
            if unique_set_ids:
                ph = ",".join("?" * len(unique_set_ids))
                for row in conn.execute(
                    f"""
                    SELECT ss.set_id, s.name
                    FROM set_tunes ss
                    JOIN tunes s ON s.id = ss.tune_id
                    WHERE ss.set_id IN ({ph})
                    ORDER BY ss.set_id, ss.sort_order ASC, ss.tune_id ASC
                    """,
                    unique_set_ids,
                ):
                    tunes_by_set[row["set_id"]].append(row["name"])
            records = []
            for r in records_raw:
                d = {k: r[k] for k in r.keys()}
                d["tunes_names"] = ", ".join(tunes_by_set.get(r["set_id"], []))
                records.append(d)
        else:
            type_rows = conn.execute(
                """
                SELECT DISTINCT TRIM(s.tune_type) AS t
                FROM tunes s
                JOIN practice_history p ON p.tune_id = s.id
                WHERE TRIM(COALESCE(s.tune_type, '')) != ''
                ORDER BY t COLLATE NOCASE
                """
            ).fetchall()
            history_types_for_filter = [str(r["t"]) for r in type_rows if r["t"] is not None]
            type_filter = type_arg if type_arg in history_types_for_filter else ""
            type_sql = ""
            type_params: list = []
            if type_filter:
                type_sql = " AND TRIM(COALESCE(s.tune_type, '')) = ?"
                type_params.append(type_filter)
            total = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM practice_history p
                JOIN tunes s ON s.id = p.tune_id
                WHERE 1=1{type_sql}
                """,
                type_params,
            ).fetchone()[0]
            total_pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
            page = min(page, total_pages)
            offset = (page - 1) * HISTORY_PAGE_SIZE
            records = conn.execute(
                f"""
                SELECT p.id, p.date_played, s.id AS tune_id, s.name,
                       s.tune_type, s.key,
                       (SELECT COUNT(*) FROM practice_history ph WHERE ph.tune_id = s.id) AS practice_count
                FROM practice_history p
                JOIN tunes s ON s.id = p.tune_id
                WHERE 1=1{type_sql}
                ORDER BY p.date_played DESC,
                CASE
                    WHEN LOWER(s.name) LIKE 'the %' THEN LOWER(SUBSTR(s.name, 5))
                    WHEN LOWER(s.name) LIKE 'a %'   THEN LOWER(SUBSTR(s.name, 3))
                    ELSE LOWER(s.name)
                END ASC
                LIMIT ? OFFSET ?
                """,
                (*type_params, HISTORY_PAGE_SIZE, offset),
            ).fetchall()

    history_q_tunes: dict = {}
    history_q_sets: dict = {"view": "sets"}
    if type_filter:
        history_q_tunes["type"] = type_filter
        history_q_sets["type"] = type_filter

    return render_template(
        "history.html",
        history_kind=kind,
        records=records,
        history_page=page,
        history_total=total,
        history_page_size=HISTORY_PAGE_SIZE,
        history_total_pages=total_pages,
        history_page_nums=_history_pagination_page_numbers(page, total_pages),
        history_types_for_filter=history_types_for_filter,
        history_type_filter=type_filter,
        history_q_tunes=history_q_tunes,
        history_q_sets=history_q_sets,
    )


@app.route("/api/practice/<int:record_id>", methods=["POST"])
def update_practice_date(record_id):
    data = request.get_json(silent=True) or {}
    value = (data.get("value") or "").strip()
    norm = normalize_practice_datetime(value)
    if not norm:
        return {"error": "Invalid date or time"}, 400
    with get_db() as conn:
        conn.execute("UPDATE practice_history SET date_played = ? WHERE id = ?", (norm, record_id))
        conn.commit()
    return {"ok": True}


@app.route("/api/set-practice/<int:record_id>", methods=["POST"])
def update_set_practice_date(record_id):
    data = request.get_json(silent=True) or {}
    value = (data.get("value") or "").strip()
    norm = normalize_practice_datetime(value)
    if not norm:
        return {"error": "Invalid date or time"}, 400
    with get_db() as conn:
        conn.execute(
            "UPDATE set_practice SET date_practiced = ? WHERE id = ?",
            (norm, record_id),
        )
        conn.commit()
    return {"ok": True}


def _history_redirect_page(form_page):
    try:
        p = int(form_page or 1)
    except (TypeError, ValueError):
        p = 1
    return max(1, p)


def _history_redirect_query(*, view_sets: bool, form_page, form_type=None):
    q: dict = {}
    if view_sets:
        q["view"] = "sets"
    p = _history_redirect_page(form_page)
    if p > 1:
        q["page"] = p
    t = (form_type or "").strip()
    if t:
        q["type"] = t
    return q


@app.route("/practice/delete/<int:record_id>", methods=["POST"])
def delete_practice(record_id):
    if request.form.get("confirm_delete") != "1":
        flash("Action was not confirmed.", "error")
        return redirect(
            url_for(
                "history_view",
                **_history_redirect_query(
                    view_sets=False,
                    form_page=request.form.get("history_page"),
                    form_type=request.form.get("history_type"),
                ),
            )
        )
    with get_db() as conn:
        conn.execute("DELETE FROM practice_history WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(
        url_for(
            "history_view",
            **_history_redirect_query(
                view_sets=False,
                form_page=request.form.get("history_page"),
                form_type=request.form.get("history_type"),
            ),
        )
    )


@app.route("/practice/set/delete/<int:record_id>", methods=["POST"])
def delete_set_practice(record_id):
    if request.form.get("confirm_delete") != "1":
        flash("Action was not confirmed.", "error")
        return redirect(
            url_for(
                "history_view",
                **_history_redirect_query(
                    view_sets=True,
                    form_page=request.form.get("history_page"),
                    form_type=request.form.get("history_type"),
                ),
            )
        )
    with get_db() as conn:
        conn.execute("DELETE FROM set_practice WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(
        url_for(
            "history_view",
            **_history_redirect_query(
                view_sets=True,
                form_page=request.form.get("history_page"),
                form_type=request.form.get("history_type"),
            ),
        )
    )


@app.route("/delete/<int:tune_id>", methods=["POST"])
def delete_tune(tune_id):
    is_modal = request.form.get("modal") == "1"
    if request.form.get("confirm_delete") != "1":
        if is_modal:
            return jsonify({"ok": False, "error": "Confirmation required."}), 400
        flash("Action was not confirmed.", "error")
        return redirect(url_for("index"))
    with get_db() as conn:
        row = conn.execute("SELECT name FROM tunes WHERE id = ?", (tune_id,)).fetchone()
        if row:
            _backup_tunes_db(conn)
            conn.execute("DELETE FROM tunes WHERE id = ?", (tune_id,))
            conn.commit()
            if is_modal:
                return jsonify({"ok": True})
        else:
            if is_modal:
                return jsonify({"ok": False, "error": "Tune not found."}), 404
            flash("Tune not found.", "error")
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5002)
