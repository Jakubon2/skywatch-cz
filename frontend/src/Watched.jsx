import { useEffect, useState } from "react";
import L from "leaflet";
import { PLANE_SVG, altitudeHue, isGround } from "./aircraft.js";
import { useApp, useInterval, useMapLayer, usePollMs, useStored } from "./state.jsx";
import "./Watched.css";

// Known categories first, in this order; anything the user adds goes after them alphabetically.
const ORDER = ["hudba", "film a TV", "sport", "byznys", "královské rody"];
const GLYPH = { hudba: "♪", "film a TV": "★", sport: "◎", byznys: "◆", "královské rody": "♛" };

const fmt = (n, d = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: d });
const normReg = (r) => (r || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("cs-CZ") : "?");
const host = (url) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

function liveText(a) {
  if (isGround(a)) return "Na zemi";
  const parts = [];
  if (typeof a.alt_baro === "number") parts.push(`${fmt(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m`);
  if (a.gs != null) parts.push(`${fmt(a.gs * 1.852)} km/h`);
  return parts.join(" · ") || "Ve vzduchu";
}

function useWatchlist() {
  const [state, setState] = useState({ status: "loading", entries: [], note: null });
  const load = () =>
    fetch("/api/watchlist")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setState({ status: "ok", entries: d.entries, note: d.note }))
      .catch(() => setState((s) => ({ ...s, status: s.entries.length ? "ok" : "error" })));
  useEffect(() => {
    load();
  }, []);
  useInterval(load, usePollMs("watchlist"));
  return [state, load];
}

// Registrations that already have an alert rule, so the button can say so.
function useAlertRegs() {
  const [regs, setRegs] = useState(new Set());
  const load = () =>
    fetch("/api/alerts")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((rules) => setRegs(new Set(rules.flatMap((r) => (r.active ? r.rule.registrations || [] : [])).map(normReg))))
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);
  return [regs, load];
}

function LiveRow({ e, onSelect }) {
  const a = e.live;
  const hue = altitudeHue(a);
  return (
    <li>
      <button className="wl-live" onClick={() => onSelect(e)}>
        <span
          className="wl-live__icon"
          style={{ "--h": hue ?? 0, "--rot": `${a.track ?? 0}deg` }}
          data-ground={hue == null || undefined}
          dangerouslySetInnerHTML={{ __html: PLANE_SVG }}
        />
        <span className="wl-live__main">
          <span className="wl-live__title">{e.label}</span>
          <span className="wl-live__sub">
            {e.reg}
            {e.type && ` · ${e.type}`} · {liveText(a)}
          </span>
        </span>
        <span className="wl-live__go" aria-hidden="true">›</span>
      </button>
    </li>
  );
}

function EntryRow({ e, alerted, onAlert, onRemove, onSelect }) {
  const [busy, setBusy] = useState(null); // null | "alert" | "remove"
  const [error, setError] = useState(null);
  const run = (kind, fn) => {
    setBusy(kind);
    setError(null);
    fn()
      .catch((err) => setError(err.message || "Nepovedlo se, zkus to znovu."))
      .finally(() => setBusy(null));
  };

  return (
    <li className={`wl-entry${e.live ? " wl-entry--live" : ""}`}>
      <div className="wl-entry__head">
        <span className="wl-entry__text">
          <span className="wl-entry__label">
            {e.label}
            {e.live && (
              <button className="wl-flying" onClick={() => onSelect(e)}>
                <span className="wl-flying__dot" /> právě letí
              </button>
            )}
          </span>
          <span className="wl-entry__reg">
            {e.reg}
            {e.type && <span className="wl-entry__type">{e.type}</span>}
          </span>
        </span>
        <span className="wl-entry__actions">
          <button
            className={`btn btn--small${alerted ? " wl-alerted" : ""}`}
            disabled={alerted || busy != null}
            onClick={() => run("alert", () => onAlert(e))}
          >
            {alerted ? "✓ Upozorním tě" : busy === "alert" ? "Ukládám…" : "Upozornit mě"}
          </button>
          <button
            className="icon-btn wl-remove"
            aria-label={`Odebrat ${e.label} (${e.reg})`}
            title="Odebrat ze seznamu"
            disabled={busy != null}
            onClick={() => window.confirm(`Odebrat ${e.label} (${e.reg}) ze seznamu?`) && run("remove", () => onRemove(e))}
          >
            ×
          </button>
        </span>
      </div>
      {e.note && <p className="wl-entry__note">{e.note}</p>}
      <p className="wl-entry__source">
        Zdroj:{" "}
        <a href={e.source} target="_blank" rel="noopener noreferrer">
          {host(e.source)}
        </a>{" "}
        · ověřeno {day(e.checked)}
      </p>
      {error && <p className="form-note form-note--error">{error}</p>}
    </li>
  );
}

