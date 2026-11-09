import { useEffect, useRef } from "react";
import L from "leaflet";
import { AIRCRAFT_ICONS, EMERGENCY_SQUAWKS, aircraftKind, altitudeHue, callsign, isGround } from "./aircraft.js";

const CZ_BOUNDS = [[48.55, 12.09], [51.06, 18.86]];

// OSM tiles need no key; styles.css mutes them (and inverts them in dark mode).
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

// Plain Leaflet in refs; no wrapper library. Markers are created once per aircraft and updated in place.
// Feature overlays get the Leaflet instance through onReady (see state.jsx), so they never need to edit this file.
// From this zoom up, planes carry a small data label (selected plane always does).
// Where labels would overlap, only the most important one stays (see declutter).
const LABEL_ZOOM = 7;
const GROUND_LABEL_ZOOM = 13; // planes and vehicles on the ground crowd the apron, so label them later
const fmt = (n) => Math.round(n).toLocaleString("cs-CZ");

// Second label line: altitude, speed and a climb/descent arrow, metric.
function labelInfo(a) {
  if (isGround(a)) return "na zemi";
  const parts = [];
  if (typeof a.alt_baro === "number") {
    const arrow = a.baro_rate > 500 ? "↑" : a.baro_rate < -500 ? "↓" : "";
    parts.push(`${arrow}${fmt(Math.round((a.alt_baro * 0.3048) / 10) * 10)} m`);
  }
  if (a.gs != null) parts.push(`${fmt(a.gs * 1.852)} km/h`);
  return parts.join(" · ");
}

// Which label wins when two overlap: selected, emergency, military, heavy, then higher planes.
function labelPriority(a, sel) {
  let p = (a.alt_baro === "ground" ? 0 : 20 + Math.min(a.alt_baro || 0, 45000) / 1000);
  if (sel) p += 1000;
  if (a.squawk in EMERGENCY_SQUAWKS) p += 500;
  if (a.dbFlags & 1) p += 100;
  if (aircraftKind(a) === "heavy") p += 30;
  return p;
}

// Label box size estimated from its text (styles.css .ac-lbl: 11.5px font, 7px padding, 2 lines).
// Estimating instead of measuring keeps declutter free of layout reads, which made the map stutter on phones.
function labelSize(a) {
  const top = callsign(a).length * 7.4 + (a.t ? a.t.length * 6.6 + 4 : 0);
  const info = labelInfo(a);
  return { w: Math.max(top, info.length * 6.4) + 16, h: info ? 36 : 21 };
}

// Greedy label placement: best label first, skip any that would overlap one already placed.
// Only cheap reads (classes, positions) and only class writes that change something.
function declutter(map, markers, selectedHex) {
  const box = map.getContainer();
  const on = box.classList.contains("z-labels") && !box.classList.contains("labels-off");
  const groundOn = box.classList.contains("z-ground-labels");
  const view = map.getBounds().pad(0.3);
  const items = [];
  for (const [hex, entry] of markers) {
    const el = entry.marker.getElement();
    if (!el) continue;
    const lbl = el.lastChild;
    const sel = hex === selectedHex;
    const shown = sel || (on && !el.firstChild.classList.contains("ac--dim") && (groundOn || !isGround(entry.a)));
    if (!shown || !view.contains(entry.marker.getLatLng())) {
      if (lbl.classList.contains("ac-lbl--hide")) lbl.classList.remove("ac-lbl--hide");
      continue;
    }
    // Small bonus for labels already shown, so they don't flicker between snapshots.
    const keep = lbl.classList.contains("ac-lbl--hide") ? 0 : 5;
    const p = map.latLngToLayerPoint(entry.marker.getLatLng());
    // Icon is 32×32 centred on the point; the label sits at left 29px, top 3px (styles.css).
    items.push({ lbl, sel, prio: labelPriority(entry.a, sel) + keep, r: { x: p.x + 13, y: p.y - 13, ...labelSize(entry.a) } });
  }
  items.sort((x, y) => y.prio - x.prio);
  const placed = [];
  for (const { lbl, sel, r } of items) {
    const hit = !sel && placed.some((q) => r.x < q.x + q.w + 2 && q.x < r.x + r.w + 2 && r.y < q.y + q.h + 2 && q.y < r.y + r.h + 2);
    if (hit !== lbl.classList.contains("ac-lbl--hide")) lbl.classList.toggle("ac-lbl--hide", hit);
    if (!hit) placed.push(r);
  }
}

