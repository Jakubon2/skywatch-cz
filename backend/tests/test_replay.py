"""Replay recorded fixtures: detectors must not flood the feed with false events."""

import pytest

from config import ROOT
from fixtures import iter_snapshots
from replay import replay

FIXTURES = sorted((ROOT / "fixtures").glob("*.jsonl.gz"))
MAX_EVENTS_PER_HOUR = 40


@pytest.mark.skipif(not FIXTURES, reason="no recorded fixtures (run record.py)")
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_replay_event_rate_is_sane(path):
    snapshots = list(iter_snapshots(path))
    hours = (snapshots[-1]["now"] - snapshots[0]["now"]) / 3_600_000
    events = replay(path)

    assert len(events) <= max(5, MAX_EVENTS_PER_HOUR * hours), [(e["type"], e["callsign"]) for e in events]
    # Dedup: never the same type twice for one aircraft within a 30 min recording.
    if hours <= 0.5:
        keys = [(e["type"], e["hex"]) for e in events]
        assert len(keys) == len(set(keys))
