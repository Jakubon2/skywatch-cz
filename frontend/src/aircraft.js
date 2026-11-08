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
