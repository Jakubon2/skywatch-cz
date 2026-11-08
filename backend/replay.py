"""Replay recorded snapshots through the poller + detectors (in-memory DB, no network).

Usage:  python replay.py ../fixtures/snapshots-*.jsonl.gz [-v]
"""

import argparse
import logging
from collections import Counter

from fixtures import iter_snapshots
from poller import Poller


def replay(path: str) -> list[dict]:
    poller = Poller(db_path=":memory:")
    events = []
    for snapshot in iter_snapshots(path):
        events += poller.ingest(snapshot)
    return events


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("-v", action="store_true", help="log every snapshot")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO if args.v else logging.WARNING, format="%(message)s")

    events = replay(args.path)
    for e in events:
        print(f"{e['started_at']}  {e['type']:<12} {e['callsign'] or e['hex']:<9} {e['aircraft_type'] or '?':<5} "
              f"{e['alt_ft']:>6} ft  {e['data']}")
    print(f"\n{len(events)} events: {dict(Counter(e['type'] for e in events))}")
