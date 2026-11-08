import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { useApp, useInterval, useMapLayer, usePollMs, useStored } from "./state.jsx";
import { EMERGENCY_SQUAWKS, altitudeHue, callsign, isGround } from "./aircraft.js";
import "./Detail.css";

const num = (n) => Math.round(n).toLocaleString("cs-CZ");
const DIRS = ["S", "SV", "V", "JV", "J", "JZ", "Z", "SZ"];

function altitude(a) {
  if (isGround(a)) return ["Na zemi", null];
  if (typeof a.alt_baro !== "number") return ["—", null];
  return [`${num(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m`, "nad mořem"];
}

function speed(a) {
  if (a.gs == null) return ["—", null];
  return [`${num(a.gs * 1.852)} km/h`, "vůči zemi"];
}

function heading(a) {
  if (a.track == null) return ["—", null];
  return [`${Math.round(a.track)}°`, DIRS[Math.round(a.track / 45) % 8]];
}

function vertical(a) {
  if (a.baro_rate == null) return ["—", null];
  const r = (a.baro_rate * 0.3048) / 60; // ft/min -> m/s
  const ms = (v) => `${Math.abs(v).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} m/s`;
  if (Math.abs(r) < 1) return ["Vodorovně", ms(r)];
  return [r > 0 ? `↑ ${ms(r)}` : `↓ ${ms(r)}`, r > 0 ? "stoupá" : "klesá"];
}

// ---- Extra facts (all metric). Every helper returns null when the data isn't there, and the row is hidden.

const kmh = (kt) => `${num(kt * 1.852)} km/h`;
const metres = (ft) => `${num(Math.round((ft * 0.3048) / 10) * 10)} m`;
const compass = (deg) => DIRS[Math.round(deg / 45) % 8];

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * r) / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

function bearing(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * r) * Math.cos(lat2 * r);
  const x = Math.cos(lat1 * r) * Math.sin(lat2 * r) - Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos((lon2 - lon1) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}

const flag = (iso) => (/^[A-Z]{2}$/.test(iso || "") ? String.fromCodePoint(...[...iso].map((c) => 127397 + c.charCodeAt(0))) : "");

const CATEGORY = {
  A1: "Lehké letadlo", A2: "Malé letadlo", A3: "Velké letadlo", A4: "Velké letadlo (silné víry)",
  A5: "Těžké letadlo", A6: "Vysoce výkonné letadlo", A7: "Vrtulník",
  B1: "Kluzák", B2: "Balon", B3: "Parašutista", B4: "Ultralight", B6: "Dron", B7: "Kosmické plavidlo",
  C1: "Pozemní vozidlo (záchranné)", C2: "Pozemní vozidlo", C3: "Překážka",
};

const SQUAWK = {
  ...EMERGENCY_SQUAWKS,
  7000: "VFR let bez přiděleného kódu",
  2000: "Zatím bez přiděleného kódu",
  1000: "Identifikace přes Mode S, běžné v Evropě",
  "0020": "Záchranný vrtulník (v Česku)",
};

// Route progress, only for a route that fits the aircraft's position.
function progress(route, a) {
  const o = route?.origin, d = route?.destination;
  if (!o || !d || route.plausible === false || [o.lat, o.lon, d.lat, d.lon].some((v) => typeof v !== "number")) return null;
  const flown = km(o.lat, o.lon, a.lat, a.lon);
  const left = km(a.lat, a.lon, d.lat, d.lon);
  const eta = a.gs > 50 && !isGround(a) ? new Date(Date.now() + (left / (a.gs * 1.852)) * 3_600_000) : null;
  return { flown, left, frac: flown / (flown + left), eta };
}

// Flight phase from altitude and vertical rate; "after take-off"/"to landing" only when the route backs it up.
function phase(a, prog) {
  if (isGround(a)) return "Na zemi";
  if (typeof a.alt_baro !== "number") return null;
  const r = a.baro_rate ?? 0;
  if (r > 300) return prog && prog.flown < 150 ? "Stoupá po vzletu" : "Stoupá";
  if (r < -300) return prog && prog.left < 200 ? "Klesá na přistání" : "Klesá";
  return a.alt_baro >= 20000 ? "Cestovní hladina" : "Vodorovný let";
}

