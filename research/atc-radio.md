# ATC rádio v skywatch-cz: legálnost a technické řešení

*Rešerše k 8. 11. 2026. **Toto není právní rada.** Jde o rešerši z veřejných zdrojů. Tam, kde je to v textu označeno jako nejasné, je potřeba se zeptat ČTÚ nebo advokáta.*

Značení jistoty:
- **[JISTÉ]**: doslovně stojí v předpisu (citace níže).
- **[VÝKLAD]**: můj výklad. Rozumný, ale nepotvrzený soudem ani úřadem.
- **[NEOVĚŘENO]**: nenašel jsem primární zdroj.

---

## Verdikt v kostce

| # | Případ užití | Verdikt | Jistota |
|---|---|---|---|
| 1 | Soukromý poslech (SDR doma) | **Pravděpodobně legální.** ČR nemá obecný zákaz poslechu rádiových zpráv, jaký má třeba Německo. | střední až vysoká, [VÝKLAD] |
| 2 | Nahrávání a ukládání zvuku pro sebe | **Pravděpodobně legální**, pokud nahrávky zůstanou jen u mě. Doporučená krátká retence. | střední, [VÝKLAD] |
| 3 | Přepis a využití obsahu v appce jen pro mě | **Pravděpodobně legální**, stejná logika jako u bodu 2. Bezpečnější je přepisovat lokálně, ne posílat zvuk do cloudu. | střední, [VÝKLAD] |
| 4 | Ukazovat nebo sdílet přepisy či zvuk dalším lidem | **Nejasné až rizikové.** Odpadá výjimka pro osobní účely (GDPR) a při komerčním záměru přichází v úvahu i § 182 odst. 2 trestního zákoníku. **Před zveřejněním je nutný dotaz na ČTÚ a právníka.** | nízká |

Krátce: pro soukromé MVP to vypadá průchodně. Pro jakékoli sdílení ne bez právního ověření. Tvrzení „pro soukromé účely by to mělo být legální“ je **pravděpodobně správné, ale žádný úřad ani soud ho nepotvrdil**. Stanovisko ČTÚ k poslechu leteckého pásma ani českou judikaturu ke skenerům jsem nenašel.

---

## 1. Právní rozbor

### 1.1 Zákon č. 127/2005 Sb., o elektronických komunikacích (ZEK)

