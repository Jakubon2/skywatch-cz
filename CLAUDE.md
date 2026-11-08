# CLAUDE.md

## Projekt

`skywatch-cz`: živá mapa letadel nad Českem s detekcí zajímavých situací, českými AI vysvětleními a alerty zadanými obyčejnou řečí. Celý plán je v `PLAN.md`, drž se ho.

## Jak pracovat

- Postupuj **po fázích z PLAN.md**. Po dokončení každé fáze se zastav, shrň, co je hotové a jak to ověřit, a počkej na potvrzení.
- Jednoduchost má přednost. Žádné zbytečné abstrakce, vrstvy ani knihovny navíc. Když existují dvě cesty, vyber tu kratší a čitelnější.
- Kód, názvy proměnných a komentáře anglicky. **Texty v UI česky.**
- Všechny jednotky v UI, notifikacích i AI textech metrické: výška v m, rychlost v km/h, stoupání v m/s, vzdálenost v km. Data zůstávají interně v ft/kt, převádí se jen pro zobrazení.
- UI je **mobile first**, ale na desktopu musí vypadat stejně krásně. Každou UI změnu ověř na šířce telefonu (375 px) i desktopu, ve světlém i tmavém režimu.
- Prahy detektorů a seznamy typů letadel drž v konfiguraci, ne natvrdo v kódu.
- Detektory piš jako čisté funkce a testuj je (pytest) na nahraných fixtures i syntetických tratích.
- Tajné klíče jen v `.env`, nikdy v repu. Udržuj `.env.example`.

## Externí služby

- adsb.lol: dotaz max každých 10 s, při HTTP 429 exponenciální backoff. V UI vždy atribuce „Data: adsb.lol (ODbL)“.
- Claude API: model `claude-haiku-5-5`, dodržuj strop počtu volání z PLAN.md.
- AI vysvětlení nesmí vymýšlet příčiny. Když nejsou z dat jasné, musí to přiznat.

## Git

- Krátké, věcné commit zprávy.
- **Nikdy nepřidávej `Co-Authored-By: Claude` ani žádné jiné řádky s AI atribucí do commit zpráv.**

## Příkazy

Vše z kořene repa:

- Backend: `cd backend && .venv/bin/uvicorn api:app --reload --timeout-graceful-shutdown 2 --port 8000` (první spuštění: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)
- Frontend: `cd frontend && npm run dev` (port 5173, `/api` proxy na 8000)
- Testy: `cd backend && .venv/bin/pytest`
- Přehrání fixtures přes detektory: `cd backend && .venv/bin/python replay.py ../fixtures/snapshots-*.jsonl.gz`
- Nahrávání fixtures: `cd backend && .venv/bin/python record.py --minutes 30` (neběžet souběžně s backendem)
