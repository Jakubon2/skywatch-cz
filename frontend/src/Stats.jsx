// "Statistiky" tab: traffic stats, AI summaries, flight predictions for home, history playback controls.
import { useEffect, useId, useRef, useState } from "react";
import { useApp, useInterval, usePollMs, useStored } from "./state.jsx";
import { PlaybackControls, hhmm, when } from "./Playback.jsx";
import { usePlayback } from "./playback.js";
import "./Stats.css";

const PERIODS = [
  { hours: 6, label: "6 h" },
  { hours: 24, label: "24 h" },
  { hours: 168, label: "7 dní" },
];

const EVENT_LABELS = {
  interesting: "Zajímavé letadlo",
  holding: "Vyčkávání v okruhu",
  emergency: "Nouzový squawk",
  go_around: "Nepovedené přiblížení",
  heli_orbit: "Kroužící vrtulník",
  rapid_descent: "Rychlý sestup",
  return_or_diversion: "Návrat nebo odklon",
};

const fmt = (n) => n.toLocaleString("cs-CZ");
// Czech plural: 1 letadlo, 2–4 letadla, 5+ letadel
const plural = (n, one, few, many) => (n === 1 ? one : n >= 2 && n <= 4 ? few : many);

// Plain fetch with a status, for endpoints that may not exist yet.
function useJson(url, deps, { refreshMs } = {}) {
  const [state, setState] = useState({ status: url ? "loading" : "idle", data: null });
  const reload = useRef(null);
  useInterval(() => reload.current?.(), refreshMs);
  useEffect(() => {
    if (!url) return setState({ status: "idle", data: null });
    let alive = true;
    const load = () =>
      fetch(url)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((data) => alive && setState({ status: "done", data }))
        .catch((code) => alive && setState((s) => ({ status: code === 404 ? "missing" : "error", data: s.data })));
    setState((s) => ({ status: "loading", data: s.data }));
    load();
    reload.current = load;
    return () => {
      alive = false;
      reload.current = null;
    };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

// ---------- Traffic chart (inline SVG, no library) ----------

const W = 1000; // viewBox width; the SVG stretches to the container, strokes stay crisp (non-scaling-stroke)
const H = 100;

function niceMax(v) {
  if (v <= 0) return 10;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * p).find((m) => m >= v * 1.08);
}

function xTicks(t0, t1) {
  const span = t1 - t0;
  const hour = 3600;
  if (span > 36 * hour) {
    // one tick per midnight
    const out = [];
    const d = new Date(t0 * 1000);
    d.setHours(24, 0, 0, 0);
    for (let t = d / 1000; t < t1; t += 24 * hour) out.push({ t, label: new Date(t * 1000).toLocaleDateString("cs-CZ", { weekday: "short" }) });
    return out.length > 7 ? out.filter((_, i) => i % 2 === 0) : out;
  }
  const step = [0.5, 1, 2, 3, 4, 6, 12].map((h) => h * hour).find((s) => span / s <= 4.5) || 12 * hour;
  const out = [];
  const tz = new Date(t0 * 1000).getTimezoneOffset() * 60; // align ticks to local clock
  for (let t = Math.ceil((t0 - tz) / step) * step + tz; t < t1; t += step) out.push({ t, label: hhmm(t) });
  return out;
}

function TrafficChart({ traffic, bucket, to }) {
  const gid = useId().replace(/:/g, "");
  const box = useRef(null);
  const [hover, setHover] = useState(null);
  if (!traffic.length) return <div className="chart chart--empty">Zatím žádná data</div>;

  const t0 = traffic[0].t;
  const t1 = Math.max(to, traffic[traffic.length - 1].t + bucket);
  const peak = Math.max(...traffic.map((p) => p.aircraft));
  const yMax = niceMax(peak);
  const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const y = (v) => H - (v / yMax) * H;

  // Split into continuous runs: gaps (backend off) stay visibly empty instead of being bridged.
  const runs = [];
  for (const p of traffic) {
    const run = runs[runs.length - 1];
    if (run && p.t - run[run.length - 1].t <= bucket * 1.5) run.push(p);
    else runs.push([p]);
  }
  const pts = (run) => {
    const r = run.length === 1 ? [run[0], { ...run[0], t: run[0].t + bucket }] : run;
    return r.map((p) => [x(p.t + (run.length === 1 ? 0 : bucket / 2)), y(p.aircraft)]);
  };
  const line = (run) => pts(run).map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join("");
  const area = (run) => {
    const p = pts(run);
    return `${line(run)}L${p[p.length - 1][0].toFixed(1)},${H}L${p[0][0].toFixed(1)},${H}Z`;
  };

  const onMove = (e) => {
    const r = box.current.getBoundingClientRect();
    const t = t0 + ((e.clientX - r.left) / r.width) * (t1 - t0);
    let best = traffic[0];
    for (const p of traffic) if (Math.abs(p.t + bucket / 2 - t) < Math.abs(best.t + bucket / 2 - t)) best = p;
    setHover(best);
  };

  const hx = hover && (x(hover.t + bucket / 2) / W) * 100;
  return (
    <div className="chart">
      <div className="chart__plot" ref={box} onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" style={{ stopColor: "var(--accent)", stopOpacity: 0.32 }} />
              <stop offset="1" style={{ stopColor: "var(--accent)", stopOpacity: 0.02 }} />
            </linearGradient>
          </defs>
          {[0, 0.5, 1].map((f) => (
            <line key={f} className="chart__grid" x1="0" x2={W} y1={H * f} y2={H * f} vectorEffect="non-scaling-stroke" />
          ))}
          {runs.map((run, i) => (
            <g key={i}>
              <path d={area(run)} fill={`url(#${gid})`} />
              <path d={line(run)} className="chart__line" vectorEffect="non-scaling-stroke" />
            </g>
          ))}
        </svg>
        <span className="chart__y" style={{ top: 0 }}>{fmt(yMax)}</span>
        <span className="chart__y" style={{ top: "50%" }}>{fmt(yMax / 2)}</span>
        {hover && (
          <>
            <span className="chart__cursor" style={{ left: `${hx}%` }} />
            <span className="chart__dot" style={{ left: `${hx}%`, top: `${(y(hover.aircraft) / H) * 100}%` }} />
            <span className={`chart__tip ${hx > 60 ? "chart__tip--left" : ""}`} style={{ left: `${hx}%` }}>
              <b>{fmt(hover.aircraft)}</b> {plural(hover.aircraft, "letadlo", "letadla", "letadel")} · {when(hover.t)}
            </span>
          </>
        )}
      </div>
      <div className="chart__x">
        {xTicks(t0, t1).map((tk) => (
          <span key={tk.t} style={{ left: `${(x(tk.t) / W) * 100}%` }}>
            {tk.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------- Lists ----------

function BarList({ items, unit }) {
  if (!items.length) return <p className="card__text card__text--muted">Zatím nic.</p>;
  const max = Math.max(...items.map((i) => i.value));
  return (
    <ol className="bars">
      {items.map((i) => (
        <li key={i.key} className="bars__item">
          <div className="bars__label">
            <span className="bars__name">{i.label}</span>
            {i.sub && <span className="bars__sub">{i.sub}</span>}
            <span className="bars__value">{fmt(i.value)}</span>
          </div>
          <div className="bars__track" aria-hidden="true">
            <span className="bars__fill" style={{ width: `${Math.max(3, (i.value / max) * 100)}%` }} />
          </div>
        </li>
      ))}
      <li className="bars__unit">{unit}</li>
    </ol>
  );
}

function Card({ title, hint, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      <div className="card__head">
        <h3 className="card__title">{title}</h3>
        {hint && <span className="card__hint">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function StatsBlock({ hours }) {
  const { status, data } = useJson(`/api/stats?hours=${hours}`, [hours], { refreshMs: usePollMs("stats") });
  if (!data) {
    if (status === "loading") return <div className="card card--skeleton" aria-busy="true" />;
    return (
      <Card title="Provoz">
        <p className="card__text card__text--muted">
          {status === "missing" ? "Statistiky backend zatím neumí." : "Statistiky se nepodařilo načíst. Běží backend?"}
        </p>
      </Card>
    );
  }

  const complete = data.traffic.filter((p, i, all) => p.t + data.bucket_s <= data.to || all.length === 1);
  const peak = data.traffic.reduce((m, p) => (p.aircraft > (m?.aircraft ?? -1) ? p : m), null);
  const events = Object.entries(data.events || {}).sort((a, b) => b[1] - a[1]);
  const eventTotal = events.reduce((s, [, n]) => s + n, 0);
  const first = data.traffic[0]?.t;
  const coveredH = first ? (data.to - first) / 3600 : 0;
  const partial = first && first > data.from + data.bucket_s * 3;

  return (
    <>
      <Card title="Provoz v čase" hint={`letadel za ${Math.round(data.bucket_s / 60)} min`}>
        {/* The current bucket is still filling up, so it would show a fake drop: leave it out. */}
        <TrafficChart traffic={complete} bucket={data.bucket_s} to={data.to} />
        {partial && (
          <p className="card__note">
            Data sbírám teprve od {when(first)}, takže statistika pokrývá jen{" "}
            {coveredH < 1 ? "pár minut" : `${Math.round(coveredH)} ${plural(Math.round(coveredH), "hodinu", "hodiny", "hodin")}`}.
          </p>
        )}
      </Card>

      <div className="stats stats--3">
        <div className="stat">
          <span className="stat__label">Letadel</span>
          <span className="stat__value">{fmt(data.unique_aircraft)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Špička</span>
          <span className="stat__value">{peak ? fmt(peak.aircraft) : "–"}</span>
          {peak && <span className="stat__sub">{when(peak.t)}</span>}
        </div>
        <div className="stat">
          <span className="stat__label">Událostí</span>
          <span className="stat__value">{fmt(eventTotal)}</span>
        </div>
      </div>

      <div className="stats-grid">
        <Card title="Nejčastější aerolinky">
          <BarList
            unit="počet letů"
            items={data.top_airlines.map((a) => ({ key: a.code, label: a.name || a.code, sub: a.name ? a.code : null, value: a.flights }))}
          />
        </Card>
        <Card title="Nejčastější typy">
          <BarList unit="počet letadel" items={data.top_types.map((t) => ({ key: t.type, label: t.type, value: t.aircraft }))} />
        </Card>
      </div>

      <div className="stats-grid">
        <Card title="Nejvzácnější typy" hint="nejméně letadel">
          {data.rarest_types.length ? (
            <ul className="rare">
              {data.rarest_types.map((t) => (
                <li key={t.type}>
                  <span className="rare__type">{t.type}</span>
                  <span className="rare__sub">
                    {t.aircraft}× · poprvé {when(t.first_seen)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card__text card__text--muted">Zatím nic.</p>
          )}
        </Card>
        <Card title="Události">
          {events.length ? (
            <ul className="events-list">
              {events.map(([type, n]) => (
                <li key={type}>
                  <span>{EVENT_LABELS[type] || type}</span>
                  <b>{fmt(n)}</b>
                </li>
              ))}
            </ul>
          ) : (
            <p className="card__text card__text--muted">Za tohle období nic zvláštního.</p>
          )}
        </Card>
      </div>
    </>
  );
}

// ---------- AI summaries (on demand: each one may cost a Claude call) ----------

function Summary({ title, url, cta }) {
  const [s, setS] = useState({ status: "idle" });
  const load = () => {
    setS({ status: "busy" });
    fetch(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => setS({ status: "done", data }))
      .catch((code) => setS({ status: code === 404 ? "missing" : "error" }));
  };
  const gen = s.data?.generated_at ? new Date(s.data.generated_at).getTime() / 1000 : null;

  return (
    <div className="summary">
      <div className="summary__head">
        <span className="summary__title">{title}</span>
        {s.status === "done" && s.data.text && <span className="ai-tag">shrnutí od AI, neověřeno</span>}
      </div>
      {s.status === "idle" && (
        <button className="btn btn--ghost btn--block" onClick={load}>
          <SparkIcon /> {cta}
        </button>
      )}
      {s.status === "busy" && <p className="summary__text summary__text--muted">Píšu shrnutí…</p>}
      {s.status === "missing" && <p className="summary__text summary__text--muted">Tohle shrnutí backend zatím neumí.</p>}
      {s.status === "error" && (
        <p className="summary__text summary__text--muted">
          Shrnutí se nepodařilo načíst.{" "}
          <button className="link-btn" onClick={load}>
            Zkusit znovu
          </button>
        </p>
      )}
      {s.status === "done" &&
        (s.data.text ? (
          <>
            <p className="summary__text">{s.data.text}</p>
            {gen && <p className="summary__meta">Vytvořeno {when(gen)}</p>}
          </>
        ) : (
          <p className="summary__text summary__text--muted">Shrnutí teď není k dispozici (denní limit AI nebo chyba). Zkus to později.</p>
        ))}
    </div>
  );
}

// ---------- Predictions for home ----------

function Predictions() {
  const { home, setView } = useApp();
  const [radius] = useStored("skywatch.radiusKm", 15);
  const url = home ? `/api/predictions?lat=${home.lat.toFixed(4)}&lon=${home.lon.toFixed(4)}&radius_km=${radius}&hours=3` : null;
  const { status, data } = useJson(url, [url], { refreshMs: usePollMs("predictions") });

  return (
    <Card title="Kdy tu poletí" hint={home ? "příští 3 h" : null}>
      {!home && (
        <div className="card__text">
          <p className="card__text card__text--muted">Nastav si domov a ukážu, které pravidelné lety obvykle letí kolem.</p>
          <button className="btn btn--ghost btn--small" onClick={() => setView("near")}>
            Nastavit polohu
          </button>
        </div>
      )}
      {home && !data && status === "loading" && <p className="card__text card__text--muted">Počítám…</p>}
      {home && !data && (status === "error" || status === "missing") && (
        <p className="card__text card__text--muted">
          {status === "missing" ? "Předpovědi backend zatím neumí." : "Předpověď se nepodařilo načíst."}
        </p>
      )}
      {home && data && (
        <>
          {data.predictions.length === 0 ? (
            <p className="card__text card__text--muted">
              {data.reason || "V příštích 3 hodinách tu žádný pravidelný let nečekám."}
            </p>
          ) : (
            <ul className="pred">
              {data.predictions.map((p) => (
                <li key={`${p.callsign}-${p.usual_time}`} className="pred__row">
                  <span className="pred__time">
                    <b>{p.usual_time}</b>
                    <small>
                      {p.window.from}–{p.window.to}
                    </small>
                  </span>
                  <span className="pred__main">
                    <span className="pred__title">
                      {p.callsign} {p.type && <span className="pred__type">{p.type}</span>}
                    </span>
                    <span className="pred__sub">
                      viděno {p.days_seen} z {p.days_observed} dní
                    </span>
                  </span>
                  <span className="pred__side">
                    <span className="pred__in">{p.expected_in_min <= 0 ? "teď" : `za ${fmt(p.expected_in_min)} min`}</span>
                    <span className={`pred__conf pred__conf--${p.confidence >= 0.75 ? "hi" : p.confidence >= 0.5 ? "mid" : "lo"}`}>
                      {p.confidence_label}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {(data.predictions.length > 0 || !data.reason) && <p className="card__note">
            V okolí místa {home.label} (přesnost asi {data.cell_km} km), podle {data.history_days}{" "}
            {plural(data.history_days, "dne", "dní", "dní")} sběru. Je to odhad z minulých dní, ne letový řád.
          </p>}
        </>
      )}
      {home && <PassAlerts home={home} radius={radius} />}
    </Card>
  );
}

// Opt-in heads-up before a predicted pass. The server needs the home location for that, so we send it only here.
function PassAlerts({ home, radius }) {
  const [deviceId, setDeviceId] = useStored("skywatch.deviceId", null);
  const [s, setS] = useState({ status: "loading", lead: 20 }); // loading | on | off | busy | error | missing
  const id = deviceId || "pending";

  useEffect(() => {
    if (!deviceId) setDeviceId(crypto.randomUUID());
  }, [deviceId]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = (r) =>
    r.ok ? r.json().then((d) => setS({ status: d.enabled ? "on" : "off", lead: d.lead_minutes ?? s.lead })) : Promise.reject(r.status);
  const fail = (code) => setS((p) => ({ ...p, status: code === 404 || code === 405 ? "missing" : "error" }));
  const put = () =>
    fetch("/api/pass-alerts", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: id, label: home.label, lat: home.lat, lon: home.lon, radius_km: radius }),
    }).then(apply);

  useEffect(() => {
    if (!deviceId) return;
    fetch(`/api/pass-alerts/${deviceId}`).then(apply).catch(fail);
  }, [deviceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the server copy in sync when the user moves home or changes the radius.
  useEffect(() => {
    if (s.status === "on") put().catch(fail);
  }, [home.lat, home.lon, radius]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (on) => {
    setS((p) => ({ ...p, status: "busy" }));
    (on ? put() : fetch(`/api/pass-alerts/${id}`, { method: "DELETE" }).then(apply)).catch(fail);
  };

  if (s.status === "missing") return null; // backend without this feature
  const on = s.status === "on";
  return (
    <div className="pass-alerts">
      <div className="pass-alerts__row">
        <span className="pass-alerts__text">
          <b>Upozornit předem</b>
          <small>Asi {s.lead} min před pravidelným letem v okolí</small>
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Upozornit předem na pravidelný let"
          className="switch"
          disabled={!deviceId || s.status === "loading" || s.status === "busy"}
          onClick={() => toggle(!on)}
        >
          <span className="switch__knob" />
        </button>
      </div>
      <p className="card__note">
        {on ? "Zapnuto. " : ""}Adresa se uloží na server kvůli upozornění (vypnutím se smaže). Upozornění přijde
        přes push nebo ntfy, podle Nastavení.
      </p>
      {s.status === "error" && <p className="form-note form-note--error">Nastavení se nepodařilo uložit. Zkus to znovu.</p>}
    </div>
  );
}

// ---------- Tab ----------

export default function Stats() {
  const [hours, setHours] = useStored("skywatch.statsHours", 24);
  const pb = usePlayback();
  // Earliest recorded data, so playback doesn't start in an empty past. Cheap: /api/stats is cached for 60 s.
  const { data: day } = useJson("/api/stats?hours=24", []);
  const earliest = day?.traffic?.[0]?.t ?? null;

  return (
    <div className={`stats-tab ${pb.active ? "stats-tab--playing" : ""}`}>
      <PlaybackControls earliest={earliest} />

      <div className="stats-tab__rest">
        <div className="stats-tab__head">
          <h2 className="section-title">Statistiky</h2>
          <div className="seg seg--small" role="group" aria-label="Období">
            {PERIODS.map((p) => (
              <button key={p.hours} className={hours === p.hours ? "is-active" : ""} aria-pressed={hours === p.hours} onClick={() => setHours(p.hours)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <StatsBlock hours={hours} />

        <Predictions />

        <Card title="Shrnutí" hint="na vyžádání">
          <Summary title="Dnešek" url="/api/summary/today" cta="Shrnout dnešek" />
          <Summary title="Posledních 7 dní" url="/api/summary/week" cta="Shrnout týden" />
          <p className="card__note">Shrnutí píše AI z nasbíraných dat a může se mýlit. Každé vytvoření stojí jedno volání AI, proto až na kliknutí.</p>
        </Card>
      </div>
    </div>
  );
}

const SparkIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
    <path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.9L12 18.5l-1.8-5.8-5.7-1.9L10.2 9z" />
  </svg>
);
