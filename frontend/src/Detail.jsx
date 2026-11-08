import { EMERGENCY_SQUAWKS, altitudeHue, callsign, isGround } from "./aircraft.js";

const num = (n) => Math.round(n).toLocaleString("cs-CZ");
const DIRS = ["S", "SV", "V", "JV", "J", "JZ", "Z", "SZ"];

function altitude(a) {
  if (isGround(a)) return ["Na zemi", null];
  if (typeof a.alt_baro !== "number") return ["—", null];
  return [`${num(a.alt_baro)} ft`, `${num(a.alt_baro * 0.3048)} m`];
}

function speed(a) {
  if (a.gs == null) return ["—", null];
  return [`${num(a.gs * 1.852)} km/h`, `${num(a.gs)} kt`];
}

function heading(a) {
  if (a.track == null) return ["—", null];
  return [`${Math.round(a.track)}°`, DIRS[Math.round(a.track / 45) % 8]];
}

function vertical(a) {
  const r = a.baro_rate;
  if (r == null) return ["—", null];
  if (Math.abs(r) < 200) return ["Vodorovně", `${num(r)} ft/min`];
  return [r > 0 ? `↑ ${num(r)}` : `↓ ${num(-r)}`, r > 0 ? "ft/min, stoupá" : "ft/min, klesá"];
}

function Stat({ label, value: [main, sub] }) {
  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <span className="stat__value">{main}</span>
      {sub && <span className="stat__sub">{sub}</span>}
    </div>
  );
}

export default function Detail({ a, lost, onClose }) {
  const hue = altitudeHue(a);
  const emergency = EMERGENCY_SQUAWKS[a.squawk];
  const military = Boolean(a.dbFlags & 1);
  const subtitle = [a.t, a.r].filter(Boolean).join(" · ") || "Neznámý typ";

  return (
    <div className="detail">
      <div className="detail__head">
        <span className="detail__icon" style={{ "--h": hue ?? 0 }} data-ground={hue == null || undefined}>
          ✈︎
        </span>
        <div className="detail__title">
          <h3>{callsign(a)}</h3>
          <p>{subtitle}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Zavřít detail">
          ✕
        </button>
      </div>

      {(lost || emergency || military) && (
        <div className="badges">
          {lost && <span className="badge">Signál ztracen, poslední známá data</span>}
          {emergency && <span className="badge badge--danger">Squawk {a.squawk}: {emergency}</span>}
          {military && <span className="badge badge--accent">Vojenské</span>}
        </div>
      )}

      <div className="stats">
        <Stat label="Výška" value={altitude(a)} />
        <Stat label="Rychlost" value={speed(a)} />
        <Stat label="Kurz" value={heading(a)} />
        <Stat label="Vertikální rychlost" value={vertical(a)} />
        <Stat label="Registrace" value={[a.r || "—", null]} />
        <Stat label="Squawk" value={[a.squawk || "—", null]} />
      </div>

      <p className="detail__hex">ICAO {a.hex.toUpperCase()}</p>
    </div>
  );
}
