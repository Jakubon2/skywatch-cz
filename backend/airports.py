"""Airport data from OurAirports (public domain). CSVs are downloaded once into data/."""

import csv
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
