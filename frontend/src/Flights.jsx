// "Moje lety": follow a flight by its number (OK 640, FR 1234) or callsign; backend/flights.py does the
// tracking and sends push notifications (take-off, approach, landing) to this device only.
// FlightsLayer (overlay, always mounted) polls the list and draws flights outside our area on the map.
import { useEffect, useState, useSyncExternalStore } from "react";
import L from "leaflet";
import { useApp, useInterval, useMapLayer } from "./state.jsx";
import { PLANE_SVG } from "./aircraft.js";
import { pushEndpoint } from "./push.js";
import "./Flights.css";

const POLL_MS = [20_000, 60_000]; // [normal, battery saver]

// Same id as Stats.jsx (useStored("skywatch.deviceId")), so one device = one id.
export function deviceId() {
  try {
    const id = JSON.parse(localStorage.getItem("skywatch.deviceId"));
    if (id) return id;
  } catch {
    /* fall through */
  }
  const id = crypto.randomUUID();
  try {
    localStorage.setItem("skywatch.deviceId", JSON.stringify(id));
  } catch {
    /* not persisted: this session only */
  }
  return id;
}

// Tiny shared store: the list is fetched by the overlay and read by the tab.
let state = { flights: [], loaded: false, error: false };
const subs = new Set();
const setState = (s) => {
  state = { ...state, ...s };
  subs.forEach((f) => f());
};
const useFlights = () => useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => state);

async function call(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Server neodpovídá, zkus to znovu.");
  setState({ flights: d.flights, loaded: true, error: false });
  return d;
}

export const refreshFlights = () =>
  call("GET", `/api/flights/${deviceId()}`).catch(() => setState({ loaded: true, error: true }));

/** Start following a flight; used by the form here and the button in the aircraft detail. */
export async function trackFlight(query) {
  return call("POST", "/api/flights", { device_id: deviceId(), query, endpoint: await pushEndpoint() });
}

const untrack = (id) => call("DELETE", `/api/flights/${deviceId()}/${id}`);

