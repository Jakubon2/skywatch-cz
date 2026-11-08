"""Runs saved alert rules against every live snapshot: records hits and sends ntfy notifications."""

import json
import logging
import time
from datetime import datetime, timezone

import feed
from alerts import AlertRule, evaluate
from notify import notify

log = logging.getLogger("alerts")

_last_hits: dict[tuple[int, str], float] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active_rules(conn) -> dict[int, AlertRule]:
    rows = conn.execute("SELECT id, rule_json FROM alert_rules WHERE active = 1").fetchall()
    return {r["id"]: AlertRule.model_validate_json(r["rule_json"]) for r in rows}


def load_last_hits(conn):
    """Restore dedup state after a restart so a restart doesn't re-send recent notifications."""
    rows = conn.execute(
        "SELECT rule_id, hex, MAX(hit_at) AS t FROM alert_hits GROUP BY rule_id, hex"
    ).fetchall()
    for r in rows:
        _last_hits[(r["rule_id"], r["hex"])] = datetime.fromisoformat(r["t"]).timestamp()


def _describe(ac: dict) -> str:
    callsign = (ac.get("flight") or "").strip() or ac.get("r") or ac["hex"]
    parts = [callsign]
    if ac.get("t"):
        parts.append(ac["t"])
    alt = ac.get("alt_baro")
    if isinstance(alt, (int, float)):
        parts.append(f"{alt:,} ft".replace(",", " "))
    return ", ".join(parts)


async def on_snapshot(poller, events: list[dict]):
    """Poller listener."""
    rules = active_rules(poller.db)
    if not rules or not poller.latest:
        return
    since = datetime.fromtimestamp(time.time() - 1800, timezone.utc).isoformat(timespec="seconds")
    recent = [dict(r) for r in poller.db.execute(
        "SELECT type, hex FROM events WHERE started_at >= ?", (since,)
    ).fetchall()]

    hits = evaluate(rules, poller.latest, recent, _last_hits)
    if not hits:
        return

    texts = {r["id"]: r["text"] for r in poller.db.execute("SELECT id, text FROM alert_rules").fetchall()}
    aircraft = {a["hex"]: a for a in poller.latest["ac"]}
    now = poller.latest["now"] / 1000
    for rule_id, hex_id in hits:
        _last_hits[(rule_id, hex_id)] = now
        poller.db.execute(
            "INSERT INTO alert_hits (rule_id, hex, hit_at) VALUES (?, ?, ?)", (rule_id, hex_id, now_iso())
        )
        ac = aircraft[hex_id]
        title = f"Skywatch: {texts.get(rule_id, 'alert')}"
        message = _describe(ac)
        log.info("ALERT rule %s hit by %s", rule_id, message)
        feed.publish("alert_hit", {"rule_id": rule_id, "hex": hex_id, "title": title, "message": message,
                                   "lat": ac.get("lat"), "lon": ac.get("lon")})
        await notify(title, message, tags=["airplane"], url=f"/?hex={hex_id}", tag=f"alert-{rule_id}-{hex_id}")
    poller.db.commit()


def rule_to_dict(row) -> dict:
    d = dict(row)
    d["rule"] = json.loads(d.pop("rule_json"))
    d["active"] = bool(d["active"])
    return d
