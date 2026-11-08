"""Event feed: explains new events in the background and pushes updates to SSE subscribers."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from explain import explain, summarize_track
from metar import get_metar

log = logging.getLogger("feed")

_subscribers: set[asyncio.Queue] = set()
_tasks: set[asyncio.Task] = set()   # keep references so background tasks aren't garbage-collected


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


def publish(kind: str, payload: dict):
    """Send {"kind", ...payload} to every SSE client; slow clients drop messages instead of blocking."""
    msg = {"kind": kind, **payload}
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def row_to_event(row) -> dict:
    e = dict(row)
    e["data"] = json.loads(e.pop("data_json") or "{}")
    return e


def list_events(conn, limit: int = 50, before_id: int | None = None, q: str | None = None,
                types: list[str] | None = None, since: str | None = None, until: str | None = None) -> list[dict]:
    """Newest first. `q` searches callsign, type, registration and the explanation text."""
    where, args = [], []
    if before_id:
        where.append("id < ?"); args.append(before_id)
    if q:
        like = f"%{q.strip()}%"
        where.append("(callsign LIKE ? OR aircraft_type LIKE ? OR hex LIKE ? OR data_json LIKE ? OR explanation LIKE ?)")
        args += [like] * 5
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})"); args += types
    if since:
        where.append("started_at >= ?"); args.append(since)
    if until:
        where.append("started_at < ?"); args.append(until)
    sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "")
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    return [row_to_event(r) for r in rows]


def get_event(conn, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return row_to_event(row) if row else None


async def _explain_and_store(poller, event: dict):
    track = list(poller.history.get(event["hex"], []))
    text = await explain(event, summarize_track(track), await get_metar())
    if not text:
        return
    explained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    poller.db.execute(
        "UPDATE events SET explanation = ?, explained_at = ? WHERE id = ?",
        (text, explained_at, event["id"]),
    )
    poller.db.commit()
    publish("explanation", {"id": event["id"], "explanation": text, "explained_at": explained_at})


def on_events(poller, events: list[dict]):
    """Poller listener: announce each new event at once, explain it in the background."""
    for e in events:
        publish("event", {"event": {**e, "explanation": None, "explained_at": None}})
        task = asyncio.create_task(_explain_and_store(poller, e))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
