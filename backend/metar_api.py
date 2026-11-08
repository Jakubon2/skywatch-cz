"""Current METAR for the airport decoded into plain Czech (GET /api/metar).

Source: aviationweather.gov JSON (same as metar.py). `decode` is a pure function over one
observation; visibility and weather codes are read from the raw METAR because the JSON gives
visibility in statute miles.
"""

import logging
import re
import time

import httpx
from fastapi import APIRouter, HTTPException

from config import CONFIG
from metar import URL

log = logging.getLogger("metar_api")
router = APIRouter(prefix="/api")
_cache = {"data": None, "fetched": None}

KT_TO_MS = 0.514444
FT_TO_M = 0.3048

# Wind direction "from the ..." (genitive), 8 sectors starting north.
DIRS_FROM = ["severu", "severovýchodu", "východu", "jihovýchodu", "jihu", "jihozápadu", "západu", "severozápadu"]
COVER = {"FEW": "ojedinělá oblačnost", "SCT": "polojasno", "BKN": "oblačno", "OVC": "zataženo",
         "VV": "obloha není vidět"}
CLOUD_TYPE = {"CB": "bouřkové mraky", "TCU": "kupovité mraky"}
DESCRIPTOR = {"MI": "přízemní", "BC": "chuchvalce", "PR": "částečná", "DR": "nízko zvířený",
              "BL": "zvířený", "SH": "přeháňky", "TS": "bouřka", "FZ": "mrznoucí"}
PHENOMENON = {"DZ": "mrholení", "RA": "déšť", "SN": "sníh", "SG": "sněhová zrna", "IC": "ledové jehličky",
              "PL": "zmrzlý déšť", "GR": "kroupy", "GS": "krupky", "UP": "neurčené srážky",
              "BR": "kouřmo", "FG": "mlha", "FU": "kouř", "VA": "sopečný popel", "DU": "prach",
              "SA": "písek", "HZ": "zákal", "PO": "prachové víry", "SQ": "húlava", "FC": "tromba",
              "SS": "písečná bouře", "DS": "prachová bouře"}
WX_RE = re.compile(r"^(?P<int>[-+]|VC)?(?P<desc>MI|BC|PR|DR|BL|SH|TS|FZ)?(?P<ph>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PO|SQ|FC|SS|DS)*)$")


def wind_strength(ms: float) -> str:
    if ms < 0.5:
        return "Bezvětří"
    if ms < 3.4:
        return "Slabý vítr"
    if ms < 8:
        return "Mírný vítr"
    if ms < 13.9:
        return "Silný vítr"
    return "Velmi silný vítr"


def decode_wind(wdir, wspd, wgst) -> dict | None:
    if wspd is None:
        return None
    ms = wspd * KT_TO_MS
    variable = not isinstance(wdir, (int, float))
    text = wind_strength(ms)
    if ms >= 0.5:
        where = "proměnlivého směru" if variable else f"od {DIRS_FROM[round(wdir / 45) % 8]}"
        text += f" {where}, {ms:.0f} m/s ({ms * 3.6:.0f} km/h)"
        if wgst:
            text += f", v nárazech {wgst * KT_TO_MS:.0f} m/s"
    return {"dir_deg": None if variable else wdir, "variable": variable, "speed_kt": wspd,
            "gust_kt": wgst, "speed_ms": round(ms, 1), "text": text}


