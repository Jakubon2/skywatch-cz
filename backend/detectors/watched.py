"""Watched aircraft: private jets of well-known public figures from config/watchlist.yaml.

Aircraft whose owners opted out of tracking (FAA LADD or PIA, see `skip_db_flags`) never match.
"""


def norm_reg(reg: str | None) -> str:
    """'OK-ABC', 'ok abc' -> 'OKABC'."""
    return "".join(c for c in (reg or "").upper() if c.isalnum())


def index(entries: list[dict]) -> dict:
    """Lookup tables for match(): hex -> entry and normalized registration -> entry."""
    return {
        "entries": entries,
        "hex": {e["hex"].lower(): e for e in entries if e.get("hex")},
        "reg": {norm_reg(e["reg"]): e for e in entries},
    }


def opted_out(sample: dict, cfg: dict) -> bool:
    flags = sample.get("dbFlags") or 0
    return any(flags & bit for bit in cfg["skip_db_flags"])


def match(sample: dict, watchlist: dict, cfg: dict) -> dict | None:
    """The watchlist entry for this readsb sample, or None (also for LADD/PIA aircraft)."""
    if opted_out(sample, cfg):
        return None
    entry = watchlist["hex"].get((sample.get("hex") or "").lower())
    if entry is None and sample.get("r"):
        entry = watchlist["reg"].get(norm_reg(sample["r"]))
    return entry


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["watched"]
    watchlist = ctx.get("watchlist")
    if not watchlist:
        return None
    # Every recent sample must match: one LADD/PIA sample in the window is enough to stay quiet.
    recent = track[-cfg["min_samples"]:]
    if len(recent) < cfg["min_samples"]:
        return None
    entries = [match(s, watchlist, cfg) for s in recent]
    entry = entries[-1]
    if entry is None or any(e is not entry for e in entries):
        return None
    return {
        "type": "watched",
        "data": {
            "label": entry["label"],
            "category": entry["category"],
            "registration": entry["reg"],
            "note": entry.get("note"),
            "source": entry["source"],
            "checked": entry["checked"],
        },
    }
