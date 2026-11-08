"""Daily Czech AI summary of the day's traffic and events, sent to ntfy at a configured time."""

import asyncio
import json
import logging
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import anthropic

import history
import notify
from config import CONFIG
from explain import EVENT_LABELS, PRAGUE, _get_client

log = logging.getLogger("summary")

SYSTEM_PROMPT = """Jsi stručný a poctivý komentátor letového provozu nad Českem. Dostaneš souhrnná čísla za dnešní den z aplikace, která sleduje data ADS-B (adsb.lol) v kruhu asi 160 NM kolem středu Česka, a seznam událostí, které zachytily automatické detektory.

Napiš 2 až 4 věty česky pro laika: jaký byl dnešní provoz a co bylo zajímavé. Bez nadpisů, odrážek a Markdownu.

Pravidla poctivosti:
- Používej jen předaná čísla a události. Nic si nevymýšlej, žádná letadla, lety ani čísla navíc.
- Počty nepočítej sám ze seznamu událostí, přebírej je přesně z polí pocty_udalosti a udalosti_podle_typu_letadla.
- Nevymýšlej příčiny událostí. Když příčina není v datech, napiš, že ji z dat nepoznáme.
- Detektory se můžou mýlit, události podávej jako zachycené, ne jako potvrzené. Nouzový kód 7500 nikdy nepodávej jako potvrzený únos.
- Když bylo málo dat (aplikace běžela jen část dne), řekni to.
- Když nebyly žádné události, řekni to jednoduše a nic nepřikrášluj."""

_calls: deque[float] = deque()      # time.monotonic() of each Claude call in the last 24 h
_cache: dict = {}                   # {"day": "YYYY-MM-DD", "at": monotonic, "result": {...}}


def _take_slot() -> bool:
    now = time.monotonic()
    while _calls and now - _calls[0] >= 86400:
        _calls.popleft()
    if len(_calls) >= CONFIG["daily_summary"]["max_calls_per_day"]:
        return False
    _calls.append(now)
    return True


def _hhmm(ts: float) -> str:
    return datetime.fromtimestamp(ts, PRAGUE).strftime("%H:%M")


def day_start(now: datetime) -> datetime:
    return now.astimezone(PRAGUE).replace(hour=0, minute=0, second=0, microsecond=0)


def build_facts(conn, now: datetime) -> dict:
    """Compact facts for the prompt: today's stats (Prague day so far) and detected events."""
    start, end = int(day_start(now).timestamp()), int(now.timestamp())
    s = history.stats(conn, start, end, top_n=3)
    peak = max(s["traffic"], key=lambda b: b["aircraft"], default=None)
    covered_min = len(s["traffic"]) * s["bucket_s"] // 60

    rows = conn.execute(
        "SELECT type, callsign, aircraft_type, started_at, explanation FROM events"
        " WHERE started_at >= ? ORDER BY started_at", (_utc_iso(start),),
    ).fetchall()
    events = [{
        "typ": EVENT_LABELS.get(r[0], r[0]),
        "callsign": (r[1] or "").strip() or None,
        "typ_letadla": r[2],
        "cas": datetime.fromisoformat(r[3]).astimezone(PRAGUE).strftime("%H:%M"),
        "vysvetleni": r[4],
    } for r in rows[-CONFIG["daily_summary"]["max_events"]:]]

    return {
        "datum": now.astimezone(PRAGUE).strftime("%Y-%m-%d"),
        "cas_souhrnu": now.astimezone(PRAGUE).strftime("%H:%M"),
        "pokryti_dat_minut": covered_min,
        "unikatnich_letadel": s["unique_aircraft"],
        "spicka": {"cas": _hhmm(peak["t"]), "letadel_za_10_min": peak["aircraft"]} if peak else None,
        "top_aerolinky": [{"kod": a["code"], "nazev": a["name"], "letu": a["flights"]} for a in s["top_airlines"]],
        "top_typy": s["top_types"],
        "nejvzacnejsi_typy": [{"typ": r["type"], "letadel": r["aircraft"]} for r in s["rarest_types"]],
        "pocty_udalosti": {EVENT_LABELS.get(k, k): v for k, v in s["events"].items()},
        "udalosti_celkem": len(rows),
        "udalosti_podle_typu_letadla": dict(Counter(r[2] or "neznámý" for r in rows).most_common()),
        "udalosti": events,
    }


def _utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


async def generate(conn, now: datetime | None = None, use_cache: bool = True) -> dict:
    """{"day", "generated_at", "text" (None when unavailable), "facts"}. Cached per day for cache_minutes."""
    cfg = CONFIG["daily_summary"]
    now = now or datetime.now(PRAGUE)
    day = now.astimezone(PRAGUE).strftime("%Y-%m-%d")
    if use_cache and _cache.get("day") == day and time.monotonic() - _cache["at"] < cfg["cache_minutes"] * 60:
        return _cache["result"]

    facts = build_facts(conn, now)
    text = await _ask_claude(facts)
    result = {"day": day, "generated_at": now.astimezone(PRAGUE).isoformat(timespec="seconds"),
              "text": text, "facts": facts}
    if text:
        _cache.update(day=day, at=time.monotonic(), result=result)
    return result


async def _ask_claude(facts: dict) -> str | None:
    if not _take_slot():
        log.info("daily summary cap reached")
        return None
    cfg = CONFIG["daily_summary"]
    try:
        response = await _get_client().messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            output_config={"effort": cfg["effort"]},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Dnešní data:\n" + json.dumps(facts, ensure_ascii=False, indent=1)}],
        )
    except anthropic.APIError as e:
        log.warning("Claude API error for daily summary: %s", e)
        return None
    if response.stop_reason != "end_turn":
        log.warning("no daily summary: stop_reason=%s", response.stop_reason)
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None


def next_run(now: datetime) -> datetime:
    """Next occurrence of the configured local time (Europe/Prague), strictly after now."""
    h, m = map(int, CONFIG["daily_summary"]["at"].split(":"))
    local = now.astimezone(PRAGUE)
    run = local.replace(hour=h, minute=m, second=0, microsecond=0)
    if run <= local:
        # Re-resolve the wall-clock time on the next day so DST changes are handled.
        d = (local + timedelta(days=1)).date()
        run = datetime(d.year, d.month, d.day, h, m, tzinfo=PRAGUE)
    return run


async def run_daily(conn):
    """Background loop started from the API lifespan: summary to ntfy once a day."""
    while True:
        target = next_run(datetime.now(PRAGUE))
        log.info("daily summary scheduled for %s", target.isoformat(timespec="minutes"))
        await asyncio.sleep(max(0.0, (target - datetime.now(PRAGUE)).total_seconds()))
        try:
            result = await generate(conn, use_cache=False)
            if result["text"]:
                await notify.send_ntfy(f"Dnešní provoz nad Českem ({target:%-d. %-m.})", result["text"],
                                       tags=["airplane"])
        except Exception:
            log.exception("daily summary failed")
        await asyncio.sleep(60)   # never fire twice for the same minute
