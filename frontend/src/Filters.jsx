// Map filters: a small button over the map that opens a filter card. Non-matching planes are dimmed
// (Map.jsx via state.jsx `setPlaneFilter`). Mounted as the "map" tab's overlay, so it is always there.
import { useEffect, useMemo, useState } from "react";
import { useApp, useStored } from "./state.jsx";
import { isGround } from "./aircraft.js";
import "./Filters.css";

// ADS-B emitter categories per filter chip.
const CATEGORIES = [
  { id: "light", label: "Lehká", codes: ["A1", "A2"] },
  { id: "airliner", label: "Dopravní", codes: ["A3", "A4"] },
  { id: "heavy", label: "Těžká", codes: ["A5"] },
  { id: "heli", label: "Vrtulníky", codes: ["A7"] },
];
const ALT_MAX = 13000; // metres; top of the slider = "and higher"
const ALT_STEP = 250;
const DEFAULT = { military: false, airline: null, alt: [0, ALT_MAX], cats: [] };

const FUNNEL = "M4 5h16l-6.2 7.4V19l-3.6-1.8v-4.8z";

export const airlineOf = (a) => /^([A-Z]{3})\d/.exec((a.flight || "").trim())?.[1] || null;

function buildFilter(f) {
  const [lo, hi] = f.alt;
  const altOn = lo > 0 || hi < ALT_MAX;
  const codes = f.cats.length ? new Set(CATEGORIES.filter((c) => f.cats.includes(c.id)).flatMap((c) => c.codes)) : null;
  if (!f.military && !f.airline && !altOn && !codes) return null;
  return (a) => {
    if (f.military && !(a.dbFlags & 1)) return false;
    if (f.airline && airlineOf(a) !== f.airline) return false;
    if (codes && !codes.has(a.category)) return false;
    if (altOn) {
      const alt = isGround(a) ? 0 : typeof a.alt_baro === "number" ? a.alt_baro * 0.3048 : null;
      if (typeof alt !== "number" || alt < lo || (hi < ALT_MAX && alt > hi)) return false;
    }
    return true;
  };
}

const metres = (n) => `${n.toLocaleString("cs-CZ")} m`;
function altLabel([lo, hi]) {
  if (lo === 0 && hi === ALT_MAX) return "Jakákoli";
  if (lo === 0) return `do ${metres(hi)}`;
  if (hi === ALT_MAX) return `nad ${metres(lo)}`;
  return `${lo.toLocaleString("cs-CZ")}–${metres(hi)}`;
}

export default function Filters() {
  const { aircraft, setPlaneFilter, dimmed } = useApp();
  const [stored, setStored] = useStored("skywatch.filters.m", DEFAULT);
  const f = { ...DEFAULT, ...stored };
  const [open, setOpen] = useState(false);

  const key = JSON.stringify(f);
  useEffect(() => setPlaneFilter(() => buildFilter(f)), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => setPlaneFilter(null), []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const airlines = useMemo(() => {
    const counts = {};
    for (const a of aircraft) {
      const c = airlineOf(a);
      if (c) counts[c] = (counts[c] || 0) + 1;
    }
    if (f.airline && !counts[f.airline]) counts[f.airline] = 0;
    return Object.entries(counts).sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]));
  }, [aircraft, f.airline]);

  const set = (patch) => setStored({ ...f, ...patch });
  const active = [f.military, f.airline, f.alt[0] > 0 || f.alt[1] < ALT_MAX, f.cats.length > 0].filter(Boolean).length;
  const shown = dimmed ? aircraft.length - dimmed.size : aircraft.length;
  const toggleCat = (id) => set({ cats: f.cats.includes(id) ? f.cats.filter((c) => c !== id) : [...f.cats, id] });
  const setAlt = (i, v) => {
    const alt = [...f.alt];
    alt[i] = Number(v);
    if (alt[0] > alt[1]) alt[1 - i] = alt[i];
    set({ alt });
  };

  return (
    <div className="filters">
      <button
        className={`filters__btn ${active ? "is-active" : ""}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label={active ? `Filtry, aktivní: ${active}` : "Filtry"}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={FUNNEL} />
        </svg>
        <span className="filters__label">Filtry</span>
        {active > 0 && <span className="filters__count">{active}</span>}
      </button>

      {open && (
        <>
          <div className="filters__backdrop" onClick={() => setOpen(false)} />
          <div className="filters__card" role="dialog" aria-label="Filtry mapy">
            <div className="filters__head">
              <h3>Filtry</h3>
              <span className="filters__match">
                {shown} z {aircraft.length}
              </span>
              {active > 0 && (
                <button className="filters__reset" onClick={() => setStored(DEFAULT)}>
                  Zrušit
                </button>
              )}
              <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Zavřít filtry">
                ✕
              </button>
            </div>

            <label className="filters__row">
              <span>Jen vojenská</span>
              <input type="checkbox" className="fl-switch" checked={f.military} onChange={(e) => set({ military: e.target.checked })} />
            </label>

            <section>
              <h4>Kategorie</h4>
              <div className="fl-chips">
                {CATEGORIES.map((c) => (
                  <button key={c.id} className={`fl-chip ${f.cats.includes(c.id) ? "is-on" : ""}`} aria-pressed={f.cats.includes(c.id)} onClick={() => toggleCat(c.id)}>
                    {c.label}
                  </button>
                ))}
              </div>
            </section>

            <section>
              <h4>
                Výška <span>{altLabel(f.alt)}</span>
              </h4>
              <div className="range2" style={{ "--lo": f.alt[0] / ALT_MAX, "--hi": f.alt[1] / ALT_MAX }}>
                <input type="range" min="0" max={ALT_MAX} step={ALT_STEP} value={f.alt[0]} onChange={(e) => setAlt(0, e.target.value)} aria-label="Výška od" />
                <input type="range" min="0" max={ALT_MAX} step={ALT_STEP} value={f.alt[1]} onChange={(e) => setAlt(1, e.target.value)} aria-label="Výška do" />
              </div>
              <div className="range2__scale" aria-hidden="true">
                <span>Zem</span>
                <span>{metres(ALT_MAX / 2)}</span>
                <span>{metres(ALT_MAX)}+</span>
              </div>
            </section>

            <section>
              <h4>Aerolinka</h4>
              {airlines.length === 0 ? (
                <p className="filters__empty">Teď není vidět žádná linka</p>
              ) : (
                <div className="fl-chips fl-chips--scroll">
                  <button className={`fl-chip ${!f.airline ? "is-on" : ""}`} aria-pressed={!f.airline} onClick={() => set({ airline: null })}>
                    Všechny
                  </button>
                  {airlines.map(([code, n]) => (
                    <button key={code} className={`fl-chip ${f.airline === code ? "is-on" : ""}`} aria-pressed={f.airline === code} onClick={() => set({ airline: f.airline === code ? null : code })}>
                      {code} <small>{n}</small>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
