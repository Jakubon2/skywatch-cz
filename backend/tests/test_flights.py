"""Flight tracking ("Moje lety"): query parsing, the state machine and the API."""

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import flights
from config import CONFIG

CFG = CONFIG["flights"]
CODES = {"OK": "CSA", "FR": "RYR", "W6": "WZZ"}
PRG = {"icao": "LKPR", "iata": "PRG", "location": "Prague", "lat": 50.1008, "lon": 14.26}
CDG = {"icao": "LFPG", "iata": "CDG", "location": "Paris", "lat": 49.0097, "lon": 2.5479}
ROUTE = {"origin": CDG, "destination": PRG}


@pytest.mark.parametrize("query,expected", [
    ("OK 640", "CSA640"), ("ok640", "CSA640"), ("FR 0123", "RYR123"), ("W6 2345", "WZZ2345"),
    ("CSA640", "CSA640"), ("RYR8NG", "RYR8NG"), ("ok-abc", "OKABC"), ("N628TS", "N628TS"),
    ("12345", None), ("X", None), ("hello world!", None),
])
def test_to_callsign(query, expected):
    assert flights.to_callsign(query, CODES) == expected


def test_config_codes_load():
    codes = flights.load_codes()
    assert codes["OK"] == "CSA" and codes["FR"] == "RYR"


def ac(lat, lon, alt, gs=250, **kw):
    return {"hex": "49d3d5", "lat": lat, "lon": lon, "alt_baro": alt, "gs": gs, **kw}


def run(states, samples, start=1000.0, step=60.0):
    """Feed samples in order; returns the final state and all events."""
    s, events, t = dict(states), [], start
    for sample in samples:
        s, ev = flights.assess(s, sample, t, CFG)
        events += ev
        t += step
    return s, events


def test_full_flight_cdg_to_prague():
    samples = [
        ac(49.01, 2.55, "ground", gs=10),         # at the gate in Paris
        ac(49.02, 2.6, 1500),                      # take-off
        ac(49.6, 8.0, 36000, gs=450),              # cruise
        ac(50.2, 13.8, 9000, gs=280),              # ~35 km out, descending
        ac(50.11, 14.24, 1200, gs=150),
        ac(50.10, 14.26, "ground", gs=40),         # on the runway
    ]
    s, events = run({"status": "waiting", "route": ROUTE}, samples)
    assert events == ["takeoff", "approach", "landed"]
    assert s["status"] == "landed" and not s["guessed"]


def test_first_seen_in_the_air_is_airborne_not_takeoff():
    s, events = run({"status": "waiting", "route": ROUTE}, [ac(49.6, 8.0, 36000, gs=450)])
    assert events == ["airborne"] and s["status"] == "airborne"
    assert 1000 + 1800 < s["eta"] < 1000 + 3000   # ~450 km at 830 km/h, path factor 1.15: ~37 min


def test_lost_near_destination_and_low_counts_as_landed():
    s, _ = run({"status": "waiting", "route": ROUTE}, [ac(50.15, 14.0, 4000, gs=200)])   # ~20 km out
    assert s["status"] == "approach"
    s, events = flights.assess(s, None, s["last_seen"] + CFG["lost_after_s"] + 1, CFG)
    assert events == ["landed_guess"] and s["status"] == "landed" and s["guessed"]


def test_lost_en_route_is_just_lost():
    s, _ = run({"status": "waiting", "route": ROUTE}, [ac(49.6, 8.0, 36000, gs=450)])
    s, events = flights.assess(s, None, s["last_seen"] + CFG["lost_after_s"] + 1, CFG)
    assert events == [] and s["status"] == "lost"
    s, events = flights.assess(s, ac(49.9, 11.0, 35000, gs=450), s["last_seen"] + 2000, CFG)
    assert events == [] and s["status"] == "airborne"   # back in coverage: no second "airborne" push


def test_departing_from_the_destination_is_not_an_approach():
    # The route database gave CAG -> MUC, but the plane is climbing out of Munich heading north (previous leg).
    MUC = {"iata": "MUC", "lat": 48.3538, "lon": 11.7861}
    s, events = run({"status": "waiting", "route": {"origin": CDG, "destination": MUC}},
                    [ac(48.6, 11.8, 8000, gs=300, track=10), ac(48.9, 11.9, 15000, gs=380, track=10)])
    assert events == ["airborne"] and s["status"] == "airborne" and s["eta"] is None


