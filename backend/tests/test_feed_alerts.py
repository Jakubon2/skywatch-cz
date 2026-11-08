"""Phase 2b/4b wiring: events feed, explanations, SSE messages and alert rules end to end."""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alerts_service
import feed
import routes_core
from alerts import AlertRule
from poller import Poller

NOW_MS = 1_800_000_000_000


def snapshot(i, **ac):
    plane = {"hex": "abc123", "flight": "TEST1  ", "t": "B738", "category": "A3", "lat": 50.0, "lon": 15.0,
             "alt_baro": 30000, "track": 90, "baro_rate": 0, "squawk": "7700", "emergency": "none",
             "seen_pos": 0, **ac}
    return {"now": NOW_MS + i * 10_000, "ac": [plane]}


@pytest.fixture
def poller():
    alerts_service._last_hits.clear()
    return Poller(db_path=":memory:")


@pytest.fixture
def client(poller):
    app = FastAPI()
    app.include_router(routes_core.make_router(poller))
    return TestClient(app)


def test_new_event_is_published_explained_and_listed(poller, client, monkeypatch):
    async def fake_explain(event, track, metar):
        return "Letadlo hlásí nouzi, důvod z dat nepoznáme."

    async def fake_metar():
        return "LKPR 081400Z ..."

    monkeypatch.setattr(feed, "explain", fake_explain)
    monkeypatch.setattr(feed, "get_metar", fake_metar)
    q = feed.subscribe()

    async def run():
        for i in range(3):   # emergency needs 2 consecutive samples
            await poller._on_snapshot(snapshot(i))
        await asyncio.gather(*feed._tasks)

    poller.listeners.append(feed.on_events)
    asyncio.run(run())

    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    feed.unsubscribe(q)
    assert [m["kind"] for m in msgs] == ["event", "explanation"]
    assert msgs[0]["event"]["type"] == "emergency"

    [event] = client.get("/api/events").json()
    assert event["type"] == "emergency" and event["data"]["squawk"] == "7700"
    assert event["explanation"].startswith("Letadlo hlásí nouzi")


def test_no_explanation_keeps_event(poller, client, monkeypatch):
    async def none(*a):
        return None

    monkeypatch.setattr(feed, "explain", none)
    monkeypatch.setattr(feed, "get_metar", none)
    poller.listeners.append(feed.on_events)

    async def run():
        for i in range(3):
            await poller._on_snapshot(snapshot(i))
        await asyncio.gather(*feed._tasks)

    asyncio.run(run())
    [event] = client.get("/api/events").json()
    assert event["explanation"] is None


def test_alert_rule_flow(poller, client, monkeypatch):
    sent = []

    async def fake_ntfy(title, message, **kw):
        sent.append((title, message))
        return True

    monkeypatch.setattr(alerts_service, "notify", fake_ntfy)

    async def fake_parse(text):
        return AlertRule(military=True)

    monkeypatch.setattr(routes_core, "parse_rule", fake_parse)

    # 1. parse shows how the rule was understood, nothing saved yet
    parsed = client.post("/api/alerts/parse", json={"text": "jakékoli vojenské letadlo"}).json()
    assert parsed["rule"]["military"] is True and parsed["summary"]
    assert client.get("/api/alerts").json() == []

    # 2. confirm saves it
    rule = client.post("/api/alerts", json={"text": "jakékoli vojenské letadlo", "rule": parsed["rule"]}).json()
    assert rule["active"] is True

    # 3. a military aircraft triggers one notification, dedup blocks the repeat
    poller.listeners.append(alerts_service.on_snapshot)

    async def run(n):
        for i in range(n):
            await poller._on_snapshot(snapshot(i, squawk="1000", dbFlags=1, flight="CEF01  "))

    asyncio.run(run(2))
    assert len(sent) == 1 and "CEF01" in sent[0][1]
    assert client.get("/api/alerts").json()[0]["hits"] == 1

    # 4. deactivated rule stays quiet
    alerts_service._last_hits.clear()
    client.patch(f"/api/alerts/{rule['id']}", json={"active": False})
    asyncio.run(run(1))
    assert len(sent) == 1

    # 5. delete
    assert client.delete(f"/api/alerts/{rule['id']}").json() == {"ok": True}
    assert client.get("/api/alerts").json() == []


def test_civil_aircraft_does_not_trigger_military_rule(poller, monkeypatch):
    sent = []

    async def fake_ntfy(title, message, **kw):
        sent.append(title)

    monkeypatch.setattr(alerts_service, "notify", fake_ntfy)
    poller.db.execute("INSERT INTO alert_rules (text, rule_json, created_at) VALUES (?, ?, ?)",
                      ("vojenské", json.dumps({"military": True}), "2026-11-08T00:00:00+00:00"))
    poller.listeners.append(alerts_service.on_snapshot)
    asyncio.run(poller._on_snapshot(snapshot(0, squawk="1000")))
    assert sent == []


def test_event_search_and_single_event(poller, client):
    base = {"hex": "abc", "lat": 50.0, "lon": 15.0, "alt_ft": 30000, "data": {}}
    import db as dbmod
    dbmod.insert_event(poller.db, {**base, "type": "interesting", "callsign": "SIA308", "aircraft_type": "A388",
                                   "started_at": "2026-11-01T12:00:00+00:00"})
    eid = dbmod.insert_event(poller.db, {**base, "type": "holding", "callsign": "CSA123", "aircraft_type": "A320",
                                         "started_at": "2026-11-08T12:00:00+00:00"})
    assert [e["callsign"] for e in client.get("/api/events", params={"q": "a388"}).json()] == ["SIA308"]
    assert [e["callsign"] for e in client.get("/api/events", params={"type": "holding"}).json()] == ["CSA123"]
    assert [e["callsign"] for e in client.get("/api/events", params={"since": "2026-11-05"}).json()] == ["CSA123"]
    assert client.get(f"/api/events/{eid}").json()["callsign"] == "CSA123"
    assert client.get("/api/events/9999").status_code == 404


def test_dedup_survives_restart(tmp_path):
    """A restart (uvicorn --reload) must not re-emit events from the last dedup window."""
    from datetime import datetime, timezone
    import db as dbmod
    path = tmp_path / "t.db"
    first = Poller(db_path=path)
    dbmod.insert_event(first.db, {"type": "interesting", "hex": "abc123", "callsign": "X", "aircraft_type": "C17",
                                  "lat": 50, "lon": 15, "alt_ft": 30000, "data": {},
                                  "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    first.db.commit()
    again = Poller(db_path=path)
    import time
    assert not again.dedup.allow("interesting", "abc123", time.time())
    assert again.dedup.allow("interesting", "other", time.time())


def test_ground_stations_are_not_aircraft(poller):
    """A 'TWR' ground station broadcasting 55 900 ft must never reach the map, chat or detectors."""
    snap = snapshot(0, squawk="1000")
    snap["ac"] += [{"hex": "tower1", "flight": "FFMUNT", "t": "TWR", "r": "TWR", "lat": 47.8, "lon": 13.0,
                    "alt_baro": 55900, "gs": 60},
                   {"hex": "car001", "category": "C2", "lat": 50.1, "lon": 14.26, "alt_baro": "ground"}]
    poller.ingest(snap)
    assert [a["hex"] for a in poller.latest["ac"]] == ["abc123"]
