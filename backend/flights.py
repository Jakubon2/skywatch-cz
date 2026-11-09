"""Moje lety: follow one flight by its number ("OK 640", "FR1234") or callsign ("CSA640").

Each device keeps its own list (device_id from the browser). On every snapshot the tracker looks the
callsign up in our area; flights elsewhere come from adsb.lol /v2/callsign, one lookup in place of an
area snapshot at most every `global_every_s` (see adsb.poll_forever), so the request rate stays the same.

`assess()` is a pure state machine: waiting -> ground -> airborne -> approach -> landed (+ lost).
Each transition worth knowing about yields one push to the device that asked (take-off, approach with
ETA, landing). Without push on that device there are no notifications, only the live card.
"""

import json
import logging
import math
import re
import sqlite3
import time
from datetime import datetime

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import enrich
import push
from adsb import RateLimited
from config import CONFIG, ROOT
from explain import PRAGUE

log = logging.getLogger("flights")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_flights (
    id INTEGER PRIMARY KEY,
    device_id TEXT NOT NULL,
    query TEXT NOT NULL,        -- as typed, e.g. "OK 640"
    callsign TEXT NOT NULL,     -- what ADS-B shows, e.g. "CSA640"
    endpoint TEXT,              -- Web Push endpoint of the device, if it has push on
    created_at REAL NOT NULL,
    state TEXT NOT NULL         -- JSON, see assess()
);
"""

ICAO_CALLSIGN = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9]{0,3}$")   # CSA640, RYR8NG
FLIGHT_NUMBER = re.compile(r"^([A-Z0-9]{2})([0-9]{1,4}[A-Z]?)$")  # OK640, W62345, FR1234A
OTHER_CALLSIGN = re.compile(r"^[A-Z0-9]{3,8}$")                 # registration as callsign: OKABC, N628TS


def load_codes() -> dict[str, str]:
    with open(ROOT / "config" / CONFIG["flights"]["airline_codes"], encoding="utf-8") as f:
        return {str(k).upper(): str(v).upper() for k, v in (yaml.safe_load(f) or {}).items()}


def to_callsign(query: str, codes: dict[str, str]) -> str | None:
    """'OK 640' -> 'CSA640', 'FR 0123' -> 'RYR123', 'CSA640' -> 'CSA640'. None if it can't be a flight."""
    q = re.sub(r"[\s-]", "", query.upper())
    if ICAO_CALLSIGN.match(q):
        return q
    m = FLIGHT_NUMBER.match(q)
    if m and m.group(1) in codes:
        return codes[m.group(1)] + m.group(2).lstrip("0")
    return q if OTHER_CALLSIGN.match(q) and not q.isdigit() else None


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def heading_to(a: dict, dest: dict) -> bool:
    """Is the aircraft pointed at the destination? A route database can return the previous leg (the plane
    just left the airport we think it's flying to), so only a plane heading there counts as arriving."""
    if a.get("track") is None:
        return True
    diff = abs((a["track"] - bearing(a["lat"], a["lon"], dest["lat"], dest["lon"]) + 180) % 360 - 180)
    return diff < 90


def on_ground(a: dict, cfg: dict) -> bool:
    return a.get("alt_baro") == "ground" or (a.get("gs") is not None and a["gs"] < cfg["ground_max_kt"])


def hidden(a: dict) -> bool:
    """Owners who opted out of tracking (FAA LADD / PIA) are never followed."""
    return bool((a.get("dbFlags") or 0) & 12)


def alt_ft(a: dict) -> float:
    return 0 if a.get("alt_baro") == "ground" else (a.get("alt_baro") or 0)


SAMPLE_FIELDS = ("hex", "r", "t", "lat", "lon", "alt_baro", "gs", "track", "baro_rate")