// ---- formatting (data stays in ft/kt, shown metric) ----
const fmt = (n) => Math.round(n).toLocaleString("cs-CZ");
const hhmm = (s) => new Date(s * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
const altitude = (a) => (a.alt_baro === "ground" ? "na zemi" : typeof a.alt_baro === "number" ? `${fmt(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m` : "–");
const speed = (a) => (a.gs != null ? `${fmt(a.gs * 1.852)} km/h` : "–");
const code = (ap) => ap?.iata || ap?.icao || "?";
const city = (ap) => ap?.location || ap?.name || "";

const STATUS = {
  waiting: ["Čeká na odlet", "Zatím ho žádný přijímač nevidí."],
  ground: ["Na zemi", "Stojí nebo pojíždí na letišti."],
  airborne: ["Ve vzduchu", null],
  approach: ["Přistává", null],
  landed: ["Přistál", null],
  lost: ["Signál ztracen", "Letí mimo dosah přijímačů (třeba nad mořem). Až se znovu objeví, data se doplní."],
};

function ago(ts) {
  const min = Math.round((Date.now() / 1000 - ts) / 60);
  return min < 1 ? "právě teď" : min < 60 ? `před ${min} min` : `v ${hhmm(ts)}`;
}

function Progress({ f }) {
  const o = f.route?.origin, d = f.route?.destination, a = f.aircraft;
  if (!o || !d || !a || typeof o.lat !== "number" || f.dist_km == null) return null;
  const R = 6371, rad = Math.PI / 180;
  const total = 2 * R * Math.asin(Math.sqrt(Math.sin(((d.lat - o.lat) * rad) / 2) ** 2 + Math.cos(o.lat * rad) * Math.cos(d.lat * rad) * Math.sin(((d.lon - o.lon) * rad) / 2) ** 2));
  const p = f.status === "landed" ? 1 : Math.min(1, Math.max(0, 1 - f.dist_km / total));
  return (
    <div className="fl-progress" aria-label={`Uletěno asi ${Math.round(p * 100)} %`}>
      <div className="fl-progress__bar" style={{ width: `${p * 100}%` }} />
      <span className="fl-progress__plane" style={{ left: `${p * 100}%` }} dangerouslySetInnerHTML={{ __html: PLANE_SVG }} />
    </div>
  );
}

function Card({ f }) {
  const { aircraft, select, setView, flyTo, setOpen } = useApp();
  const [busy, setBusy] = useState(false);
  const [label, hint] = STATUS[f.status] || STATUS.waiting;
  const a = f.aircraft;
  const r = f.route;

  const show = () => {
    if (f.in_range && aircraft.some((x) => x.hex === a.hex)) {
      setView("map");
      select(a.hex);
    } else if (a) {
      setOpen(false);
      flyTo(a.lat, a.lon, 7);
    }
  };

  return (
    <li className={`fl-card fl-card--${f.status}`}>
      <div className="fl-card__head">
        <div>
          <h3>{f.query}</h3>
          <p>{[r?.airline_name, f.callsign !== f.query.replace(/\s/g, "") && f.callsign, a?.t, a?.r].filter(Boolean).join(" · ")}</p>
        </div>
        <span className={`fl-status fl-status--${f.status}`}>{f.guessed ? "Nejspíš přistál" : label}</span>
        <button className="icon-btn" disabled={busy} onClick={() => (setBusy(true), untrack(f.id).catch(() => setBusy(false)))} aria-label={`Přestat sledovat ${f.query}`}>
          ✕
        </button>
      </div>

      {f.route_doubtful && (
        <p className="fl-note">Letadlo letí jinam, než říká databáze tras. Trasa je nejspíš z předchozího letu, přílet proto neodhadneme.</p>
      )}
      {r?.origin && r?.destination && !f.route_doubtful ? (
        <div className="fl-route">
          <div>
            <b>{code(r.origin)}</b>
            <small>{city(r.origin)}</small>
          </div>
          <Progress f={f} />
          <div className="fl-route__to">
            <b>{code(r.destination)}</b>
            <small>{city(r.destination)}</small>
          </div>
        </div>
      ) : (
        a && !f.route_doubtful && <p className="fl-note">Trasa letu zatím není známá, přílet proto neodhadneme.</p>
      )}

      {a && f.status !== "waiting" && f.status !== "landed" && (
        <div className="fl-facts">
          <span>
            <small>Výška</small>
            {altitude(a)}
          </span>
          <span>
            <small>Rychlost</small>
            {speed(a)}
          </span>
          <span>
            <small>Přílet</small>
            {f.eta ? `~${hhmm(f.eta)}` : "–"}
          </span>
        </div>
      )}

      {f.status === "landed" && f.landed_at && (
        <p className="fl-note">
          {f.guessed
            ? `Naposledy viděn v ${hhmm(f.landed_at)} těsně před cílem, kde přijímače už nedosáhnou na zem. Přesný čas přistání neznáme.`
            : `Přistál v ${hhmm(f.landed_at)}.`}
        </p>
      )}
      {hint && <p className="fl-note">{hint}</p>}

      <div className="fl-card__foot">
        <span>{f.last_seen ? `Data ${ago(f.last_seen)}` : "Hledáme každou minutu"}</span>
        {a && f.status !== "landed" && (
          <button className="btn btn--ghost btn--small" onClick={show}>
            Ukázat na mapě
          </button>
        )}
      </div>
    </li>
  );
}

export default function Flights() {
  const { flights, loaded, error } = useFlights();
  const [q, setQ] = useState("");
  const [form, setForm] = useState({ busy: false, error: null });
  const [push, setPush] = useState(null);
  useEffect(() => {
    refreshFlights();
    pushEndpoint().then((e) => setPush(Boolean(e)));
  }, []);

  const submit = (ev) => {
    ev.preventDefault();
    setForm({ busy: true, error: null });
    trackFlight(q.trim())
      .then(() => (setQ(""), setForm({ busy: false, error: null })))
      .catch((e) => setForm({ busy: false, error: e.message }));
  };

  return (
    <div className="flights">
      <h2 className="section-title">Moje lety</h2>
      <form className="fl-form" onSubmit={submit}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Číslo letu, např. OK 640"
          aria-label="Číslo letu nebo volací znak"
          autoCapitalize="characters"
          autoComplete="off"
          required
          minLength={2}
          maxLength={20}
        />
        <button className="btn btn--primary" disabled={form.busy || q.trim().length < 2}>
          Sledovat
        </button>
      </form>
      {form.error && <p className="form-note form-note--error">{form.error}</p>}
      {push === false && (
        <p className="form-note">
          Upozornění na vzlet, přiblížení a přistání přijdou jen se zapnutými upozorněními (Nastavení). Zapni je dřív, než let přidáš.
        </p>
      )}

      {flights.length ? (
        <ul className="fl-list">
          {flights.map((f) => (
            <Card key={f.id} f={f} />
          ))}
        </ul>
      ) : (
        loaded && (
          <div className="empty">
            <p>{error ? "Seznam letů se nepodařilo načíst." : "Zatím nesleduješ žádný let."}</p>
          </div>
        )
      )}

      <p className="form-note form-note--small">
        Číslo letu z letenky (OK 640, FR 1234) převádíme na volací znak, který letadlo vysílá (CSA640, RYR1234). Ryanair,
        easyJet nebo Wizz Air ale často létají s jiným znakem (třeba RYR8NG). Když let nenajdeme, zadej volací znak, nebo
        klepni na letadlo na mapě a zvol „Sledovat let“. Data: adsb.lol, odhad příletu z polohy a rychlosti.
      </p>
    </div>
  );
}

// Overlay: keeps the list fresh and shows tracked flights that are outside our area (inside, the normal marker is there).
export function FlightsLayer() {
  const { saver, setView } = useApp();
  const { flights } = useFlights();
  useEffect(() => {
    refreshFlights();
  }, []);
  useInterval(refreshFlights, POLL_MS[saver ? 1 : 0]);

  const far = flights.filter((f) => f.aircraft && !f.in_range && f.status !== "landed");
  const key = far.map((f) => `${f.id}:${f.aircraft.lat}:${f.aircraft.lon}:${f.aircraft.track}`).join("|");
  useMapLayer(
    (map) => {
      const layers = far.map((f) => {
        const icon = L.divIcon({
          className: "ac-marker",
          html: `<div class="ac fl-far" style="--rot:${f.aircraft.track ?? 0}deg">${PLANE_SVG}</div><div class="ac-lbl fl-far__lbl"><b></b></div>`,
          iconSize: [32, 32],
        });
        const m = L.marker([f.aircraft.lat, f.aircraft.lon], { icon, keyboard: false }).on("click", () => setView("flights")).addTo(map);
        m.getElement().querySelector("b").textContent = f.query; // textContent: typed by the user
        return m;
      });
      return () => layers.forEach((l) => l.remove());
    },
    [key],
  );
  return null;
}
