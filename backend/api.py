"""FastAPI app. The poller runs as a background task inside this single process."""

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import airspace
import alerts_service
import board
import chat
import contrails
import metar_api
import feed
import flights
import noise
import pass_alerts
import push
import routes_core
import routes_extra
import watchlist
import whatwasthat
from poller import Poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

poller = Poller()
poller.listeners += [feed.on_events, alerts_service.on_snapshot]
poller.listeners.append(push.on_events)
alerts_service.load_last_hits(poller.db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    extra_task = routes_extra.start(poller)  # history recorder + daily summary loop
    task = asyncio.create_task(poller.run())
    yield
    task.cancel()
    if extra_task:
        extra_task.cancel()


app = FastAPI(title="skywatch-cz", lifespan=lifespan)
app.include_router(routes_core.make_router(poller))
app.include_router(routes_extra.router)
app.include_router(push.make_router(poller))
app.include_router(noise.make_router(poller))
app.include_router(contrails.router)
app.include_router(metar_api.router)
app.include_router(airspace.router)  # map overlays: airspace zones + radar frame
app.include_router(watchlist.make_router(poller))
app.include_router(pass_alerts.make_router(poller))  # heads-up before predicted passes
app.include_router(board.make_router(poller))  # LKPR arrivals/departures board
app.include_router(whatwasthat.make_router(poller))  # "Co to bylo?"
app.include_router(flights.make_router(poller))  # "Moje lety": follow one flight, push on take-off/landing


@app.get("/api/health")
def health():
    latest = poller.latest
    return {
        "ok": latest is not None,
        "snapshot_ms": latest["now"] if latest else None,
        "aircraft": len(latest["ac"]) if latest else 0,
        "tracks": len(poller.history),
    }


AIRCRAFT_FIELDS = ("hex", "flight", "r", "t", "lat", "lon", "alt_baro", "gs", "track",
                   "baro_rate", "squawk", "category", "dbFlags")


@app.get("/api/aircraft")
def aircraft():
    latest = poller.latest
    if not latest:
        return {"now": None, "aircraft": []}
    return {
        "now": latest["now"],
        "aircraft": [{k: a[k] for k in AIRCRAFT_FIELDS if k in a} for a in latest["ac"]],
    }


# --- Geocoding for "Nad hlavou": address -> coordinates via Nominatim (OSM) ---
# Usage policy: identifying User-Agent, at most 1 request/s, cache results, no autocomplete
# (the frontend only searches on submit). https://operations.osmfoundation.org/policies/nominatim/

import time  # noqa: E402

import httpx  # noqa: E402
from fastapi import HTTPException, Query  # noqa: E402

_geocode_cache: dict[str, list[dict]] = {}
_geocode_lock = asyncio.Lock()
_geocode_last = -math.inf  # "never" (monotonic counts from boot)


def _geocode_label(r: dict) -> str:
    ad = r.get("address", {})
    street = " ".join(filter(None, [ad.get("road") or ad.get("pedestrian"), ad.get("house_number")]))
    place = ad.get("city") or ad.get("town") or ad.get("village") or ad.get("municipality")
    name = r.get("name") if r.get("name") not in (ad.get("road"), place) else None
    parts = list(dict.fromkeys(filter(None, [name, street, ad.get("suburb"), place])))
    return ", ".join(parts) or r.get("display_name", "")


@app.get("/api/geocode")
async def geocode(q: str = Query(min_length=2, max_length=200)):
    global _geocode_last
    key = " ".join(q.lower().split())
    if key in _geocode_cache:
        return _geocode_cache[key]
    async with _geocode_lock:
        if key in _geocode_cache:
            return _geocode_cache[key]
        wait = _geocode_last + 1.0 - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "skywatch-cz/0.1 (personal app)"}) as http:
                r = await http.get("https://nominatim.openstreetmap.org/search", params={
                    "q": q, "format": "jsonv2", "countrycodes": "cz", "limit": 5,
                    "addressdetails": 1, "accept-language": "cs",
                })
                r.raise_for_status()
                rows = r.json()
        except (httpx.HTTPError, ValueError) as e:
            logging.getLogger("geocode").warning("Nominatim failed: %s", e)
            raise HTTPException(502, "Geocoding failed")
        finally:
            _geocode_last = time.monotonic()
    results = [{"label": _geocode_label(x), "lat": float(x["lat"]), "lon": float(x["lon"])} for x in rows]
    if len(_geocode_cache) > 500:
        _geocode_cache.clear()
    _geocode_cache[key] = results
    return results


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    if req.messages[-1].role != "user":
        raise HTTPException(422, "Poslední zpráva musí být od uživatele.")
    try:
        reply = await chat.chat([m.model_dump() for m in req.messages], poller)
    except chat.ChatLimitError:
        raise HTTPException(429, "Chat má vyčerpaný hodinový limit dotazů. Zkus to prosím později.")
    return {"reply": reply}
