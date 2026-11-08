"""Czech chat over the live data: Claude with tools over the latest snapshot and stored events."""

import json
import logging
import re
import time
from collections import Counter, deque
from datetime import datetime, timezone

import anthropic

from config import CONFIG
from detectors import watched
from detectors.geo import distance_nm
from explain import PRAGUE, _get_client, summarize_track

log = logging.getLogger("chat")


class ChatLimitError(Exception):
    """Hourly cap on chat questions reached."""


SYSTEM_PROMPT = """Jsi asistent aplikace skywatch-cz, která ukazuje živý letový provoz nad Českem z dat ADS-B (adsb.lol). Odpovídáš na otázky o aktuálním provozu a o událostech, které zachytily detektory (nouze, holding, go-around u Prahy, zajímavá letadla).

Pravidla:
- Odpovídej jen z výsledků nástrojů. Nic si nevymýšlej, žádná čísla ani letadla, která nástroje nevrátily.
- Když data na otázku neodpovídají, řekni to rovnou („to z dat nepoznám“).
- Data pokrývají kruh asi 160 NM kolem středu Česka, takže zahrnují i okolní státy. Když se uživatel ptá na „nad ČR“ / „nad Českem“, použij only_czechia=true (hranice je přibližná). Jinak řekni, jakou oblast počítáš.
- Místo podle názvu (např. Beroun, letiště Brno) převeď na souřadnice sám a hledej s rozumným poloměrem (u města asi 5–10 NM). Řekni, jaký poloměr jsi použil.
- Letecká společnost se pozná z prvních tří písmen volacího znaku (ICAO kód, např. RYR = Ryanair, CSA = Czech Airlines, SWR = Swiss). Když si přiřazením kódu nejsi jistý, přiznej to. Některé společnosti létají pod více kódy (Ryanair skupina např. i RYS, MAY, LDA), zmiň to, když je to podstatné.
- Vždy zmiň čas dat (data_time) z výsledku nástroje. Všechny časy v nástrojích jsou pražský místní čas.
- Odpovídej česky, stručně (1–4 věty, u výčtu krátký seznam). Výšky vždy v metrech, rychlosti v km/h, stoupání v m/s, vzdálenosti v km. Data z nástrojů jsou v ft, kt a NM, převeď je (1 ft = 0,3048 m, 1 kt = 1,852 km/h, 1 NM = 1,852 km) a zaokrouhli. Stopy, uzly ani míle uživateli neuváděj.
- Detektory se můžou mýlit; příčiny událostí nevymýšlej.
- U sledovaných letadel (tryskáče známých osobností) vždy řekni, že vlastnictví je z veřejných zdrojů a může být zastaralé, a netvrď, kdo je na palubě."""

AREA_PROPS = {
    "only_czechia": {"type": "boolean", "description": "Jen letadla nad územím ČR (přibližná hranice)."},
    "lat": {"type": "number", "description": "Střed oblasti, zeměpisná šířka."},
    "lon": {"type": "number", "description": "Střed oblasti, zeměpisná délka."},
    "radius_nm": {"type": "number", "description": "Poloměr oblasti v námořních mílích (s lat/lon)."},
}

TOOLS = [
    {
        "name": "search_aircraft",
        "description": "Najde letadla v posledním snapshotu podle filtrů. Vrací celkový počet a omezený seznam.",
        "input_schema": {
            "type": "object",
            "properties": {
                "callsign_prefix": {"type": "string", "description": "Začátek volacího znaku, např. 'RYR' (ICAO kód aerolinky) nebo 'CSA123'."},
                "type_prefix": {"type": "string", "description": "Začátek ICAO typu letadla, např. 'A320' nebo 'B73' (všechny Boeingy 737)."},
                "min_alt_ft": {"type": "number"},
                "max_alt_ft": {"type": "number"},
                "on_ground": {"type": "boolean", "description": "true = jen na zemi, false = jen ve vzduchu."},
                "military": {"type": "boolean", "description": "true = jen vojenská letadla."},
                **AREA_PROPS,
                "limit": {"type": "integer", "description": "Max. počet letadel v seznamu (výchozí 15)."},
            },
        },
    },
    {
        "name": "aircraft_detail",
        "description": "Detail jednoho letadla podle hex kódu nebo volacího znaku: poloha, výška, rychlost, souhrn trati a jeho nedávné události.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Hex (např. '4b1805') nebo volací znak (např. 'SWR1484')."}},
            "required": ["query"],
        },
    },
    {
        "name": "recent_events",
        "description": "Události zachycené detektory za posledních N minut.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["emergency", "holding", "go_around", "interesting", "watched"]},
                "minutes": {"type": "integer", "description": "Okno v minutách (výchozí 60)."},
            },
        },
    },
    {
        "name": "watched_aircraft",
        "description": "Sledovaná letadla (soukromé tryskáče veřejně známých osobností ze seznamu v aplikaci), která jsou teď v dosahu dat. Vrací i velikost seznamu.",
        "input_schema": {"type": "object", "properties": {"only_czechia": AREA_PROPS["only_czechia"]}},
    },
    {
        "name": "stats",
        "description": "Souhrn posledního snapshotu: počty letadel (celkem, ve vzduchu, na zemi, vojenská), nejčastější aerolinky a typy.",
        "input_schema": {"type": "object", "properties": AREA_PROPS},
    },
]

