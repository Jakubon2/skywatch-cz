"""Detectors on synthetic tracks. Real config thresholds, fake airport (no network)."""

from math import cos, radians, sin

import pytest
import yaml

from config import ROOT
from detectors import (Deduper, emergency, go_around, heli_orbit, holding, interesting, rapid_descent,
                       return_or_diversion, run_all)

APT = {"ident": "LKPR", "name_cs": "Letiště Václava Havla Praha", "lat": 50.1009, "lon": 14.2599,
       "elevation_ft": 1247, "runways": []}
BRNO = {"ident": "LKTB", "name_cs": "Letiště Brno-Tuřany", "lat": 49.1513, "lon": 16.6940,
        "elevation_ft": 778, "runways": []}
T0 = 1_800_000_000.0
NM_LAT = 1 / 60  # degrees of latitude per NM


@pytest.fixture
def ctx():
    with open(ROOT / "config" / "detectors.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return {
        "cfg": cfg,
        "airports": [APT, BRNO],
        "interesting_types": {"A124": "Antonov An-124 Ruslan"},
        "seen_types": {},
        "history_since": None,
    }


def sample(i, lat, lon, alt=10000, track=90.0, rate=0, **extra):
    return {"hex": "abc123", "flight": "TEST1  ", "t": "B738", "category": "A3", "ts": T0 + i * 10,
            "lat": lat, "lon": lon, "alt_baro": alt, "track": track, "baro_rate": rate,
            "squawk": "1000", "emergency": "none", **extra}


def straight(n=60, alt=35000):
    """Eastbound cruise, ~450 kt."""
    return [sample(i, 49.8, 14.0 + i * 0.035, alt=alt) for i in range(n)]


def circle(n=60, radius_nm=3, period=24, alt=8000):
    """Orbit: one full turn every `period` samples (4 min at 10 s)."""
    out = []
    for i in range(n):
        ang = 2 * 3.14159 * i / period
        lat = 49.9 + radius_nm * NM_LAT * cos(ang)
        lon = 14.6 + radius_nm * NM_LAT * sin(ang) / cos(radians(49.9))
        out.append(sample(i, lat, lon, alt=alt + (50 if i % 2 else -50), track=(i * 360 / period + 90) % 360))
    return out


def approach(alts_rates, apt=APT):
    """Samples walking towards the airport from 5 NM east, with given (alt, baro_rate) pairs."""
    n = len(alts_rates)
    return [
        sample(i, apt["lat"], apt["lon"] + (5 - 5 * i / n) * NM_LAT / cos(radians(apt["lat"])), alt=a, rate=r, track=270)
        for i, (a, r) in enumerate(alts_rates)
    ]


# ---------- emergency ----------

def test_emergency_squawk_7700(ctx):
    track = straight(5)
    for s in track[-2:]:
        s["squawk"] = "7700"
    hit = emergency.detect(track, ctx)
    assert hit["type"] == "emergency" and hit["data"]["squawk"] == "7700"
    assert hit["data"]["unverified"] is False


def test_emergency_7500_marked_unverified(ctx):
    track = straight(5)
    for s in track[-2:]:
        s["squawk"] = "7500"
    assert emergency.detect(track, ctx)["data"]["unverified"] is True


def test_emergency_single_sample_glitch_ignored(ctx):
    track = straight(5)
    track[-1]["squawk"] = "7700"
    assert emergency.detect(track, ctx) is None


def test_emergency_status_field(ctx):
    track = straight(5)
    for s in track[-2:]:
        s["emergency"] = "general"
    assert emergency.detect(track, ctx)["data"]["emergency"] == "general"


# ---------- holding ----------

def test_holding_orbit_detected(ctx):
    hit = holding.detect(circle(), ctx)
    assert hit["type"] == "holding"
    assert hit["data"]["turned_deg"] >= 330


def test_holding_straight_flight_ignored(ctx):
    assert holding.detect(straight(), ctx) is None


def test_holding_too_low_ignored(ctx):
    assert holding.detect(circle(alt=2500), ctx) is None


def test_holding_climbing_orbit_ignored(ctx):
    track = circle()
    for i, s in enumerate(track):
        s["alt_baro"] = 6000 + i * 100   # climbs 6000 ft in the window
    assert holding.detect(track, ctx) is None


