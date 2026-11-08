"""Daily and weekly Czech AI summaries of traffic and events, sent via notify (ntfy + Web Push) at configured times."""

import asyncio
import json
import logging
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import anthropic

import history
import notify
import passes
from config import CONFIG
from explain import EVENT_LABELS, PRAGUE, _get_client

log = logging.getLogger("summary")

SYSTEM_PROMPT = """Jsi stručný a poctivý komentátor letového provozu nad Českem. Dostaneš souhrnná čísla za dnešní den z aplikace, která sleduje data ADS-B (adsb.lol) v kruhu asi 300 km kolem středu Česka, a seznam událostí, které zachytily automatické detektory.

Napiš 2 až 4 věty česky pro laika: jaký byl dnešní provoz a co bylo zajímavé. Bez nadpisů, odrážek a Markdownu.

Pravidla poctivosti:
- Používej jen předaná čísla a události. Nic si nevymýšlej, žádná letadla, lety ani čísla navíc.
- Počty nepočítej sám ze seznamu událostí, přebírej je přesně z polí pocty_udalosti a udalosti_podle_typu_letadla.
- Nevymýšlej příčiny událostí. Když příčina není v datech, napiš, že ji z dat nepoznáme.
- Detektory se můžou mýlit, události podávej jako zachycené, ne jako potvrzené. Nouzový kód 7500 nikdy nepodávej jako potvrzený únos.
- Když bylo málo dat (aplikace běžela jen část dne), řekni to.
- Když nebyly žádné události, řekni to jednoduše a nic nepřikrášluj.

Jednotky: výšky vždy v metrech, rychlosti v km/h, stoupání a klesání v m/s, vzdálenosti v km. Data jsou ve stopách (ft), uzlech (kt) a ft/min, převeď je (1 ft = 0,3048 m, 1 kt = 1,852 km/h, 1000 ft/min ≈ 5 m/s) a zaokrouhli. Stopy, uzly ani míle nikdy neuváděj."""

# Same rules for the week; the facts come from the compact pass table (per-day flights) and the event log.
WEEK_PROMPT = (SYSTEM_PROMPT
               .replace("za dnešní den", "za posledních 7 dní")
               .replace("jaký byl dnešní provoz", "jaký byl provoz za uplynulý týden, který den byl nejrušnější")
               .replace("aplikace běžela jen část dne", "aplikace některé dny neběžela nebo běžela jen část dne, "
                        "viz hodin_zaznamu u jednotlivých dní"))

_calls: deque[float] = deque()      # time.monotonic() of each Claude call in the last 24 h
_cache: dict = {}                   # kind -> {"day": "YYYY-MM-DD", "at": monotonic, "result": {...}}


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


def build_week_facts(conn, now: datetime) -> dict:
    """Facts for the last 7 Prague days including today: flights per day, top airlines/types, events."""
    last = now.astimezone(PRAGUE).date()
    first = last - timedelta(days=6)
    w = passes.week_stats(conn, first, last, top_n=5)
    start = _utc_iso(int(datetime(first.year, first.month, first.day, tzinfo=PRAGUE).timestamp()))
    counts = conn.execute(
        "SELECT type, COUNT(*) FROM events WHERE started_at >= ? GROUP BY type ORDER BY COUNT(*) DESC", (start,),
    ).fetchall()
    rows = conn.execute(
        "SELECT type, callsign, aircraft_type, started_at FROM events WHERE started_at >= ? ORDER BY started_at",
        (start,),
    ).fetchall()
    events = [{
        "typ": EVENT_LABELS.get(r[0], r[0]),
        "callsign": (r[1] or "").strip() or None,
        "typ_letadla": r[2],
        "kdy": datetime.fromisoformat(r[3]).astimezone(PRAGUE).strftime("%-d. %-m. %H:%M"),
    } for r in rows[-CONFIG["daily_summary"]["max_events"]:]]
    busiest = max(w["days"], key=lambda d: d["flights"], default=None)
    return {
        "obdobi": {"od": first.isoformat(), "do": last.isoformat()},
        "cas_souhrnu": now.astimezone(PRAGUE).strftime("%Y-%m-%d %H:%M"),
        "dny": [{"datum": d["date"], "letu": d["flights"], "hodin_zaznamu": d["hours_recorded"]} for d in w["days"]],
        "letu_celkem": w["flights"],
        "nejrusnejsi_den": {"datum": busiest["date"], "letu": busiest["flights"]}
                           if busiest and busiest["flights"] else None,
        "top_aerolinky": [{"kod": c, "nazev": history.AIRLINES.get(c), "letu": n} for c, n in w["top_airlines"]],
        "top_typy": [{"typ": t, "letu": n} for t, n in w["top_types"]],
        "nejvzacnejsi_typy": [{"typ": t, "letu": n} for t, n in w["rare_types"]],
        "pocty_udalosti": {EVENT_LABELS.get(k, k): v for k, v in counts},
        "udalosti_celkem": len(rows),
        "udalosti_podle_typu_letadla": dict(Counter(r[2] or "neznámý" for r in rows).most_common()),
        "udalosti": events,
        "poznamka": "Let = jeden volací znak za den v oblasti. Dny s malým počtem hodin záznamu mají neúplná data.",
    }


