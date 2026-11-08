"""'Co to bylo?': which aircraft passed closest/loudest over a point around a given time.

Tracks come from the poller's in-memory history (last few minutes, ~10 s samples) and the stored
position history (history.py, 30 s samples, 24 h). Between samples the position and altitude are
interpolated linearly, so a jet that crossed overhead between two 30 s samples is still found.
Candidates are ranked by the rough noise estimate from noise.py. The sentence and the reasons are
built from the data only, never guessed.
"""

import asyncio
import logging
import math
import time
from datetime import datetime

import yaml
from fastapi import APIRouter, HTTPException, Query

import enrich
import noise
from config import CONFIG, ROOT
from explain import PRAGUE
from history import AIRLINES, AIRLINE_CALLSIGN

log = logging.getLogger("whatwasthat")

CFG = CONFIG["what_was_that"]
KM_PER_DEG = 111.32
FT = 0.3048
PRIVATE_FLAGS = 12          # readsb dbFlags: 8 = FAA LADD, 4 = PIA -> never show registration/callsign

with open(ROOT / "config" / "interesting_types.yaml", encoding="utf-8") as f:
    TYPE_NAMES = {**(yaml.safe_load(f) or {}), **CFG["type_names"]}


# ---------- tracks ----------

def _sample(ts, lat, lon, alt, gs=None, track=None, rate=None, flight=None, t=None, r=None,
            category=None, flags=None) -> dict:
    return {"ts": float(ts), "lat": lat, "lon": lon, "alt": alt, "gs": gs, "track": track,
            "rate": rate, "flight": (flight or "").strip() or None, "t": t, "r": r,
            "category": category, "flags": flags}


def merge_tracks(live: dict, rows: list) -> dict[str, list[dict]]:
    """Live poller samples ({hex: [readsb dict + ts]}) and stored rows
    (ts, hex, flight, t, lat, lon, alt, track, gs, category, db_flags) -> {hex: samples by time}."""
    out: dict[str, list[dict]] = {}
    for ts, hx, flight, t, lat, lon, alt, track, gs, cat, flags in rows:
        out.setdefault(hx, []).append(_sample(ts, lat, lon, alt, gs, track, None, flight, t, None, cat, flags))
    for hx, samples in live.items():
        for s in samples:
            out.setdefault(hx, []).append(_sample(
                s["ts"], s["lat"], s["lon"], s.get("alt_baro"), s.get("gs"), s.get("track"),
                s.get("baro_rate"), s.get("flight"), s.get("t"), s.get("r"), s.get("category"), s.get("dbFlags")))
    for hx, samples in out.items():
        samples.sort(key=lambda s: s["ts"])
        dedup = []
        for s in samples:       # the same position can be both stored and live: keep the richer live one
            if dedup and s["ts"] - dedup[-1]["ts"] < 1:
                dedup[-1] = s if s["rate"] is not None or s["r"] else dedup[-1]
            else:
                dedup.append(s)
        out[hx] = dedup
    return out


def _meta(samples: list[dict]) -> dict:
    m = {}
    for s in samples:
        for k in ("flight", "t", "r", "category", "flags"):
            if s[k] is not None:
                m[k] = s[k]
    return m


# ---------- closest point of approach ----------

def _xyz(s: dict, lat0: float, lon0: float, elev_m: float) -> tuple[float, float, float]:
    """Flat local frame around the observer, km. Fine for tens of km."""
    x = (s["lon"] - lon0) * KM_PER_DEG * math.cos(math.radians(lat0))
    y = (s["lat"] - lat0) * KM_PER_DEG
    z = max(s["alt"] * FT - elev_m, 0) / 1000
    return x, y, z


def _airborne(s: dict) -> bool:
    return isinstance(s["alt"], (int, float)) and s["lat"] is not None and s["lon"] is not None