Zdroj: [zakonyprolidi.cz/cs/2005-127](https://www.zakonyprolidi.cz/cs/2005-127), aktuální znění 1. 11. 2026 (verze 53).

**§ 89 Důvěrnost komunikací**, odst. 1 [JISTÉ]:

> „Podnikatelé zajišťující veřejné komunikační sítě nebo poskytující veřejně dostupné služby elektronických komunikací jsou povinni zajistit technicky a organizačně důvěrnost zpráv a s nimi spojených provozních a lokalizačních údajů, které se přenášejí prostřednictvím jejich veřejné komunikační sítě a veřejně dostupných služeb elektronických komunikací. Zejména nepřipustí odposlech, ukládání zpráv nebo jiné druhy zachycení nebo sledování zpráv a s nimi spojených údajů osobami jinými, než jsou uživatelé, bez souhlasu dotčených uživatelů, pokud zákon nestanoví jinak.“

§ 89 odst. 2 [JISTÉ]:

> „Zprávou se rozumí jakákoli informace, která se vyměňuje nebo přenáší mezi konečným počtem účastníků nebo uživatelů prostřednictvím veřejně dostupné služby elektronických komunikací, s výjimkou informace přenášené jako součást veřejného rozhlasového nebo televizního vysílání […]“

Co z toho plyne:
- [JISTÉ] Povinnost podle § 89 odst. 1 má **operátor veřejné sítě**, ne posluchač. Pojem „zpráva“ je v § 89 navázán na **veřejně dostupnou službu** elektronických komunikací.
- [VÝKLAD] Letecká pohyblivá služba (komunikace ATC s piloty) není veřejně dostupná služba elektronických komunikací. Provozuje ji ŘLP ČR, s. p., pro letový provoz, ne pro veřejnost. § 89 se na ni proto podle všeho **nevztahuje vůbec**.
- [JISTÉ] Zadání předpokládalo, že ZEK obsahuje **povinnost osoby, která omylem přijme zprávu jí neurčenou**, zprávu nezaznamenat a nešířit. **Takové ustanovení v platném ZEK není.** Plný text jsem prohledal na výrazy „odposlech“, „není/nejsou určen“ a „k příjmu“. Odposlech se objevuje jen v § 89 (povinnost operátorů), v § 97 (odposlech pro policii, BIS a VZ) a v § 113 odst. 4. Tam je zákaz sdělovat obsah zpráv uložen jen **kontrolujícím ČTÚ**:
  > „Kontrolující nesmějí obsah přenášených zpráv sdělovat jiným osobám než odesílateli nebo adresátovi přenášených zpráv, popřípadě jimi zmocněnému zástupci ani umožnit jiným osobám, aby získávaly informace o obsahu přenášených zpráv.“
- [NEOVĚŘENO] Na fóru FlightSim.cz se zmiňuje, že dřívější zákon o telekomunikacích (č. 151/2000 Sb.) zákaz příjmu cizích zpráv obsahoval. Neověřoval jsem to. Platí dnes ZEK z roku 2005 a ten zákaz pro fyzické osoby nemá.
- [JISTÉ] Sankce: přestupek podle **§ 118 odst. 14 písm. j)** (porušení § 89 odst. 1) může spáchat jen *„podnikatel zajišťující veřejnou komunikační síť nebo poskytující veřejně dostupnou službu elektronických komunikací“*. Pokuta je podle § 118 odst. 26 písm. b) až 15 mil. Kč nebo 5 % obratu. **§ 119 (přestupky fyzických osob) na § 89 neodkazuje.** Za samotný poslech tedy fyzické osobě podle ZEK žádná pokuta nehrozí.
- [VÝKLAD] Přijímač, který nic nevysílá, podle všeho nepotřebuje oprávnění k využívání kmitočtů od ČTÚ, protože ta se týkají vysílání. Výslovné ustanovení „přijímač nepotřebuje oprávnění“ jsem ale nenašel. Letecké přijímače a skenery se v ČR běžně a legálně prodávají (např. [aviatik.cz](https://www.aviatik.cz/prijimace-leteckeho-pasma/)), ale to je jen nepřímý doklad.

Pro srovnání podstatná definice, § 2 písm. b) ZEK [JISTÉ]: *„sítí elektronických komunikací přenosové systémy […] které umožňují přenos signálů po vedení, rádiovými, optickými nebo jinými elektromagnetickými prostředky […] bez ohledu na typ přenášené informace“*. Tato definice **není** omezená na veřejné sítě. Rádiový systém ATC je proto „síť elektronických komunikací“, což je důležité pro trestní zákoník níže.

### 1.2 Trestní zákoník, zákon č. 40/2009 Sb.

Zdroj: [zakonyprolidi.cz/cs/2009-40](https://www.zakonyprolidi.cz/cs/2009-40), znění k 1. 1. 2026.

**§ 182 Porušení tajemství dopravovaných zpráv** [JISTÉ]:

> „(1) Kdo úmyslně poruší tajemství […]
> b) datové, textové, hlasové, zvukové či obrazové zprávy posílané prostřednictvím sítě elektronických komunikací a přiřaditelné k identifikovanému účastníku nebo uživateli, který zprávu přijímá, nebo
> c) neveřejného přenosu dat do počítačového systému, z něj nebo v jeho rámci […]
> bude potrestán odnětím svobody až na dvě léta nebo zákazem činnosti.
>
> (2) Stejně bude potrestán, kdo v úmyslu způsobit jinému škodu nebo opatřit sobě nebo jinému neoprávněný prospěch
> a) prozradí tajemství, o němž se dozvěděl z písemnosti, telegramu, telefonního hovoru nebo přenosu prostřednictvím sítě elektronických komunikací, který nebyl určen jemu, nebo
> b) takového tajemství využije.“