async def generate(conn, now: datetime | None = None, use_cache: bool = True, kind: str = "day") -> dict:
    """{"kind", "day", "generated_at", "text" (None when unavailable), "facts"}. Cached per kind and day."""
    cache_min = CONFIG["weekly_summary" if kind == "week" else "daily_summary"]["cache_minutes"]
    now = now or datetime.now(PRAGUE)
    day = now.astimezone(PRAGUE).strftime("%Y-%m-%d")
    hit = _cache.get(kind)
    if use_cache and hit and hit["day"] == day and time.monotonic() - hit["at"] < cache_min * 60:
        return hit["result"]

    facts = build_week_facts(conn, now) if kind == "week" else build_facts(conn, now)
    text = await _ask_claude(facts, kind)
    result = {"kind": kind, "day": day, "generated_at": now.astimezone(PRAGUE).isoformat(timespec="seconds"),
              "text": text, "facts": facts}
    if text:
        _cache[kind] = {"day": day, "at": time.monotonic(), "result": result}
    return result


async def _ask_claude(facts: dict, kind: str = "day") -> str | None:
    if not _take_slot():
        log.info("summary cap reached")
        return None
    cfg = CONFIG["daily_summary"]
    intro = "Data za posledních 7 dní:\n" if kind == "week" else "Dnešní data:\n"
    try:
        response = await _get_client().messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            output_config={"effort": cfg["effort"]},
            system=WEEK_PROMPT if kind == "week" else SYSTEM_PROMPT,
            messages=[{"role": "user", "content": intro + json.dumps(facts, ensure_ascii=False, indent=1)}],
        )
    except anthropic.APIError as e:
        log.warning("Claude API error for %s summary: %s", kind, e)
        return None
    if response.stop_reason != "end_turn":
        log.warning("no %s summary: stop_reason=%s", kind, response.stop_reason)
        return None
    return "".join(b.text for b in response.content if b.type == "text").strip() or None


def next_run(now: datetime, at: str | None = None, weekday: int | None = None) -> datetime:
    """Next occurrence of local time `at` (Europe/Prague), strictly after now; optionally only on `weekday`
    (0 = Monday ... 6 = Sunday)."""
    h, m = map(int, (at or CONFIG["daily_summary"]["at"]).split(":"))
    local = now.astimezone(PRAGUE)
    d = local.date()
    while True:
        # Resolve the wall-clock time per day so DST changes are handled.
        run = datetime(d.year, d.month, d.day, h, m, tzinfo=PRAGUE)
        if run > local and (weekday is None or d.weekday() == weekday):
            return run
        d += timedelta(days=1)


async def run_loop(conn, kind: str = "day"):
    """Background loop started from the API lifespan: summary via notify (ntfy + Web Push) on schedule."""
    cfg = CONFIG["weekly_summary" if kind == "week" else "daily_summary"]
    weekday = cfg["weekday"] if kind == "week" else None
    while True:
        target = next_run(datetime.now(PRAGUE), cfg["at"], weekday)
        log.info("%s summary scheduled for %s", kind, target.isoformat(timespec="minutes"))
        await asyncio.sleep(max(0.0, (target - datetime.now(PRAGUE)).total_seconds()))
        try:
            result = await generate(conn, use_cache=False, kind=kind)
            if result["text"]:
                title = (f"Týden nad Českem (do {target:%-d. %-m.})" if kind == "week"
                         else f"Dnešní provoz nad Českem ({target:%-d. %-m.})")
                await notify.notify(title, result["text"], tags=["airplane"], url="/", tag=f"summary-{kind}")
        except Exception:
            log.exception("%s summary failed", kind)
        await asyncio.sleep(60)   # never fire twice for the same minute