export default function Map({ aircraft, selectedHex, onSelect, onReady, dimmed }) {
  const el = useRef(null);
  const mapRef = useRef(null);
  const markers = useRef(new globalThis.Map()); // hex -> { marker, rot }
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const selRef = useRef(selectedHex);
  selRef.current = selectedHex;

  useEffect(() => {
    const map = L.map(el.current, { zoomControl: false, attributionControl: false });
    const { paddingTopLeft, paddingBottomRight } = overlayPadding();
    map.fitBounds(CZ_BOUNDS, { paddingTopLeft, paddingBottomRight: isDesktop() ? paddingBottomRight : [12, 80] });

    L.control.attribution({ position: "bottomright", prefix: "Data: adsb.lol (ODbL)" }).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);
    L.tileLayer(TILE_URL, { maxZoom: 18, attribution: TILE_ATTRIBUTION }).addTo(map);

    // Planes glide between 10 s snapshots; pause gliding while Leaflet repositions on zoom.
    const box = map.getContainer();
    box.classList.add("glide");
    // Smaller planes when zoomed out, so busy airspace doesn't turn into a blob.
    const sizeIcons = () => {
      const z = map.getZoom();
      box.style.setProperty("--ac", `${z <= 6 ? 15 : z === 7 ? 18 : 22}px`);
      box.classList.toggle("z-labels", z >= LABEL_ZOOM);
      box.classList.toggle("z-ground-labels", z >= GROUND_LABEL_ZOOM);
    };
    sizeIcons();
    map.on("zoomstart", () => box.classList.remove("glide"));
    map.on("zoomend", () => {
      sizeIcons();
      requestAnimationFrame(() => requestAnimationFrame(() => box.classList.add("glide")));
    });
    map.on("click", () => onSelectRef.current(null));
    // moveend also follows every zoom; labelschange is fired by MapLayers.
    map.on("moveend labelschange", () => declutter(map, markers.current, selRef.current));

    mapRef.current = map;
    onReady?.(map);
    return () => {
      onReady?.(null);
      map.remove();
      mapRef.current = null;
      markers.current.clear();
    };
  }, []);

  // Sync markers with the latest snapshot.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const seen = new Set();

    for (const a of aircraft) {
      seen.add(a.hex);
      let entry = markers.current.get(a.hex);
      if (!entry) {
        const marker = L.marker([a.lat, a.lon], {
          icon: L.divIcon({ className: "ac-marker", html: `<div class="ac"></div><div class="ac-lbl"><b></b> <small></small><span></span></div>`, iconSize: [32, 32] }),
          keyboard: false,
        })
          .bindTooltip("", { direction: "top", offset: [0, -14], className: "ac-tip" })
          .on("click", () => onSelectRef.current(a.hex))
          .addTo(map);
        entry = { marker, rot: a.track ?? 0, a };
        markers.current.set(a.hex, entry);
      } else {
        entry.marker.setLatLng([a.lat, a.lon]);
        // Rotate the short way round (350° -> 10° turns 20°, not 340°).
        if (a.track != null) entry.rot += ((a.track - entry.rot + 540) % 360) - 180;
      }

      entry.a = a;
      const node = entry.marker.getElement()?.firstChild;
      const lbl = node?.nextSibling;
      // Icon by kind of aircraft; the category can arrive a snapshot later, so re-check each time.
      const kind = aircraftKind(a);
      if (node && node.dataset.kind !== kind) {
        node.innerHTML = AIRCRAFT_ICONS[kind];
        node.dataset.kind = kind;
        node.classList.toggle("ac--heavy", kind === "heavy");
      }
      if (lbl) {
        // textContent only: callsigns and types come from external data.
        const [name, type, info] = lbl.querySelectorAll("b, small, span");
        name.textContent = callsign(a);
        type.textContent = a.t || "";
        info.textContent = labelInfo(a);
      }
      if (node) {
        const hue = altitudeHue(a);
        node.style.setProperty("--rot", `${entry.rot}deg`);
        node.style.setProperty("--h", hue ?? 0);
        node.classList.toggle("ac--ground", isGround(a));
        node.classList.toggle("ac--emg", a.squawk in EMERGENCY_SQUAWKS);
      }
      entry.marker.setTooltipContent(callsign(a));
    }

    for (const [hex, entry] of markers.current) {
      if (!seen.has(hex)) {
        entry.marker.remove();
        markers.current.delete(hex);
      }
    }
  }, [aircraft]);


  // Map filter hook: dim planes the filter (Filters.jsx via state.jsx) doesn't match. `dimmed` = Set of hex or null.
  useEffect(() => {
    for (const [hex, { marker }] of markers.current) marker.getElement()?.firstChild.classList.toggle("ac--dim", Boolean(dimmed?.has(hex)));
  }, [aircraft, dimmed]);

  // Highlight the selected plane and keep it out from under the panel.
  useEffect(() => {
    for (const [hex, { marker }] of markers.current) {
      const sel = hex === selectedHex;
      marker.getElement()?.firstChild.classList.toggle("ac--sel", sel);
      marker.setZIndexOffset(sel ? 10000 : 0);
    }
    const entry = markers.current.get(selectedHex);
    if (entry) mapRef.current.panInside(entry.marker.getLatLng(), overlayPadding());
  }, [selectedHex]);

  // Last effect, so it sees the dim/selection classes set above. Only when the data, filter or selection change.
  useEffect(() => {
    if (mapRef.current) declutter(mapRef.current, markers.current, selectedHex);
  }, [aircraft, dimmed, selectedHex]);

  return <div ref={el} className="map" />;
}
