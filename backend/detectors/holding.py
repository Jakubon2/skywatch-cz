"""Holding: lots of turning in a small area at a stable altitude."""

from .geo import altitude, distance_nm, heading_change


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["holding"]
    if track[-1].get("category") not in cfg["categories"]:
        return None
    window_s = cfg["window_minutes"] * 60
    end = track[-1]["ts"]
    window = [s for s in track if s["ts"] >= end - window_s and s.get("track") is not None]
    if len(window) < 3 or window[-1]["ts"] - window[0]["ts"] < window_s * cfg["min_window_coverage"]:
        return None

    alts = [altitude(s) for s in window]
    if any(a is None or a <= cfg["min_alt_ft"] for a in alts):
        return None
    if (max(alts) - min(alts)) / 2 > cfg["max_alt_dev_ft"]:
        return None

    first = window[0]
    drift = max(distance_nm(first["lat"], first["lon"], s["lat"], s["lon"]) for s in window)
    if drift > cfg["max_drift_nm"]:
        return None

    turned = sum(abs(heading_change(a["track"], b["track"])) for a, b in zip(window, window[1:]))
    if turned < cfg["min_turn_deg"]:
        return None

    lats = [s["lat"] for s in window]
    lons = [s["lon"] for s in window]
    return {
        "type": "holding",
        "data": {
            "turned_deg": round(turned),
            "window_min": round((window[-1]["ts"] - window[0]["ts"]) / 60, 1),
            "max_drift_nm": round(drift, 1),
            "alt_min_ft": min(alts),
            "alt_max_ft": max(alts),
            "center": [round(sum(lats) / len(lats), 4), round(sum(lons) / len(lons), 4)],
        },
    }
