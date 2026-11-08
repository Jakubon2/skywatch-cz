// "Co to bylo?": which plane did I just hear (or what flew over at 2:14 at night)? Backend: /api/what-was-that.
// Lives at the top of the "Nad hlavou" tab; WhatWasThatFab is a shortcut button on the map.
import { useEffect, useState } from "react";
import L from "leaflet";
import { useApp, useMapLayer } from "./state.jsx";
import { isDesktop, visiblePadding } from "./Map.jsx";
import "./WhatWasThat.css";

const RETENTION_H = 24; // backend keeps positions this long (config history.retention_hours)
const fmt = (n, d = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: d });
const km = (x) => `${fmt(x, x < 10 ? 1 : 0)} km`;
const meters = (m) => `${fmt(Math.round(m / 50) * 50)} m`;
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString("cs-CZ", { hour: "numeric", minute: "2-digit" });

// The map shortcut asks before this component is mounted: remember the request until it is.
let pendingAsk = false;
// Last answer, so it is still there after a detail (which replaces the tab) is closed.
let last = null; // { state, focus, at }
const ASK_EVENT = "skywatch:whatwasthat";

function when(c, live) {
  if (!live) return clock(c.cpa_ts);
  const s = c.ago_s;
  return s < 15 ? "právě teď" : s < 60 ? `před ${s} s` : s < 3600 ? `před ${Math.round(s / 60)} min` : `v ${clock(c.cpa_ts)}`;
}

function title(c) {
  const name = c.type_name || c.t || "Neznámý typ";
  if (c.private) return `${name} · soukromé`;
  return [name, c.operator || c.flight].filter(Boolean).join(" · ");
}

function locate() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("Tenhle prohlížeč polohu neumí. Nastav si domov níže."));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (err) => reject(new Error(err.code === 1 ? "Přístup k poloze je zakázaný. Povol ho, nebo si níže nastav domov." : "Polohu se nepodařilo zjistit.")),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 120000 },
    );
  });
}

// "HH:MM" today/yesterday -> Date, or an error text.
function pickedTime(day, hm) {
  const [h, m] = hm.split(":").map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return { error: "Zadej čas." };
  const d = new Date();
  if (day === "yesterday") d.setDate(d.getDate() - 1);
  d.setHours(h, m, 0, 0);
  const now = Date.now();
  if (d.getTime() > now + 60_000) return { error: "Tenhle čas ještě nenastal." };
  if (d.getTime() < now - RETENTION_H * 3600_000) return { error: `Polohy letadel uchovávám jen ${RETENTION_H} hodin. Vyber pozdější čas.` };
  return { date: d };
}

// Track of the highlighted candidate + its closest point, fitted with the observer into the visible map.
function useCandidateLayer(c, point) {
  useMapLayer(
    (map) => {
      if (!c || !point) return;
      const group = L.layerGroup().addTo(map);
      if (c.path.length > 1) L.polyline(c.path, { className: "wwt-path", interactive: false }).addTo(group);
      L.polyline([[point.lat, point.lon], [c.lat, c.lon]], { className: "wwt-link", interactive: false }).addTo(group);
      L.circleMarker([c.lat, c.lon], { radius: 7, className: "wwt-cpa", interactive: false }).addTo(group);
      const bounds = L.latLngBounds([...c.path, [c.lat, c.lon], [point.lat, point.lon]]);
      map.flyToBounds(bounds, { ...visiblePadding(), maxZoom: 12, duration: 0.6 });
      return () => group.remove();
    },
    [c, point],
  );
}

function Facts({ c }) {
  const items = [
    `~${fmt(c.db)} dB · ${c.label}`,
    `výška ${meters(c.alt_m)}`,
    `nejblíž ${km(c.distance_km)}`,
    c.gs_kmh != null && `${fmt(c.gs_kmh)} km/h`,
    c.rate_ms != null && Math.abs(c.rate_ms) >= 1 && `${c.rate_ms > 0 ? "stoupá" : "klesá"} ${fmt(Math.abs(c.rate_ms), 1)} m/s`,
  ].filter(Boolean);
  return (
    <div className="badges wwt-facts">
      {items.map((t, i) => (
        <span key={t} className={`badge ${i === 0 ? "badge--accent" : ""}`}>{t}</span>
      ))}
    </div>
  );
}