const EMPTY_FORM = { reg: "", label: "", category: "", type: "", hex: "", source: "", note: "" };

function AddForm({ categories, onDone, onCancel }) {
  const [f, setF] = useState(EMPTY_FORM);
  const [state, setState] = useState({ busy: false, error: null });
  const set = (k) => (ev) => setF({ ...f, [k]: ev.target.value });

  const submit = (ev) => {
    ev.preventDefault();
    setState({ busy: true, error: null });
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() || null]).filter(([, v]) => v));
    fetch("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(async (r) => {
        if (r.ok) return onDone();
        const d = await r.json().catch(() => ({}));
        const msg =
          r.status === 409
            ? d.detail
            : "Zkontroluj údaje: registrace, jméno, kategorie a odkaz na veřejný zdroj (https://…). Hex má 6 znaků 0–9/a–f.";
        setState({ busy: false, error: msg });
      })
      .catch(() => setState({ busy: false, error: "Server neodpovídá, zkus to znovu." }));
  };

  return (
    <form className="wl-form" onSubmit={submit}>
      <p className="wl-form__intro">
        Přidávej jen letadla <strong>veřejně známých osobností</strong>, nikdy soukromých lidí, a vždy s odkazem na veřejný zdroj.
      </p>
      <div className="wl-form__grid">
        <label>
          <span>Registrace</span>
          <input value={f.reg} onChange={set("reg")} placeholder="N621MM" required maxLength={12} autoCapitalize="characters" />
        </label>
        <label>
          <span>Typ (ICAO, volitelně)</span>
          <input value={f.type} onChange={set("type")} placeholder="FA7X" maxLength={4} autoCapitalize="characters" />
        </label>
        <label className="wl-form__wide">
          <span>Osobnost</span>
          <input value={f.label} onChange={set("label")} placeholder="Jméno osobnosti" required maxLength={80} />
        </label>
        <label>
          <span>Kategorie</span>
          <input value={f.category} onChange={set("category")} list="wl-categories" placeholder="sport" required maxLength={40} />
          <datalist id="wl-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
        <label>
          <span>Hex (volitelně)</span>
          <input value={f.hex} onChange={set("hex")} placeholder="a81b13" pattern="[0-9a-fA-F]{6}" maxLength={6} />
        </label>
        <label className="wl-form__wide">
          <span>Veřejný zdroj</span>
          <input type="url" value={f.source} onChange={set("source")} placeholder="https://…" required />
        </label>
        <label className="wl-form__wide">
          <span>Poznámka (volitelně)</span>
          <input value={f.note} onChange={set("note")} placeholder="Např. registrováno na firmu…" maxLength={300} />
        </label>
      </div>
      {state.error && <p className="form-note form-note--error">{state.error}</p>}
      <div className="wl-form__buttons">
        <button type="button" className="btn btn--link" onClick={onCancel}>
          Zrušit
        </button>
        <button className="btn btn--primary" disabled={state.busy}>
          {state.busy ? "Ukládám…" : "Přidat do seznamu"}
        </button>
      </div>
    </form>
  );
}

