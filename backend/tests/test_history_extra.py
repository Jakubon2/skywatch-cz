import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

import db
import enrich
import history
import passes
import summary
from explain import PRAGUE

T0 = 1_794_100_000  # unix seconds


def plane(hex, ts_offset=0, flight="CSA123", t="A320", lat=50.0, lon=14.5, alt=30000):
    return {"hex": hex, "flight": flight + "  ", "t": t, "lat": lat, "lon": lon, "alt_baro": alt,
            "track": 90.4, "gs": 450.6, "category": "A3", "dbFlags": 0, "seen_pos": ts_offset}


def snap(ts, ac):
    return {"now": ts * 1000, "ac": ac}


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    history.init(c)
    passes.init(c)
    return c


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]


# ---------- recorder ----------

def test_downsampling(conn):
    rec = history.Recorder(conn)
    for i in range(13):                     # one snapshot every 10 s for 2 min
        rec.record(snap(T0 + i * 10, [plane("aaaaaa"), plane("bbbbbb", lat=49.0)]))
    # sample_s = 30 -> t0, t0+30, t0+60, t0+90, t0+120 per aircraft
    assert count(conn) == 10
    row = conn.execute("SELECT flight, alt, gs FROM positions LIMIT 1").fetchone()
    assert row[0] == "CSA123" and row[1] == 30000


def test_skips_no_position_and_keeps_ground(conn):
    rec = history.Recorder(conn)
    rec.record(snap(T0, [{"hex": "cccccc"}, plane("dddddd", alt="ground")]))
    assert [tuple(r) for r in conn.execute("SELECT hex, alt FROM positions")] == [("dddddd", "ground")]


def test_pruning(conn):
    rec = history.Recorder(conn)
    rec.record(snap(T0, [plane("aaaaaa")]))
    rec.record(snap(T0 + 23 * 3600, [plane("aaaaaa")]))
    assert count(conn) == 2
    rec.record(snap(T0 + 25 * 3600, [plane("aaaaaa")]))   # prune due (> 10 min since last)
    assert count(conn) == 2                                # first one (25 h old) removed
    assert conn.execute("SELECT MIN(ts) FROM positions").fetchone()[0] == T0 + 23 * 3600


def test_size_estimate(conn, tmp_path):
    """~250 aircraft for 2 h at 30 s sampling; bytes per row stays small enough for 24 h."""
    c = db.connect(tmp_path / "s.db")
    rec = history.Recorder(c)
    for i in range(0, 7200, 10):
        rec.record(snap(T0 + i, [plane(f"{n:06x}", lat=48 + n / 100, flight=f"ABC{n}") for n in range(250)]))
    c.execute("VACUUM")
    rows = count(c)
    size = (tmp_path / "s.db").stat().st_size
    per_row = size / rows
    assert rows == 250 * 240
    # 24 h at ~250 aircraft: 720k rows; keep the DB comfortably under ~100 MB.
    assert per_row * 720_000 < 100e6, per_row


# ---------- frames ----------

def test_frames(conn):
    rec = history.Recorder(conn)
    for i in range(0, 600, 10):
        ac = [plane("aaaaaa", lon=14 + i / 1000)]
        if i < 200:
            ac.append(plane("bbbbbb", flight="RYR1", t="B738"))
        rec.record(snap(T0 + i, ac))
    out = history.frames(conn, T0, T0 + 600, 60)
    assert out["step"] == 60 and len(out["frames"]) == 11
    assert out["aircraft"]["bbbbbb"] == ["RYR1", "B738", "A3", 0]
    hexes = [{p[0] for p in f["ac"]} for f in out["frames"]]
    assert hexes[0] == {"aaaaaa", "bbbbbb"}
    assert hexes[-1] == {"aaaaaa"}                 # bbbbbb went stale after ~90 s
    assert all("aaaaaa" in h for h in hexes)       # no flicker despite 30 s sampling
    last = out["frames"][-1]["ac"][0]
    assert last[1:4] == [50.0, 14.57, 30000] and last[4:] == [90, 451]


