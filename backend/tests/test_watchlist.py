import shutil
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat
import watchlist
from config import ROOT
from detectors import Deduper, load_context, run_all, watched

NOW = 1_762_600_000
CFG = {"watched": {"skip_db_flags": [4, 8], "min_samples": 2}}
LIST = watched.index([
    {"reg": "N621MM", "hex": "a81b13", "type": "FA7X", "label": "Taylor Swift", "category": "hudba",
     "source": "https://example.org/swift", "checked": "2026-11-08"},
    {"reg": "PH-UTL", "type": "FA8X", "label": "Max Verstappen", "category": "sport",
     "source": "https://example.org/max", "checked": "2026-11-08"},
])


def sample(hex_id="a81b13", reg="N621MM", i=0, **kw):
    return {"hex": hex_id, "r": reg, "t": "FA7X", "lat": 50.1, "lon": 14.3, "alt_baro": 39000,
            "gs": 470, "track": 120, "ts": NOW + 10 * i, **kw}


def ctx(wl=LIST):
    return {"cfg": CFG, "watchlist": wl}


# --- detector ----------------------------------------------------------------

def test_matches_by_hex():
    hit = watched.detect([sample(i=0), sample(i=1)], ctx())
    assert hit["type"] == "watched"
    assert hit["data"]["label"] == "Taylor Swift"
    assert hit["data"]["category"] == "hudba"
    assert hit["data"]["source"] == "https://example.org/swift"


def test_matches_by_registration_without_hex_and_ignores_dash_and_case():
    track = [sample("484000", "ph-utl", i) for i in range(2)]
    assert watched.detect(track, ctx())["data"]["label"] == "Max Verstappen"
    track = [sample("484000", "PHUTL", i) for i in range(2)]
    assert watched.detect(track, ctx())["data"]["registration"] == "PH-UTL"


@pytest.mark.parametrize("flags", [4, 8, 12, 4 | 1, 8 | 2])
def test_ladd_and_pia_never_match(flags):
    track = [sample(i=i, dbFlags=flags) for i in range(3)]
    assert watched.detect(track, ctx()) is None
    assert watched.match(track[-1], LIST, CFG["watched"]) is None


def test_military_or_interesting_flag_alone_still_matches():
    assert watched.detect([sample(i=i, dbFlags=1 | 2) for i in range(2)], ctx()) is not None


def test_one_opted_out_sample_in_window_keeps_quiet():
    assert watched.detect([sample(i=0, dbFlags=8), sample(i=1)], ctx()) is None


def test_needs_min_samples_and_unlisted_aircraft_is_ignored():
    assert watched.detect([sample()], ctx()) is None
    assert watched.detect([sample("4ca123", "EI-ABC", i) for i in range(3)], ctx()) is None
    assert watched.detect([sample(i=i) for i in range(2)], ctx(watched.index([]))) is None


def test_run_all_and_dedup_with_real_config():
    real = load_context()
    entry = real["watchlist"]["entries"][0]
    track = [sample(entry.get("hex", "000000"), entry["reg"], i) for i in range(3)]
    events = [e for e in run_all(track, real) if e["type"] == "watched"]
    assert len(events) == 1 and events[0]["data"]["label"] == entry["label"]
    dedup = Deduper(real["cfg"]["dedup_minutes"])
    assert dedup.allow("watched", entry["hex"], NOW)
    assert not dedup.allow("watched", entry["hex"], NOW + 600)


def test_starter_list_is_sourced_and_unique():
    entries = load_context()["watchlist"]["entries"]
    assert 20 <= len(entries) <= 40
    regs = [watched.norm_reg(e["reg"]) for e in entries]
    assert len(regs) == len(set(regs))
    for e in entries:
        assert e["source"].startswith("https://"), e
        assert e["checked"] and e["label"] and e["category"], e
        assert e.get("hex") is None or len(e["hex"]) == 6, e


# --- endpoints ---------------------------------------------------------------

@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "watchlist.yaml"
    shutil.copy(ROOT / "config" / "watchlist.yaml", path)
    real = load_context()
    entries = real["watchlist"]["entries"]
    first, second = entries[0], entries[1]
    poller = SimpleNamespace(
        ctx={"cfg": real["cfg"], "watchlist": watched.index(watchlist.load(path))},
        latest={"now": NOW * 1000, "ac": [
            sample(first["hex"], first["reg"]),
            sample(second["hex"], second["reg"], dbFlags=8),  # LADD: never shown as live
            sample("4ca999", "EI-XYZ"),
        ]},
    )
    app = FastAPI()
    app.include_router(watchlist.make_router(poller, path))
    return SimpleNamespace(client=TestClient(app), poller=poller, path=path, first=first, second=second)


def test_get_lists_entries_with_live_position(setup):
    d = setup.client.get("/api/watchlist").json()
    assert d["note"] and d["now"] == NOW * 1000
    by_reg = {e["reg"]: e for e in d["entries"]}
    assert by_reg[setup.first["reg"]]["live"]["lat"] == 50.1
    assert by_reg[setup.second["reg"]]["live"] is None
    assert sum(1 for e in d["entries"] if e["live"]) == 1


def test_add_and_remove_persist_and_update_detector(setup):
    body = {"reg": "ok-abc", "label": "Test Osobnost", "category": "sport", "source": "https://example.org/a"}
    r = setup.client.post("/api/watchlist", json=body)
    assert r.status_code == 201
    assert r.json()["reg"] == "OK-ABC" and r.json()["checked"]
    assert setup.client.post("/api/watchlist", json=body).status_code == 409

    saved = yaml.safe_load(setup.path.read_text(encoding="utf-8"))["aircraft"]
    assert saved[-1]["reg"] == "OK-ABC"
    assert setup.path.read_text(encoding="utf-8").startswith("# Sledovaná letadla")

    track = [sample("49d123", "OK-ABC", i) for i in range(2)]
    assert watched.detect(track, setup.poller.ctx)["data"]["label"] == "Test Osobnost"

    assert setup.client.delete("/api/watchlist/OKABC").status_code == 204
    assert setup.client.delete("/api/watchlist/OK-ABC").status_code == 404
    assert watched.detect(track, setup.poller.ctx) is None
    assert len(yaml.safe_load(setup.path.read_text(encoding="utf-8"))["aircraft"]) == len(saved) - 1


@pytest.mark.parametrize("bad", [
    {"label": "X Y", "category": "sport", "source": "https://e.org"},                  # no reg
    {"reg": "OK-ABC", "label": "X Y", "category": "sport"},                            # no source
    {"reg": "OK-ABC", "label": "X Y", "category": "sport", "source": "neco"},          # not a URL
    {"reg": "OK-ABC", "hex": "xyz", "label": "X Y", "category": "sport", "source": "https://e.org"},
])
def test_add_validates(setup, bad):
    assert setup.client.post("/api/watchlist", json=bad).status_code == 422


# --- chat tool ---------------------------------------------------------------

def test_chat_tool_lists_watched_in_range(setup):
    r = chat.run_tool(setup.poller, "watched_aircraft", {})
    assert r["count"] == 1 and r["watchlist_size"] == len(setup.poller.ctx["watchlist"]["entries"])
    assert r["aircraft"][0]["label"] == setup.first["label"] and r["caveat"]
    r = chat.run_tool(setup.poller, "watched_aircraft", {"only_czechia": True})
    assert r["count"] == 1  # 50.1 / 14.3 is near Prague
