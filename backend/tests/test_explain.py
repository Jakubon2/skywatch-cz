import asyncio
from types import SimpleNamespace

import pytest

import explain
import metar
from config import CONFIG

EVENT = {
    "type": "holding",
    "hex": "4b1805",
    "callsign": "SWR1484 ",
    "aircraft_type": "A320",
    "lat": 49.95,
    "lon": 14.05,
    "alt_ft": 7000,
    "started_at": "2026-11-08T13:05:00Z",
    "data": {"turn_deg": 380},
}
METAR = "METAR LKPR 081230Z 35003KT 2800 BR SCT002 BKN015 01/00 Q1025 NOSIG (kategorie IFR)"


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_response(text="Letadlo nejspíš čeká na přistání. Důvod z dat nepoznáme.", stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def fake_client(monkeypatch):
    explain._calls.clear()
    messages = FakeMessages(fake_response())
    monkeypatch.setattr(explain, "_get_client", lambda: SimpleNamespace(messages=messages))
    return messages


def run(event=EVENT, track=(), metar_text=METAR):
    return asyncio.run(explain.explain(event, list(track), metar_text))


def test_returns_text_and_uses_configured_model(fake_client):
    assert run() == "Letadlo nejspíš čeká na přistání. Důvod z dat nepoznáme."
    call = fake_client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"effort": CONFIG["explain"]["effort"]}


def test_prompt_contains_metar_event_and_honesty_rules(fake_client):
    run(track=[{"min_ago": 0, "lat": 49.95, "lon": 14.05}])
    call = fake_client.calls[0]
    user = call["messages"][0]["content"]
    assert METAR in user
    assert "SWR1484" in user and "A320" in user and "holding" in user
    assert '"turn_deg": 380' in user
    system = call["system"]
    assert "Nevymýšlej příčiny" in system
    assert "důvod z dat nepoznáme" in system
    assert "nejspíš" in system and "může jít o" in system


def test_missing_metar_is_stated(fake_client):
    run(metar_text=None)
    assert "METAR: není k dispozici" in fake_client.calls[0]["messages"][0]["content"]


def test_cap_blocks_calls_over_limit(fake_client, monkeypatch):
    monkeypatch.setitem(CONFIG["explain"], "max_calls_per_hour", 3)
    results = [run() for _ in range(5)]
    assert results[:3] == [fake_client.response.content[0].text] * 3
    assert results[3:] == [None, None]
    assert len(fake_client.calls) == 3


def test_cap_frees_slots_after_an_hour(fake_client, monkeypatch):
    monkeypatch.setitem(CONFIG["explain"], "max_calls_per_hour", 2)
    now = [1000.0]
    monkeypatch.setattr(explain.time, "monotonic", lambda: now[0])
    run(), run()
    assert run() is None
    now[0] += 3600
    assert run() is not None
    assert len(fake_client.calls) == 3


def test_refusal_or_truncation_gives_none(fake_client):
    fake_client.response = fake_response(stop_reason="refusal")
    assert run() is None
    fake_client.response = fake_response(stop_reason="max_tokens")
    assert run() is None


def test_api_error_gives_none(monkeypatch):
    explain._calls.clear()

    async def boom(**kwargs):
        raise explain.anthropic.APIConnectionError(request=None)

    monkeypatch.setattr(explain, "_get_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=boom)))
    assert run() is None


def sample(ts, alt=5000, **kw):
    return {"ts": ts, "lat": 50.0 + ts / 1e5, "lon": 14.0, "alt_baro": alt, "gs": 250.4,
            "track": 90.6, "baro_rate": -64, **kw}


def test_summarize_track_keeps_window_and_spreads_points():
    history = [sample(t) for t in range(0, 1200, 10)]  # 20 min, one sample per 10 s
    points = explain.summarize_track(history)
    assert len(points) == CONFIG["explain"]["track_points"]
    assert points[0]["min_ago"] == CONFIG["explain"]["track_minutes"]
    assert points[-1]["min_ago"] == 0
    assert points[-1] == {"min_ago": 0.0, "lat": 50.012, "lon": 14.0, "alt_ft": 5000,
                          "gs_kt": 250, "track_deg": 91, "vs_fpm": -64}


def test_summarize_track_short_and_ground_and_empty():
    assert explain.summarize_track([]) == []
    points = explain.summarize_track([sample(0, alt="ground"), sample(10, gs=None)])
    assert len(points) == 2
    assert points[0]["alt_ft"] == "na zemi"
    assert points[1]["gs_kt"] is None


def test_format_metar():
    obs = {"rawOb": "METAR LKPR 081230Z 35003KT 2800 BR", "fltCat": "IFR"}
    assert metar.format_metar(obs) == "METAR LKPR 081230Z 35003KT 2800 BR (kategorie IFR)"
    assert metar.format_metar({"rawOb": "METAR LKPR 081230Z"}) == "METAR LKPR 081230Z"
