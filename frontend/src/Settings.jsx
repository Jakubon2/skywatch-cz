import { useEffect, useState } from "react";
import { useApp, useStored } from "./state.jsx";
import { disablePush, enablePush, getPushState, isPushSupported, sendTestPush } from "./push.js";
import "./Settings.css";

const isIOS = () =>
  /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS reports as a Mac
const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;

// beforeinstallprompt fires once, early after load, possibly before this tab is ever opened.
// This module is imported by tabs.js at startup, so catching it here is early enough.
let installEvent = null;
const installListeners = new Set();
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); // keep it for our own button instead of the browser's mini-infobar
  installEvent = e;
  installListeners.forEach((f) => f());
});
window.addEventListener("appinstalled", () => {
  installEvent = null;
  installListeners.forEach((f) => f());
});

const ICONS = {
  bell: "M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0",
  sound: "M4 9.5h3.5L12 5.5v13l-4.5-4H4zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
  home: "M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z",
  install: "M8 3h8a1.5 1.5 0 0 1 1.5 1.5v15A1.5 1.5 0 0 1 16 21H8a1.5 1.5 0 0 1-1.5-1.5v-15A1.5 1.5 0 0 1 8 3zM12 7.5v7M9.5 12l2.5 2.5 2.5-2.5",
  battery: "M4 8h13a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 17 16H4a1.5 1.5 0 0 1-1.5-1.5v-5A1.5 1.5 0 0 1 4 8zM21 11v2M6 11v2",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5.5M12 7.5v.01",
};

function Switch({ checked, onChange, disabled, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="switch"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="switch__knob" />
    </button>
  );
}

function Card({ icon, title, children }) {
  return (
    <section className="set-card">
      <h3 className="set-card__title">
        <svg className="set-card__icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d={icon} />
        </svg>
        {title}
      </h3>
      {children}
    </section>
  );
}

// "Sdílet" glyph as iOS draws it, so the steps match what the user sees in Safari.
const ShareGlyph = () => (
  <svg className="ios-glyph" viewBox="0 0 24 24" aria-label="Sdílet">
    <path d="M12 3v12M8 7l4-4 4 4M6 11H5v10h14V11h-1" />
  </svg>
);

const IosSteps = () => (
  <ol className="steps">
    <li>Otevři Skywatch v <b>Safari</b>.</li>
    <li>Klepni na <b>Sdílet</b> <ShareGlyph /> dole na liště.</li>
    <li>Vyber <b>Přidat na plochu</b> a potvrď <b>Přidat</b>.</li>
    <li>Spusť Skywatch z ikony na ploše a zapni upozornění tady.</li>
  </ol>
);

function PushSettings() {
  const support = isPushSupported();
  const [state, setState] = useState(support.supported ? "loading" : "unsupported");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null); // {text, error}

  useEffect(() => {
    if (support.supported) getPushState().then(setState, () => setState("off"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn, ok) => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
      if (ok) setNote({ text: ok });
    } catch (e) {
      setNote({ text: e.message, error: true });
    }
    setState(await getPushState().catch(() => "off"));
    setBusy(false);
  };

  const toggle = (on) => run(on ? enablePush : disablePush, on ? "Upozornění jsou zapnutá." : null);
  const test = () => run(sendTestPush, "Zkušební upozornění odesláno. Mělo by dorazit do pár sekund.");

  return (
    <Card icon={ICONS.bell} title="Upozornění">
      <div className="set-row">
        <div className="set-row__text">
          <span className="set-row__label">Push upozornění</span>
          <span className="set-row__sub">Nouzové squawky a tvoje alerty, i když je aplikace zavřená.</span>
        </div>
        <Switch
          label="Push upozornění"
          checked={state === "on"}
          disabled={busy || state === "loading" || state === "unsupported" || state === "denied"}
          onChange={toggle}
        />
      </div>

      {state === "on" && (
        <button className="btn btn--ghost btn--block set-gap" onClick={test} disabled={busy}>
          {busy ? "Posílám…" : "Poslat zkušební"}
        </button>
      )}

      {state === "denied" && (
        <div className="callout callout--warn">
          <p><b>Upozornění jsou v prohlížeči zablokovaná.</b> Aplikace se nemůže zeptat znovu, povol je ručně:</p>
          <ul>
            <li><b>Chrome:</b> ikona vlevo od adresy → Nastavení webu → Oznámení → Povolit.</li>
            <li><b>Safari na Macu:</b> Safari → Nastavení → Weby → Oznámení.</li>
            <li><b>iPhone:</b> Nastavení → Oznámení → Skywatch.</li>
          </ul>
          <p>Pak stránku obnov.</p>
        </div>
      )}

      {state === "unsupported" && (
        <div className="callout">
          {support.reason === "ios-not-installed" ? (
            <>
              <p>Na iPhonu a iPadu fungují upozornění jen v aplikaci <b>přidané na plochu</b>, a to od <b>iOS 16.4</b>.</p>
              <IosSteps />
            </>
          ) : support.reason === "ios-too-old" ? (
            <p>Upozornění na iPhonu vyžadují <b>iOS 16.4 nebo novější</b>. Aktualizuj systém v Nastavení → Obecné → Aktualizace softwaru.</p>
          ) : (
            <p>{support.message}</p>
          )}
        </div>
      )}

      {note && <p className={`form-note ${note.error ? "form-note--error" : ""}`} role="status">{note.text}</p>}
    </Card>
  );
}

