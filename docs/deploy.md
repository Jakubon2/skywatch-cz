# Nasazení na VPS

Cíl: appka (i PWA na telefonu) běží i mimo domácí Wi-Fi, na vlastní doméně s HTTPS a chráněná tokenem.

## Zvolená cesta: jedna VPS, Caddy + backend v docker compose

```
telefon / prohlížeč ──HTTPS──▶ Caddy (:443)
                                 ├─ /api/*  ──▶ backend:8000 (FastAPI + poller, SQLite v ./data)
                                 └─ ostatní ──▶ build frontendu (/srv)
```

- **Jeden server, jedna doména, jeden `docker compose up`.** Frontend i API jsou na stejném originu, takže relativní `/api/...` funguje beze změny kódu, nejsou potřeba CORS ani cookies přes domény.
- **SSE (`/api/stream`) jde přímo přes Caddy** s `flush_interval -1` a bez komprese, události chodí okamžitě. Spojení může být otevřené libovolně dlouho.
- **PWA:** `sw.js` a `manifest.webmanifest` z `frontend/public/` se servírují ze stejného originu, service worker má scope `/` a obal aplikace se cachuje jako doteď.
- **Cena:** jen VPS (zhruba 6 € měsíčně) a doména.

Soubory: [`docker-compose.yml`](../docker-compose.yml), [`backend/Dockerfile`](../backend/Dockerfile), [`deploy/Caddyfile`](../deploy/Caddyfile). Frontend se builduje přímo v compose (Node stage, výsledek se zkopíruje do image Caddy), na serveru tedy není potřeba Node.

### Proč ne Vercel (původní nápad z backlogu)

Vercel pro frontend a VPS pro backend znamená dvě nasazení, dvě místa pro ochranu přístupu a buď CORS a cookies přes dvě domény, nebo proxy `/api` přes externí rewrite na Vercelu. U toho rewritu není zdokumentované, jak se chová u dlouho otevřeného SSE streamu. Čekání na odpověď originu má limit (aktuálně 120 s) a chování u streamu by se muselo vyzkoušet. VPS je potřeba tak jako tak a Caddy na ní obslouží statické soubory zadarmo. Vercel by dával smysl, jen kdyby frontend potřeboval globální CDN, a to osobní appka nepotřebuje.

## Ochrana přístupu

Chat, alerty a AI vysvětlení stojí peníze za Claude API a data jsou osobní, takže **bez tokenu nejde nic kromě metadat PWA** (manifest, ikony, `sw.js`, favicon). Ty se nechávají veřejné, protože prohlížeč manifest a ikony stahuje bez cookies a s ochranou by instalace PWA selhala.

**Jak to funguje:** Caddy porovná cookie `skywatch_token` s hodnotou `SKYWATCH_TOKEN` z `.env`. Bez platné cookie vrátí malou přihlašovací stránku (HTTP 401) a na `/api/*` jen `401 Nepřihlášeno`. Po zadání tokenu nastaví `/login` cookie (HttpOnly, Secure, platnost 1 rok) a přesměruje na `/`. Skripty a curl mohou místo cookie poslat hlavičku `Authorization: Bearer <token>`. Aplikační kód se nemění, všechno je v Caddyfile.

### Proč ne HTTP basic auth

Basic auth by byl jeden řádek v Caddyfile, jenže:

- **iPhone, PWA na ploše:** webové appky přidané na plochu iOS mají s dialogem basic auth dlouhou historii problémů (dialog se nezobrazí, appka se po přihlášení zasekne, při dalším spuštění se ptá znovu). Hlášení jsou starší a podle verzí iOS se to opravovalo a znovu rozbíjelo, spolehnout se na to nedá.
- **Instalace PWA:** manifest a ikony se stahují bez přihlašovacích údajů. Za basic auth by dostaly 401, a pokud by se nevyjmuly, Chrome appku nenabídne k instalaci.
- **SSE:** `EventSource` neumí na 401 zobrazit dialog, spoléhá na to, že prohlížeč údaje už má.
- Odhlášení nebo výměna hesla v prohlížeči jsou nepohodlné.

