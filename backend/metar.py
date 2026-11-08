"""Current METAR for the airport, used as weather context for AI explanations."""

import logging
import time

import httpx

from config import CONFIG

log = logging.getLogger("metar")

URL = "https://aviationweather.gov/api/data/metar"

_cache = {"text": None, "fetched": None}  # fetched = time.monotonic() of last success


def format_metar(obs: dict) -> str:
    """Raw METAR plus the flight category (VFR/MVFR/IFR/LIFR), which hints at fog or low cloud."""
    text = obs.get("rawOb", "").strip()
    if obs.get("fltCat"):
        text += f" (kategorie {obs['fltCat']})"
    return text


async def get_metar() -> str | None:
    """Return the cached METAR text, refreshing it at most every metar_refresh_minutes.

    On a fetch error returns the last known value (possibly None).
    """
    cfg = CONFIG["explain"]
    fetched = _cache["fetched"]
    if fetched is not None and time.monotonic() - fetched < cfg["metar_refresh_minutes"] * 60:
        return _cache["text"]

    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "skywatch-cz/0.1"}) as http:
            r = await http.get(URL, params={"ids": cfg["metar_station"], "format": "json"})
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("METAR fetch failed (%s), using cached value", e)
        return _cache["text"]

    if data:
        _cache["text"] = format_metar(data[0])
    _cache["fetched"] = time.monotonic()
    return _cache["text"]
