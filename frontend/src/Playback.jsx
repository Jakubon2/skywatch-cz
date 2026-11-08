// History playback: map overlay (historical markers + "Přehrávání" badge) and the controls shown in the Stats tab.
import { useEffect, useRef } from "react";
import L from "leaflet";
import { PLANE_SVG, altitudeHue } from "./aircraft.js";
import { useApp, useMapLayer } from "./state.jsx";
import { SPEEDS, TICK_SECONDS, frameAt, playback, usePlayback } from "./playback.js";

const DAYS = ["ne", "po", "út", "st", "čt", "pá", "so"];
export const hhmm = (t) => new Date(t * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
// "14:32", "včera 23:10", "po 08:00"
export function when(t) {
  const d = new Date(t * 1000);
  const days = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (days === 0) return hhmm(t);
  if (days === 1) return `včera ${hhmm(t)}`;
  return `${DAYS[d.getDay()]} ${hhmm(t)}`;
}

const SPEED_LABEL = { 60: "1 min/s", 300: "5 min/s", 900: "15 min/s" };

// Always mounted (tabs.js `overlay`). While playback is active it hides the live layer and draws its own markers.
export function PlaybackOverlay() {
  const pb = usePlayback();
  const { setView, setOpen, select, selectedHex } = useApp();
  const layer = useRef(null); // { group, markers: Map(hex -> { marker, rot }) }

  useMapLayer(
    (map) => {
      if (!pb.active) return;
      // Hiding the live layer: Map.jsx keeps updating its markers, `.map--playback` (Stats.css) just hides them.
      // No change to Map.jsx/state.jsx needed; removing the class brings the live planes straight back.
      const box = map.getContainer();
      box.classList.add("map--playback");
      box.style.setProperty("--pb-glide", `${TICK_SECONDS}s`);
      const group = L.layerGroup().addTo(map);
      layer.current = { group, markers: new globalThis.Map() };
      return () => {
        box.classList.remove("map--playback");
        group.remove();
        layer.current = null;
      };
    },
    [pb.active],
  );

  // Close a live detail when playback starts: its plane isn't on the map any more.
  useEffect(() => {
    if (pb.active && selectedHex) select(null);
  }, [pb.active]); // eslint-disable-line react-hooks/exhaustive-deps

  const frame = pb.active ? frameAt(pb.data, pb.t) : null;

  useEffect(() => {
    const l = layer.current;
    if (!l) return;
    const { fields, aircraft: info } = pb.data || {};
    const idx = Object.fromEntries((fields || []).map((f, i) => [f, i]));
    const seen = new Set();
    for (const row of frame?.ac || []) {
      const hex = row[idx.hex];
      const lat = row[idx.lat];
      const lon = row[idx.lon];
      const alt = row[idx.alt];
      const track = row[idx.track];
      seen.add(hex);
      let entry = l.markers.get(hex);
      if (!entry) {
        const marker = L.marker([lat, lon], {
          icon: L.divIcon({ className: "pb-marker", html: `<div class="ac">${PLANE_SVG}</div>`, iconSize: [32, 32] }),
          keyboard: false,
          interactive: true,
        })
          .bindTooltip("", { direction: "top", offset: [0, -14], className: "ac-tip" })
          .addTo(l.group);
        entry = { marker, rot: track ?? 0 };
        l.markers.set(hex, entry);
      } else {
        entry.marker.setLatLng([lat, lon]);
        if (track != null) entry.rot += ((track - entry.rot + 540) % 360) - 180;
      }
      const node = entry.marker.getElement()?.firstChild;
      if (node) {
        const hue = altitudeHue({ alt_baro: alt });
        node.style.setProperty("--rot", `${entry.rot}deg`);
        node.style.setProperty("--h", hue ?? 0);
        node.classList.toggle("ac--ground", alt === "ground");
      }
      const [flight, type] = info?.[hex] || [];
      entry.marker.setTooltipContent([(flight || "").trim() || hex.toUpperCase(), type].filter(Boolean).join(" · "));
    }
    for (const [hex, entry] of l.markers) {
      if (!seen.has(hex)) {
        entry.marker.remove();
        l.markers.delete(hex);
      }
    }
  }, [frame, pb.data]);

  if (!pb.active) return null;
  return (
    <div className="pb-badge-wrap">
      <div className="pb-badge" role="status">
        <button
          className="pb-badge__time"
          onClick={() => {
            setView("stats");
            setOpen(true);
          }}
          aria-label="Otevřít ovládání přehrávání"
        >
          {pb.playing ? <PlayIcon /> : <PauseIcon />}
          Přehrávání: {when(pb.t)}
        </button>
        <button className="pb-badge__back" onClick={playback.stop}>
          Zpět na živá data
        </button>
      </div>
    </div>
  );
}

// Controls for the Stats tab. `earliest` = first recorded moment (from /api/stats), may be null.
export function PlaybackControls({ earliest }) {
  const pb = usePlayback();
  const frame = pb.active ? frameAt(pb.data, pb.t) : null;

  if (!pb.active) {
    return (
      <section className="card pb-intro">
        <div className="card__head">
          <h3 className="card__title">Přehrát historii</h3>
          <span className="card__hint">posledních 24 h</span>
        </div>
        <p className="card__text">Pusť si na mapě, co se nad Českem dělo. Živá letadla se mezitím schovají.</p>
        <button className="btn btn--primary btn--block" onClick={() => playback.start(earliest)}>
          <PlayIcon /> Spustit přehrávání
        </button>
      </section>
    );
  }

  const pct = pb.max > pb.min ? ((pb.t - pb.min) / (pb.max - pb.min)) * 100 : 100;
  const count = frame?.ac.length ?? 0;
  let status = `${count} ${count === 1 ? "letadlo" : count >= 2 && count <= 4 ? "letadla" : "letadel"}`;
  if (pb.loading) status = "Načítám…";
  else if (pb.data && !frame?.ac.length) status = "Z téhle doby nejsou data";

  return (
    <section className="card player">
      <div className="player__top">
        <div>
          <div className="player__time">{hhmm(pb.t)}</div>
          <div className="player__sub">
            {when(pb.t) !== hhmm(pb.t) ? when(pb.t).split(" ")[0] + " · " : ""}
            {status}
          </div>
        </div>
        <button className="btn btn--ghost btn--small" onClick={playback.stop}>
          Zpět na živá data
        </button>
      </div>

      {pb.error && (
        <p className="form-note form-note--error">
          Historii se nepodařilo načíst.{" "}
          <button className="link-btn" onClick={playback.retry}>
            Zkusit znovu
          </button>
        </p>
      )}

      <input
        className="player__range"
        type="range"
        min={pb.min}
        max={pb.max}
        step={30}
        value={pb.t}
        style={{ "--p": `${pct}%` }}
        onChange={(e) => playback.seek(Number(e.target.value))}
        aria-label="Čas přehrávání"
        aria-valuetext={when(pb.t)}
      />
      <div className="player__ends">
        <span>{when(pb.min)}</span>
        <span>teď</span>
      </div>

      <div className="player__row">
        <button className="player__play" onClick={playback.toggle} aria-label={pb.playing ? "Pozastavit" : "Přehrát"}>
          {pb.playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="seg seg--small player__speed" role="group" aria-label="Rychlost přehrávání">
          {SPEEDS.map((s) => (
            <button key={s} className={pb.speed === s ? "is-active" : ""} aria-pressed={pb.speed === s} onClick={() => playback.setSpeed(s)}>
              {SPEED_LABEL[s]}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

const PlayIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" />
  </svg>
);
const PauseIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" fill="currentColor" />
  </svg>
);
