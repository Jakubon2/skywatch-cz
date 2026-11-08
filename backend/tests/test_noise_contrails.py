import asyncio
import json
from datetime import datetime

import httpx
import pytest

import contrails
import noise
from contrails import PRAGUE

PRAHA = (50.08, 14.43)


def ac(hex="abc123", t="A320", category="A3", lat=50.08, lon=14.43, alt=3000, rate=0, flight="CSA1 "):
    return {"hex": hex, "t": t, "category": category, "lat": lat, "lon": lon,
            "alt_baro": alt, "baro_rate": rate, "flight": flight}


# ---------- noise ----------

def test_level_at_reference_distance_is_reference():
    assert noise.level_db(88, noise.CFG["ref_distance_m"]) == pytest.approx(88)


def test_spherical_spreading_and_absorption_known_value():
    # 10x the distance: -20 dB spreading, absorption over (3050 - 305) m at 1.5 dB/km = -4.1175 dB
    assert noise.level_db(88, 3050) == pytest.approx(88 - 20 - 1.5 * 2.745)


def test_level_decreases_monotonically_with_distance():
    levels = [noise.level_db(90, d) for d in range(100, 30000, 250)]
    assert all(a > b for a, b in zip(levels, levels[1:]))


def test_louder_class_and_phase_and_closer_aircraft():
    def db(**kw):
        return noise.estimate([ac(**kw)], *PRAHA, 20, elev_m=0)["loudest"]["db"]
    assert db(t="A388", category="A5") > db(t="A320") > db(t="AT76", category="A2") > db(t="C172", category="A1")
    assert db(rate=2000, alt=12000) > db(rate=0, alt=12000)  # climb louder than cruise
    assert db(alt=2000) > db(alt=6000) > db(alt=36000)
    assert db(lat=50.08) > db(lat=50.2)


def test_estimate_filters_sorts_and_labels():
    planes = [ac("far", lat=51.5), ac("ground", alt="ground"), ac("unknown", t=None, category=None),
              ac("high", alt=36000), ac("low", alt=2000)]
    res = noise.estimate(planes, *PRAHA, 20)
    assert res["estimate"] is True and "odhad" in res["note"]
    assert [r["hex"] for r in res["aircraft"]] == ["low", "high"]
    assert res["loudest"]["hex"] == "low" and res["loudest"]["phase"] == "approach"
    assert res["aircraft"][1]["phase"] == "cruise"
    assert res["total_db"] >= res["loudest"]["db"]
    assert noise.label_cs(45) == "jako tichá kancelář" and noise.label_cs(65) == "jako rušná ulice"


def test_cruise_jet_overhead_is_quiet_and_low_jet_is_loud():
    high = noise.estimate([ac(alt=36000)], *PRAHA, 20)["loudest"]["db"]
    low = noise.estimate([ac(alt=1500, rate=-700)], *PRAHA, 20)["loudest"]["db"]
    assert 25 < high < 45
    assert 75 < low < 95


def test_empty():
    res = noise.estimate([], *PRAHA, 20)
    assert res["loudest"] is None and res["total_db"] is None and res["aircraft"] == []


# ---------- Schmidt-Appleman ----------

def test_saturation_pressure_reference_values():
    assert contrails.e_sat_water(0) == pytest.approx(611.2, abs=0.5)   # Pa
    assert contrails.e_sat_ice(-40) == pytest.approx(12.84, abs=0.05)


def test_schumann_reference_example():
    # Schumann (1996): kerosene, eta = 0.3, p = 250 hPa -> G ~ 1.67 Pa/K, T_LM ~ -41.8 degC
    g = contrails.mixing_slope(250, eta=0.3)
    assert g == pytest.approx(1.668, abs=0.005)
    t_lm = contrails.threshold_saturated(g)
    assert t_lm == pytest.approx(-41.8, abs=0.1)
    # T_LM is where the mixing line is tangent to the saturation curve: de_w/dT = G
    slope = (contrails.e_sat_water(t_lm + 0.01) - contrails.e_sat_water(t_lm - 0.01)) / 0.02
    assert slope == pytest.approx(g, rel=0.01)
    assert contrails.critical_temp(250, 100, eta=0.3) == pytest.approx(t_lm, abs=0.05)


