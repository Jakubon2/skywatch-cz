"""Helicopter (rescue, police) circling low over one spot for several minutes.

Unlike `holding`, this one targets rotorcraft only.
"""

from .geo import altitude, distance_nm, heading_change, on_ground


def is_rotorcraft(sample: dict, prefixes: list[str]) -> bool:
    category = sample.get("category")
    if category == "A7":
        return True
    callsign = (sample.get("flight") or "").strip().upper()
    return category is None and callsign.startswith(tuple(prefixes))


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["heli_orbit"]
    if not is_rotorcraft(track[-1], cfg["callsign_prefixes"]):
        return None
    window_s = cfg["window_minutes"] * 60
    end = track[-1]["ts"]
    window = [s for s in track if s["ts"] >= end - window_s]
    if len(window) < 3 or window[-1]["ts"] - window[0]["ts"] < window_s * cfg["min_window_coverage"]:
        return None

    if any(on_ground(s) for s in window):
        return None
    alts = [a for a in (altitude(s) for s in window) if a is not None]
    if not alts or max(alts) > cfg["max_alt_ft"]:
        return None
    if any((s.get("gs") or 0) > cfg["max_gs_kt"] for s in window):
        return None

    first = window[0]
    drift = max(distance_nm(first["lat"], first["lon"], s["lat"], s["lon"]) for s in window)
    if drift > cfg["max_drift_nm"]:
        return None

    # Track is meaningless while hovering, count turning only while actually moving.
    moving = [s for s in window if s.get("track") is not None and (s.get("gs") or 0) >= cfg["min_gs_kt"]]
    turned = sum(abs(heading_change(a["track"], b["track"])) for a, b in zip(moving, moving[1:]))
    if turned < cfg["min_turn_deg"]:
        return None

    lats = [s["lat"] for s in window]
    lons = [s["lon"] for s in window]
    return {
        "type": "heli_orbit",
        "data": {
            "turned_deg": round(turned),
            "window_min": round((window[-1]["ts"] - window[0]["ts"]) / 60, 1),
            "max_drift_nm": round(drift, 1),
            "alt_min_ft": min(alts),
            "alt_max_ft": max(alts),
            "center": [round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)],
        },
    }
