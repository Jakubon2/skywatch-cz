# skywatch-cz: vývoj (česky)

Živá mapa letadel nad Českem s detekcí zajímavých situací, českými AI vysvětleními a alerty zadanými obyčejnou řečí. Plán je v [PLAN.md](../PLAN.md).

Data: [adsb.lol](https://adsb.lol) (ODbL 1.0). Mapa: © OpenStreetMap.

## Požadavky

- Python 3.12+ (ověřeno na 3.14)
- Node 20+

## Spuštění

```bash
cp .env.example .env
```

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api:app --reload --timeout-graceful-shutdown 2 --port 8000
```

Poller se spustí s aplikací a každých 10 s loguje počet letadel. Stav: <http://127.0.0.1:8000/api/health>.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Otevři <http://localhost:5173>. Vite běží i na lokální síti, takže jde otevřít z telefonu na stejné Wi-Fi (adresu vypíše `npm run dev`). Požadavky na `/api` jdou přes proxy na backend.

### Nahrání fixtures

```bash
cd backend
.venv/bin/python record.py --minutes 30
```

Uloží snapshoty do `fixtures/snapshots-YYYYMMDD-HHMM.jsonl.gz` (jeden JSON na řádek). Nespouštěj zároveň s backendem, jinak se na adsb.lol posílají dva dotazy za 10 s.

Shrnutí nahrávky (funguje i na rozepsaném souboru):

```bash
cd backend
.venv/bin/python fixtures.py ../fixtures/snapshots-*.jsonl.gz
```

### Přehrání nahrávky přes detektory

```bash
cd backend
.venv/bin/python replay.py ../fixtures/snapshots-*.jsonl.gz
```

Vypíše události, které by detektory vyrobily (databáze jen v paměti, bez sítě). Prahy se ladí v `config/detectors.yaml`.

### Testy

```bash
cd backend
.venv/bin/pytest
```

### PWA (instalace na telefon)

Service worker se registruje jen v produkčním buildu, ve `npm run dev` neběží. Lokální ověření:

```bash
cd frontend
npm run build && npm run preview
```

- `public/sw.js` drží offline jen obal aplikace (HTML, JS, CSS, ikony). `/api/*` i mapové dlaždice jdou vždy ze sítě. Nový deploy se načte při dalším otevření s internetem, nic se nemusí verzovat.
- Ikony v `public/icons/` se generují z návrhu favicony: `sh scripts/make-icons.sh` (macOS, používá vestavěný `sips`).
- Instalace: Android Chrome nabídne „Instalovat aplikaci“, na iPhonu Safari → Sdílet → „Přidat na plochu“. Instalace z telefonu vyžaduje HTTPS (localhost je výjimka), takže přes IP adresu v síti Wi-Fi se appka nenainstaluje, jen otevře.

## Nasazení

Produkčně běží na jedné VPS: `docker compose up -d --build` spustí backend a Caddy, který servíruje build frontendu, proxuje `/api` (včetně SSE), sám vyřídí HTTPS a chrání appku tokenem (`SKYWATCH_TOKEN` v `.env`). Postup krok za krokem (VPS, DNS, aktualizace, zálohy, logy, PWA na iPhonu): [docs/deploy.md](deploy.md).

## Konfigurace

- `config/config.yaml`: zdroj dat, střed a poloměr oblasti, interval a backoff pollingu, délka historie. Prahy detektorů jsou v `config/detectors.yaml`, seznam zajímavých typů v `config/interesting_types.yaml`. Letiště a dráhy se stahují z OurAirports do `data/`.
- `.env`: tajné klíče (viz `.env.example`).
- `frontend/.env`: volitelně jiné mapové dlaždice (viz `frontend/.env.example`).