function ago(s) {
  if (s < 60) return `před ${Math.max(0, Math.round(s))} s`;
  return `před ${Math.round(s / 60)} min`;
}

function Row({ label, children, sub }) {
  if (children == null || children === "" || children === false) return null;
  return (
    <div className="facts__row">
      <dt>{label}</dt>
      <dd>
        {children}
        {sub && <small>{sub}</small>}
      </dd>
    </div>
  );
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

// ---- Enrichment: photo, route, trail. Each part fails soft: if its endpoint errors, it is not shown.

// GET a JSON url; state is "loading" | "ok" | "error". `url` null = skip.
function useJson(url, refreshMs) {
  const [res, setRes] = useState({ state: "loading", data: null });
  const reload = useRef(null);
  useInterval(() => reload.current?.(), refreshMs);
  useEffect(() => {
    if (!url) return setRes({ state: "error", data: null });
    let alive = true;
    setRes({ state: "loading", data: null });
    const load = () =>
      fetch(url)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((data) => alive && setRes({ state: "ok", data }))
        .catch(() => alive && setRes((s) => (s.data ? s : { state: "error", data: null })));
    load();
    reload.current = load;
    return () => {
      alive = false;
      reload.current = null;
    };
  }, [url]);
  return res;
}

const PLACEHOLDER_PLANE =
  "M12 1.5c.9 0 1.4 1 1.4 2.2v5.4l8 4.8v2.2l-8-2.5v4.6l2.3 1.7v1.7L12 20.8l-3.7.8v-1.7l2.3-1.7v-4.6l-8 2.5v-2.2l8-4.8V3.7c0-1.2.5-2.2 1.4-2.2z";

function Photo({ a }) {
  const key = a.r || a.hex;
  const { state, data } = useJson(`/api/photo/${encodeURIComponent(key)}`);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [key]);
  if (state === "error") return null;

  const p = data?.photo;
  if (state === "loading" || p) {
    return (
      <figure className="photo" data-loading={!loaded || undefined}>
        {p && (
          <a href={p.link} target="_blank" rel="noopener noreferrer" aria-label="Fotka na planespotters.net">
            <img src={p.thumbnail_large || p.thumbnail} alt={`Letadlo ${a.r || ""}`} onLoad={() => setLoaded(true)} />
          </a>
        )}
        {p && (
          <figcaption>
            Foto: {p.photographer} /{" "}
            <a href={p.link} target="_blank" rel="noopener noreferrer">
              planespotters.net
            </a>
          </figcaption>
        )}
      </figure>
    );
  }
  return (
    <div className="photo photo--none">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d={PLACEHOLDER_PLANE} />
      </svg>
      <span>Fotka tohoto letadla zatím není</span>
    </div>
  );
}

function Airport({ ap, align }) {
  if (!ap) return <div className={`route__ap route__ap--${align}`}><b>?</b><span>Neznámé</span></div>;
  return (
    <div className={`route__ap route__ap--${align}`} title={[ap.name, ap.location].filter(Boolean).join(", ")}>
      <b>{ap.iata || ap.icao}</b>
      <span>{ap.location || ap.name}</span>
      {ap.location && ap.name && <small>{ap.name}</small>}
    </div>
  );
}

