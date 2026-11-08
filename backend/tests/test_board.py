"""Board classification on synthetic snapshots around a fake LKPR."""

from types import SimpleNamespace
from collections import deque

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import board
import enrich
from config import ROOT

CFG = yaml.safe_load(open(ROOT / "config" / "config.yaml", encoding="utf-8"))["board"]
AP = {"ident": "LKPR", "name": "Václav Havel Airport Prague", "lat": 50.1008, "lon": 14.26, "elevation_ft": 1247}
NOW_MS = 1_762_600_000_000


def ac(hex_id, lat, lon, alt, gs=250, track=90, rate=0, flight=None, **kw):
    a = {"hex": hex_id, "lat": lat, "lon": lon, "alt_baro": alt, "gs": gs, "track": track, "baro_rate": rate, "t": "A320"}
    if flight:
        a["flight"] = flight.ljust(8)
    return {**a, **kw}


def route(orig, dest, plausible=True, city_o="Londýn", city_d="Praha"):
    return {"origin": {"icao": orig, "iata": orig[1:], "location": city_o},
            "destination": {"icao": dest, "iata": dest[1:], "location": city_d},
            "plausible": plausible}


def run(aircraft, routes=None, tracks=None):
    return board.build_board(aircraft, NOW_MS, AP, CFG, routes or {}, tracks)


def statuses(rows):
    return {r["hex"]: r["status"] for r in rows}


def test_descending_toward_airport_is_arrival_with_eta():
    # ~55 km west, heading east, descending, 300 kt -> ~ 55*1.15/556*60 ≈ 7 min
    a = ac("aaa001", 50.1, 13.49, 9000, gs=300, track=90, rate=-1200)
    out = run([a])
    assert statuses(out["arrivals"]) == {"aaa001": "přistává"}
    row = out["arrivals"][0]
    assert 5 <= row["eta_min"] <= 9
    assert row["time_ms"] == pytest.approx(NOW_MS + row["eta_min"] * 60_000, abs=60_000)
    assert out["departures"] == []


def test_descending_away_from_airport_is_ignored():
    a = ac("aaa002", 50.1, 13.49, 9000, track=270, rate=-1200)
    out = run([a])
    assert out["arrivals"] == [] and out["departures"] == []


def test_climbing_near_airport_is_departure():
    a = ac("ddd001", 50.15, 14.40, 6000, gs=220, track=60, rate=2000)
    out = run([a])
    assert statuses(out["departures"]) == {"ddd001": "vzlétl"}
    assert out["departures"][0]["time_ms"] < NOW_MS


def test_takeoff_time_from_track():
    a = ac("ddd002", 50.12, 14.30, 3000, gs=180, rate=2500)
    t0 = NOW_MS / 1000
    track = deque([{**a, "alt_baro": "ground", "gs": 140, "ts": t0 - 130},
                   {**a, "alt_baro": 1600, "ts": t0 - 120}, {**a, "ts": t0}])
    row = run([a], tracks={"ddd002": track})["departures"][0]
    assert row["time_ms"] == int((t0 - 120) * 1000)
    assert row["estimated"] is False


def test_ground_at_airport_parked_and_moving():
    parked = ac("ggg001", 50.101, 14.262, "ground", gs=0)
    taxi = ac("ggg002", 50.099, 14.255, "ground", gs=15)
    elsewhere = ac("ggg003", 49.15, 16.69, "ground", gs=0)   # Brno
    out = run([parked, taxi, elsewhere])
    assert statuses(out["departures"]) == {"ggg001": "na zemi", "ggg002": "odlétá"}
    assert [r["hex"] for r in out["departures"]] == ["ggg002", "ggg001"]


def test_ground_vehicles_are_ignored():
    tower = ac("v1", 50.101, 14.262, "ground", gs=0, t="TWR")
    car = ac("v2", 50.101, 14.262, "ground", gs=20, t=None, category="C2", flight="FOLLOW3")
    out = run([tower, car])
    assert out["departures"] == []
    assert board.route_candidates([tower, car], AP, CFG, set()) == []


def test_numeric_altitude_near_field_counts_as_ground():
    a = ac("ggg004", 50.101, 14.262, 1275, gs=3)
    assert statuses(run([a])["departures"]) == {"ggg004": "na zemi"}


