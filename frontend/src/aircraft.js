// Shared helpers for aircraft display.

export const EMERGENCY_SQUAWKS = {
  7700: "Nouze",
  7600: "Ztráta spojení",
  7500: "Únos – často jde o chybu nebo test, neověřeno",
};

export const isGround = (a) => a.alt_baro === "ground";

// Altitude -> hue: orange near the ground, through green and blue, violet at cruise.
export function altitudeHue(a) {
  if (isGround(a) || typeof a.alt_baro !== "number") return null;
  const alt = Math.max(0, Math.min(a.alt_baro, 40000));
  return Math.round(30 + (alt / 40000) * 250);
}

export const callsign = (a) => (a.flight || "").trim() || a.r || a.hex.toUpperCase();

export const PLANE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5c.9 0 1.4 1 1.4 2.2v5.4l8 4.8v2.2l-8-2.5v4.6l2.3 1.7v1.7L12 20.8l-3.7.8v-1.7l2.3-1.7v-4.6l-8 2.5v-2.2l8-4.8V3.7c0-1.2.5-2.2 1.4-2.2z"/></svg>';

// ---- Icon per kind of aircraft, from the ADS-B emitter category the aircraft broadcasts ----
// All shapes point up (nose at the top) in a 24x24 box; markers rotate them by track.
const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;

export const AIRCRAFT_ICONS = {
  airliner: PLANE_SVG,
  heavy: PLANE_SVG, // same shape, drawn larger (.ac--heavy)
  jet: svg(
    "M12 1.8c.7 0 1.1.9 1.1 2v5.6l6.9 5v1.8l-6.9-2.4v4.6l2.6 2v1.5L12 21l-3.7.9v-1.5l2.6-2v-4.6L4 16.2v-1.8l6.9-5V3.8c0-1.1.4-2 1.1-2zM8.6 13.6h1.6v3.6H8.6zM13.8 13.6h1.6v3.6h-1.6z",
  ),
  light: svg(
    "M12 2.5c.8 0 1.2.8 1.2 1.8V8H22v2.6h-8.8l-.5 7.6h3.6v2.3h-3.7L12 22l-.6-1.5H7.7v-2.3h3.6l-.5-7.6H2V8h8.8V4.3c0-1 .4-1.8 1.2-1.8z",
  ),
  heli: svg(
    "M12 5.5c1.9 0 3 1.6 3 3.8 0 2.4-1.2 4.2-2.3 4.8V20h1.8v1.4H9.5V20h1.8v-5.9C10.2 13.5 9 11.7 9 9.3c0-2.2 1.1-3.8 3-3.8zM3.2 2.6l.9-.9 16.7 16.7-.9.9zM19.9 1.7l.9.9L4.1 19.3l-.9-.9z",
  ),
  glider: svg(
    "M12 3c.6 0 .9.7.9 1.6v4.6H23v1.3l-10.1.9-.4 7.6h2.6v1.4h-2.7L12 21.5l-.4-1.1H8.9V19h2.6l-.4-7.6L1 10.5V9.2h10.1V4.6c0-.9.3-1.6.9-1.6z",
  ),
  balloon: svg("M12 3.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13zM10.4 17.5h3.2v3h-3.2z"),
  vehicle: svg("M8.5 5h7a1.5 1.5 0 0 1 1.5 1.5v11a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 7 17.5v-11A1.5 1.5 0 0 1 8.5 5z"),
};

// readsb `category`: A1 light, A2 small (bizjets, regionals), A3/A4 large, A5 heavy, A7 rotorcraft,
// B1 glider, B2 balloon, B4 ultralight, B6 drone, C1–C3 ground vehicles/obstacles. Unknown -> airliner.
const KIND_BY_CATEGORY = {
  A1: "light", A2: "jet", A3: "airliner", A4: "airliner", A5: "heavy", A6: "jet", A7: "heli",
  B1: "glider", B2: "balloon", B4: "light", B6: "light", C1: "vehicle", C2: "vehicle", C3: "vehicle",
};

export const aircraftKind = (a) => KIND_BY_CATEGORY[a.category] || "airliner";
