"""Map overlay data: airspace zones (GET /api/airspace) and the latest radar frame (GET /api/radar).

Airspace comes from openAIP (CC BY-NC 4.0): the public per-country GeoJSON export, or the REST API
when OPENAIP_API_KEY is set. Both use the same schema; `parse` is a pure function that keeps the
types from config and turns the numeric codes into Czech labels. The whole country is fetched once
per cache period (never per viewport) and kept on disk so restarts don't refetch.

Radar: RainViewer's public weather-maps.json, reduced to a ready-to-use tile URL template.
"""

import json
import logging
import os
import time

import httpx
from fastapi import APIRouter, HTTPException

from config import CONFIG, ROOT

log = logging.getLogger("airspace")
router = APIRouter(prefix="/api")
UA = {"User-Agent": "skywatch-cz/0.1"}
FT_TO_M = 0.3048

KIND_NAMES = {
    "CTR": "Řízený okrsek", "MCTR": "Vojenský řízený okrsek", "ATZ": "Letištní provozní zóna",
    "TMA": "Koncová řízená oblast", "CTA": "Řízená oblast", "R": "Omezený prostor",
    "P": "Zakázaný prostor", "D": "Nebezpečný prostor", "TRA": "Dočasně rezervovaný prostor",
    "TSA": "Dočasně vyhrazený prostor", "RMZ": "Zóna povinného rádiového spojení",
    "TMZ": "Zóna povinného použití odpovídače",
}
ICAO_CLASS = {0: "A", 1: "B", 2: "C", 3: "D", 4: "E", 5: "F", 6: "G"}


def _num(v: float) -> str:
    return f"{round(v):,}".replace(",", " ")  # 5000 -> "5 000"


def format_limit(limit: dict | None) -> str:
    """openAIP limit {value, unit (0 m, 1 ft, 6 FL), referenceDatum (0 GND, 1 MSL, 2 STD)} -> Czech text."""
    if not limit:
        return "neuvedeno"
    value, unit, ref = limit.get("value"), limit.get("unit"), limit.get("referenceDatum")
    if value is None:
        return "neuvedeno"
    # UI is metric only: FL keeps its name (pilots' term) but always with metres; ft becomes metres.
    if unit == 6:
        return f"FL{value:g} ≈ {_num(round(value * 100 * FT_TO_M, -2))} m"
    if ref == 0 and value == 0:
        return "zem"
    where = "nad zemí" if ref == 0 else "n. m."
    metres = value if unit == 0 else round(value * FT_TO_M, -1)
    return f"{_num(metres)} m {where}"


def _round_coords(c):
    return [_round_coords(x) for x in c] if isinstance(c[0], list) else [round(c[0], 5), round(c[1], 5)]


def parse(items: list[dict], types: dict) -> list[dict]:
    """openAIP airspace objects (export features' properties + geometry, or API items) -> slim GeoJSON features."""
    types = {int(k): v for k, v in types.items()}
    out = []
    for it in items:
        props = it.get("properties", it)
        geom = it.get("geometry")
        kind = types.get(props.get("type"))
        if not kind or not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        out.append({
            "type": "Feature",
            "geometry": {"type": geom["type"], "coordinates": _round_coords(geom["coordinates"])},
            "properties": {
                "name": props.get("name") or "Bez názvu",
                "kind": kind,
                "kind_name": KIND_NAMES.get(kind, kind),
                "icao_class": ICAO_CLASS.get(props.get("icaoClass")),
                "lower": format_limit(props.get("lowerLimit")),
                "upper": format_limit(props.get("upperLimit")),
                "lower_ft": _limit_ft(props.get("lowerLimit")),
                "by_notam": bool(props.get("byNotam")),
            },
        })
    out.sort(key=lambda f: f["properties"]["lower_ft"])
    return out


