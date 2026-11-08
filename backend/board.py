"""Arrivals/departures board for one airport (LKPR), estimated from the live ADS-B snapshot.

build_board() is a pure function: aircraft + cached routes (+ optional track history) -> two lists.
The router only reads routes already in enrich's cache and looks up a few missing ones in the
background, so opening the board never waits on (or hammers) the route APIs.
"""

import asyncio
import logging
import time

from fastapi import APIRouter

import airports
import enrich
from config import CONFIG
from detectors.geo import bearing_deg, distance_nm, heading_change

log = logging.getLogger("board")

KM_PER_NM = 1.852


def _callsign(a: dict) -> str:
    return (a.get("flight") or "").strip().upper()


def _is_ground(a: dict, field_ft: int, cfg: dict) -> bool:
    alt = a.get("alt_baro")
    if alt == "ground":
        return True
    return (isinstance(alt, (int, float)) and alt - field_ft < cfg["ground_max_agl_ft"]
            and (a.get("gs") or 0) < cfg["ground_max_gs_kt"])


def _transition(track: list[dict], field_ft: int, cfg: dict, to_ground: bool) -> float | None:
    """Timestamp (s) of the last ground->air (to_ground=False) or air->ground switch in the track."""
    found = None
    track = list(track)
    for prev, cur in zip(track, track[1:]):
        if _is_ground(prev, field_ft, cfg) != to_ground and _is_ground(cur, field_ft, cfg) == to_ground:
            found = cur["ts"]
    return found


def _place(ap: dict | None) -> dict | None:
    if not ap:
        return None
    return {"city": ap.get("location") or ap.get("name"), "code": ap.get("iata") or ap.get("icao"),
            "icao": ap.get("icao")}


def _is_vehicle(a: dict, cfg: dict) -> bool:
    return a.get("t") in cfg["exclude_types"] or a.get("category") in cfg["exclude_categories"]


def classify(a: dict, airport: dict, cfg: dict, route: dict | None) -> str | None:
    """'arrival', 'departure' or None for one aircraft."""
    if _is_vehicle(a, cfg):
        return None
    field = airport["elevation_ft"]
    ident = airport["ident"]
    dist_km = distance_nm(airport["lat"], airport["lon"], a["lat"], a["lon"]) * KM_PER_NM
    if dist_km > cfg["radius_km"]:
        return None
    dest = route and route.get("destination", {}).get("icao")
    orig = route and route.get("origin", {}).get("icao")

    if _is_ground(a, field, cfg):
        if dist_km > cfg["ground_radius_km"]:
            return None
        return "arrival" if dest == ident and orig != ident else "departure"

    if dest == ident:
        return "arrival"
    if orig == ident:
        return "departure"
    if route:                       # known route that doesn't touch the airport = overflight
        return None

    alt = a.get("alt_baro")
    if not isinstance(alt, (int, float)) or not a.get("gs"):
        return None
    rate = a.get("baro_rate") or 0
    track = a.get("track")
    to_airport = bearing_deg(a["lat"], a["lon"], airport["lat"], airport["lon"])
    toward = track is not None and abs(heading_change(track, to_airport)) <= cfg["toward_max_deg"]
    away = track is not None and abs(heading_change(track, (to_airport + 180) % 360)) <= 90

    if rate > cfg["climb_fpm"]:
        if dist_km <= cfg["departure_radius_km"] and alt <= cfg["departure_max_alt_ft"] and (away or dist_km < 10):
            return "departure"
        return None
    descending = rate < -cfg["descent_fpm"] and alt <= cfg["arrival_max_alt_ft"]
    low_and_close = dist_km <= cfg["approach_radius_km"] and alt - field <= cfg["approach_max_agl_ft"]
    if toward and (descending or low_and_close):
        return "arrival"
    return None


