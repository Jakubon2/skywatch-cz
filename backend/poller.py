"""Keeps the latest snapshot and a rolling per-aircraft track history in memory,
runs the detectors on every update and stores new events."""

import asyncio
import logging
from collections import deque

import db
from adsb import AdsbClient, poll_forever
from config import CONFIG
from detectors import Deduper, load_context, run_all

log = logging.getLogger("poller")


class Poller:
    def __init__(self, db_path=db.DEFAULT_PATH):
        self.history_s = CONFIG["poller"]["history_minutes"] * 60
        self.latest: dict | None = None            # last raw snapshot
        self.history: dict[str, deque] = {}        # hex -> deque of samples (oldest first)

        self.db = db.connect(db_path)
        self.ctx = load_context()
        self.ctx["seen_types"], self.ctx["history_since"] = db.load_seen_types(self.db)
        self.dedup = Deduper(self.ctx["cfg"]["dedup_minutes"])
        # Called after every live snapshot as listener(poller, new_events); sync or async.
        # Feature modules (explanations, alerts, history...) register here instead of editing ingest().
        self.listeners: list = []

    def ingest(self, snapshot: dict) -> list[dict]:
        """Process one snapshot; returns the new (deduplicated, stored) events."""
        now = snapshot["now"] / 1000
        aircraft = [a for a in snapshot.get("ac", []) if "lat" in a and "lon" in a]

        updated = []
        for a in aircraft:
            # Timestamp of the position itself, not of the snapshot.
            sample = {**a, "ts": now - a.get("seen_pos", 0)}
            track = self.history.setdefault(a["hex"], deque())
            if not track or sample["ts"] > track[-1]["ts"]:
                track.append(sample)
                updated.append(a["hex"])

        cutoff = now - self.history_s
        for hex_id in list(self.history):
            track = self.history[hex_id]
            while track and track[0]["ts"] < cutoff:
                track.popleft()
            if not track:
                del self.history[hex_id]

        events = []
        for hex_id in updated:
            if hex_id not in self.history:
                continue
            for e in run_all(list(self.history[hex_id]), self.ctx):
                if self.dedup.allow(e["type"], e["hex"], now):
                    e["id"] = db.insert_event(self.db, e)
                    events.append(e)
                    log.info("EVENT %s %s %s %s", e["type"], e["callsign"] or e["hex"], e["aircraft_type"], e["data"])

        # Remember which types fly here, after detection so a rare type still counts as rare.
        types = {a["t"] for a in aircraft if a.get("t")}
        db.touch_types(self.db, types, now)
        for t in types:
            self.ctx["seen_types"][t] = now
        if self.ctx["history_since"] is None:
            self.ctx["history_since"] = now

        self.latest = {"now": snapshot["now"], "ac": aircraft}
        log.info(
            "snapshot: %d aircraft with position (%d total), %d tracks, %d new events",
            len(aircraft), len(snapshot.get("ac", [])), len(self.history), len(events),
        )
        return events

    async def _on_snapshot(self, snapshot: dict):
        events = self.ingest(snapshot)
        for listener in self.listeners:
            try:
                result = listener(self, events)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("listener %s failed", getattr(listener, "__name__", listener))

    async def run(self):
        client = AdsbClient()
        try:
            await poll_forever(client, self._on_snapshot)
        finally:
            await client.close()
