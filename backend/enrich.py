"""Detail enrichment: flight route (adsb.lol routeset, adsbdb.com fallback) and aircraft photo (planespotters.net).

Both are cached hard and throttled; results (including "unknown") are cached so the UI
never makes us hit the upstream in a loop.
"""

import asyncio
import math
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
        self.last = -math.inf  # "never" (monotonic counts from boot, so 0.0 would mean "just now")
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
registry = Upstream("aircraft")


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


def parse_adsbdb(data, lat: float, lon: float) -> dict | None:
    """adsbdb.com /v0/callsign response -> same shape as parse_route. adsbdb has no plausibility
    check, so we call a route plausible when the aircraft lies roughly on the way between the two airports."""
    resp = data.get("response") if isinstance(data, dict) else None   # a string like "unknown callsign" on a miss
    fr = resp.get("flightroute") if isinstance(resp, dict) else None
    if not isinstance(fr, dict) or not fr.get("origin") or not fr.get("destination"):
        return None

    def ap(a):
        return {"icao": a.get("icao_code"), "iata": a.get("iata_code"), "name": a.get("name"),
                "location": a.get("municipality"), "countryiso2": a.get("country_iso_name"),
                "lat": a.get("latitude"), "lon": a.get("longitude")}

    o, d = ap(fr["origin"]), ap(fr["destination"])
    plausible = None not in (o["lat"], o["lon"], d["lat"], d["lon"])
    if plausible:
        direct = _km(o["lat"], o["lon"], d["lat"], d["lon"])
        plausible = _km(o["lat"], o["lon"], lat, lon) + _km(lat, lon, d["lat"], d["lon"]) <= direct * 1.3 + 150
    return {
        "callsign": (fr.get("callsign_icao") or fr.get("callsign") or "").upper(),
        "airline_code": (fr.get("airline") or {}).get("icao"),
        "airline_name": (fr.get("airline") or {}).get("name"),
        "origin": o, "destination": d, "stops": [],
        "codes": "-".join(a["iata"] or a["icao"] or "?" for a in (o, d)),
        "plausible": plausible,
    }


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


async def _adsbdb_route(client, callsign: str, lat: float, lon: float) -> dict | None:
    """Fallback source when adsb.lol has no route. Failures here just mean 'no route'."""
    url = routes.cfg.get("fallback_url")
    if not url:
        return None
    try:
        if client:
            r = await client.get(url.format(callsign=callsign))
        else:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent()}) as c:
                r = await c.get(url.format(callsign=callsign))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return parse_adsbdb(r.json(), lat, lon)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("adsbdb route lookup failed for %s: %s", callsign, e)
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
            if value is None:
                value = await _adsbdb_route(client, callsign, lat, lon)
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


# ---------- aircraft registry (adsbdb.com) ----------

def parse_aircraft(data) -> dict | None:
    """adsbdb.com /v0/aircraft response -> type, manufacturer, owner and country, or None ("unknown aircraft")."""
    resp = data.get("response") if isinstance(data, dict) else None
    a = resp.get("aircraft") if isinstance(resp, dict) else None
    if not isinstance(a, dict):
        return None
    value = {
        "type": a.get("type"),                  # e.g. "737NG 8AS/W"
        "icao_type": a.get("icao_type"),
        "manufacturer": a.get("manufacturer"),
        "registration": a.get("registration"),
        "owner": a.get("registered_owner"),
        "owner_country": a.get("registered_owner_country_name"),
        "owner_country_iso": a.get("registered_owner_country_iso_name"),
        "operator_code": a.get("registered_owner_operator_flag_code"),
    }
    return value if any(value.values()) else None


async def aircraft(hex_id: str, client: httpx.AsyncClient | None = None) -> dict | None:
    """Registry data for an ICAO hex. Same politeness as route(): cached, spaced, capped per hour."""
    hex_id = hex_id.strip().lower()
    hit, value = registry.cached(hex_id)
    if hit:
        return value
    async with registry.lock:
        hit, value = registry.cached(hex_id)
        if hit:
            return value
        await registry.slot()
        try:
            url = registry.cfg["url"].format(hex=hex_id)
            if client:
                r = await client.get(url)
            else:
                async with httpx.AsyncClient(timeout=10, headers={"User-Agent": user_agent()}) as c:
                    r = await c.get(url)
            if r.status_code == 429:
                raise Unavailable()
            if r.status_code == 404:        # adsbdb answers 404 + "unknown aircraft"
                value = None
            else:
                r.raise_for_status()
                value = parse_aircraft(r.json())
        except (httpx.HTTPError, ValueError) as e:
            log.warning("aircraft lookup failed for %s: %s", hex_id, e)
            raise Unavailable() from e
        registry.store(hex_id, value)
        return value
