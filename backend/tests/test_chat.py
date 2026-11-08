import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import chat
import db

NOW_MS = int(datetime(2026, 11, 8, 13, 20, tzinfo=timezone.utc).timestamp() * 1000)
NOW = NOW_MS / 1000

PRAGUE = (50.08, 14.43)
VIENNA = (48.20, 16.37)  # inside the snapshot radius, outside Czechia
BEROUN = (49.96, 14.07)


def ac(hex_id, flight, t, lat, lon, alt=35000, **kw):
    return {"hex": hex_id, "flight": f"{flight:<8}", "t": t, "lat": lat, "lon": lon, "alt_baro": alt, "gs": 420, **kw}


SNAPSHOT = [
    ac("4ca001", "RYR12AB", "B738", *PRAGUE),
    ac("4ca002", "RYR3KL", "B38M", 49.2, 16.6),          # Brno
    ac("4ca003", "RYR77", "B738", *VIENNA),              # Ryanair, but over Austria
    ac("4ca004", "RYRX", "B738", 49.5, 15.0),            # not an airline callsign (no digit after prefix)
    ac("49d001", "CSA4FT", "A320", *PRAGUE, alt=3000),
    ac("49d002", "OKABC", "C172", *BEROUN, alt=2500),    # private, registration as callsign
    ac("3f0001", "GAF123", "A400", 50.0, 15.0, alt=24000, dbFlags=1),
    ac("49d003", "CSA1", "A320", 50.10, 14.26, alt="ground"),
]


@pytest.fixture
def poller():
    conn = db.connect(":memory:")
    db.insert_event(conn, {
        "type": "holding", "hex": "4ca001", "callsign": "RYR12AB ", "aircraft_type": "B738",
        "lat": 50.0, "lon": 14.4, "alt_ft": 7000, "started_at": "2026-11-08T13:10:00+00:00",
        "data": {"turn_deg": 380},
    })
    db.insert_event(conn, {
        "type": "emergency", "hex": "49d001", "callsign": "CSA4FT", "aircraft_type": "A320",
        "lat": 50.0, "lon": 14.4, "alt_ft": 3000, "started_at": "2026-11-08T10:00:00+00:00",
        "data": {"squawk": "7700"},
    })
    history = {"4ca001": deque({**SNAPSHOT[0], "ts": NOW - 60 * i} for i in range(5, -1, -1))}
    return SimpleNamespace(latest={"now": NOW_MS, "ac": SNAPSHOT}, history=history, db=conn)


def test_in_czechia():
    assert chat.in_czechia(*PRAGUE)
    assert chat.in_czechia(49.2, 16.6)
    assert chat.in_czechia(49.83, 18.28)  # Ostrava
    assert not chat.in_czechia(*VIENNA)
    assert not chat.in_czechia(51.05, 13.74)  # Dresden
    assert not chat.in_czechia(48.15, 17.11)  # Bratislava


def test_kolik_ryanairu_nad_cr(poller):
    r = chat.search_aircraft(poller, {"callsign_prefix": "RYR", "only_czechia": True})
    assert r["count"] == 3  # RYRX still matches the prefix filter; Vienna does not
    assert "4ca003" not in {a["hex"] for a in r["aircraft"]}
    everywhere = chat.search_aircraft(poller, {"callsign_prefix": "ryr"})
    assert everywhere["count"] == 4
    assert r["data_time"].startswith("2026-11-08")


def test_search_filters(poller):
    assert chat.search_aircraft(poller, {"military": True})["count"] == 1
    assert chat.search_aircraft(poller, {"type_prefix": "B73"})["count"] == 3
    assert chat.search_aircraft(poller, {"on_ground": True})["count"] == 1
    assert chat.search_aircraft(poller, {"max_alt_ft": 5000})["count"] == 3  # includes the one on the ground
    assert chat.search_aircraft(poller, {"max_alt_ft": 5000, "on_ground": False})["count"] == 2
    assert chat.search_aircraft(poller, {"min_alt_ft": 30000})["count"] == 4
    near_beroun = chat.search_aircraft(poller, {"lat": BEROUN[0], "lon": BEROUN[1], "radius_nm": 5})
    assert [a["callsign"] for a in near_beroun["aircraft"]] == ["OKABC"]
    assert len(chat.search_aircraft(poller, {"limit": 2})["aircraft"]) == 2


def test_stats(poller):
    s = chat.stats(poller, {"only_czechia": True})
    assert s["total"] == 7
    assert s["on_ground"] == 1
    assert s["military"] == 1
    assert dict(s["top_airlines_icao"]) == {"RYR": 2, "CSA": 2, "GAF": 1}


