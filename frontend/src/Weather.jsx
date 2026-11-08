// "Počasí a hluk" tab: noise estimate at home (/api/noise) and contrail forecast (/api/contrails).
import { useEffect, useState } from "react";
import { useApp, useInterval, usePollMs } from "./state.jsx";
import "./Weather.css";

const NOISE_RADIUS_KM = 20;
const SCALE = [20, 100]; // dB(A) range of the gauge
const TICKS = [
  [30, "šepot"],
  [50, "kancelář"],
  [70, "ulice"],
  [90, "kamion"],
];
const PHASE = { climb: "stoupá", approach: "klesá nízko", cruise: "cestovní let" };
const fmt = (n, d = 0) => n.toLocaleString("cs-CZ", { maximumFractionDigits: d });
const pct = (db) => Math.min(100, Math.max(0, ((db - SCALE[0]) / (SCALE[1] - SCALE[0])) * 100));

// Fetch JSON whenever `url` or `tick` changes; keep the last good data while reloading.
function useJson(url, tick) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    if (!url) return;
    let live = true;
    fetch(url)
      .then((r) => (r.ok ? r.json() : r.json().then((j) => Promise.reject(j.detail), () => Promise.reject())))
      .then((data) => live && setState({ data, error: null }))
      .catch((e) => live && setState((s) => ({ ...s, error: typeof e === "string" ? e : "Nepodařilo se načíst." })));
    return () => {
      live = false;
    };
  }, [url, tick]);
  return state;
}

function Gauge({ db }) {
  return (
    <div className="wx-gauge" role="img" aria-label={`Odhad ${fmt(db)} dB(A) na stupnici ${SCALE[0]} až ${SCALE[1]}`}>
      <div className="wx-gauge__track" style={{ "--p": `${pct(db)}%` }}>
        <span className="wx-gauge__mark" style={{ left: `${pct(db)}%` }} />
      </div>
      <div className="wx-gauge__ticks" aria-hidden="true">
        {TICKS.map(([v, t]) => (
          <span key={v} style={{ left: `${pct(v)}%` }}>
            <b>{v}</b> {t}
          </span>
        ))}
      </div>
    </div>
  );
}

