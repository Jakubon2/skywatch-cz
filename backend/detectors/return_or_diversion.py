"""Probable return or diversion: flew a steady leg, reversed course, now descending toward a Czech airport.

We can't know the planned route, so this only covers the "turned back and descends toward an
airport" case and is always marked probable. The "before" leg must be high and not descending,
which rules out the normal downwind -> final reversal of an arrival.
"""

from .geo import altitude, bearing_deg, distance_nm, heading_change, mean_heading, nearest_airport


def _leg(samples: list[dict], max_spread: float) -> float | None:
    """Mean heading of a steady leg, None if it's not steady."""
    headings = [s["track"] for s in samples]
    mean = mean_heading(headings)
    if any(abs(heading_change(mean, h)) > max_spread for h in headings):
        return None
    return mean


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["return_or_diversion"]
    last = track[-1]
    if last.get("category") not in cfg["categories"]:
        return None

    samples = [s for s in track if s.get("track") is not None]
    leg_s = cfg["leg_minutes"] * 60
    if len(samples) < 6 or samples[-1]["ts"] - samples[0]["ts"] < 2 * leg_s:
        return None
    before = [s for s in samples if s["ts"] <= samples[0]["ts"] + leg_s]
    after = [s for s in samples if s["ts"] >= last["ts"] - leg_s]

    h_before, h_after = _leg(before, cfg["max_leg_spread_deg"]), _leg(after, cfg["max_leg_spread_deg"])
    if h_before is None or h_after is None:
        return None
    reversal = abs(heading_change(h_before, h_after))
    if reversal < cfg["min_reversal_deg"]:
        return None

    before_alts = [altitude(s) for s in before]
    after_alts = [altitude(s) for s in after]
    if any(a is None for a in before_alts + after_alts) or min(before_alts) < cfg["min_before_alt_ft"]:
        return None
    if before_alts[0] - before_alts[-1] > cfg["max_before_descent_ft"]:
        return None
    if after_alts[0] - after_alts[-1] < cfg["min_descent_ft"]:
        return None

    apt, dist = nearest_airport(last, ctx["airports"])
    if dist > cfg["max_airport_dist_nm"]:
        return None
    to_apt = bearing_deg(last["lat"], last["lon"], apt["lat"], apt["lon"])
    if abs(heading_change(h_after, to_apt)) > cfg["max_bearing_off_deg"]:
        return None
    first = after[0]
    if distance_nm(apt["lat"], apt["lon"], first["lat"], first["lon"]) - dist < cfg["min_closing_nm"]:
        return None

    return {
        "type": "return_or_diversion",
        "data": {
            "probable": True,   # shown as "pravděpodobně": the planned route is unknown
            "airport": apt["ident"],
            "airport_name": apt["name_cs"],
            "dist_nm": round(dist, 1),
            "heading_before": round(h_before),
            "heading_now": round(h_after),
            "reversal_deg": round(reversal),
            "alt_before_ft": min(before_alts),
            "alt_ft": after_alts[-1],
        },
    }
