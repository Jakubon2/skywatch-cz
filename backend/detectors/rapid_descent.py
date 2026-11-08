"""Rapid descent from cruise without an emergency squawk (e.g. after a pressurisation problem).

baro_rate from ADS-B is often garbage, so the descent must also show in alt_baro itself.
"""

from .geo import altitude


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["rapid_descent"]
    last = track[-1]
    if last.get("category") not in cfg["categories"]:
        return None

    recent = track[-cfg["min_samples"]:]
    if len(recent) < cfg["min_samples"]:
        return None
    if not all(isinstance(s.get("baro_rate"), (int, float)) and s["baro_rate"] < cfg["descent_rate_fpm"] for s in recent):
        return None
    alts = [altitude(s) for s in recent]
    if any(a is None for a in alts):
        return None
    minutes = (recent[-1]["ts"] - recent[0]["ts"]) / 60
    if minutes <= 0 or (alts[-1] - alts[0]) / minutes > cfg["min_alt_rate_fpm"]:
        return None

    window = [altitude(s) for s in track if s["ts"] >= last["ts"] - cfg["window_minutes"] * 60]
    top = max(a for a in window if a is not None)
    loss = top - alts[-1]
    if top < cfg["min_start_alt_ft"] or loss < cfg["min_loss_ft"]:
        return None

    return {
        "type": "rapid_descent",
        "data": {
            "start_alt_ft": top,
            "alt_ft": alts[-1],
            "loss_ft": loss,
            "rate_fpm": round(sum(s["baro_rate"] for s in recent) / len(recent)),
            "squawk": last.get("squawk"),
        },
    }
