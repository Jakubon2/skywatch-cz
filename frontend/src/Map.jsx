import { useEffect, useRef } from "react";
import L from "leaflet";
import { MutedTileLayer } from "./tiles.js";
import { callsign } from "./aircraft.js";
import { PlaneLayer } from "./planes.js";

const CZ_BOUNDS = [[48.55, 12.09], [51.06, 18.86]];

// OSM tiles need no key; tiles.js mutes them (and inverts them in dark mode).
// Swap in a keyed provider (MapTiler, Stadia, ...) via VITE_TILE_URL if needed.
const TILE_URL = import.meta.env.VITE_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  import.meta.env.VITE_TILE_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export const isDesktop = () => window.matchMedia("(min-width: 960px)").matches;

// Pixels hidden by the overlay UI, so we can keep things out from under it.
const overlayPadding = () =>
  isDesktop()
    ? { paddingTopLeft: [412, 40], paddingBottomRight: [40, 40] }
    : { paddingTopLeft: [12, 70], paddingBottomRight: [12, Math.round(window.innerHeight * 0.5)] };

// Padding that keeps a fitted area inside the map strip left visible by the open panel.
// For features: map.flyToBounds(bounds, { ...visiblePadding() }).
export function visiblePadding() {
  const sheet = document.querySelector(".panel");
  if (isDesktop() || !sheet) return overlayPadding();
  return { paddingTopLeft: [12, 70], paddingBottomRight: [12, sheet.offsetHeight + 12] };
}

// Plain Leaflet in refs; no wrapper library. Aircraft are drawn on one canvas (planes.js).
// Feature overlays get the Leaflet instance through onReady (see state.jsx), so they never need to edit this file.
// From this zoom up, planes carry a small data label (selected plane always does); planes.js declutters them.
const LABEL_ZOOM = 7;
const GROUND_LABEL_ZOOM = 13; // planes and vehicles on the ground crowd the apron, so label them later

export default function Map({ aircraft, selectedHex, onSelect, onReady, dimmed }) {
  const el = useRef(null);
  const mapRef = useRef(null);
  const planes = useRef(null); // PlaneLayer: all aircraft on one canvas
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const map = L.map(el.current, { zoomControl: false, attributionControl: false });
    const { paddingTopLeft, paddingBottomRight } = overlayPadding();
    map.fitBounds(CZ_BOUNDS, { paddingTopLeft, paddingBottomRight: isDesktop() ? paddingBottomRight : [12, 80] });

    L.control.attribution({ position: "bottomright", prefix: "Data: adsb.lol (ODbL)" }).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);
    new MutedTileLayer(TILE_URL, { maxZoom: 18, attribution: TILE_ATTRIBUTION }).addTo(map);

    const layer = new PlaneLayer({ labelZoom: LABEL_ZOOM, groundLabelZoom: GROUND_LABEL_ZOOM }).addTo(map);
    planes.current = layer;
    map.planeAt = (point) => layer.planeAt(point); // MapLayers: a tap on a plane isn't a tap on a zone
    const box = map.getContainer();
    const zoomClasses = () => {
      const z = map.getZoom();
      box.classList.toggle("z-labels", z >= LABEL_ZOOM); // still used by Flights.jsx far markers
      box.classList.toggle("z-ground-labels", z >= GROUND_LABEL_ZOOM);
    };
    zoomClasses();
    map.on("zoomend", zoomClasses);
    map.on("click", (e) => onSelectRef.current(layer.planeAt(e.containerPoint)));

    // Desktop: callsign tooltip and pointer cursor over a plane.
    if (window.matchMedia("(hover: hover)").matches) {
      const tip = L.tooltip({ direction: "top", offset: [0, -14], className: "ac-tip" });
      let frame = 0;
      map.on("mousemove", (e) => {
        if (frame) return;
        frame = requestAnimationFrame(() => {
          frame = 0;
          const hex = layer.planeAt(e.containerPoint, 14);
          box.style.cursor = hex ? "pointer" : "";
          const a = hex && layer.planes.get(hex)?.a;
          if (a) tip.setLatLng(layer.position(hex)).setContent(callsign(a)).addTo(map);
          else tip.remove();
        });
      });
      map.on("mouseout movestart", () => tip.remove());
    }

    mapRef.current = map;
    onReady?.(map);
    return () => {
      onReady?.(null);
      map.remove();
      mapRef.current = null;
      planes.current = null;
    };
  }, []);

  // Latest snapshot; planes glide to it unless battery saver is on.
  useEffect(() => {
    planes.current?.setAircraft(aircraft, !el.current.closest(".saver"));
  }, [aircraft]);

  // Map filter hook: dim planes the filter (Filters.jsx via state.jsx) doesn't match. `dimmed` = Set of hex or null.
  useEffect(() => {
    planes.current?.setDimmed(dimmed);
  }, [dimmed]);

  // Highlight the selected plane and keep it out from under the panel.
  useEffect(() => {
    planes.current?.setSelected(selectedHex);
    const pos = selectedHex && planes.current?.position(selectedHex);
    if (pos) mapRef.current.panInside(pos, overlayPadding());
  }, [selectedHex]);

  return <div ref={el} className="map" />;
}
