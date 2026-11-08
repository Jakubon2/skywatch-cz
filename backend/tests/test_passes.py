from datetime import datetime, timedelta

import pytest

import db
import passes
from explain import PRAGUE

NOW = datetime(2026, 11, 8, 13, 0, tzinfo=PRAGUE)


def snap(dt, ac):
    return {"now": dt.timestamp() * 1000, "ac": ac}


def a380(lat=50.0, lon=14.5, flight="SIA308"):
    return {"hex": "76cdb1", "flight": flight, "t": "A388", "lat": lat, "lon": lon, "alt_baro": 40000}


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    passes.init(c)
    return c


def record_days(conn, days, minute_jitter=(0, 5, -4, 8, 2, -6)):
    rec = passes.PassRecorder(conn)
    for d in range(1, days + 1):
        base = (NOW - timedelta(days=d)).replace(hour=14, minute=0)
        rec.record(snap(base.replace(hour=13), []))   # recorder ran in the 13:00 hour too
        dt = base + timedelta(minutes=minute_jitter[d % len(minute_jitter)])
        rec.record(snap(dt, [a380()]))
        rec.record(snap(dt + timedelta(minutes=3), [a380()]))   # same cell: first visit wins
        rec.record(snap(dt, [a380(lat=49.0, lon=17.0, flight="RANDOM1")]))  # far away


def test_needs_history(conn):
    record_days(conn, 2)
    r = passes.predict(conn, 50.0, 14.5, 10, 3, NOW)
    assert r["predictions"] == [] and "Málo dat" in r["reason"]


def test_recurring_flight_predicted(conn):
    record_days(conn, 5)
    r = passes.predict(conn, 50.05, 14.55, 10, 3, NOW)
    assert r["reason"] is None and r["history_days"] == 5
    (p,) = r["predictions"]
    assert p["callsign"] == "SIA308" and p["type"] == "A388"
    assert p["days_seen"] == 5 and p["days_observed"] == 5 and p["confidence"] == 1.0
    assert 55 <= p["expected_in_min"] <= 70
    assert "A388 (SIA308)" in passes.message_cs(p)
    # Outside the window / far away -> nothing
    assert passes.predict(conn, 50.0, 14.5, 10, 0.5, NOW)["predictions"] == []
    assert passes.predict(conn, 48.5, 12.0, 10, 3, NOW)["predictions"] == []
    assert passes.upcoming(conn, 50.0, 14.5, 10, 90, now=NOW)[0]["callsign"] == "SIA308"


def test_one_row_per_cell_day(conn):
    record_days(conn, 3)
    assert conn.execute("SELECT COUNT(*) FROM passes WHERE callsign='SIA308'").fetchone()[0] == 3


def test_cluster_midnight_wrap():
    assert sorted(passes._cluster([1430, 5, 10, 700], 45)) == [5, 10, 1430]


def test_downtime_does_not_count_against_flight(conn):
    record_days(conn, 5)
    # Day 6: the recorder ran at 14:xx, but the flight did not come -> one miss.
    rec = passes.PassRecorder(conn)
    rec.record(snap((NOW - timedelta(days=6)).replace(hour=14, minute=10), []))
    # Day 7: the recorder was down all day -> not counted at all.
    p = passes.predict(conn, 50.0, 14.5, 10, 3, NOW)["predictions"][0]
    assert p["days_seen"] == 5 and p["days_observed"] == 6 and p["confidence"] == 0.83