def test_frames_capped(conn):
    out = history.frames(conn, T0, T0 + 24 * 3600, 30)
    assert len(out["frames"]) <= 241 and out["step"] == 360


# ---------- stats ----------

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def test_stats(conn):
    rec = history.Recorder(conn)
    for i in range(0, 1200, 30):
        ac = [plane("a1", flight="CSA1"), plane("a2", flight="CSA2"), plane("a3", flight="RYR9", t="B738"),
              plane("a4", flight="OKABC", t="C172")]
        if i >= 600:
            ac.append(plane("a5", flight="XYZ12", t="A124"))
        rec.record(snap(T0 - T0 % 600 + i, ac))
    db.touch_types(conn, {"A320", "B738", "C172"}, T0 - 86400 * 10)
    db.touch_types(conn, {"A124"}, T0)
    for typ in ("holding", "holding", "emergency"):
        db.insert_event(conn, {"type": typ, "hex": "a1", "callsign": "CSA1", "aircraft_type": "A320",
                               "lat": 50, "lon": 14, "alt_ft": 5000, "started_at": iso(T0), "data": {}})
    db.insert_event(conn, {"type": "go_around", "hex": "a1", "callsign": "CSA1", "aircraft_type": "A320",
                           "lat": 50, "lon": 14, "alt_ft": 5000, "started_at": iso(T0 - 7 * 86400), "data": {}})

    s = history.stats(conn, T0 - 3600, T0 + 3600, top_n=3)
    assert [b["aircraft"] for b in s["traffic"]] == [4, 5]
    assert s["unique_aircraft"] == 5
    assert s["top_airlines"][0] == {"code": "CSA", "name": "Czech Airlines", "flights": 2}
    assert {a["code"] for a in s["top_airlines"]} == {"CSA", "RYR", "XYZ"}   # OKABC isn't an airline
    assert s["top_types"][0] == {"type": "A320", "aircraft": 2}
    assert s["rarest_types"][0]["type"] == "A124"    # 1 aircraft, seen most recently
    assert s["events"] == {"holding": 2, "emergency": 1}


# ---------- daily summary ----------

def test_summary_facts_and_schedule(conn):
    now = datetime(2026, 11, 8, 19, 0, tzinfo=PRAGUE)
    rec = history.Recorder(conn)
    rec.record(snap(int(now.timestamp()) - 600, [plane("a1")]))
    db.insert_event(conn, {"type": "holding", "hex": "a1", "callsign": "CSA1", "aircraft_type": "A320",
                           "lat": 50, "lon": 14, "alt_ft": 5000, "started_at": iso(now.timestamp() - 300),
                           "data": {}})
    f = summary.build_facts(conn, now)
    assert f["unikatnich_letadel"] == 1 and f["udalosti_celkem"] == 1
    assert f["udalosti"][0]["cas"] == "18:55"
    assert f["udalosti_podle_typu_letadla"] == {"A320": 1}
    json.dumps(f, ensure_ascii=False)

    assert summary.next_run(now) == datetime(2026, 11, 8, 20, 0, tzinfo=PRAGUE)
    assert summary.next_run(now.replace(hour=20)) == datetime(2026, 11, 9, 20, 0, tzinfo=PRAGUE)


def test_summary_without_api_call(conn, monkeypatch):
    kinds = []

    async def fake(facts, kind="day"):
        kinds.append(kind)
        return "Dnes byl klidný den." if kind == "day" else "Klidný týden."
    monkeypatch.setattr(summary, "_ask_claude", fake)
    summary._cache.clear()
    now = datetime(2026, 11, 8, 20, 0, tzinfo=PRAGUE)
    r = asyncio.run(summary.generate(conn, now))
    assert r["text"] == "Dnes byl klidný den." and r["day"] == "2026-11-08" and r["kind"] == "day"
    w = asyncio.run(summary.generate(conn, now, kind="week"))
    assert w["text"] == "Klidný týden." and w["kind"] == "week"
    # Both cached separately: no further calls
    asyncio.run(summary.generate(conn, now))
    asyncio.run(summary.generate(conn, now, kind="week"))
    assert kinds == ["day", "week"]


