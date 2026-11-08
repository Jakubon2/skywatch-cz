# Volitelné vrstvy mapy: radar, blesky, vzdušné prostory, NOTAMy

*Rešerše k 8. 11. 2026. Toto není právní rada. Podmínky zdrojů se mění, před veřejným nasazením je potřeba je znovu zkontrolovat.*

Implementace: `backend/airspace.py` (`/api/airspace`, `/api/radar`), `frontend/src/MapLayers.jsx` (vrstvy a přepínač), nastavení v `config/config.yaml` → `map_layers`.

## Srážkový radar: RainViewer ✅

- Zdroj: veřejné API `https://api.rainviewer.com/public/weather-maps.json`, bez klíče. Backend z něj vybere nejnovější snímek a vrátí šablonu URL dlaždic (cache 5 min).
- Podmínky: bezplatné API je jen pro osobní a vzdělávací použití a vyžaduje atribuci. Atribuce „Radar: RainViewer“ se zobrazí v rohu mapy, když je vrstva zapnutá.
- Omezení bezplatné verze: barevné schéma jen „Universal Blue“ (`color_scheme: 2`). Dlaždice nad zoomem 7 vracely stejný zástupný obrázek, proto `max_native_zoom: 7` a Leaflet je při větším přiblížení zvětšuje. Pokud RainViewer limity uvolní, stačí změnit konfiguraci.
- Komerční nasazení by potřebovalo placený tarif nebo jiný zdroj.

## Blesky: vynecháno ❌

- **Blitzortung.org / LightningMaps.org**: data jsou určená jen účastníkům sítě (provozovatelům stanic) nebo těm, komu to projekt výslovně povolí. LightningMaps zakazuje vkládat své mapy a surová data do cizích webů (iframe apod.). Neoficiální WebSocket stream nejde použít bez písemného souhlasu. Pokud by uživatel provozoval vlastní stanici Blitzortung, nekomerční použití na webu je podle vyjádření na fóru možné. To ale není formální licence.
- **EUMETSAT MTG Lightning Imager** (Meteosat-12, provozně od 31. 10. 2024): data jsou dostupná přes EUMETCast a Data Store po registraci. Podle datové politiky EUMETSAT mají produkty licence podle kategorie a u neesenciálních dat je redistribuce původních dat zakázaná. U produktů LI jsem nenašel jasné potvrzení, že je smí volně zobrazovat veřejná webová aplikace. Navíc jde o satelitní detekci s nižším prostorovým rozlišením, takže pro „blesky nad Českem“ je méně vhodná.
- **ČHMÚ**: neověřeno. Jestli ČHMÚ poskytuje data detekce blesků jako otevřená data, by bylo potřeba zjistit přímo u nich.
- Závěr: žádný bezplatný zdroj s podmínkami, které by jasně povolovaly zobrazení v osobní webové aplikaci. Vrstva se nepřidala. Až to bude potřeba, nejschůdnější cesta je žádost o svolení u Blitzortung (případně vlastní stanice), nebo ověření licence MTG LI přímo u EUMETSAT.

## Vzdušné prostory: openAIP ✅

- Zdroj: openAIP, licence **CC BY-NC 4.0** (nekomerční použití s atribucí, na mapě „Vzdušné prostory: openAIP (CC BY-NC 4.0)“). V popupu je upozornění, že údaje nejsou pro navigaci.
- Dvě cesty se stejným schématem:
  1. Bez klíče: veřejný export celé země `https://storage.openaip.net/openaip-system-exports/cz_asp.geojson`. Je to subdoména openAIP. Původní bucket na Google Cloud Storage teď vrací chybu „requester pays“ a bez účtu nefunguje.
  2. S klíčem: REST API `https://api.core.openaip.net/api/airspaces?country=CZ` s hlavičkou `x-openaip-api-key`. Zapne se, když je v `.env` nastavené `OPENAIP_API_KEY` (klíč zdarma po registraci na openaip.net).
- Stahuje se celá země jednou za 24 h, nikdy po výřezech mapy. Výsledek se ukládá i na disk (`data/airspace_cz.json`), takže restart nestahuje znovu.
- Zobrazené typy (`map_layers.airspace.types`): CTR, MCTR, ATZ, TMA, CTA, P, R, D, TRA, TSA, RMZ, TMZ. Vynechané jsou plachtařské sektory, výsadkové zóny a FIR, které by mapu zahltily. Aktuálně jde o 239 zón.
- ŘLP ČR AIM: AIP ČR je veřejně jako PDF (ENR 5.1 atd.), ale ne jako strojově čitelná data. Převod z PDF by byla křehká ruční práce, openAIP ta data už má.

## NOTAMy a aktivace TRA/TSA: nezahrnuto ⚠️

- ŘLP ČR nemá veřejné API ani otevřený datový výstup NOTAMů. Briefing (IBS, PIB) je určený pilotům a jeho strojové stahování by bylo scrapování.
- Aktivace TRA/TSA na konkrétní den se publikuje v AUP/UUP přes EUROCONTROL Network Manager (B2B služby vyžadují smlouvu).
- Komerční NOTAM API (Aviation Edge, DTN apod.) jsou placená. FAA NOTAM API jsem neověřoval.
- Mapa proto ukazuje jen statické hranice zón. U zón, které openAIP označuje příznakem `byNotam`, popup napíše „Aktivuje se NOTAMem“. TRA/TSA jsou kreslené čárkovaně jako „dočasné“.
