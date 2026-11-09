"""Visits of watched (celebrity) aircraft: when they were last over our area and where they came from / went.

A poller listener records one row per visit (a gap longer than `new_sighting_gap_min` starts a new one),
keeping the first and last position. `describe()` turns those into Czech text: an airport when the plane
was low next to one ("vzlétlo z letiště Prague (PRG)"), otherwise a compass direction from the
middle of our area ("odletělo na severozápad"). LADD/PIA aircraft never match (detectors/watched.match).
"""

import math
import sqlite3
from datetime import datetime, timedelta, timezone

import airports
from config import CONFIG
from detectors.watched import match, norm_reg

SCHEMA = """
CREATE TABLE IF NOT EXISTS watched_visits (
    id INTEGER PRIMARY KEY,
    reg TEXT NOT NULL,           -- normalized registration (watchlist key)
    hex TEXT,
    callsign TEXT,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    first_lat REAL, first_lon REAL, first_alt REAL,   -- alt in ft, 0 = on the ground
    last_lat REAL, last_lon REAL, last_alt REAL,
    max_alt REAL
);
CREATE INDEX IF NOT EXISTS watched_visits_reg ON watched_visits (reg, end_ts);
"""

DIRECTIONS = ["sever", "severovýchod", "východ", "jihovýchod", "jih", "jihozápad", "západ", "severozápad"]
DIRECTIONS_FROM = ["severu", "severovýchodu", "východu", "jihovýchodu", "jihu", "jihozápadu", "západu", "severozápadu"]


def _alt(a: dict) -> float:
    return 0.0 if a.get("alt_baro") == "ground" else float(a.get("alt_baro") or 0)


def record(conn: sqlite3.Connection, reg: str, a: dict, now: float, gap_s: float):
    """Extend the open visit of `reg`, or start a new one."""
    row = conn.execute("SELECT id, max_alt FROM watched_visits WHERE reg = ? AND end_ts >= ? ORDER BY end_ts DESC LIMIT 1",
                       (reg, now - gap_s)).fetchone()
    alt, cs = _alt(a), (a.get("flight") or "").strip() or None
    if row:
        conn.execute("UPDATE watched_visits SET end_ts = ?, last_lat = ?, last_lon = ?, last_alt = ?, max_alt = ?, "
                     "callsign = COALESCE(callsign, ?) WHERE id = ?",
                     (now, a["lat"], a["lon"], alt, max(row[1] or 0, alt), cs, row[0]))
    else:
        conn.execute("INSERT INTO watched_visits (reg, hex, callsign, start_ts, end_ts, first_lat, first_lon, first_alt, "
                     "last_lat, last_lon, last_alt, max_alt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (reg, a.get("hex"), cs, now, now, a["lat"], a["lon"], alt, a["lat"], a["lon"], alt, alt))


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(deg: float, names=DIRECTIONS) -> str:
    return names[int((deg + 22.5) // 45) % 8]


def describe(v: dict, cfg: dict, nearest=None) -> dict:
    """{"from": "...", "to": "...", "from_airport", "to_airport"} for one visit row."""
    nearest = nearest or airports.nearest
    src = CONFIG["source"]
    clat, clon = src["center_lat"], src["center_lon"]
    out = {}
    for end, lat, lon, alt in (("from", v["first_lat"], v["first_lon"], v["first_alt"]),
                               ("to", v["last_lat"], v["last_lon"], v["last_alt"])):
        ap = nearest(lat, lon, cfg["airport_max_km"]) if alt is not None and alt < cfg["airport_max_ft"] else None
        out[f"{end}_airport"] = ap
        if ap:
            place = f"{ap.get('city') or ap['name']} ({ap.get('iata') or ap['ident']})"
            out[end] = f"vzlétlo z letiště {place}" if end == "from" else f"přistálo na letišti {place}"
        else:
            d = bearing(clat, clon, lat, lon)
            out[end] = f"přiletělo od {compass(d, DIRECTIONS_FROM)}" if end == "from" else f"odletělo na {compass(d)}"
    return out


def visit_view(v: sqlite3.Row, cfg: dict, labels: dict) -> dict:
    v = dict(v)
    e = labels.get(v["reg"], {})
    return {
        "reg": e.get("reg", v["reg"]), "label": e.get("label"), "category": e.get("category"), "type": e.get("type"),
        "callsign": v["callsign"], "start": v["start_ts"], "end": v["end_ts"],
        "max_alt_ft": v["max_alt"], **describe(v, cfg),
    }


class Recorder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cfg = CONFIG["watched_history"]
        self.pruned = None

    def __call__(self, poller, new_events):
        latest = poller.latest
        if not latest:
            return
        now = latest["now"] / 1000
        wl, wcfg = poller.ctx["watchlist"], poller.ctx["cfg"]["watched"]
        hits = [(norm_reg(e["reg"]), a) for a in latest["ac"] if (e := match(a, wl, wcfg)) is not None]
        for reg, a in hits:
            record(self.conn, reg, a, now, self.cfg["new_sighting_gap_min"] * 60)
        today = datetime.now(timezone.utc).date()
        if self.pruned != today:
            self.pruned = today
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.cfg["keep_days"])).timestamp()
            self.conn.execute("DELETE FROM watched_visits WHERE end_ts < ?", (cutoff,))
        if hits or self.pruned == today:
            self.conn.commit()


def init(poller):
    poller.db.executescript(SCHEMA)
    poller.listeners.append(Recorder(poller.db))


def last_visits(conn: sqlite3.Connection, entries: list[dict]) -> dict[str, dict]:
    """Latest visit per normalized registration, ready for the UI."""
    cfg = CONFIG["watched_history"]
    labels = {norm_reg(e["reg"]): e for e in entries}
    rows = conn.execute("SELECT v.* FROM watched_visits v JOIN (SELECT reg, MAX(end_ts) m FROM watched_visits GROUP BY reg) l "
                        "ON v.reg = l.reg AND v.end_ts = l.m").fetchall()
    return {r["reg"]: visit_view(r, cfg, labels) for r in rows if r["reg"] in labels}


def recent(conn: sqlite3.Connection, entries: list[dict], limit: int = 20) -> list[dict]:
    cfg = CONFIG["watched_history"]
    labels = {norm_reg(e["reg"]): e for e in entries}
    rows = conn.execute("SELECT * FROM watched_visits ORDER BY end_ts DESC LIMIT ?", (limit * 2,)).fetchall()
    return [visit_view(r, cfg, labels) for r in rows if r["reg"] in labels][:limit]