def test_landed_aircraft_with_destination_lkpr_is_arrival_on_ground():
    a = ac("ggg005", 50.101, 14.262, "ground", gs=12, flight="BAW856")
    out = run([a], routes={"BAW856": route("EGLL", "LKPR")})
    assert statuses(out["arrivals"]) == {"ggg005": "na zemi"}
    assert out["arrivals"][0]["place"]["city"] == "Londýn"


def test_route_overrides_heuristics():
    # Level cruise far away but bound for LKPR -> arrival; descending but bound elsewhere -> ignored.
    inbound = ac("rrr001", 49.5, 16.0, 30000, gs=450, track=300, flight="CSA123")
    elsewhere = ac("rrr002", 50.1, 13.49, 9000, track=90, rate=-1200, flight="DLH1")
    out_lkpr = ac("rrr003", 50.6, 15.0, 33000, gs=460, track=60, flight="CSA77")
    routes = {"CSA123": route("LFPG", "LKPR", city_o="Paříž"), "DLH1": route("EDDF", "EPWA"),
              "CSA77": route("LKPR", "UUEE", city_o="Praha", city_d="Moskva")}
    out = run([inbound, elsewhere, out_lkpr], routes)
    assert statuses(out["arrivals"]) == {"rrr001": "přistává"}
    assert out["arrivals"][0]["place"] == {"city": "Paříž", "code": "FPG", "icao": "LFPG"}
    assert statuses(out["departures"]) == {"rrr003": "vzlétl"}
    assert out["departures"][0]["place"]["city"] == "Moskva"


def test_implausible_route_is_ignored():
    a = ac("rrr004", 49.5, 16.0, 30000, gs=450, track=300, flight="CSA123")
    assert run([a], {"CSA123": route("LFPG", "LKPR", plausible=False)})["arrivals"] == []


def test_overflight_and_far_away_ignored():
    cruise = ac("ooo001", 50.0, 14.5, 37000, gs=480, track=90)
    far = ac("ooo002", 52.5, 13.4, 5000, track=180, rate=-1000, flight="X1")   # Berlin, ~300 km
    out = run([cruise, far], {"X1": route("EGLL", "LKPR")})
    assert out["arrivals"] == [] and out["departures"] == []


def test_arrivals_sorted_by_eta_and_capped():
    planes = [ac(f"s{i:05d}", 50.1, 14.26 - 0.1 * (i + 1), 5000, gs=200, track=90, rate=-800)
              for i in range(CFG["max_rows"] + 3)]
    rows = run(planes)["arrivals"]
    assert len(rows) == CFG["max_rows"]
    assert [r["eta_min"] for r in rows] == sorted(r["eta_min"] for r in rows)


def test_route_candidates_closest_first_and_skip_known():
    near = ac("c1", 50.2, 14.3, 4000, flight="A1")
    far = ac("c2", 49.5, 15.5, 20000, flight="A2")
    high = ac("c3", 50.2, 14.3, 38000, flight="A3")
    known = ac("c4", 50.1, 14.26, 3000, flight="A4")
    nocs = ac("c5", 50.1, 14.26, 3000)
    out = board.route_candidates([far, near, high, known, nocs], AP, CFG, {"A4"})
    assert [a["hex"] for a in out] == ["c1", "c2"]


def test_endpoint_uses_cache_only(monkeypatch):
    calls = []

    async def fake_route(cs, lat, lon, client=None):
        calls.append(cs)
        return None

    monkeypatch.setattr(board.airports, "airport", lambda ident: AP)
    monkeypatch.setattr(enrich, "route", fake_route)
    monkeypatch.setattr(enrich.routes, "cache", {})
    enrich.routes.store("CSA123", route("LFPG", "LKPR", city_o="Paříž"))
    poller = SimpleNamespace(
        latest={"now": NOW_MS, "ac": [ac("e1", 49.5, 16.0, 30000, gs=450, track=300, flight="CSA123"),
                                      ac("e2", 50.2, 14.3, 4000, track=200, rate=-900, flight="NEW1")]},
        history={},
    )
    app = FastAPI()
    app.include_router(board.make_router(poller))
    body = TestClient(app).get("/api/board").json()
    assert {r["hex"] for r in body["arrivals"]} == {"e1", "e2"}
    rows = {r["hex"]: r for r in body["arrivals"]}
    assert rows["e1"]["place"]["city"] == "Paříž" and rows["e2"]["place"] is None
    assert calls == ["NEW1"]     # only the uncached callsign is looked up, in the background
