"""Probable go-around: descending near an airport, then a sustained climb without touching down.

Checks the airport from ctx["airports"] that the aircraft is currently closest to.

Note: alt_baro is pressure altitude (1013 hPa). With low QNH it reads higher than the real
altitude (~30 ft per hPa), so max_agl_ft is deliberately loose.
"""

from .geo import altitude, distance_nm, nearest_airport, on_ground


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["go_around"]
    apt, dist = nearest_airport(track[-1], ctx["airports"])
    if dist > cfg["max_dist_nm"]:
        return None
    end = track[-1]["ts"]

    near = [
        s for s in track
        if s["ts"] >= end - cfg["window_minutes"] * 60
        and distance_nm(apt["lat"], apt["lon"], s["lat"], s["lon"]) <= cfg["max_dist_nm"]
    ]

    descending = False
    low = None          # lowest altitude since the descent started
    climbs = 0
    prev_ts = None
    for s in near:
        gap = prev_ts is not None and s["ts"] - prev_ts > cfg["max_gap_s"]
        prev_ts = s["ts"]
        if on_ground(s) or gap:
            descending, low, climbs = False, None, 0   # landed, touch-and-go or a gap that may hide one
            continue
        alt, rate = altitude(s), s.get("baro_rate")
        if alt is None or rate is None:
            continue
        if not descending:
            if rate < cfg["descent_rate_fpm"]:
                descending, low = True, alt
            continue

        low = min(low, alt)
        climbs = climbs + 1 if rate > cfg["climb_rate_fpm"] else 0
        if (
            climbs >= cfg["climb_samples"]
            and low - apt["elevation_ft"] < cfg["max_agl_ft"]
            and alt - low >= cfg["min_gain_ft"]
        ):
            return {
                "type": "go_around",
                "data": {
                    "airport": apt["ident"],
                    "airport_name": apt["name_cs"],
                    "probable": True,
                    "lowest_alt_ft": low,
                    "lowest_agl_ft": low - apt["elevation_ft"],
                    "climb_ft": alt - low,
                    "dist_nm": round(distance_nm(apt["lat"], apt["lon"], s["lat"], s["lon"]), 1),
                },
            }
    return None
