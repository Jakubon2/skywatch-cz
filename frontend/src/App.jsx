import { Suspense, useRef, useState } from "react";
import Map, { isDesktop } from "./Map.jsx";
import Detail from "./Detail.jsx";
import { TABS } from "./tabs.js";
import { AppProvider, useApp } from "./state.jsx";

const MORE_ICON = "M5 12h.01M12 12h.01M19 12h.01";
const MAX_TABS = 5; // more than this: the first 4 stay, the rest go under "Více"

// "před 3 min" / "před 2 h 5 min" / "před 2 dny"
function age(ms) {
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (min < 1) return "před chvílí";
  if (min < 60) return `před ${min} min`;
  if (min < 48 * 60) return `před ${Math.floor(min / 60)} h ${min % 60} min`;
  return `před ${Math.floor(min / 1440)} dny`;
}

function StatusPill({ status, count, shown, at }) {
  if (status === "loading") return <span className="pill">Načítám…</span>;
  if (status === "offline") {
    const why = navigator.onLine === false ? "Bez připojení" : "Backend neběží";
    if (!at || !count) return <span className="pill pill--off">{why}</span>;
    return (
      <span className="pill pill--off pill--stale" title={`${why}. Poslední data: ${new Date(at).toLocaleString("cs-CZ")}`}>
        Offline · data {age(at)}
      </span>
    );
  }
  if (status === "waiting") return <span className="pill">Čekám na data…</span>;
  return (
    <span className="pill pill--live">
      <span className="dot" /> {shown == null ? count : `${shown} / ${count}`} letadel
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

// Mobile bottom sheet: drag the handle/tab bar down to collapse it, up to open it. A short move is still a tap.
function useSheetDrag(open, setOpen) {
  const drag = useRef(null);
  const suppress = useRef(false);
  const panel = (e) => e.currentTarget.closest(".panel");
  const onPointerDown = (e) => {
    if (isDesktop() || e.button > 0) return;
    // Collapsed, the sheet shows just this handle, so it sits (sheet height - handle height) lower.
    drag.current = { y: e.clientY, dy: 0, moved: false, peek: panel(e).offsetHeight - e.currentTarget.offsetHeight };
  };
  const onPointerMove = (e) => {
    const d = drag.current;
    if (!d) return;
    d.dy = e.clientY - d.y;
    if (!d.moved && Math.abs(d.dy) < 8) return;
    if (!d.moved) {
      d.moved = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      panel(e).style.transition = "none";
    }
    // Follow the finger, clamped between fully open and the collapsed peek.
    const y = Math.min(d.peek, Math.max(0, (open ? 0 : d.peek) + d.dy));
    panel(e).style.transform = `translateY(${y}px)`;
  };
  const onPointerUp = (e) => {
    const d = drag.current;
    drag.current = null;
    if (!d?.moved) return;
    const el = panel(e);
    el.style.transition = "";
    el.style.transform = "";
    if (open && d.dy > 60) setOpen(false);
    else if (!open && d.dy < -60) setOpen(true);
    // The drag may end over a tab button: that release isn't a tap.
    suppress.current = true;
    setTimeout(() => (suppress.current = false), 0);
  };
  const onClickCapture = (e) => {
    if (suppress.current) e.stopPropagation();
  };
  return { onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, onClickCapture };
}

function Shell() {
  const { aircraft, status, dataAt, selectedHex, selected, selectedLost, select, view, open, setOpen, setMap, dimmed } = useApp();
  const tab = TABS.find((t) => t.id === view) || TABS[0];
  const Active = tab.component;
  const sheetDrag = useSheetDrag(open, setOpen);

  return (
    <div className="app">
      <Map aircraft={aircraft} selectedHex={selectedHex} onSelect={select} onReady={setMap} dimmed={dimmed} />
      {TABS.map((t) => t.overlay && <t.overlay key={t.id} />)}

      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>Skywatch <b>CZ</b></span>
        </div>
        <StatusPill status={status} count={aircraft.length} shown={dimmed && aircraft.length - dimmed.size} at={dataAt} />
      </header>

      <aside className={`panel panel--${selected ? "detail" : tab.id} ${open ? "panel--open" : ""}`}>
        <div className="panel__handle" {...sheetDrag}>
          <button className="panel__grab" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? "Sbalit panel" : "Rozbalit panel"}>
            <span className="grabber" />
          </button>
          <Nav />
        </div>

        <div className="panel__body">
          {selected ? <Detail a={selected} lost={selectedLost} onClose={() => select(null)} /> : (
            <Suspense fallback={<p className="empty">Načítám…</p>}>
              <Active />
            </Suspense>
          )}
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
