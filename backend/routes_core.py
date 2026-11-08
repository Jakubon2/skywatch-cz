"""Events feed, live stream (SSE) and alert rule management."""

import asyncio
import json

import anthropic
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import alerts_service
import feed
from alerts import AlertRule, Home, RuleParseError, parse_rule, rule_summary_cs


def make_router(poller) -> APIRouter:
    router = APIRouter(prefix="/api")
    db = poller.db

    # ---------- events ----------

    @router.get("/events")
    def events(
        limit: int = Query(50, ge=1, le=200),
        before_id: int | None = None,
        q: str | None = Query(None, max_length=100),
        type: list[str] | None = Query(None),
        since: str | None = None,
        until: str | None = None,
    ):
        """Feed and history search. since/until are ISO timestamps (UTC), type may repeat."""
        return feed.list_events(db, limit, before_id, q, type, since, until)

    @router.get("/events/{event_id}")
    def event(event_id: int):
        """Single event, e.g. for a shared link /?event=123."""
        e = feed.get_event(db, event_id)
        if not e:
            raise HTTPException(404, "Událost neexistuje.")
        return e

    @router.get("/stream")
    async def stream():
        """SSE: {"kind": "event"|"explanation"|"alert_hit", ...} messages, comment ping every 15 s."""
        q = feed.subscribe()

        async def gen():
            try:
                yield "retry: 5000\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                feed.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------- alerts ----------

    class ParseRequest(BaseModel):
        text: str = Field(min_length=3, max_length=500)
        home: Home | None = None  # the user's place from the device, for "nade mnou" rules

    class CreateRequest(BaseModel):
        text: str = Field(min_length=3, max_length=500)
        rule: AlertRule

    class PatchRequest(BaseModel):
        active: bool

    @router.post("/alerts/parse")
    async def alerts_parse(req: ParseRequest):
        """Step 1: how Claude understood the text. Nothing is saved until the user confirms."""
        try:
            rule = await (parse_rule(req.text, home=req.home) if req.home else parse_rule(req.text))
        except RuleParseError as e:
            raise HTTPException(422, f"Zadání se nepodařilo převést na pravidlo: {e}")
        except anthropic.APIError:
            raise HTTPException(502, "AI teď neodpovídá, zkus to prosím za chvíli.")
        return {"rule": rule.model_dump(), "summary": rule_summary_cs(rule)}

    @router.post("/alerts")
    def alerts_create(req: CreateRequest):
        """Step 2: save the rule the user confirmed."""
        cur = db.execute(
            "INSERT INTO alert_rules (text, rule_json, active, created_at) VALUES (?, ?, 1, ?)",
            (req.text, req.rule.model_dump_json(), alerts_service.now_iso()),
        )
        db.commit()
        return _get_rule(cur.lastrowid)

    @router.get("/alerts")
    def alerts_list():
        rows = db.execute("SELECT * FROM alert_rules ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = alerts_service.rule_to_dict(r)
            d["summary"] = rule_summary_cs(AlertRule.model_validate(d["rule"]))
            d["hits"] = db.execute("SELECT COUNT(*) FROM alert_hits WHERE rule_id = ?", (r["id"],)).fetchone()[0]
            out.append(d)
        return out

    @router.patch("/alerts/{rule_id}")
    def alerts_patch(rule_id: int, req: PatchRequest):
        if not db.execute("UPDATE alert_rules SET active = ? WHERE id = ?", (int(req.active), rule_id)).rowcount:
            raise HTTPException(404, "Alert neexistuje.")
        db.commit()
        return _get_rule(rule_id)

    @router.delete("/alerts/{rule_id}")
    def alerts_delete(rule_id: int):
        db.execute("DELETE FROM alert_hits WHERE rule_id = ?", (rule_id,))
        if not db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,)).rowcount:
            raise HTTPException(404, "Alert neexistuje.")
        db.commit()
        return {"ok": True}

    def _get_rule(rule_id: int) -> dict:
        row = db.execute("SELECT * FROM alert_rules WHERE id = ?", (rule_id,)).fetchone()
        d = alerts_service.rule_to_dict(row)
        d["summary"] = rule_summary_cs(AlertRule.model_validate(d["rule"]))
        return d

    return router