function Noise({ home }) {
  const { aircraft, select } = useApp();
  const url = `/api/noise?lat=${home.lat}&lon=${home.lon}&radius_km=${NOISE_RADIUS_KM}`;
  const { data, error } = useJson(url, aircraft); // aircraft changes every 10 s poll

  return (
    <section className="wx-card">
      <div className="wx-card__head">
        <h3>Hluk u tebe</h3>
        <span className="wx-estimate">Odhad, ne měření</span>
      </div>

      {!data && !error && <p className="wx-muted">Počítám…</p>}
      {!data && error && <p className="form-note form-note--error">{error}</p>}

      {data && !data.loudest && (
        <div className="noise-hero noise-hero--quiet">
          <span className="noise-hero__db">Ticho</span>
          <p className="wx-muted">Do {NOISE_RADIUS_KM} km teď neletí nic, co by bylo slyšet.</p>
        </div>
      )}

      {data?.loudest && (
        <>
          <div className="noise-hero">
            <span className="noise-hero__db">
              {fmt(data.loudest.db)} <small>dB(A)</small>
            </span>
            <span className="noise-hero__label">{data.loudest.label}</span>
            <button className="noise-hero__plane" onClick={() => select(data.loudest.hex)}>
              Nejhlasitější: <b>{data.loudest.flight || data.loudest.hex.toUpperCase()}</b>
              {data.loudest.t && ` · ${data.loudest.t}`} · {fmt(data.loudest.slant_km, 1)} km od tebe
            </button>
          </div>
          <Gauge db={data.loudest.db} />

          {data.aircraft.length > 1 && (
            <>
              <p className="wx-muted wx-gap">
                Všechna letadla dohromady: <b>{fmt(data.total_db)} dB(A)</b>, {data.total_label}.
              </p>
              <ul className="noise-list">
                {data.aircraft.map((r) => (
                  <li key={r.hex}>
                    <button onClick={() => select(r.hex)}>
                      <span className="noise-list__main">
                        <span className="noise-list__title">
                          {r.flight || r.hex.toUpperCase()} {r.t && <span>{r.t}</span>}
                        </span>
                        <span className="noise-list__sub">
                          {PHASE[r.phase]} · {fmt(r.distance_km, r.distance_km < 10 ? 1 : 0)} km
                        </span>
                      </span>
                      <span className="noise-list__bar" aria-hidden="true">
                        <span style={{ width: `${Math.max(pct(r.db), 3)}%` }} />
                      </span>
                      <span className="noise-list__db">{fmt(r.db)} dB</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      <p className="wx-note">{data?.note || "Hrubý odhad z typu letadla, výšky a vzdálenosti, ne měření."}</p>
    </section>
  );
}

const timeFmt = (ms) => new Date(ms).toLocaleTimeString("cs-CZ", { hour: "numeric", minute: "2-digit" });
const ago = (ms) => {
  const min = Math.max(0, Math.round((Date.now() - ms) / 60000));
  return min < 1 ? "právě teď" : min < 60 ? `před ${min} min` : `před ${Math.floor(min / 60)} h ${min % 60} min`;
};

// Keep numbers with their units on one line ("8 m/s", "93 %").
const nb = (t) => (typeof t === "string" ? t.replace(/(\d) (?=[a-zA-Z%°])/g, "$1\u00a0") : t);

// Current observation at Praha-Ruzyně (/api/metar), refreshed every 10 min.
function Metar() {
  const [tick, setTick] = useState(0);
  useInterval(() => setTick((t) => t + 1), usePollMs("metar"));
  const { data: m, error } = useJson("/api/metar", tick);

  const rows = m && [
    m.wind && [
      "Vítr",
      <>
        {!m.wind.variable && m.wind.speed_ms >= 0.5 && (
          <svg className="wx-wind" viewBox="0 0 24 24" style={{ transform: `rotate(${m.wind.dir_deg + 180}deg)` }} aria-hidden="true">
            <path d="M12 3v18M6 9l6-6 6 6" />
          </svg>
        )}
        {nb(m.wind.text)}
      </>,
    ],
    m.visibility && ["Dohlednost", m.visibility.text],
    ["Oblačnost", m.clouds_text],
    m.temp_c != null && [
      "Teplota",
      [`${fmt(m.temp_c)} °C`, m.dewpoint_c != null && `rosný bod ${fmt(m.dewpoint_c)} °C`, m.humidity != null && `vlhkost ${m.humidity} %`]
        .filter(Boolean)
        .join(", "),
    ],
    m.pressure_hpa && ["Tlak", `${fmt(m.pressure_hpa)} hPa (přepočtený na hladinu moře)`],
  ].filter(Boolean);

  return (
    <section className="wx-card">
      <div className="wx-card__head">
        <h3>Počasí na Ruzyni</h3>
        {m?.observed && <span className="wx-time">{timeFmt(m.observed)}</span>}
      </div>

      {!m && !error && <p className="wx-muted">Načítám počasí z letiště…</p>}
      {!m && error && <p className="form-note form-note--error">{error}</p>}

      {m && (
        <>
          <p className="trail-summary">{m.summary}</p>
          {m.weather.some((w) => !m.summary.toLowerCase().includes(w.toLowerCase())) && (
            <div className="wx-chips">
              {m.weather.filter((w) => !m.summary.toLowerCase().includes(w.toLowerCase())).map((w) => (
                <span key={w} className="wx-chip">{w}</span>
              ))}
            </div>
          )}
          <dl className="wx-rows">
            {rows.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{nb(v)}</dd>
              </div>
            ))}
          </dl>
          <p className="wx-raw">{m.raw}</p>
          <p className="wx-note">
            Pozorování z {timeFmt(m.observed)} ({ago(m.observed)}), {m.name}. Letištní zpráva METAR, aviationweather.gov.
          </p>
        </>
      )}
    </section>
  );
}

const CELL_TEXT = { persistent: "dlouhé stopy", forms: "krátké stopy", none: "bez stop" };
const cellState = (l) => (l.persistent ? "persistent" : l.forms ? "forms" : "none");
const hourOf = (ts) => ts.slice(11, 13).replace(/^0/, "");

function Contrails({ home }) {
  const url = `/api/contrails?lat=${home.lat}&lon=${home.lon}`;
  const { data, error } = useJson(url, null);
  const hours = data?.hours || [];
  // Rows by flight level, highest on top, so the chart reads like the sky.
  const levels = hours[0] ? [...hours[0].levels].sort((a, b) => b.fl - a.fl) : [];

  return (
    <section className="wx-card">
      <div className="wx-card__head">
        <h3>Kondenzační stopy</h3>
        <span className="wx-estimate">Předpověď</span>
      </div>

      {!data && !error && <p className="wx-muted">Načítám předpověď…</p>}
      {!data && error && <p className="form-note form-note--error">{error}</p>}

      {data && (
        <>
          <p className="trail-summary">{data.summary}</p>

          {hours.length > 0 && (
            <div className="trail-chart" style={{ "--cols": hours.length }}>
              {levels.map(({ hpa, fl }) => (
                <div className="trail-chart__row" key={hpa}>
                  <span className="trail-chart__axis">FL{fl}</span>
                  {hours.map((h) => {
                    const l = h.levels.find((x) => x.hpa === hpa);
                    const s = l ? cellState(l) : "none";
                    return (
                      <span
                        key={h.time}
                        className={`trail-cell trail-cell--${s}`}
                        title={`${hourOf(h.time)}:00, FL${fl}: ${CELL_TEXT[s]}${l ? ` (${fmt(l.temp_c)} °C)` : ""}`}
                      />
                    );
                  })}
                </div>
              ))}
              <div className="trail-chart__row trail-chart__row--cloud">
                <span className="trail-chart__axis">mraky</span>
                {hours.map((h) => (
                  <span
                    key={h.time}
                    className="trail-cloud"
                    style={{ "--c": (h.cloud_cover ?? 0) / 100 }}
                    title={`${hourOf(h.time)}:00: oblačnost ${h.cloud_cover ?? "?"} %`}
                  />
                ))}
              </div>
              <div className="trail-chart__row trail-chart__row--hours" aria-hidden="true">
                <span className="trail-chart__axis" />
                {hours.map((h, i) => (
                  <span key={h.time}>{i % 2 === 0 ? hourOf(h.time) : ""}</span>
                ))}
              </div>
            </div>
          )}

          <div className="trail-legend">
            <span><i className="trail-cell trail-cell--persistent" /> dlouhé, vydrží</span>
            <span><i className="trail-cell trail-cell--forms" /> krátké, zmizí</span>
            <span><i className="trail-cell trail-cell--none" /> žádné</span>
          </div>

          <p className="wx-explain">
            Za tryskovými motory vzniká vodní pára, která v mrazu kolem −40 °C a níž zmrzne na ledové krystalky. Když je
            ve výšce sucho, čárka za pár vteřin zmizí. Ve vlhkém vzduchu vydrží desítky minut a může se rozlít do
            závoje řasových mraků. Řádky jsou letové hladiny (FL340 ≈ 10,4 km), sloupce hodiny.
          </p>
          <p className="wx-note">{data.note} Zdroj: {data.source}.</p>
        </>
      )}
    </section>
  );
}

export default function Weather() {
  const { home, setView } = useApp();
  if (!home)
    return (
      <div className="wx">
        <div className="empty">
          <div className="empty__icon">⌂</div>
          <p className="empty__title">Nejdřív nastav domov</p>
          <p>Hluk i kondenzační stopy počítám pro tvoji adresu.</p>
          <button className="btn btn--primary" onClick={() => setView("near")}>Zadat adresu</button>
        </div>
        <Metar />
      </div>
    );

  return (
    <div className="wx">
      <p className="wx-place">⌂ {home.label}</p>
      <Noise home={home} />
      <Metar />
      <Contrails home={home} />
    </div>
  );
}
