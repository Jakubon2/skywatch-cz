"""Extra endpoints: position history playback, stats, daily summary preview, route/photo/trail."""

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


def start(poller) -> asyncio.Task | None:
    """Call from the API lifespan: registers the history recorder, starts the daily summary loop."""
    global _poller
    _poller = poller
    poller.listeners.append(history.Recorder(poller.db))
    poller.listeners.append(passes.PassRecorder(poller.db))
    if CONFIG["daily_summary"]["enabled"]:
        return asyncio.create_task(summary.run_daily(poller.db))
    return None


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