def test_aircraft_detail(poller):
    d = chat.aircraft_detail(poller, {"query": "ryr12ab"})
    assert d["hex"] == "4ca001"
    assert d["airline_icao"] == "RYR"
    assert len(d["track_summary"]) > 1
    assert d["events"][0]["type"] == "holding"
    assert chat.aircraft_detail(poller, {"query": "4CA001"})["callsign"] == "RYR12AB"
    assert "error" in chat.aircraft_detail(poller, {"query": "NOPE1"})


def test_recent_events(poller):
    r = chat.recent_events(poller, {"minutes": 60})
    assert [e["type"] for e in r["events"]] == ["holding"]
    assert r["events"][0]["callsign"] == "RYR12AB"
    assert chat.recent_events(poller, {"minutes": 600, "type": "emergency"})["count"] == 1


def test_no_snapshot_yet():
    p = SimpleNamespace(latest=None, history={}, db=None)
    assert "error" in chat.run_tool(p, "stats", {})


# --- loop with a mocked client ---------------------------------------------

def block(type, **kw):
    return SimpleNamespace(type=type, **kw)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def fake(monkeypatch):
    chat._calls.clear()

    def install(*responses):
        messages = FakeMessages(responses)
        monkeypatch.setattr(chat, "_get_client", lambda: SimpleNamespace(messages=messages))
        return messages

    return install


def test_loop_runs_tool_and_answers(poller, fake):
    tool_call = SimpleNamespace(stop_reason="tool_use", content=[
        block("text", text="Podívám se."),
        block("tool_use", id="tu1", name="search_aircraft", input={"callsign_prefix": "RYR", "only_czechia": True}),
    ])
    final = SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Nad ČR jsou teď 3 Ryanairy.")])
    messages = fake(tool_call, final)

    reply = asyncio.run(chat.chat([{"role": "user", "content": "kolik Ryanairů je teď nad ČR?"}], poller))

    assert reply == "Nad ČR jsou teď 3 Ryanairy."
    first, second = messages.calls
    assert first["model"] == "claude-haiku-5-5"
    assert {t["name"] for t in first["tools"]} == {"search_aircraft", "aircraft_detail", "recent_events", "stats"}
    result = second["messages"][-1]["content"][0]
    assert result["tool_use_id"] == "tu1" and not result["is_error"]
    assert json.loads(result["content"])["count"] == 3
    assert second["messages"][-2] == {"role": "assistant", "content": tool_call.content}


def test_loop_tool_error_is_reported_not_raised(poller, fake):
    bad = SimpleNamespace(stop_reason="tool_use", content=[block("tool_use", id="x", name="nope", input={})])
    final = SimpleNamespace(stop_reason="end_turn", content=[block("text", text="To z dat nepoznám.")])
    messages = fake(bad, final)
    assert asyncio.run(chat.chat([{"role": "user", "content": "?"}], poller)) == "To z dat nepoznám."
    assert messages.calls[1]["messages"][-1]["content"][0]["is_error"]


def test_loop_stops_after_max_iterations(poller, fake, monkeypatch):
    monkeypatch.setitem(chat.CONFIG["chat"], "max_tool_iterations", 2)
    loop = SimpleNamespace(stop_reason="tool_use", content=[block("tool_use", id="a", name="stats", input={})])
    messages = fake(loop, loop)
    reply = asyncio.run(chat.chat([{"role": "user", "content": "?"}], poller))
    assert "příliš mnoho kroků" in reply
    assert len(messages.calls) == 2


def test_history_trimmed_to_start_with_user(poller, fake, monkeypatch):
    monkeypatch.setitem(chat.CONFIG["chat"], "max_history_messages", 2)
    messages = fake(SimpleNamespace(stop_reason="end_turn", content=[block("text", text="ok")]))
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    asyncio.run(chat.chat(history, poller))
    assert messages.calls[0]["messages"] == [{"role": "user", "content": "c"}]


def test_hourly_cap(poller, fake, monkeypatch):
    monkeypatch.setitem(chat.CONFIG["chat"], "max_calls_per_hour", 1)
    fake(SimpleNamespace(stop_reason="end_turn", content=[block("text", text="ok")]))
    asyncio.run(chat.chat([{"role": "user", "content": "a"}], poller))
    with pytest.raises(chat.ChatLimitError):
        asyncio.run(chat.chat([{"role": "user", "content": "b"}], poller))
