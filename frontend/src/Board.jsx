// "Tabule" tab: LKPR arrivals/departures estimated from live ADS-B (/api/board), split-flap style.
import { useEffect, useState } from "react";
import { useApp, useInterval, useStored } from "./state.jsx";
import "./Board.css";

const POLL_MS = [15_000, 60_000]; // [normal, battery saver]
const STATUS = {
  "přistává": "landing",
  "na zemi": "ground",
  "odlétá": "taxi",
  "vzlétl": "airborne",
};

const hhmm = (ms) => new Date(ms).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Prague" });

function useBoard() {
  const { saver } = useApp();
  const [state, setState] = useState({ data: null, error: false });
  const load = () =>
    fetch("/api/board")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((data) => setState({ data, error: false }))
      .catch(() => setState((s) => ({ ...s, error: true })));
  useEffect(() => {
    load();
  }, []);
  useInterval(load, POLL_MS[saver ? 1 : 0]);
  return state;
}

// One flap per character. The key includes the character, so a change remounts the cell and replays the flip.
function Flaps({ text, width, label }) {
  const chars = text.padEnd(width, " ").slice(0, width).split("");
  return (
    <span className="flaps" role="text" aria-label={label ?? text.trim()}>
      {chars.map((c, i) => (
        <span key={`${i}${c}`} className="flap" style={{ "--i": i }} aria-hidden="true">
          {c === " " ? " " : c}
        </span>
      ))}
    </span>
  );
}

// Time column + the line under it.
function when(row, now) {
  if (row.status === "přistává" && row.eta_min != null)
    return { time: hhmm(row.time_ms), sub: row.eta_min < 1 ? "teď" : `za ${row.eta_min} min`, label: `odhad příletu ${hhmm(row.time_ms)}` };
  if (row.time_ms && row.status === "vzlétl") {
    const ago = Math.max(0, Math.round((now - row.time_ms) / 60000));
    return { time: hhmm(row.time_ms), sub: `${row.estimated ? "≈ " : ""}před ${ago} min`, label: `vzlétl ${row.estimated ? "přibližně " : ""}v ${hhmm(row.time_ms)}` };
  }
  if (row.time_ms && row.status === "na zemi") return { time: hhmm(row.time_ms), sub: "přistál", label: `přistál v ${hhmm(row.time_ms)}` };
  return { time: "--:--", sub: row.status === "odlétá" ? "pojíždí" : "stojí", label: "bez času" };
}

function Row({ row, now, kind, onPick }) {
  const w = when(row, now);
  const flight = row.callsign || row.reg || row.hex.toUpperCase();
  const place = row.place?.city || row.place?.code;
  return (
    <li>
      <button className="board__row" onClick={() => onPick(row)}>
        <span className="board__time">
          <Flaps text={w.time} width={5} label={w.label} />
          <small>{w.sub}</small>
        </span>
        <span className="board__main">
          <Flaps text={flight} width={7} label={`let ${flight}`} />
          <small>
            {place ? (
              <>
                <span className="board__place">{place}</span>
                {row.place?.code && place !== row.place.code && <span className="board__code">{row.place.code}</span>}
              </>
            ) : (
              <span className="board__unknown">{kind === "arr" ? "odkud neznámo" : "kam neznámo"}</span>
            )}
            {row.type && <span className="board__type">{row.type}</span>}
          </small>
        </span>
        <span className={`board__status board__status--${STATUS[row.status]}`}>{row.status}</span>
      </button>
    </li>
  );
}

export default function Board() {
  const { aircraft, select, flyTo } = useApp();
  const { data, error } = useBoard();
  const [kind, setKind] = useStored("skywatch.board.kind", "arr");
  const [now, setNow] = useState(Date.now());
  useInterval(() => setNow(Date.now()), 30_000);

  const pick = (row) => {
    const a = aircraft.find((x) => x.hex === row.hex);
    select(row.hex);
    if (a) flyTo(a.lat, a.lon, row.alt_ft == null ? 14 : 10);
  };

  if (!data) {
    return <div className="empty"><p>{error ? "Tabuli se nepodařilo načíst." : "Načítám tabuli…"}</p></div>;
  }
  const rows = kind === "arr" ? data.arrivals : data.departures;

  return (
    <div className="board">
      <div className="board__head">
        <div>
          <h2>Letiště Praha</h2>
          <p>Václava Havla · LKPR · PRG</p>
        </div>
        <time className="board__clock">{data.now ? hhmm(data.now) : "--:--"}</time>
      </div>

      <div className="seg seg--small" role="tablist" aria-label="Přílety nebo odlety">
        {[
          ["arr", "Přílety", data.arrivals.length],
          ["dep", "Odlety", data.departures.length],
        ].map(([id, label, n]) => (
          <button key={id} role="tab" aria-selected={kind === id} className={kind === id ? "is-active" : ""} onClick={() => setKind(id)}>
            {label} <span className="board__count">{n}</span>
          </button>
        ))}
      </div>

      <div className="board__panel">
        <div className="board__cols" aria-hidden="true">
          <span>{kind === "arr" ? "Přílet" : "Čas"}</span>
          <span>Let · {kind === "arr" ? "odkud" : "kam"} · typ</span>
          <span>Stav</span>
        </div>
        {rows.length ? (
          <ul className="board__list">
            {rows.map((r) => (
              <Row key={r.hex} row={r} now={now} kind={kind} onPick={pick} />
            ))}
          </ul>
        ) : (
          <p className="board__empty">
            {kind === "arr" ? "Teď k Praze nic nepřilétá." : "Teď z Prahy nic neodlétá."}
          </p>
        )}
      </div>

      <p className="board__note">
        Odhad z dat ADS-B (adsb.lol), <strong>ne oficiální letový řád</strong>. Časy příletu počítáme ze vzdálenosti a rychlosti,
        trasy z veřejných databází, takže se mohou lišit. Klepnutím na řádek letadlo ukážeš na mapě.
        {error && <span className="board__stale"> Poslední aktualizace selhala, zobrazuji starší data.</span>}
      </p>
    </div>
  );
}
