"""Alerts in plain Czech: text -> structured rule (Claude), rule summary, and rule evaluation."""

import logging
import math
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from config import CONFIG

log = logging.getLogger("alerts")

MODEL = "claude-haiku-5-5"
DEDUP_MINUTES = CONFIG.get("alerts", {}).get("dedup_minutes", 30)

EventType = Literal["emergency", "holding", "go_around", "interesting"]

# readsb emitter categories ordered by size (A6 high-performance, A7 rotorcraft are not sizes).
SIZE_CATEGORIES = ["A1", "A2", "A3", "A4", "A5"]
SIZE_LABELS = {
    "A1": "lehké (do 7 t)",
    "A2": "malé (7–34 t)",
    "A3": "velké (34–136 t)",
    "A4": "velké s silnou turbulencí v úplavu (např. B757)",
    "A5": "těžké (nad 136 t)",
}

EVENT_LABELS = {
    "emergency": "nouze",
    "holding": "holding",
    "go_around": "nepovedené přistání",
    "interesting": "zajímavé letadlo",
}

# Approximate centre + radius of each Czech region; no polygons in the MVP.
# key: (name, "nad ..." form, lat, lon, radius_nm)
REGIONS = [
    ("Česko", "nad Českem", 49.8, 15.5, 140),
    ("Praha", "nad Prahou", 50.08, 14.43, 10),
    ("Středočeský kraj", "nad Středočeským krajem", 49.95, 14.6, 45),
    ("Jihočeský kraj", "nad Jihočeským krajem", 49.0, 14.45, 45),
    ("Plzeňský kraj", "nad Plzeňským krajem", 49.6, 13.3, 40),
    ("Karlovarský kraj", "nad Karlovarským krajem", 50.2, 12.75, 25),
    ("Ústecký kraj", "nad Ústeckým krajem", 50.5, 13.9, 35),
    ("Liberecký kraj", "nad Libereckým krajem", 50.75, 15.0, 25),
    ("Královéhradecký kraj", "nad Královéhradeckým krajem", 50.35, 15.85, 30),
    ("Pardubický kraj", "nad Pardubickým krajem", 49.9, 16.05, 30),
    ("Vysočina", "nad Vysočinou", 49.4, 15.6, 40),
    ("Jihomoravský kraj", "nad Jihomoravským krajem", 49.05, 16.6, 40),
    ("Olomoucký kraj", "nad Olomouckým krajem", 49.75, 17.15, 35),
    ("Zlínský kraj", "nad Zlínským krajem", 49.15, 17.75, 25),
    ("Moravskoslezský kraj", "nad Moravskoslezským krajem", 49.8, 18.0, 35),
]


# ---------- Rule model ----------

