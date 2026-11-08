"""Compact long-term pass history ("callsign X was in grid cell Y on day D at local minute M")
and the flight predictions built on it ("SIA308 A388 usually passes here around 14:02").

Full positions are kept only 24 h (history.py); this table is small enough to keep ~30 days.
"""

import logging
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime

from config import CONFIG
from detectors.geo import distance_nm
from explain import PRAGUE

log = logging.getLogger("passes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS passes (
  ci INTEGER NOT NULL, cj INTEGER NOT NULL,   -- grid cell: floor(lat / cell_lat_deg), floor(lon / cell_lon_deg)
  day INTEGER NOT NULL,                       -- Prague local date as ordinal
  callsign TEXT NOT NULL,
  minute INTEGER NOT NULL,                    -- Prague local minute of day of the first sample in the cell
  t TEXT,
  PRIMARY KEY (ci, cj, day, callsign)
) WITHOUT ROWID;

-- Which local hours the recorder was running, so missing data isn't mistaken for "flight didn't come".
CREATE TABLE IF NOT EXISTS pass_coverage (
  day INTEGER NOT NULL, hour INTEGER NOT NULL,
  PRIMARY KEY (day, hour)
) WITHOUT ROWID;
"""

NM_PER_KM = 1 / 1.852


def init(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)


def cell_of(lat: float, lon: float) -> tuple[int, int]:
    cfg = CONFIG["passes"]
    return math.floor(lat / cfg["cell_lat_deg"]), math.floor(lon / cfg["cell_lon_deg"])


class PassRecorder:
    """Poller listener: one row per (cell, day, callsign); the first visit of the day wins."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.day = None
        self.seen: set = set()
        self.last_prune_day = None
        init(conn)

    def record(self, snapshot: dict):
        local = datetime.fromtimestamp(snapshot["now"] / 1000, PRAGUE)
        day = local.toordinal()
        if day != self.day:
            self.day, self.seen = day, set()
        minute = local.hour * 60 + local.minute
        rows = []
        for a in snapshot["ac"]:
            callsign = (a.get("flight") or "").strip().upper()
            if not callsign or "lat" not in a or "lon" not in a or a.get("alt_baro") == "ground":
                continue
            key = (*cell_of(a["lat"], a["lon"]), callsign)
            if key in self.seen:
                continue
            self.seen.add(key)
            rows.append((key[0], key[1], day, callsign, minute, a.get("t")))
        # INSERT OR IGNORE: after a restart the earlier visit already stored today is kept.
        self.conn.executemany("INSERT OR IGNORE INTO passes VALUES (?,?,?,?,?,?)", rows)
        self.conn.execute("INSERT OR IGNORE INTO pass_coverage VALUES (?, ?)", (day, local.hour))
        self.conn.commit()
        if self.last_prune_day != day:
            self.prune(day)

    def prune(self, today: int):
        cutoff = today - CONFIG["passes"]["retention_days"]
        n = self.conn.execute("DELETE FROM passes WHERE day < ?", (cutoff,)).rowcount
        self.conn.execute("DELETE FROM pass_coverage WHERE day < ?", (cutoff,))
        self.conn.commit()
        self.last_prune_day = today
        if n:
            log.info("pruned %d passes older than %d days", n, CONFIG["passes"]["retention_days"])

    def __call__(self, poller, new_events):
        self.record(poller.latest)


# ---------- predictions ----------

def _cells_near(lat: float, lon: float, radius_km: float) -> set[tuple[int, int]]:
    """Grid cells that intersect the circle (distance from the point to the cell's nearest point)."""
    cfg = CONFIG["passes"]
    dlat, dlon = cfg["cell_lat_deg"], cfg["cell_lon_deg"]
    rlat = radius_km / 111.0
    rlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    cells = set()
    for ci in range(math.floor((lat - rlat) / dlat), math.floor((lat + rlat) / dlat) + 1):
        for cj in range(math.floor((lon - rlon) / dlon), math.floor((lon + rlon) / dlon) + 1):
            near_lat = min(max(lat, ci * dlat), (ci + 1) * dlat)
            near_lon = min(max(lon, cj * dlon), (cj + 1) * dlon)
            if distance_nm(lat, lon, near_lat, near_lon) <= radius_km * NM_PER_KM:
                cells.add((ci, cj))
    return cells


def _signed(a: int, b: int) -> int:
    """a - b in minutes on the 24 h circle, in (-720, 720]."""
    d = (a - b) % 1440
    return d - 1440 if d > 720 else d


def _cluster(minutes: list[int], width: int) -> list[int]:
    """Largest group of times within ±width of one of them (handles midnight wrap)."""
    best = []
    for c in minutes:
        group = [m for m in minutes if abs(_signed(m, c)) <= width]
        if len(group) > len(best):
            best = group
    return best