export default function Watched() {
  const { select, flyTo } = useApp();
  const [{ status, entries, note }, reload] = useWatchlist();
  const [alertRegs, reloadAlerts] = useAlertRegs();
  const [closed, setClosed] = useStored("skywatch.watched.closed", []);
  const [adding, setAdding] = useState(false);

  const live = entries.filter((e) => e.live);

  // While this tab is open: a ring around every watched plane in range.
  useMapLayer(
    (map) => {
      const rings = live.map((e) =>
        L.marker([e.live.lat, e.live.lon], {
          icon: L.divIcon({ className: "wl-ring", iconSize: [44, 44] }),
          interactive: false,
          keyboard: false,
        })
          .bindTooltip(e.label, { permanent: true, direction: "top", offset: [0, -20], className: "wl-ring__label" })
          .addTo(map),
      );
      return () => rings.forEach((r) => r.remove());
    },
    [live.map((e) => `${e.reg}@${e.live.lat},${e.live.lon}`).join("|")],
  );

  const showOnMap = (e) => {
    select(e.live.hex);
    flyTo(e.live.lat, e.live.lon, 9);
  };

  const alert = (e) =>
    fetch("/api/alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: `Sledované letadlo: ${e.label} (${e.reg})`, rule: { registrations: [e.reg] } }),
    }).then((r) => {
      if (!r.ok) throw new Error("Upozornění se nepodařilo uložit.");
      return reloadAlerts();
    });

  const remove = (e) =>
    fetch(`/api/watchlist/${encodeURIComponent(e.reg)}`, { method: "DELETE" }).then((r) => {
      if (!r.ok && r.status !== 404) throw new Error("Odebrání se nepovedlo.");
      return reload();
    });

  const categories = [...new Set(entries.map((e) => e.category))].sort((a, b) => {
    const ia = ORDER.indexOf(a) + 1 || 99;
    const ib = ORDER.indexOf(b) + 1 || 99;
    return ia - ib || a.localeCompare(b, "cs");
  });
  const toggle = (c) => setClosed(closed.includes(c) ? closed.filter((x) => x !== c) : [...closed, c]);

  if (status === "loading") return <p className="wl-loading">Načítám seznam…</p>;
  if (status === "error")
    return (
      <div className="empty">
        <div className="empty__icon">!</div>
        <p className="empty__title">Seznam se nepodařilo načíst</p>
        <p>Server teď neodpovídá. Zkusím to znovu za chvilku.</p>
      </div>
    );

  return (
    <div className="wl">
      <div className="wl-hero">
        <span className="wl-hero__icon" aria-hidden="true">★</span>
        <span className="wl-hero__text">
          <span className="wl-hero__title">Sledovaná letadla</span>
          <span className="wl-hero__sub">
            {entries.length} tryskáčů známých osobností ·{" "}
            {live.length ? <strong>{live.length} právě v dosahu</strong> : "teď žádný v dosahu"}
          </span>
        </span>
      </div>

      {live.length > 0 && (
        <section>
          <h2 className="section-title">Právě letí</h2>
          <ul className="wl-live-list">
            {live.map((e) => (
              <LiveRow key={e.reg} e={e} onSelect={showOnMap} />
            ))}
          </ul>
        </section>
      )}

      {adding ? (
        <AddForm
          categories={categories}
          onCancel={() => setAdding(false)}
          onDone={() => {
            setAdding(false);
            reload();
          }}
        />
      ) : (
        <button className="btn btn--ghost btn--block" onClick={() => setAdding(true)}>
          <span aria-hidden="true">＋</span> Přidat letadlo
        </button>
      )}

      {categories.map((c) => {
        const items = entries.filter((e) => e.category === c).sort((a, b) => Boolean(b.live) - Boolean(a.live) || a.label.localeCompare(b.label, "cs"));
        const open = !closed.includes(c);
        const flying = items.filter((e) => e.live).length;
        return (
          <section key={c} className="wl-group">
            <button className="wl-group__head" aria-expanded={open} onClick={() => toggle(c)}>
              <span className="wl-group__glyph" aria-hidden="true">{GLYPH[c] || "●"}</span>
              <span className="wl-group__name">{c}</span>
              <span className="wl-group__count">
                {flying > 0 && <span className="wl-flying__dot" />}
                {items.length}
              </span>
              <span className="wl-group__chev" aria-hidden="true">›</span>
            </button>
            {open && (
              <ul className="wl-list">
                {items.map((e) => (
                  <EntryRow
                    key={e.reg}
                    e={e}
                    alerted={alertRegs.has(normReg(e.reg))}
                    onAlert={alert}
                    onRemove={remove}
                    onSelect={showOnMap}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}

      {note && <p className="wl-disclaimer">{note}</p>}
    </div>
  );
}