def test_week_facts(conn):
    now = datetime(2026, 11, 8, 20, 0, tzinfo=PRAGUE)   # Sunday
    rec = passes.PassRecorder(conn)
    for days_ago, flights in ((0, ["CSA1", "RYR2"]), (2, ["CSA1"]), (9, ["OLD1"])):
        t = now.timestamp() - days_ago * 86400 - 3600
        rec.record({"now": t * 1000, "ac": [plane(f, flight=f, t="A320") for f in flights]})
    db.insert_event(conn, {"type": "holding", "hex": "a1", "callsign": "CSA1", "aircraft_type": "A320",
                           "lat": 50, "lon": 14, "alt_ft": 5000, "started_at": iso(now.timestamp() - 2 * 86400),
                           "data": {}})
    db.insert_event(conn, {"type": "holding", "hex": "a1", "callsign": "CSA1", "aircraft_type": "A320",
                           "lat": 50, "lon": 14, "alt_ft": 5000, "started_at": iso(now.timestamp() - 9 * 86400),
                           "data": {}})
    f = summary.build_week_facts(conn, now)
    assert f["obdobi"] == {"od": "2026-11-02", "do": "2026-11-08"}
    assert [d["letu"] for d in f["dny"]] == [0, 0, 0, 0, 1, 0, 2]
    assert f["dny"][-1]["hodin_zaznamu"] == 1 and f["dny"][0]["hodin_zaznamu"] == 0
    assert f["letu_celkem"] == 3 and f["nejrusnejsi_den"] == {"datum": "2026-11-08", "letu": 2}
    assert f["top_aerolinky"][0] == {"kod": "CSA", "nazev": "Czech Airlines", "letu": 2}
    assert f["udalosti_celkem"] == 1 and f["udalosti"][0]["kdy"] == "6. 11. 20:00"
    json.dumps(f, ensure_ascii=False)


def test_weekly_schedule():
    sat = datetime(2026, 11, 7, 21, 0, tzinfo=PRAGUE)
    assert summary.next_run(sat, "20:30", 6) == datetime(2026, 11, 8, 20, 30, tzinfo=PRAGUE)
    sun_late = datetime(2026, 11, 8, 20, 30, tzinfo=PRAGUE)
    assert summary.next_run(sun_late, "20:30", 6) == datetime(2026, 11, 15, 20, 30, tzinfo=PRAGUE)
    # Across the DST change (25 Oct 2026): still 20:30 local
    assert summary.next_run(datetime(2026, 10, 24, 21, 0, tzinfo=PRAGUE), "20:30", 6).hour == 20


# ---------- route / photo ----------

ROUTESET = [{
    "_airport_codes_iata": "PRG-LHR", "_airports": [
        {"icao": "LKPR", "iata": "PRG", "name": "Václav Havel Airport Prague", "location": "Prague",
         "countryiso2": "CZ", "lat": 50.1, "lon": 14.26, "alt_feet": 1247},
        {"icao": "EGLL", "iata": "LHR", "name": "London Heathrow", "location": "London",
         "countryiso2": "GB", "lat": 51.47, "lon": -0.46, "alt_feet": 83},
    ], "airline_code": "CSA", "callsign": "CSA3RM", "number": "3RM", "plausible": True,
}]


def test_parse_route():
    r = enrich.parse_route(ROUTESET, "CSA3RM")
    assert r["origin"]["icao"] == "LKPR" and r["destination"]["iata"] == "LHR"
    assert r["stops"] == [] and r["plausible"] is True
    assert enrich.parse_route(ROUTESET, "RYR1") is None
    assert enrich.parse_route(None, "CSA3RM") is None
    assert enrich.parse_route([{"callsign": "CSA3RM", "_airports": []}], "CSA3RM") is None