def test_holding_needs_enough_history(ctx):
    assert holding.detect(circle(n=20), ctx) is None


def test_holding_single_turn_ignored(ctx):
    # Straight, one 90 degree turn, straight again: a normal route change.
    track = straight(48)
    for s in track[24:]:
        s["track"] = 180.0
    assert holding.detect(track, ctx) is None


# ---------- go-around ----------

def test_go_around_detected(ctx):
    profile = [(3500, -700), (3000, -700), (2600, -700), (2200, -600), (1900, -400),
               (2100, 1200), (2500, 1500), (2900, 1500), (3300, 1500)]
    hit = go_around.detect(approach(profile), ctx)
    assert hit["type"] == "go_around"
    assert hit["data"]["probable"] is True
    assert hit["data"]["lowest_alt_ft"] == 1900
    assert hit["data"]["airport"] == "LKPR"


def test_go_around_at_brno(ctx):
    # Same profile shifted by Brno's lower elevation (778 ft).
    profile = [(3000, -700), (2500, -700), (2100, -700), (1700, -600), (1400, -400),
               (1600, 1200), (2000, 1500), (2400, 1500), (2800, 1500)]
    hit = go_around.detect(approach(profile, apt=BRNO), ctx)
    assert hit["data"]["airport"] == "LKTB"
    assert hit["data"]["airport_name"] == "Letiště Brno-Tuřany"


def test_normal_landing_ignored(ctx):
    profile = [(3500, -700), (3000, -700), (2500, -700), (2000, -700), (1600, -600), ("ground", 0), ("ground", 0)]
    assert go_around.detect(approach(profile), ctx) is None


def test_touch_and_go_ignored(ctx):
    profile = [(3000, -700), (2200, -700), (1500, -600), ("ground", 0), (1800, 1500), (2300, 1500), (2800, 1500)]
    assert go_around.detect(approach(profile), ctx) is None


def test_go_around_data_gap_ignored(ctx):
    # 40 s without data while low may hide a touchdown (light aircraft at LKMT in the recording).
    profile = [(3500, -700), (3000, -700), (2600, -700), (2200, -600), (1900, -400),
               (2100, 1200), (2500, 1500), (2900, 1500), (3300, 1500)]
    track = approach(profile)
    for s in track[5:]:
        s["ts"] += 40
    assert go_around.detect(track, ctx) is None


def test_departure_ignored(ctx):
    profile = [("ground", 0), (1600, 2000), (2200, 2500), (2900, 2500), (3600, 2500)]
    assert go_around.detect(approach(profile), ctx) is None


def test_go_around_far_from_airport_ignored(ctx):
    profile = [(3500, -700), (3000, -700), (2200, -600), (1900, -400), (2100, 1200), (2500, 1500), (2900, 1500)]
    track = approach(profile)
    for s in track:
        s["lon"] += 0.5   # ~19 NM east
    assert go_around.detect(track, ctx) is None


def test_level_off_on_high_approach_ignored(ctx):
    # Step-down then climb, but never low: the lowest point is 5000 ft (~3750 AGL).
    profile = [(6000, -700), (5500, -700), (5000, -500), (5400, 1200), (5900, 1500), (6400, 1500)]
    assert go_around.detect(approach(profile), ctx) is None


# ---------- interesting ----------

def test_interesting_listed_type(ctx):
    track = straight(3)
    track[-1]["t"] = "A124"
    hit = interesting.detect(track, ctx)
    assert hit["data"]["reasons"] == ["listed_type"]
    assert hit["data"]["type_name"] == "Antonov An-124 Ruslan"


def test_interesting_military(ctx):
    track = straight(3)
    track[-1]["dbFlags"] = 1
    assert interesting.detect(track, ctx)["data"]["reasons"] == ["military"]


def test_ordinary_aircraft_ignored(ctx):
    assert interesting.detect(straight(3), ctx) is None


def test_rare_type_needs_history(ctx):
    track = straight(3)
    ctx["history_since"] = T0 - 5 * 86400   # only 5 days of history
    assert interesting.detect(track, ctx) is None