Token v cookie tyhle problémy nemá: přihlašovací stránka je obyčejná HTML stránka, takže funguje i uvnitř nainstalované PWA bez adresního řádku.

### Co čekat na telefonu

- **Android (Chrome):** přihlas se v prohlížeči a pak „Instalovat aplikaci“. Nainstalovaná appka sdílí cookies s Chromem, znovu se přihlašovat nemusíš.
- **iPhone (Safari):** přihlas se v Safari a pak Sdílet → „Přidat na plochu“. Appka na ploše může mít vlastní úložiště cookies oddělené od Safari. Když se po prvním spuštění ukáže přihlašovací stránka, zadej token ještě jednou, tentokrát přímo v appce. Cookie nastavuje server, takže se na ni nevztahuje 7denní limit Safari pro cookies nastavené JavaScriptem. Pole tokenu je typu heslo, Klíčenka ho tedy může uložit.
- **Ověřit na skutečném zařízení:** po nasazení zkontroluj v nainstalované PWA přihlášení, živou mapu, chat, živé události (SSE) a to, že po zavření a znovuotevření appky zůstaneš přihlášený. Na reálném iPhonu to zatím odzkoušené není.

### Výměna tokenu

Změň `SKYWATCH_TOKEN` v `.env` a spusť `docker compose up -d`. Caddy se restartuje se starou cookie neplatnou a všechna zařízení se musí přihlásit znovu. Otevřená appka uvidí na `/api` odpovědi 401, stačí ji obnovit.

## Krok za krokem

### 1. VPS

- **Doporučení: Hetzner Cloud CX23** (2 vCPU, 4 GB RAM, 40 GB SSD, 20 TB přenosů; nahradil CX22). Po zdražení od 15. 6. 2026 stojí zhruba **5,49 € měsíčně + 0,50 € za IPv4, bez DPH**. Ceny i dostupnost se mění, ověř je na <https://www.hetzner.com/cloud>. Když CX23 nejde objednat, vezmi **CAX11** (ARM, podobná cena), protože použité Docker image běží i na ARM. Appce stačí i menší stroj, poller a SQLite skoro nic nepotřebují.
- Lokalita: Falkenstein nebo Norimberk (nejblíž ČR).
- Image: **Ubuntu 24.04**. Přihlášení **jen SSH klíčem**.
- **Firewall** (Hetzner Cloud Firewall): povolit dovnitř TCP 22, 80, 443 a UDP 443, nic jiného.
- Volitelně **zálohy Hetzner** (+20 % ceny serveru, denní snapshot celého disku).

Alternativy za podobné peníze: Contabo, OVH VPS, Wedos (ČR). Postup je stejný na jakémkoli Linuxu s Dockerem.

### 2. Doména a DNS

U registrátora domény vytvoř záznam:

```
skywatch.tvoje-domena.cz.   A      <IPv4 serveru>
skywatch.tvoje-domena.cz.   AAAA   <IPv6 serveru>   (volitelně)
```

Počkej, až se záznam rozšíří (`dig +short skywatch.tvoje-domena.cz` vrací IP serveru). Teprve potom spusť Caddy, jinak se mu nepodaří získat certifikát.

Bez vlastní domény jde použít `<ip-s-pomlckami>.sslip.io` (např. `203-0-113-7.sslip.io`). Funguje bez nastavování a Let's Encrypt na ni certifikát vydá, ale limity certifikátů sdílí se všemi uživateli sslip.io.

### 3. Docker na serveru

```bash
ssh root@<IP>
curl -fsSL https://get.docker.com | sh
docker compose version
```

### 4. Kód a `.env` na server

Repo zatím nemá vzdálený remote. Buď ho dej do soukromého repa na GitHubu a na serveru udělej `git clone`, nebo ho pošli rsyncem z Macu (z kořene repa):

```bash
rsync -av --exclude .git --exclude .venv --exclude node_modules --exclude dist \
  --exclude /data --exclude /.env --exclude /fixtures ./ root@<IP>:/opt/skywatch/
```

Na serveru:

```bash
cd /opt/skywatch
cp .env.example .env
nano .env        # ANTHROPIC_API_KEY, NTFY_TOPIC, DOMAIN, SKYWATCH_TOKEN
openssl rand -hex 32   # vygeneruje SKYWATCH_TOKEN
mkdir -p data && chown 1000:1000 data   # backend běží v kontejneru jako uid 1000
```

