# Plán projektu: „Flightradar na steroidech“ (pracovní název `skywatch-cz`)

## Cíl

Webová aplikace (později i mobil jako PWA), která nad živými daty letadel nad Českem nejen ukazuje mapu, ale hlavně:

1. **Detekuje zajímavé situace** (nouzové kódy, holding, nepovedené přistání, vzácná a vojenská letadla).
2. **Vysvětlí je česky pomocí AI** („Letadlo krouží v holdingu nad Berounem, pravděpodobně kvůli mlze na Ruzyni“).
3. **Hlídá alerty zadané obyčejnou řečí** („Napiš mi, až nad Vysočinou poletí An-124“).

Tohle Flightradar24 nedělá. Mapa je jen podklad, hodnota je ve feedu událostí, vysvětleních a alertech.

## Mimo rozsah MVP

- Přepis ATC rádia (nejasná legálnost v ČR, žádný spolehlivý zdroj zvuku). Až po právním ověření.
- Předpověď zpoždění. Až po MVP.
- Uživatelské účty. MVP je pro jednoho uživatele (mě).

---

## Data

### Polohy letadel: adsb.lol (primární)

- Bez klíče, zdarma, data pod licencí **ODbL 1.0** (nutné uvést atribuci „Data: adsb.lol, ODbL“ v UI).
- Endpoint: `GET https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}` (max 250 NM).
- Pro celé Česko stačí jeden dotaz: střed cca `49.8, 15.5`, poloměr `160` NM.
- Interval dotazů: **každých 10 s** (nepřetěžovat, při HTTP 429 exponenciální backoff).
- Užitečná pole: `hex`, `flight` (callsign), `r` (registrace), `t` (typ, např. `A388`), `lat`, `lon`, `alt_baro`, `gs`, `track`, `baro_rate`, `squawk`, `emergency`, `category`, `nav_altitude_mcp`, `dbFlags` (bit 1 = vojenské).
- Pozor: adsb.lol avizoval, že v budoucnu může vyžadovat API klíč. Klient napsat tak, aby šel klíč snadno přidat a aby šlo vyměnit zdroj (stejný formát odpovědí má i airplanes.live a adsb.fi, ty jsou ale jen pro nekomerční použití).

### Počasí: METAR

- `GET https://aviationweather.gov/api/data/metar?ids=LKPR&format=json`
- Stahovat jednou za 10 min, používat jako kontext pro AI vysvětlení (mlha, vítr, nízká oblačnost).

### Letiště a dráhy

- OurAirports (veřejná doména), soubory `airports.csv` a `runways.csv`. Z nich vzít polohu LKPR, nadmořskou výšku (1 247 ft) a prahy drah. **Souřadnice nehardcodovat ručně**, načíst z dat.

---

## Architektura (záměrně jednoduchá)

```
backend/   Python 3.12, FastAPI, SQLite
  poller.py        stahuje snapshot každých 10 s, drží historii tratí v paměti (posledních 15 min na letadlo)
  detectors/       čisté funkce: (historie letadla, kontext) -> událost nebo nic
  explain.py       Claude API: událost + kontext -> česká vysvětlivka
  alerts.py        převod textu na pravidlo (Claude) + vyhodnocování pravidel
  api.py           REST + SSE pro frontend
frontend/  Vite + React + Leaflet
  mapa, feed událostí, správa alertů
```

- Jeden proces backendu (poller běží jako background task ve FastAPI).
- Databáze SQLite, žádné ORM navíc kromě toho, co je nutné.
- Notifikace na mobil přes **ntfy.sh** (stačí HTTP POST, appka ntfy v telefonu). Web push až později.
- AI: Claude API, model `claude-haiku-5-5` pro vysvětlení a převod alertů (levný, rychlý). Klíč v `.env`.

### Datový model (SQLite)

```sql
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,          -- emergency | holding | go_around | interesting
  hex TEXT NOT NULL,
  callsign TEXT,
  aircraft_type TEXT,
  lat REAL, lon REAL, alt_ft INTEGER,
  started_at TEXT NOT NULL,
  data_json TEXT,              -- detaily z detektoru
  explanation TEXT,            -- česká vysvětlivka od AI
  explained_at TEXT
);

CREATE TABLE alert_rules (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,          -- původní zadání uživatele
  rule_json TEXT NOT NULL,     -- strukturované pravidlo
  active INTEGER DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE alert_hits (
  id INTEGER PRIMARY KEY,
  rule_id INTEGER NOT NULL,
  hex TEXT NOT NULL,
  hit_at TEXT NOT NULL
);
```

