"""Rough aircraft noise estimate at a point on the ground (GET /api/noise).

This is a deliberately simple point-source model, NOT a measurement:

    L = L_ref(class) + offset(phase) - 20·log10(d / d_ref) - a·(d - d_ref) / 1000

* L_ref: typical LAmax in dB(A) at d_ref = 305 m (1000 ft) at take-off/climb thrust, per class
  (light / regional / narrowbody / widebody / rotorcraft). Ballpark values in line with EASA type-
  certificate noise data (certification levels in EPNdB at 120-450 m, roughly LAmax + 10..13 dB)
  and published LAmax-vs-distance curves (ECAC Doc 29 / ANP database NPD tables).
* offset(phase): climb 0 dB, approach/low level -2 dB, cruise -8 dB (reduced thrust).
  Phase from baro_rate (± climb_fpm) and altitude.
* 20·log10: spherical spreading of a point source (inverse-square law, -6 dB per doubling).
* a: one effective A-weighted atmospheric absorption coefficient in dB/km. ISO 9613-1 gives
  ~2-5 dB/km at 1 kHz, much less at low frequencies; since distant aircraft noise is dominated by
  low frequencies, a single broadband value of ~1.5 dB/km is used.

Ignored on purpose: ground reflection, terrain/buildings, wind and temperature gradients, engine
type, real thrust and aircraft weight. Expect errors of ±10 dB. Class tables live in config.yaml.
"""

import math

from fastapi import APIRouter, HTTPException, Query

from config import CONFIG
from detectors.geo import distance_nm

CFG = CONFIG["noise"]
NOTE = ("Jde o hrubý odhad z jednoduchého modelu (typ letadla, výška, vzdálenost), ne o měření. "
        "Skutečná hlasitost se může lišit o ±10 dB podle počasí, terénu, budov a výkonu motorů.")

_TYPE_CLASS = {t: cls for cls, types in CFG["type_class"].items() for t in types}


def aircraft_class(ac: dict) -> str | None:
    """Noise class by ICAO type, else by ADS-B category; None = unknown (skipped)."""
    return _TYPE_CLASS.get(ac.get("t")) or CFG["category_class"].get(ac.get("category"))


def flight_phase(alt_ft: float, baro_rate: float | None) -> str:
    rate = baro_rate or 0
    if rate > CFG["climb_fpm"]:
        return "climb"
    if rate < -CFG["climb_fpm"] or alt_ft < CFG["low_level_ft"]:
        return "approach"
    return "cruise"


def level_db(ref_db: float, slant_m: float) -> float:
    """Reference level at d_ref attenuated to slant_m: spherical spreading + atmospheric absorption."""
    d = max(slant_m, CFG["min_slant_m"])
    d_ref = CFG["ref_distance_m"]
    return ref_db - 20 * math.log10(d / d_ref) - CFG["absorption_db_per_km"] * (d - d_ref) / 1000


def label_cs(db: float) -> str:
    for upper, text in CFG["labels"]:
        if db < upper:
            return text
    return CFG["labels"][-1][1]


def energy_sum(levels: list[float]) -> float | None:
    if not levels:
        return None
    return 10 * math.log10(sum(10 ** (x / 10) for x in levels))


def estimate(aircraft: list[dict], lat: float, lon: float, radius_km: float,
             elev_m: float | None = None) -> dict:
    """Pure function: per-aircraft dB(A) estimates at (lat, lon), loudest first."""
    elev = CFG["observer_elev_m"] if elev_m is None else elev_m
    rows = []
    for a in aircraft:
        alt = a.get("alt_baro")
        if a.get("lat") is None or a.get("lon") is None or not isinstance(alt, (int, float)):
            continue  # no position, or on the ground ("ground")
        horiz_km = distance_nm(lat, lon, a["lat"], a["lon"]) * 1.852
        if horiz_km > radius_km:
            continue
        cls = aircraft_class(a)
        if cls is None:
            continue
        phase = flight_phase(alt, a.get("baro_rate"))
        height_m = max(alt * 0.3048 - elev, 0)
        slant_m = math.hypot(horiz_km * 1000, height_m)
        db = level_db(CFG["ref_db"][cls] + CFG["phase_offset_db"][phase], slant_m)
        rows.append({
            "hex": a.get("hex"), "flight": (a.get("flight") or "").strip() or None, "t": a.get("t"),
            "class": cls, "phase": phase, "alt_ft": alt, "lat": a["lat"], "lon": a["lon"],
            "distance_km": round(horiz_km, 2), "slant_km": round(slant_m / 1000, 2),
            "db": round(db, 1), "label": label_cs(db),
        })
    rows.sort(key=lambda r: -r["db"])
    total = energy_sum([r["db"] for r in rows])
    return {
        "estimate": True,
        "note": NOTE,
        "loudest": rows[0] if rows else None,
        "total_db": round(total, 1) if total is not None else None,
        "total_label": label_cs(total) if total is not None else None,
        "aircraft": rows,
    }


def make_router(poller) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/noise")
    def noise(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
              radius_km: float = Query(20, gt=0, le=CFG["max_radius_km"]),
              elev_m: float | None = Query(None, ge=-100, le=5000)):
        latest = poller.latest
        if not latest:
            raise HTTPException(503, "Zatím nemám data o letadlech.")
        res = estimate(latest["ac"], lat, lon, radius_km, elev_m)
        return {"now": latest["now"], "lat": lat, "lon": lon, "radius_km": radius_km, **res}

    return router