function Route({ res: { state, data }, prog }) {
  if (state === "error") return null;
  if (state === "loading") return <div className="route route--loading" aria-hidden="true" />;

  const r = data?.route;
  if (!data?.known || !r) {
    return (
      <div className="route route--unknown">
        <span className="route__line" />
        <p>Trasa letu není známá</p>
      </div>
    );
  }
  const stops = (r.stops || []).map((s) => s.iata || s.icao).filter(Boolean);
  return (
    <div className="route">
      {r.airline_name && <p className="route__airline">{r.airline_name}</p>}
      <Airport ap={r.origin} align="from" />
      <div className="route__mid" aria-hidden="true">
        <span className="route__line" />
        <svg viewBox="0 0 24 24">
          <path d={PLACEHOLDER_PLANE} />
        </svg>
        {stops.length > 0 && <small>přes {stops.join(", ")}</small>}
      </div>
      <Airport ap={r.destination} align="to" />
      {prog && (
        <div className="route__progress">
          <div className="route__bar" style={{ "--p": prog.frac }} role="progressbar" aria-valuenow={Math.round(prog.frac * 100)} aria-valuemin="0" aria-valuemax="100" aria-label="Průběh letu">
            <span />
          </div>
          <p>
            <span>Uletěno {num(prog.flown)} km</span>
            <span>zbývá {num(prog.left)} km</span>
          </p>
          {prog.eta && (
            <p className="route__eta">
              Přílet asi v {prog.eta.toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}{" "}
              <small>odhad přímou čarou při současné rychlosti</small>
            </p>
          )}
        </div>
      )}
      {r.plausible === false && <p className="route__note">Trasa je jen pravděpodobná, úplně nesedí k poloze letadla</p>}
    </div>
  );
}

// Altitude-coloured, fading polyline of the last 15 min. Lives as long as the detail is open.
function useTrail(a) {
  const ms = usePollMs("trail"); // null in battery saver: no trail
  const { data } = useJson(ms === null ? null : `/api/trail/${a.hex}`, ms);
  const points = data?.points || [];
  useMapLayer(
    (map) => {
      if (points.length < 1) return;
      const pts = points.map((p) => ({ ll: [p[1], p[2]], alt: p[3] }));
      pts.push({ ll: [a.lat, a.lon], alt: a.alt_baro }); // join the trail to the live marker
      const group = L.layerGroup().addTo(map);
      // Halo under the whole trail so it reads on both light and dark tiles.
      L.polyline(pts.map((p) => p.ll), { className: "trail-halo", interactive: false }).addTo(group);
      for (let i = 1; i < pts.length; i++) {
        const hue = altitudeHue({ alt_baro: pts[i].alt });
        const seg = L.polyline([pts[i - 1].ll, pts[i].ll], { className: "trail-seg", interactive: false }).addTo(group);
        const el = seg.getElement();
        if (el) {
          el.style.setProperty("--h", hue ?? 0);
          el.style.setProperty("--o", (0.35 + 0.65 * (i / (pts.length - 1))).toFixed(2));
          if (hue == null) el.classList.add("trail-seg--ground");
        }
      }
      return () => group.remove();
    },
    [data, a.hex, a.lat, a.lon],
  );
}