def assess(state: dict, sample: dict | None, now: float, cfg: dict) -> tuple[dict, list[str]]:
    """Advance one flight. state: {"status", "last", "last_seen", "route", ...}; sample: readsb aircraft or None.
    Returns (new state, events) with events from "airborne", "takeoff", "approach", "landed", "landed_guess"."""
    s = dict(state)
    status = s.get("status", "waiting")
    dest = (s.get("route") or {}).get("destination") or {}
    has_dest = isinstance(dest.get("lat"), (int, float)) and isinstance(dest.get("lon"), (int, float))
    events = []

    if sample is None:
        last, seen = s.get("last"), s.get("last_seen")
        if status in ("airborne", "approach") and last and seen and now - seen > cfg["lost_after_s"]:
            near = has_dest and km(last["lat"], last["lon"], dest["lat"], dest["lon"]) < cfg["landed_guess_km"]
            if near and alt_ft(last) < cfg["landed_guess_max_ft"]:
                s.update(status="landed", landed_at=seen, guessed=True)
                events.append("landed_guess")
            else:
                s["status"] = "lost"
        return s, events

    s["last"] = {k: sample.get(k) for k in SAMPLE_FIELDS}
    s["last_seen"] = now
    ground = on_ground(sample, cfg)
    dist = km(sample["lat"], sample["lon"], dest["lat"], dest["lon"]) if has_dest else None
    s["dist_km"] = round(dist, 1) if dist is not None else None
    toward = has_dest and heading_to(sample, dest)
    s["toward"] = toward
    gs_kmh = (sample.get("gs") or 0) * 1.852
    s["eta"] = (now + dist * cfg["eta_path_factor"] / gs_kmh * 3600
                if dist is not None and toward and not ground and gs_kmh > 100 else None)

    if status == "landed":
        return s, events
    if ground:
        if status in ("airborne", "approach") or (status == "lost" and has_dest and dist < cfg["landed_guess_km"]):
            s.update(status="landed", landed_at=now, guessed=False)
            events.append("landed")
        elif status in ("waiting", "lost"):
            s["status"] = "ground"
        return s, events

    if status in ("waiting", "ground", "lost"):
        events.append("takeoff" if status == "ground" else "airborne" if status == "waiting" else None)
        status = s["status"] = "airborne"
    near = dist is not None and dist < cfg["approach_km"] and alt_ft(sample) < cfg["approach_max_ft"]
    if status == "airborne" and near and toward:
        s["status"] = "approach"
        events.append("approach")
    elif status == "approach" and not (near and toward):
        s["status"] = "airborne"   # went around, or it wasn't arriving after all: quietly back to "ve vzduchu"
    return s, [e for e in events if e]


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts, PRAGUE).strftime("%H:%M")


def _place(ap: dict | None) -> str:
    ap = ap or {}
    return ap.get("location") or ap.get("name") or ap.get("iata") or ap.get("icao") or "cíle"


def message(event: str, query: str, s: dict) -> tuple[str, str]:
    """Czech push title and body for an event."""
    r = s.get("route") or {}
    to = _place(r.get("destination"))
    eta = f" Přílet kolem {_hhmm(s['eta'])}." if s.get("eta") else ""
    if event == "takeoff":
        return f"{query} vzlétl", f"Let {query} právě vzlétl{' z ' + _place(r['origin']) if r.get('origin') else ''}.{eta}"
    if event == "airborne":
        return f"{query} je ve vzduchu", f"Let {query} letí{' do ' + to if r.get('destination') else ''}.{eta}"
    if event == "approach":
        return f"{query} přistává", f"Let {query} se blíží k {to}, je asi {s['dist_km']:.0f} km daleko.{eta}"
    if event == "landed":
        return f"{query} přistál", f"Let {query} přistál{' v ' + to if r.get('destination') else ''}."
    return f"{query} nejspíš přistál", (f"Let {query} zmizel z dosahu přijímačů těsně před {to}, "
                                         "nejspíš už přistál. Přesný čas přistání neznáme.")


