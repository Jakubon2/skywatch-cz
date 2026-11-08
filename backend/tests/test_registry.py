import asyncio

import httpx
import pytest

import db
import enrich
import history
import routes_extra

ADSBDB_AIRCRAFT = {"response": {"aircraft": {
    "type": "737NG 8AS/W", "icao_type": "B738", "manufacturer": "Boeing", "mode_s": "4CA7B5",
    "registration": "EI-EFZ", "registered_owner_country_iso_name": "IE",
    "registered_owner_country_name": "Ireland", "registered_owner_operator_flag_code": "RYR",
    "registered_owner": "Ryanair", "url_photo": "https://image.airport-data.com/x.jpg"}}}


def test_parse_aircraft():
    a = enrich.parse_aircraft(ADSBDB_AIRCRAFT)
    assert a == {"type": "737NG 8AS/W", "icao_type": "B738", "manufacturer": "Boeing", "registration": "EI-EFZ",
                 "owner": "Ryanair", "owner_country": "Ireland", "owner_country_iso": "IE", "operator_code": "RYR"}
    assert enrich.parse_aircraft({"response": "unknown aircraft"}) is None
    assert enrich.parse_aircraft({"response": {"aircraft": {}}}) is None
    assert enrich.parse_aircraft(None) is None


def test_parse_adsbdb_airline_name():
    data = {"response": {"flightroute": {
        "callsign_icao": "LOT5CN", "airline": {"icao": "LOT", "name": "LOT Polish Airlines"},
        "origin": {"icao_code": "EPWA", "latitude": 52.17, "longitude": 20.97},
        "destination": {"icao_code": "LSGG", "latitude": 46.24, "longitude": 6.11}}}}
    r = enrich.parse_adsbdb(data, 50.2, 13.0)
    assert r["airline_name"] == "LOT Polish Airlines" and r["airline_code"] == "LOT"


def run_lookups(handler, *hexes):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return [await enrich.aircraft(h, client=c) for h in hexes]
    return asyncio.run(run())


@pytest.fixture
def fresh_registry(monkeypatch):
    monkeypatch.setitem(enrich.registry.cfg, "min_interval_s", 0)
    enrich.registry.cache.clear()
    enrich.registry.calls.clear()


def test_aircraft_lookup_cached(fresh_registry):
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=ADSBDB_AIRCRAFT)
    a, b = run_lookups(handler, "4CA7B5", "4ca7b5")
    assert a == b and a["owner"] == "Ryanair"
    assert urls == ["https://api.adsbdb.com/v0/aircraft/4ca7b5"]


def test_aircraft_unknown_is_cached_as_none(fresh_registry):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, json={"response": "unknown aircraft"})
    assert run_lookups(handler, "44040e", "44040e") == [None, None]
    assert len(calls) == 1


def test_aircraft_429_raises_and_is_not_cached(fresh_registry):
    with pytest.raises(enrich.Unavailable):
        run_lookups(lambda r: httpx.Response(429), "abcdef")
    assert enrich.registry.cached("abcdef") == (False, None)


def test_privacy_filter_hides_owner_for_ladd_and_pia():
    info = enrich.parse_aircraft(ADSBDB_AIRCRAFT)
    assert routes_extra.privacy_filter(info, 0)["owner"] == "Ryanair"
    assert routes_extra.privacy_filter(info, 1)["owner"] == "Ryanair"       # military only
    for flags in (4, 8, 12, 13):
        hidden = routes_extra.privacy_filter(info, flags)
        assert hidden["owner"] is None and hidden["registration"] is None and hidden["owner_country"] is None
        assert hidden["manufacturer"] == "Boeing"                            # the type is fine to show
    assert routes_extra.privacy_filter(None, 8) is None


def test_type_seen():
    conn = db.connect(":memory:")
    history.init(conn)
    now = 1_794_100_000
    rows = [(now - 60, "aaa001", "B738"), (now - 120, "aaa001", "B738"), (now - 600, "aaa002", "B738"),
            (now - 90_000, "aaa003", "B738"), (now - 60, "aaa004", "A320")]
    for ts, hex_, t in rows:
        conn.execute("INSERT INTO positions (ts, hex, t, lat, lon) VALUES (?, ?, ?, 50, 14)", (ts, hex_, t))
    conn.execute("INSERT INTO seen_types (type, first_seen, last_seen) VALUES ('B738', ?, ?)", (now - 5000, now))
    routes_extra._type_cache.clear()
    assert routes_extra.type_seen(conn, "B738", now) == {"type": "B738", "aircraft_24h": 2, "first_seen": now - 5000}
    assert routes_extra.type_seen(conn, "ZZZZ", now)["aircraft_24h"] == 0
