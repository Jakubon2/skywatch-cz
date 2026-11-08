"""Read snapshots recorded by record.py."""

import gzip
import json
from pathlib import Path
from typing import Iterator


def iter_snapshots(path: str | Path) -> Iterator[dict]:
    """Yield snapshots in order. Tolerates a truncated file (recording still running or killed)."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        try:
            for line in f:
                if line.endswith("\n"):
                    yield json.loads(line)
        except EOFError:
            return


if __name__ == "__main__":
    import sys

    snapshots = list(iter_snapshots(sys.argv[1]))
    counts = [len(s["ac"]) for s in snapshots]
    span_min = (snapshots[-1]["now"] - snapshots[0]["now"]) / 60000 if snapshots else 0
    print(f"{len(snapshots)} snapshots over {span_min:.1f} min, "
          f"aircraft per snapshot min/avg/max: {min(counts)}/{sum(counts) // len(counts)}/{max(counts)}")
