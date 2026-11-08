from datetime import timedelta

import pytest

import db
import pass_alerts
import passes
from tests.test_passes import NOW, record_days

SOON = NOW.replace(hour=13, minute=45)  # SIA308 usually passes ~14:00


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    passes.init(c)
    pass_alerts.init(c)
    record_days(c, 5)
    return c


def subscribe(conn, device_id="dev-aaaaaaaa"):
    conn.execute("INSERT INTO pass_alert_subs VALUES (?, 'Doma', 50.0, 14.5, 10, 0)", (device_id,))


def test_not_due_outside_lead_time(conn):
    subscribe(conn)
    assert pass_alerts.due(conn, NOW) == []  # 13:00, pass ~60 min away, lead 20 min


def test_fires_once_per_pass(conn):
    subscribe(conn)
    first = pass_alerts.due(conn, SOON)
    assert [p["callsign"] for _, p in first] == ["SIA308"]
    assert pass_alerts.due(conn, SOON) == []
    assert pass_alerts.due(conn, SOON + timedelta(minutes=5)) == []


def test_fires_again_next_day(conn):
    subscribe(conn)
    assert pass_alerts.due(conn, SOON)
    assert [p["callsign"] for _, p in pass_alerts.due(conn, SOON + timedelta(days=1))] == ["SIA308"]


def test_dedup_is_per_device(conn):
    subscribe(conn, "dev-aaaaaaaa")
    subscribe(conn, "dev-bbbbbbbb")
    assert sorted(s["device_id"] for s, _ in pass_alerts.due(conn, SOON)) == ["dev-aaaaaaaa", "dev-bbbbbbbb"]
    assert pass_alerts.due(conn, SOON) == []


def test_no_subscriptions_no_alerts(conn):
    assert pass_alerts.due(conn, SOON) == []
