"""Downsampled position history in SQLite (for time-scrub playback) and traffic stats."""

import logging
import re
import sqlite3
from datetime import datetime, timezone

import yaml

from config import CONFIG, ROOT

log = logging.getLogger("history")

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
  ts INTEGER NOT NULL,         -- unix seconds of the position itself
  hex TEXT NOT NULL,
  flight TEXT, t TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL,
  alt,                         -- readsb alt_baro: feet (int) or 'ground'
  track REAL, gs REAL,
  category TEXT, db_flags INTEGER
);
CREATE INDEX IF NOT EXISTS positions_ts ON positions(ts);
"""

AIRLINE_CALLSIGN = re.compile(r"^([A-Z]{3})\d")

with open(ROOT / "config" / "airlines.yaml", encoding="utf-8") as f:
    AIRLINES: dict[str, str] = yaml.safe_load(f) or {}


def init(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)


class Recorder:
    """Poller listener: stores at most one position per aircraft every sample_s seconds."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cfg = CONFIG["history"]
        self.last: dict[str, int] = {}     # hex -> ts of the last stored position
        self.last_prune = 0.0
        init(conn)

    def record(self, snapshot: dict):
        now = snapshot["now"] / 1000
        rows = []
        for a in snapshot["ac"]:
            if "lat" not in a or "lon" not in a:
                continue
            ts = int(now - a.get("seen_pos", 0))
            if ts - self.last.get(a["hex"], 0) < self.cfg["sample_s"]:
                continue
            self.last[a["hex"]] = ts
            rows.append((
                ts, a["hex"], (a.get("flight") or "").strip() or None, a.get("t"),
                round(a["lat"], 5), round(a["lon"], 5), a.get("alt_baro"),
                a.get("track"), a.get("gs"), a.get("category"), a.get("dbFlags"),
            ))
        if rows:
            self.conn.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            self.conn.commit()
        if now - self.last_prune >= self.cfg["prune_every_minutes"] * 60:
            self.prune(now)

    def prune(self, now: float):
        cutoff = int(now - self.cfg["retention_hours"] * 3600)
        n = self.conn.execute("DELETE FROM positions WHERE ts < ?", (cutoff,)).rowcount
        self.conn.commit()
        self.last = {h: ts for h, ts in self.last.items() if ts >= now - 3600}
        self.last_prune = now
        if n:
            log.info("pruned %d positions older than %d h", n, self.cfg["retention_hours"])

    def __call__(self, poller, new_events):
        self.record(poller.latest)


def frames(conn: sqlite3.Connection, start: int, end: int, step: int) -> dict:
    """Playback frames: for each frame time, the latest position of every aircraft seen within stale_s.

    Returns {"from", "to", "step", "fields", "aircraft": {hex: [flight, t, category, dbFlags]},
             "frames": [{"t": ts, "ac": [[hex, lat, lon, alt, track, gs], ...]}, ...]}.
    """
    cfg = CONFIG["history"]
    step = max(int(step), cfg["sample_s"])
    end = max(end, start)
    if (end - start) / step > cfg["max_frames"]:
        step = -(-(end - start) // cfg["max_frames"])          # ceil: stay within max_frames
    stale = max(step, cfg["stale_s"])

    rows = conn.execute(
        "SELECT ts, hex, flight, t, lat, lon, alt, track, gs, category, db_flags FROM positions"
        " WHERE ts > ? AND ts <= ? ORDER BY ts", (start - stale, end),
    ).fetchall()

    meta: dict[str, list] = {}
    current: dict[str, tuple] = {}    # hex -> (ts, position row)
    out = []
    i = 0
    for t in range(start, end + 1, step):
        while i < len(rows) and rows[i][0] <= t:
            ts, hx, flight, typ, lat, lon, alt, track, gs, cat, flags = rows[i]
            current[hx] = (ts, [hx, lat, lon, alt, _r(track), _r(gs)])
            m = meta.setdefault(hx, [None, None, None, None])
            for k, v in enumerate((flight, typ, cat, flags)):
                if v is not None:
                    m[k] = v
            i += 1
        ac = [p for ts, p in current.values() if ts > t - stale]
        out.append({"t": t, "ac": ac})
        for hx in [h for h, (ts, _) in current.items() if ts <= t - stale]:
            del current[hx]
    used = {p[0] for f in out for p in f["ac"]}
    return {
        "from": start, "to": end, "step": step,
        "fields": ["hex", "lat", "lon", "alt", "track", "gs"],
        "aircraft_fields": ["flight", "t", "category", "dbFlags"],
        "aircraft": {h: m for h, m in meta.items() if h in used},
        "frames": out,
    }


def _r(x):
    return round(x) if x is not None else None


def stats(conn: sqlite3.Connection, start: int, end: int, top_n: int = 10) -> dict:
    """Traffic per 10 min, top airlines/types, rarest types and event counts in [start, end]."""
    bucket = 600
    traffic = [
        {"t": b, "aircraft": n} for b, n in conn.execute(
            "SELECT ts / ? * ? AS b, COUNT(DISTINCT hex) FROM positions WHERE ts >= ? AND ts <= ?"
            " GROUP BY b ORDER BY b", (bucket, bucket, start, end))
    ]
    airlines = conn.execute(
        "SELECT substr(flight, 1, 3) AS code, COUNT(DISTINCT hex || flight) AS n FROM positions"
        " WHERE ts >= ? AND ts <= ? AND flight GLOB '[A-Z][A-Z][A-Z][0-9]*'"
        " GROUP BY code ORDER BY n DESC, code LIMIT ?", (start, end, top_n),
    ).fetchall()
    types = conn.execute(
        "SELECT t, COUNT(DISTINCT hex) AS n FROM positions WHERE ts >= ? AND ts <= ? AND t IS NOT NULL"
        " GROUP BY t", (start, end),
    ).fetchall()
    seen = {r[0]: r[1] for r in conn.execute("SELECT type, first_seen FROM seen_types")}
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")  # noqa: E731
    events = conn.execute(
        "SELECT type, COUNT(*) FROM events WHERE started_at >= ? AND started_at <= ? GROUP BY type"
        " ORDER BY COUNT(*) DESC", (iso(start), iso(end)),
    ).fetchall()
    unique = conn.execute(
        "SELECT COUNT(DISTINCT hex) FROM positions WHERE ts >= ? AND ts <= ?", (start, end),
    ).fetchone()[0]

    by_count = sorted(types, key=lambda r: (-r[1], r[0]))
    # Rarest: fewest distinct aircraft in the window; ties -> type first seen most recently.
    rarest = sorted(types, key=lambda r: (r[1], -seen.get(r[0], 0), r[0]))
    return {
        "from": start, "to": end, "bucket_s": bucket,
        "unique_aircraft": unique,
        "traffic": traffic,
        "top_airlines": [{"code": c, "name": AIRLINES.get(c), "flights": n} for c, n in airlines],
        "top_types": [{"type": t, "aircraft": n} for t, n in by_count[:top_n]],
        "rarest_types": [
            {"type": t, "aircraft": n, "first_seen": seen.get(t)} for t, n in rarest[:top_n]
        ],
        "events": {t: n for t, n in events},
    }

