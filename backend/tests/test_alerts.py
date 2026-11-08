import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import alerts
import notify
from alerts import AlertRule, RuleParseError, evaluate, matches, parse_rule, rule_summary_cs

NOW_MS = 1_794_142_424_000
NOW = NOW_MS / 1000


def plane(hex="abc123", t="B738", lat=49.8, lon=15.5, alt=35000, category="A3", db=0):
    return {"hex": hex, "t": t, "lat": lat, "lon": lon, "alt_baro": alt, "category": category, "dbFlags": db}


VYSOCINA = {"lat": 49.4, "lon": 15.6, "radius_nm": 40}


# ---------- matches ----------

def test_area():
    rule = AlertRule(area=VYSOCINA)
    assert matches(rule, plane(lat=49.4, lon=15.6), [])
    assert matches(rule, plane(lat=49.9, lon=15.6), [])        # ~30 NM north, inside
    assert not matches(rule, plane(lat=50.1, lon=14.26), [])   # Prague airport, ~55 NM, outside
    assert not matches(rule, {"hex": "x", "t": "B738"}, [])    # no position


def test_types_case_insensitive():
    rule = AlertRule(aircraft_types=["a124"])
    assert rule.aircraft_types == ["A124"]
    assert matches(rule, plane(t="A124"), [])
    assert not matches(rule, plane(t="B738"), [])
    assert not matches(rule, {"hex": "x", "lat": 49.8, "lon": 15.5}, [])  # unknown type


def test_military_flag():
    mil, civ = plane(db=1), plane(db=0)
    assert matches(AlertRule(military=True), mil, [])
    assert not matches(AlertRule(military=True), civ, [])
    assert matches(AlertRule(military=False), civ, [])
    assert matches(AlertRule(military=True), plane(db=3), [])  # other bits set too


def test_size_category():
    rule = AlertRule(min_size_category="A5")
    assert matches(rule, plane(category="A5"), [])
    assert not matches(rule, plane(category="A3"), [])
    assert not matches(rule, plane(category="A7"), [])   # rotorcraft is not a size
    assert not matches(rule, plane(category=None), [])


def test_altitude_and_ground():
    rule = AlertRule(min_alt_ft=1000, max_alt_ft=10000)
    assert matches(rule, plane(alt=5000), [])
    assert not matches(rule, plane(alt=20000), [])
    assert not matches(rule, plane(alt="ground"), [])
    assert matches(AlertRule(max_alt_ft=500), plane(alt="ground"), [])
    assert not matches(rule, plane(alt=None), [])


def test_event_types():
    rule = AlertRule(event_types=["holding"])
    assert matches(rule, plane(), [{"hex": "abc123", "type": "holding"}])
    assert not matches(rule, plane(), [{"hex": "abc123", "type": "interesting"}])
    assert not matches(rule, plane(), [])


def test_combined_conditions():
    rule = AlertRule(area=VYSOCINA, aircraft_types=["A124"])
    assert matches(rule, plane(t="A124", lat=49.4, lon=15.6), [])
    assert not matches(rule, plane(t="A124", lat=50.1, lon=14.26), [])
    assert not matches(rule, plane(t="B738", lat=49.4, lon=15.6), [])


# ---------- validation ----------

def test_rule_validation():
    with pytest.raises(ValueError):
        AlertRule()                                    # no condition at all
    with pytest.raises(ValueError):
        AlertRule(min_alt_ft=5000, max_alt_ft=1000)
    with pytest.raises(ValueError):
        AlertRule(area={"lat": 49.4, "lon": 15.6, "radius_nm": -1})
    with pytest.raises(ValueError):
        AlertRule(military=True, color="red")          # unknown field


# ---------- evaluate + dedup ----------

def snapshot(*aircraft, now_ms=NOW_MS):
    return {"now": now_ms, "ac": list(aircraft)}


