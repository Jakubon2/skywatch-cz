"""Web Push: subscription storage, fan-out, expired-subscription cleanup (pywebpush mocked)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pywebpush import WebPushException

import notify
import push
from poller import Poller


def sub(n):
    return {"endpoint": f"https://push.example/{n}", "keys": {"p256dh": f"p{n}", "auth": f"a{n}"}}


@pytest.fixture
def sent(monkeypatch):
    """Fake pywebpush.webpush; endpoints in `calls.gone` fail with the given HTTP status."""
    class Calls(list):
        gone: dict = {}

    calls = Calls()

    def fake_webpush(info, data, **kw):
        calls.append((info["endpoint"], json.loads(data), kw))
        status = calls.gone.get(info["endpoint"])
        if status:
            raise WebPushException("gone", response=SimpleNamespace(status_code=status, text=""))

    monkeypatch.setattr(push, "webpush", fake_webpush)
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")
    return calls


@pytest.fixture
def poller():
    return Poller(db_path=":memory:")


@pytest.fixture
def client(poller):
    app = FastAPI()
    app.include_router(push.make_router(poller))
    return TestClient(app)


def count(poller):
    return poller.db.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


def test_key_and_subscription_storage(client, poller, sent):
    assert client.get("/api/push/key").json() == {"key": "pub"}
    assert client.post("/api/push/subscribe", json=sub(1)).status_code == 200
    # Re-subscribing the same endpoint updates keys instead of duplicating.
    again = {**sub(1), "keys": {"p256dh": "new", "auth": "new"}}
    assert client.post("/api/push/subscribe", json=again).status_code == 200
    client.post("/api/push/subscribe", json=sub(2))
    assert count(poller) == 2
    row = poller.db.execute("SELECT p256dh FROM push_subscriptions WHERE endpoint = ?", (sub(1)["endpoint"],)).fetchone()
    assert row["p256dh"] == "new"

    client.post("/api/push/unsubscribe", json={"endpoint": sub(1)["endpoint"]})
    assert count(poller) == 1


def test_rejects_non_https_endpoint(client, sent):
    bad = {**sub(1), "endpoint": "http://evil.local/x"}
    assert client.post("/api/push/subscribe", json=bad).status_code == 422


def test_key_unavailable_without_vapid(client, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert client.get("/api/push/key").status_code == 503


def test_fan_out_and_expired_cleanup(client, poller, sent):
    for n in (1, 2, 3):
        client.post("/api/push/subscribe", json=sub(n))
    sent.gone = {sub(2)["endpoint"]: 410, sub(3)["endpoint"]: 404}

    ok = asyncio.run(push.send_push("Titulek", "Zpráva", url="/?hex=abc123", tag="t1"))

    assert ok == 1
    assert {c[0] for c in sent} == {sub(n)["endpoint"] for n in (1, 2, 3)}
    assert sent[0][1] == {"title": "Titulek", "body": "Zpráva", "url": "/?hex=abc123", "tag": "t1"}
    assert sent[0][2]["vapid_claims"] == {"sub": "mailto:test@example.com"}
    # 404/410 = subscription gone for good: removed. Others stay.
    rows = [r[0] for r in poller.db.execute("SELECT endpoint FROM push_subscriptions")]
    assert rows == [sub(1)["endpoint"]]


def test_temporary_failure_keeps_subscription(client, poller, sent):
    client.post("/api/push/subscribe", json=sub(1))
    sent.gone = {sub(1)["endpoint"]: 500}
    assert asyncio.run(push.send_push("x", "y")) == 0
    assert count(poller) == 1


def test_test_endpoint_targets_only_caller(client, sent):
    client.post("/api/push/subscribe", json=sub(1))
    client.post("/api/push/subscribe", json=sub(2))
    r = client.post("/api/push/test", json={"endpoint": sub(2)["endpoint"]})
    assert r.status_code == 200
    assert [c[0] for c in sent] == [sub(2)["endpoint"]]
    assert client.post("/api/push/test", json={"endpoint": "https://push.example/unknown"}).status_code == 404


def test_emergency_listener(client, sent):
    client.post("/api/push/subscribe", json=sub(1))
    events = [
        {"id": 7, "type": "emergency", "hex": "abc123", "callsign": "CSA123", "aircraft_type": "A320",
         "data": {"squawk": "7500", "unverified": True}},
        {"id": 8, "type": "holding", "hex": "def456", "callsign": "X", "aircraft_type": None, "data": {}},
    ]
    asyncio.run(push.on_events(None, events))
    assert len(sent) == 1
    msg = sent[0][1]
    assert msg["url"] == "/?event=7" and msg["tag"] == "event-7"
    assert "CSA123" in msg["body"] and "7500" in msg["body"] and "neověřeno" in msg["body"]


def test_notify_sends_both_channels(monkeypatch):
    got = []

    async def fake_ntfy(title, message, **kw):
        got.append(("ntfy", kw.get("click")))
        return True

    async def fake_push(title, body, url=None, tag=None):
        got.append(("push", url))
        raise RuntimeError("push down")  # one channel failing must not stop the other

    monkeypatch.setattr(notify, "send_ntfy", fake_ntfy)
    monkeypatch.setattr(push, "send_push", fake_push)
    asyncio.run(notify.notify("t", "m", url="/?hex=abc"))
    assert sorted(got) == [("ntfy", None), ("push", "/?hex=abc")]