function SoundSettings() {
  const [sound, setSound] = useStored("skywatch.sound", true);
  const play = (on) => {
    setSound(on);
    if (on) navigator.vibrate?.(30); // short tap as feedback where vibration exists (Android)
  };
  return (
    <Card icon={ICONS.sound} title="Zvuk a vibrace">
      <div className="set-row">
        <div className="set-row__text">
          <span className="set-row__label">Zvuk při události</span>
          <span className="set-row__sub">Krátké cinknutí a zavibrování, když se při otevřené aplikaci objeví nouze nebo tvůj alert.</span>
        </div>
        <Switch label="Zvuk při události" checked={sound !== false} onChange={play} />
      </div>
    </Card>
  );
}

function BatterySettings() {
  const { saver, setSaver } = useApp();
  return (
    <Card icon={ICONS.battery} title="Baterie">
      <div className="set-row">
        <div className="set-row__text">
          <span className="set-row__label">Úspora baterie</span>
          <span className="set-row__sub">Mapa se obnovuje jen každých 30 s, bez animací a bez stopy letu u detailu. Na pozadí aplikace nestahuje nic.</span>
        </div>
        <Switch label="Úspora baterie" checked={Boolean(saver)} onChange={setSaver} />
      </div>
    </Card>
  );
}

function HomeSettings() {
  const { home, setView, setOpen } = useApp();
  const go = () => {
    setView("near");
    setOpen(true);
  };
  return (
    <Card icon={ICONS.home} title="Domov">
      <div className="set-row">
        <div className="set-row__text">
          {home ? (
            <>
              <span className="set-row__label set-row__label--clip">{home.label}</span>
              <span className="set-row__sub">Pro „Nad hlavou“, hluk a kondenzační stopy. Uloženo jen v tomhle zařízení.</span>
            </>
          ) : (
            <>
              <span className="set-row__label">Zatím nenastaveno</span>
              <span className="set-row__sub">Zadej adresu a uvidíš letadla nad sebou, odhad hluku i stopy na obloze.</span>
            </>
          )}
        </div>
        <button className="btn btn--small" onClick={go}>{home ? "Změnit" : "Nastavit"}</button>
      </div>
    </Card>
  );
}

function InstallSettings() {
  const [, rerender] = useState(0);
  useEffect(() => {
    const f = () => rerender((n) => n + 1);
    installListeners.add(f);
    return () => installListeners.delete(f);
  }, []);

  const install = async () => {
    const e = installEvent;
    if (!e) return;
    e.prompt();
    await e.userChoice.catch(() => null);
    installEvent = null; // a prompt event can be used only once
    rerender((n) => n + 1);
  };

  let body;
  if (isStandalone()) body = <p className="set-text">Skywatch běží jako nainstalovaná aplikace. ✓</p>;
  else if (installEvent)
    body = (
      <>
        <p className="set-text">Přidej si Skywatch jako aplikaci: vlastní ikona, celá obrazovka a rychlé spuštění.</p>
        <button className="btn btn--primary btn--block set-gap" onClick={install}>Instalovat appku</button>
      </>
    );
  else if (isIOS())
    body = (
      <>
        <p className="set-text">Přidej si Skywatch na plochu. Poběží přes celou obrazovku a půjdou zapnout upozornění.</p>
        <IosSteps />
      </>
    );
  else
    body = (
      <p className="set-text">
        V menu prohlížeče zvol <b>Instalovat aplikaci</b> nebo <b>Přidat na plochu</b> (Chrome, Edge, Samsung Internet).
        V Safari na Macu: Soubor → <b>Přidat do Docku</b>.
      </p>
    );

  return <Card icon={ICONS.install} title="Instalovat appku">{body}</Card>;
}

function About() {
  return (
    <Card icon={ICONS.info} title="O aplikaci">
      <ul className="about">
        <li>Data o letadlech: <a href="https://adsb.lol" target="_blank" rel="noopener noreferrer">adsb.lol</a> (ODbL)</li>
        <li>Mapa: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> přispěvatelé</li>
        <li>Výškové počasí: <a href="https://open-meteo.com" target="_blank" rel="noopener noreferrer">Open-Meteo</a></li>
        <li>
          Fotky letadel: planespotters.net, vždy s autorem a odkazem podle jejich{" "}
          <a href="https://www.planespotters.net/photo/api" target="_blank" rel="noopener noreferrer">pravidel</a>
        </li>
      </ul>
      <p className="callout callout--quiet">
        Vysvětlení a odpovědi od AI jsou generované automaticky a <b>nejsou ověřené</b>. Odhady hluku a stop jsou
        orientační. Skywatch je osobní projekt, ne oficiální zdroj informací o letovém provozu.
      </p>
    </Card>
  );
}

export default function Settings() {
  return (
    <div className="settings">
      <PushSettings />
      <SoundSettings />
      <BatterySettings />
      <HomeSettings />
      <InstallSettings />
      <About />
    </div>
  );
}