---

## Detektory (MVP)

Každý detektor je čistá funkce nad historií jednoho letadla. Deduplikace: stejný typ události pro stejné `hex` max jednou za 30 min.

1. **Nouze**: `squawk` v {7700, 7600, 7500} nebo `emergency != "none"`.
   - 7500 (únos) zobrazovat s upozorněním „často jde o chybu nebo test, neověřeno“.
2. **Holding**: v posledních 8 min součet absolutních změn kurzu ≥ 330°, letadlo se nevzdálilo o víc než 15 NM od začátku okna, výška > 3 000 ft a kolísá méně než ±1 000 ft.
3. **Nepovedené přistání (go-around)**: do 6 NM od LKPR, výška pod ~2 000 ft nad letištěm, předtím klesání (`baro_rate < -300`), pak aspoň dva po sobě jdoucí vzorky stoupání (`baro_rate > +800`), nárůst výšky ≥ 400 ft a mezitím ani jednou `on_ground`. Označovat jako „pravděpodobné“.
4. **Zajímavé letadlo**: typ ze seznamu v `config/interesting_types.yaml` (např. A388, A124, B748, C17, A400, AN22), nebo vojenské (`dbFlags & 1`), nebo typ, který se v datech za posledních 30 dní neobjevil.

Prahy (ty čísla výše) držet v jednom konfiguračním souboru, budou se ladit na reálných datech.

---

## AI vysvětlení

- Vstup pro Claude: typ události, callsign, typ letadla, souhrn trati za posledních 10 min (pár bodů, ne celé raw data), aktuální METAR LKPR, čas.
- Výstup: 1–3 věty česky, pro laika.
- Systémový prompt musí vyžadovat poctivost: **nevymýšlet příčiny**, když nejsou z dat jasné, napsat „důvod z dat nepoznáme“ a příčiny formulovat jako pravděpodobné („nejspíš“, „může jít o“).
- Strop: max 30 vysvětlení za hodinu, aby nevyletěly náklady. Nad strop se událost uloží bez vysvětlení.
- V UI u každého vysvětlení štítek „vysvětlení od AI, neověřeno“.

---

## Alerty obyčejnou řečí

1. Uživatel napíše text („Upozorni mě, když nad Vysočinou poletí cokoli většího než A350“).
2. Claude ho převede na JSON podle pevného schématu:
   ```json
   {
     "area": {"lat": 49.4, "lon": 15.6, "radius_nm": 40},
     "aircraft_types": ["A124"],
     "min_size_category": null,
     "military": null,
     "event_types": null,
     "min_alt_ft": null,
     "max_alt_ft": null
   }
   ```
3. JSON se validuje (pydantic). UI ukáže, jak pravidlo pochopil, a uživatel ho **potvrdí** před uložením.
4. Při každém pollu se aktivní pravidla vyhodnotí. Zásah = záznam v `alert_hits` + notifikace přes ntfy (max jednou za 30 min na pravidlo a letadlo).

Regiony jako „Vysočina“ převádět na střed + poloměr (jednoduše, žádné polygony v MVP).

---

## Fáze a hotovo-když

### Fáze 0: Kostra a data
- Repo, `backend/` a `frontend/`, `.env.example`, README se spuštěním.
- Poller stahuje adsb.lol každých 10 s a loguje počet letadel.
- Skript `record.py`, který 30 minut ukládá snapshoty do `fixtures/` (pro testy a ladění detektorů).
- **Hotovo, když:** poller běží a v logu je rozumný počet letadel nad ČR, existuje aspoň 30 minut nahraných dat.

### Fáze 1: Detektory
- Všechny 4 detektory + konfigurace prahů.
- Testy (pytest) nad nahranými fixtures a nad ručně vyrobenými syntetickými tratěmi (kruh = holding, stoupání po klesání u LKPR = go-around).
- Ukládání událostí do SQLite.
- **Hotovo, když:** testy procházejí a přehrání hodiny nahraných dat vyprodukuje rozumný počet událostí (ne stovky falešných).

