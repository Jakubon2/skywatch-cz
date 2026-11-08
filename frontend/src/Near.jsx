import { useState } from "react";
import L from "leaflet";
import { PLANE_SVG, altitudeHue, callsign, isGround } from "./aircraft.js";
import { useApp, useMapLayer, useStored } from "./state.jsx";
import { visiblePadding } from "./Map.jsx";
import "./Near.css";

const RADII_KM = [5, 10, 15, 30];
const DIRS = ["S", "SV", "V", "JV", "J", "JZ", "Z", "SZ"];
const KM_PER_DEG = 111.32;
const fmt = (n, d = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: d });

// Plane position and velocity in a flat local frame around home (km, km/h). Fine for tens of km.
function relative(home, a) {
  const x = (a.lon - home.lon) * KM_PER_DEG * Math.cos((home.lat * Math.PI) / 180);
  const y = (a.lat - home.lat) * KM_PER_DEG;
  const v = a.gs != null && a.track != null && !isGround(a) ? a.gs * 1.852 : 0;
  const t = ((a.track ?? 0) * Math.PI) / 180;
  return { x, y, vx: v * Math.sin(t), vy: v * Math.cos(t), v };
}

// Distance now, plus closest approach on a straight line at constant speed.
function nearby(aircraft, home, radiusKm) {
  return aircraft
    .map((a) => {
      const { x, y, vx, vy, v } = relative(home, a);
      const dist = Math.hypot(x, y);
      let trend = "none"; // none | approaching | passing | leaving
      let cpaMin = null;
      let cpaKm = null;
      if (v > 30) {
        const tH = -(x * vx + y * vy) / (v * v);
        trend = tH > 0 ? "approaching" : "leaving";
        if (tH > 0) {
          cpaMin = tH * 60;
          cpaKm = Math.hypot(x + vx * tH, y + vy * tH);
          if (dist - cpaKm < 1) trend = "passing"; // barely gets closer: flies past sideways
        }
      }
      return { a, dist, trend, cpaMin, cpaKm };
    })
    .filter((r) => r.dist <= radiusKm)
    .sort((p, q) => p.dist - q.dist);
}

function trendText(r) {
  if (isGround(r.a)) return "Na zemi";
  if (r.trend === "leaving") return "Vzdaluje se";
  if (r.trend === "passing") return "Míjí bokem";
  if (r.trend === "approaching") {
    const when = r.cpaMin < 1 ? "teď" : `za ${fmt(r.cpaMin)} min`;
    return `Nejblíž ${when} · ${fmt(r.cpaKm, r.cpaKm < 10 ? 1 : 0)} km`;
  }
  return "Stojí na místě";
}

function Row({ r, onSelect }) {
  const { a } = r;
  const hue = altitudeHue(a);
  const alt = isGround(a) ? null : typeof a.alt_baro === "number" ? `${fmt(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m` : null;
  const dir = a.track != null && !isGround(a) ? `letí na ${DIRS[Math.round(a.track / 45) % 8]}` : null;
  return (
    <li>
      <button className="near-row" onClick={() => onSelect(a.hex)}>
        <span
          className="near-row__icon"
          style={{ "--h": hue ?? 0, "--rot": `${a.track ?? 0}deg` }}
          data-ground={hue == null || undefined}
          dangerouslySetInnerHTML={{ __html: PLANE_SVG }}
        />
        <span className="near-row__main">
          <span className="near-row__title">
            {callsign(a)} {a.t && <span className="near-row__type">{a.t}</span>}
          </span>
          <span className="near-row__sub">{[alt, dir].filter(Boolean).join(" · ") || "—"}</span>
        </span>
        <span className="near-row__side">
          <span className="near-row__dist">{fmt(r.dist, r.dist < 10 ? 1 : 0)} km</span>
          <span className={`near-row__trend near-row__trend--${r.trend}`}>{trendText(r)}</span>
        </span>
      </button>
    </li>
  );
}