function Result({ data, focus, setFocus }) {
  const { select } = useApp();
  if (data.status !== "ok")
    return (
      <div className="wwt-card wwt-card--empty">
        <p className="empty__title">{data.status === "empty" ? "Nic jsem nenašel" : "Na tenhle čas nemám data"}</p>
        <p>{data.message}</p>
      </div>
    );

  const [top, ...rest] = data.candidates;
  const open = (c) => {
    setFocus(c.hex);
    if (c.live) select(c.hex);
  };
  return (
    <>
      <div className="wwt-card" aria-live="polite">
        <p className="wwt-sentence">{data.sentence}</p>
        <Facts c={top} />
        <div className="wwt-actions">
          <button className="btn btn--small" onClick={() => setFocus(top.hex)} aria-pressed={focus === top.hex}>
            Trasa na mapě
          </button>
          {top.live && (
            <button className="btn btn--small" onClick={() => select(top.hex)}>
              Detail letadla
            </button>
          )}
        </div>
      </div>

      {rest.length > 0 && (
        <>
          <h3 className="wwt-sub">Další v tu dobu</h3>
          <ul className="wwt-list">
            {rest.map((c) => (
              <li key={c.hex}>
                <button className={`wwt-row ${focus === c.hex ? "is-focus" : ""}`} onClick={() => open(c)}>
                  <span className="wwt-row__main">
                    <span className="wwt-row__title">{title(c)}</span>
                    <span className="wwt-row__sub">
                      {when(c, data.live)} · {meters(c.alt_m)} · {km(c.distance_km)}
                    </span>
                  </span>
                  <span className="wwt-row__db">~{fmt(c.db)} dB</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="form-note form-note--small wwt-note">Hlasitost je hrubý odhad z typu, výšky a vzdálenosti, ne měření. Letadla bez odpovídače ADS-B tu nejsou.</p>
    </>
  );
}

export default function WhatWasThat({ home }) {
  const [mode, setMode] = useState("now"); // now | past
  const [day, setDay] = useState("today");
  const [hm, setHm] = useState(() => {
    const d = new Date(Date.now() - 15 * 60_000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  });
  const recent = last && Date.now() - last.at < 10 * 60_000 ? last : null;
  const [state, setState] = useState(recent?.state || { status: "idle" }); // idle | busy | done | error
  const [focus, setFocus] = useState(recent?.focus ?? null);
  useEffect(() => {
    if (state.status === "done") last = { state, focus, at: last?.state === state ? last.at : Date.now() };
  }, [state, focus]);

  const ask = async (at = null) => {
    setState({ status: "busy" });
    try {
      const point = home || (await locate());
      const q = new URLSearchParams({ lat: point.lat, lon: point.lon });
      if (at) q.set("at", at.toISOString());
      const r = await fetch(`/api/what-was-that?${q}`);
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.detail && typeof data.detail === "string" ? data.detail : "Dotaz se nepovedl. Zkus to znovu.");
      setState({ status: "done", data, point });
      setFocus(data.candidates[0]?.hex ?? null);
    } catch (e) {
      setState({ status: "error", error: e.message || "Dotaz se nepovedl. Zkus to znovu." });
    }
  };

  // Map shortcut (WhatWasThatFab): run at once.
  useEffect(() => {
    const run = () => {
      pendingAsk = false;
      setMode("now");
      ask();
    };
    if (pendingAsk) run();
    window.addEventListener(ASK_EVENT, run);
    return () => window.removeEventListener(ASK_EVENT, run);
  }, [home]); // eslint-disable-line react-hooks/exhaustive-deps

  const picked = mode === "past" ? pickedTime(day, hm) : null;
  const data = state.status === "done" ? state.data : null;
  useCandidateLayer(data?.candidates.find((c) => c.hex === focus), state.point);

  return (
    <section className="wwt">
      {mode === "now" ? (
        <button className="wwt-hero" onClick={() => ask()} disabled={state.status === "busy"}>
          <span className="wwt-hero__icon" aria-hidden="true">?</span>
          <span className="wwt-hero__text">
            <span className="wwt-hero__title">{state.status === "busy" ? "Hledám…" : "Co to bylo?"}</span>
            <span className="wwt-hero__sub">{home ? "Co mi právě přeletělo nad hlavou" : "Použije tvoji polohu"}</span>
          </span>
        </button>
      ) : (
        <div className="wwt-past">
          <p className="wwt-past__title">Co letělo v…</p>
          <div className="wwt-past__row">
            <div className="seg seg--small" role="radiogroup" aria-label="Den">
              {[["today", "Dnes"], ["yesterday", "Včera"]].map(([id, label]) => (
                <button key={id} role="radio" aria-checked={day === id} className={day === id ? "is-active" : ""} onClick={() => setDay(id)}>
                  {label}
                </button>
              ))}
            </div>
            <input type="time" className="wwt-time" value={hm} onChange={(e) => setHm(e.target.value)} aria-label="Čas" />
          </div>
          {picked.error && <p className="form-note form-note--error">{picked.error}</p>}
          <button className="btn btn--primary btn--block" disabled={Boolean(picked.error) || state.status === "busy"} onClick={() => ask(picked.date)}>
            {state.status === "busy" ? "Hledám…" : "Najít"}
          </button>
        </div>
      )}
      <button
        className="btn btn--link btn--block wwt-switch"
        onClick={() => {
          setMode(mode === "now" ? "past" : "now");
          setState({ status: "idle" });
        }}
      >
        {mode === "now" ? "Hledat v jiném čase (dnes nebo včera)" : "Zpět na „Co to bylo teď?“"}
      </button>

      {state.status === "error" && <p className="form-note form-note--error">{state.error}</p>}
      {data && <Result data={data} focus={focus} setFocus={setFocus} />}
    </section>
  );
}

// Map shortcut: opens "Nad hlavou" and asks right away.
export function WhatWasThatFab() {
  const { view, setView, open, setOpen, select, selected } = useApp();
  // Phone: only over the bare map. Under an open sheet or the aircraft detail it would just
  // shine through the translucent panel. Desktop: everywhere except the "Nad hlavou" tab itself.
  if (isDesktop() ? view === "near" && !selected : open || selected) return null;
  return (
    <button
      className="wwt-fab"
      onClick={() => {
        pendingAsk = true;
        select(null);
        setView("near");
        setOpen(true);
        window.dispatchEvent(new Event(ASK_EVENT));
      }}
    >
      <span aria-hidden="true">?</span> Co to bylo?
    </button>
  );
}