Tohle je **jediné nalezené ustanovení, které na ATC teoreticky dopadá**:
- [VÝKLAD] Odst. 1 písm. b): hlasová zpráva v síti elektronických komunikací (ta je definovaná široce) a přiřaditelná k identifikovanému uživateli. Pokyn ATC je adresovaný konkrétnímu volacímu znaku. Formální znaky by se tedy daly najít. Klíčové je ale slovo **„tajemství“**. ATC vysílá nešifrovaně na kmitočtech zveřejněných v AIP a poslouchají ho tisíce lidí. Prostředky k poslechu se volně prodávají a obsah není z povahy věci důvěrný. Navíc je potřeba úmysl. Považuju za **velmi nepravděpodobné**, že by pasivní poslech naplnil § 182 odst. 1. Judikaturu k tomu jsem nenašel.
- [VÝKLAD] Odst. 2 je relevantní hlavně pro **případ 4**. Trestné je prozradit nebo využít obsah přenosu, „který nebyl určen jemu“, ale jen **„v úmyslu způsobit jinému škodu nebo opatřit sobě nebo jinému neoprávněný prospěch“**. Soukromá appka bez zisku tento úmysl nemá. U veřejné **monetizované** služby by se o „neoprávněném prospěchu“ teoreticky dalo uvažovat. I tady ale platí, že musí jít o „tajemství“.

**§ 183** (tajemství listin a dokumentů „uchovávaných v soukromí jiného“) [VÝKLAD]: na ATC nedopadá. Vysílání není dokument uchovávaný v soukromí.

### 1.3 Občanský zákoník, zákon č. 89/2012 Sb. (ochrana osobnosti, hlas)

Zdroj: [zakonyprolidi.cz/cs/2012-89](https://www.zakonyprolidi.cz/cs/2012-89).

§ 86 [JISTÉ]:
> „Nikdo nesmí zasáhnout do soukromí jiného, nemá-li k tomu zákonný důvod. Zejména nelze bez svolení člověka narušit jeho soukromé prostory, sledovat jeho soukromý život nebo pořizovat o tom zvukový nebo obrazový záznam, využívat takové či jiné záznamy pořízené o soukromém životě člověka třetí osobou, nebo takové záznamy o jeho soukromém životě šířit. […]“

§ 89 [JISTÉ]:
> „Podobizna nebo zvukový či obrazový záznam se mohou bez svolení člověka také pořídit nebo použít přiměřeným způsobem též k vědeckému nebo uměleckému účelu a pro tiskové, rozhlasové, televizní nebo obdobné zpravodajství.“

§ 90 [JISTÉ]: zákonný důvod *„nesmí být využit nepřiměřeným způsobem v rozporu s oprávněnými zájmy člověka“*.

- [VÝKLAD] Komunikace řídících a pilotů je **profesní projev při výkonu práce**, ne „soukromý život“ podle § 86. Riziko zásahu do soukromí je u bodů 1 až 3 malé.
- [VÝKLAD] U bodu 4 (zveřejnění **zvuku**) je hlas konkrétního řídícího nebo pilota „zvukový záznam týkající se člověka“ (§ 87 odst. 1 OZ). Zveřejnění bez svolení by se muselo opřít o některou výjimku, např. „obdobné zpravodajství“ podle § 89, a dodržet přiměřenost podle § 90. Zveřejnit **text bez hlasu** je výrazně méně rizikové než zveřejnit zvuk.

### 1.4 GDPR (nařízení EU 2016/679)

- [JISTÉ] Čl. 2 odst. 2 písm. c) GDPR: nařízení se nevztahuje na zpracování *„prováděné fyzickou osobou v průběhu výlučně osobních či domácích činností“* (výjimka pro domácnost).
- [VÝKLAD] Hlas je osobní údaj, pokud jde o identifikovatelnou osobu. **Volací znak + registrace + ADS-B data z appky** umožňují nepřímou identifikaci: u všeobecného letectví (OK-xxx) je provozovatelem často fyzická osoba, u aerolinek posádka konkrétního letu. Appka tyhle údaje propojuje automaticky, takže v ní půjde o osobní údaje.
- [VÝKLAD] Body 1 až 3 (jen pro mě, nic nezveřejněno) by měly spadat pod **výjimku pro domácnost**. Pozor na rozsudek SDEU **C-212/13 Ryneš** (český případ kamery): výjimku vykládá úzce a nepoužije ji na systematické zachycování mimo soukromou sféru. Bezpečné je proto: nic nesdílet, krátká retence a ideálně neposílat zvuk třetím stranám (cloud STT). Do Claude API jde jen text, a to v rámci stávajícího limitu.
- [VÝKLAD] U bodu 4 výjimka pro domácnost **odpadá**. Je potřeba právní titul (oprávněný zájem, čl. 6 odst. 1 písm. f), test proporcionality), informační povinnost, záznamy o zpracování a u hlasu a sledování letadel nejspíš i DPIA. Rozumné by bylo zveřejňovat jen text, bez zvuku a s retencí.