def cpa(samples: list[dict], lat: float, lon: float, start: float, end: float,
        elev_m: float, max_gap_s: float) -> dict | None:
    """Closest point (slant distance) of one track to the observer within [start, end],
    interpolating linearly between consecutive airborne samples no more than max_gap_s apart."""
    air = [s for s in samples if _airborne(s)]
    best = None

    def consider(dist, ts, p, a, b, f):
        nonlocal best
        if best is None or dist < best["dist"]:
            best = {"dist": dist, "ts": ts, "p": p, "a": a, "b": b, "f": f}

    for s in air:                                   # single points (also covers isolated samples)
        if start <= s["ts"] <= end:
            p = _xyz(s, lat, lon, elev_m)
            consider(math.hypot(*p), s["ts"], p, s, s, 0.0)
    for a, b in zip(air, air[1:]):
        dt = b["ts"] - a["ts"]
        if dt <= 0 or dt > max_gap_s or b["ts"] < start or a["ts"] > end:
            continue
        pa, pb = _xyz(a, lat, lon, elev_m), _xyz(b, lat, lon, elev_m)
        f0 = (max(a["ts"], start) - a["ts"]) / dt
        f1 = (min(b["ts"], end) - a["ts"]) / dt
        q0 = [pa[i] + (pb[i] - pa[i]) * f0 for i in range(3)]
        d = [(pb[i] - pa[i]) * (f1 - f0) for i in range(3)]
        dd = sum(v * v for v in d)
        g = 0.0 if dd == 0 else min(max(-sum(q0[i] * d[i] for i in range(3)) / dd, 0.0), 1.0)
        p = tuple(q0[i] + d[i] * g for i in range(3))
        f = f0 + (f1 - f0) * g
        consider(math.hypot(*p), a["ts"] + dt * f, p, a, b, f)
    return best


def _lerp(a, b, f):
    if a is None:
        return b
    if b is None:
        return a
    return a + (b - a) * f


def _vertical_fpm(c: dict) -> float | None:
    a, b = c["a"], c["b"]
    near = a if c["f"] < 0.5 else b
    if near["rate"] is not None:
        return near["rate"]
    if b["ts"] > a["ts"]:
        return (b["alt"] - a["alt"]) / (b["ts"] - a["ts"]) * 60
    return None


def find_passes(tracks: dict[str, list[dict]], lat: float, lon: float, start: float, end: float,
                elev_m: float | None = None, cfg: dict = CFG) -> list[dict]:
    """Pure function: per aircraft, its closest point to (lat, lon) in [start, end], loudest first."""
    elev = noise.CFG["observer_elev_m"] if elev_m is None else elev_m
    out = []
    for hx, samples in tracks.items():
        c = cpa(samples, lat, lon, start, end, elev, cfg["max_gap_s"])
        if c is None:
            continue
        x, y, z = c["p"]
        horiz_km = math.hypot(x, y)
        if horiz_km > cfg["max_distance_km"]:
            continue
        a, b, f = c["a"], c["b"], c["f"]
        meta = _meta(samples)
        alt_ft = _lerp(a["alt"], b["alt"], f)
        rate = _vertical_fpm(c)
        cls = noise.aircraft_class({"t": meta.get("t"), "category": meta.get("category")})
        phase = noise.flight_phase(alt_ft, rate)
        slant_m = math.hypot(horiz_km * 1000, z * 1000)
        db = noise.level_db(noise.CFG["ref_db"][cls or cfg["unknown_class"]] + noise.CFG["phase_offset_db"][phase], slant_m)
        private = bool((meta.get("flags") or 0) & PRIVATE_FLAGS)
        pad = cfg["path_pad_s"]
        path = [[s["lat"], s["lon"]] for s in samples if _airborne(s) and abs(s["ts"] - c["ts"]) <= pad]
        out.append({
            "hex": hx,
            "flight": None if private else meta.get("flight"),
            "r": None if private else meta.get("r"),
            "t": meta.get("t"),
            "type_name": TYPE_NAMES.get(meta.get("t")),
            "private": private,
            "class": cls, "phase": phase,
            "cpa_ts": round(c["ts"], 1),
            "lat": round(_lerp(a["lat"], b["lat"], f), 5), "lon": round(_lerp(a["lon"], b["lon"], f), 5),
            "alt_ft": round(alt_ft), "alt_m": round(alt_ft * FT),
            "height_m": round(z * 1000),
            "rate_ms": round(rate * FT / 60, 1) if rate is not None else None,
            "gs_kmh": round(gs * 1.852) if (gs := _lerp(a["gs"], b["gs"], f)) is not None else None,
            "track": a["track"] if f < 0.5 else b["track"],
            "distance_km": round(horiz_km, 2), "slant_km": round(slant_m / 1000, 2),
            "db": round(db, 1), "label": noise.label_cs(db),
            "path": path,
        })
    out.sort(key=lambda r: (-r["db"], r["slant_km"]))
    return out


# ---------- Czech text ----------

