// Shared app state for all tabs. Features read it with useApp() instead of editing App.jsx or Map.jsx.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import L from "leaflet";
import { visiblePadding } from "./Map.jsx";

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

function useAircraft() {
  const [state, setState] = useState({ aircraft: [], status: "loading" });
  useEffect(() => {
    const load = () =>
      fetch("/api/aircraft")
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => setState({ aircraft: d.aircraft, status: d.now ? "live" : "waiting" }))
        // Keep the last known planes on screen if the backend drops out.
        .catch(() => setState((s) => ({ ...s, status: "offline" })));
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);
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
  const { aircraft, status } = useAircraft();
  const [map, setMap] = useState(null);
  const [view, setView] = useState("map");
  const [open, setOpen] = useState(false); // mobile bottom sheet expanded
  const [selectedHex, setSelectedHex] = useState(null);
  const [home, setHome] = useStored("skywatch.home", null); // {label, lat, lon} or null

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
    map?.flyToBounds(L.latLng(lat, lon).toBounds(100), { ...visiblePadding(), maxZoom: zoom, duration: 0.6 });
  };

  const value = {
    aircraft, status,
    selectedHex, selected, selectedLost: Boolean(selected && !live), select,
    view, setView, open, setOpen,
    home, setHome,
    map, setMap, flyTo,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