def test_route_cached(monkeypatch):
    monkeypatch.setitem(enrich.routes.cfg, "min_interval_s", 0)
    enrich.routes.cache.clear()
    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=ROUTESET)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            a = await enrich.route("csa3rm", 50, 14, client=c)
            b = await enrich.route("CSA3RM", 50, 14, client=c)
            return a, b
    a, b = asyncio.run(run())
    assert a == b and a["destination"]["icao"] == "EGLL"
    assert calls == [{"planes": [{"callsign": "CSA3RM", "lat": 50, "lng": 14}]}]


def test_route_empty_body_cached_as_unknown(monkeypatch):
    monkeypatch.setitem(enrich.routes.cfg, "min_interval_s", 0)
    enrich.routes.cache.clear()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(201))) as c:
            return await enrich.route("XXX1", 50, 14, client=c)
    assert asyncio.run(run()) is None
    assert enrich.routes.cached("XXX1") == (True, None)


def test_route_429_raises(monkeypatch):
    monkeypatch.setitem(enrich.routes.cfg, "min_interval_s", 0)
    enrich.routes.cache.clear()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as c:
            return await enrich.route("YYY1", 50, 14, client=c)
    with pytest.raises(enrich.Unavailable):
        asyncio.run(run())
    assert enrich.routes.cached("YYY1") == (False, None)


PHOTOS = {"photos": [{
    "id": "123", "thumbnail": {"src": "https://t.plnspttrs.net/1/x_t.jpg", "size": {"width": 200, "height": 133}},
    "thumbnail_large": {"src": "https://t.plnspttrs.net/1/x_280.jpg", "size": {"width": 420, "height": 280}},
    "link": "https://www.planespotters.net/photo/123/ok-tse", "photographer": "Jan Novák",
}]}


def test_parse_photo():
    p = enrich.parse_photo(PHOTOS)
    assert p["thumbnail_large"].endswith("_280.jpg") and p["width"] == 420
    assert p["photographer"] == "Jan Novák" and p["link"].startswith("https://www.planespotters.net/")
    assert enrich.parse_photo({"photos": []}) is None
    assert enrich.parse_photo({"error": "x"}) is None


def test_photo_by_hex_and_reg(monkeypatch):
    monkeypatch.setenv("SKYWATCH_CONTACT", "https://example.com/contact")
    monkeypatch.setitem(enrich.photos.cfg, "min_interval_s", 0)
    enrich.photos.cache.clear()
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=PHOTOS)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await enrich.photo("49D3A1", client=c)
            await enrich.photo("ok-tse", client=c)
            await enrich.photo("49d3a1", client=c)     # cached
    asyncio.run(run())
    assert urls == ["https://api.planespotters.net/pub/photos/hex/49d3a1",
                    "https://api.planespotters.net/pub/photos/reg/OK-TSE"]


def test_photo_needs_contact(monkeypatch):
    monkeypatch.delenv("SKYWATCH_CONTACT", raising=False)
    enrich.photos.cache.clear()
    with pytest.raises(enrich.Unavailable):
        asyncio.run(enrich.photo("49d3a1"))


ADSBDB = {"response": {"flightroute": {
    "callsign_icao": "TVS1234", "airline": {"icao": "TVS"},
    "origin": {"icao_code": "LKPR", "iata_code": "PRG", "name": "Prague", "municipality": "Prague",
               "country_iso_name": "CZ", "latitude": 50.1, "longitude": 14.26},
    "destination": {"icao_code": "HEGN", "iata_code": "HRG", "name": "Hurghada", "municipality": "Hurghada",
                    "country_iso_name": "EG", "latitude": 27.18, "longitude": 33.8}}}}


def test_parse_adsbdb_route_and_plausibility():
    on_way = enrich.parse_adsbdb(ADSBDB, 47.5, 19.0)          # over Budapest
    assert on_way["origin"]["icao"] == "LKPR" and on_way["destination"]["icao"] == "HEGN"
    assert on_way["codes"] == "PRG-HRG" and on_way["plausible"] is True
    assert enrich.parse_adsbdb(ADSBDB, 55.7, 12.6)["plausible"] is False   # over Copenhagen
    assert enrich.parse_adsbdb({"response": "unknown callsign"}, 50, 14) is None
