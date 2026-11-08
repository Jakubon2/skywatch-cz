"""Web Push notifications to the installed PWA (alongside ntfy, see notify.py).

Keys: VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT in .env (generate with vapid_keys.py).
pywebpush does the payload encryption (RFC 8291) and VAPID signing; doing that by hand isn't simpler.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush

import config  # noqa: F401  (loads .env)

log = logging.getLogger("push")

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
  endpoint TEXT PRIMARY KEY,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

_db = None  # the poller's sqlite connection, set by make_router()


def _vapid() -> tuple[str, str] | None:
    key, subject = os.getenv("VAPID_PRIVATE_KEY"), os.getenv("VAPID_SUBJECT")
    return (key, subject) if key and subject else None


def _send_one(sub, payload: str, vapid: tuple[str, str]) -> int | None:
    """Blocking send. Returns the push service's error status, or None on success."""
    info = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}
    try:
        webpush(info, payload, vapid_private_key=vapid[0], vapid_claims={"sub": vapid[1]}, ttl=3600, timeout=10)
        return None
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        log.warning("push to %s… failed: %s", sub["endpoint"][:40], status or e)
        return status or 0
    except Exception as e:  # network errors etc. must never break the poller
        log.warning("push to %s… failed: %s", sub["endpoint"][:40], e)
        return 0


async def send_push(title: str, body: str, url: str | None = None, tag: str | None = None,
                    endpoint: str | None = None) -> int:
    """Send to every subscription (or only `endpoint`). Removes expired ones. Returns how many succeeded."""
    vapid = _vapid()
    if _db is None or not vapid:
        log.info("Web Push not configured, skipping: %s", title)
        return 0
    if endpoint:
        subs = _db.execute("SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchall()
    else:
        subs = _db.execute("SELECT * FROM push_subscriptions").fetchall()
    if not subs:
        return 0

    payload = json.dumps({"title": title, "body": body, "url": url or "/", "tag": tag}, ensure_ascii=False)
    results = await asyncio.gather(*(asyncio.to_thread(_send_one, s, payload, vapid) for s in subs))

    expired = [s["endpoint"] for s, status in zip(subs, results) if status in (404, 410)]
    if expired:
        _db.executemany("DELETE FROM push_subscriptions WHERE endpoint = ?", [(e,) for e in expired])
        _db.commit()
        log.info("removed %d expired push subscription(s)", len(expired))
    return sum(1 for r in results if r is None)


# --- Emergency events -> push ---

SQUAWK_TEXT = {
    "7700": "squawk 7700 – nouze",
    "7600": "squawk 7600 – ztráta rádiového spojení",
    "7500": "squawk 7500 – protiprávní zásah (neověřeno, často jde o omyl)",
}


async def on_events(poller, events: list[dict]):
    """Poller listener: push every new emergency event."""
    for e in events:
        if e["type"] != "emergency":
            continue
        data = e.get("data") or {}
        what = SQUAWK_TEXT.get(data.get("squawk")) or f"nouzový stav: {data.get('emergency') or 'neznámý'}"
        if data.get("unverified") and "neověřeno" not in what:
            what += " (neověřeno)"
        name = e.get("callsign") or e["hex"]
        body = ", ".join(filter(None, [name, e.get("aircraft_type"), what]))
        await send_push("Skywatch: nouzová situace", body, url=f"/?event={e['id']}", tag=f"event-{e['id']}")


# --- API ---

class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class Subscription(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    keys: Keys


class Endpoint(BaseModel):
    endpoint: str = Field(max_length=1000)


def make_router(poller) -> APIRouter:
    global _db
    _db = poller.db
    _db.executescript(SCHEMA)
    router = APIRouter(prefix="/api/push")

    @router.get("/key")
    def key():
        public = os.getenv("VAPID_PUBLIC_KEY")
        if not public or not _vapid():
            raise HTTPException(503, "Web Push není na serveru nastavený (chybí VAPID klíče).")
        return {"key": public}

    @router.post("/subscribe")
    def subscribe(sub: Subscription):
        _db.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth",
            (sub.endpoint, sub.keys.p256dh, sub.keys.auth, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        _db.commit()
        return {"ok": True}

    @router.post("/unsubscribe")
    def unsubscribe(req: Endpoint):
        _db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (req.endpoint,))
        _db.commit()
        return {"ok": True}

    @router.post("/test")
    async def test(req: Endpoint):
        """Test notification for the caller's own subscription only."""
        if not _db.execute("SELECT 1 FROM push_subscriptions WHERE endpoint = ?", (req.endpoint,)).fetchone():
            raise HTTPException(404, "Toto zařízení nemá zapnutá upozornění.")
        sent = await send_push("Skywatch: zkušební upozornění", "Upozornění z aplikace fungují.",
                               url="/", tag="test", endpoint=req.endpoint)
        if not sent:
            raise HTTPException(502, "Upozornění se nepodařilo odeslat.")
        return {"ok": True}

    return router
