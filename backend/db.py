"""SQLite storage. Plain sqlite3, no ORM."""

import json
import sqlite3

from config import ROOT

DEFAULT_PATH = ROOT / "data" / "skywatch.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,          -- emergency | holding | go_around | interesting | rapid_descent | return_or_diversion | heli_orbit
  hex TEXT NOT NULL,
  callsign TEXT,
  aircraft_type TEXT,
  lat REAL, lon REAL, alt_ft INTEGER,
  started_at TEXT NOT NULL,
  data_json TEXT,
  explanation TEXT,
  explained_at TEXT
);
CREATE INDEX IF NOT EXISTS events_started_at ON events(started_at);

CREATE TABLE IF NOT EXISTS alert_rules (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  rule_json TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_hits (
  id INTEGER PRIMARY KEY,
  rule_id INTEGER NOT NULL,
  hex TEXT NOT NULL,
  hit_at TEXT NOT NULL
);

-- For the "type not seen in 30 days" detector.
CREATE TABLE IF NOT EXISTS seen_types (
  type TEXT PRIMARY KEY,
  first_seen REAL NOT NULL,    -- unix ts
  last_seen REAL NOT NULL
);
"""


def connect(path=DEFAULT_PATH) -> sqlite3.Connection:
    if path != ":memory:":
        path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_event(conn: sqlite3.Connection, e: dict) -> int:
    cur = conn.execute(
        "INSERT INTO events (type, hex, callsign, aircraft_type, lat, lon, alt_ft, started_at, data_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (e["type"], e["hex"], e["callsign"], e["aircraft_type"], e["lat"], e["lon"], e["alt_ft"],
         e["started_at"], json.dumps(e["data"], ensure_ascii=False)),
    )
    conn.commit()
    return cur.lastrowid


def load_seen_types(conn: sqlite3.Connection) -> tuple[dict[str, float], float | None]:
    rows = conn.execute("SELECT type, first_seen, last_seen FROM seen_types").fetchall()
    seen = {r["type"]: r["last_seen"] for r in rows}
    since = min((r["first_seen"] for r in rows), default=None)
    return seen, since


def touch_types(conn: sqlite3.Connection, types: set[str], ts: float):
    conn.executemany(
        "INSERT INTO seen_types (type, first_seen, last_seen) VALUES (?, ?, ?)"
        " ON CONFLICT(type) DO UPDATE SET last_seen = excluded.last_seen",
        [(t, ts, ts) for t in types],
    )
    conn.commit()