class Area(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_nm: float = Field(gt=0, le=250)
    label: str | None = Field(None, max_length=120)  # set for the user's home, e.g. "Domov"


class Home(BaseModel):
    """The user's own place. Stored only on the device; the UI sends it with the parse request."""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = Field(None, max_length=120)


def _norm_reg(r: str) -> str:
    return r.replace("-", "").replace(" ", "").upper()


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: Area | None = None
    aircraft_types: list[str] | None = None        # ICAO type designators, e.g. ["A124"]
    registrations: list[str] | None = None         # e.g. ["OK-ABC"]; dash and case insensitive
    callsigns: list[str] | None = None             # e.g. ["CSA123"] or ["TVS*"] for a whole airline
    min_size_category: Literal["A1", "A2", "A3", "A4", "A5"] | None = None
    military: bool | None = None                   # True = only military, False = only civil
    event_types: list[EventType] | None = None     # aircraft must have one of these events
    min_alt_ft: int | None = None
    max_alt_ft: int | None = None

    @field_validator("aircraft_types")
    @classmethod
    def _upper_types(cls, v):
        if v is None:
            return None
        v = [t.strip().upper() for t in v if t.strip()]
        return v or None

    @field_validator("registrations")
    @classmethod
    def _clean_regs(cls, v):
        if v is None:
            return None
        v = [r.strip().upper() for r in v if _norm_reg(r)]
        return v or None

    @field_validator("callsigns")
    @classmethod
    def _clean_callsigns(cls, v):
        if v is None:
            return None
        out = []
        for c in v:
            c = c.replace(" ", "").upper()
            if not c:
                continue
            prefix = c.removesuffix("*")
            if "*" in prefix or len(prefix) < 2:
                raise ValueError(f"neplatná volačka {c!r} (hvězdička jen na konci, aspoň 2 znaky před ní)")
            out.append(c)
        return out or None

    @field_validator("event_types")
    @classmethod
    def _empty_events(cls, v):
        return v or None

    @model_validator(mode="after")
    def _check(self):
        if self.min_alt_ft is not None and self.max_alt_ft is not None and self.min_alt_ft > self.max_alt_ft:
            raise ValueError("min_alt_ft je větší než max_alt_ft")
        if all(getattr(self, f) is None for f in type(self).model_fields):
            raise ValueError("pravidlo nemá žádnou podmínku")
        return self


# ---------- Text -> rule (Claude) ----------

SYSTEM_PROMPT = f"""Převádíš český požadavek na upozornění na letadla nad Českem do strukturovaného pravidla. Vždy zavolej právě jeden nástroj.

Jak plnit pole save_rule (co uživatel neříká, nech null):
- area: střed (lat, lon) a poloměr v námořních mílích. Pro kraje a Česko použij tuto tabulku (název: lat, lon, poloměr NM):
{chr(10).join(f"  {name}: {lat}, {lon}, {r}" for name, _, lat, lon, r in REGIONS)}
  Pro město nebo místo mimo tabulku použij jeho souřadnice a poloměr 15 NM, pokud uživatel neřekne jinak. 1 NM = 1,852 km.
- near_home: true, když uživatel myslí své místo („nade mnou“, „nad domem“, „u mě“, „u nás“, „kolem mě“). Area pak nech null, souřadnice doplní aplikace. Když řekne vzdálenost („do 10 km ode mě“), dej ji do home_radius_nm v námořních mílích.
- aircraft_types: ICAO typové označení všech variant typu, např. An-124 → ["A124"], Boeing 747 → ["B741","B742","B743","B744","B748","B74S"], A380 → ["A388"], C-17 → ["C17"].
- registrations: konkrétní imatrikulace letadla, např. „OK-ABC“ → ["OK-ABC"].
- callsigns: volačka konkrétního letu, např. „CSA123“ → ["CSA123"]. Pro celou leteckou společnost použij její tříznakový ICAO kód s hvězdičkou: Smartwings → ["TVS*"], ČSA → ["CSA*"], Ryanair → ["RYR*"], Wizz Air → ["WZZ*"], Lufthansa → ["DLH*"]. Číslo letu s IATA kódem převeď na ICAO volačku (OK123 → CSA123, QS1234 → TVS1234).
- min_size_category: minimální velikostní kategorie ADS-B: A1 lehké (do 7 t), A2 malé (7–34 t), A3 velké (34–136 t), A4 B757, A5 těžké (nad 136 t). „Cokoli většího než A350“ nebo „velké dopravní jako 747“ → A5.
- military: true jen pro vojenská letadla, false jen pro civilní.
- event_types: když se ptá na situace: emergency (nouze), holding (kroužení), go_around (nepovedené přistání), interesting (zajímavé nebo vzácné letadlo).
- min_alt_ft, max_alt_ft: výška ve stopách. Uživatel ji obvykle zadá v metrech, převeď ji (1 m = 3,28 ft, např. 3000 m → 9843).

Když text není požadavek na upozornění, nebo je tak nejasný, že by z něj šlo jen hádat, zavolej cannot_parse a česky vysvětli proč."""

HOME_RADIUS_NM = 5


def _save_rule_schema() -> dict:
    """AlertRule schema plus near_home / home_radius_nm. The model never sees the user's address."""
    schema = AlertRule.model_json_schema()
    schema["$defs"]["Area"]["properties"].pop("label", None)  # labels are set by the app only
    schema["properties"]["near_home"] = {
        "type": "boolean", "description": "Uživatel myslí své místo (nade mnou, nad domem).",
    }
    schema["properties"]["home_radius_nm"] = {
        "type": "number", "description": "Poloměr kolem domova v NM, jen když ho uživatel řekne.",
    }
    return schema


TOOLS = [
    {
        "name": "save_rule",
        "description": "Uloží strukturované pravidlo upozornění.",
        "input_schema": _save_rule_schema(),
    },
    {
        "name": "cannot_parse",
        "description": "Požadavek nejde převést na pravidlo.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Krátké vysvětlení česky."}},
            "required": ["reason"],
        },
    },
]

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()  # ANTHROPIC_API_KEY from .env (loaded by config)
    return _client


