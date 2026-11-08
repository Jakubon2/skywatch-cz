"""Record raw snapshots to fixtures/ for tests and detector tuning.

Usage:  python record.py [--minutes 30]

Writes one gzipped JSON Lines file, one snapshot per line. The file is flushed
after every snapshot, so an interrupted recording is still readable.
"""

import argparse
import asyncio
import gzip
import json
import logging
import time
from datetime import datetime

from adsb import AdsbClient, poll_forever
from config import ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("record")


async def main(minutes: float):
    out = ROOT / "fixtures" / f"snapshots-{datetime.now():%Y%m%d-%H%M}.jsonl.gz"
    out.parent.mkdir(exist_ok=True)
    client = AdsbClient()
    count = 0

    with gzip.open(out, "wt", encoding="utf-8") as f:
        def write(snapshot: dict):
            nonlocal count
            f.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
            f.flush()
            count += 1
            log.info("#%d: %d aircraft -> %s", count, len(snapshot.get("ac", [])), out.name)

        try:
            await poll_forever(client, write, stop_at=time.monotonic() + minutes * 60)
        finally:
            await client.close()

    log.info("done, %d snapshots in %s", count, out)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=30)
    try:
        asyncio.run(main(p.parse_args().minutes))
    except KeyboardInterrupt:
        log.info("stopped early; the file is complete up to the last snapshot")
