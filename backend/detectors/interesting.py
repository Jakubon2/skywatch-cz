"""Interesting aircraft: listed type, military, or a type not seen for a long time."""

DAY = 86400


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["interesting"]
    last = track[-1]
    ac_type = last.get("t")
    reasons = []

    if ac_type and ac_type in ctx["interesting_types"]:
        reasons.append("listed_type")
    if cfg["military"] and (last.get("dbFlags") or 0) & 1:
        reasons.append("military")

    # Rare type: only meaningful once we have enough history of what normally flies here.
    seen, since = ctx.get("seen_types") or {}, ctx.get("history_since")
    if ac_type and since is not None and last["ts"] - since >= cfg["unseen_min_history_days"] * DAY:
        last_seen = seen.get(ac_type)
        if last_seen is None or last["ts"] - last_seen > cfg["unseen_days"] * DAY:
            reasons.append("rare_type")

    if not reasons:
        return None
    return {
        "type": "interesting",
        "data": {"reasons": reasons, "type_name": ctx["interesting_types"].get(ac_type), "registration": last.get("r")},
    }
