"""Detail enrichment: flight route (adsb.lol routeset) and aircraft photo (planespotters.net).

Both are cached hard and throttled; results (including "unknown") are cached so the UI
never makes us hit the upstream in a loop.
"""

import asyncio
import logging
import os
import re
import time

import httpx

from config import CONFIG

log = logging.getLogger("enrich")

HEX = re.compile(r"^[0-9a-f]{6}$")


class Unavailable(Exception):
    """Upstream rate-limited, failing or not configured; try again later."""


def user_agent() -> str:
    # planespotters requires a contact URL or e-mail in the UA; set SKYWATCH_CONTACT in .env.
    contact = os.getenv("SKYWATCH_CONTACT")
    return f"skywatch-cz/0.1 (+{contact})" if contact else "skywatch-cz/0.1 (personal app)"


class Upstream:
    """TTL cache + minimum spacing + hourly cap around one upstream API."""

    def __init__(self, name: str):
        self.cfg = CONFIG["enrich"][name]
        self.cache: dict[str, tuple[float, dict | None]] = {}
        self.lock = asyncio.Lock()
        self.last = 0.0
        self.calls: list[float] = []

    def cached(self, key: str):
        hit = self.cache.get(key)
        if hit and hit[0] > time.monotonic():
            return True, hit[1]
        return False, None

    def store(self, key: str, value: dict | None):
        ttl = self.cfg["cache_hours"] * 3600 if value else self.cfg["miss_cache_minutes"] * 60
        if len(self.cache) > 2000:
            now = time.monotonic()
            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
        self.cache[key] = (time.monotonic() + ttl, value)

    async def slot(self):
        """Wait for the minimum spacing; raise Unavailable when the hourly cap is used up."""
        now = time.monotonic()
        self.calls = [t for t in self.calls if now - t < 3600]
        if len(self.calls) >= self.cfg["max_per_hour"]:
            raise Unavailable()
        wait = self.last + self.cfg["min_interval_s"] - now
        if wait > 0:
            await asyncio.sleep(wait)
        self.last = time.monotonic()
        self.calls.append(self.last)


routes = Upstream("route")
photos = Upstream("photo")


# ---------- route ----------

def _airport(a: dict) -> dict:
    return {k: a.get(k) for k in ("icao", "iata", "name", "location", "countryiso2", "lat", "lon")}


def parse_route(data, callsign: str) -> dict | None:
    """adsb.lol routeset response (list of routes) -> {origin, destination, stops, plausible} or None."""
    if not isinstance(data, list):
        return None
    for r in data:
        if not isinstance(r, dict) or (r.get("callsign") or "").upper() != callsign:
            continue
        airports = [a for a in r.get("_airports") or [] if isinstance(a, dict)]
        if len(airports) < 2:
            return None
        return {
            "callsign": callsign,
            "airline_code": r.get("airline_code"),
            "origin": _airport(airports[0]),
            "destination": _airport(airports[-1]),
            "stops": [_airport(a) for a in airports[1:-1]],
            "codes": r.get("_airport_codes_iata") or r.get("airport_codes"),
            # adsb.lol's check whether the route fits the aircraft's position; False = likely stale.
            "plausible": bool(r.get("plausible")),
        }
    return None


async def route(callsign: str, lat: float, lon: float, client: httpx.AsyncClient | None = None) -> dict | None:
    callsign = callsign.strip().upper()
    hit, value = routes.cached(callsign)
    if hit:
        return value
    async with routes.lock:
        hit, value = routes.cached(callsign)
        if hit:
            return value
        await routes.slot()
        body = {"planes": [{"callsign": callsign, "lat": lat, "lng": lon}]}
        try:
            r = await _post(client, routes.cfg["url"], body)
            if r.status_code == 429:
                raise Unavailable()
            r.raise_for_status()
            # The API sometimes answers with an empty body for unknown callsigns.
            value = parse_route(r.json() if r.content.strip() else None, callsign)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("route lookup failed for %s: %s", callsign, e)
            raise Unavailable() from e     # don't cache transient failures, but don't retry now either
        routes.store(callsign, value)
        return value


async def _post(client, url, body):
    if client:
        return await client.post(url, json=body)
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent()}) as c:
        return await c.post(url, json=body)


# ---------- photo ----------

def parse_photo(data) -> dict | None:
    """planespotters /pub/photos response -> first photo with attribution, or None."""
    photos_ = (data or {}).get("photos") if isinstance(data, dict) else None
    if not photos_:
        return None
    p = photos_[0]
    thumb = p.get("thumbnail") or {}
    large = p.get("thumbnail_large") or {}
    if not (thumb.get("src") or large.get("src")):
        return None
    size = (large.get("size") or thumb.get("size") or {})
    return {
        "thumbnail": thumb.get("src"),
        "thumbnail_large": large.get("src"),
        "width": size.get("width"),
        "height": size.get("height"),
        "photographer": p.get("photographer"),
        "link": p.get("link"),
        "source": "planespotters.net",
    }


async def photo(key: str, client: httpx.AsyncClient | None = None) -> dict | None:
    """Photo by ICAO hex (6 hex digits) or registration."""
    key = key.strip()
    kind = "hex" if HEX.match(key.lower()) else "reg"
    key = key.lower() if kind == "hex" else key.upper()
    cache_key = f"{kind}:{key}"
    hit, value = photos.cached(cache_key)
    if hit:
        return value
    if not os.getenv("SKYWATCH_CONTACT"):
        raise Unavailable("SKYWATCH_CONTACT not set (planespotters requires a contact in the User-Agent)")
    async with photos.lock:
        hit, value = photos.cached(cache_key)
        if hit:
            return value
        await photos.slot()
        url = f"{photos.cfg['url'].rstrip('/')}/{kind}/{key}"
        try:
            if client:
                r = await client.get(url)
            else:
                async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent()}) as c:
                    r = await c.get(url)
            if r.status_code == 429:
                raise Unavailable()
            r.raise_for_status()
            value = parse_photo(r.json())
        except (httpx.HTTPError, ValueError) as e:
            log.warning("photo lookup failed for %s: %s", cache_key, e)
            raise Unavailable() from e
        photos.store(cache_key, value)
        return value