# Rough border of Czechia (lon, lat), good to a few km; enough for "over CZ" counts.
CZECHIA = [
    (12.09, 50.25), (12.50, 50.40), (12.94, 50.41), (13.25, 50.51), (13.79, 50.73), (14.25, 50.86),
    (14.32, 51.06), (14.85, 50.85), (15.03, 51.02), (15.38, 50.78), (15.95, 50.70), (16.45, 50.60),
    (16.20, 50.40), (16.55, 50.15), (16.85, 50.20), (17.00, 50.42), (17.43, 50.27), (17.70, 50.08),
    (17.90, 49.98), (18.30, 49.92), (18.57, 49.92), (18.63, 49.75), (18.86, 49.53), (18.40, 49.30),
    (18.00, 49.05), (17.65, 48.85), (17.13, 48.85), (16.94, 48.62), (16.64, 48.80), (16.05, 48.75),
    (15.35, 48.99), (14.97, 48.77), (14.70, 48.58), (14.33, 48.55), (13.84, 48.77), (13.23, 49.13),
    (12.95, 49.34), (12.55, 49.62), (12.40, 49.75), (12.50, 49.98), (12.20, 50.10),
]

AIRLINE_CALLSIGN = re.compile(r"^([A-Z]{3})\d")

_calls: deque[float] = deque()  # time.monotonic() of each chat question in the last hour


def _take_slot() -> bool:
    now = time.monotonic()
    while _calls and now - _calls[0] >= 3600:
        _calls.popleft()
    if len(_calls) >= CONFIG["chat"]["max_calls_per_hour"]:
        return False
    _calls.append(now)
    return True


# --- tools -----------------------------------------------------------------