function HomeForm({ onSave, onCancel }) {
  const [q, setQ] = useState("");
  const [state, setState] = useState({ status: "idle", results: [] }); // idle | busy | done | error | locating
  const [geoError, setGeoError] = useState(null);

  const search = (e) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setState({ status: "busy", results: [] });
    fetch(`/api/geocode?q=${encodeURIComponent(q.trim())}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((results) => setState({ status: "done", results }))
      .catch(() => setState({ status: "error", results: [] }));
  };

  const locate = () => {
    setGeoError(null);
    if (!navigator.geolocation) return setGeoError("Tenhle prohlížeč polohu neumí.");
    setState({ status: "locating", results: [] });
    navigator.geolocation.getCurrentPosition(
      (p) => onSave({ label: "Moje poloha", lat: p.coords.latitude, lon: p.coords.longitude }),
      (err) => {
        setState({ status: "idle", results: [] });
        setGeoError(err.code === 1 ? "Přístup k poloze je zakázaný. Povol ho v prohlížeči, nebo zadej adresu." : "Polohu se nepodařilo zjistit.");
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  };

  return (
    <div className="home-form">
      <div className="home-form__intro">
        <div className="empty__icon">⌂</div>
        <p className="empty__title">Co mi letí nad hlavou?</p>
        <p>Zadej adresu a uvidíš letadla v okolí. Uloží se jen v tomhle zařízení.</p>
      </div>

      <form className="search" onSubmit={search}>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Např. Vinohradská 12, Praha"
          aria-label="Adresa"
          enterKeyHint="search"
          autoComplete="street-address"
        />
        <button className="btn btn--primary" disabled={state.status === "busy" || q.trim().length < 2}>
          {state.status === "busy" ? "Hledám…" : "Hledat"}
        </button>
      </form>

      {state.status === "error" && <p className="form-note form-note--error">Hledání adresy selhalo. Zkus to znovu.</p>}
      {state.status === "done" && state.results.length === 0 && (
        <p className="form-note">Nic jsem nenašel. Zkus obec nebo přesnější adresu v Česku.</p>
      )}
      {state.results.length > 0 && (
        <ul className="results">
          {state.results.map((r) => (
            <li key={`${r.lat},${r.lon}`}>
              <button onClick={() => onSave(r)}>{r.label}</button>
            </li>
          ))}
        </ul>
      )}

      <div className="divider"><span>nebo</span></div>
      <button className="btn btn--ghost btn--block" onClick={locate} disabled={state.status === "locating"}>
        <span aria-hidden="true">◎</span> {state.status === "locating" ? "Zjišťuji polohu…" : "Použít moji polohu"}
      </button>
      {geoError && <p className="form-note form-note--error">{geoError}</p>}
      {onCancel && (
        <button className="btn btn--link btn--block" onClick={onCancel}>
          Zrušit
        </button>
      )}
      <p className="form-note form-note--small">Adresy hledá OpenStreetMap Nominatim.</p>
    </div>
  );
}

const HOME_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2 3.5 10v10.3h6v-6h5v6h6V10z"/></svg>';

// Always on the map (registered as the tab's overlay): the home pin.
export function HomePin() {
  const { home } = useApp();
  useMapLayer(
    (map) => {
      if (!home) return;
      const pin = L.marker([home.lat, home.lon], {
        icon: L.divIcon({ className: "home-marker", html: HOME_SVG, iconSize: [34, 34] }),
        keyboard: false,
        interactive: false,
        zIndexOffset: -1000,
      }).addTo(map);
      return () => pin.remove();
    },
    [home],
  );
  return null;
}

export default function Near() {
  const { aircraft, home, setHome, select: onSelect } = useApp();
  const [radius, setRadiusKm] = useStored("skywatch.radiusKm", 15);
  const radiusKm = RADII_KM.includes(radius) ? radius : 15;
  const [editing, setEditing] = useState(false);

  // While this tab is open: the search radius, fitted into the visible part of the map.
  useMapLayer(
    (map) => {
      if (!home) return;
      const circle = L.circle([home.lat, home.lon], { radius: radiusKm * 1000, className: "home-radius", interactive: false }).addTo(map);
      map.flyToBounds(circle.getBounds(), { ...visiblePadding(), duration: 0.6 });
      return () => circle.remove();
    },
    [home, radiusKm],
  );

  if (!home || editing)
    return (
      <HomeForm
        onSave={(h) => {
          setHome(h);
          setEditing(false);
        }}
        onCancel={home ? () => setEditing(false) : null}
      />
    );

  // Ground traffic (taxiing planes, airport vehicles) isn't "overhead": count it, don't list it.
  const all = nearby(aircraft, home, radiusKm);
  const rows = all.filter((r) => !isGround(r.a));
  const ground = all.length - rows.length;

  return (
    <div className="near">
      <div className="home-card">
        <span className="home-card__icon" aria-hidden="true">⌂</span>
        <div className="home-card__text">
          <span className="home-card__label">{home.label}</span>
          <span className="home-card__sub">
            {rows.length} ve vzduchu{ground > 0 && ` · ${ground} na zemi`}
          </span>
        </div>
        <button className="btn btn--small" onClick={() => setEditing(true)}>Změnit</button>
      </div>

      <div className="seg seg--small" role="radiogroup" aria-label="Okruh">
        {RADII_KM.map((r) => (
          <button key={r} role="radio" aria-checked={r === radiusKm} className={r === radiusKm ? "is-active" : ""} onClick={() => setRadiusKm(r)}>
            {r} km
          </button>
        ))}
      </div>

      {rows.length ? (
        <ul className="near-list">
          {rows.map((r) => (
            <Row key={r.a.hex} r={r} onSelect={onSelect} />
          ))}
        </ul>
      ) : (
        <div className="empty">
          <div className="empty__icon">☁︎</div>
          <p className="empty__title">Nad tebou je čisté nebe</p>
          <p>Do {radiusKm} km teď nic neletí. {radiusKm < 30 ? "Zkus větší okruh, nebo počkej chvilku." : "Počkej chvilku, data se obnovují každých 10 s."}</p>
          {radiusKm < 30 && (
            <button className="btn btn--ghost" onClick={() => setRadiusKm(RADII_KM[RADII_KM.indexOf(radiusKm) + 1])}>
              Zvětšit na {RADII_KM[RADII_KM.indexOf(radiusKm) + 1]} km
            </button>
          )}
        </div>
      )}
    </div>
  );
}
