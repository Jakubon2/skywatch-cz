// Optional map overlays (precipitation radar, airspace zones) and the floating switcher that toggles them.
// Data comes from /api/radar and /api/airspace (backend/airspace.py). Choice is remembered per device.
import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { useApp, useMapLayer, useStored } from "./state.jsx";
import "./MapLayers.css";

const LAYERS_ICON = "M12 3.5 2.5 8.5l9.5 5 9.5-5zM2.5 12.5l9.5 5 9.5-5M2.5 16.5l9.5 5 9.5-5";
const RADAR_REFRESH_MS = 5 * 60_000;

// Zone colours by airspace kind; dashed = only active when reserved (TRA/TSA) or a mandatory zone.
const ZONE_STYLE = {
  CTR: { color: "#2563eb" }, MCTR: { color: "#2563eb" }, ATZ: { color: "#0891b2", weight: 1 },
  TMA: { color: "#7c3aed" }, CTA: { color: "#7c3aed" },
  P: { color: "#dc2626", fillOpacity: 0.16 }, R: { color: "#ea580c", fillOpacity: 0.12 }, D: { color: "#d97706", fillOpacity: 0.1 },
  TRA: { color: "#16a34a", dashArray: "6 4" }, TSA: { color: "#16a34a", dashArray: "6 4" },
  RMZ: { color: "#64748b", dashArray: "2 4" }, TMZ: { color: "#64748b", dashArray: "2 4" },
};
const LEGEND = [
  ["#2563eb", "CTR / ATZ – okolí letišť"],
  ["#7c3aed", "TMA – koncové oblasti"],
  ["#dc2626", "P / R – zakázané a omezené"],
  ["#d97706", "D – nebezpečné"],
  ["#16a34a", "TRA / TSA – vojenské, dočasné"],
];