def test_go_around_leaves_approach_quietly():
    s, events = run({"status": "waiting", "route": ROUTE}, [ac(50.2, 13.8, 9000, gs=280, track=110)])
    assert s["status"] == "approach"
    s, events = flights.assess(s, ac(50.12, 14.5, 4000, gs=200, track=60), s["last_seen"] + 60, CFG)
    assert s["status"] == "airborne" and events == []


def test_no_destination_no_approach_but_landing_works():
    s, events = run({"status": "waiting"}, [ac(50.0, 14.0, 3000), ac(50.0, 14.0, 500), ac(50.0, 14.0, "ground", gs=20)])
    assert events == ["airborne", "landed"] and s["eta"] is None


def test_messages_are_czech_and_metric():
    s, _ = run({"status": "waiting", "route": ROUTE}, [ac(50.2, 13.8, 9000, gs=280)])
    title, body = flights.message("approach", "OK 640", s)
    assert title == "OK 640 přistává" and "km" in body and "Přílet kolem" in body
    assert "ft" not in body and "kt" not in body


def test_opted_out_aircraft_are_hidden():
    assert flights.hidden({"dbFlags": 8}) and flights.hidden({"dbFlags": 4}) and not flights.hidden({"dbFlags": 1})


# --- API ---------------------------------------------------------------------

class FakePoller:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.listeners = []
        self.side_request = None
        self.latest = {"now": 1_700_000_000_000, "ac": [
            {"hex": "49d3d5", "flight": "CSA640  ", "lat": 50.11, "lon": 14.24, "alt_baro": 1200, "gs": 150},
        ]}


@pytest.fixture
def api(monkeypatch):
    async def no_route(*a, **kw):
        return None
    monkeypatch.setattr(flights.enrich, "route", no_route)
    poller = FakePoller()
    app = FastAPI()
    app.include_router(flights.make_router(poller))
    return poller, TestClient(app)


def test_add_list_remove(api):
    poller, client = api
    dev = "device-1234"
    r = client.post("/api/flights", json={"device_id": dev, "query": "ok 640"})
    assert r.status_code == 201
    f = r.json()["flights"][0]
    assert f["callsign"] == "CSA640" and f["query"] == "OK 640"
    assert f["status"] == "airborne" and f["in_range"] and not f["push"]   # found in our area right away
    assert client.post("/api/flights", json={"device_id": dev, "query": "CSA640"}).status_code == 409
    assert client.get("/api/flights/other-device").json()["flights"] == []
    assert client.post("/api/flights", json={"device_id": dev, "query": "12345"}).status_code == 422
    assert client.delete(f"/api/flights/other-device/{f['id']}").status_code == 404
    assert client.delete(f"/api/flights/{dev}/{f['id']}").json()["flights"] == []


def test_side_request_only_for_flights_outside_the_area(api):
    poller, client = api
    client.post("/api/flights", json={"device_id": "device-1234", "query": "CSA640"})
    assert poller.side_request() is None          # in our area: no global lookup
    client.post("/api/flights", json={"device_id": "device-1234", "query": "BAW8NG"})
    coro = poller.side_request()
    assert coro is not None
    coro.close()
    assert poller.side_request() is None          # spaced by global_every_s


def test_global_hit_is_used(api):
    poller, client = api
    client.post("/api/flights", json={"device_id": "device-1234", "query": "BAW8NG"})
    tracker = poller.listeners[0]

    class Client:
        async def fetch_callsign(self, cs):
            return {"now": 1_700_000_005_000, "ac": [{"hex": "4007f1", "flight": "BAW8NG", "lat": 51.4, "lon": -0.4,
                                                      "alt_baro": "ground", "gs": 0, "seen_pos": 1}]}
    poller.client = Client()
    asyncio.run(tracker._lookup("BAW8NG"))
    poller.latest = {"now": 1_700_000_010_000, "ac": []}
    asyncio.run(tracker(poller, []))
    f = client.get("/api/flights/device-1234").json()["flights"][0]
    assert f["status"] == "ground" and f["aircraft"]["lat"] == 51.4 and not f["in_range"]
