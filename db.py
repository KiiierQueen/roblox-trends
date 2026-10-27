"""SQLite-хранилище: игры, замеры онлайна, обновления, журнал запусков."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS games(
    universe_id     INTEGER PRIMARY KEY,
    root_place_id   INTEGER,
    name            TEXT,
    description     TEXT,
    creator         TEXT,
    updated         TEXT,
    created         TEXT,
    visits          INTEGER,
    playing         INTEGER,
    favorites       INTEGER,
    icon_url        TEXT,
    first_seen      INTEGER,
    last_seen       INTEGER,
    first_seen_top  INTEGER,
    last_seen_top   INTEGER,
    is_manual       INTEGER DEFAULT 0,
    sorts           TEXT
);
CREATE TABLE IF NOT EXISTS snapshots(
    universe_id INTEGER,
    ts          INTEGER,
    playing     INTEGER,
    visits      INTEGER,
    PRIMARY KEY(universe_id, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);
CREATE TABLE IF NOT EXISTS updates(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    universe_id     INTEGER,
    ts              INTEGER,
    kind            TEXT,          -- 'text' (название/описание) или 'publish' (только новая версия)
    old_name        TEXT,
    new_name        TEXT,
    old_description TEXT,
    new_description TEXT,
    old_updated     TEXT,
    new_updated     TEXT
);
CREATE INDEX IF NOT EXISTS idx_upd ON updates(universe_id, ts);
CREATE INDEX IF NOT EXISTS idx_upd_ts ON updates(ts);
CREATE TABLE IF NOT EXISTS runs(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started    INTEGER,
    finished   INTEGER,
    ok         INTEGER,
    games      INTEGER,
    restricted INTEGER,
    message    TEXT
);
CREATE TABLE IF NOT EXISTS place_map(
    place_id    INTEGER PRIMARY KEY,
    universe_id INTEGER
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    con = sqlite3.connect(path, timeout=60, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(games)")}
    for col, typ in (("up_votes", "INTEGER"), ("down_votes", "INTEGER"), ("genre", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE games ADD COLUMN {col} {typ}")
    return con


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value):
    con.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
