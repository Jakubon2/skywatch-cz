"""Heads-up notifications for predicted passes ("Za 20 min tu nejspíš poletí A388 (SIA308)…").

The user opts in per device from the "Kdy tu poletí" card; the device sends its home location, which is stored
here (it lives only in the browser otherwise). A poller listener checks every `check_every_s` seconds and sends
each predicted pass at most once per subscription and day (table pass_alert_sent).
"""

import logging
import sqlite3
import time
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

import notify
import passes
from config import CONFIG
from explain import PRAGUE

log = logging.getLogger("pass_alerts")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pass_alert_subs (
    device_id TEXT PRIMARY KEY,
    label TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    radius_km REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pass_alert_sent (
    device_id TEXT NOT NULL,
    day TEXT NOT NULL,          -- Prague date of the pass
    callsign TEXT NOT NULL,
    usual_time TEXT NOT NULL,   -- a callsign can recur at two times a day
    sent_at REAL NOT NULL,
    PRIMARY KEY (device_id, day, callsign, usual_time)
);
"""


def init(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)


def due(conn: sqlite3.Connection, now: datetime | None = None) -> list[tuple[dict, dict]]:
    """Predictions to announce now, as (subscription, prediction). Marks them sent, so each fires once."""
    cfg = CONFIG["pass_alerts"]
    now = (now or datetime.now(PRAGUE)).astimezone(PRAGUE)
    day = now.date().isoformat()
    out = []
    for sub in conn.execute("SELECT * FROM pass_alert_subs").fetchall():
        sub = dict(sub)
        for p in passes.upcoming(conn, sub["lat"], sub["lon"], sub["radius_km"], cfg["lead_minutes"],
                                 cfg["min_confidence"], now):
            cur = conn.execute(
                "INSERT OR IGNORE INTO pass_alert_sent (device_id, day, callsign, usual_time, sent_at) "
                "VALUES (?, ?, ?, ?, ?)", (sub["device_id"], day, p["callsign"], p["usual_time"], now.timestamp()))
            if cur.rowcount:
                out.append((sub, p))
    conn.execute("DELETE FROM pass_alert_sent WHERE sent_at < ?", (now.timestamp() - 3 * 86400,))
    conn.commit()
    return out


class Checker:
    """Poller listener: runs `due` at most every check_every_s and sends the notifications."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.last = 0.0

    async def __call__(self, poller, new_events):
        cfg = CONFIG["pass_alerts"]
        if not cfg["enabled"] or time.monotonic() - self.last < cfg["check_every_s"]:
            return
        self.last = time.monotonic()
        for sub, p in due(self.conn):
            log.info("pass alert %s for %s", p["callsign"], sub["device_id"][:8])
            await notify.notify("Brzy nad tebou", passes.message_cs(p), tags=["airplane"], url="/",
                                tag=f"pass-{p['callsign']}")


# ---------- API ----------

class Subscription(BaseModel):
    device_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    label: str | None = Field(None, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(15, gt=0, le=100)


def make_router(poller) -> APIRouter:
    """Call once from api.py: creates the tables, registers the listener, returns the routes."""
    conn = poller.db
    init(conn)
    poller.listeners.append(Checker(conn))
    router = APIRouter(prefix="/api/pass-alerts")

    @router.get("/{device_id}")
    def get(device_id: str):
        row = conn.execute("SELECT label FROM pass_alert_subs WHERE device_id = ?", (device_id,)).fetchone()
        return {"enabled": row is not None, "label": row["label"] if row else None,
                "lead_minutes": CONFIG["pass_alerts"]["lead_minutes"]}

    @router.put("")
    def put(s: Subscription):
        # Rounded to ~100 m: the prediction grid is ~22 km anyway, no need to keep an exact address.
        conn.execute(
            "INSERT OR REPLACE INTO pass_alert_subs (device_id, label, lat, lon, radius_km, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (s.device_id, s.label, round(s.lat, 3), round(s.lon, 3), s.radius_km, time.time()))
        conn.commit()
        return get(s.device_id)

    @router.delete("/{device_id}")
    def delete(device_id: str):
        conn.execute("DELETE FROM pass_alert_subs WHERE device_id = ?", (device_id,))
        conn.execute("DELETE FROM pass_alert_sent WHERE device_id = ?", (device_id,))
        conn.commit()
        return {"enabled": False}

    return router