def decode_visibility(raw: str) -> dict | None:
    tokens = raw.split()
    if "CAVOK" in tokens:
        return {"m": 10000, "text": "10 km a víc, bez nízké oblačnosti (CAVOK)"}
    for t in tokens[3:]:  # skip "METAR LKPR 081700Z"
        if re.fullmatch(r"\d{4}", t):
            m = int(t)
            if m >= 9999:
                return {"m": 10000, "text": "10 km a víc"}
            km = f"{m / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") if m < 5000 else str(m // 1000)
            return {"m": m, "text": f"{km} km"}
    return None


def decode_clouds(raw: str, clouds: list | None) -> tuple[list[dict], str]:
    tokens = raw.split()
    if any(t in tokens for t in ("CAVOK", "NSC", "SKC", "CLR", "NCD")):
        return [], "Bez oblačnosti v nízkých výškách"
    layers = []
    for c in clouds or []:
        cover, base = c.get("cover"), c.get("base")
        if cover not in COVER:
            continue
        base_m = round(base * FT_TO_M / 10) * 10 if base is not None else None
        ctype = next((CLOUD_TYPE[k] for k in CLOUD_TYPE
                      if base is not None and f"{cover}{base // 100:03d}{k}" in tokens), None)
        text = COVER[cover] + (f" ve {base_m} m" if base_m is not None else "")
        if ctype:
            text += f" ({ctype})"
        layers.append({"cover": cover, "base_m": base_m, "type": ctype, "text": text})
    if not layers:
        return [], "Oblačnost nehlášena"
    text = "; ".join(l["text"] for l in layers)
    return layers, text[0].upper() + text[1:]


def decode_weather(wx: str | None) -> list[str]:
    out = []
    for token in (wx or "").split():
        m = WX_RE.match(token)
        if not m or not (m["desc"] or m["ph"]):
            continue
        phs = [PHENOMENON[m["ph"][i:i + 2]] for i in range(0, len(m["ph"]), 2)]
        parts = []
        if m["desc"] in ("SH", "TS"):
            parts.append(DESCRIPTOR[m["desc"]] + (": " + ", ".join(phs) if phs else ""))
        else:
            parts.append(" ".join(([DESCRIPTOR[m["desc"]]] if m["desc"] else []) + [", ".join(phs)]).strip())
        text = parts[0]
        text = text[0].upper() + text[1:]
        if m["int"] == "-":
            text += " (slabá intenzita)"
        elif m["int"] == "+":
            text += " (silná intenzita)"
        elif m["int"] == "VC":
            text += " v okolí"
        out.append(text)
    return out


def humidity(t: float | None, td: float | None) -> int | None:
    if t is None or td is None:
        return None
    # Magnus formula
    def e(x):
        return 6.112 * 2.718281828 ** (17.62 * x / (243.12 + x))
    return round(100 * e(td) / e(t))


def decode(obs: dict) -> dict:
    raw = (obs.get("rawOb") or "").strip()
    clouds, clouds_text = decode_clouds(raw, obs.get("clouds"))
    weather = decode_weather(obs.get("wxString"))
    temp = obs.get("temp")
    summary = ", ".join(x for x in [f"{temp:.0f} °C" if temp is not None else None,
                                     weather[0].lower() if weather else clouds_text.split(";")[0].lower()] if x)
    return {
        "station": obs.get("icaoId"),
        "name": "Letiště Praha-Ruzyně" if obs.get("icaoId") == "LKPR" else obs.get("name"),
        "observed": obs.get("obsTime") * 1000 if obs.get("obsTime") else None,  # ms since epoch
        "raw": raw,
        "flight_category": obs.get("fltCat"),
        "summary": summary[:1].upper() + summary[1:],
        "temp_c": temp,
        "dewpoint_c": obs.get("dewp"),
        "humidity": humidity(temp, obs.get("dewp")),
        "pressure_hpa": obs.get("altim"),
        "wind": decode_wind(obs.get("wdir"), obs.get("wspd"), obs.get("wgst")),
        "visibility": decode_visibility(raw),
        "clouds": clouds,
        "clouds_text": clouds_text,
        "weather": weather,
    }


@router.get("/metar")
async def metar():
    cfg = CONFIG["explain"]
    fetched = _cache["fetched"]
    if fetched is not None and time.monotonic() - fetched < cfg["metar_refresh_minutes"] * 60:
        return _cache["data"]
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "skywatch-cz/0.1"}) as http:
            r = await http.get(URL, params={"ids": cfg["metar_station"], "format": "json"})
            r.raise_for_status()
            data = r.json()
        if not data:
            raise ValueError("empty METAR response")
        _cache["data"] = decode(data[0])
        _cache["fetched"] = time.monotonic()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("METAR fetch failed: %s", e)
        _cache["fetched"] = time.monotonic()  # don't hammer the source; serve the stale value meanwhile
        if _cache["data"] is None:
            raise HTTPException(502, "Počasí z letiště se nepodařilo načíst.")
    return _cache["data"]