def _num(x: float, d: int = 0) -> str:
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def _alt(m: float) -> str:
    return f"{_num(round(m / 50) * 50)} m"


def _km(km: float) -> str:
    return f"{_num(km, 1 if km < 10 else 0)} km"


def ago(seconds: float) -> str:
    s = max(0, round(seconds))
    if s < 60:
        return f"před {s} s"
    if s < 3600:
        return f"před {round(s / 60)} min"
    h, m = divmod(round(s / 60), 60)
    return f"před {h} h {m} min" if m else f"před {h} h"


def at_clock(ts: float, now: float) -> str:
    """'ve 2:14', 'v 15:03', 'včera ve 23:40' (Prague time). 've' before dvě/tři/čtyři/dvanáct/…"""
    t = datetime.fromtimestamp(ts, PRAGUE)
    prep = "ve" if t.hour in (2, 3, 4, 12, 13, 14, 20, 21, 22, 23) else "v"
    day = (datetime.fromtimestamp(now, PRAGUE).date() - t.date()).days
    pre = "včera " if day == 1 else "" if day == 0 else f"{t.day}. {t.month}. "
    return f"{pre}{prep} {t.hour}:{t.minute:02d}"


def operator(c: dict) -> str | None:
    m = AIRLINE_CALLSIGN.match(c["flight"] or "")
    return AIRLINES.get(m.group(1)) if m else None


def route_text(route: dict | None) -> str | None:
    if not route or route.get("plausible") is False:
        return None
    name = lambda a: a.get("location") or a.get("name") or a.get("iata") or a.get("icao")  # noqa: E731
    o, d = name(route["origin"] or {}), name(route["destination"] or {})
    return f"{o} → {d}" if o and d else None


def reasons(c: dict, cfg: dict = CFG) -> list[str]:
    """Why it was audible, only from the data. Verb endings for a neuter subject ('Letadlo letělo')
    or masculine for a helicopter ('Vrtulník letěl')."""
    r = cfg["reasons"]
    g = "" if c["class"] == "rotorcraft" else "o"
    out = []
    if c["db"] < r["quiet_db"]:
        return out          # nothing to explain
    if c["height_m"] < r["low_height_m"]:
        out.append(f"letěl{g} nízko")
    if c["rate_ms"] is not None and c["rate_ms"] > r["climb_ms"]:
        out.append(f"stoupal{g} po startu" if c["height_m"] < r["takeoff_max_height_m"] else f"stoupal{g}")
    if c["slant_km"] < r["close_slant_km"]:
        out.append(f"byl{g} od tebe jen {_km(c['slant_km'])}")
    if c["class"] == "widebody":
        out.append("je to velký dálkový typ")
    return out


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " a " + parts[-1]


def sentence(c: dict, now: float, live: bool, route: dict | None = None, cfg: dict = CFG) -> str:
    """One natural Czech sentence (plus a 'why' sentence) about a candidate."""
    heli = c["class"] == "rotorcraft"
    name = c["type_name"] or ("vrtulník" if heli else f"letadlo typu {c['t']}" if c["t"] else "letadlo")
    verb = "přeletělo" if name.startswith("letadlo") else "přeletěla" if name.startswith("Cessna") else "přeletěl"
    if live and now - c["cpa_ts"] < cfg["just_now_s"]:
        when, verb = "právě teď", "letí"     # closest point is (about) now: still passing or approaching
    else:
        when = ago(now - c["cpa_ts"]) if live else at_clock(c["cpa_ts"], now)
    who = name
    if not c["private"]:
        op = operator(c)
        if op:
            who += f" {op}"
        extra = [x for x in (c["flight"], route_text(route)) if x]
        if extra:
            who += f" ({', '.join(extra)})"
    where = "nad tebou" if c["distance_km"] < cfg["overhead_km"] else "kolem tebe"
    text = f"{when[0].upper()}{when[1:]} {where} {verb} {who}, výška {_alt(c['alt_m'])}"
    if where == "kolem tebe":
        text += f", nejblíž {_km(c['distance_km'])}"
    text += "."

    r = cfg["reasons"]
    why = reasons(c, cfg)
    subj, g, adj = ("Vrtulník", "", "ý") if heli else ("Letadlo", "o", "é")
    if c["db"] >= r["loud_db"] and why:
        text += f" {subj} {_join(why)}, proto byl{g} tak hlasit{adj}."
    elif why:
        text += f" {subj} {_join(why)}."
    if c["db"] < r["quiet_db"]:
        text += (f" Podle odhadu ale u tebe moc hlasit{adj} nebyl{g} (asi {_num(c['db'])} dB),"
                 " možná šlo o jiný zdroj zvuku nebo o letadlo bez odpovídače ADS-B.")
    return text