def build_board(aircraft: list[dict], now_ms: int, airport: dict, cfg: dict,
                routes: dict[str, dict | None], tracks: dict | None = None) -> dict:
    """routes: callsign -> route (enrich.route shape) for the callsigns whose route is known.
    tracks: hex -> list of samples with "ts" (seconds), used for actual take-off/landing times."""
    field = airport["elevation_ft"]
    now = now_ms / 1000
    arrivals, departures = [], []

    for a in aircraft:
        if "lat" not in a or "lon" not in a:
            continue
        cs = _callsign(a)
        route = routes.get(cs) if cs else None
        if route and route.get("plausible") is False:
            route = None
        kind = classify(a, airport, cfg, route)
        if not kind:
            continue
        dist_km = distance_nm(airport["lat"], airport["lon"], a["lat"], a["lon"]) * KM_PER_NM
        ground = _is_ground(a, field, cfg)
        gs = a.get("gs") or 0
        track = (tracks or {}).get(a["hex"]) or []
        row = {
            "hex": a["hex"], "callsign": cs or None, "reg": a.get("r"), "type": a.get("t"),
            "dist_km": round(dist_km, 1),
            "alt_ft": None if ground else a.get("alt_baro"),
            "route_known": route is not None,
            "time_ms": None, "eta_min": None, "estimated": True,
        }
        if kind == "arrival":
            row["place"] = _place(route and route.get("origin"))
            if ground:
                row["status"] = "na zemi"
                landed = _transition(track, field, cfg, to_ground=True)
                if landed:
                    row.update(time_ms=int(landed * 1000), estimated=False)
            else:
                row["status"] = "přistává"
                if gs > 0:
                    minutes = dist_km * cfg["eta_path_factor"] / (gs * KM_PER_NM) * 60
                    row.update(eta_min=round(minutes), time_ms=int(now_ms + minutes * 60_000))
            arrivals.append(row)
        else:
            row["place"] = _place(route and route.get("destination"))
            if ground:
                row["status"] = "odlétá" if gs >= cfg["taxi_min_kt"] else "na zemi"
            else:
                row["status"] = "vzlétl"
                took_off = _transition(track, field, cfg, to_ground=False)
                if took_off:
                    row.update(time_ms=int(took_off * 1000), estimated=False)
                elif gs > 0:
                    minutes = dist_km / (gs * cfg["departed_speed_factor"] * KM_PER_NM) * 60
                    row["time_ms"] = int(now_ms - minutes * 60_000)
            departures.append(row)

    # Arrivals: airborne by ETA, landed ones last (most recent first).
    arrivals.sort(key=lambda r: (r["status"] == "na zemi", r["eta_min"] if r["eta_min"] is not None
                                 else -(r["time_ms"] or 0)))
    # Departures: rolling/taxiing first, then the most recent take-offs, parked aircraft last.
    order = {"odlétá": 0, "vzlétl": 1, "na zemi": 2}
    departures.sort(key=lambda r: (order[r["status"]], -(r["time_ms"] or 0), r["dist_km"]))
    n = cfg["max_rows"]
    return {"now": now_ms, "airport": {"ident": airport["ident"], "name": airport["name"]},
            "arrivals": arrivals[:n], "departures": departures[:n]}


def route_candidates(aircraft: list[dict], airport: dict, cfg: dict, known: set[str]) -> list[dict]:
    """Aircraft worth a route lookup (near, low or on the ground at the airport), closest first."""
    out = []
    for a in aircraft:
        cs = _callsign(a)
        if not cs or cs in known or "lat" not in a or _is_vehicle(a, cfg):
            continue
        dist_km = distance_nm(airport["lat"], airport["lon"], a["lat"], a["lon"]) * KM_PER_NM
        alt = a.get("alt_baro")
        if _is_ground(a, airport["elevation_ft"], cfg):
            ok = dist_km <= cfg["ground_radius_km"]
        else:
            ok = dist_km <= cfg["radius_km"] and isinstance(alt, (int, float)) and alt <= cfg["route_candidate_max_alt_ft"]
        if ok:
            out.append((dist_km, a))
    return [a for _, a in sorted(out, key=lambda x: x[0])]


def make_router(poller) -> APIRouter:
    router = APIRouter(prefix="/api")
    cfg = CONFIG["board"]
    lookups: list[float] = []          # monotonic times of our own route lookups (rolling hour)
    running: dict = {"task": None}

    async def lookup(planes: list[dict]):
        for a in planes:
            now = time.monotonic()
            lookups[:] = [t for t in lookups if now - t < 3600]
            if len(lookups) >= cfg["route_lookups_per_hour"]:
                return
            lookups.append(now)
            try:
                await enrich.route(_callsign(a), a["lat"], a["lon"])
            except enrich.Unavailable:
                return
            except Exception:  # noqa: BLE001 - background task, never crash the loop
                log.exception("route lookup failed")
                return

    @router.get("/board")
    async def board():
        latest = poller.latest
        try:
            airport = airports.airport(cfg["airport"])
        except Exception:  # noqa: BLE001 - CSV missing and download failed
            log.exception("airport data unavailable")
            airport = None
        if not latest or not airport:
            return {"now": None, "airport": None, "arrivals": [], "departures": []}

        routes, known = {}, set()
        for a in latest["ac"]:
            cs = _callsign(a)
            if cs:
                hit, value = enrich.routes.cached(cs)
                if hit:
                    known.add(cs)
                    if value:
                        routes[cs] = value

        task = running["task"]
        if task is None or task.done():
            todo = route_candidates(latest["ac"], airport, cfg, known)[: cfg["route_lookups_per_request"]]
            if todo:
                running["task"] = asyncio.create_task(lookup(todo))

        return build_board(latest["ac"], latest["now"], airport, cfg, routes, poller.history)

    return router