def test_rare_type_after_enough_history(ctx):
    track = straight(3)
    ctx["history_since"] = T0 - 60 * 86400
    ctx["seen_types"] = {"B738": T0 - 45 * 86400}   # last B738 45 days ago
    assert interesting.detect(track, ctx)["data"]["reasons"] == ["rare_type"]
    ctx["seen_types"] = {"B738": T0 - 86400}
    assert interesting.detect(track, ctx) is None


# ---------- run_all + dedup ----------

def test_run_all_builds_event(ctx):
    track = straight(5)
    for s in track[-2:]:
        s["squawk"] = "7700"
    [event] = run_all(track, ctx)
    assert event["type"] == "emergency"
    assert event["hex"] == "abc123" and event["callsign"] == "TEST1"
    assert event["started_at"].endswith("+00:00")


def test_dedup_window():
    d = Deduper(30)
    assert d.allow("holding", "abc", T0)
    assert not d.allow("holding", "abc", T0 + 600)
    assert d.allow("go_around", "abc", T0 + 600)
    assert d.allow("holding", "abc", T0 + 1801)


def test_holding_light_aircraft_ignored(ctx):
    track = circle()
    for s in track:
        s["category"] = "A1"   # Cessna circling for sightseeing is not a holding
    assert holding.detect(track, ctx) is None


def fly(lat, lon, legs, gs_kt=300, **extra):
    """Integrate a path. legs: [(samples, heading_start, heading_end, alt_start, alt_end)], 10 s per sample."""
    out, i = [], 0
    step_nm = gs_kt * 10 / 3600
    for n, h0, h1, a0, a1 in legs:
        turn = (h1 - h0 + 180) % 360 - 180 if h1 != h0 else 0
        for k in range(n):
            h = (h0 + turn * k / max(n - 1, 1)) % 360
            lat += step_nm * cos(radians(h)) * NM_LAT
            lon += step_nm * sin(radians(h)) * NM_LAT / cos(radians(lat))
            alt = round(a0 + (a1 - a0) * k / max(n - 1, 1))
            out.append(sample(i, lat, lon, alt=alt, track=h, gs=gs_kt, **extra))
            i += 1
    return out


# ---------- rapid descent ----------

def descent(rate_fpm, start=35000, cruise=12, n=14, **extra):
    """Cruise, then descend at rate_fpm with matching altitudes (10 s samples)."""
    track = [sample(i, 49.8, 14.0 + i * 0.01, alt=start, **extra) for i in range(cruise)]
    for k in range(1, n + 1):
        track.append(sample(cruise + k, 49.8, 14.0 + (cruise + k) * 0.01,
                            alt=round(start + rate_fpm * k / 6), rate=rate_fpm, **extra))
    return track


def test_rapid_descent_detected(ctx):
    hit = rapid_descent.detect(descent(-6000), ctx)
    assert hit["type"] == "rapid_descent"
    assert hit["data"]["start_alt_ft"] == 35000
    assert hit["data"]["loss_ft"] >= 8000


def test_normal_descent_ignored(ctx):
    assert rapid_descent.detect(descent(-2500, n=40), ctx) is None


def test_rapid_descent_needs_large_loss(ctx):
    assert rapid_descent.detect(descent(-6000, n=5), ctx) is None   # only ~5000 ft so far


def test_rapid_descent_from_low_altitude_ignored(ctx):
    assert rapid_descent.detect(descent(-6000, start=16000), ctx) is None


def test_rapid_descent_garbage_baro_rate_ignored(ctx):
    # baro_rate says -50 000 fpm but the altitude doesn't move (seen in the recording).
    track = straight(30)
    for s in track[-5:]:
        s["baro_rate"] = -50000
    assert rapid_descent.detect(track, ctx) is None


def test_rapid_descent_fighter_ignored(ctx):
    assert rapid_descent.detect(descent(-8000, category="A6"), ctx) is None


# ---------- return or diversion ----------

def turn_back(alt_before=15000, alt_after=11000, lat=APT["lat"], lon=APT["lon"] + 0.5, before_loss=0, **extra):
    """Eastbound from ~20 NM east of LKPR, 180 degree turn, back west toward LKPR while descending."""
    turn_alt = alt_before - before_loss
    return fly(lat, lon, [(24, 90, 90, alt_before, turn_alt),
                          (6, 90, 270, turn_alt, turn_alt),
                          (24, 270, 270, alt_before, alt_after)], **extra)


