"""Extra endpoints: position history playback, stats, predictions, summary previews, route/photo/trail."""

import asyncio
import re
import time

from fastapi import APIRouter, HTTPException, Query

import enrich
import history
import passes
import summary
from config import CONFIG

router = APIRouter(prefix="/api")
_poller = None
_stats_cache: dict[int, tuple[float, dict]] = {}


def start(poller) -> asyncio.Future | None:
    """Call from the API lifespan: registers the recorders, starts the enabled summary loops.
    Returns one cancellable future (or None when no loop is enabled)."""
    global _poller
    _poller = poller
    poller.listeners.append(history.Recorder(poller.db))
    poller.listeners.append(passes.PassRecorder(poller.db))
    loops = [summary.run_loop(poller.db, kind) for kind, section in (("day", "daily_summary"),
             ("week", "weekly_summary")) if CONFIG[section]["enabled"]]
    return asyncio.gather(*loops) if loops else None


@router.get("/history")
def get_history(
    from_: int | None = Query(None, alias="from", description="unix seconds, default to - 1 h"),
    to: int | None = Query(None, description="unix seconds, default now"),
    step: int = Query(60, ge=1, description="seconds between frames (raised to stay within limits)"),
):
    end = to or int(time.time())
    start = from_ if from_ is not None else end - 3600
    if start > end:
        raise HTTPException(422, "Parametr from musí být před to.")
    start = max(start, end - CONFIG["history"]["retention_hours"] * 3600)
    return history.frames(_poller.db, start, end, step)


@router.get("/stats")
def get_stats(hours: int = Query(24, ge=1, le=168)):
    hit = _stats_cache.get(hours)
    if hit and time.monotonic() - hit[0] < CONFIG["history"]["stats_cache_s"]:
        return hit[1]
    end = int(time.time())
    result = history.stats(_poller.db, end - hours * 3600, end, CONFIG["history"]["stats_top_n"])
    _stats_cache[hours] = (time.monotonic(), result)
    return result


@router.get("/predictions")
def get_predictions(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                    radius_km: float = Query(15, gt=0, le=100), hours: float = Query(3, gt=0, le=24)):
    return passes.predict(_poller.db, lat, lon, radius_km, hours)


@router.get("/summary/today")
async def summary_today():
    """Preview of today's summary (not sent). Cached; text is null over the cap or on API errors."""
    return await summary.generate(_poller.db)


@router.get("/summary/week")
async def summary_week():
    """Preview of the last 7 days' summary (not sent). Same shape as /summary/today, kind "week"."""
    return await summary.generate(_poller.db, kind="week")


CALLSIGN = re.compile(r"^[A-Z0-9]{2,8}$")


@router.get("/route/{callsign}")
async def get_route(callsign: str):
    callsign = callsign.strip().upper()
    if not CALLSIGN.match(callsign):
        raise HTTPException(422, "Neplatný volací znak.")
    # The API checks plausibility against the current position; fall back to the area centre.
    src = CONFIG["source"]
    lat, lon = src["center_lat"], src["center_lon"]
    for a in (_poller.latest or {}).get("ac", []):
        if (a.get("flight") or "").strip().upper() == callsign:
            lat, lon = a["lat"], a["lon"]
            break
    try:
        r = await enrich.route(callsign, lat, lon)
    except enrich.Unavailable:
        raise HTTPException(503, "Trasu letu teď nejde zjistit, zkus to prosím později.")
    if r and not r.get("airline_name"):
        code = r.get("airline_code") or (m.group(1) if (m := history.AIRLINE_CALLSIGN.match(callsign)) else None)
        r = {**r, "airline_name": history.AIRLINES.get(code)}
    return {"callsign": callsign, "known": r is not None, "route": r}


@router.get("/photo/{key}")
async def get_photo(key: str):
    if not re.match(r"^[A-Za-z0-9-]{2,10}$", key):
        raise HTTPException(422, "Neplatná registrace nebo hex.")
    try:
        p = await enrich.photo(key)
    except enrich.Unavailable:
        raise HTTPException(503, "Fotku teď nejde načíst.")
    return {"key": key, "photo": p}


@router.get("/trail/{hex_id}")
def get_trail(hex_id: str):
    track = _poller.history.get(hex_id.lower())
    if not track:
        raise HTTPException(404, "Letadlo nemá žádnou trať za posledních 15 minut.")
    return {
        "hex": hex_id.lower(),
        "fields": ["ts", "lat", "lon", "alt", "track", "gs"],
        "points": [[round(s["ts"], 1), s["lat"], s["lon"], s.get("alt_baro"), s.get("track"), s.get("gs")]
                   for s in track],
    }


HEX_ID = re.compile(r"^~?[0-9a-f]{6}$")
_type_cache: dict[str, tuple[float, dict]] = {}


def type_seen(conn, t: str, now: float) -> dict:
    """How common an ICAO type is here: distinct aircraft in the last 24 h and when we first saw it."""
    hit = _type_cache.get(t)
    if hit and now - hit[0] < 600:
        return hit[1]
    n = conn.execute("SELECT COUNT(DISTINCT hex) FROM positions WHERE ts >= ? AND t = ?",
                     (int(now) - 86400, t)).fetchone()[0]
    row = conn.execute("SELECT first_seen FROM seen_types WHERE type = ?", (t,)).fetchone()
    result = {"type": t, "aircraft_24h": n, "first_seen": row[0] if row else None}
    _type_cache[t] = (now, result)
    return result


@router.get("/aircraft/{hex_id}")
def get_aircraft(hex_id: str):
    """Full live readsb record of one aircraft (IAS/TAS/Mach, wind, OAT, autopilot altitude, ...) + type stats."""
    hex_id = hex_id.lower()
    if not HEX_ID.match(hex_id):
        raise HTTPException(422, "Neplatný hex.")
    rec = next((a for a in (_poller.latest or {}).get("ac", []) if a.get("hex") == hex_id), None)
    if rec is None:
        raise HTTPException(404, "Letadlo teď není v datech.")
    return {"now": _poller.latest["now"], "aircraft": rec, "type_stats": type_seen(_poller.db, rec["t"], time.time()) if rec.get("t") else None}


@router.get("/registry/{hex_id}")
async def get_registry(hex_id: str):
    """Registry data from adsbdb.com. The owner is never returned for LADD/PIA aircraft (dbFlags & 12)."""
    hex_id = hex_id.lower()
    if not HEX_ID.match(hex_id) or hex_id.startswith("~"):
        raise HTTPException(422, "Neplatný hex.")
    rec = next((a for a in (_poller.latest or {}).get("ac", []) if a.get("hex") == hex_id), {})
    try:
        info = await enrich.aircraft(hex_id)
    except enrich.Unavailable:
        raise HTTPException(503, "Údaje o letadle teď nejde zjistit.")
    return {"hex": hex_id, "info": privacy_filter(info, rec.get("dbFlags") or 0)}


def privacy_filter(info: dict | None, db_flags: int) -> dict | None:
    """Drop owner identity for LADD (8) / PIA (4) aircraft."""
    if not info or not db_flags & 12:
        return info
    return {**info, "owner": None, "owner_country": None, "owner_country_iso": None, "operator_code": None,
            "registration": None}
