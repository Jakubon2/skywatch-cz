// Shared app state for all tabs. Features read it with useApp() instead of editing App.jsx or Map.jsx.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { visiblePadding } from "./Map.jsx";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

// All polling intervals in ms: [normal, battery saver]. 0 = load once, no refresh; null = skip the fetch.
export const POLL = {
  aircraft: [10_000, 30_000],
  watchlist: [10_000, 60_000],
  trail: [15_000, null], // map overlay, non-essential
  stats: [60_000, 0],
  predictions: [5 * 60_000, 0],
  metar: [10 * 60_000, 30 * 60_000],
};
export const usePollMs = (key) => POLL[key][useApp().saver ? 1 : 0];

// True while the page is visible (not a background tab or a locked phone).
export function useVisible() {
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const f = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return visible;
}

// setInterval that pauses while the page is hidden and calls `fn` at once when it becomes visible again.
// `ms` falsy = never. Callers do their own first load.
export function useInterval(fn, ms) {
  const cb = useRef(fn);
  cb.current = fn;
  useEffect(() => {
    if (!ms) return;
    let id = null;
    const start = () => {
      clearInterval(id);
      id = document.hidden ? null : setInterval(() => cb.current(), ms);
    };
    const onVisibility = () => {
      if (!document.hidden) cb.current();
      start();
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ms]);
}

// Last good snapshot, so the map is not empty when the app opens without a network.
const SNAPSHOT_KEY = "skywatch.lastSnapshot";
function readSnapshot() {
  try {
    return JSON.parse(localStorage.getItem(SNAPSHOT_KEY)) || null;
  } catch {
    return null;
  }
}

function useAircraft(saver) {
  // `at` = when the shown data was fetched (ms); shown as its age while offline.
  const [state, setState] = useState({ aircraft: [], status: "loading", at: null });
  const load = () =>
    fetch("/api/aircraft")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        const at = Date.now();
        setState({ aircraft: d.aircraft, status: d.now ? "live" : "waiting", at });
        try {
          if (d.now) localStorage.setItem(SNAPSHOT_KEY, JSON.stringify({ aircraft: d.aircraft, at }));
        } catch {
          /* storage full or blocked */
        }
      })
      // Keep the last known planes on screen if the backend drops out; on a cold start use the saved snapshot.
      .catch(() =>
        setState((s) => {
          const snap = !s.aircraft.length && readSnapshot();
          return snap ? { aircraft: snap.aircraft, at: snap.at, status: "offline" } : { ...s, status: "offline" };
        }),
      );
  useEffect(() => {
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(load, POLL.aircraft[saver ? 1 : 0]);
  return state;
}

// Per-device setting in localStorage. Storage can be blocked (private mode): then it lives for this visit only.
export function useStored(key, initial) {
  const [value, setValue] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? initial : JSON.parse(raw);
    } catch {
      return initial;
    }
  });
  const set = (v) => {
    setValue(v);
    try {
      if (v == null) localStorage.removeItem(key);
      else localStorage.setItem(key, JSON.stringify(v));
    } catch {
      /* not persisted */
    }
  };
  return [value, set];
}

// Runs `draw(map)` once the map exists and again when deps change; `draw` returns a cleanup.
// For overlays from feature components: useMapLayer((map) => { const l = L.marker(...).addTo(map); return () => l.remove(); }, [deps]).
export function useMapLayer(draw, deps) {
  const { map } = useApp();
  useEffect(() => (map ? draw(map) : undefined), [map, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function AppProvider({ children }) {
  const [saver, setSaver] = useStored("skywatch.saver", false); // "Úspora baterie"
  const { aircraft, status, at: dataAt } = useAircraft(saver);
  useEffect(() => {
    document.documentElement.classList.toggle("saver", Boolean(saver));
  }, [saver]);
  const [map, setMap] = useState(null);
  const [view, setView] = useState("map");
  const [open, setOpen] = useState(false); // mobile bottom sheet expanded
  const [selectedHex, setSelectedHex] = useState(null);
  const [home, setHome] = useStored("skywatch.home", null); // {label, lat, lon} or null

  // Map filter hook (set by Filters.jsx): a predicate over an aircraft, or null = show all.
  // `dimmed` (Set of hex not matching, or null) dims planes in Map.jsx and feeds the status pill count.
  const [planeFilter, setPlaneFilter] = useState(null);
  const dimmed = useMemo(
    () => (planeFilter ? new Set(aircraft.filter((a) => !planeFilter(a)).map((a) => a.hex)) : null),
    [aircraft, planeFilter],
  );

  // If the selected plane drops out of the data, keep showing its last known state.
  const lastSelected = useRef(null);
  const live = selectedHex ? aircraft.find((a) => a.hex === selectedHex) : null;
  if (live) lastSelected.current = live;
  const selected = selectedHex ? live || lastSelected.current : null;

  const select = (hex) => {
    setSelectedHex(hex);
    setOpen(Boolean(hex));
  };

  // Center a point inside the part of the map the panel leaves visible.
  const flyTo = (lat, lon, zoom = 11) => {
    map?.flyToBounds(L.latLng(lat, lon).toBounds(100), { ...visiblePadding(), maxZoom: zoom, duration: 0.6, animate: !saver });
  };

  const value = {
    aircraft, status, dataAt,
    saver, setSaver,
    selectedHex, selected, selectedLost: Boolean(selected && !live), select,
    view, setView, open, setOpen,
    home, setHome,
    planeFilter, setPlaneFilter, dimmed,
    map, setMap, flyTo,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