def test_evaluate_hits_and_dedup():
    rules = {1: AlertRule(military=True), 2: AlertRule(aircraft_types=["A124"])}
    snap = snapshot(plane(hex="mil1", db=1), plane(hex="ant1", t="A124"), plane(hex="civ1"))

    hits = evaluate(rules, snap, [], {})
    assert sorted(hits) == [(1, "mil1"), (2, "ant1")]

    # The caller records hits; within 30 min the same rule+aircraft is skipped.
    last_hits = {h: NOW for h in hits}
    assert evaluate(rules, snapshot(*snap["ac"], now_ms=NOW_MS + 10 * 60_000), [], last_hits) == []

    # A different aircraft for the same rule still fires.
    more = snapshot(plane(hex="mil2", db=1), now_ms=NOW_MS + 60_000)
    assert evaluate(rules, more, [], last_hits) == [(1, "mil2")]

    # After 30 min it fires again.
    later = snapshot(*snap["ac"], now_ms=NOW_MS + 31 * 60_000)
    assert sorted(evaluate(rules, later, [], last_hits)) == [(1, "mil1"), (2, "ant1")]


def test_evaluate_uses_events_per_hex():
    rules = {7: AlertRule(event_types=["emergency"])}
    snap = snapshot(plane(hex="a"), plane(hex="b"))
    events = [{"hex": "b", "type": "emergency"}, {"hex": "a", "type": "holding"}]
    assert evaluate(rules, snap, events, {}) == [(7, "b")]


# ---------- summary ----------

def test_summary_region_and_type():
    s = rule_summary_cs(AlertRule(area=VYSOCINA, aircraft_types=["A124"]))
    assert s == "Upozorním tě na letadlo typu A124, nad Vysočinou."


def test_summary_military_over_cz():
    s = rule_summary_cs(AlertRule(area={"lat": 49.8, "lon": 15.5, "radius_nm": 140}, military=True))
    assert s == "Upozorním tě na vojenské letadlo, nad Českem."


def test_summary_custom_area_altitude_events():
    s = rule_summary_cs(AlertRule(
        area={"lat": 50.0, "lon": 14.0, "radius_nm": 10}, min_alt_ft=1000, max_alt_ft=10000,
        event_types=["holding", "go_around"], min_size_category="A5",
    ))
    assert "do 19 km od bodu 50.00° s. š., 14.00° v. d." in s
    assert "1 000 ft až 10 000 ft" in s
    assert "holding, nepovedené přistání" in s
    assert "těžké" in s


# ---------- parse_rule with a mocked Claude client ----------

class FakeMessages:
    def __init__(self, tool_name, tool_input):
        self.reply = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", name=tool_name, input=tool_input)],
        )
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def fake_client(monkeypatch, tool_name, tool_input):
    messages = FakeMessages(tool_name, tool_input)
    monkeypatch.setattr(alerts, "_get_client", lambda: SimpleNamespace(messages=messages))
    return messages


def test_parse_military_over_cz(monkeypatch):
    fake = fake_client(monkeypatch, "save_rule", {
        "area": {"lat": 49.8, "lon": 15.5, "radius_nm": 140},
        "aircraft_types": None, "min_size_category": None, "military": True,
        "event_types": None, "min_alt_ft": None, "max_alt_ft": None,
    })
    rule = asyncio.run(parse_rule("jakékoli vojenské letadlo nad ČR"))

    assert rule.military is True and rule.area.radius_nm == 140
    assert matches(rule, plane(db=1), [])
    assert not matches(rule, plane(db=0), [])

    req = fake.calls[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["messages"] == [{"role": "user", "content": "jakékoli vojenské letadlo nad ČR"}]
    assert req["tool_choice"] == {"type": "any"}
    assert {t["name"] for t in req["tools"]} == {"save_rule", "cannot_parse"}
    assert "Vysočina: 49.4, 15.6, 40" in req["system"]


def test_parse_an124_over_vysocina(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"area": VYSOCINA, "aircraft_types": ["A124"]})
    rule = asyncio.run(parse_rule("Napiš mi, až nad Vysočinou poletí An-124"))

    assert rule.aircraft_types == ["A124"]
    assert rule_summary_cs(rule) == "Upozorním tě na letadlo typu A124, nad Vysočinou."
    assert matches(rule, plane(t="A124", lat=49.5, lon=15.7), [])
    assert not matches(rule, plane(t="A124", lat=50.1, lon=14.26), [])


