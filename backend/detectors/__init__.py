"""Detectors are pure functions: (track, ctx) -> {"type", "data"} or None.

`track` is one aircraft's samples (readsb dicts + "ts"), oldest first.
`ctx` holds config and shared context, see `load_context()`.
"""

from datetime import datetime, timezone

import yaml

from airports import airport
from config import ROOT

from . import emergency, go_around, heli_orbit, holding, interesting, rapid_descent, return_or_diversion

DETECTORS = [
    emergency.detect, holding.detect, go_around.detect, interesting.detect,
    rapid_descent.detect, return_or_diversion.detect, heli_orbit.detect,
]


def load_context() -> dict:
    with open(ROOT / "config" / "detectors.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(ROOT / "config" / cfg["interesting"]["types_file"], encoding="utf-8") as f:
        types = yaml.safe_load(f)
    return {
        "cfg": cfg,
        # [{ident, name, name_cs, lat, lon, elevation_ft, runways}], from OurAirports + Czech name from config
        "airports": [{**airport(ident), "name_cs": name} for ident, name in cfg["airports"].items()],
        "interesting_types": types,
        "seen_types": {},       # type -> last seen ts, filled by the caller
        "history_since": None,  # ts of the oldest seen_types record
    }


def run_all(track: list[dict], ctx: dict) -> list[dict]:
    """Run every detector and turn hits into full event dicts (shape of the `events` table)."""
    if not track:
        return []
    last = track[-1]
    events = []
    for detect in DETECTORS:
        hit = detect(track, ctx)
        if hit:
            alt = last.get("alt_baro")
            events.append({
                "type": hit["type"],
                "hex": last["hex"],
                "callsign": (last.get("flight") or "").strip() or None,
                "aircraft_type": last.get("t"),
                "lat": last["lat"],
                "lon": last["lon"],
                "alt_ft": alt if isinstance(alt, (int, float)) else 0,
                "started_at": datetime.fromtimestamp(last["ts"], timezone.utc).isoformat(timespec="seconds"),
                "data": hit["data"],
            })
    return events


class Deduper:
    """Lets the same event type for the same aircraft through at most once per window."""

    def __init__(self, minutes: float):
        self.window_s = minutes * 60
        self.last: dict[tuple[str, str], float] = {}

    def allow(self, event_type: str, hex_id: str, ts: float) -> bool:
        key = (event_type, hex_id)
        prev = self.last.get(key)
        if prev is not None and ts - prev < self.window_s:
            return False
        self.last[key] = ts
        return True