const fmtTime = (s) => new Date(s * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// Ray casting on [lon, lat] rings; inside the outer ring and in no hole.
function inRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function contains(geom, lon, lat) {
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  return polys.some(([outer, ...holes]) => inRing(lon, lat, outer) && !holes.some((h) => inRing(lon, lat, h)));
}

function zonesPopup(zones) {
  const rows = zones
    .map(({ properties: p }) => {
      const color = (ZONE_STYLE[p.kind] || ZONE_STYLE.RMZ).color;
      const cls = p.icao_class ? `, třída ${p.icao_class}` : "";
      const notam = p.by_notam ? '<div class="zone-pop__note">Aktivuje se NOTAMem</div>' : "";
      return `<li style="--zc:${color}"><b>${esc(p.name)}</b><span class="zone-pop__kind">${esc(p.kind_name)} (${esc(p.kind)})${cls}</span>
        <span class="zone-pop__lim">${esc(p.lower)} – ${esc(p.upper)}</span>${notam}</li>`;
    })
    .join("");
  return `<ul class="zone-pop">${rows}</ul><p class="zone-pop__src">Orientační údaje z openAIP, ne pro navigaci.</p>`;
}

function useFetched(url, enabled, refreshMs) {
  const [state, setState] = useState({ data: null, error: false });
  useEffect(() => {
    if (!enabled) return undefined;
    const load = () =>
      fetch(url)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data) => setState({ data, error: false }))
        .catch(() => setState((s) => ({ ...s, error: true })));
    if (!state.data || refreshMs) load();
    const id = refreshMs ? setInterval(load, refreshMs) : null;
    return () => clearInterval(id);
  }, [url, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function RadarLayer({ radar }) {
  useMapLayer(
    (map) => {
      if (!radar) return undefined;
      const layer = L.tileLayer(radar.url, {
        opacity: radar.opacity,
        maxNativeZoom: radar.max_native_zoom,
        maxZoom: 18,
        zIndex: 5,
        className: "radar-layer",
        attribution: `Radar: ${radar.attribution}`,
      }).addTo(map);
      return () => layer.remove();
    },
    [radar?.url],
  );
  return null;
}

function AirspaceLayer({ data }) {
  const { selectedHex } = useApp();
  const selRef = useRef(selectedHex);
  selRef.current = selectedHex;

  useMapLayer(
    (map) => {
      if (!data) return undefined;
      // Drawn largest-first so small zones (CTR, P) stay on top; polygons aren't clickable themselves,
      // a map tap lists every zone under the finger instead (they overlap a lot).
      const features = [...data.features].reverse();
      const layer = L.geoJSON(features, {
        interactive: false,
        attribution: data.attribution,
        style: (f) => ({ weight: 1.5, opacity: 0.85, fillOpacity: 0.05, ...(ZONE_STYLE[f.properties.kind] || ZONE_STYLE.RMZ) }),
      }).addTo(map);
      const onClick = (e) => {
        if (selRef.current) return; // that tap just closes the aircraft detail
        const { lat, lng } = e.latlng;
        const hits = data.features.filter((f) => contains(f.geometry, lng, lat));
        if (!hits.length) return;
        L.popup({ className: "zone-popup", maxWidth: 280, maxHeight: 260, autoPanPadding: [16, 80] })
          .setLatLng(e.latlng)
          .setContent(zonesPopup(hits))
          .openOn(map);
      };
      map.on("click", onClick);
      return () => {
        map.off("click", onClick);
        map.closePopup();
        layer.remove();
      };
    },
    [data],
  );
  return null;
}

export default function MapLayers() {
  const [on, setOn] = useStored("skywatch.layers", { radar: false, airspace: false, labels: true });
  const labelsOn = on.labels !== false; // older stored settings have no `labels` key
  // Plane labels are drawn by Map.jsx from zoom 9 up; this switch hides them via a class on the map.
  useMapLayer((map) => {
    map.getContainer().classList.toggle("labels-off", !labelsOn);
  }, [labelsOn]);
  const [open, setOpen] = useState(false);
  const radar = useFetched("/api/radar", on.radar, RADAR_REFRESH_MS);
  const airspace = useFetched("/api/airspace", on.airspace, 0);
  const active = (on.radar ? 1 : 0) + (on.airspace ? 1 : 0);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const toggle = (key) => (e) => setOn({ ...on, [key]: e.target.checked });

  return (
    <div className="layers">
      {on.radar && <RadarLayer radar={radar.data} />}
      {on.airspace && <AirspaceLayer data={airspace.data} />}

      <button
        className={`layers__btn ${active ? "is-active" : ""}`}
        aria-expanded={open}
        aria-label="Vrstvy mapy"
        title="Vrstvy mapy"
        onClick={() => setOpen(!open)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={LAYERS_ICON} />
        </svg>
      </button>

      {open && (
        <>
          <div className="layers__backdrop" onClick={() => setOpen(false)} />
          <div className="layers__card" role="dialog" aria-label="Vrstvy mapy">
            <h3>Vrstvy mapy</h3>

            <label className="layers__row">
              <span>
                Popisky u letadel
                <small>Volačka, typ, výška a rychlost při přiblížení</small>
              </span>
              <input type="checkbox" className="fl-switch" checked={labelsOn} onChange={(e) => setOn({ ...on, labels: e.target.checked })} />
            </label>

            <label className="layers__row">
              <span>
                Srážkový radar
                <small>
                  {!on.radar ? "RainViewer" : radar.error && !radar.data ? "Radar se nepodařilo načíst" : radar.data ? `RainViewer · snímek ${fmtTime(radar.data.time)}` : "Načítám…"}
                </small>
              </span>
              <input type="checkbox" className="fl-switch" checked={on.radar} onChange={toggle("radar")} />
            </label>

            <label className="layers__row">
              <span>
                Vzdušné prostory
                <small>
                  {!on.airspace
                    ? "CTR, TMA, zakázané a vojenské zóny"
                    : airspace.error && !airspace.data
                      ? "Zóny se nepodařilo načíst"
                      : airspace.data
                        ? `${airspace.data.features.length} zón · klepněte do mapy`
                        : "Načítám…"}
                </small>
              </span>
              <input type="checkbox" className="fl-switch" checked={on.airspace} onChange={toggle("airspace")} />
            </label>

            {on.airspace && (
              <ul className="layers__legend">
                {LEGEND.map(([color, label]) => (
                  <li key={label} style={{ "--zc": color }}>
                    {label}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}