def test_return_detected(ctx):
    hit = return_or_diversion.detect(turn_back(), ctx)
    assert hit["type"] == "return_or_diversion"
    assert hit["data"]["probable"] is True
    assert hit["data"]["airport"] == "LKPR"
    assert hit["data"]["reversal_deg"] >= 150


def test_downwind_to_final_ignored(ctx):
    # Arrival: downwind leg and final are opposite, but low. Not a return.
    assert return_or_diversion.detect(turn_back(alt_before=4000, alt_after=2500), ctx) is None


def test_descending_high_downwind_ignored(ctx):
    # Arrival descending through FL100 on a long downwind, then turning onto final (seen in the recording).
    assert return_or_diversion.detect(turn_back(alt_before=12000, before_loss=2500, alt_after=6000), ctx) is None


def test_turn_back_level_ignored(ctx):
    assert return_or_diversion.detect(turn_back(alt_after=15000), ctx) is None


def test_normal_turn_ignored(ctx):
    track = fly(APT["lat"], APT["lon"] + 0.5, [(24, 90, 90, 15000, 15000), (6, 90, 180, 15000, 15000),
                                                (24, 180, 180, 15000, 11000)])
    assert return_or_diversion.detect(track, ctx) is None


def test_turn_back_away_from_airports_ignored(ctx):
    # Same manoeuvre over Bavaria, >80 NM from any configured airport.
    assert return_or_diversion.detect(turn_back(lat=48.5, lon=11.5), ctx) is None


def test_turn_back_light_aircraft_ignored(ctx):
    assert return_or_diversion.detect(turn_back(category="A1"), ctx) is None


def test_turn_back_needs_enough_history(ctx):
    assert return_or_diversion.detect(turn_back()[-30:], ctx) is None


# ---------- helicopter orbit ----------

def heli_circle(n=40, radius_nm=0.3, period=9, alt=1500, gs=70, **extra):
    """Tight orbit, one turn every 90 s."""
    fields = {"category": "A7", "flight": "KRYS12 ", "t": "EC35", "gs": gs, **extra}
    out = []
    for i in range(n):
        ang = 2 * 3.14159 * i / period
        lat = 50.0 + radius_nm * NM_LAT * cos(ang)
        lon = 15.0 + radius_nm * NM_LAT * sin(ang) / cos(radians(50.0))
        out.append(sample(i, lat, lon, alt=alt, track=(i * 360 / period + 90) % 360, **fields))
    return out


def test_heli_orbit_detected(ctx):
    hit = heli_orbit.detect(heli_circle(), ctx)
    assert hit["type"] == "heli_orbit"
    assert hit["data"]["turned_deg"] >= 540


def test_heli_orbit_callsign_without_category(ctx):
    assert heli_orbit.detect(heli_circle(category=None), ctx)["type"] == "heli_orbit"


def test_heli_orbit_light_aircraft_ignored(ctx):
    # A Cessna circling over a town: not a rotorcraft.
    assert heli_orbit.detect(heli_circle(category="A1", flight="OKABC  "), ctx) is None


def test_heli_orbit_unknown_callsign_without_category_ignored(ctx):
    assert heli_orbit.detect(heli_circle(category=None, flight="CPA216  "), ctx) is None


def test_heli_orbit_fast_a7_ignored(ctx):
    # Airliners sometimes wrongly report A7; a fast one is not a helicopter.
    assert heli_orbit.detect(heli_circle(gs=250), ctx) is None


def test_heli_straight_flight_ignored(ctx):
    track = fly(50.0, 15.0, [(40, 90, 90, 1500, 1500)], gs_kt=100, category="A7")
    assert heli_orbit.detect(track, ctx) is None


def test_heli_orbit_too_high_ignored(ctx):
    assert heli_orbit.detect(heli_circle(alt=6000), ctx) is None


def test_heli_hover_noise_ignored(ctx):
    # Hovering: track jumps around but gs ~ 0, that's not circling.
    track = heli_circle(gs=3)
    assert heli_orbit.detect(track, ctx) is None


def test_heli_orbit_too_short_ignored(ctx):
    assert heli_orbit.detect(heli_circle(n=20), ctx) is None