### Fáze 2: AI vysvětlení + API
- `explain.py` s Claude API, METAR kontext, strop na počet volání.
- FastAPI: `GET /api/aircraft` (poslední snapshot), `GET /api/events`, `GET /api/stream` (SSE s novými událostmi).
- **Hotovo, když:** nová událost se do pár sekund objeví v `/api/events` i s českým vysvětlením.

### Fáze 3: Webový dashboard
- Mapa (Leaflet) s letadly, ikona podle kurzu, klik = detail.
- Postranní feed „Co se teď děje nad Českem“ s vysvětleními, klik na událost = přiblížení na letadlo.
- Atribuce dat adsb.lol (ODbL) v patičce.
- Funguje na mobilu (responzivní).
- **Hotovo, když:** dashboard v prohlížeči i na telefonu ukazuje živá letadla a feed událostí.

### Fáze 4: Alerty
- Formulář na zadání alertu, zobrazení pochopeného pravidla, potvrzení, seznam alertů s možností vypnout.
- Vyhodnocování v pollu, notifikace přes ntfy.sh.
- **Hotovo, když:** testovací alert (např. „jakékoli vojenské letadlo nad ČR“) pošle notifikaci do telefonu.

### Fáze 5: PWA
- Manifest, ikony, service worker (offline shell, data vždy živě), instalace na plochu telefonu, iOS meta tagy.
- **Hotovo, když:** appka jde nainstalovat na telefon a otevře se na celou obrazovku.

### Fáze 6: Co mi letí nad hlavou
- Každý si nastaví vlastní adresu (nebo „použít moji polohu“), uloží se jen v jeho zařízení (localStorage), žádné účty.
- Geokódování adresy přes backend (Nominatim/OSM s cache a dodržením usage policy).
- Seznam letadel v okolí adresy seřazený podle vzdálenosti: volačka, typ, výška, kam letí, za jak dlouho bude nejblíž.
- **Hotovo, když:** po zadání adresy vidím letadla nad ní a klik na letadlo ho ukáže na mapě.

### Fáze 7: Chat nad živými daty
- `POST /api/chat`: Claude (`claude-haiku-5-5`) s nástroji nad posledním snapshotem a událostmi („kolik Ryanairů je teď nad ČR?“, „co krouží nad Berounem?“).
- Odpovídá jen z dat, nevymýšlí; když data odpověď nedávají, řekne to. Strop počtu volání za hodinu v konfiguraci.
- **Hotovo, když:** na otázky o aktuálním provozu odpovídá česky a čísla sedí s `/api/aircraft`.

### Fáze 8: Rozšíření
- **Feed, detail, přehledy:** feed událostí s živým streamem, správa alertů v UI; trasa letu, fotka (planespotters) a stopa v detailu; filtry na mapě; statistiky; přehrávání historie posuvníkem; denní a týdenní AI souhrn; vyhledávání v historii událostí.
- **Detektory:** go-around i na LKTB, LKMT, LKPD; prudký sestup; návrat/odklon; kroužící vrtulník.
- **Mobil:** „Co je to za letadlo?“ (poloha + natočení telefonu); web push z PWA místo ntfy; haptika a zvuk při nouzi a alertu.
- **Chytřejší alerty:** konkrétní registrace nebo volačka; alert nad vlastní adresou (adresa se serveru předá jen v pravidle, které uživatel sám uloží); předpověď přeletů z historie.
- **Zajímavosti:** odhad hluku nad adresou; předpověď kondenzačních stop (výškové počasí); sdílení události odkazem nebo obrázkem.
- **Nasazení:** jedna VPS (docker compose + Caddy), přístup chráněný tokenem. Viz `docs/deploy.md`.

### Potom (backlog)
- Předpověď zpoždění příletů do Prahy podle polohy letadla.
- Nasazení: backend na malé VPS (docker compose), frontend na Vercel.
- ATC přepis, až po ověření legálnosti.

---

## Otevřené otázky

- Komerční využití: adsb.lol je pod ODbL (komerčně použitelné s atribucí), ostatní zdroje jen nekomerčně. Před případnou monetizací ověřit aktuální podmínky.
- Legálnost poslechu a zveřejňování ATC v ČR (ČTÚ).
