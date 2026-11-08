from metar_api import decode, decode_visibility, decode_weather, decode_wind

OBS = {
    "icaoId": "LKPR", "obsTime": 1794157200, "temp": 1, "dewp": -1, "wdir": 160, "wspd": 3,
    "visib": 5.59, "altim": 1025, "fltCat": "VFR",
    "rawOb": "METAR LKPR 081700Z 16003KT 080V190 9000 FEW011 01/M01 Q1025 NOSIG",
    "clouds": [{"cover": "FEW", "base": 1100}],
}


def test_decode_real_observation():
    d = decode(OBS)
    assert d["name"] == "Letiště Praha-Ruzyně"
    assert d["observed"] == 1794157200000
    assert d["wind"]["text"] == "Slabý vítr od jihu, 2 m/s (6 km/h)"
    assert d["visibility"] == {"m": 9000, "text": "9 km"}
    assert d["clouds_text"] == "Ojedinělá oblačnost ve 340 m"
    assert d["pressure_hpa"] == 1025 and d["humidity"] == 87
    assert d["summary"] == "1 °C, ojedinělá oblačnost ve 340 m"
    assert d["weather"] == []


def test_fog_rain_cb_and_cavok():
    raw = "METAR LKPR 080600Z 24015G28KT 0300 +TSRA FG BKN008CB OVC020 05/05 Q0998"
    d = decode({**OBS, "rawOb": raw, "wxString": "+TSRA FG", "wdir": 240, "wspd": 15, "wgst": 28, "temp": 5, "dewp": 5,
                "clouds": [{"cover": "BKN", "base": 800}, {"cover": "OVC", "base": 2000}]})
    assert d["weather"] == ["Bouřka: déšť (silná intenzita)", "Mlha"]
    assert d["visibility"]["text"] == "0,3 km"
    assert d["clouds"][0]["type"] == "bouřkové mraky"
    assert d["wind"]["text"].startswith("Mírný vítr od jihozápadu, 8 m/s") and "v nárazech 14 m/s" in d["wind"]["text"]
    assert d["summary"] == "5 °C, bouřka: déšť (silná intenzita)"
    assert decode_visibility("METAR LKPR 081200Z 00000KT 4000 RA")["text"] == "4 km"
    assert decode_visibility("METAR LKPR 081200Z 00000KT CAVOK 10/02 Q1020")["m"] == 10000
    assert decode({**OBS, "rawOb": "METAR LKPR 081200Z VRB02KT CAVOK 10/02 Q1020", "clouds": []})["clouds_text"].startswith("Bez oblačnosti")


def test_weather_codes_and_calm():
    assert decode_weather("-DZ BR VCSH FZFG -SHSN") == [
        "Mrholení (slabá intenzita)", "Kouřmo", "Přeháňky v okolí", "Mrznoucí mlha", "Přeháňky: sníh (slabá intenzita)"]
    assert decode_wind(0, 0, None)["text"] == "Bezvětří"
    assert decode_wind("VRB", 4, None)["text"].startswith("Slabý vítr proměnlivého směru")
