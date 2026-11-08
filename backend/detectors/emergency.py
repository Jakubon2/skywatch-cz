"""Emergency squawk (7700/7600/7500) or ADS-B emergency status."""


def _flag(sample: dict, squawks: list[str]) -> str | None:
    if sample.get("squawk") in squawks:
        return sample["squawk"]
    emergency = sample.get("emergency")
    if emergency and emergency != "none":
        return emergency
    return None


def detect(track: list[dict], ctx: dict) -> dict | None:
    cfg = ctx["cfg"]["emergency"]
    recent = track[-cfg["min_samples"]:]
    if len(recent) < cfg["min_samples"]:
        return None
    flags = [_flag(s, cfg["squawks"]) for s in recent]
    if not all(flags):
        return None

    last = track[-1]
    squawk = last.get("squawk")
    return {
        "type": "emergency",
        "data": {
            "squawk": squawk,
            "emergency": last.get("emergency"),
            "unverified": squawk == cfg["hijack_squawk"],
        },
    }