def _limit_ft(limit: dict | None) -> float:
    """Rough feet for sorting; AGL is treated as MSL, which is fine for ordering."""
    if not limit or limit.get("value") is None:
        return 0
    v = limit["value"]
    return v * 100 if limit.get("unit") == 6 else v / FT_TO_M if limit.get("unit") == 0 else v


# --- airspace --------------------------------------------------------------------------------

_air = {"data": None, "fetched": 0.0}


def _cache_path(country: str):
    return ROOT / "data" / f"airspace_{country.lower()}.json"


async def _download(cfg: dict) -> tuple[list[dict], str]:
    key = os.getenv("OPENAIP_API_KEY") or None
    async with httpx.AsyncClient(timeout=cfg["timeout_s"], headers=UA) as http:
        if not key:
            r = await http.get(cfg["export_url"].format(country=cfg["country"].lower()))
            r.raise_for_status()
            return r.json()["features"], "export"
        items, page = [], 1
        while True:
            r = await http.get(cfg["api_url"], params={"country": cfg["country"], "page": page, "limit": 1000},
                               headers={"x-openaip-api-key": key})
            r.raise_for_status()
            d = r.json()
            items += d["items"]
            if page >= d.get("totalPages", 1):
                return items, "api"
            page += 1


@router.get("/airspace")
async def airspace():
    cfg = CONFIG["map_layers"]["airspace"]
    max_age = cfg["cache_hours"] * 3600
    path = _cache_path(cfg["country"])
    if _air["data"] is None and path.exists():
        try:
            _air["data"] = json.loads(path.read_text(encoding="utf-8"))
            _air["fetched"] = _air["data"]["fetched"]
        except (OSError, ValueError, KeyError):
            pass
    if _air["data"] is not None and time.time() - _air["fetched"] < max_age:
        return _air["data"]
    try:
        items, source = await _download(cfg)
        data = {"type": "FeatureCollection", "features": parse(items, cfg["types"]), "source": source,
                "fetched": time.time(), "attribution": "Vzdušné prostory: openAIP (CC BY-NC 4.0)"}
        _air["data"], _air["fetched"] = data, data["fetched"]
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("airspace fetch failed: %s", e)
        _air["fetched"] = time.time() - max_age + 600  # retry in 10 min, serve stale meanwhile
        if _air["data"] is None:
            raise HTTPException(502, "Vzdušné prostory se nepodařilo načíst.")
    return _air["data"]


# --- radar -----------------------------------------------------------------------------------

_radar = {"data": None, "fetched": 0.0}


def latest_radar(maps: dict, color_scheme: int) -> dict | None:
    """RainViewer weather-maps.json -> {time, url} of the newest past radar frame, or None."""
    frames = (maps.get("radar") or {}).get("past") or []
    if not frames or not maps.get("host"):
        return None
    f = max(frames, key=lambda x: x["time"])
    return {"time": f["time"], "url": f"{maps['host']}{f['path']}/256/{{z}}/{{x}}/{{y}}/{color_scheme}/1_1.png"}


@router.get("/radar")
async def radar():
    cfg = CONFIG["map_layers"]["radar"]
    if _radar["data"] is not None and time.monotonic() - _radar["fetched"] < cfg["cache_minutes"] * 60:
        return _radar["data"]
    try:
        async with httpx.AsyncClient(timeout=10, headers=UA) as http:
            r = await http.get(cfg["url"])
            r.raise_for_status()
            frame = latest_radar(r.json(), cfg["color_scheme"])
        if not frame:
            raise ValueError("no radar frames")
        _radar["data"] = {**frame, "max_native_zoom": cfg["max_native_zoom"], "opacity": cfg["opacity"],
                          "attribution": '<a href="https://www.rainviewer.com/">RainViewer</a>'}
        _radar["fetched"] = time.monotonic()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("radar fetch failed: %s", e)
        _radar["fetched"] = time.monotonic()
        if _radar["data"] is None:
            raise HTTPException(502, "Radar se nepodařilo načíst.")
    return _radar["data"]