def test_parse_cannot_parse(monkeypatch):
    fake_client(monkeypatch, "cannot_parse", {"reason": "Tohle není požadavek na upozornění."})
    with pytest.raises(RuleParseError, match="není požadavek"):
        asyncio.run(parse_rule("jaké bude zítra počasí?"))


def test_parse_invalid_model_output(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"area": {"lat": 49.4, "lon": 15.6, "radius_nm": 0}})
    with pytest.raises(RuleParseError):
        asyncio.run(parse_rule("nad Vysočinou"))


def test_tool_schema_is_json_serializable():
    json.dumps(alerts.TOOLS)


# ---------- ntfy (no real requests) ----------

def test_ntfy_noop_without_topic(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert asyncio.run(notify.send_ntfy("Test", "zpráva")) is False


def test_ntfy_payload(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "skywatch-test")
    sent = []

    def handler(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await notify.send_ntfy("An-124 nad Vysočinou", "UR-82009, 31 000 ft", tags=["airplane"], client=client)

    assert asyncio.run(run()) is True
    url, body = sent[0]
    assert url == "https://ntfy.sh"
    assert body == {"topic": "skywatch-test", "title": "An-124 nad Vysočinou",
                    "message": "UR-82009, 31 000 ft", "tags": ["airplane"]}


def test_ntfy_error_does_not_raise(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "skywatch-test")

    async def run():
        transport = httpx.MockTransport(lambda r: httpx.Response(500))
        async with httpx.AsyncClient(transport=transport) as client:
            return await notify.send_ntfy("x", "y", client=client)

    assert asyncio.run(run()) is False


# ---------- registrations and callsigns ----------

def test_registration_dash_and_case_insensitive():
    rule = AlertRule(registrations=["ok-abc"])
    assert rule.registrations == ["OK-ABC"]
    assert matches(rule, {**plane(), "r": "OK-ABC"}, [])
    assert matches(rule, {**plane(), "r": "okabc"}, [])
    assert not matches(rule, {**plane(), "r": "OK-ABD"}, [])
    assert not matches(rule, plane(), [])                     # no registration in data


def test_callsign_exact_and_prefix():
    exact = AlertRule(callsigns=["csa123"])
    assert matches(exact, {**plane(), "flight": "CSA123  "}, [])  # readsb pads with spaces
    assert not matches(exact, {**plane(), "flight": "CSA1234 "}, [])
    assert not matches(exact, plane(), [])

    airline = AlertRule(callsigns=["TVS*"])
    assert matches(airline, {**plane(), "flight": "TVS4LP  "}, [])
    assert not matches(airline, {**plane(), "flight": "CSA123  "}, [])

    both = AlertRule(callsigns=["CSA123", "TVS*"])
    assert matches(both, {**plane(), "flight": "CSA123"}, [])
    assert matches(both, {**plane(), "flight": "TVS1"}, [])


def test_callsign_validation():
    with pytest.raises(ValueError):
        AlertRule(callsigns=["C*S"])     # star only at the end
    with pytest.raises(ValueError):
        AlertRule(callsigns=["*"])       # too broad
    assert AlertRule(callsigns=["tvs *"]).callsigns == ["TVS*"]


def test_summary_registration_and_callsigns():
    assert rule_summary_cs(AlertRule(registrations=["OK-ABC"])) == \
        "Upozorním tě na letadlo s imatrikulací OK-ABC."
    assert rule_summary_cs(AlertRule(callsigns=["TVS*"])) == \
        "Upozorním tě na letadlo s volačkou začínající TVS."
    assert rule_summary_cs(AlertRule(callsigns=["CSA123", "TVS*"])) == \
        "Upozorním tě na letadlo s volačkou CSA123 nebo s volačkou začínající TVS."


def test_parse_registration(monkeypatch):
    fake = fake_client(monkeypatch, "save_rule", {"registrations": ["OK-ABC"]})
    rule = asyncio.run(parse_rule("dej vědět, až poletí OK-ABC"))
    assert rule.registrations == ["OK-ABC"]
    props = {t["name"]: t for t in fake.calls[0]["tools"]}["save_rule"]["input_schema"]["properties"]
    assert {"registrations", "callsigns", "near_home", "home_radius_nm"} <= props.keys()


def test_parse_airline(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"callsigns": ["TVS*"]})
    rule = asyncio.run(parse_rule("jakýkoli Smartwings"))
    assert matches(rule, {**plane(), "flight": "TVS7TK  "}, [])


# ---------- home ----------

HOME = alerts.Home(lat=50.0755, lon=14.4378, label="Vinohrady")


def test_parse_near_home_uses_home(monkeypatch):
    fake = fake_client(monkeypatch, "save_rule", {"near_home": True, "area": None})
    rule = asyncio.run(parse_rule("dej vědět, až poletí něco nade mnou", home=HOME))

    assert rule.area.lat == HOME.lat and rule.area.lon == HOME.lon
    assert rule.area.radius_nm == alerts.HOME_RADIUS_NM and rule.area.label == "Vinohrady"
    assert rule_summary_cs(rule) == "Upozorním tě na letadlo, do 9 km od místa Vinohrady."
    # The user's address and coordinates never go to Claude.
    assert "50.0755" not in json.dumps(fake.calls[0], default=str)
    assert "Vinohrady" not in json.dumps(fake.calls[0], default=str)


def test_parse_near_home_custom_radius_and_type(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"near_home": True, "home_radius_nm": 10, "military": True})
    rule = asyncio.run(parse_rule("vojenské letadlo do 18 km ode mě", home=HOME))
    assert rule.area.radius_nm == 10 and rule.military is True