def _hhmm(minute: int) -> str:
    minute %= 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def predict(conn: sqlite3.Connection, lat: float, lon: float, radius_km: float, hours: float,
            now: datetime | None = None) -> dict:
    """Recurring callsigns expected near the point within `hours`, from past days' passes.

    Only days before today are used. A day counts as observed for a flight only when the recorder
    was running in the hour of the flight's usual time.
    """
    cfg = CONFIG["passes"]
    now = (now or datetime.now(PRAGUE)).astimezone(PRAGUE)
    today = now.toordinal()
    since = today - cfg["retention_days"]
    now_min = now.hour * 60 + now.minute

    coverage = defaultdict(set)   # hour -> days
    for day, hour in conn.execute("SELECT day, hour FROM pass_coverage WHERE day >= ? AND day < ?",
                                  (since, today)):
        coverage[hour].add(day)
    days_with_data = len(set().union(*coverage.values())) if coverage else 0
    base = {
        "lat": lat, "lon": lon, "radius_km": radius_km, "hours": hours,
        "now": now.isoformat(timespec="seconds"),
        "history_days": days_with_data,
        "cell_km": round(cfg["cell_lat_deg"] * 111),
    }
    if days_with_data < cfg["min_history_days"]:
        return {**base, "predictions": [],
                "reason": "Málo dat, předpověď bude fungovat po několika dnech sběru "
                          f"(zatím {days_with_data} {'den' if days_with_data == 1 else 'dny' if 2 <= days_with_data <= 4 else 'dní'})."}

    cells = _cells_near(lat, lon, radius_km)
    if not cells:
        return {**base, "predictions": [], "reason": None}
    cis = [c[0] for c in cells]
    cjs = [c[1] for c in cells]
    first = {}   # (callsign, day) -> (minute, type): first entry into the area that day
    for ci, cj, day, callsign, minute, t in conn.execute(
        "SELECT ci, cj, day, callsign, minute, t FROM passes"
        " WHERE ci BETWEEN ? AND ? AND cj BETWEEN ? AND ? AND day >= ? AND day < ?",
        (min(cis), max(cis), min(cjs), max(cjs), since, today),
    ):
        if (ci, cj) not in cells:
            continue
        key = (callsign, day)
        if key not in first or minute < first[key][0]:
            first[key] = (minute, t)

    by_callsign = defaultdict(list)
    for (callsign, day), (minute, t) in first.items():
        by_callsign[callsign].append((day, minute, t))

    out = []
    for callsign, visits in by_callsign.items():
        if len(visits) < cfg["min_days_seen"]:
            continue
        group = _cluster([m for _, m, _ in visits], cfg["cluster_minutes"])
        if len(group) < cfg["min_days_seen"]:
            continue
        center = group[0]
        offsets = sorted(_signed(m, center) for m in group)
        usual = (center + offsets[len(offsets) // 2]) % 1440
        start, end = (center + offsets[0]) % 1440, (center + offsets[-1]) % 1440
        expected_in = _signed(usual, now_min)
        if not (-cfg["grace_minutes"] <= expected_in <= hours * 60):
            continue
        in_group = set(group)
        seen_days = {d for d, m, _ in visits if m in in_group}
        # Observed = recorder ran in the usual hour, plus every day the flight was actually seen
        # (a 13:56 sighting of a 14:02 flight proves the recorder was running even without 14:xx data).
        observed = len(coverage.get(usual // 60, set()) | seen_days)
        seen = len(seen_days)
        confidence = round(min(1.0, seen / observed), 2) if observed else 0.0
        types = Counter(t for _, m, t in visits if t and m in in_group)
        out.append({
            "callsign": callsign,
            "type": types.most_common(1)[0][0] if types else None,
            "usual_time": _hhmm(usual),
            "window": {"from": _hhmm(start), "to": _hhmm(end)},
            "expected_in_min": expected_in,
            "days_seen": seen,
            "days_observed": observed,
            "confidence": confidence,
            "confidence_label": ("vysoká" if confidence >= 0.7 and seen >= 5
                                 else "střední" if confidence >= 0.4 else "nízká"),
        })
    out.sort(key=lambda p: (p["expected_in_min"], -p["confidence"]))
    return {**base, "predictions": out[:cfg["max_results"]], "reason": None}


def upcoming(conn: sqlite3.Connection, lat: float, lon: float, radius_km: float, within_min: int,
             min_confidence: float = 0.5, now: datetime | None = None) -> list[dict]:
    """Hook for alerts: confident predictions due within `within_min` minutes (no notifications here)."""
    r = predict(conn, lat, lon, radius_km, within_min / 60, now)
    return [p for p in r["predictions"] if p["confidence"] >= min_confidence and p["expected_in_min"] >= 0]


def message_cs(p: dict) -> str:
    """Czech one-liner for an alert, e.g. 'Za 20 minut tu nejspíš poletí A388 (SIA308)…'."""
    what = f"{p['type']} ({p['callsign']})" if p.get("type") else p["callsign"]
    when = "teď" if p["expected_in_min"] <= 0 else f"za {p['expected_in_min']} min"
    return (f"{when.capitalize()} tu nejspíš poletí {what}, obvykle kolem {p['usual_time']} "
            f"(viděno {p['days_seen']} z {p['days_observed']} dní).")


# ---------- weekly stats ----------

def week_stats(conn: sqlite3.Connection, first_day: date, last_day: date, top_n: int = 5) -> dict:
    """Flights (distinct callsign per day) for the summary, from the pass table."""
    a, b = first_day.toordinal(), last_day.toordinal()
    flights = conn.execute(
        "SELECT day, callsign, MAX(t) FROM passes WHERE day BETWEEN ? AND ? GROUP BY day, callsign", (a, b),
    ).fetchall()
    hours = Counter(d for (d,) in conn.execute(
        "SELECT day FROM pass_coverage WHERE day BETWEEN ? AND ?", (a, b)))
    per_day = Counter(d for d, _, _ in flights)
    airlines = Counter(cs[:3] for _, cs, _ in flights if len(cs) > 3 and cs[:3].isalpha() and cs[3].isdigit())
    types = Counter(t for _, _, t in flights if t)
    return {
        "days": [{"date": date.fromordinal(d).isoformat(), "flights": per_day.get(d, 0),
                  "hours_recorded": hours.get(d, 0)} for d in range(a, b + 1)],
        "flights": len(flights),
        "top_airlines": airlines.most_common(top_n),
        "top_types": types.most_common(top_n),
        "rare_types": sorted(types.items(), key=lambda kv: (kv[1], kv[0]))[:top_n],
    }