class RuleParseError(ValueError):
    """The text could not be turned into a valid rule. The message is Czech, for the UI."""


NO_HOME_ERROR = "Nejdřív si v aplikaci nastav svou adresu, pak můžu hlídat letadla nad tebou."


async def parse_rule(text: str, home: Home | None = None) -> AlertRule:
    """Text -> rule. `home` is used as the area when the text means the user's own place."""
    response = await _get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": text}],
    )
    call = next((b for b in response.content if b.type == "tool_use"), None)
    if call is None:
        raise RuleParseError("Nepodařilo se pochopit zadání, zkus ho napsat jinak.")
    if call.name == "cannot_parse":
        raise RuleParseError(call.input.get("reason") or "Zadání nejde převést na pravidlo.")

    data = dict(call.input)
    near_home = data.pop("near_home", None)
    home_radius = data.pop("home_radius_nm", None)
    if isinstance(data.get("area"), dict):
        data["area"] = {k: v for k, v in data["area"].items() if k != "label"}
    if near_home:
        if home is None:
            raise RuleParseError(NO_HOME_ERROR)
        data["area"] = {"lat": home.lat, "lon": home.lon, "radius_nm": home_radius or HOME_RADIUS_NM,
                        "label": home.label or "Domov"}
    try:
        return AlertRule.model_validate(data)
    except ValidationError as e:
        log.warning("invalid rule from model for %r: %s", text, e)
        raise RuleParseError("Pravidlo z tohoto zadání nedává smysl, zkus ho upřesnit.") from e


# ---------- Rule -> Czech summary ----------

def _fmt_ft(ft: int) -> str:
    """Rules store feet (like the data); users see metres rounded to 50 m."""
    return f"{round(ft * 0.3048 / 50) * 50:,} m".replace(",", " ")


def _area_label(area: Area) -> str:
    if area.label:
        return f"do {round(area.radius_nm * 1.852)} km od místa {area.label}"
    for _, over, lat, lon, r in REGIONS:
        if abs(area.lat - lat) < 0.05 and abs(area.lon - lon) < 0.05 and abs(area.radius_nm - r) < 1:
            return over
    km = round(area.radius_nm * 1.852)
    return f"do {km} km od bodu {area.lat:.2f}° s. š., {area.lon:.2f}° v. d."


def rule_summary_cs(rule: AlertRule) -> str:
    """How the rule was understood, e.g. 'Upozorním tě na letadlo typu A124 nad Vysočinou.'"""
    what = []
    if rule.military is True:
        what.append("vojenské")
    elif rule.military is False:
        what.append("civilní")
    what.append("letadlo")
    if rule.aircraft_types:
        what.append(("typu " if len(rule.aircraft_types) == 1 else "typů ") + ", ".join(rule.aircraft_types))
    if rule.min_size_category:
        what.append(f"aspoň kategorie {SIZE_LABELS[rule.min_size_category]}")
    if rule.registrations:
        what.append("s imatrikulací " + ", ".join(rule.registrations))
    if rule.callsigns:
        exact = [c for c in rule.callsigns if not c.endswith("*")]
        prefixes = [c[:-1] for c in rule.callsigns if c.endswith("*")]
        if exact:
            what.append(("s volačkou " if len(exact) == 1 else "s volačkami ") + ", ".join(exact))
        if prefixes:
            joiner = "nebo " if exact else ""
            what.append(joiner + "s volačkou začínající " + " nebo ".join(prefixes))

    parts = [" ".join(what)]
    if rule.area:
        parts.append(_area_label(rule.area))
    if rule.min_alt_ft is not None and rule.max_alt_ft is not None:
        parts.append(f"ve výšce {_fmt_ft(rule.min_alt_ft)} až {_fmt_ft(rule.max_alt_ft)}")
    elif rule.min_alt_ft is not None:
        parts.append(f"výš než {_fmt_ft(rule.min_alt_ft)}")
    elif rule.max_alt_ft is not None:
        parts.append(f"níž než {_fmt_ft(rule.max_alt_ft)}")
    if rule.event_types:
        parts.append("při události: " + ", ".join(EVENT_LABELS[t] for t in rule.event_types))

    return "Upozorním tě na " + ", ".join(parts) + "."