// "Letadlo" facts (registry + type stats) and the technical extras behind "Více údajů".
function Facts({ a, live, info, home, now }) {
  const [more, setMore] = useStored("skywatch.detailMore", false);
  const x = { ...a, ...live }; // live record has everything /api/aircraft has, plus IAS/TAS/wind/...
  const typeName = info?.manufacturer && info?.type ? `${info.manufacturer} ${info.type}` : null;
  const ts = live?.type_stats;
  const seenAgo = x.seen_pos != null && now ? (Date.now() - now) / 1000 + x.seen_pos : null;
  const fromHome = home && typeof a.lat === "number" ? [km(home.lat, home.lon, a.lat, a.lon), bearing(home.lat, home.lon, a.lat, a.lon)] : null;
  const owner = info?.owner;
  const squawk = x.squawk && SQUAWK[x.squawk];
  const wind = x.ws != null && x.wd != null;
  // True airspeed as the value; indicated airspeed and Mach as the subline.
  const airSub = [x.ias != null && `IAS ${kmh(x.ias)}`, x.mach != null && `Mach ${x.mach.toLocaleString("cs-CZ", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`].filter(Boolean).join(" · ");
  const source = { adsb_icao: "ADS-B", adsb_icao_nt: "ADS-B", mlat: "MLAT (triangulace)", mode_s: "Mode S", tisb_icao: "TIS-B", adsr_icao: "ADS-R" }[x.type];

  return (
    <>
      <section className="facts">
        <h4>Letadlo</h4>
        <dl>
          <Row label="Typ" sub={CATEGORY[x.category]}>{typeName || x.t}</Row>
          <Row label="Registrace">{x.r}</Row>
          <Row label="Provozovatel" sub={info?.owner_country}>{owner && `${flag(info.owner_country_iso)} ${owner}`.trim()}</Row>
          <Row label="Squawk" sub={squawk}>{x.squawk}</Row>
          {ts && (
            <Row label="Tento typ tu" sub={ts.aircraft_24h <= 1 ? "vzácný host" : null}>
              {ts.aircraft_24h <= 1 ? "za 24 h jen toto letadlo" : `za 24 h ${num(ts.aircraft_24h)} letadel`}
            </Row>
          )}
          {fromHome && (
            <Row label="Od domova" sub={`směrem na ${compass(fromHome[1])}`}>
              {fromHome[0] < 10 ? fromHome[0].toLocaleString("cs-CZ", { maximumFractionDigits: 1 }) : num(fromHome[0])} km
            </Row>
          )}
        </dl>
      </section>

      <section className="facts facts--more">
        <button className="facts__toggle" aria-expanded={more} onClick={() => setMore(!more)}>
          Více údajů
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
        {more && (
          <dl>
            {/* Only when it differs from the current altitude, i.e. the plane is heading somewhere else. */}
            <Row label="Autopilot míří do">{x.nav_altitude_mcp != null && typeof x.alt_baro === "number" && Math.abs(x.nav_altitude_mcp - x.alt_baro) > 250 && metres(x.nav_altitude_mcp)}</Row>
            <Row label="Rychlost vůči vzduchu" sub={airSub}>{x.tas != null ? kmh(x.tas) : x.ias != null && kmh(x.ias)}</Row>
            <Row label="Vítr ve výšce letu">{wind && `z ${compass(x.wd)} (${Math.round(x.wd)}°), ${kmh(x.ws)}`}</Row>
            <Row label="Teplota venku">{x.oat != null && `${Math.round(x.oat)} °C`}</Row>
            <Row label="Výška podle GPS">{typeof x.alt_geom === "number" && metres(x.alt_geom)}</Row>
            <Row label="Poslední poloha" sub={source}>{seenAgo != null && ago(seenAgo)}</Row>
            <Row label="ICAO adresa">{a.hex.toUpperCase()}</Row>
          </dl>
        )}
      </section>
    </>
  );
}

export default function Detail({ a, lost, onClose }) {
  const { home } = useApp();
  const hue = altitudeHue(a);
  const emergency = EMERGENCY_SQUAWKS[a.squawk];
  const military = Boolean(a.dbFlags & 1);
  const cs = (a.flight || "").trim();
  const routeRes = useJson(cs ? `/api/route/${encodeURIComponent(cs)}` : null);
  const liveRes = useJson(`/api/aircraft/${a.hex}`, usePollMs("aircraft"));
  const info = useJson(/^[0-9a-f]{6}$/.test(a.hex) ? `/api/registry/${a.hex}` : null).data?.info;
  const route = routeRes.data?.route;
  const prog = progress(route, a);
  const flightPhase = phase(a, prog);
  const subtitle = [route?.airline_name, a.t, a.r].filter(Boolean).join(" · ") || "Neznámý typ";
  useTrail(a);

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

      {(lost || emergency || military || flightPhase) && (
        <div className="badges">
          {lost && <span className="badge">Signál ztracen, poslední známá data</span>}
          {emergency && <span className="badge badge--danger">Squawk {a.squawk}: {emergency}</span>}
          {military && <span className="badge badge--accent">Vojenské</span>}
          {flightPhase && !lost && <span className="badge badge--phase">{flightPhase}</span>}
        </div>
      )}

      <Photo key={`p${a.hex}`} a={a} />
      <Route key={`r${a.hex}${cs}`} res={routeRes} prog={prog} />

      <div className="stats">
        <Stat label="Výška" value={altitude(a)} />
        <Stat label="Rychlost" value={speed(a)} />
        <Stat label="Kurz" value={heading(a)} />
        <Stat label="Vertikální rychlost" value={vertical(a)} />
      </div>

      <Facts a={a} live={liveRes.data?.aircraft ? { ...liveRes.data.aircraft, type_stats: liveRes.data.type_stats } : null} info={info} home={home} now={liveRes.data?.now} />
    </div>
  );
}
