"""
Theme system (ported from robbie). Built-in ids live in static/themes.json and THEME_PRESETS
(loaded from the same file for those ids). Custom user themes in themes.json are not in
THEME_PRESETS and can be deleted.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from flask import Request

_KATIE_ROOT = Path(__file__).resolve().parent
THEMES_PATH = str(_KATIE_ROOT / "static" / "themes.json")
SETTINGS_PATH = str(_KATIE_ROOT / "settings.json")

KATIE_BUILTIN_IDS: frozenset[str] = frozenset(
    {
        "steel-blue",
        "f401115f234b",  # Red White Blue
        "e6e76020fcb8",  # Greens
        "57ec9a630b26",  # Blues
        "pearl",
        "arctic",
        "blush",
        "clay",
        "iris",
        "ivory",
        "linen",
        "mist",
        "copper",
        "wisteria",
        "fjord",
        "citrine",
        "peony",
        "cute",
    }
)

KATIE_THEME_ORDER: tuple[str, ...] = (
    "steel-blue",
    "f401115f234b",
    "e6e76020fcb8",
    "57ec9a630b26",
    "pearl",
    "arctic",
    "blush",
    "clay",
    "iris",
    "ivory",
    "linen",
    "mist",
    "copper",
    "wisteria",
    "fjord",
    "citrine",
    "peony",
    "cute",
)

# ── Default palette (Katie) ──
THEME_PRESET_PEARL: dict[str, str] = {
    "bg": "#f6f7f9",
    "surface": "#ffffff",
    "modal-surface": "#ffffff",
    "surface-2": "#e8eaef",
    "border": "#5c6570",
    "accent": "#0b4f8c",
    "accent-focus": "#0b4f8c",
    "accent-hover": "#0a3d6e",
    "accent-light": "#062a4a",
    "text": "#0a0a0b",
    "text-muted": "#4a5058",
    "sidebar-text": "#4a5058",
    "sidebar-bg": "#e3e4e6",
    "sidebar-selected-bg": "#e8eaef",
    "sidebar-selected-color": "#062a4a",
    "danger": "#b91c1c",
    "danger-hover": "#dc2626",
    "badge-type-bg": "rgba(11,79,140,0.12)",
    "badge-type-color": "#062a4a",
    "badge-type-border": "rgba(11,79,140,0.32)",
    "badge-key-bg": "rgba(15,100,80,0.10)",
    "badge-key-color": "#0d5c48",
    "badge-key-border": "rgba(15,100,80,0.28)",
    "practiced-bg": "rgba(15,110,60,0.12)",
    "practiced-color": "#0d5c36",
    "practiced-border": "rgba(15,110,60,0.30)",
    "practiced-bg-played": "#c9bec3",
    "practiced-bg-hover": "rgba(15,110,60,0.30)",
    "practiced-bg-played-hover": "#c9bec3",
    "practiced-color-played": "#0a0a0b",
    "practiced-color-hover": "#0d5c36",
    "practiced-color-played-hover": "#0a0a0b",
    "practiced-border-played": "#a8a6ae",
    "played-today-bg": "#f3e6eb",
    "card-text": "#0a0a0b",
    "card-text-played": "#0a0a0b",
    "header": "#ffffff",
    "widgets": "#f6f7f9",
}

THEME_FALLBACK_ID = "pearl"  # must be a KATIE_BUILTIN_IDS key; see themes.json

THEME_EDITOR_GROUPS: list[tuple[str, str]] = [
    ("general", "General"),
    ("sidebar", "Sidebar and Header"),
    ("layout", "Cards"),
    ("accent", "Accents & buttons"),
    ("badge", "Tune type & key badges"),
]

THEME_EDITOR_ROWS: list[tuple[str, str, str]] = [
    ("bg", "Page Background", "general"),
    ("widgets", "Widgets (primary)", "general"),
    ("modal-surface", "Modals (settings, color picker)", "general"),
    ("surface-2", "Muted (section headers, widget secondary)", "general"),
    ("border", "Borders", "general"),
    ("accent-focus", "Focused Item Border", "general"),
    ("text", "Primary Text Color", "general"),
    ("text-muted", "Muted text", "general"),
    ("sidebar-bg", "Background (desktop sidebar & mobile menu drawer)", "sidebar"),
    ("header", "Header (top bar)", "sidebar"),
    ("sidebar-text", "Sidebar Links", "sidebar"),
    (
        "sidebar-selected-bg",
        "Selected Sidebar Link Background",
        "sidebar",
    ),
    (
        "sidebar-selected-color",
        "Selected Sidebar Link Text",
        "sidebar",
    ),
    ("surface", "Card Background (normal)", "layout"),
    ("played-today-bg", "Card Background (played)", "layout"),
    ("card-text", "Text Color (normal)", "layout"),
    ("card-text-played", "Text Color (played)", "layout"),
    ("practiced-bg", "Practice button background (normal)", "layout"),
    ("practiced-bg-played", "Practice button background (played)", "layout"),
    ("practiced-color", "Practice button text (normal)", "layout"),
    ("practiced-color-played", "Practice button text (played)", "layout"),
    (
        "practiced-bg-hover",
        "Practice button background (normal, hover)",
        "layout",
    ),
    (
        "practiced-bg-played-hover",
        "Practice button background (played, hover)",
        "layout",
    ),
    ("practiced-color-hover", "Practice button text (normal, hover)", "layout"),
    (
        "practiced-color-played-hover",
        "Practice button text (played, hover)",
        "layout",
    ),
    ("practiced-border", "Practice button border (normal)", "layout"),
    ("practiced-border-played", "Practice button border (played)", "layout"),
    ("accent", "Buttons", "accent"),
    ("accent-hover", "Accent hover", "accent"),
    ("danger", "Danger / delete", "accent"),
    ("danger-hover", "Danger hover", "accent"),
    ("badge-type-bg", "Type badge background", "badge"),
    ("badge-type-color", "Type badge text", "badge"),
    ("badge-type-border", "Type badge border", "badge"),
    ("badge-key-bg", "Key badge background", "badge"),
    ("badge-key-color", "Key badge text", "badge"),
    ("badge-key-border", "Key badge border", "badge"),
]

THEME_EDITOR_FORM_KEYS: frozenset[str] = frozenset(k for k, _, _ in THEME_EDITOR_ROWS)
THEME_EDITOR_KEYS: frozenset[str] = THEME_EDITOR_FORM_KEYS | frozenset({"accent-light"})

_THEME_VALUE_MAX_LEN = 160

def _load_builtin_theme_presets() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not os.path.isfile(THEMES_PATH):
        return {"pearl": {**THEME_PRESET_PEARL}}
    try:
        with open(THEMES_PATH, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"pearl": {**THEME_PRESET_PEARL}}
    for t in data.get("themes", []) or []:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if tid in KATIE_BUILTIN_IDS and isinstance(t.get("variables"), dict):
            out[tid] = dict(t["variables"])
    if not out:
        return {"pearl": {**THEME_PRESET_PEARL}}
    return out


# Built-in id -> base variables (must be set before _theme_foundation / complete_theme run)
THEME_PRESETS: dict[str, dict[str, str]] = _load_builtin_theme_presets()


def _parse_hex_color_rgb(s: str) -> tuple[int, int, int] | None:
    t = s.strip()
    if t.startswith("#"):
        t = t[1:]
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        return None
    try:
        return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except ValueError:
        return None


def _hex_srgb_mix(a: str, b: str, wa: float, wb: float) -> str | None:
    ca = _parse_hex_color_rgb(a)
    cb = _parse_hex_color_rgb(b)
    if not ca or not cb:
        return None
    w = wa + wb
    if w <= 0:
        return None
    out = tuple(round((ca[i] * wa + cb[i] * wb) / w) for i in range(3))
    return f"#{out[0]:02x}{out[1]:02x}{out[2]:02x}"


def _sanitize_theme_css_value(val: str) -> str | None:
    val = val.strip()
    if not val or len(val) > _THEME_VALUE_MAX_LEN:
        return None
    if "<" in val or ">" in val or "url(" in val.lower():
        return None
    return val


def _normalize_theme_variables_dict(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k not in THEME_EDITOR_KEYS:
            continue
        if not isinstance(v, str):
            v = str(v)
        s = _sanitize_theme_css_value(v)
        if s:
            out[k] = s
    return out


def _theme_foundation_dict() -> dict[str, str]:
    """All editor keys; prefers pearl, then any preset key."""
    f: dict[str, str] = {}
    for k in THEME_EDITOR_KEYS:
        if k in THEME_PRESET_PEARL:
            f[k] = THEME_PRESET_PEARL[k]
    for pid in THEME_PRESETS:
        for k, v in THEME_PRESETS[pid].items():
            if k in THEME_EDITOR_KEYS and k not in f:
                f[k] = v
    for k in THEME_EDITOR_KEYS:
        if k not in f:
            f[k] = THEME_PRESET_PEARL.get("text", "#0a0a0b")
    return f


def complete_theme_variables(partial: dict[str, str] | None) -> dict[str, str]:
    base = _theme_foundation_dict()
    if partial:
        for k, v in partial.items():
            if k not in THEME_EDITOR_KEYS:
                continue
            s = _sanitize_theme_css_value(v) if v else None
            if s:
                base[k] = s
    tv = _sanitize_theme_css_value(base.get("text", ""))
    if tv:
        base["accent-light"] = tv
    if partial and "card-text" not in partial and tv:
        base["card-text"] = tv
    if partial and "card-text-played" not in partial and tv:
        base["card-text-played"] = tv
    sc = _sanitize_theme_css_value(base.get("sidebar-selected-color", ""))
    if not sc:
        al = _sanitize_theme_css_value(base.get("accent-light", ""))
        if al:
            base["sidebar-selected-color"] = al
    ac = base.get("accent")
    if ac and not str(base.get("accent-focus") or "").strip():
        s_ac = _sanitize_theme_css_value(ac)
        if s_ac:
            base["accent-focus"] = s_ac
    if partial:
        if "practiced-color-played" not in partial:
            pctp = _sanitize_theme_css_value(base.get("card-text-played", ""))
            pt_ = _sanitize_theme_css_value(base.get("text", ""))
            if pctp:
                base["practiced-color-played"] = pctp
            elif pt_:
                base["practiced-color-played"] = pt_
        ptd = _sanitize_theme_css_value(base.get("played-today-bg", ""))
        txd = _sanitize_theme_css_value(base.get("text", ""))
        brd = _sanitize_theme_css_value(base.get("border", ""))
        if "practiced-bg-played" not in partial and ptd and txd:
            m = _hex_srgb_mix(ptd, txd, 0.82, 0.18)
            if m:
                base["practiced-bg-played"] = m
        if "practiced-border-played" not in partial and ptd and brd:
            m = _hex_srgb_mix(ptd, brd, 0.5, 0.5)
            if m:
                base["practiced-border-played"] = m
    pbr = _sanitize_theme_css_value(base.get("practiced-border", ""))
    if pbr and not _sanitize_theme_css_value(base.get("practiced-bg-hover", "")):
        base["practiced-bg-hover"] = pbr
    pbgp = _sanitize_theme_css_value(base.get("practiced-bg-played", ""))
    if pbgp and not _sanitize_theme_css_value(base.get("practiced-bg-played-hover", "")):
        base["practiced-bg-played-hover"] = pbgp
    pc_ = _sanitize_theme_css_value(base.get("practiced-color", ""))
    if pc_ and not _sanitize_theme_css_value(base.get("practiced-color-hover", "")):
        base["practiced-color-hover"] = pc_
    pcp_ = _sanitize_theme_css_value(base.get("practiced-color-played", ""))
    if pcp_ and not _sanitize_theme_css_value(
        base.get("practiced-color-played-hover", "")
    ):
        base["practiced-color-played-hover"] = pcp_
    return base


def _builtin_labels() -> dict[str, str]:
    labels: dict[str, str] = {
        tid: tid.replace("-", " ").title() for tid in KATIE_THEME_ORDER
    }
    labels["steel-blue"] = "Steel Blue"
    labels["f401115f234b"] = "Red White Blue"
    labels["e6e76020fcb8"] = "Greens"
    labels["57ec9a630b26"] = "Blues"
    return labels


def _default_themes_payload() -> dict:
    labels = _builtin_labels()
    themes: list[dict] = []
    for tid in KATIE_THEME_ORDER:
        base_vars = THEME_PRESETS.get(tid)
        if not base_vars:
            continue
        v = {**base_vars}
        v["sidebar-selected-color"] = v.get("sidebar-selected-color") or v.get(
            "accent-light", THEME_PRESET_PEARL["accent-light"]
        )
        themes.append(
            {
                "id": tid,
                "name": labels.get(tid, tid.replace("-", " ").title()),
                "variables": complete_theme_variables(v),
            }
        )
    if not themes:
        themes = [
            {
                "id": THEME_FALLBACK_ID,
                "name": "Pearl",
                "variables": complete_theme_variables({**THEME_PRESET_PEARL}),
            }
        ]
    return {"active_id": THEME_FALLBACK_ID, "themes": themes}


def _ensure_themes_file() -> None:
    if os.path.isfile(THEMES_PATH):
        return
    os.makedirs(os.path.dirname(THEMES_PATH), exist_ok=True)
    data = _default_themes_payload()
    with open(THEMES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _normalize_themes_file_payload(raw: object) -> dict:
    if not isinstance(raw, dict):
        return _default_themes_payload()
    themes_in: object = raw.get("themes")
    if not isinstance(themes_in, list) or not themes_in:
        return _default_themes_payload()
    out_list: list[dict] = []
    seen: set[str] = set()
    for item in themes_in:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        name = str(item.get("name") or "Untitled").strip()[:120] or "Untitled"
        variables = _normalize_theme_variables_dict(item.get("variables"))
        if not variables:
            continue
        out_list.append(
            {
                "id": tid,
                "name": name,
                "variables": complete_theme_variables(variables),
            }
        )
    if not out_list:
        return _default_themes_payload()
    active = str(raw.get("active_id") or "").strip()
    if active not in {t["id"] for t in out_list}:
        active = out_list[0]["id"]
    return {"active_id": active, "themes": out_list}


_THEMES_MIGRATED = False


def _settings_host_module() -> Any | None:
    """app.py as loaded by the interpreter (e.g. ``kb_tunes.app`` under WSGI, not always ``app``)."""
    import importlib
    import sys

    try:
        m = importlib.import_module("app")
        if hasattr(m, "SETTINGS_DEFAULTS") and hasattr(m, "SETTINGS_PATH"):
            return m
    except ModuleNotFoundError:
        pass
    for mod in sys.modules.values():
        if mod is None:
            continue
        if not hasattr(mod, "SETTINGS_DEFAULTS") or not hasattr(mod, "SETTINGS_PATH"):
            continue
        if getattr(mod, "app", None) is None:
            continue
        return mod
    return None


def _migrate_legacy_theme_settings_from_settings_json() -> None:
    app_mod = _settings_host_module()
    if app_mod is None:
        return
    defaults = app_mod.SETTINGS_DEFAULTS
    p = str(app_mod.SETTINGS_PATH)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            raw: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    legacy = any(
        k in raw and raw.get(k) not in (None, "", [], {})
        for k in ("theme", "custom_theme", "named_themes", "active_named_theme_id")
    )
    if not legacy:
        return

    def _old_norm_vars(r: object) -> dict[str, str]:
        if not isinstance(r, dict):
            return {}
        o: dict[str, str] = {}
        for k, v in r.items():
            if k not in THEME_EDITOR_KEYS:
                continue
            if not isinstance(v, str):
                v = str(v)
            s = _sanitize_theme_css_value(v)
            if s:
                o[k] = s
        return o

    def _old_norm_named(r: object) -> list[dict[str, Any]]:
        if not isinstance(r, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in r:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            name = str(item.get("name") or "Untitled").strip()[:120] or "Untitled"
            base = str(item.get("base") or THEME_FALLBACK_ID).strip()
            if base not in THEME_PRESETS:
                base = THEME_FALLBACK_ID
            ov = _old_norm_vars(item.get("overrides"))
            out.append({"id": tid, "name": name, "base": base, "overrides": ov})
        return out

    _ensure_themes_file()
    with open(THEMES_PATH, "r", encoding="utf-8") as f:
        tdata = _normalize_themes_file_payload(json.load(f))

    by_id = {t["id"]: t for t in tdata["themes"]}
    named = _old_norm_named(raw.get("named_themes"))
    ct = _old_norm_vars(raw.get("custom_theme"))
    if ct and not named:
        th0 = str(raw.get("theme") or THEME_FALLBACK_ID).strip()
        b0 = th0 if th0 in THEME_PRESETS else THEME_FALLBACK_ID
        named = [
            {
                "id": secrets.token_hex(6),
                "name": "My theme",
                "base": b0,
                "overrides": dict(ct),
            }
        ]
    for e in named:
        start = {**THEME_PRESETS.get(e["base"], THEME_PRESET_PEARL), **e["overrides"]}
        full = complete_theme_variables(start)
        by_id[e["id"]] = {"id": e["id"], "name": e["name"], "variables": full}
    order = [t["id"] for t in tdata["themes"]]
    seen_ids = set(order)
    for e in named:
        if e["id"] not in seen_ids:
            order.append(e["id"])
            seen_ids.add(e["id"])
    tdata["themes"] = [by_id[i] for i in order if i in by_id]
    aid = str(raw.get("active_named_theme_id") or "").strip()
    th_builtin = str(raw.get("theme") or THEME_FALLBACK_ID).strip()
    if aid and aid in by_id:
        tdata["active_id"] = aid
    elif th_builtin in by_id:
        tdata["active_id"] = th_builtin
    elif tdata["themes"]:
        tdata["active_id"] = tdata["themes"][0]["id"]
    tdata = _normalize_themes_file_payload(tdata)
    with open(THEMES_PATH, "w", encoding="utf-8") as f:
        json.dump(tdata, f, indent=2)

    for k in ("theme", "custom_theme", "named_themes", "active_named_theme_id"):
        raw.pop(k, None)
    new_settings: dict = dict(defaults)
    for key, default in defaults.items():
        v = raw.get(key)
        if isinstance(default, bool):
            if isinstance(v, bool):
                new_settings[key] = v
        elif isinstance(default, list):
            if isinstance(v, list):
                new_settings[key] = v
        elif isinstance(default, dict):
            if isinstance(v, dict):
                new_settings[key] = v
        elif isinstance(v, type(default)):
            new_settings[key] = v
    with open(p, "w", encoding="utf-8") as f:
        json.dump(new_settings, f, indent=2)


def load_themes_data() -> dict:
    global _THEMES_MIGRATED
    if not _THEMES_MIGRATED:
        _migrate_legacy_theme_settings_from_settings_json()
        _THEMES_MIGRATED = True
    _ensure_themes_file()
    try:
        with open(THEMES_PATH, "r", encoding="utf-8") as f:
            raw: Any = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    return _normalize_themes_file_payload(raw)


def save_themes_data(data: dict) -> None:
    normalized = _normalize_themes_file_payload(data)
    os.makedirs(os.path.dirname(THEMES_PATH), exist_ok=True)
    with open(THEMES_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2)


def theme_runtime_for_client() -> dict:
    tdata = load_themes_data()
    active_id = str(tdata.get("active_id") or "").strip() or THEME_FALLBACK_ID
    by_id: dict[str, dict] = {t["id"]: t for t in tdata.get("themes", []) if isinstance(t, dict)}
    entry = by_id.get(active_id) or (tdata.get("themes") or [{}])[0] if tdata.get("themes") else None
    if not entry or not isinstance(entry, dict):
        return {
            "data_theme": THEME_FALLBACK_ID,
            "theme_variables": complete_theme_variables({**THEME_PRESET_PEARL}),
            "active_id": THEME_FALLBACK_ID,
        }
    variables = complete_theme_variables(entry.get("variables") or {})
    return {"data_theme": entry["id"], "theme_variables": variables, "active_id": entry["id"]}


def themes_list_for_client() -> list[dict]:
    tdata = load_themes_data()
    out: list[dict] = []
    for t in tdata.get("themes", []):
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or "").strip()
        if not tid:
            continue
        name = str(t.get("name") or tid).strip()[:120] or tid
        v = t.get("variables")
        c = (
            complete_theme_variables(v if isinstance(v, dict) else {})
            if v
            else complete_theme_variables({})
        )
        out.append(
            {
                "id": tid,
                "name": name,
                "variables": c,
                "swatch_sidebar": c.get("sidebar-bg", "#1a759f"),
                "swatch_surface": c.get("surface", "#f9f9f9"),
                "swatch_practiced": c.get("practiced-bg", "#1a759f"),
            }
        )
    return out


def upsert_theme_in_file(
    theme_id: str | None,
    name: str,
    variables: dict[str, str],
    *,
    activate: bool = True,
) -> str:
    tdata = load_themes_data()
    tid = (theme_id or "").strip() or secrets.token_hex(6)
    full = complete_theme_variables(variables)
    entry = {
        "id": tid,
        "name": (name or "Untitled").strip()[:120] or "Untitled",
        "variables": full,
    }
    themes: list[dict] = [t for t in tdata.get("themes", []) if isinstance(t, dict)]
    found = False
    for i, t in enumerate(themes):
        if str(t.get("id") or "").strip() == tid:
            themes[i] = entry
            found = True
            break
    if not found:
        themes.append(entry)
    tdata["themes"] = themes
    if activate:
        tdata["active_id"] = tid
    save_themes_data(tdata)
    return tid


def delete_theme_in_file(theme_id: str) -> str | None:
    tid = (theme_id or "").strip()
    if not tid:
        return "missing_id"
    if tid in THEME_PRESETS:
        return "builtin"
    tdata = load_themes_data()
    themes: list[dict] = [t for t in tdata.get("themes", []) if isinstance(t, dict)]
    ids = [str(t.get("id") or "").strip() for t in themes if str(t.get("id") or "").strip()]
    if not ids or tid not in ids:
        return "not_found"
    if len(ids) <= 1:
        return "last_theme"
    new_themes = [t for t in themes if str(t.get("id") or "").strip() != tid]
    if not new_themes:
        return "last_theme"
    tdata["themes"] = new_themes
    remaining = {str(t.get("id") or "").strip() for t in new_themes}
    active = str(tdata.get("active_id") or "").strip()
    if active not in remaining:
        tdata["active_id"] = new_themes[0]["id"]
    save_themes_data(tdata)
    return None


def _variables_from_post_form(request: Request) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key in THEME_EDITOR_FORM_KEYS:
        raw = request.form.get(f"var_{key}", "")
        if not isinstance(raw, str):
            continue
        s = _sanitize_theme_css_value(raw)
        if s:
            merged[key] = s
    t = _sanitize_theme_css_value(merged.get("text", ""))
    if t:
        merged["accent-light"] = t
    return merged


def theme_editor_page_state(
    library_id: str | None,
    prefer_new: bool,
    from_arg: str | None,
) -> tuple[dict[str, str], str, str]:
    tdata = load_themes_data()
    by_id = {t["id"]: t for t in tdata.get("themes", []) if isinstance(t, dict)}

    library_id = (library_id or "").strip()
    if library_id and library_id in by_id:
        t = by_id[library_id]
        name = str(t.get("name") or "Untitled").strip()[:120] or "Untitled"
        v = t.get("variables")
        return complete_theme_variables(v if isinstance(v, dict) else {}), library_id, name
    if library_id:
        library_id = ""

    from_arg = (from_arg or "").strip()
    if from_arg in by_id:
        v0 = by_id[from_arg].get("variables")
        return (
            complete_theme_variables(v0 if isinstance(v0, dict) else {}),
            "" if prefer_new else secrets.token_hex(6),
            "New theme" if prefer_new else "My theme",
        )
    if from_arg in THEME_PRESETS:
        return (
            complete_theme_variables(dict(THEME_PRESETS[from_arg])),
            "",
            "New theme" if prefer_new else "My theme",
        )
    return (
        complete_theme_variables({**THEME_PRESET_PEARL}),
        "",
        "New theme" if prefer_new else "My theme",
    )