def view(row: sqlite3.Row, in_range: set[str]) -> dict:
    s = json.loads(row["state"])
    last = s.get("last")
    return {
        "id": row["id"], "query": row["query"], "callsign": row["callsign"], "push": bool(row["endpoint"]),
        "status": s.get("status", "waiting"), "guessed": s.get("guessed", False),
        "aircraft": last, "last_seen": s.get("last_seen"), "route": s.get("route"),
        "eta": s.get("eta"), "dist_km": s.get("dist_km"), "landed_at": s.get("landed_at"),
        # Pointed away from a destination it's close to: the route database most likely gave the previous leg.
        "route_doubtful": bool(s.get("route") and s.get("toward") is False and (s.get("dist_km") or 1e9) < 300),
        "in_range": bool(last and last.get("hex") in in_range and s.get("status") != "landed"),
        "created_at": row["created_at"],
    }


class Tracker:
    """Poller listener + side request for flights outside our area."""

    def __init__(self, conn: sqlite3.Connection, poller=None):
        self.conn = conn
        self.poller = poller
        self.local: set[str] = set()   # callsigns in the latest area snapshot
        self.cfg = CONFIG["flights"]
        self.global_hits: dict[str, tuple[float, dict | None]] = {}  # callsign -> (time, sample or None)
        self.last_global = 0.0
        self.turn = 0
        self.route_tried: dict[str, float] = {}

    def rows(self):
        return self.conn.execute("SELECT * FROM tracked_flights ORDER BY created_at").fetchall()

    def side_request(self):
        """Coroutine for one global callsign lookup when one is due, else None (poll_forever calls this)."""
        if time.monotonic() - self.last_global < self.cfg["global_every_s"]:
            return None
        wanted = sorted({r["callsign"] for r in self.rows()
                         if json.loads(r["state"]).get("status") != "landed" and r["callsign"] not in self.local})
        if not wanted:
            return None
        self.last_global = time.monotonic()
        callsign = wanted[self.turn % len(wanted)]
        self.turn += 1
        return self._lookup(callsign)

    async def _lookup(self, callsign: str):
        try:
            data = await self.poller.client.fetch_callsign(callsign)
        except (RateLimited, httpx.HTTPError, ValueError):
            raise   # poll_forever backs off as for a snapshot
        except Exception:
            log.exception("callsign lookup %s failed", callsign)
            return
        ac = [a for a in data.get("ac", []) if "lat" in a and "lon" in a and not hidden(a)
              and (a.get("flight") or "").strip().upper() == callsign]
        best = min(ac, key=lambda a: a.get("seen_pos", 99), default=None)
        if best:
            best = {**best, "_ts": data.get("now", time.time() * 1000) / 1000 - best.get("seen_pos", 0)}
        self.global_hits[callsign] = (time.time(), best)
        log.info("global lookup %s: %s", callsign, "found" if best else "not flying")

    async def __call__(self, poller, new_events):
        latest = poller.latest or {}
        now = latest.get("now", time.time() * 1000) / 1000
        by_cs = {}
        for a in latest.get("ac", []):
            cs = (a.get("flight") or "").strip().upper()
            if cs and not hidden(a):
                by_cs[cs] = a
        self.local = set(by_cs)
        for row in self.rows():
            await self._update(row, by_cs, now)
        self._expire(now)

    async def _update(self, row, by_cs: dict, now: float):
        cs, s = row["callsign"], json.loads(row["state"])
        sample, ts = by_cs.get(cs), now
        if sample is None and cs in self.global_hits:
            got_at, hit = self.global_hits[cs]
            if hit and hit["_ts"] > (s.get("last_seen") or 0):
                sample, ts = hit, hit["_ts"]
            elif hit is None and now - got_at > self.cfg["global_every_s"] * 3:
                self.global_hits.pop(cs, None)
        if sample is not None and not s.get("route") and time.time() - self.route_tried.get(cs, 0) > self.cfg["route_retry_s"]:
            self.route_tried[cs] = time.time()
            try:
                route = await enrich.route(cs, sample["lat"], sample["lon"])
                if route and route.get("plausible") is not False:
                    s["route"] = {k: route.get(k) for k in ("origin", "destination", "airline_name", "codes")}
            except enrich.Unavailable:
                pass
        new, events = assess(s, sample, ts, self.cfg)
        if new != s or events:
            self.conn.execute("UPDATE tracked_flights SET state = ? WHERE id = ?", (json.dumps(new), row["id"]))
            self.conn.commit()
        for e in events:
            title, body = message(e, row["query"], new)
            log.info("flight %s: %s", cs, e)
            if row["endpoint"]:
                await push.send_push(title, body, url="/?view=flights", tag=f"flight-{row['id']}", endpoint=row["endpoint"])

    def _expire(self, now: float):
        for row in self.rows():
            s = json.loads(row["state"])
            if s.get("status") == "landed" and now - s.get("landed_at", now) > self.cfg["keep_landed_h"] * 3600:
                self.conn.execute("DELETE FROM tracked_flights WHERE id = ?", (row["id"],))
            elif s.get("status") == "waiting" and now - row["created_at"] > self.cfg["keep_waiting_h"] * 3600:
                self.conn.execute("DELETE FROM tracked_flights WHERE id = ?", (row["id"],))
        self.conn.commit()


