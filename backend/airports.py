"""Airport data from OurAirports (public domain). CSVs are downloaded once into data/."""

import csv
import math
from functools import cache

import httpx

from config import ROOT

DATA = ROOT / "data"
BASE_URL = "https://davidmegginson.github.io/ourairports-data"


def _csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        r = httpx.get(f"{BASE_URL}/{name}", timeout=60, follow_redirects=True)
        r.raise_for_status()
        path.write_bytes(r.content)
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@cache
def airport(ident: str) -> dict:
    """{"ident", "name", "lat", "lon", "elevation_ft", "runways": [{"ident", "lat", "lon", "elevation_ft", "heading"}]}"""
    row = next(a for a in _csv("airports.csv") if a["ident"] == ident)
    runways = []
    for r in _csv("runways.csv"):
        if r["airport_ident"] != ident or r["closed"] == "1":
            continue
        for end in ("le", "he"):
            if r[f"{end}_latitude_deg"]:
                runways.append({
                    "ident": r[f"{end}_ident"],
                    "lat": float(r[f"{end}_latitude_deg"]),
                    "lon": float(r[f"{end}_longitude_deg"]),
                    "elevation_ft": int(r[f"{end}_elevation_ft"] or row["elevation_ft"]),
                    "heading": float(r[f"{end}_heading_degT"] or 0),
                })
    return {
        "ident": ident,
        "name": row["name"],
        "lat": float(row["latitude_deg"]),
        "lon": float(row["longitude_deg"]),
        "elevation_ft": int(row["elevation_ft"]),
        "runways": runways,
    }


@cache
def _nearby_airports() -> list[dict]:
    """Airports (not heliports) in a box around central Europe, for nearest()."""
    out = []
    for a in _csv("airports.csv"):
        if a["type"] not in ("large_airport", "medium_airport", "small_airport"):
            continue
        lat, lon = float(a["latitude_deg"]), float(a["longitude_deg"])
        if 45 <= lat <= 55 and 7 <= lon <= 25:
            out.append({"ident": a["ident"], "iata": a["iata_code"] or None, "name": a["name"],
                        "city": a["municipality"] or None, "lat": lat, "lon": lon, "size": a["type"]})
    return out


def nearest(lat: float, lon: float, max_km: float) -> dict | None:
    """Closest airport within max_km (bigger airports win near ties), or None."""
    best, best_d = None, max_km
    for a in _nearby_airports():
        dy = (a["lat"] - lat) * 111.2
        dx = (a["lon"] - lon) * 111.2 * math.cos(math.radians(lat))
        d = math.hypot(dx, dy) - (2 if a["size"] == "large_airport" else 1 if a["size"] == "medium_airport" else 0)
        if d < best_d:
            best, best_d = a, d
    return best