def in_czechia(lat: float, lon: float) -> bool:
    inside = False
    j = len(CZECHIA) - 1
    for i, (xi, yi) in enumerate(CZECHIA):
        xj, yj = CZECHIA[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _callsign(a: dict) -> str:
    return (a.get("flight") or "").strip().upper()


def _airline(a: dict) -> str | None:
    m = AIRLINE_CALLSIGN.match(_callsign(a))
    return m.group(1) if m else None


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(PRAGUE).strftime("%Y-%m-%d %H:%M:%S")


def _data_time(poller) -> dict:
    ms = poller.latest["now"]
    return {"data_time": datetime.fromtimestamp(ms / 1000, PRAGUE).strftime("%Y-%m-%d %H:%M:%S")}


def _in_area(a: dict, args: dict) -> bool:
    if args.get("only_czechia") and not in_czechia(a["lat"], a["lon"]):
        return False
    if args.get("lat") is not None and args.get("lon") is not None:
        radius = args.get("radius_nm") or 10
        if distance_nm(args["lat"], args["lon"], a["lat"], a["lon"]) > radius:
            return False
    return True


def _brief(a: dict) -> dict:
    return {
        "hex": a["hex"],
        "callsign": _callsign(a) or None,
        "type": a.get("t"),
        "registration": a.get("r"),
        "alt_ft": "na zemi" if a.get("alt_baro") == "ground" else a.get("alt_baro"),
        "gs_kt": round(a["gs"]) if a.get("gs") is not None else None,
        "lat": round(a["lat"], 3),
        "lon": round(a["lon"], 3),
        "military": bool((a.get("dbFlags") or 0) & 1),
    }


def search_aircraft(poller, args: dict) -> dict:
    prefix = (args.get("callsign_prefix") or "").strip().upper()
    type_prefix = (args.get("type_prefix") or "").strip().upper()
    found = []
    for a in poller.latest["ac"]:
        alt = a.get("alt_baro")
        ground = alt == "ground"
        if prefix and not _callsign(a).startswith(prefix):
            continue
        if type_prefix and not (a.get("t") or "").upper().startswith(type_prefix):
            continue
        if args.get("on_ground") is not None and ground != args["on_ground"]:
            continue
        if args.get("min_alt_ft") is not None and (ground or alt is None or alt < args["min_alt_ft"]):
            continue
        if args.get("max_alt_ft") is not None and not ground and (alt is None or alt > args["max_alt_ft"]):
            continue
        if args.get("military") and not (a.get("dbFlags") or 0) & 1:
            continue
        if not _in_area(a, args):
            continue
        found.append(a)
    limit = args.get("limit") or CONFIG["chat"]["list_limit"]
    return {**_data_time(poller), "count": len(found), "aircraft": [_brief(a) for a in found[:limit]]}


def aircraft_detail(poller, args: dict) -> dict:
    q = (args.get("query") or "").strip().upper()
    a = next((a for a in poller.latest["ac"] if a["hex"].upper() == q or _callsign(a) == q), None)
    if a is None:
        return {**_data_time(poller), "error": f"Letadlo '{q}' v posledním snapshotu není."}
    rows = poller.db.execute(
        "SELECT type, started_at, data_json FROM events WHERE hex = ? ORDER BY started_at DESC LIMIT 5", (a["hex"],)
    ).fetchall()
    return {
        **_data_time(poller),
        **_brief(a),
        "track_deg": a.get("track"),
        "vs_fpm": a.get("baro_rate"),
        "squawk": a.get("squawk"),
        "airline_icao": _airline(a),
        "track_summary": summarize_track(list(poller.history.get(a["hex"], []))),
        "events": [{"type": r["type"], "started_at": _local(r["started_at"]), "data": json.loads(r["data_json"] or "{}")} for r in rows],
    }


def recent_events(poller, args: dict) -> dict:
    minutes = args.get("minutes") or 60
    cutoff = datetime.fromtimestamp(poller.latest["now"] / 1000 - minutes * 60, timezone.utc).isoformat(timespec="seconds")
    sql = "SELECT type, hex, callsign, aircraft_type, alt_ft, started_at, data_json, explanation FROM events WHERE started_at >= ?"
    params = [cutoff]
    if args.get("type"):
        sql += " AND type = ?"
        params.append(args["type"])
    rows = poller.db.execute(sql + " ORDER BY started_at DESC LIMIT 30", params).fetchall()
    events = []
    for r in rows:
        e = dict(r)
        e["callsign"] = (e["callsign"] or "").strip() or None
        e["started_at"] = _local(e["started_at"])
        e["data"] = json.loads(e.pop("data_json") or "{}")
        events.append(e)
    return {**_data_time(poller), "minutes": minutes, "count": len(events), "events": events}


def stats(poller, args: dict) -> dict:
    ac = [a for a in poller.latest["ac"] if _in_area(a, args)]
    n = CONFIG["chat"]["top_n"]
    ground = sum(1 for a in ac if a.get("alt_baro") == "ground")
    return {
        **_data_time(poller),
        "total": len(ac),
        "airborne": len(ac) - ground,
        "on_ground": ground,
        "military": sum(1 for a in ac if (a.get("dbFlags") or 0) & 1),
        "top_airlines_icao": Counter(x for a in ac if (x := _airline(a))).most_common(n),
        "top_types": Counter(a["t"] for a in ac if a.get("t")).most_common(n),
    }


def watched_aircraft(poller, args: dict) -> dict:
    """Watchlist entries in range. LADD/PIA aircraft never match (see detectors/watched.py)."""
    wl, cfg = poller.ctx["watchlist"], poller.ctx["cfg"]["watched"]
    found = []
    for a in poller.latest["ac"]:
        entry = watched.match(a, wl, cfg)
        if entry is None or not _in_area(a, args):
            continue
        found.append({**_brief(a), "label": entry["label"], "category": entry["category"],
                      "note": entry.get("note"), "source": entry["source"], "checked": entry["checked"]})
    return {
        **_data_time(poller),
        "watchlist_size": len(wl["entries"]),
        "count": len(found),
        "aircraft": found,
        "caveat": "Vlastnictví je z veřejných zdrojů a může být zastaralé; kdo je na palubě, z dat nepoznáme.",
    }


TOOL_FUNCS = {f.__name__: f for f in (search_aircraft, aircraft_detail, recent_events, watched_aircraft, stats)}


def run_tool(poller, name: str, args: dict) -> dict:
    if poller.latest is None:
        return {"error": "Zatím nejsou k dispozici žádná data (poller ještě nic nestáhl)."}
    return TOOL_FUNCS[name](poller, args)


# --- loop ------------------------------------------------------------------

async def chat(messages: list[dict], poller) -> str:
    """Answer the last user message. Raises ChatLimitError over the hourly cap."""
    cfg = CONFIG["chat"]
    if not _take_slot():
        raise ChatLimitError

    history = [{"role": m["role"], "content": m["content"]} for m in messages][-cfg["max_history_messages"]:]
    while history and history[0]["role"] != "user":
        history.pop(0)

    for _ in range(cfg["max_tool_iterations"]):
        try:
            response = await _get_client().messages.create(
                model=cfg["model"],
                max_tokens=cfg["max_tokens"],
                output_config={"effort": cfg["effort"]},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=history,
            )
        except anthropic.APIError as e:
            log.warning("Claude API error in chat: %s", e)
            return "Omlouvám se, spojení s AI teď nefunguje. Zkus to prosím za chvíli."

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "end_turn" and text:
                return text
            log.warning("chat ended without answer: stop_reason=%s", response.stop_reason)
            return "Na tohle ti neumím odpovědět."

        history.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result, is_error = run_tool(poller, block.name, block.input), False
            except Exception as e:  # a bad tool input must not kill the whole answer
                log.exception("chat tool %s failed", block.name)
                result, is_error = {"error": str(e)}, True
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
                "is_error": is_error,
            })
        history.append({"role": "user", "content": results})

    log.warning("chat hit max_tool_iterations")
    return "Odpověď vyžadovala příliš mnoho kroků, zkus otázku zjednodušit."
