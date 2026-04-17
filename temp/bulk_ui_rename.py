from pathlib import Path

root = Path(__file__).resolve().parent
files = list(root.glob("templates/**/*.html")) + list(root.glob("static/*.css")) + list(root.glob("static/*.js"))
subs = [
    ("song-modal", "tune-modal"),
    ("song-panel", "tune-panel"),
    ("song-notes", "tune-notes"),
    ("song-card", "tune-card"),
    ("song-form", "tune-form"),
    ("song-table", "tune-table"),
    ("song-link", "tune-link"),
    ("songTable", "tuneTable"),
    ("songEditForm", "tuneEditForm"),
    ("songModal", "tuneModal"),
    ("songPanel", "tunePanel"),
    ("data-song-id", "data-tune-id"),
    ("song_name_field", "tune_name_field"),
    ("song_tune_type", "tune_tune_type"),
    ("song_key", "tune_key"),
    ("song_priority", "tune_priority"),
    ("song_capo", "tune_capo"),
    ("song_strumming", "tune_strumming"),
    ("song_progress", "tune_progress"),
]
for path in files:
    t = path.read_text(encoding="utf-8")
    for a, b in subs:
        t = t.replace(a, b)
    path.write_text(t, encoding="utf-8")
print("ok", len(files))