Když chceš převzít dosavadní databázi a CSV z OurAirports, zkopíruj `data/` z Macu (`rsync -av data/ root@<IP>:/opt/skywatch/data/`) a znovu spusť `chown -R 1000:1000 data`. CSV se jinak stáhnou samy při prvním startu.

### 5. První spuštění

```bash
docker compose up -d --build
docker compose logs -f
```

V logu backendu má každých 10 s přibýt řádek s počtem letadel a Caddy má hlásit `certificate obtained successfully`. Pak otevři `https://skywatch.tvoje-domena.cz`, zadej token a nainstaluj PWA (viz výše).

Rychlý test z Macu:

```bash
curl -i https://skywatch.tvoje-domena.cz/api/health                     # 401
curl -s -H "Authorization: Bearer <token>" https://skywatch.tvoje-domena.cz/api/health
curl -N -H "Authorization: Bearer <token>" https://skywatch.tvoje-domena.cz/api/stream   # každých 15 s ": ping"
```

> **adsb.lol:** smí se ptát nejvýš jednou za 10 s. Když běží backend na serveru, nenechávej zároveň dlouho běžet lokální backend ani `record.py`, ať se dotazy nezdvojují.

### 6. Aktualizace

```bash
# na Macu: rsync jako v kroku 4 (nebo na serveru: git pull)
ssh root@<IP> 'cd /opt/skywatch && docker compose up -d --build'
```

Přebuildují se jen změněné části. Backend se restartuje (krátký výpadek pollingu, živá spojení SSE se samy obnoví). PWA si nový frontend načte při dalším otevření s internetem. Změna jen v `config/*.yaml`: stačí `docker compose restart backend`, protože config je do kontejneru připojený, ne zabalený v image.

Úklid starých image občas: `docker image prune -f`.

### 7. Zálohy SQLite

Databáze je v `/opt/skywatch/data/skywatch.db`. Za běhu ji nekopíruj přes `cp`, použij online zálohu SQLite:

```bash
cd /opt/skywatch
docker compose exec -T backend python -c "import sqlite3, os; os.makedirs('/app/data/backup', exist_ok=True); sqlite3.connect('/app/data/skywatch.db').backup(sqlite3.connect('/app/data/backup/skywatch-$(date +%F).db'))"
```

Denně ve 3:30 přes cron (`crontab -e` na serveru), se smazáním záloh starších než 14 dní:

```
30 3 * * * cd /opt/skywatch && docker compose exec -T backend python -c "import sqlite3, os; os.makedirs('/app/data/backup', exist_ok=True); sqlite3.connect('/app/data/skywatch.db').backup(sqlite3.connect('/app/data/backup/skywatch-$(date +\%F).db'))" && find data/backup -name '*.db' -mtime +14 -delete
```

Záloha mimo server (z Macu, třeba jednou týdně):

```bash
rsync -av root@<IP>:/opt/skywatch/data/backup/ ~/skywatch-backup/
```

Obnova: `docker compose stop backend`, nahraj soubor jako `data/skywatch.db`, `chown 1000:1000 data/skywatch.db`, `docker compose start backend`.

### 8. Logy

```bash
docker compose logs -f backend          # poller, detektory, Claude, ntfy
docker compose logs --tail 200 caddy    # certifikáty, chyby proxy
docker compose ps                       # co běží
```

Logy se rotují (3 × 10 MB na službu). Přístupový log Caddy je vypnutý. Pokud ho zapneš (`log` v Caddyfile), objeví se v něm i `/login?token=...`.

## Shrnutí proměnných v `.env`

| Proměnná | K čemu |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API (vysvětlení, chat, alerty) |
| `ADSB_API_KEY` | volitelné, pokud ho adsb.lol začne vyžadovat |
| `NTFY_TOPIC` | téma ntfy.sh pro alerty |
| `DOMAIN` | doména pro Caddy, např. `skywatch.tvoje-domena.cz` |
| `SKYWATCH_TOKEN` | přístupový token, `openssl rand -hex 32` |