# ---------- API ----------

class Track(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    query: str = Field(min_length=2, max_length=20)
    endpoint: str | None = Field(None, max_length=1000)


def make_router(poller) -> APIRouter:
    conn = poller.db
    conn.executescript(SCHEMA)
    tracker = Tracker(conn, poller)
    poller.listeners.append(tracker)
    poller.side_request = tracker.side_request
    codes = load_codes()
    cfg = CONFIG["flights"]
    router = APIRouter(prefix="/api/flights")

    def listing(device_id: str):
        rows = conn.execute("SELECT * FROM tracked_flights WHERE device_id = ? ORDER BY created_at",
                            (device_id,)).fetchall()
        return {"flights": [view(r, {a["hex"] for a in (poller.latest or {}).get("ac", [])}) for r in rows]}

    @router.get("/{device_id}")
    def get(device_id: str):
        return listing(device_id)

    @router.post("", status_code=201)
    async def add(t: Track):
        callsign = to_callsign(t.query, codes)
        if not callsign:
            raise HTTPException(422, "Tohle nevypadá jako číslo letu. Zkus třeba OK 640, FR 1234 nebo CSA640.")
        mine = conn.execute("SELECT callsign FROM tracked_flights WHERE device_id = ?", (t.device_id,)).fetchall()
        if callsign in {r["callsign"] for r in mine}:
            raise HTTPException(409, f"Let {callsign} už sleduješ.")
        if len(mine) >= cfg["max_per_device"]:
            raise HTTPException(429, f"Sledovat jde nejvýš {cfg['max_per_device']} letů najednou.")
        if conn.execute("SELECT COUNT(*) FROM tracked_flights").fetchone()[0] >= cfg["max_total"]:
            raise HTTPException(429, "Server teď sleduje příliš mnoho letů, zkus to později.")
        conn.execute("INSERT INTO tracked_flights (device_id, query, callsign, endpoint, created_at, state) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (t.device_id, t.query.strip().upper(), callsign, t.endpoint, time.time(),
                      json.dumps({"status": "waiting"})))
        conn.commit()
        tracker.last_global = 0.0   # look it up on the next free slot
        await tracker(poller, [])   # pick it up right away if it's in our area
        return listing(t.device_id)

    @router.delete("/{device_id}/{flight_id}")
    def remove(device_id: str, flight_id: int):
        cur = conn.execute("DELETE FROM tracked_flights WHERE id = ? AND device_id = ?", (flight_id, device_id))
        conn.commit()
        if not cur.rowcount:
            raise HTTPException(404, "Tenhle let nesleduješ.")
        return listing(device_id)

    return router
