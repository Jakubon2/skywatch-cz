"""Contrail forecast from upper-air temperature and humidity (GET /api/contrails).

Data: Open-Meteo forecast API (free, no key), hourly `temperature_{p}hPa`,
`relative_humidity_{p}hPa` on pressure levels plus `cloud_cover`. https://open-meteo.com/en/docs

Formation: Schmidt-Appleman criterion (Schumann 1996, Meteorol. Z. 5, 4-23). The exhaust plume
mixes with ambient air along a straight line in (T, e) space with slope

    G = EI_H2O · cp · p / (eps · Q · (1 - eta))        [Pa/K]

EI_H2O = 1.25 kg/kg, cp = 1004 J/(kg K), eps = 0.622, Q = 43.2 MJ/kg, eta = overall propulsion
efficiency. eta = 0.35 is assumed for a typical modern turbofan (Schumann 2000: 0.3 for older
engines, ~0.4 for the newest; higher eta = contrails at warmer temperatures). A contrail forms
when the mixing line crosses liquid-water saturation. The threshold for saturated air is
(Schumann 1996, eq. 31, valid -60..-10 °C)

    T_LM = -46.46 + 9.43 ln(G - 0.053) + 0.72 ln²(G - 0.053)          [°C]

and for ambient humidity RH_w the critical temperature T_LC solves
RH_w · e_w(T_LC) = e_w(T_LM) - G · (T_LM - T_LC); contrails form when T <= T_LC.

Persistence: a contrail lives long (and spreads into cirrus) only in ice-supersaturated air,
RH_ice >= 100 %. RH_ice = RH_w · e_w(T) / e_i(T), saturation pressures after Sonntag (1990).

Assumptions and limits: Open-Meteo humidity is taken as relative to liquid water (WMO convention);
weather models smooth and usually underestimate upper-tropospheric supersaturation, so
"persistent" is uncertain. Visibility from the ground also depends on lower clouds.
"""

import asyncio
import logging
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Query

from config import CONFIG

CFG = CONFIG["contrails"]
PRAGUE = ZoneInfo("Europe/Prague")
USER_AGENT = "skywatch-cz/0.1 (personal app)"
CP, EPS = 1004.0, 0.622
NOTE = ("Předpověď z modelu počasí a zjednodušeného fyzikálního kritéria (Schmidt–Appleman). "
        "Vlhkost ve výškách modely často podceňují, takže hlavně odhad trvalých stop je nejistý.")

log = logging.getLogger("contrails")
router = APIRouter(prefix="/api")
_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_lock = asyncio.Lock()


# ---------- physics (pure) ----------

def e_sat_water(t_c: float) -> float:
    """Saturation vapour pressure over liquid water in Pa (Sonntag 1990)."""
    t = t_c + 273.15
    return 100 * math.exp(-6096.9385 / t + 16.635794 - 2.711193e-2 * t + 1.673952e-5 * t * t
                          + 2.433502 * math.log(t))


def e_sat_ice(t_c: float) -> float:
    """Saturation vapour pressure over ice in Pa (Sonntag 1990)."""
    t = t_c + 273.15
    return 100 * math.exp(-6024.5282 / t + 24.7219 + 1.0613868e-2 * t - 1.3198825e-5 * t * t
                          - 0.49382577 * math.log(t))


def mixing_slope(p_hpa: float, eta: float | None = None) -> float:
    """Slope G of the exhaust mixing line in Pa/K."""
    eta = CFG["propulsion_efficiency"] if eta is None else eta
    return CFG["ei_h2o"] * CP * p_hpa * 100 / (EPS * CFG["fuel_heat"] * (1 - eta))


def threshold_saturated(g: float) -> float:
    """T_LM in °C: max temperature for contrail formation in water-saturated air (Schumann 1996)."""
    x = math.log(g - 0.053)
    return -46.46 + 9.43 * x + 0.72 * x * x


def critical_temp(p_hpa: float, rh_water: float, eta: float | None = None) -> float:
    """T_LC in °C: contrails form at or below this temperature for the given RH over water (%)."""
    g = mixing_slope(p_hpa, eta)
    t_lm = threshold_saturated(g)
    u = min(max(rh_water, 0), 100) / 100
    e_lm = e_sat_water(t_lm)

    def f(t):  # >= 0 where the mixing line reaches saturation
        return u * e_sat_water(t) - e_lm + g * (t_lm - t)

    lo, hi = t_lm - 40, t_lm
    for _ in range(50):
        mid = (lo + hi) / 2
        if f(mid) >= 0:
            lo = mid
        else:
            hi = mid
    return lo


def rh_ice(t_c: float, rh_water: float) -> float:
    return rh_water * e_sat_water(t_c) / e_sat_ice(t_c)


def flight_level(p_hpa: float) -> int:
    """ISA pressure altitude rounded to 10 flight levels (300 hPa -> FL300, 250 -> FL340)."""
    h_m = 44330.8 * (1 - (p_hpa / 1013.25) ** 0.190263)
    return int(round(h_m / 0.3048 / 1000)) * 10


