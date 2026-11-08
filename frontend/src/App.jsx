import { useState } from "react";
import Map from "./Map.jsx";
import Detail from "./Detail.jsx";
import { TABS } from "./tabs.js";
import { AppProvider, useApp } from "./state.jsx";

const MORE_ICON = "M5 12h.01M12 12h.01M19 12h.01";
const MAX_TABS = 5; // more than this: the first 4 stay, the rest go under "Více"

function StatusPill({ status, count }) {
  if (status === "loading") return <span className="pill">Načítám…</span>;
  if (status === "offline") return <span className="pill pill--off">Backend neběží</span>;
  if (status === "waiting") return <span className="pill">Čekám na data…</span>;
  return (
    <span className="pill pill--live">
      <span className="dot" /> {count} letadel
    </span>
  );
}

const Icon = ({ d }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d={d} />
  </svg>
);

function Nav() {
  const { view, setView, open, setOpen, selected, select } = useApp();
  const [menu, setMenu] = useState(false);
  const shown = TABS.length > MAX_TABS ? TABS.slice(0, MAX_TABS - 1) : TABS;
  const more = TABS.slice(shown.length);
  const activeMore = more.find((t) => t.id === view);

  // Tapping the active tab toggles the sheet (mobile); another tab opens it. Either closes a detail.
  const pick = (id) => {
    setMenu(false);
    if (id === view && !selected) setOpen(!open);
    else {
      setView(id);
      select(null);
      setOpen(true);
    }
  };

  return (
    <nav className={`seg tabs ${shown.length + (more.length ? 1 : 0) > 3 ? "tabs--compact" : ""}`} aria-label="Sekce">
      {shown.map((t) => (
        <button key={t.id} aria-current={view === t.id ? "page" : undefined} className={view === t.id ? "is-active" : ""} onClick={() => pick(t.id)}>
          <Icon d={t.icon} />
          {t.label}
        </button>
      ))}
      {more.length > 0 && (
        <>
          <button
            className={`tabs__more ${activeMore ? "is-active" : ""}`}
            aria-expanded={menu}
            aria-haspopup="menu"
            onClick={() => {
              setMenu(!menu);
              setOpen(true);
            }}
          >
            <Icon d={activeMore ? activeMore.icon : MORE_ICON} />
            {activeMore ? activeMore.label : "Více"}
          </button>
          {menu && (
            <>
              <div className="tabs__backdrop" onClick={() => setMenu(false)} />
              <div className="tabs__menu" role="menu">
                {more.map((t) => (
                  <button key={t.id} role="menuitem" className={view === t.id ? "is-active" : ""} onClick={() => pick(t.id)}>
                    <Icon d={t.icon} />
                    {t.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </nav>
  );
}

function Shell() {
  const { aircraft, status, selectedHex, selected, selectedLost, select, view, open, setOpen, setMap } = useApp();
  const tab = TABS.find((t) => t.id === view) || TABS[0];
  const Active = tab.component;

  return (
    <div className="app">
      <Map aircraft={aircraft} selectedHex={selectedHex} onSelect={select} onReady={setMap} />
      {TABS.map((t) => t.overlay && <t.overlay key={t.id} />)}

      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>Skywatch <b>CZ</b></span>
        </div>
        <StatusPill status={status} count={aircraft.length} />
      </header>

      <aside className={`panel panel--${selected ? "detail" : tab.id} ${open ? "panel--open" : ""}`}>
        <div className="panel__handle">
          <button className="panel__grab" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? "Sbalit panel" : "Rozbalit panel"}>
            <span className="grabber" />
          </button>
          <Nav />
        </div>

        <div className="panel__body">
          {selected ? <Detail a={selected} lost={selectedLost} onClose={() => select(null)} /> : <Active />}
        </div>

        <footer className="panel__footer">Data: adsb.lol (ODbL)</footer>
      </aside>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
