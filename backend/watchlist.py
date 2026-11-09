"""Watched aircraft ("Sledovaná letadla"): list, live position and user edits of config/watchlist.yaml."""

import threading
from datetime import date

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from config import ROOT
import watched_history
from detectors.watched import index, match, norm_reg

NOTE = ("Vlastníci letadel pocházejí z veřejných zdrojů a můžou být zastaralí: letadla se prodávají, "
        "pronajímají a přeregistrovávají. Letadla, jejichž majitelé požádali o skrytí (FAA LADD/PIA), "
        "aplikace nikdy nezvýrazní.")

HEADER = """\
# Sledovaná letadla: soukromé tryskáče veřejně známých osobností.
# Pravidla: jen veřejné osobnosti (nikdy soukromé osoby), každý záznam má veřejný zdroj a datum ověření.
# Letadla s příznakem FAA LADD nebo PIA (readsb dbFlags 8 / 4) aplikace nikdy nezvýrazní ani neohlásí.
# Vlastnictví pochází z veřejných zdrojů a může být zastaralé: letadla se prodávají, pronajímají
# a přeregistrovávají. Hex u N-registrací ověřen převodem N-čísla na ICAO adresu.
# Soubor můžeš upravit ručně; aplikace ho přepisuje při přidání nebo odebrání záznamu (komentáře mimo hlavičku zmizí).
"""

LIVE_FIELDS = ("hex", "flight", "t", "lat", "lon", "alt_baro", "gs", "track")


def load(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("aircraft") or []


def save(path, entries: list[dict]):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(HEADER)
        yaml.safe_dump({"aircraft": entries}, f, allow_unicode=True, sort_keys=False, width=200)
    tmp.replace(path)


class Entry(BaseModel):
    reg: str = Field(min_length=2, max_length=12)
    hex: str | None = Field(None, pattern=r"^[0-9a-fA-F]{6}$")
    type: str | None = Field(None, max_length=4)
    label: str = Field(min_length=2, max_length=80)
    category: str = Field(min_length=2, max_length=40)
    note: str | None = Field(None, max_length=300)
    source: str = Field(pattern=r"^https?://\S+$", max_length=500)  # every entry needs a public source

    @field_validator("reg", "type")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if v else v

    @field_validator("hex")
    @classmethod
    def _lower(cls, v):
        return v.lower() if v else None

    @field_validator("label", "category", "note")
    @classmethod
    def _strip(cls, v):
        return v.strip() or None if v else v


def make_router(poller, path=None) -> APIRouter:
    router = APIRouter(prefix="/api")
    path = path or ROOT / "config" / poller.ctx["cfg"]["watched"]["file"]
    cfg = poller.ctx["cfg"]["watched"]
    lock = threading.Lock()

    watched_history.init(poller)

    def publish(entries):
        poller.ctx["watchlist"] = index(entries)  # the detector sees the change on the next snapshot

    @router.get("/watchlist")
    def list_watchlist():
        """All entries; `live` is the current position when the aircraft is in range (never for LADD/PIA)."""
        latest = poller.latest
        wl = poller.ctx["watchlist"]
        live = {}
        for a in (latest or {}).get("ac", []):
            entry = match(a, wl, cfg)
            if entry is not None:
                live[norm_reg(entry["reg"])] = {k: a[k] for k in LIVE_FIELDS if k in a}
        visits = watched_history.last_visits(poller.db, wl["entries"])
        return {
            "now": latest["now"] if latest else None,
            "note": NOTE,
            "entries": [{**e, "live": live.get(norm_reg(e["reg"])), "last_visit": visits.get(norm_reg(e["reg"]))}
                        for e in wl["entries"]],
        }

    @router.get("/watchlist/visits")
    def visits(limit: int = 20):
        """Most recent visits of watched aircraft over our area, newest first."""
        return {"visits": watched_history.recent(poller.db, poller.ctx["watchlist"]["entries"], min(limit, 100))}

    @router.post("/watchlist", status_code=201)
    def add(entry: Entry):
        with lock:
            entries = load(path)
            if any(norm_reg(e["reg"]) == norm_reg(entry.reg) for e in entries):
                raise HTTPException(409, "Letadlo s touto registrací už v seznamu je.")
            new = {k: v for k, v in entry.model_dump().items() if v is not None}
            new["checked"] = date.today().isoformat()
            entries.append(new)
            save(path, entries)
            publish(entries)
        return new

    @router.delete("/watchlist/{reg}", status_code=204)
    def remove(reg: str):
        with lock:
            entries = load(path)
            kept = [e for e in entries if norm_reg(e["reg"]) != norm_reg(reg)]
            if len(kept) == len(entries):
                raise HTTPException(404, "Letadlo v seznamu není.")
            save(path, kept)
            publish(kept)

    return router