# ---------- endpoint ----------

def parse_at(at: str | None, now: float) -> float:
    if not at:
        return now
    try:
        dt = datetime.fromisoformat(at.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "Neplatný čas. Použij formát ISO, např. 2026-11-08T02:14.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PRAGUE)
    return dt.timestamp()


def make_router(poller) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/what-was-that")
    async def what_was_that(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                            at: str | None = Query(None, description="ISO time; omitted = now"),
                            window_s: int | None = Query(None, ge=10, le=CFG["max_window_s"])):
        now = time.time()
        at_ts = parse_at(at, now)
        live = at is None or now - at_ts < 30
        if at_ts > now + 60:
            raise HTTPException(422, "Tenhle čas ještě nenastal.")
        if live:
            start, end = now - (window_s or CFG["default_window_s"]), now
        else:
            w = window_s or CFG["past_window_s"]
            start, end = at_ts - w, min(at_ts + w, now)
        base = {"now": now, "at_ts": at_ts, "live": live, "from_ts": start, "to_ts": end,
                "lat": lat, "lon": lon, "note": noise.NOTE, "sentence": None, "candidates": []}

        retention = CONFIG["history"]["retention_hours"] * 3600
        if end < now - retention:
            return {**base, "status": "too_old",
                    "message": f"Polohy letadel uchovávám jen {CONFIG['history']['retention_hours']} hodin, na tenhle čas už nemám data."}

        pad = CFG["max_gap_s"]
        dlat = (CFG["max_distance_km"] + 30) / KM_PER_DEG
        dlon = dlat / max(0.1, math.cos(math.radians(lat)))
        rows = poller.db.execute(
            "SELECT ts, hex, flight, t, lat, lon, alt, track, gs, category, db_flags FROM positions"
            " WHERE ts >= ? AND ts <= ? AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
            (int(start - pad), int(end + pad) + 1, lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()
        live_tracks = {hx: [s for s in tr if start - pad <= s["ts"] <= end + pad]
                       for hx, tr in poller.history.items()}
        live_tracks = {hx: tr for hx, tr in live_tracks.items() if tr}
        has_data = bool(live_tracks) or poller.db.execute(
            "SELECT 1 FROM positions WHERE ts >= ? AND ts <= ? LIMIT 1", (int(start), int(end) + 1)).fetchone() is not None
        if not has_data:
            return {**base, "status": "no_data",
                    "message": "Pro tenhle čas nemám žádná data o letadlech (aplikace tehdy nejspíš neběžela)."}

        cands = find_passes(merge_tracks(live_tracks, rows), lat, lon, start, end)[:CFG["top_n"]]
        # Registration for aircraft still in the live data (stored positions don't keep it).
        regs = {a["hex"]: a.get("r") for a in (poller.latest or {}).get("ac", [])}
        for c in cands:
            if not c["private"] and not c["r"]:
                c["r"] = regs.get(c["hex"])
            c["live"] = c["hex"] in regs
            c["ago_s"] = round(now - c["cpa_ts"])
            c["operator"] = None if c["private"] else operator(c)
            c["reasons"] = reasons(c)
            c["route"] = None
        # Routes are cached but rate limited (one upstream call per ~10 s): don't let the answer wait on them.
        async def add_route(c):
            try:
                c["route"] = await asyncio.wait_for(enrich.route(c["flight"], c["lat"], c["lon"]), CFG["route_timeout_s"])
            except (enrich.Unavailable, asyncio.TimeoutError):
                pass
        await asyncio.gather(*(add_route(c) for c in cands[:CFG["route_top_n"]] if c["flight"] and not c["private"]))
        for c in cands:
            c["route_text"] = route_text(c["route"])
        if not cands:
            return {**base, "status": "empty",
                    "message": f"V tu dobu nad tebou do {CFG['max_distance_km']} km nic s odpovídačem ADS-B neletělo."}
        return {**base, "status": "ok", "message": None,
                "sentence": sentence(cands[0], now, live, cands[0]["route"]), "candidates": cands}

    return router