# ---------- Evaluation ----------

def _distance_nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def matches(rule: AlertRule, aircraft: dict, events_for_hex: list[dict]) -> bool:
    """Pure check of one readsb aircraft dict (and its recent events) against a rule."""
    if rule.area:
        if aircraft.get("lat") is None or aircraft.get("lon") is None:
            return False
        if _distance_nm(rule.area.lat, rule.area.lon, aircraft["lat"], aircraft["lon"]) > rule.area.radius_nm:
            return False

    if rule.aircraft_types and (aircraft.get("t") or "").upper() not in rule.aircraft_types:
        return False

    # Owners who opted out of tracking (LADD 8, PIA 4) are never followed by registration or callsign.
    if (rule.registrations or rule.callsigns) and aircraft.get("dbFlags", 0) & 12:
        return False

    if rule.registrations:
        reg = _norm_reg(aircraft.get("r") or "")
        if not reg or reg not in {_norm_reg(r) for r in rule.registrations}:
            return False

    if rule.callsigns:
        flight = (aircraft.get("flight") or "").replace(" ", "").upper()
        if not flight or not any(
            flight.startswith(c[:-1]) if c.endswith("*") else flight == c for c in rule.callsigns
        ):
            return False

    if rule.min_size_category:
        cat = aircraft.get("category")
        if cat not in SIZE_CATEGORIES or SIZE_CATEGORIES.index(cat) < SIZE_CATEGORIES.index(rule.min_size_category):
            return False

    if rule.military is not None and bool(aircraft.get("dbFlags", 0) & 1) != rule.military:
        return False

    if rule.min_alt_ft is not None or rule.max_alt_ft is not None:
        alt = aircraft.get("alt_baro")
        alt = 0 if alt == "ground" else alt
        if not isinstance(alt, (int, float)):
            return False
        if rule.min_alt_ft is not None and alt < rule.min_alt_ft:
            return False
        if rule.max_alt_ft is not None and alt > rule.max_alt_ft:
            return False

    if rule.event_types and not any(e.get("type") in rule.event_types for e in events_for_hex):
        return False

    return True


def evaluate(
    rules: dict[int, AlertRule],
    snapshot: dict,
    recent_events: list[dict],
    last_hits: dict[tuple[int, str], float],
) -> list[tuple[int, str]]:
    """Return new (rule_id, hex) hits for active rules in this snapshot.

    `last_hits` maps (rule_id, hex) -> epoch seconds of the last hit; it is not modified.
    The caller records the returned hits (alert_hits table + last_hits) and sends notifications.
    """
    now = snapshot["now"] / 1000
    window = DEDUP_MINUTES * 60
    events_by_hex: dict[str, list[dict]] = {}
    for e in recent_events:
        events_by_hex.setdefault(e["hex"], []).append(e)

    hits = []
    for rule_id, rule in rules.items():
        for ac in snapshot.get("ac", []):
            key = (rule_id, ac["hex"])
            if key in last_hits and now - last_hits[key] < window:
                continue
            if matches(rule, ac, events_by_hex.get(ac["hex"], [])):
                hits.append(key)
    return hits