### 1.5 Letecké předpisy a ŘLP ČR

- [NEOVĚŘENO] Nenašel jsem předpis ani stanovisko ŘLP ČR nebo ÚCL, které by upravovalo poslech **veřejností**. Letecké předpisy (EU 2017/373, Doplněk 10 ICAO) ukládají povinnosti poskytovateli služby (ŘLP), například povinnost nahrávat a uchovávat záznamy. Na třetí osoby nedopadají.
- [JISTÉ] Kmitočty LKPR jsou veřejně zveřejněné v AIP ČR: [eAIP LKPR AD 2.18](https://aim.rlp.cz/eaip/html/eAIP/LK-AD-2.LKPR-en-GB.html).
- [JISTÉ] Hobby zdroj [Aeroweb.cz](https://www.aeroweb.cz/clanky/781-zajimavy-konicek-poslech-letecke-komunikace) uvádí, že poslech komunikace mezi posádkami a řídícími *„není nijak obtížný ani nelegální“*. Článek je ale starý a nejde o autoritativní zdroj.
- Bezpečnostní poznámka: na leteckých kmitočtech **nikdy nic nevysílat**. To už by byl provoz vysílače bez oprávnění a průkazu radiotelefonisty.

### 1.6 Srovnání: LiveATC a EU

- [JISTÉ] **Německo** výslovně zakazuje poslech, viz § 5 odst. 1 TDDDG ([gesetze-im-internet.de/ttdsg/__5.html](https://www.gesetze-im-internet.de/ttdsg/__5.html)): *„Mit einer Funkanlage […] dürfen nur solche Nachrichten abgehört […] werden, die für den Betreiber der Funkanlage, für Funkamateure […], für die Allgemeinheit oder für einen unbestimmten Personenkreis bestimmt sind.“* Porušení je podle § 27 trestné (až 2 roky). **Český ZEK obdobu tohoto ustanovení nemá.** To je hlavní argument, proč je soukromý poslech v ČR pravděpodobně v pořádku.
- [NEOVĚŘENO] Velká Británie má podobný zákaz (Wireless Telegraphy Act 2006, s. 48). LiveATC proto podle obecně známé praxe nemá britské ani německé feedy z velkých letišť. Jinde v EU (např. Nizozemsko, Polsko a dříve i Praha) feedy provozuje. Tyto feedy dodávají dobrovolníci a odpovědnost za legálnost nese podle všeho poskytovatel feedu.
- [JISTÉ] LiveATC dříve **pražské feedy měl**, ale na jejich fóru se od března 2024 hlásí, že je všech 6 feedů LKPR dlouhodobě mimo provoz ([fórum LiveATC, ticket 52913](https://forums.liveatc.net/listener-forum/czech-republic-lkpr-6-feeds-are-down-ticket-52913)). Aktuální stav jsem ověřit nemohl, protože liveatc.net vrací automatickým dotazům HTTP 403.
- [JISTÉ podle citací ve výsledcích vyhledávání, stránku jsem sám neotevřel] Podmínky LiveATC ([liveatc.net/legal](https://liveatc.net/legal)) dávají licenci *„for personal non-commercial purposes only“* a homepage uvádí, že *„third-party use of LiveATC live audio streams is prohibited“*. **Automatické stahování streamů do vlastní appky je tedy v rozporu s jejich podmínkami.** Jako zdroj pro skywatch-cz LiveATC nepřipadá v úvahu.

---

## 2. Technické řešení

### 2.1 Zdroj zvuku: vlastní SDR (doporučeno)

Kmitočty LKPR podle [eAIP AD 2.18](https://aim.rlp.cz/eaip/html/eAIP/LK-AD-2.LKPR-en-GB.html). Před nastavením je ověřit v aktuálním AIRACu:

| Služba | Volací znak | MHz | Poznámka |
|---|---|---|---|
| APP | PRAHA RADAR | 120.530 | odlety, H24 |
| APP | PRAHA RADAR | 127.580 | přílety, H24 |
| APP | RUZYNĚ RADAR | 119.010, 118.310 | omezená provozní doba, mimo ni 127.580 |
| TWR | RUZYNĚ TOWER | 134.560 | H24, jen angličtina |
| DEL | RUZYNĚ DELIVERY | 120.060 | jen EN, DCL i přes ACARS |
| GND | RUZYNĚ GROUND | 121.910 | jen EN |
| nouzová | | 121.500 | H24 |
| ACC | PRAHA CONTROL | více sektorů | v AIP ENR, [NEOVĚŘENO] |

- **Hardware:** RTL-SDR Blog V4 nebo podobný (~1 000 Kč za kus). Pásmo 118–137 MHz, AM, rozteč kanálů 8,33 kHz.
- **Kolik donglů:** jeden RTL-SDR pokryje ~2,4 MHz najednou. 118.31–120.53 se do toho vejde, ale 121.91, 127.58 a 134.56 už ne. Pro souběžný příjem TWR + GND + APP jsou potřeba **2–3 dongly**, případně jeden dongle se skenováním (s výpadky).
- **Anténa:** stačí čtvrtvlnný ground plane pro ~125 MHz (prut ~57 cm, DIY za pár stovek) nebo hotová letecká anténa (1–2 tis. Kč). Umístit co nejvýš, ideálně venku. Volitelně airband filtr nebo LNA proti rušení z FM a mobilů (~500–1 000 Kč).
- **Dosah [VÝKLAD, fyzika přímé viditelnosti]:** letadla ve výšce (APP, ACC) se dají slyšet na **desítky až přes 100 km**. Vysílač věže a letadla na zemi (TWR, GND) jsou nízko, takže je potřeba být **v řádu jednotek km od letiště** s výhledem tím směrem. Jinak člověk slyší jen piloty, ne řídícího. To je hlavní praktické omezení a dá se ověřit jen zkouškou na místě.
- **Software:** [RTLSDR-Airband](https://github.com/charlie-foxtrot/RTLSDR-Airband) umí multichannel AM, squelch a ukládání **každého vysílání do samostatného souboru** (`split_on_transmission`), případně stream do Icecastu. Segmentace podle squelche je přesně to, co potřebuje přepis. Na ruční poslech a ladění se hodí SDR++.
- **Kde to poběží:** přijímač musí být fyzicky doma, u antény (Raspberry Pi 4/5, ~2–3 tis. Kč, nebo domácí počítač). PLAN.md počítá s backendem na VPS. Pi by pak posílal na VPS **jen text** přepisů, zvuk ne.

### 2.2 Zdroj zvuku: streamy třetích stran

Prošel jsem, odkud se dá zvuk LKPR stáhnout bez vlastního přijímače (stav 8. 11. 2026). **Žádný použitelný zdroj jsem nenašel.** Prakticky všechny české stránky, které „ATC zvuk z Ruzyně“ nabízejí, jen odkazují na LiveATC.

| Zdroj | Co nabízí | Stav | Použitelné pro appku? |
|---|---|---|---|
| **LiveATC** (`lkpr_twr`, `lkpr_app`, `lkpr_gnd`, `lkpr_del`, `lkaa_wh`, `lkaa_wl`) | TWR, APP, GND, DEL a FIR Praha high/low | Stránky feedů existují a ve vyhledávači mají aktuální METAR. Fórum ale od 2024 hlásí výpadek všech 6 feedů a vyhledávání LiveATC uvádí, že LKPR „není pokryto“. **Aktuální stav jsem ověřit nemohl**, web blokuje automatický přístup ochranou proti botům. | **Ne.** Podmínky povolují jen „personal non-commercial“ použití a zakazují použití streamů ve třetích aplikacích. Ručně v prohlížeči poslouchat můžete. |
| **Oficiální stream Letiště Praha** (YouTube [@PragueAirport](https://www.youtube.com/@PragueAirport), dříve i Mall.tv) | kamera na dráhu 06/24, podle tiskových zpráv z 2021 a 2022 *„doplněno autentickou komunikací mezi posádkami a řídícími“* | Záložka „Živě“ na kanálu dnes ukazuje jen staré pořady (7 let), **24/7 přenos z dráhy tam neběží**. Mall.tv už nevysílá [NEOVĚŘENO]. | **Ne.** Neběží, a i kdyby běžel, šlo by o mix zvuku k videu bez metadat. Zajímavé je ale něco jiného: letiště samo léta veřejně šířilo ATC zvuk ([prg.aero 2022](https://prg.aero/en/nearly-14-million-people-view-airport-main-runway-live-stream)). Pro bod 4 je to argument, že veřejné šíření není v ČR nemyslitelné. Nevíme ale, jestli k tomu měli souhlas ŘLP. |
| [Flying Revue](https://www.flying-revue.cz/letiste-vaclava-havla2), [Planeta cestování](https://www.planetacestovani.cz/primy-prenos-letiste-praha-online/), [FlyRadar.cz](https://www.flyradar.cz/planespotting/playtvak/) | video z kamer (Playtvak/Mafra) + „poslech ATC“ | Zvuk není jejich, **jen odkazují na LiveATC** (ATIS na IVAO = virtuální letectví, ne skutečné ATC). Komentáře z 2024–2025 hlásí, že zvuk nefunguje. | Ne (= LiveATC) |
| Webkamery [mangolinkworld](https://www.mangolinkworld.com/webcams/transport/prague-airport-webcam.html), [airportwebcams.net](https://airportwebcams.net/prague-airport-webcam/) | „zvuk LKPR Tower“ | Agregátory, zdroj zvuku neuveden, nejspíš opět LiveATC | Ne |
| Veřejné webové SDR (OpenWebRX/[ReceiverBook](https://receiverbook.de/?type=openwebrx), WebSDR, KiwiSDR) | vzdálený přijímač ovládaný z prohlížeče | Přijímač v okolí Prahy s leteckým pásmem jsem nenašel. KiwiSDR pokrývá jen 0–30 MHz. | Ne. A kdyby se našel, automatické stahování cizího přijímače by stejně potřebovalo souhlas provozovatele. |

Závěr: **spolehlivý zdroj zvuku pro automatické zpracování je jen vlastní přijímač.** Na ruční poslech si můžete LiveATC otevřít v prohlížeči a ověřit, jestli pražské feedy znovu běží. Kdybyste chtěli feedy LiveATC přece jen použít automaticky, jediná legitimní cesta je napsat LiveATC o písemný souhlas. Případně se dá stát vlastním poskytovatelem feedu pro LiveATC: postavíte přijímač, posíláte zvuk jim a data máte zároveň u sebe.

### 2.3 Přepis řeči (STT)

**Kvalita:** obecný Whisper je na ATC špatný. Studie uvádějí WER 60–95 % bez doladění. Modely doladěné na ATC (korpusy ATCO2 a UWB-ATCC, v obou jsou i pražské nahrávky) se dostávají na zhruba 15–40 % WER:
- [jacktol/whisper-medium.en-fine-tuned-for-ATC](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC): udávaná WER 15,08 % oproti 94,59 % bez doladění. Existuje i verze pro faster-whisper ([odkaz](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper)). Jen angličtina.
- [BUT-FIT/whisper-ATC-czech-full](https://huggingface.co/BUT-FIT/whisper-ATC-czech-full) (VUT Brno): čeština + angličtina, trénováno na LKKU. Karta modelu uvádí pro LKPR/LKTB **dvě protichůdná čísla (3,6 % a 19,6 % WER)**. Ověřit vlastním testem.
- Přehled: [arXiv 2502.20311](https://arxiv.org/pdf/2502.20311) (Whisper large-v3 doladěný na ATCO2 ~38 % WER v jejich nastavení).

**Typické chyby:** volací znaky („Speedbird“ místo „BAW“) a čísla (FL, kurzy, kmitočty). Na šumu a tichu Whisper **halucinuje** celé věty. Přepis je proto vždy jen „pravděpodobný“ a pro AI vysvětlení platí stejná pravidla poctivosti jako jinde v appce.

**Čeština:** LKPR Tower, Ground a Delivery jsou podle AIP „Only EN“. Čeština se může objevit na APP u VFR a všeobecného letectví, tam se hodí model BUT-FIT.

**Lokálně vs. cloud:**
- Lokálně (faster-whisper nebo whisper.cpp, model medium): na Macu s Apple Silicon nebo slušném PC v reálném čase bez problému. Na Raspberry Pi 5 jen malé modely a horší kvalita, případně posílat klipy na domácí počítač. **Náklady 0 Kč**, zvuk nikam neodchází (lepší z hlediska GDPR, viz 1.4).
- Cloud (ceny z agregátorů, ověřit u výrobce): OpenAI gpt-4o-mini-transcribe ~0,003 $/min, gpt-4o-transcribe ~0,006 $/min, AssemblyAI od ~0,15 $/h, Deepgram Nova-3 ~0,46 $/h. Na ATC nejsou doladěné, takže přesnost bude spíš horší než u ATC modelů výše.

**Objem [odhad]:** po odstranění ticha squelchem má jeden aktivní kmitočet ve špičce řádově 30–50 % vysílání, v noci skoro nic. Pro 3–4 kmitočty to dává hrubě **10–30 h řeči denně**. V cloudu za ~0,2–0,4 $/h to je **~1,5–8 tis. Kč/měsíc**. Proto lokální přepis.

### 2.4 Napojení na architekturu skywatch-cz

```
[anténa] → RTL-SDR ×2–3 → RTLSDR-Airband (klip na každé vysílání)
   → atc_transcriber.py (faster-whisper, lokálně; běží u přijímače)
   → SQLite tabulka atc_transmissions (nebo POST na backend, jen text)
   → explain.py: k události (go-around, holding, nouze) přidá přepisy
     z TWR/APP v okně ±2 min, které odpovídají volacímu znaku
```

- Nová tabulka (návrh):
  `atc_transmissions(id, freq_mhz, started_at, duration_s, text, callsign_guess, confidence, audio_path NULL)`
- **Párování volacích znaků:** ADS-B má `BAW123`, v rádiu zazní „Speedbird one two three“. Potřebuje to tabulku telefonních označení aerolinek (ICAO designator → telephony) v `config/` a fuzzy match čísel. To je samostatný, dobře testovatelný čistý modul (pytest na syntetických přepisech).
- **Detektory:** přepis by neměl být sám zdrojem událostí (kvůli halucinacím). Má sloužit jako **kontext** pro existující detektory. Výjimka by mohla být slova „go around“, „mayday“ a „pan pan“ jako *pomocný* signál pro go_around a emergency, který potvrzují ADS-B data.
- **Claude:** přepisy jdou jen jako část kontextu do stávajícího `explain.py`, ve stávajícím limitu 30 volání za hodinu. Žádné souhrny každého vysílání. Prompt musí říkat, že přepis je strojový a může být chybný, a UI ho tak musí označit („strojový přepis rádia, může být chybný“).
- **Retence:** zvuk mazat po 24–48 h (stačí na ladění), text po 30 dnech. U zvuku se nastavení retence dá zapnout přímo v RTLSDR-Airband nebo cronem.

### 2.5 Hrubý odhad nákladů

| Položka | Jednorázově | Měsíčně |
|---|---|---|
| 2–3× RTL-SDR Blog V4 | 2–3 tis. Kč | |
| Anténa + kabel + filtr | 1–3 tis. Kč | |
| Raspberry Pi 5 + zdroj + SD (nebo stávající PC) | 0–3 tis. Kč | |
| Elektřina (Pi + dongly ~10 W) | | ~50–80 Kč |
| Přepis lokálně | | 0 Kč |
| Přepis v cloudu (alternativa) | | ~1,5–8 tis. Kč |
| Claude (v rámci stávajícího limitu) | | ~beze změny |
| **Celkem (lokální varianta)** | **~3–9 tis. Kč** | **~100 Kč** |

---

## 3. Doporučená cesta k MVP

1. **Ověření příjmu (bez kódu v repu):** koupit 1 RTL-SDR + anténu, v SDR++ poslouchat 127.580, 120.530 a 134.560 z místa, kde poběží přijímač. Zjistit, jestli je slyšet i řídící, nebo jen piloti.
2. **Test přesnosti:** nahrát pár hodin přes RTLSDR-Airband, ručně přepsat ~50 klipů a změřit WER pro `jacktol/...ATC-faster-whisper`, `BUT-FIT/whisper-ATC-czech-full` a vanilla `large-v3-turbo`. Pod ~25 % WER u volacích znaků nemá cenu pokračovat.
3. **Soukromá integrace:** `atc_transcriber.py` + tabulka + párování volacích znaků + kontext v `explain.py`. Vše jen lokálně pro jednoho uživatele, zvuk se nesdílí, krátká retence, zvuk nejde do cloudu.
4. **Před jakýmkoli sdílením (bod 4):** písemný dotaz na ČTÚ a konzultace s advokátem (média/IT/GDPR). Pokud ano, pak zveřejňovat jen text bez zvuku, s retencí a GDPR podklady.

Do PLAN.md bych to zařadil do backlogu jako „ATC přepis: soukromý (body 1–3)“ a nechal poznámku, že veřejná verze vyžaduje právní ověření.

## 4. Otevřené otázky

- **Pro ČTÚ (písemný dotaz přes podatelnu):** Je pasivní příjem letecké pohyblivé služby fyzickou osobou v ČR přípustný? Vztahuje se na něj nějak § 89 ZEK nebo jiný předpis? Je nějaký rozdíl mezi poslechem, záznamem a zveřejněním?
- **Pro advokáta:** Může § 182 odst. 1 písm. b) nebo odst. 2 TZ dopadnout na zveřejnění přepisů ATC? Co je u nešifrovaného, veřejně známého provozu „tajemství“? Jak vypadá zveřejnění z pohledu GDPR a § 86–90 OZ (hlas řídících), včetně rozsudku Ryneš?
- **Pro ŘLP ČR:** Má k veřejnému šíření záznamů nebo přepisů svého provozu stanovisko nebo podmínky?
- **Pro Letiště Praha:** Na jakém základě (souhlas ŘLP?) šířilo ATC zvuk ve svém 24/7 streamu z let 2020–2022? Odpověď by hodně napověděla k bodu 4.
- Neověřil jsem: aktuální stav LKPR na LiveATC (stránka blokuje automatické dotazy), plné znění podmínek LiveATC, kmitočty ACC Praha, starý zákon 151/2000 Sb. a skutečný dosah z konkrétního místa.

## 5. Zdroje

Primární:
- Zákon č. 127/2005 Sb., o elektronických komunikacích (§ 2, § 89, § 97, § 113, § 118, § 119): https://www.zakonyprolidi.cz/cs/2005-127
- Zákon č. 40/2009 Sb., trestní zákoník (§ 182, § 183): https://www.zakonyprolidi.cz/cs/2009-40
- Zákon č. 89/2012 Sb., občanský zákoník (§ 84–90): https://www.zakonyprolidi.cz/cs/2012-89
- GDPR, nařízení (EU) 2016/679, čl. 2 odst. 2 písm. c): https://eur-lex.europa.eu/eli/reg/2016/679/oj
- SDEU C-212/13 Ryneš: https://curia.europa.eu/juris/liste.jsf?num=C-212/13
- eAIP ČR, LKPR AD 2.18: https://aim.rlp.cz/eaip/html/eAIP/LK-AD-2.LKPR-en-GB.html
- ČTÚ, informace o využívání rádiových kmitočtů: https://ctu.gov.cz/informace-o-vyuzivani-radiovych-kmitoctu
- Německo, § 5 TDDDG (dříve TTDSG): https://www.gesetze-im-internet.de/ttdsg/__5.html

Sekundární:
- Aeroweb.cz, Poslech letecké komunikace: https://www.aeroweb.cz/clanky/781-zajimavy-konicek-poslech-letecke-komunikace
- Fórum FlightSim.cz: https://www.flightsim.cz/forum_prispevek.php?id=65254&lan=0&style=2
- LiveATC, podmínky: https://liveatc.net/legal
- LiveATC fórum, LKPR feeds down: https://forums.liveatc.net/listener-forum/czech-republic-lkpr-6-feeds-are-down-ticket-52913
- RTLSDR-Airband: https://github.com/charlie-foxtrot/RTLSDR-Airband
- Whisper pro ATC: https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC, https://huggingface.co/BUT-FIT/whisper-ATC-czech-full, https://arxiv.org/pdf/2502.20311
- Ceny STT (agregátor, ověřit u výrobců): https://soniox.com/compare/stt/pricing