def test_critical_temperature_behaviour():
    # drier air needs colder temperatures (dry threshold ~ 10 K below the saturated one)
    t0, t50, t100 = (contrails.critical_temp(250, rh) for rh in (0, 50, 100))
    assert t0 < t50 < t100 and 8 < t100 - t0 < 12
    # higher efficiency engines make contrails at warmer temperatures
    assert contrails.critical_temp(250, 50, eta=0.4) > contrails.critical_temp(250, 50, eta=0.3)
    # lower pressure (higher up) -> colder threshold
    assert contrails.critical_temp(200, 50) < contrails.critical_temp(300, 50)


def test_assess_level_states():
    warm = contrails.assess_level(250, -30, 90)
    short = contrails.assess_level(250, -55, 30)
    persistent = contrails.assess_level(250, -55, 70)  # RH_ice ~ 120 %
    assert not warm["forms"] and not warm["persistent"]
    assert short["forms"] and not short["persistent"]
    assert persistent["forms"] and persistent["persistent"] and persistent["rh_ice"] > 100
    assert [contrails.flight_level(p) for p in (300, 250, 200)] == [300, 340, 390]


# ---------- Open-Meteo parsing with mocked HTTP ----------

def meteo(times, t250, rh250, cloud=None):
    n = len(times)
    return {"hourly": {
        "time": times, "cloud_cover": cloud or [10] * n,
        "temperature_300hPa": [-30.0] * n, "relative_humidity_300hPa": [40] * n,
        "temperature_250hPa": t250, "relative_humidity_250hPa": rh250,
        "temperature_200hPa": [-35.0] * n, "relative_humidity_200hPa": [10] * n,
    }}


def test_fetch_and_build_with_mocked_http():
    seen = {}
    data = meteo(["2026-11-08T13:00", "2026-11-08T14:00", "2026-11-08T15:00"],
                 [-40.0, -55.0, -56.0], [30, 75, 80])

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        seen["hourly"] = request.url.params["hourly"]
        return httpx.Response(200, json=data)

    contrails._cache.clear()
    res = asyncio.run(contrails.forecast(50.0812, 14.4311, transport=httpx.MockTransport(handler)))
    assert seen["ua"].startswith("skywatch-cz")
    assert "temperature_250hPa" in seen["hourly"] and "relative_humidity_200hPa" in seen["hourly"]
    assert (res["lat"], res["lon"]) == (50.1, 14.4)
    assert res["estimate"] is True and res["source"] == "Open-Meteo"
    assert [h["state"] for h in res["hours"]] == ["none", "persistent", "persistent"]
    assert res["now"]["levels"][1]["fl"] == 340
    assert "dlouhé čáry" in res["summary"]

    # second call is served from the cache (no HTTP)
    def boom(request):
        raise AssertionError("should be cached")
    again = asyncio.run(contrails.forecast(50.08, 14.43, transport=httpx.MockTransport(boom)))
    assert again is res


def test_parse_skips_missing_values():
    data = meteo(["2026-11-08T13:00", "2026-11-08T14:00"], [None, -55.0], [None, 30])
    data["hourly"]["temperature_300hPa"] = [None, -30.0]
    data["hourly"]["temperature_200hPa"] = [None, -35.0]
    hours = contrails.parse(data)
    assert len(hours) == 1 and hours[0]["state"] == "short"


def test_summary_texts():
    now = datetime(2026, 11, 8, 10, 0, tzinfo=PRAGUE)
    def hours(states, start="2026-11-08T13:00", cover=10):
        base = datetime.fromisoformat(start)
        return [{"time": base.replace(hour=base.hour + i).isoformat(timespec="minutes"),
                 "cloud_cover": cover, "state": s, "levels": []} for i, s in enumerate(states)]
    assert contrails.summary_cs(hours(["none", "persistent", "persistent"]), now) == \
        "Dnes odpoledne budou za letadly dlouhé čáry na obloze, které vydrží."
    assert contrails.summary_cs(hours(["short"], start="2026-11-08T19:00"), now).startswith("Dnes večer se za letadly budou tvořit jen krátké")
    assert "nebudou" in contrails.summary_cs(hours(["none", "none"]), now)
    assert "zataženo" in contrails.summary_cs(hours(["persistent"], cover=95), now)
    assert contrails.summary_cs(hours(["persistent"], start="2026-11-09T09:00"), now).startswith("Zítra dopoledne")
