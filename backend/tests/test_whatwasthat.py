import math
from datetime import datetime

import whatwasthat as w
from explain import PRAGUE

HOME = (50.08, 14.42)
T0 = 1_762_600_000.0


def line(hex_id, t, lat0, lon0, dlat, dlon, alt, n=6, step=30, rate=None, flight=None, flags=None, gs=450):
    """Straight track: n samples `step` s apart, moving dlat/dlon degrees per sample."""
    return [w._sample(T0 + i * step, lat0 + i * dlat, lon0 + i * dlon,
                      alt + (rate or 0) * step / 60 * i if isinstance(alt, (int, float)) else alt,
                      gs, 90, rate, flight, t, None, None, flags)
            for i in range(n)]


def test_overhead_between_two_samples():
    # Eastbound 777 at 3 000 ft. Samples at x = -3.5 km and +3.5 km; it crosses overhead between them.
    dlon = 7 / (w.KM_PER_DEG * math.cos(math.radians(HOME[0])))
    lon0 = HOME[1] - 3.5 / 7 * dlon - 2 * dlon
    tracks = {"aaaaaa": line("aaaaaa", "B77W", HOME[0], lon0, 0, dlon, 3000, flight="DHK123")}
    r = w.find_passes(tracks, *HOME, T0, T0 + 150)
    assert len(r) == 1
    c = r[0]
    # Closest point halfway between samples 2 and 3 (t = 75 s), nearly on top of us.
    assert abs(c["cpa_ts"] - (T0 + 75)) < 1
    assert c["distance_km"] < 0.05
    # Without interpolation the nearest sample would be 3.5 km away.
    assert c["slant_km"] < 1.0
    assert c["class"] == "widebody"
    assert c["type_name"] == "Boeing 777"


def test_loud_heavy_beats_distant_light():
    # Climbing 777 passing 4 km north vs a Cessna passing 3 km south: horizontally the Cessna is
    # closer, but the heavy at climb thrust is the one you hear.
    heavy = line("heavy1", "B772", HOME[0] + 0.036, HOME[1] - 0.1, 0, 0.03, 4500, rate=1500)
    light = line("light1", "C172", HOME[0] - 0.027, HOME[1] - 0.01, 0, 0.004, 2000, gs=100)
    r = w.find_passes({"heavy1": heavy, "light1": light}, *HOME, T0, T0 + 150)
    assert [c["hex"] for c in r] == ["heavy1", "light1"]
    assert r[0]["distance_km"] > r[1]["distance_km"]
    assert r[0]["db"] > r[1]["db"] + 5
    assert r[0]["phase"] == "climb"
    assert "stoupalo" in " ".join(w.reasons(r[0])) and "je to velký dálkový typ" in w.reasons(r[0])


def test_closest_light_beats_distant_light():
    near = line("near01", "C172", HOME[0] + 0.005, HOME[1] - 0.02, 0, 0.004, 2500, gs=100)
    far = line("far001", "C172", HOME[0] + 0.12, HOME[1] - 0.02, 0, 0.004, 2500, gs=100)
    r = w.find_passes({"near01": near, "far001": far}, *HOME, T0, T0 + 150)
    assert [c["hex"] for c in r] == ["near01", "far001"]


def test_empty_result():
    assert w.find_passes({}, *HOME, T0, T0 + 150) == []
    # Far away, on the ground, or outside the time window.
    far = line("far", "A320", HOME[0] + 1, HOME[1], 0, 0.01, 30000)
    ground = line("gnd", "A320", HOME[0], HOME[1], 0, 0.0001, "ground")
    later = line("late", "A320", *HOME, 0, 0.01, 3000)
    later = [{**s, "ts": s["ts"] + 3600} for s in later]
    assert w.find_passes({"far": far, "gnd": ground, "late": later}, *HOME, T0, T0 + 150) == []


def test_no_interpolation_across_gap():
    # Samples ~18 km either side of home, 5 minutes apart: not interpolated, so nothing is "close".
    s = line("gap", "A320", HOME[0], HOME[1] - 0.25, 0, 0.5, 5000, n=2, step=300)
    assert w.find_passes({"gap": s}, *HOME, T0, T0 + 300) == []


def test_private_aircraft_anonymous():
    s = line("ladd01", "C25A", *HOME, 0, 0.003, 3000, flight="N123AB", flags=8)
    c = w.find_passes({"ladd01": s}, *HOME, T0, T0 + 150)[0]
    assert c["private"] and c["flight"] is None and c["r"] is None
    assert "N123AB" not in w.sentence(c, T0 + 200, live=True)


def test_merge_live_and_stored():
    rows = [(int(T0), "abc", "CSA1", "A320", 50.0, 14.0, 5000, 90, 300, "A3", 0),
            (int(T0) + 30, "abc", "CSA1", "A320", 50.0, 14.1, 5000, 90, 300, "A3", 0)]
    live = {"abc": [{"ts": T0 + 30, "lat": 50.0, "lon": 14.1, "alt_baro": 5000, "baro_rate": 0, "r": "OK-ABC"},
                    {"ts": T0 + 40, "lat": 50.0, "lon": 14.13, "alt_baro": 5000}]}
    tr = w.merge_tracks(live, rows)["abc"]
    assert [s["ts"] for s in tr] == [T0, T0 + 30, T0 + 40]
    assert tr[1]["r"] == "OK-ABC"


def test_sentence_and_reasons():
    c = {"hex": "x", "flight": "DHK123", "r": None, "t": "B77W", "type_name": "Boeing 777", "private": False,
         "class": "widebody", "cpa_ts": T0, "alt_m": 914, "height_m": 664, "rate_ms": 8.0,
         "distance_km": 0.4, "slant_km": 0.78, "db": 88.0}
    route = {"plausible": True, "origin": {"location": "Leipzig"}, "destination": {"location": "Hong Kong"}}
    text = w.sentence(c, T0 + 40, live=True, route=route)
    assert text.startswith("Před 40 s nad tebou přeletěl Boeing 777 DHL Air (DHK123, Leipzig → Hong Kong)")
    assert "výška 900 m" in text
    assert "stoupalo po startu" in text and "proto bylo tak hlasité" in text

    # Quiet, high and far: no invented loudness reasons, and an honest note.
    quiet = {**c, "class": "narrowbody", "type_name": None, "t": "A320", "flight": None, "alt_m": 11000,
             "height_m": 10750, "rate_ms": 0, "distance_km": 8, "slant_km": 13.4, "db": 45.0}
    assert w.reasons(quiet) == []
    text = w.sentence(quiet, T0 + 600, live=True)
    assert "proto" not in text and "kolem tebe přeletělo letadlo typu A320" in text
    assert "nebylo (asi 45 dB)" in text


def test_at_clock():
    now = datetime(2026, 11, 8, 10, 0, tzinfo=PRAGUE).timestamp()
    assert w.at_clock(datetime(2026, 11, 8, 2, 14, tzinfo=PRAGUE).timestamp(), now) == "ve 2:14"
    assert w.at_clock(datetime(2026, 11, 8, 9, 5, tzinfo=PRAGUE).timestamp(), now) == "v 9:05"
    assert w.at_clock(datetime(2026, 11, 7, 23, 40, tzinfo=PRAGUE).timestamp(), now) == "včera ve 23:40"
