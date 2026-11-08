"""Czech layperson explanations of detected events via the Claude API."""

import json
import logging
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

from config import CONFIG

log = logging.getLogger("explain")

PRAGUE = ZoneInfo("Europe/Prague")

EVENT_LABELS = {
    "emergency": "nouzový kód (squawk) nebo hlášená nouze",
    "holding": "holding (letadlo krouží na místě)",
    "go_around": "pravděpodobné nepovedené přistání (go-around) u letiště Praha",
    "interesting": "zajímavé letadlo (vzácný typ nebo vojenské)",
    "watched": "sledované letadlo: soukromý tryskáč, který veřejné zdroje spojují se známou osobností (kdo je na palubě, z dat nepoznáme)",
}

SYSTEM_PROMPT = """Jsi stručný a poctivý komentátor letového provozu nad Českem. Dostaneš událost, kterou automaticky zachytil detektor z dat ADS-B, souhrn trati letadla a aktuální počasí (METAR) z letiště Praha.

Napiš 1 až 3 věty česky pro laika: co se děje a proč to může být zajímavé. Bez odborného žargonu, bez nadpisů a odrážek.

Pravidla poctivosti:
- Nevymýšlej příčiny. Opírej se jen o předaná data.
- Když z dat není příčina jasná, napiš doslova „důvod z dat nepoznáme“.
- Možné příčiny formuluj jako pravděpodobné („nejspíš“, „může jít o“), nikdy jako jistotu.
- Počasí zmiň jen tehdy, když opravdu může souviset (mlha, nízká oblačnost, silný vítr).
- Detektor se může mýlit. Nouzový kód 7500 (únos) bývá často chyba nebo test, proto ho nikdy nepodávej jako potvrzený únos.

Jednotky: výšky vždy v metrech, rychlosti v km/h, stoupání a klesání v m/s, vzdálenosti v km. Data jsou ve stopách (ft), uzlech (kt) a ft/min, převeď je (1 ft = 0,3048 m, 1 kt = 1,852 km/h, 1000 ft/min ≈ 5 m/s) a zaokrouhli. Stopy, uzly ani míle nikdy neuváděj."""

_calls: deque[float] = deque()  # time.monotonic() of each API call in the last hour
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()  # ANTHROPIC_API_KEY from .env (loaded by config)
    return _client


def _take_slot() -> bool:
    """Reserve one call within the rolling-hour cap. False when the cap is reached."""
    now = time.monotonic()
    while _calls and now - _calls[0] >= 3600:
        _calls.popleft()
    if len(_calls) >= CONFIG["explain"]["max_calls_per_hour"]:
        return False
    _calls.append(now)
    return True


def summarize_track(history: list[dict]) -> list[dict]:
    """A few evenly spaced points from the last track_minutes of a readsb track (oldest first)."""
    cfg = CONFIG["explain"]
    if not history:
        return []
    last_ts = history[-1]["ts"]
    window = [s for s in history if s["ts"] >= last_ts - cfg["track_minutes"] * 60]
    n = cfg["track_points"]
    if len(window) > n:
        step = (len(window) - 1) / (n - 1)
        window = [window[round(i * step)] for i in range(n)]

    points = []
    for s in window:
        alt = s.get("alt_baro")
        points.append({
            "min_ago": round((last_ts - s["ts"]) / 60, 1),
            "lat": round(s["lat"], 3),
            "lon": round(s["lon"], 3),
            "alt_ft": "na zemi" if alt == "ground" else alt,
            "gs_kt": round(s["gs"]) if s.get("gs") is not None else None,
            "track_deg": round(s["track"]) if s.get("track") is not None else None,
            "vs_fpm": s.get("baro_rate"),
        })
    return points


def build_prompt(event: dict, track_summary: list[dict], metar: str | None) -> str:
    event_info = {
        "typ_udalosti": EVENT_LABELS.get(event["type"], event["type"]),
        "callsign": (event.get("callsign") or "").strip() or None,
        "typ_letadla": event.get("aircraft_type"),
        "poloha": {"lat": event.get("lat"), "lon": event.get("lon"), "alt_ft": event.get("alt_ft")},
        "zacatek": event.get("started_at"),
        "detaily_detektoru": event.get("data") or {},
    }
    now = datetime.now(PRAGUE).strftime("%Y-%m-%d %H:%M")
    return (
        f"Aktuální čas (Praha): {now}\n\n"
        f"Událost:\n{json.dumps(event_info, ensure_ascii=False, indent=1)}\n\n"
        "Trať za posledních minut (min_ago = před kolika minutami, vs_fpm = stoupání/klesání ft/min):\n"
        f"{json.dumps(track_summary, ensure_ascii=False)}\n\n"
        f"METAR: {metar or 'není k dispozici'}"
    )


async def explain(event: dict, track_summary: list[dict], metar: str | None) -> str | None:
    """Return a 1-3 sentence Czech explanation, or None (over the cap, API error, refusal)."""
    if not _take_slot():
        log.info("explanation cap reached, %s for %s stays unexplained", event["type"], event.get("hex"))
        return None

    cfg = CONFIG["explain"]
    try:
        response = await _get_client().messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            output_config={"effort": cfg["effort"]},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(event, track_summary, metar)}],
        )
    except anthropic.APIError as e:
        log.warning("Claude API error for %s: %s", event.get("hex"), e)
        return None

    if response.stop_reason != "end_turn":
        log.warning("no explanation for %s: stop_reason=%s", event.get("hex"), response.stop_reason)
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None