def test_parse_near_home_without_home(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"near_home": True})
    with pytest.raises(RuleParseError, match="nastav svou adresu"):
        asyncio.run(parse_rule("cokoli nad domem"))


def test_parse_ignores_label_from_model(monkeypatch):
    fake_client(monkeypatch, "save_rule", {"area": {**VYSOCINA, "label": "Domov"}})
    rule = asyncio.run(parse_rule("nad Vysočinou", home=HOME))
    assert rule.area.label is None and rule.area.lat == 49.4


def test_saved_home_rule_roundtrip():
    """The UI sends the confirmed rule (with area.label) back to POST /api/alerts."""
    rule = AlertRule(area={"lat": HOME.lat, "lon": HOME.lon, "radius_nm": 5, "label": "Vinohrady"})
    again = AlertRule.model_validate_json(rule.model_dump_json())
    assert again == rule
    assert matches(again, plane(lat=50.08, lon=14.44), [])


def test_parse_endpoint_passes_home(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes_core

    seen = []

    async def fake_parse(text, home=None):
        seen.append(home)
        if home is None:
            raise RuleParseError(alerts.NO_HOME_ERROR)
        return AlertRule(area={"lat": home.lat, "lon": home.lon, "radius_nm": 5, "label": home.label})

    monkeypatch.setattr(routes_core, "parse_rule", fake_parse)
    app = FastAPI()
    app.include_router(routes_core.make_router(SimpleNamespace(db=None)))
    client = TestClient(app)

    r = client.post("/api/alerts/parse", json={"text": "nade mnou", "home": HOME.model_dump()})
    assert r.status_code == 200
    assert r.json()["rule"]["area"]["label"] == "Vinohrady"
    assert seen[-1] == HOME

    r = client.post("/api/alerts/parse", json={"text": "nade mnou"})
    assert r.status_code == 422 and "nastav svou adresu" in r.json()["detail"]
