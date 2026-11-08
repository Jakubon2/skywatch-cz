from airspace import format_limit, latest_radar, parse

TYPES = {4: "CTR", 7: "TMA", 1: "R", 8: "TRA"}
SQUARE = {"type": "Polygon", "coordinates": [[[14.1234567, 50.1], [14.3, 50.1], [14.3, 50.2], [14.1234567, 50.1]]]}


def feature(name, type_, lower, upper, icao=3, **extra):
    # Same shape as the openAIP export (properties) and API items (flat).
    return {"type": "Feature", "geometry": SQUARE,
            "properties": {"name": name, "type": type_, "icaoClass": icao, "lowerLimit": lower, "upperLimit": upper, **extra}}


GND = {"value": 0, "unit": 1, "referenceDatum": 0}


def test_format_limit():
    assert format_limit(GND) == "zem"
    assert format_limit({"value": 5000, "unit": 1, "referenceDatum": 1}) == "1 520 m n. m."
    assert format_limit({"value": 500, "unit": 1, "referenceDatum": 0}) == "150 m nad zemí"
    assert format_limit({"value": 95, "unit": 6, "referenceDatum": 2}) == "FL95 ≈ 2 900 m"
    assert format_limit({"value": 300, "unit": 0, "referenceDatum": 0}) == "300 m nad zemí"
    assert format_limit(None) == "neuvedeno"


def test_parse_filters_types_and_labels_in_czech():
    items = [
        feature("TMA I PRAHA", 7, {"value": 3500, "unit": 1, "referenceDatum": 1}, {"value": 95, "unit": 6, "referenceDatum": 2}),
        feature("CTR PRAHA", 4, GND, {"value": 3500, "unit": 1, "referenceDatum": 1}),
        feature("DROPZONE JAROMER", 28, GND, {"value": 95, "unit": 6, "referenceDatum": 2}, icao=8),  # not in TYPES
        feature("LKR1 TEMELIN", 1, GND, {"value": 4500, "unit": 1, "referenceDatum": 1}, icao=8),
    ]
    out = parse(items, TYPES)
    assert [f["properties"]["name"] for f in out][-1] == "TMA I PRAHA"  # sorted by lower limit
    names = {f["properties"]["name"]: f["properties"] for f in out}
    assert "DROPZONE JAROMER" not in names
    ctr = names["CTR PRAHA"]
    assert ctr["kind"] == "CTR" and ctr["kind_name"] == "Řízený okrsek" and ctr["icao_class"] == "D"
    assert ctr["lower"] == "zem" and ctr["upper"] == "1 070 m n. m."
    assert names["LKR1 TEMELIN"]["icao_class"] is None and names["LKR1 TEMELIN"]["kind_name"] == "Omezený prostor"
    assert out[0]["geometry"]["coordinates"][0][0] == [14.12346, 50.1]


def test_parse_accepts_api_items_and_string_type_keys():
    item = {"name": "TRA GA1", "type": 8, "icaoClass": 8, "byNotam": True, "geometry": SQUARE,
            "lowerLimit": GND, "upperLimit": {"value": 65, "unit": 6, "referenceDatum": 2}}
    out = parse([item, {"name": "no geometry", "type": 8}], {"8": "TRA"})
    assert len(out) == 1 and out[0]["properties"]["by_notam"] is True and out[0]["properties"]["kind"] == "TRA"


def test_latest_radar_frame():
    maps = {"host": "https://tilecache.rainviewer.com", "radar": {"past": [
        {"time": 100, "path": "/v2/radar/a"}, {"time": 300, "path": "/v2/radar/c"}, {"time": 200, "path": "/v2/radar/b"}]}}
    assert latest_radar(maps, 2) == {"time": 300, "url": "https://tilecache.rainviewer.com/v2/radar/c/256/{z}/{x}/{y}/2/1_1.png"}
    assert latest_radar({"host": "x", "radar": {"past": []}}, 2) is None