def assess_level(p_hpa: float, t_c: float, rh_w: float) -> dict:
    t_crit = critical_temp(p_hpa, rh_w)
    forms = t_c <= t_crit
    rhi = rh_ice(t_c, rh_w)
    return {
        "hpa": p_hpa, "fl": flight_level(p_hpa), "temp_c": t_c, "rh_water": rh_w,
        "rh_ice": round(rhi, 1), "t_crit_c": round(t_crit, 1),
        "forms": forms, "persistent": forms and rhi >= CFG["persistent_rhi"],
    }


# ---------- parsing and summary (pure) ----------

def parse(data: dict) -> list[dict]:
    """Open-Meteo JSON -> hourly list of {time, cloud_cover, state, levels}."""
    h = data["hourly"]
    hours = []
    for i, ts in enumerate(h["time"]):
        levels = []
        for p in CFG["levels_hpa"]:
            t = h.get(f"temperature_{p}hPa", [None] * (i + 1))[i]
            rh = h.get(f"relative_humidity_{p}hPa", [None] * (i + 1))[i]
            if t is not None and rh is not None:
                levels.append(assess_level(p, t, rh))
        if not levels:
            continue
        state = ("persistent" if any(x["persistent"] for x in levels)
                 else "short" if any(x["forms"] for x in levels) else "none")
        hours.append({"time": ts, "cloud_cover": (h.get("cloud_cover") or [None] * (i + 1))[i],
                      "state": state, "levels": levels})
    return hours


def _period(ts: str, today) -> str:
    dt = datetime.fromisoformat(ts)
    part = ("v noci" if dt.hour < 6 else "dopoledne" if dt.hour < 12
            else "odpoledne" if dt.hour < 18 else "večer")
    days = (dt.date() - today).days
    if part == "v noci" and days in (0, 1):
        return "v noci"
    return f"{'dnes' if days == 0 else 'zítra' if days == 1 else dt.strftime('%-d. %-m.')} {part}"


def _join(parts: list[str]) -> str:
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " a " + parts[-1]
    return text[0].upper() + text[1:]


def summary_cs(hours: list[dict], now: datetime) -> str:
    if not hours:
        return "Předpověď výškového počasí teď není k dispozici."
    today = now.date()
    for state, tail in (("persistent", "budou za letadly dlouhé čáry na obloze, které vydrží."),
                        ("short", "se za letadly budou tvořit jen krátké čárky, které rychle zmizí.")):
        sel = [h for h in hours if h["state"] == state]
        if sel:
            periods = list(dict.fromkeys(_period(h["time"], today) for h in sel))
            text = f"{_join(periods)} {tail}"
            covers = [h["cloud_cover"] for h in sel if h["cloud_cover"] is not None]
            if covers and sum(covers) / len(covers) >= CFG["overcast_cover"]:
                text += " Bude ale zataženo, takže je nejspíš neuvidíš."
            return text
    return "V nejbližších hodinách se kondenzační stopy tvořit nebudou, ve výškách je na ně moc teplo nebo sucho."


def build(data: dict, now: datetime) -> dict:
    hours = parse(data)
    return {
        "estimate": True,
        "note": NOTE,
        "source": "Open-Meteo",
        "assumptions": {"criterion": "Schmidt–Appleman (Schumann 1996)",
                        "propulsion_efficiency": CFG["propulsion_efficiency"],
                        "persistent_rhi": CFG["persistent_rhi"],
                        "rh_reference": "voda"},
        "summary": summary_cs(hours, now),
        "now": hours[0] if hours else None,
        "hours": hours,
    }


# ---------- HTTP ----------

async def fetch(lat: float, lon: float, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    hourly = ["cloud_cover"] + [f"{v}_{p}hPa" for p in CFG["levels_hpa"]
                                for v in ("temperature", "relative_humidity")]
    async with httpx.AsyncClient(timeout=CFG["timeout_s"], transport=transport,
                                 headers={"User-Agent": USER_AGENT}) as http:
        r = await http.get(CFG["url"], params={
            "latitude": lat, "longitude": lon, "hourly": ",".join(hourly),
            "forecast_hours": CFG["horizon_hours"], "timezone": "Europe/Prague",
        })
        r.raise_for_status()
        return r.json()


async def forecast(lat: float, lon: float, transport=None) -> dict:
    step = CFG["round_deg"]
    key = (round(round(lat / step) * step, 4), round(round(lon / step) * step, 4))
    ttl = CFG["cache_minutes"] * 60
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    async with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        data = await fetch(*key, transport=transport)
        res = {"lat": key[0], "lon": key[1], **build(data, datetime.now(PRAGUE))}
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (time.monotonic(), res)
        return res


@router.get("/contrails")
async def contrails(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180)):
    try:
        return await forecast(lat, lon)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("Open-Meteo failed: %s", e)
        raise HTTPException(502, "Předpověď výškového počasí se nepodařilo načíst.")
